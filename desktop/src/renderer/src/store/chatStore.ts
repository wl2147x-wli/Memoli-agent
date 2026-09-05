import { create } from 'zustand'
import apiClient from '../api/client'
import { useWorkspaceStore } from './workspaceStore'
import { sessionOwner } from './sessionStore'
import { cfgFor } from './sessionSettingsStore'
import { findAgent } from './agentStore'
import { notifyRunDone } from '../lib/taskNotify'
import { parseAttachmentMarkers } from '../lib/fileKind'
import type { Artifact, ChatMessage, MessageStep, Attachment, StreamEvent, HistoryMessage, AgentBadge } from '../types'

/**
 * Per-session chat state. Supports parallel sessions: each session keeps its
 * own message list and active stream, so switching sessions never interrupts a
 * background run. The active EventSource lives in `streams` (outside React).
 */

interface SessionRuntime {
  messages: ChatMessage[]
  isStreaming: boolean
  requestId: string | null
  // 历史分页
  historyPage: number
  historyHasMore: boolean
  historyLoaded: boolean
}

interface ChatState {
  sessions: Record<string, SessionRuntime>

  getSession: (sid: string) => SessionRuntime
  ensureSession: (sid: string) => void

  send: (sid: string, text: string, attachments: Attachment[]) => Promise<void>
  cancel: (sid: string) => Promise<void>
  regenerate: (sid: string, botMessageId: string) => Promise<void>
  editUserMessage: (sid: string, messageId: string) => { text: string; attachments: Attachment[] } | null
  deleteMessage: (sid: string, userSeq: number, cascade: boolean) => Promise<void>

  loadHistory: (sid: string, page?: number) => Promise<void>
  clearContext: (sid: string) => Promise<boolean>
  clearLocal: (sid: string) => void

  // 附加在 SSE 外部轮询的服务器推送消息（调度程序/推送）
  // 流。通过 requestId 进行重复数据删除，因此屏幕上已有的回复不会重复。
  receivePush: (sid: string, content: string, requestId?: string) => boolean
}

// EventSource 实例保留在存储之外（不可序列化）。
const streams: Record<string, EventSource> = {}

const EMPTY: SessionRuntime = {
  messages: [],
  isStreaming: false,
  requestId: null,
  historyPage: 0,
  historyHasMore: false,
  historyLoaded: false,
}

function uid(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
}

/**
 * History keeps the English cancel marker for the LLM; strip it for display so
 * the bubble shows a clean answer + a dedicated "cancelled" badge instead.
 */
function stripCancelMarker(text: string): string {
  if (!text) return text
  return text
    .replace(/_\(Cancelled by user\)_/g, '')
    .replace(/_\(Cancelled\)_/g, '')
    .trim()
}

/**
 * Everyone addressable in a conversation, owner first: the owner plus any
 * invited teammates. Empty outside a group chat.
 */
function sessionRoster(sid: string): AgentBadge[] {
  const team = cfgFor(sid)?.team
  if (!team || !team.members?.length) return []
  const roster: AgentBadge[] = [team.owner]
  for (const m of team.members) {
    if (!roster.some((a) => a.id === m.id)) roster.push(m)
  }
  return roster
}

/**
 * The teammate a message hands the turn to, or '' for nobody. Mirrors the
 * server's rule: only a leading mention counts (naming someone mid-sentence is
 * talking *about* them), matched by display name or id, longest label first so
 * a name containing another name still resolves to the one written.
 */
function addressedAgentId(text: string, roster: AgentBadge[]): string {
  const stripped = (text || '').replace(/^\s+/, '')
  if (!stripped.startsWith('@') || roster.length < 2) return ''
  const labels: Array<[string, string]> = []
  for (const a of roster) {
    for (const label of [a.name, a.id]) {
      if (label) labels.push([String(label), a.id])
    }
  }
  labels.sort((x, y) => y[0].length - x[0].length)
  for (const [label, id] of labels) {
    const re = new RegExp(`^@${label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?=[\\s，,：:、]|$)`, 'i')
    if (re.test(stripped)) return id
  }
  return ''
}

const SUBSTEP_ARGS_CHARS = 90

