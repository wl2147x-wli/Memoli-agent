import React, { useEffect, useRef, useCallback, useState } from 'react'
import {
  ChevronUp,
  Loader2,
  FolderOpen,
  Clock,
  Code2,
  BookOpen,
  Puzzle,
  Terminal,
  type LucideIcon,
} from 'lucide-react'
import MessageBubble from '../components/MessageBubble'
import ChatInput, { type ChatInputHandle } from '../components/ChatInput'
import { product } from '@product'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { Attachment, ChatMessage } from '../types'
import { useChatStore } from '../store/chatStore'
import { useSessionStore, sessionOwner } from '../store/sessionStore'
import { useAgentStore } from '../store/agentStore'
import { useWorkspaceStore } from '../store/workspaceStore'
import { startNewChat } from '../lib/newChat'

interface ChatPageProps {
  baseUrl: string
}

// 欢迎屏幕建议卡（与 Web 控制台对齐：6 张卡）。
// `send` overrides the text dropped into the input (e.g. show "查看全部命令"
// 但填写“/help”）；否则使用卡的 *_text。
// 每张卡的图标 + 强调颜色，与 Web 控制台调色板对齐。
const SUGGESTIONS: {
  key: string
  send?: string
  icon: LucideIcon
  iconClass: string
  bgClass: string
}[] = [
  { key: 'example_sys', icon: FolderOpen, iconClass: 'text-blue-500', bgClass: 'bg-blue-500/10' },
  { key: 'example_task', icon: Clock, iconClass: 'text-amber-500', bgClass: 'bg-amber-500/10' },
  { key: 'example_code', icon: Code2, iconClass: 'text-emerald-500', bgClass: 'bg-emerald-500/10' },
  { key: 'example_knowledge', icon: BookOpen, iconClass: 'text-violet-500', bgClass: 'bg-violet-500/10' },
  { key: 'example_skill', icon: Puzzle, iconClass: 'text-rose-500', bgClass: 'bg-rose-500/10' },
  { key: 'example_web', send: '/help', icon: Terminal, iconClass: 'text-content-tertiary', bgClass: 'bg-content-tertiary/10' },
]

