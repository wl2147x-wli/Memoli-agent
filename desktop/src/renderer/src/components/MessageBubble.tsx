import React, { useState } from 'react'
import { Copy, Check, RefreshCw, Trash2, File as FileIcon, Folder, Sprout } from 'lucide-react'
import type { ChatMessage } from '../types'
import { t } from '../i18n'
import apiClient from '../api/client'
import { useWorkspaceStore } from '../store/workspaceStore'
import Markdown from './Markdown'
import MentionText from './MentionText'
import MessageSteps, { ThinkingStep } from './MessageSteps'
import FileCard from './FileCard'
import { useLightboxStore } from './Lightbox'
import AgentAvatar from './AgentAvatar'
import { useAgentStore, selectMultiAgent, findAgent } from '../store/agentStore'
import { useSessionSettingsStore, selectSharedConversation } from '../store/sessionSettingsStore'
import { product } from '@product'

interface MessageBubbleProps {
  message: ChatMessage
  onRegenerate?: (id: string) => void
  onEdit?: (id: string) => void
  onDelete?: (msg: ChatMessage) => void
  /** Fired when an inline image/video finishes loading, so the parent can
   *  re-scroll to the bottom (async media changes bubble height after mount). */
  onMediaLoad?: () => void
}

function fmtTime(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

const HoverAction: React.FC<{ onClick: () => void; title: string; danger?: boolean; children: React.ReactNode }> = ({
  onClick,
  title,
  danger,
  children,
}) => (
  <button
    onClick={onClick}
    title={title}
    className={`inline-flex items-center justify-center w-7 h-7 rounded-md cursor-pointer transition-colors text-content-tertiary ${
      danger ? 'hover:text-danger hover:bg-danger-soft' : 'hover:text-content hover:bg-surface-2'
    }`}
  >
    {children}
  </button>
)

const MessageBubble: React.FC<MessageBubbleProps> = ({ message, onRegenerate, onEdit, onDelete, onMediaLoad }) => {
  const isUser = message.role === 'user'
  const [copied, setCopied] = useState(false)
  const preview = useWorkspaceStore((s) => s.preview)
  const openLightbox = useLightboxStore((s) => s.open)
  // 在多代理模式下，在助手气泡上显示说话的代理的脸部。
  // 队友的回合被标记为作者（`extras.agent_id`）；未标记的
  // 回复是对话所有者的，并且所有者始终是主动的
  // 代理（打开聊天会激活其所有者；在聊天中切换代理
  // 有消息开始新的消息），所以回到它永远不会重写谁
  // 过去轮流说话。
  const multiAgent = useAgentStore(selectMultiAgent)
  const activeAgentId = useAgentStore((s) => s.activeAgentId)
  const speakerId = (message.extras?.agent_id as string) || activeAgentId
  const speaker = multiAgent && speakerId ? findAgent(speakerId) : undefined
  // 在群组对话中，多个代理进行回答，因此每个回复都带有标签
  // 及其发言人的姓名（如网络控制台中所示）。单独聊天可以保持
  // 普通的气泡——仅凭脸就可以看出它是谁。
  const shared = useSessionSettingsStore(selectSharedConversation)
  const speakerName = shared && speaker ? speaker.name || speaker.id : ''

  const copy = () => {
    navigator.clipboard.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  // 打开发送的文件：更喜欢通过 Electron 的本地路径（Finder / 默认
  // 应用程序）；当不可用时，回退到浏览器中提供的 URL。
  const openAttachment = (att: { abs_path?: string; preview_url?: string; file_path: string }) => {
    if (att.abs_path && window.electronAPI?.openPath) {
      window.electronAPI.openPath(att.abs_path)
      return
    }
    window.open(apiClient.getFileUrl(att.preview_url || att.file_path), '_blank')
  }

  if (isUser) {
    return (
      <div className="group flex flex-col items-end px-4 sm:px-6 py-2">
        {message.attachments && message.attachments.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-1.5 justify-end max-w-[75%]">
            {message.attachments.map((att, i) => {
              if (att.file_type === 'image' && (att.preview_url || att.file_path)) {
                // 历史重播可从提示标记中恢复附件，
                // 仅携带本地 file_path - 通过 /api/file 提供服务。
                const url = att.preview_url
                  ? apiClient.getFileUrl(att.preview_url)
                  : apiClient.getServeFileUrl(att.file_path)
                return (
                  <img
                    key={i}
                    src={url}
                    alt={att.file_name}
                    onClick={() => openLightbox(url)}
                    className="max-w-[260px] max-h-[220px] rounded-xl object-cover border border-default cursor-zoom-in"
                  />
                )
              }
              if (att.file_type === 'workspace_ref') {
                return (
                  <div
                    key={i}
                    title={att.file_path}
                    onClick={() => preview(att.file_path)}
                    className="flex items-center gap-1.5 px-3 py-2 bg-surface-2 hover:bg-surface-3 rounded-xl text-xs text-content-secondary cursor-pointer transition-colors"
                  >
                    {att.is_dir ? <Folder size={13} /> : <FileIcon size={13} />}
                    {att.file_name}
                  </div>
                )
              }
              return (
                <div key={i} className="flex items-center gap-1.5 px-3 py-2 bg-surface-2 rounded-xl text-xs text-content-secondary">
                  <FileIcon size={13} />
                  {att.file_name}
                </div>
              )
            })}
          </div>
        )}
        <div className="max-w-[75%] rounded-2xl rounded-br-md px-4 py-2.5 bg-bubble-user text-bubble-user-text">
          <div className="text-sm whitespace-pre-wrap break-words">
            <MentionText text={message.content} onAccent />
          </div>
        </div>
        <div className="flex items-center gap-0.5 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <span className="text-[11px] text-content-tertiary mr-1">{fmtTime(message.timestamp)}</span>
          {/* 隐藏编辑条目：编辑过去的问题级联删除所有
              随后的转弯，这让用户感到惊讶。保持关闭直到我们支持
              非破坏性编辑。 */}
          {onDelete && message.userSeq != null && (
            <HoverAction onClick={() => onDelete(message)} title={t('msg_delete')} danger>
              <Trash2 size={13} />
            </HoverAction>
          )}
        </div>
      </div>
    )
  }

  // 助理
  const showCursor = message.isStreaming && !message.content && (!message.steps || message.steps.length === 0)

  const hasSteps = !!(message.steps && message.steps.length > 0)
  const hasLiveReasoning = !!(message.reasoning && message.isStreaming)

  return (
    <div className="group flex gap-3 px-4 sm:px-6 py-2">
      {product.slots?.AssistantAvatar ? (
        <div className="w-7 h-7 rounded-lg flex-shrink-0 mt-1 overflow-hidden">
          <product.slots.AssistantAvatar />
        </div>
      ) : speaker ? (
        <div className="mt-1">
          <AgentAvatar agent={speaker} size={28} shape="square" />
        </div>
      ) : (
        <img src="./logo.jpg" alt="Agent" className="w-7 h-7 rounded-lg flex-shrink-0 mt-1" />
      )}
      <div className="flex-1 min-w-0 max-w-[calc(100%-2.5rem)]">
        {speakerName && (
          <div className="text-[11px] font-medium text-content-tertiary mb-1 ml-1 truncate">{speakerName}</div>
        )}
        <div className="inline-block w-full rounded-2xl border border-default bg-surface px-4 py-3">
          {message.kind === 'evolution' && (
            <div className="inline-flex items-center gap-1 mb-1.5 text-[11px] text-content-tertiary">
              <Sprout size={11} />
              {t('msg_self_learned')}
            </div>
          )}

          {/* 步骤区域（思考/工具/中间内容），与网络对齐：
              静音，通过虚线分隔线与最终答案分开。 */}
          {(hasSteps || hasLiveReasoning) && (
            <div className="mb-2.5 pb-2 border-b border-dashed border-default">
              {hasSteps && <MessageSteps steps={message.steps!} />}
              {/* 现场推理是当前的、尚未承诺的思维，所以它
                  必须在所有提交的步骤（工具/思考）之后渲染，而不是在
                  气泡的最顶部。 */}
              {hasLiveReasoning && (
                <div className={hasSteps ? 'mt-1' : ''}>
                  <ThinkingStep content={message.reasoning!} streaming />
                </div>
              )}
            </div>
          )}

          {/* 最终答案 */}
          {message.content && <Markdown content={message.content} />}

          {/* 特工本轮写入的文件 - 单击以打开预览面板。 */}
          {message.artifacts && message.artifacts.length > 0 && (
            <div className="flex flex-col items-start">
              {message.artifacts.map((a) => (
                <FileCard key={a.abs_path || a.rel_path} meta={a} />
              ))}
            </div>
          )}

          {/* 通过 `send` 工具发送的媒体附件（图像/文件）。 */}
          {message.attachments && message.attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-2">
              {message.attachments.map((att, i) => {
                const url = apiClient.getFileUrl(att.preview_url || att.file_path)
                if (att.file_type === 'image') {
                  return (
                    <img
                      key={i}
                      src={url}
                      alt={att.file_name}
                      onLoad={() => onMediaLoad?.()}
                      onClick={() => openLightbox(url)}
                      className="max-w-[320px] w-full rounded-xl border border-default cursor-zoom-in"
                    />
                  )
                }
                if (att.file_type === 'video') {
                  return (
                    <video
                      key={i}
                      src={url}
                      controls
                      onLoadedData={() => onMediaLoad?.()}
                      className="max-w-[360px] w-full rounded-xl border border-default"
                    />
                  )
                }
                return (
                  <button
                    key={i}
                    type="button"
                    onClick={() => openAttachment(att)}
                    className="flex items-center gap-1.5 px-3 py-2 bg-surface-2 rounded-xl text-xs text-content-secondary hover:text-content cursor-pointer"
                  >
                    <FileIcon size={13} />
                    {att.file_name}
                  </button>
                )
              })}
            </div>
          )}

          {showCursor && (
            <div className="flex items-center gap-1 py-0.5">
              <span className="typing-dot" />
              <span className="typing-dot" />
              <span className="typing-dot" />
            </div>
          )}

          {message.isStreaming && message.content && (
            <span className="inline-block w-[6px] h-[14px] bg-accent ml-0.5 align-middle animate-blink" />
          )}

          {message.isCancelled && <div className="text-xs text-warning mt-1">{t('msg_cancelled')}</div>}
          {message.error && <div className="text-xs text-danger mt-1">{message.error}</div>}
        </div>

        {/* 悬停操作（仅当完成时） */}
        {!message.isStreaming && (message.content || message.error) && (
          <div className="flex items-center gap-0.5 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <span className="text-[11px] text-content-tertiary mr-1">{fmtTime(message.timestamp)}</span>
            <HoverAction onClick={copy} title={t('msg_copy')}>
              {copied ? <Check size={13} /> : <Copy size={13} />}
            </HoverAction>
            {onRegenerate && (
              <HoverAction onClick={() => onRegenerate(message.id)} title={t('msg_regenerate')}>
                <RefreshCw size={13} />
              </HoverAction>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default MessageBubble