/** Tool arguments on one line, for a step in a list of dozens. */
function summarizeArgs(args?: Record<string, unknown>): string {
  if (!args || typeof args !== 'object') return ''
  const joined = Object.entries(args)
    .map(([key, value]) => `${key}=${typeof value === 'object' ? JSON.stringify(value) : String(value)}`)
    .join(', ')
  return joined.length > SUBSTEP_ARGS_CHARS ? joined.slice(0, SUBSTEP_ARGS_CHARS) + '…' : joined
}

/**
 * Rebuild attachments from `send`-tool results persisted in the message steps.
 * SSE `file_to_send` events aren't stored, so on history reload the only record
 * of a sent image/file is the tool result JSON. Mirrors the web console's
 * `_renderSentFileFromToolResult` so media survives an app restart.
 */
function attachmentsFromSteps(steps: MessageStep[]): Attachment[] {
  const out: Attachment[] = []
  for (const s of steps) {
    if (s.type !== 'tool' || !s.result) continue
    let payload: Record<string, unknown>
    try {
      payload = typeof s.result === 'string' ? JSON.parse(s.result) : (s.result as unknown as Record<string, unknown>)
    } catch {
      continue
    }
    if (!payload || payload.type !== 'file_to_send') continue
    const rawPath = (payload.path as string) || ''
    const url = (payload.url as string) || ''
    if (!rawPath && !url) continue
    const isRemote = url.toLowerCase().startsWith('http://') || url.toLowerCase().startsWith('https://')
    // 本地文件通过 /api/file 提供；直接使用远程 URL。
    const previewUrl = isRemote
      ? url
      : rawPath.toLowerCase().startsWith('http')
        ? rawPath
        : apiClient.getServeFileUrl(rawPath)
    const kind = (payload.file_type as string) || 'file'
    const fileType: Attachment['file_type'] =
      kind === 'image' ? 'image' : kind === 'video' ? 'video' : 'file'
    out.push({
      file_path: previewUrl,
      file_name: (payload.file_name as string) || 'file',
      file_type: fileType,
      preview_url: previewUrl,
      abs_path: isRemote ? undefined : rawPath,
    })
  }
  return out
}

/** Convert a backend history message into a UI ChatMessage. */
function historyToMessage(m: HistoryMessage): ChatMessage {
  if (m.role === 'user') {
    // 历史记录仅保留提示文本，因此附件芯片必须是
    // 从附加的 `[label: path]` 标记中恢复。
    const { text, attachments } = parseAttachmentMarkers(m.content)
    return {
      id: uid('user'),
      role: 'user',
      content: text,
      timestamp: m.created_at,
      userSeq: m._seq,
      attachments,
    }
  }

  // 后端将最终答案存储为 `content` 和 LAST
  // `content` 步骤。删除尾随内容步骤，使其不被渲染
  // 两次（与 Web 控制台的 renderStepsHtml 逻辑匹配）。
  const raw = m.steps || []
  let lastContentIdx = -1
  for (let i = raw.length - 1; i >= 0; i--) {
    if (raw[i].type === 'content') {
      lastContentIdx = i
      break
    }
  }
  const steps: MessageStep[] = raw
    .filter((_, i) => i !== lastContentIdx)
    .map((s) => ({ ...s }))
  const finalContent = m.content || (lastContentIdx >= 0 ? raw[lastContentIdx].content || '' : '')
  const attachments = attachmentsFromSteps(raw)
  // 工件由后端重建，后端仅知道工作区根目录。
  const artifacts = m.artifacts || []

  return {
    id: uid('assistant'),
    role: 'assistant',
    content: finalContent,
    timestamp: m.created_at,
    steps,
    reasoning: m.reasoning,
    kind: m.kind,
    extras: m.extras,
    botSeq: m._seq,
    attachments: attachments.length > 0 ? attachments : undefined,
    artifacts: artifacts.length > 0 ? artifacts : undefined,
  }
}