const ChatPage: React.FC<ChatPageProps> = ({ baseUrl }) => {
  const activeId = useSessionStore((s) => s.activeId)
  const loadSessions = useSessionStore((s) => s.loadSessions)
  const activeAgentId = useAgentStore((s) => s.activeAgentId)

  const session = useChatStore((s) => s.sessions[activeId])
  const send = useChatStore((s) => s.send)
  const cancel = useChatStore((s) => s.cancel)
  const regenerate = useChatStore((s) => s.regenerate)
  const editUserMessage = useChatStore((s) => s.editUserMessage)
  const deleteMessage = useChatStore((s) => s.deleteMessage)
  const loadHistory = useChatStore((s) => s.loadHistory)
  const ensureSession = useChatStore((s) => s.ensureSession)
  const clearContext = useChatStore((s) => s.clearContext)
  const wsOnSessionSwitch = useWorkspaceStore((s) => s.onSessionSwitch)

  const messages = session?.messages ?? []
  const isStreaming = session?.isStreaming ?? false

  const scrollRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputResetRef = useRef<ChatInputHandle>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const titlePendingRef = useRef(false)

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
  }, [baseUrl])

  // 切换到尚未加载的会话时加载历史记录。
  useEffect(() => {
    ensureSession(activeId)
    const s = useChatStore.getState().sessions[activeId]
    if (s && !s.historyLoaded && !s.isStreaming) {
      loadHistory(activeId, 1)
    }
  }, [activeId, ensureSession, loadHistory])

  // 历史存在于业主代理的商店中。如果业主开放
  // 我们的谈话发生了变化（第一次加载后名单就解决了，
  // 或者后端列表更正了谁拥有它），我们加载的内容来自
  // 错误的商店 - 从正确的商店重新获取它。仅空闲会话。
  const loadedOwnerRef = useRef<{ sid: string; owner: string } | null>(null)
  useEffect(() => {
    const owner = sessionOwner(activeId)
    const prev = loadedOwnerRef.current
    loadedOwnerRef.current = { sid: activeId, owner }
    // 会话切换由上述效果处理；仅同一会话
    // 所有者更改意味着加载的历史记录来自错误的存储。
    if (!prev || prev.sid !== activeId || prev.owner === owner) return
    // 无范围（预名册）请求已读取默认代理的存储。
    if (prev.owner === '' && owner === useAgentStore.getState().defaultAgentId) return
    const s = useChatStore.getState().sessions[activeId]
    if (s && !s.isStreaming) loadHistory(activeId, 1)
  }, [activeId, activeAgentId, loadHistory])

  // 保持工作区面板的范围为活动会话（项目与默认）。
  useEffect(() => {
    wsOnSessionSwitch(activeId)
  }, [activeId, wsOnSessionSwitch])

  const scrollToBottom = useCallback((smooth = true) => {
    // 推迟到下一帧，因此我们读取新内容*之后*的高度
    // 已经布局（markdown/streaming 渲染比效果晚一帧）。
    requestAnimationFrame(() => {
      const el = scrollRef.current
      if (!el) return
      // 流畅的动画会被高频流媒体更新打断
      // 并且永远不会追上，所以在顺流而下时立即跳跃。
      if (smooth) {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
      } else {
        el.scrollTop = el.scrollHeight
      }
    })
  }, [])

  // 切换会话时立即捕捉到底部（无从上到下动画）。
  // 历史记录可能会稍后加载一帧，因此请立即捕捉，直到内容到达。
  const lastSessionRef = useRef('')
  const lastLenRef = useRef(0)
  const pendingSnapRef = useRef(false)
  // 确实如此，但我们应该将视图固定在底部（例如在
  // 流式传输）。当用户向上滚动以阅读较早的消息时清除。
  const followBottomRef = useRef(true)
  // 跟踪之前的流媒体状态，以便我们可以对
  // 流结束时的右下角（长命令输出的最后一个块
  // 通常与 isStreaming 一起翻转为 false）。
  const wasStreamingRef = useRef(false)
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return

    if (lastSessionRef.current !== activeId) {
      lastSessionRef.current = activeId
      lastLenRef.current = messages.length
      pendingSnapRef.current = true
      followBottomRef.current = true
    }

    if (pendingSnapRef.current) {
      // 即时捕捉开关和随后登陆的第一个内容。
      lastLenRef.current = messages.length
      scrollToBottom(false)
      if (messages.length > 0) pendingSnapRef.current = false
      return
    }

    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160
    const grew = messages.length !== lastLenRef.current
    lastLenRef.current = messages.length
    // 关注底部时：有新消息到达，用户已在附近
    // 底部，或者我们正在流式传输并且用户尚未向上滚动。这个
    // 保留长命令/流输出（其中长度不变，但
    // 内容不断增长）粘在最新的一行上。
    // 流结束时最后一次快照，因此是长命令的尾部
    // 输出不会在屏幕外滚动。
    const justFinished = wasStreamingRef.current && !isStreaming
    wasStreamingRef.current = isStreaming

    const following = isStreaming && followBottomRef.current
    if (grew || nearBottom || following || (justFinished && followBottomRef.current)) {
      // 流式传输/新内容时即时跳转（平滑的动画得到
      // 被快速更新打断并且永远不会到达底部）；仅平滑
      // 当用户已经坐在底部附近时，进行单独的增量。
      const smooth = nearBottom && !following && !grew && !justFinished
      scrollToBottom(smooth)
    }
  }, [messages, activeId, isStreaming, scrollToBottom])

  const handleSend = useCallback(
    async (text: string, attachments: Attachment[]) => {
      const sid = activeId
      const isFirst = (useChatStore.getState().sessions[sid]?.messages.length ?? 0) === 0
      titlePendingRef.current = isFirst
      // 在等待之前解决所有者：所有权请求必须落在
      // 即使用户同时切换，消息也会存储相同的内容。
      const owner = sessionOwner(sid) || undefined
      await send(sid, text, attachments)
      // 在第一条消息之后，刷新列表并要求后端为其添加标题。
      if (isFirst) {
        try {
          await apiClient.generateSessionTitle(sid, text, undefined, owner)
        } catch {
          /* 忽略 */
        }
        loadSessions(1)
        titlePendingRef.current = false
      }
    },
    [activeId, send, loadSessions]
  )

  const handleNewChat = useCallback(async () => {
    // 新的聊天会重新调整工作区面板的范围，关闭所有打开的编辑器。
    if (!(await useWorkspaceStore.getState().guardUnsavedEdit())) return
    startNewChat()
  }, [])

  const handleClearContext = useCallback(async () => {
    await clearContext(activeId)
    scrollToBottom(true)
  }, [clearContext, activeId, scrollToBottom])

  const handleStop = useCallback(() => cancel(activeId), [cancel, activeId])

  const handleRegenerate = useCallback((id: string) => regenerate(activeId, id), [regenerate, activeId])

  const handleEdit = useCallback(
    (id: string) => {
      const result = editUserMessage(activeId, id)
      if (result && inputResetRef.current) inputResetRef.current(result.text, result.attachments)
    },
    [editUserMessage, activeId]
  )

  const handleDelete = useCallback(
    (msg: ChatMessage) => {
      if (msg.userSeq != null) deleteMessage(activeId, msg.userSeq, true)
    },
    [deleteMessage, activeId]
  )

  // 内联图像/视频异步加载并在安装后增长气泡，
  // 因此，在最终高度之前，会在消息更改时触发滚动
  // 已知。媒体加载后重新滚动，但仅在跟随底部时重新滚动。
  const handleMediaLoad = useCallback(() => {
    if (followBottomRef.current) scrollToBottom(false)
  }, [scrollToBottom])

  const handleScroll = useCallback(
    async (e: React.UIEvent<HTMLDivElement>) => {
      const el = e.currentTarget
      // 跟踪用户是否想要保持固定在底部：向上滚动
      // 暂停自动跟随；返回底部附近即可恢复。
      followBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 160
      const s = useChatStore.getState().sessions[activeId]
      if (el.scrollTop < 40 && s?.historyHasMore && !loadingMore && !isStreaming) {
        setLoadingMore(true)
        const prevHeight = el.scrollHeight
        await loadHistory(activeId, s.historyPage + 1)
        requestAnimationFrame(() => {
          // 在添加旧消息后保留滚动位置
          el.scrollTop = el.scrollHeight - prevHeight
          setLoadingMore(false)
        })
      }
    },
    [activeId, loadHistory, loadingMore, isStreaming]
  )

  const isEmpty = messages.length === 0

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div ref={scrollRef} className="flex-1 overflow-y-auto" onScroll={handleScroll}>
        {loadingMore && (
          <div className="flex items-center justify-center py-3 text-content-tertiary">
            <Loader2 size={16} className="animate-spin" />
          </div>
        )}

        {isEmpty ? (
          <div data-home className="chat-home flex flex-col items-center justify-center h-full px-6 py-12">
            {product.slots?.HomeLogo ? (
              <div className="w-16 h-16 rounded-2xl mb-5 shadow-md overflow-hidden">
                <product.slots.HomeLogo />
              </div>
            ) : (
              <img src="./logo.jpg" alt="CowAgent" className="w-16 h-16 rounded-2xl mb-5 shadow-md" />
            )}
            <h1 className="text-xl font-semibold text-content mb-2">{t('chat_welcome')}</h1>
            <p className="text-content-tertiary text-sm text-center max-w-md mb-8 leading-relaxed whitespace-pre-line">
              {t('welcome_subtitle')}
            </p>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 w-full max-w-2xl">
              {SUGGESTIONS.map(({ key, send, icon: Icon, iconClass, bgClass }) => (
                <button
                  key={key}
                  onClick={() => {
                    // 填写输入（不自动发送），以便用户可以先对其进行调整。
                    const draft = send ?? t(`${key}_text` as Parameters<typeof t>[0])
                    inputResetRef.current?.(draft, [])
                  }}
                  className="group text-left bg-surface border border-default rounded-xl p-3.5 cursor-pointer hover:border-accent hover:shadow-sm transition-all"
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <span
                      className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${bgClass}`}
                    >
                      <Icon size={15} className={iconClass} />
                    </span>
                    <span className="font-medium text-sm text-content">
                      {t(`${key}_title` as Parameters<typeof t>[0])}
                    </span>
                  </div>
                  <p className="text-xs text-content-tertiary leading-relaxed line-clamp-2">
                    {t(`${key}_text` as Parameters<typeof t>[0])}
                  </p>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="py-3 max-w-3xl mx-auto">
            {messages.map((msg) =>
              msg.kind === 'divider' ? (
                <div key={msg.id} className="flex items-center gap-3 px-6 py-3 text-content-tertiary">
                  <span
                    className="flex-1 h-px"
                    style={{ background: 'linear-gradient(to right, transparent, var(--border-strong), transparent)' }}
                  />
                  <span className="text-xs whitespace-nowrap">{t('context_cleared')}</span>
                  <span
                    className="flex-1 h-px"
                    style={{ background: 'linear-gradient(to right, transparent, var(--border-strong), transparent)' }}
                  />
                </div>
              ) : (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  onRegenerate={handleRegenerate}
                  onEdit={handleEdit}
                  onDelete={handleDelete}
                  onMediaLoad={handleMediaLoad}
                />
              )
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* 跳到底部的可供性可能会在以后到达这里 */}

      <ChatInput
        onSend={handleSend}
        onNewChat={handleNewChat}
        onStop={handleStop}
        onClearContext={handleClearContext}
        isStreaming={isStreaming}
        sessionId={activeId}
        ref={inputResetRef}
      />
    </div>
  )
}

export default ChatPage
