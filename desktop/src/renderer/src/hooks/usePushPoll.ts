import { useEffect } from 'react'
import apiClient from '../api/client'
import { useChatStore } from '../store/chatStore'
import { useSessionStore } from '../store/sessionStore'
import { useUIStore } from '../store/uiStore'

// 轮询活动会话以获取 SSE 流之外推送的消息（调度程序
// 提醒、主动推送）。镜像 Web 控制台：实时 SSE 回复是
// 跳过服务器端，因此 /poll 只产生这些带外消息。民意调查
// 击中后立即加快，闲置时减慢。
const DELAY_HIT_MS = 5000
const DELAY_IDLE_MS = 10000

// 模块级保护，因此只有一个轮询循环在进程范围内运行。 /民意调查是一个
// 破坏性的 get，所以两个循环（例如 React StrictMode 双挂载
// 在开发中的效果）会窃取彼此的消息并删除通知。
let loopActive = false

export function usePushPoll(ready: boolean): void {
  useEffect(() => {
    if (!ready || loopActive) return
    loopActive = true
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const schedule = (delay: number) => {
      if (cancelled) return
      timer = setTimeout(poll, delay)
    }

    async function poll() {
      if (cancelled) return
      // 隐藏时保持轮询：推送消息正是操作系统的内容
      // 下面的通知应发送到后台窗口。
      const sid = useSessionStore.getState().activeId
      if (!sid) {
        schedule(DELAY_IDLE_MS)
        return
      }
      try {
        const data = await apiClient.poll(sid)
        if (cancelled) return
        if (data.status === 'success' && data.has_content && data.content) {
          const added = useChatStore.getState().receivePush(sid, data.content, data.request_id)
          if (added) notify(sid, data.content)
          schedule(DELAY_HIT_MS)
          return
        }
      } catch {
        /* 短暂的；继续投票 */
      }
      schedule(DELAY_IDLE_MS)
    }

    poll()
    return () => {
      cancelled = true
      loopActive = false
      if (timer) clearTimeout(timer)
    }
  }, [ready])
}

function notify(sessionId: string, body: string): void {
  const { taskNotify, taskNotifySound } = useUIStore.getState()
  if (!taskNotify) return
  // 当没有会话名称时省略标题，以便主流程回退到
  // app.name 而不是硬编码的产品名称。
  const title = useSessionStore.getState().sessions.find((s) => s.session_id === sessionId)?.title
  window.electronAPI
    ?.notify?.({ title: title || undefined, body, sessionId, silent: !taskNotifySound })
    .catch(() => {})
}