export const useChatStore = create<ChatState>((set, get) => {
  // --- 助手在单个会话上进行不可更改的操作 ---
  const patchSession = (sid: string, patch: Partial<SessionRuntime>) =>
    set((st) => ({
      sessions: { ...st.sessions, [sid]: { ...(st.sessions[sid] || EMPTY), ...patch } },
    }))

  const patchMessages = (sid: string, fn: (msgs: ChatMessage[]) => ChatMessage[]) =>
    set((st) => {
      const cur = st.sessions[sid] || EMPTY
      return { sessions: { ...st.sessions, [sid]: { ...cur, messages: fn(cur.messages) } } }
    })

  const updateMsg = (sid: string, id: string, fn: (m: ChatMessage) => ChatMessage) =>
    patchMessages(sid, (msgs) => msgs.map((m) => (m.id === id ? fn(m) : m)))

  /** Attach an EventSource for a request and wire all SSE events to a bot message. */
  const attachStream = (sid: string, requestId: string, botId: string) => {
    const es = apiClient.createSSEStream(requestId)
    streams[sid] = es
    let tailTimer: ReturnType<typeof setTimeout> | null = null
    // 设置用户启动的取消，以便尾随错误事件不会触发
    // 虚假的“任务失败”通知。
    let userCancelled = false

    const closeStream = () => {
      if (tailTimer) {
        clearTimeout(tailTimer)
        tailTimer = null
      }
      es.close()
      if (streams[sid] === es) delete streams[sid]
    }

    // 将回合标记为完成：UI 立即再次变为交互式。
    const completeTurn = () => {
      patchSession(sid, { isStreaming: false, requestId: null })
      updateMsg(sid, botId, (m) => ({ ...m, isStreaming: false }))
    }

    const finishStream = () => {
      completeTurn()
      closeStream()
    }

    es.onmessage = (event) => {
      let data: StreamEvent
      try {
        data = JSON.parse(event.data)
      } catch {
        return // 保活
      }

      switch (data.type) {
        case 'reasoning':
          updateMsg(sid, botId, (m) => ({ ...m, reasoning: (m.reasoning || '') + (data.content || '') }))
          break

        case 'delta':
          updateMsg(sid, botId, (m) => ({ ...m, content: m.content + (data.content || '') }))
          break

        case 'message_end':
          // 当工具调用随后时，将累积的文本冻结为内容步骤，
          // 镜像 Web 控制台的交错步骤模型。
          if (data.has_tool_calls) {
            updateMsg(sid, botId, (m) => {
              if (!m.content.trim()) return m
              const steps = [...(m.steps || []), { type: 'content' as const, content: m.content.trim() }]
              return { ...m, steps, content: '' }
            })
          }
          break

        case 'tool_start':
          updateMsg(sid, botId, (m) => {
            // 将任何推理纳入思考步骤
            const steps = [...(m.steps || [])]
            if (m.reasoning && m.reasoning.trim()) {
              steps.push({ type: 'thinking', content: m.reasoning.trim() })
            }
            steps.push({
              type: 'tool',
              id: data.tool_call_id,
              name: data.tool,
              arguments: data.arguments,
              status: 'running',
            })
            return { ...m, steps, reasoning: '', content: '' }
          })
          break

        case 'tool_progress':
          updateMsg(sid, botId, (m) => ({
            ...m,
            steps: (m.steps || []).map((s) =>
              s.type === 'tool' && s.id === data.tool_call_id ? { ...s, result: data.content } : s
            ),
          }))
          break

        case 'tool_end':
          updateMsg(sid, botId, (m) => ({
            ...m,
            steps: (m.steps || []).map((s) =>
              s.type === 'tool' && s.id === data.tool_call_id
                ? {
                    ...s,
                    status: data.status,
                    result: data.result ?? s.result,
                    display: data.display ?? s.display,
                    execution_time: data.execution_time,
                    is_error: data.status !== 'success',
                    permission_denied: data.permission_denied,
                    permission_mode: data.permission_mode,
                  }
                : s
            ),
          }))
          break

        // 在子代理内部进行的工具调用，归档在该子代理的下
        // 以便可以跟踪其工作记录而不是猜测。
        // 步骤消失时被忽略：子代理在超时时取消
        // 继续下去，直到下一个检查点，以及之后报告的内容
        // 这描述了没有人在等待的工作。
        case 'subagent_step':
          if (!data.card_id || !data.step_id) break
          updateMsg(sid, botId, (m) => ({
            ...m,
            steps: (m.steps || []).map((s) => {
              if (s.type !== 'tool' || s.id !== data.card_id) return s
              const substeps = [...(s.substeps || [])]
              const at = substeps.findIndex((sub) => sub.id === data.step_id)
              if (at < 0) {
                if (data.phase !== 'start') return s
                substeps.push({
                  id: data.step_id!,
                  name: data.tool || 'tool',
                  args: summarizeArgs(data.arguments),
                  status: 'running',
                })
              } else {
                if (data.phase !== 'end') return s
                substeps[at] = {
                  ...substeps[at],
                  status: data.status || 'success',
                  execution_time: data.execution_time,
                  error: data.error,
                }
              }
              return { ...s, substeps }
            }),
          }))
          break

        case 'image':
        case 'file': {
          // 由 `send` 工具推送的媒体 (file_to_send)。 `content` 是
          // 后端 /api/file?path=... URL 或传递的 http(s) URL。
          const url = data.content || ''
          if (!url) break
          // 更喜欢后端的具体媒体类型（图像/视频/...）；
          // 回退到粗略的 SSE 事件类型。
          const kind = data.file_type || (data.type === 'image' ? 'image' : 'file')
          const attType: Attachment['file_type'] =
            kind === 'image' ? 'image' : kind === 'video' ? 'video' : 'file'
          const att: Attachment = {
            file_path: url,
            file_name: data.file_name || 'file',
            file_type: attType,
            preview_url: url,
            abs_path: data.abs_path,
          }
          updateMsg(sid, botId, (m) => ({
            ...m,
            attachments: [...(m.attachments || []), att],
          }))
          break
        }

        case 'artifact': {
          if (!data.abs_path) break
          const artifact: Artifact = {
            abs_path: data.abs_path,
            rel_path: data.rel_path || data.file_name || '',
            file_name: data.file_name || '',
            kind: data.kind || 'file',
            previewable: !!data.previewable,
            size: data.size || 0,
            raw_url: data.raw_url || '',
            preview_url: data.preview_url || '',
          }
          updateMsg(sid, botId, (m) =>
            (m.artifacts || []).some((a) => a.abs_path === artifact.abs_path)
              ? m
              : { ...m, artifacts: [...(m.artifacts || []), artifact] }
          )
          useWorkspaceStore.getState().addTurnArtifact(artifact)
          break
        }

        case 'cancelled':
          userCancelled = true
          updateMsg(sid, botId, (m) => ({ ...m, isCancelled: true }))
          break

        case 'done':
          updateMsg(sid, botId, (m) => {
            const next = stripCancelMarker(data.content || m.content)
            return {
              ...m,
              content: next,
              botSeq: data.bot_seq ?? m.botSeq,
              isStreaming: false,
            }
          })
          // 回填前面的用户消息的序列以进行编辑/删除
          if (data.user_seq != null) {
            patchMessages(sid, (msgs) => {
              const idx = msgs.findIndex((m) => m.id === botId)
              for (let i = idx - 1; i >= 0; i--) {
                if (msgs[i].role === 'user') {
                  msgs[i] = { ...msgs[i], userSeq: data.user_seq }
                  break
                }
              }
              return [...msgs]
            })
          }
          // 答案是最终的：立即释放 UI（不要等待 onerror）。
          completeTurn()
          notifyRunDone(sid, 'done', data.content || '')
          useWorkspaceStore.getState().maybeAutoOpen()
          // 后端保持流打开一段短尾（例如，TTS 音频通过
          // 语音_附加）。如果没有其他东西到达，我们自己关闭它。
          if (tailTimer) clearTimeout(tailTimer)
          tailTimer = setTimeout(closeStream, 1500)
          break

        case 'voice_attach':
          if (data.audio_url) {
            updateMsg(sid, botId, (m) => ({
              ...m,
              extras: { ...(m.extras || {}), audio: data.audio_url },
            }))
          }
          finishStream()
          break

        case 'error':
          updateMsg(sid, botId, (m) => ({ ...m, error: data.message || 'stream error', isStreaming: false }))
          if (!userCancelled) notifyRunDone(sid, 'error', data.message || 'stream error')
          finishStream()
          break
      }
    }

    es.onerror = () => {
      // 流关闭（通常是 `done`/tail 之后的正常结束）。完成。
      finishStream()
    }
  }

  return {
    sessions: {},

    getSession: (sid) => get().sessions[sid] || EMPTY,

    ensureSession: (sid) => {
      if (!get().sessions[sid]) patchSession(sid, { ...EMPTY })
    },

    send: async (sid, text, attachments) => {
      const userMsg: ChatMessage = {
        id: uid('user'),
        role: 'user',
        content: text,
        timestamp: Date.now() / 1000,
        attachments: attachments.length ? attachments : undefined,
      }
      const botId = uid('assistant')
      // 对话的所有者会回答，除非向队友发出了
      // 引导@提及（群聊）。将扬声器锁定在发送时的回复上
      // 因此，稍后的代理切换永远不会重写历史记录中的发言者。
      // 单代理模式下为空，因此这些回复保留产品徽标
      // 和以前一样。
      const owner = sessionOwner(sid)
      const addressed = owner ? addressedAgentId(text, sessionRoster(sid)) : ''
      const speakerAgentId = addressed || owner
      const botMsg: ChatMessage = {
        id: botId,
        role: 'assistant',
        content: '',
        timestamp: Date.now() / 1000,
        steps: [],
        isStreaming: true,
        extras: speakerAgentId ? { agent_id: speakerAgentId } : undefined,
      }
      patchMessages(sid, (msgs) => [...msgs, userMsg, botMsg])
      patchSession(sid, { isStreaming: true })
      useWorkspaceStore.getState().resetTurnArtifacts()

      try {
        const res = await apiClient.sendMessage(sid, text, {
          stream: true,
          attachments: attachments.length ? attachments : undefined,
          agentId: owner || undefined,
          speakerAgentId: addressed && addressed !== owner ? addressed : undefined,
        })
        // 服务器是决定轮到谁的权力；重新绘制现场
        // 如果解决问题的方式与我们猜测的不同，则会出现气泡。
        if (owner && res.status === 'success') {
          const speaker = res.speaker || owner
          if (speaker !== speakerAgentId && findAgent(speaker)) {
            updateMsg(sid, botId, (m) => ({ ...m, extras: { ...(m.extras || {}), agent_id: speaker } }))
          }
        }
        if (res.status === 'success' && res.stream && res.request_id) {
          patchSession(sid, { requestId: res.request_id })
          attachStream(sid, res.request_id, botId)
        } else if (res.inline_reply) {
          updateMsg(sid, botId, (m) => ({ ...m, content: res.inline_reply || '', isStreaming: false }))
          patchSession(sid, { isStreaming: false })
        } else {
          updateMsg(sid, botId, (m) => ({ ...m, error: 'send failed', isStreaming: false }))
          patchSession(sid, { isStreaming: false })
        }
      } catch (err) {
        updateMsg(sid, botId, (m) => ({ ...m, error: `${err}`, isStreaming: false }))
        patchSession(sid, { isStreaming: false })
      }
    },

    cancel: async (sid) => {
      const s = get().sessions[sid]
      if (!s?.requestId) return
      // 乐观地立即停止UI：标记最后一个助手气泡
      // 已取消，释放输入，并拆除本地 SSE 流，因此不会
      // 用户点击停止后进一步呈现增量。后端仍然得到
      // 用于中止正在运行的代理任务的取消请求。
      patchMessages(sid, (msgs) => {
        for (let i = msgs.length - 1; i >= 0; i--) {
          if (msgs[i].role === 'assistant') {
            msgs[i] = { ...msgs[i], isCancelled: true, isStreaming: false }
            break
          }
        }
        return [...msgs]
      })
      patchSession(sid, { isStreaming: false, requestId: null })
      const es = streams[sid]
      if (es) {
        es.close()
        delete streams[sid]
      }
      try {
        await apiClient.cancel({ requestId: s.requestId, sessionId: sid })
      } catch {
        /* 忽略 */
      }
    },

    regenerate: async (sid, botMessageId) => {
      const s = get().sessions[sid] || EMPTY
      const idx = s.messages.findIndex((m) => m.id === botMessageId)
      if (idx < 0) return
      // 找到产生此机器人回复的用户消息
      let userMsg: ChatMessage | null = null
      for (let i = idx - 1; i >= 0; i--) {
        if (s.messages[i].role === 'user') {
          userMsg = s.messages[i]
          break
        }
      }
      if (!userMsg) return
      // 删除后端的开启（通过用户的序列）然后重新发送
      if (userMsg.userSeq != null) {
        try {
          await apiClient.deleteMessage({
            sessionId: sid,
            userSeq: userMsg.userSeq,
            deleteUser: true,
            cascade: true,
            agentId: sessionOwner(sid) || undefined,
          })
        } catch {
          /* 忽略 */
        }
      }
      // 从 idx- 本地删除 user+bot 消息？ ：从用户消息中删除
      const userIdx = s.messages.indexOf(userMsg)
      patchMessages(sid, (msgs) => msgs.slice(0, userIdx))
      await get().send(sid, userMsg.content, userMsg.attachments || [])
    },

    editUserMessage: (sid, messageId) => {
      const s = get().sessions[sid] || EMPTY
      const msg = s.messages.find((m) => m.id === messageId)
      if (!msg || msg.role !== 'user') return null
      const userIdx = s.messages.indexOf(msg)
      // 在后端级联删除本轮
      if (msg.userSeq != null) {
        apiClient
          .deleteMessage({
            sessionId: sid,
            userSeq: msg.userSeq,
            deleteUser: true,
            cascade: true,
            agentId: sessionOwner(sid) || undefined,
          })
          .catch(() => {})
      }
      patchMessages(sid, (msgs) => msgs.slice(0, userIdx))
      return { text: msg.content, attachments: msg.attachments || [] }
    },

    deleteMessage: async (sid, userSeq, cascade) => {
      try {
        await apiClient.deleteMessage({
          sessionId: sid,
          userSeq,
          deleteUser: true,
          cascade,
          agentId: sessionOwner(sid) || undefined,
        })
      } catch {
        /* 忽略 */
      }
      // 重新加载历史记录以反映服务器状态
      await get().loadHistory(sid, 1)
    },

    loadHistory: async (sid, page = 1) => {
      try {
        const res = await apiClient.getHistory(sid, page, 20, sessionOwner(sid) || undefined)
        const uiMsgs = res.messages.map(historyToMessage)
        patchSession(sid, {
          historyPage: res.page,
          historyHasMore: res.has_more,
          historyLoaded: true,
        })
        if (page === 1) {
          patchMessages(sid, () => uiMsgs)
        } else {
          // 旧页面：前置
          patchMessages(sid, (msgs) => [...uiMsgs, ...msgs])
        }
      } catch {
        patchSession(sid, { historyLoaded: true })
      }
    },

    clearContext: async (sid) => {
      try {
        const res = await apiClient.clearContext(sid, sessionOwner(sid) || undefined)
        if (res.status !== 'success') return false
        // 附加视觉分隔线，以便用户看到上下文已清除
        // （镜像 Web 控制台的上下文分隔符）。
        patchMessages(sid, (msgs) => [
          ...msgs,
          {
            id: uid('divider'),
            role: 'system',
            kind: 'divider',
            content: '',
            timestamp: Date.now() / 1000,
          },
        ])
        return true
      } catch {
        return false
      }
    },

    clearLocal: (sid) => {
      const es = streams[sid]
      if (es) {
        es.close()
        delete streams[sid]
      }
      patchSession(sid, { ...EMPTY })
    },

    receivePush: (sid, content, requestId) => {
      if (!content) return false
      const cur = get().sessions[sid]
      // 已通过 SSE 传输此请求，或已进行相同的推送
      // 着陆 - 不要渲染两次。
      if (requestId && cur?.messages.some((m) => m.pushRequestId === requestId)) {
        return false
      }
      const msg: ChatMessage = {
        id: uid('assistant'),
        role: 'assistant',
        content,
        timestamp: Date.now() / 1000,
        pushRequestId: requestId,
      }
      patchMessages(sid, (msgs) => [...msgs, msg])
      return true
    },
  }
})
