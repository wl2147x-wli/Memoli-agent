import React, { useState, useRef, useCallback, useEffect, useMemo, forwardRef, useImperativeHandle } from 'react'
import {
  Plus,
  Paperclip,
  Square,
  X,
  File as FileIcon,
  Loader2,
  Trash2,
  AtSign,
  Folder,
  Mic
} from 'lucide-react'
import { t } from '../i18n'
import type { Attachment, WorkspaceEntry, AgentBadge } from '../types'
import AgentAvatar from './AgentAvatar'
import { chatDraft } from '../store/draftStore'
import apiClient from '../api/client'
import { PaperPlaneIcon } from './icons'
import { WORKSPACE_DRAG_TYPE } from './FileTree'
import { iconFor, colorFor } from '../lib/fileKind'
import WorkspaceSelector from './WorkspaceSelector'
import PermissionSelector from './PermissionSelector'
import ModelSelector from './ModelSelector'
import AgentSelector from './AgentSelector'
import { useAgentStore, selectMultiAgent } from '../store/agentStore'
import Tooltip from './Tooltip'
import { useSessionSettingsStore, selectSharedConversation } from '../store/sessionSettingsStore'

export type ChatInputHandle = (text: string, attachments: Attachment[]) => void

// 语音输入需要MediaRecorder + getUserMedia；不在时隐藏麦克风。
const micSupported =
  typeof navigator !== 'undefined' &&
  !!navigator.mediaDevices?.getUserMedia &&
  typeof window.MediaRecorder !== 'undefined'

interface SlashCommand {
  cmd: string
  desc: string
  // 'new'/'clear' 运行本地操作； 'send'（默认）是一个完成
  // 作为普通消息发送到后端（由命令插件处理）。
  action?: 'new' | 'clear'
}

interface ChatInputProps {
  onSend: (message: string, attachments: Attachment[]) => void
  onNewChat: () => void
  onStop: () => void
  onClearContext: () => void
  isStreaming: boolean
  sessionId: string
}

const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(function ChatInput(
  { onSend, onNewChat, onStop, onClearContext, isStreaming, sessionId },
  ref
) {
  // 在挂载时恢复保存在 `chatDraft` 中的草稿（惰性初始化：第一个
  // 渲染必须已经显示它，否则下面的直写效果会
  // 用初始的空状态覆盖保存的草稿）。
  const [text, setText] = useState(() => chatDraft.text)
  const [attachments, setAttachments] = useState(() => chatDraft.attachments)
  // 仅当安装运行团队时才显示代理选择器。单代理
  // 客户永远不会看到它，保持作曲家行与以前相同。
  const multiAgent = useAgentStore(selectMultiAgent)
  // 群组对话有多个代理，每个代理都根据自己的模型进行回答，因此
  // 没有单一的每个会话模型可以固定 - 隐藏芯片，就像网络一样。
  const sharedConversation = useSessionSettingsStore(
    (s) => (s.sessionId === sessionId ? selectSharedConversation(s) : false)
  )
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [slashOpen, setSlashOpen] = useState(false)
  const [slashIndex, setSlashIndex] = useState(0)
  // `@` 选择器：代理提及（仅限群聊）首先出现，然后是工作区
  // 文件。座席在本地与会话名册进行匹配；文件是
  // 当用户输入时从后端获取。
  const [mentionItems, setMentionItems] = useState<WorkspaceEntry[]>([])
  const [mentionAgents, setMentionAgents] = useState<AgentBadge[]>([])
  const [mentionIndex, setMentionIndex] = useState(0)
  const mentionStartRef = useRef(-1)
  const mentionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // 当前群聊中可使用@寻址的队友。业主（
  // 一个已经回复的人）被排除在外——@将轮到其他人了。
  const activeAgentId = useAgentStore((s) => s.activeAgentId)
  const team = useSessionSettingsStore((s) => (s.sessionId === sessionId ? s.cfg?.team : undefined))
  const mentionRoster = useMemo<AgentBadge[]>(() => {
    if (!sharedConversation) return []
    const roster: AgentBadge[] = []
    for (const m of team?.members || []) {
      if (m.id !== activeAgentId && !roster.some((a) => a.id === m.id)) roster.push(m)
    }
    return roster
  }, [sharedConversation, activeAgentId, team])
  const composingRef = useRef(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // 语音输入：通过 MediaRecorder 录音，通过配置的 ASR 转录
  // 提供商（与 Web 控制台的麦克风按钮相同的流程）。
  const [micState, setMicState] = useState<'idle' | 'recording' | 'busy'>('idle')
  const [micError, setMicError] = useState('')
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const micStartedAtRef = useRef(0)
  const micErrorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const pickMicMimeType = () => {
    const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
    for (const m of candidates) {
      if (window.MediaRecorder.isTypeSupported?.(m)) return m
    }
    return ''
  }

  const flashMicError = (msg: string) => {
    setMicError(msg)
    if (micErrorTimerRef.current) clearTimeout(micErrorTimerRef.current)
    micErrorTimerRef.current = setTimeout(() => setMicError(''), 2500)
  }

  const stopMicStream = () => {
    streamRef.current?.getTracks().forEach((tr) => tr.stop())
    streamRef.current = null
  }

  const uploadRecording = async (blob: Blob) => {
    setMicState('busy')
    try {
      const res = await apiClient.voiceAsr(blob)
      if (res.status === 'success' && res.text) {
        const recognized = res.text
        // 将识别的文本填写到输入中，供用户查看和发送。
        setText((prev) => (prev ? (prev.endsWith(' ') ? prev : prev + ' ') + recognized : recognized))
        requestAnimationFrame(() => {
          const el = textareaRef.current
          if (el) {
            el.focus()
            el.selectionStart = el.selectionEnd = el.value.length
            autoSize(el)
          }
        })
      } else {
        flashMicError(res.message || t('mic_error'))
      }
    } catch (e) {
      flashMicError(`${t('mic_error')}: ${(e as Error).message}`)
    } finally {
      setMicState('idle')
    }
  }

  const startRecording = async () => {
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      // 显示具体的故障名称，例如被拒绝/缺少设备/不安全
      // 可以区分上下文，而不是总是指责权限。
      const err = e as Error
      flashMicError(`${t('mic_permission_denied')} (${err.name || 'Error'})`)
      return
    }
    streamRef.current = stream
    chunksRef.current = []
    const mimeType = pickMicMimeType()
    let recorder: MediaRecorder
    try {
      recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
    } catch (e) {
      stopMicStream()
      flashMicError(`${t('mic_error')}: ${(e as Error).message}`)
      return
    }
    mediaRecorderRef.current = recorder
    recorder.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) chunksRef.current.push(ev.data)
    }
    recorder.onstop = () => {
      stopMicStream()
      const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
      // 256 字节 ≈ 仅容器标头 — 视为意外点击。
      if (blob.size < 256) {
        setMicState('idle')
        flashMicError(t('mic_too_short'))
        return
      }
      uploadRecording(blob)
    }
    // timeslice=250ms：每 250ms 刷新一个块，这样非常短的点击就不会丢失。
    recorder.start(250)
    micStartedAtRef.current = Date.now()
    setMicState('recording')
  }

  const stopRecording = () => {
    const recorder = mediaRecorderRef.current
    if (!recorder || recorder.state === 'inactive') return
    // 给录音机一点时间，在快速点击时至少捕获一个块。
    const elapsed = Date.now() - micStartedAtRef.current
    const minMs = 350
    if (elapsed < minMs) {
      setTimeout(() => {
        if (recorder.state !== 'inactive') recorder.stop()
      }, minMs - elapsed)
    } else {
      recorder.stop()
    }
  }

  const toggleMic = () => {
    if (micState === 'recording') stopRecording()
    else if (micState === 'idle') startRecording()
  }

  // 卸载聊天页面后释放麦克风和计时器。
  useEffect(() => {
    return () => {
      const recorder = mediaRecorderRef.current
      if (recorder && recorder.state !== 'inactive') {
        recorder.onstop = null
        recorder.stop()
      }
      stopMicStream()
      if (micErrorTimerRef.current) clearTimeout(micErrorTimerRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 每会话模型/权限芯片遵循主动对话。
  useEffect(() => {
    useSessionSettingsStore.getState().refresh(sessionId)
    useSessionSettingsStore.getState().setOpenMenu(null)
  }, [sessionId])

  // 本地操作（“new”/“clear”）加上后端处理的完成命令
  // 命令插件（cow_cli/godcmd）。以空格结尾的命令需要一个
  // 参数，因此选择它们会将焦点放在输入而不是发送上。
  const slashCommands: SlashCommand[] = [
    { cmd: '/new', desc: t('slash_new'), action: 'new' },
    { cmd: '/clear', desc: t('slash_clear'), action: 'clear' },
    { cmd: '/help', desc: t('slash_help') },
    { cmd: '/status', desc: t('slash_status') },
    { cmd: '/context', desc: t('slash_context') },
    { cmd: '/compact', desc: t('slash_compact') },
    { cmd: '/skill list', desc: t('slash_skill_list') },
    { cmd: '/skill search ', desc: t('slash_skill_search') },
    { cmd: '/skill install ', desc: t('slash_skill_install') },
    { cmd: '/memory dream ', desc: t('slash_memory_dream') },
    { cmd: '/knowledge', desc: t('slash_knowledge') },
    { cmd: '/knowledge list', desc: t('slash_knowledge_list') },
    { cmd: '/install-browser', desc: t('slash_install_browser') },
    { cmd: '/config', desc: t('slash_config') },
    { cmd: '/cancel', desc: t('slash_cancel') },
    { cmd: '/logs', desc: t('slash_logs') },
    { cmd: '/version', desc: t('slash_version') },
  ]
  const filtered = slashCommands.filter((c) => c.cmd.startsWith(text.trim().toLowerCase()))

  // 调整文本区域的大小以适合其内容（单行 = 42px，上限为
  // 180 像素）。保持溢出隐藏，直到我们达到上限，所以空/短输入
  // 从不显示滚动条（与 Web 控制台行为匹配）。
  const autoSize = (el: HTMLTextAreaElement | null) => {
    if (!el) return
    el.style.height = '48px'
    const h = Math.min(el.scrollHeight, 200)
    el.style.height = h + 'px'
    el.style.overflowY = el.scrollHeight > 200 ? 'auto' : 'hidden'
  }

  const resetHeight = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = '48px'
    el.style.overflowY = 'hidden'
  }

  // 安装后同步高度，以便第一个渲染与 42px 匹配
  // 单行高度而不是浏览器的默认文本区域大小。
  useEffect(() => {
    autoSize(textareaRef.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 每次更改时将输入写入 `chatDraft`，以便它能够幸存
  // 当用户导航到另一个页面（聊天路径）时卸载组件
  // 卸载 ChatPage；请参阅 store/draftStore.ts）。发送会清除输入，这
  // 因此也会清除保存的草稿。
  useEffect(() => {
    chatDraft.text = text
    chatDraft.attachments = attachments
  }, [text, attachments])

  // 允许家长加载草稿（例如，在编辑过去的用户消息时）。
  useImperativeHandle(ref, () => (draft: string, atts: Attachment[]) => {
    setText(draft)
    setAttachments(atts)
    requestAnimationFrame(() => {
      const el = textareaRef.current
      if (el) {
        el.focus()
        autoSize(el)
      }
    })
  })

  const runSlash = (c: SlashCommand) => {
    setSlashOpen(false)
    if (c.action === 'new') {
      setText('')
      resetHeight()
      onNewChat()
      return
    }
    if (c.action === 'clear') {
      setText('')
      resetHeight()
      onClearContext()
      return
    }
    // 完成命令。如果需要参数（尾随空格），请保留它
    // 在输入中，以便用户可以键入参数；否则现在就发送。
    const needsArg = c.cmd.endsWith(' ')
    if (needsArg) {
      setText(c.cmd)
      requestAnimationFrame(() => textareaRef.current?.focus())
    } else {
      onSend(c.cmd.trim(), [])
      setText('')
      resetHeight()
    }
  }

  const handleSubmit = useCallback(() => {
    const trimmed = text.trim()
    if (!trimmed && attachments.length === 0) return
    if (isStreaming) return
    onSend(trimmed, attachments)
    setText('')
    setAttachments([])
    setSlashOpen(false)
    resetHeight()
  }, [text, attachments, isStreaming, onSend])

  // 选择器显示代理（群聊）然后文件；要么非空
  // 保持打开状态。 `mentionCount` 是键盘导航的组合长度。
  const mentionCount = mentionAgents.length + mentionItems.length
  const mentionOpen = mentionStartRef.current >= 0 && mentionCount > 0

  const closeMention = () => {
    mentionStartRef.current = -1
    setMentionItems([])
    setMentionAgents([])
    setMentionIndex(0)
  }

  // 在键入提及的位置插入“@name”，因此后端的前导-@
  // 规则将轮流路由到该代理（与 Web 控制台匹配）。
  const acceptAgentMention = (index: number) => {
    const agent = mentionAgents[index]
    const el = textareaRef.current
    if (!agent || !el) return
    const caret = el.selectionStart
    const insert = `@${agent.name || agent.id} `
    const next = text.slice(0, mentionStartRef.current) + insert + text.slice(caret)
    const caretAfter = mentionStartRef.current + insert.length
    setText(next)
    closeMention()
    requestAnimationFrame(() => {
      el.focus()
      el.selectionStart = el.selectionEnd = caretAfter
      autoSize(el)
    })
  }

  // 一份名单，代理商优先。接受组合索引所在的行。
  const acceptMentionAt = (index: number) => {
    if (index < mentionAgents.length) acceptAgentMention(index)
    else acceptMention(index - mentionAgents.length)
  }

  /** Reference an existing workspace file or folder in place, not as an upload. */
  const addWorkspaceRef = (entry: WorkspaceEntry) => {
    setAttachments((prev) =>
      prev.some((a) => a.file_type === 'workspace_ref' && a.file_path === entry.path)
        ? prev
        : [
            ...prev,
            {
              file_path: entry.path,
              file_name: entry.name,
              file_type: 'workspace_ref',
              is_dir: entry.is_dir,
            },
          ]
    )
  }

  const acceptMention = (index: number) => {
    const item = mentionItems[index]
    const el = textareaRef.current
    if (!item || !el) return
    addWorkspaceRef(item)
    // 删除“@query”片段：文件作为附件附带。
    const caret = el.selectionStart
    const next = text.slice(0, mentionStartRef.current) + text.slice(caret)
    const caretAfter = mentionStartRef.current
    setText(next)
    closeMention()
    requestAnimationFrame(() => {
      el.focus()
      el.selectionStart = el.selectionEnd = caretAfter
      autoSize(el)
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // 提及菜单优先：它仅在输入“@…”时打开。
    if (mentionOpen) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setMentionIndex((i) => (i + 1) % mentionCount)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setMentionIndex((i) => (i - 1 + mentionCount) % mentionCount)
        return
      }
      if ((e.key === 'Enter' && !e.shiftKey) || e.key === 'Tab') {
        e.preventDefault()
        acceptMentionAt(mentionIndex)
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        closeMention()
        return
      }
    }
    // 斜杠菜单导航
    if (slashOpen && filtered.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSlashIndex((i) => (i + 1) % filtered.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSlashIndex((i) => (i - 1 + filtered.length) % filtered.length)
        return
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        runSlash(filtered[slashIndex])
        return
      }
      if (e.key === 'Escape') {
        setSlashOpen(false)
        return
      }
    }
    // IME 正在撰写时请勿提交（中文输入）
    if (e.key === 'Enter' && !e.shiftKey && !composingRef.current) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const v = e.target.value
    setText(v)
    autoSize(e.target)
    // 当输入以“/”开头并且没有空格时打开斜杠菜单
    setSlashOpen(v.startsWith('/') && !v.includes(' '))
    setSlashIndex(0)

    // 在开头或空格后的“@”处触发文件选择器。
    const match = v.slice(0, e.target.selectionStart).match(/(?:^|\s)@([^\s@]*)$/)
    if (mentionTimerRef.current) clearTimeout(mentionTimerRef.current)
    if (!match) {
      closeMention()
      return
    }
    mentionStartRef.current = e.target.selectionStart - match[1].length - 1
    const query = match[1]
    // 代理在本地匹配并立即更新（无请求），因此组
    // 名册显示输入“@”的时刻。
    const q = query.toLowerCase()
    const matchedAgents = mentionRoster.filter(
      (a) => !q || (a.name || a.id).toLowerCase().includes(q) || a.id.toLowerCase().includes(q)
    )
    setMentionAgents(matchedAgents)
    setMentionIndex(0)
    mentionTimerRef.current = setTimeout(async () => {
      try {
        const res = await apiClient.workspaceSearch(query, 12, sessionId)
        if (mentionStartRef.current < 0) return
        setMentionItems(res.results || [])
      } catch {
        setMentionItems([])
      }
    }, 160)
  }

  const uploadFiles = async (files: File[]) => {
    if (!files.length) return
    setUploading(true)
    setUploadError('')
    // 报告每个文件的结果：这里的无声失败与
    // 文件选择器永远不会打开，这使得该功能看起来很糟糕。
    const failed: string[] = []
    try {
      for (const file of files) {
        try {
          const result = await apiClient.uploadFile(file, sessionId)
          if (result.status === 'success') {
            setAttachments((prev) => [
              ...prev,
              {
                file_path: result.file_path,
                file_name: result.file_name,
                file_type: result.file_type as Attachment['file_type'],
                preview_url: result.preview_url,
              },
            ])
          } else {
            failed.push(`${file.name}: ${result.message || 'unknown error'}`)
          }
        } catch (err) {
          failed.push(`${file.name}: ${(err as Error).message}`)
        }
      }
    } finally {
      setUploading(false)
      if (failed.length) {
        console.error('Upload failed:', failed)
        setUploadError(`${t('upload_failed')} — ${failed.join('; ')}`)
      }
    }
  }

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files) await uploadFiles(Array.from(files))
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleDropData = (dt: DataTransfer) => {
    // 从工作区面板拖动的文件已在磁盘上
    // 工作区 - 引用它而不是上传副本。
    const wsPayload = dt.getData(WORKSPACE_DRAG_TYPE)
    if (wsPayload) {
      try {
        addWorkspaceRef(JSON.parse(wsPayload) as WorkspaceEntry)
      } catch {
        /* 格式错误的拖动有效负载 */
      }
      return
    }
    const files = Array.from(dt.files || [])
    if (files.length) uploadFiles(files)
  }

  // 通读引用，以便下面的窗口侦听器可以保持绑定一次
  // 而不是在输入状态发生变化时重新订阅。
  const dropHandlerRef = useRef(handleDropData)
  dropHandlerRef.current = handleDropData

  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items
    if (!items) return
    const files: File[] = []
    for (const item of Array.from(items)) {
      if (item.kind === 'file') {
        const f = item.getAsFile()
        if (f) files.push(f)
      }
    }
    if (files.length) {
      e.preventDefault()
      uploadFiles(files)
    }
  }

  const removeAttachment = (index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index))
  }

  // 保持斜线索引在范围内
  useEffect(() => {
    if (slashIndex >= filtered.length) setSlashIndex(0)
  }, [filtered.length, slashIndex])

  // 接受在窗口中的任何位置放置，而不仅仅是在输入框上：
  // 用户瞄准对话区域，没有元素处理的掉落会导致
  // Chromium 导航到删除的文件，替换整个 UI。
  useEffect(() => {
    const carriesFiles = (dt: DataTransfer | null) =>
      !!dt && (dt.types.includes('Files') || dt.types.includes(WORKSPACE_DRAG_TYPE))

    // 在后代之间移动时，dragenter/dragleave 也会触发，因此跟踪
    // 嵌套深度，并且只有在拖动真正离开时才删除突出显示。
    let depth = 0
    const onDragEnter = (e: DragEvent) => {
      if (!carriesFiles(e.dataTransfer)) return
      e.preventDefault()
      depth += 1
      setDragOver(true)
    }
    const onDragOver = (e: DragEvent) => {
      if (!carriesFiles(e.dataTransfer)) return
      e.preventDefault()
    }
    const onDragLeave = (e: DragEvent) => {
      if (!carriesFiles(e.dataTransfer)) return
      depth = Math.max(0, depth - 1)
      if (depth === 0) setDragOver(false)
    }
    const onDrop = (e: DragEvent) => {
      depth = 0
      setDragOver(false)
      if (!carriesFiles(e.dataTransfer)) return
      e.preventDefault()
      dropHandlerRef.current(e.dataTransfer!)
    }
    // 拖动可以结束而无需放下（Esc，或在窗口外释放）。
    const onDragEnd = () => {
      depth = 0
      setDragOver(false)
    }

    window.addEventListener('dragenter', onDragEnter)
    window.addEventListener('dragover', onDragOver)
    window.addEventListener('dragleave', onDragLeave)
    window.addEventListener('drop', onDrop)
    window.addEventListener('dragend', onDragEnd)
    return () => {
      window.removeEventListener('dragenter', onDragEnter)
      window.removeEventListener('dragover', onDragOver)
      window.removeEventListener('dragleave', onDragLeave)
      window.removeEventListener('drop', onDrop)
      window.removeEventListener('dragend', onDragEnd)
    }
  }, [])

  const canSend = !isStreaming && (!!text.trim() || attachments.length > 0)

  return (
    <div className="flex-shrink-0 border-t border-default bg-surface px-4 py-3">
      {/* 一张高的圆形卡片将文本区域放在顶部和工具栏行
          （芯片 + 操作）位于底部，与 Web 控制台编辑器相匹配。 */}
      <div
        className={`max-w-3xl mx-auto relative rounded-2xl border bg-inset transition-colors ${
          dragOver ? 'border-accent ring-2 ring-accent/30' : 'border-strong focus-within:border-accent'
        }`}
      >
        {dragOver && (
          // 口音软是 12%-alpha 色调，因此它需要在下面有一个不透明层
          // 它 - 否则文本区域占位符会通过提示显示。
          <div className="absolute inset-0 z-20 rounded-2xl bg-surface pointer-events-none">
            <div className="flex h-full w-full items-center justify-center rounded-2xl bg-accent-soft text-accent text-sm font-medium">
              {t('drop_to_attach')}
            </div>
          </div>
        )}

        {uploadError && (
          <div className="mb-2 flex items-start gap-2 rounded-lg border border-danger-border bg-danger-soft px-3 py-2 text-xs text-danger">
            <span className="flex-1 break-all">{uploadError}</span>
            <button
              onClick={() => setUploadError('')}
              className="flex-shrink-0 cursor-pointer hover:opacity-70"
              title={t('ws_close')}
            >
              <X size={12} />
            </button>
          </div>
        )}

        {/* 斜线命令菜单 */}
        {slashOpen && filtered.length > 0 && (
          <div className="absolute bottom-full left-0 right-0 mb-1.5 max-h-80 overflow-y-auto rounded-xl border border-default bg-elevated shadow-xl z-30 p-1.5">
            <div className="px-2.5 pt-1 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-content-tertiary">
              {t('slash_menu_title')}
            </div>
            {filtered.map((c, i) => (
              <button
                key={c.cmd}
                onMouseEnter={() => setSlashIndex(i)}
                onClick={() => runSlash(c)}
                className={`w-full flex items-center justify-between gap-3 px-2.5 py-2 rounded-lg text-left cursor-pointer transition-colors ${
                  i === slashIndex ? 'bg-accent-soft' : 'hover:bg-surface-2'
                }`}
              >
                <span
                  className={`text-[13px] font-medium font-mono whitespace-nowrap ${
                    i === slashIndex ? 'text-accent' : 'text-content-secondary'
                  }`}
                >
                  {c.cmd}
                </span>
                <span className="text-xs text-content-tertiary whitespace-nowrap truncate">{c.desc}</span>
              </button>
            ))}
          </div>
        )}

        {/* @ picker：首先是群聊代理，然后是工作区文件 - 一个平面
            列表，以便代理读起来就像任何其他选择一样。 */}
        {mentionOpen && (
          <div className="absolute bottom-full left-0 right-0 mb-1.5 max-h-72 overflow-y-auto rounded-xl border border-default bg-elevated shadow-xl z-30 p-1.5">
            {mentionAgents.map((a, i) => (
              <button
                key={`agent:${a.id}`}
                onMouseEnter={() => setMentionIndex(i)}
                onMouseDown={(e) => {
                  e.preventDefault()
                  acceptAgentMention(i)
                }}
                className={`w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg text-left cursor-pointer transition-colors ${
                  i === mentionIndex ? 'bg-accent-soft' : 'hover:bg-surface-2'
                }`}
              >
                <AgentAvatar agent={a} size={20} />
                <span className="text-[13px] text-content shrink-0 max-w-[55%] truncate">{a.name || a.id}</span>
                <span className="flex-1 min-w-0 text-[11px] text-content-tertiary text-right truncate">{a.id}</span>
              </button>
            ))}
            {mentionItems.map((item, j) => {
              const i = mentionAgents.length + j
              const Icon = iconFor(item.kind)
              return (
                <button
                  key={item.path}
                  onMouseEnter={() => setMentionIndex(i)}
                  onMouseDown={(e) => {
                    e.preventDefault()
                    acceptMention(j)
                  }}
                  className={`w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg text-left cursor-pointer transition-colors ${
                    i === mentionIndex ? 'bg-accent-soft' : 'hover:bg-surface-2'
                  }`}
                >
                  <Icon size={13} className={`shrink-0 ${colorFor(item.kind)}`} />
                  <span className="text-[13px] text-content shrink-0 max-w-[45%] truncate">{item.name}</span>
                  <span className="flex-1 min-w-0 text-[11px] text-content-tertiary text-right truncate">
                    {item.path}
                  </span>
                </button>
              )
            })}
          </div>
        )}

        {/* 附件预览位于卡片顶部、文本区域上方。 */}
        {attachments.length > 0 && (
          <div className="flex items-center gap-2 relative px-3 pt-2.5">
            <div className="flex-1 min-w-0 flex items-center gap-2 overflow-x-auto overflow-y-visible">
              {attachments.map((att, i) => (
                <div key={i} className="relative shrink-0">
                  {att.file_type === 'image' && att.preview_url ? (
                    <div className="relative">
                      <img
                        src={apiClient.getFileUrl(att.preview_url)}
                        alt={att.file_name}
                        className="w-8 h-8 rounded-lg object-cover border border-default"
                      />
                      <button
                        onClick={() => removeAttachment(i)}
                        className="absolute top-0 right-0 w-3.5 h-3.5 rounded-full bg-danger text-white flex items-center justify-center cursor-pointer ring-1 ring-surface leading-none"
                      >
                        <X size={8} strokeWidth={2.5} />
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1.5 pl-2 pr-1 py-1 bg-surface border border-default rounded-lg text-[11px] text-content-secondary max-w-[160px]">
                      {att.file_type === 'workspace_ref' ? (
                        att.is_dir ? (
                          <Folder size={11} className="text-accent shrink-0" />
                        ) : (
                          <AtSign size={11} className="text-accent shrink-0" />
                        )
                      ) : (
                        <FileIcon size={11} className="shrink-0" />
                      )}
                      <span className="truncate" title={att.file_path}>
                        {att.file_name}
                      </span>
                      <button
                        onClick={() => removeAttachment(i)}
                        className="shrink-0 w-4 h-4 rounded flex items-center justify-center text-content-tertiary hover:text-danger hover:bg-danger-soft cursor-pointer"
                      >
                        <X size={11} strokeWidth={2.5} />
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          multiple
          onChange={handleFileSelect}
        />

        {/* 文本区域位于卡片的顶部，无边框（卡片拥有
            边框）并且比单行高，因此作曲家读起来很高。 */}
        <div className="relative">
          <textarea
            ref={textareaRef}
            id="chat-input"
            value={text}
            onChange={handleTextChange}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            onCompositionStart={() => (composingRef.current = true)}
            onCompositionEnd={() => (composingRef.current = false)}
            placeholder={t('input_placeholder')}
            rows={1}
            className="w-full px-4 pt-3 pb-0 bg-transparent text-content placeholder:text-content-tertiary focus:outline-none text-sm leading-relaxed resize-none overflow-y-hidden"
          />
          {micError && (
            // 输入上方的瞬态错误提示，镜像 Web 控制台。
            <div className="absolute right-3 bottom-full mb-2 px-2 py-1 rounded-md text-xs text-white bg-black/80 dark:bg-white/20 shadow-md pointer-events-none whitespace-nowrap z-10">
              {micError}
            </div>
          )}
        </div>

        {/* 卡片内的工具栏行：左侧为芯片，右侧为操作。
            这就是使作曲家读起来像网络一样高大的卡片的原因
            控制台，而不是一个带有浮动控件的简短输入。
            中间的芯片组缩小/截断，因此狭窄的作曲家（右
            面板打开）永远不会溢出卡。 */}
        <div className="composer-toolbar flex items-center gap-1 px-2 pb-1 pt-2 min-w-0">
          {/* 作曲家的“+”是一个快速的新聊天：它打开了一个新的
              当前代理立即拥有的对话，无需选择器
              （与网络控制台匹配）。选择不同的代理或启动一个
              组位于会话列表“+”菜单中。 */}
          <Tooltip label={t('session_new')}>
            <button
              onClick={onNewChat}
              className="shrink-0 w-8 h-8 flex items-center justify-center rounded-btn cursor-pointer transition-colors text-content-secondary hover:text-accent hover:bg-accent-soft"
            >
              <Plus size={17} />
            </button>
          </Tooltip>
          <Tooltip label={t('chat_attach')}>
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="shrink-0 w-8 h-8 flex items-center justify-center rounded-btn text-content-secondary hover:text-accent hover:bg-accent-soft cursor-pointer transition-colors disabled:opacity-50"
            >
              {uploading ? <Loader2 size={17} className="animate-spin" /> : <Paperclip size={17} />}
            </button>
          </Tooltip>
          <Tooltip label={t('chat_clear_context')}>
            <button
              onClick={onClearContext}
              className="shrink-0 w-8 h-8 flex items-center justify-center rounded-btn text-content-secondary hover:text-danger hover:bg-danger-soft cursor-pointer transition-colors"
            >
              <Trash2 size={17} />
            </button>
          </Tooltip>

          <div className="mx-1 h-4 w-px bg-default shrink-0" />

          {/* 芯片共享柔性中间；每个都可能缩小和截断。 */}
          <div className="flex items-center gap-1 min-w-0 flex-1">
            <WorkspaceSelector sessionId={sessionId} />
            <PermissionSelector sessionId={sessionId} />
          </div>

          <div className="flex items-center gap-1 shrink-0 pl-1">
            {!sharedConversation && (
              <div className="max-w-[200px] min-w-0">
                <ModelSelector sessionId={sessionId} />
              </div>
            )}
            {/* 代理选择器位于最右侧，仅包含头像，作为身份
                回复来自。仅在多Agent模式下。 */}
            {multiAgent && <AgentSelector sessionId={sessionId} />}
            {micSupported && (
              <Tooltip
                label={
                  micState === 'recording'
                    ? t('mic_recording_title')
                    : micState === 'busy'
                      ? t('mic_busy_title')
                      : t('mic_idle_title')
                }
              >
                <button
                  onClick={toggleMic}
                  disabled={micState === 'busy'}
                  className={`w-8 h-8 flex items-center justify-center rounded-btn cursor-pointer transition-colors disabled:cursor-not-allowed ${
                    micState === 'recording'
                      ? 'text-red-500 animate-pulse hover:text-red-600'
                      : micState === 'busy'
                        ? 'text-accent'
                        : 'text-content-tertiary hover:text-accent hover:bg-accent-soft'
                  }`}
                >
                  {micState === 'recording' ? (
                    <Square size={12} className="fill-current" />
                  ) : micState === 'busy' ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Mic size={16} />
                  )}
                </button>
              </Tooltip>
            )}
            {isStreaming ? (
              <Tooltip label={t('msg_stop')}>
                <button
                  onClick={onStop}
                  className="flex-shrink-0 w-9 h-9 flex items-center justify-center rounded-btn bg-surface-2 text-content hover:bg-inset-2 cursor-pointer transition-colors"
                >
                  <Square size={14} className="fill-current" />
                </button>
              </Tooltip>
            ) : (
              <Tooltip label={t('chat_send')}>
                <button
                  onClick={handleSubmit}
                  disabled={!canSend}
                  className="flex-shrink-0 w-9 h-9 flex items-center justify-center rounded-btn bg-accent text-white hover:bg-accent-hover disabled:bg-surface-2 disabled:text-content-disabled disabled:cursor-not-allowed cursor-pointer transition-none [&_*]:transition-none"
                >
                  <PaperPlaneIcon size={14} />
                </button>
              </Tooltip>
            )}
          </div>
        </div>
      </div>
    </div>
  )
})

export default ChatInput
