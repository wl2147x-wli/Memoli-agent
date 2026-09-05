import { useState, useEffect, useCallback, useRef } from 'react'
import type { BackendErrorCode } from '../types'

// 首选端口 — 必须与 main/python-manager.ts 中的 DESKTOP_BACKEND_PORT 匹配。
// 这只是探测的开始猜测：主要流程可能会回退到
// 当此端口无法绑定时使用另一个端口（Windows 保留端口范围
// Hyper-V/WSL2），它通过 getBackendPort / the
// “开始”后端状态事件。总是更喜欢这个而不是这个常数。
const BACKEND_PORT = 9876

// 健康的后端会在几秒钟内做出响应；崩溃立即退出并且
// 楔入的一个被 app.py 中的看门狗杀死，因此两种真正的故障模式
// 在此之前，我们已收到错误事件。它仅限制以下情况
// 该事件永远不会到来，空白的旋转器很快就会显示为损坏的应用程序。
// 梯子中的最后一个（后端看门狗 < 主进程探针 < 这个），所以
// 最具体的错误总是首先出现在屏幕上。
const GIVE_UP_AFTER_MS = 40_000
// 足够长，不会在正常冷启动时触发，足够短，用户
// 即将强制退出时，看到应用程序承认出现了问题。
const SLOW_START_AFTER_MS = 15_000

// 安装本身的失败。他们没有什么可以改善的
// 等待，所以他们完全跳过轮询截止日期：可执行文件不是
// 将重新出现，在说这句话之前旋转 40 秒是 40
// 假设应用程序只是运行缓慢，用户花费的秒数。
const UNRECOVERABLE_CODES: ReadonlySet<string> = new Set<BackendErrorCode>([
  'backend_removed',
  'backend_missing',
  'backend_blocked',
])

interface BackendState {
  status: 'connecting' | 'ready' | 'error'
  port: number
  error?: string
  code?: BackendErrorCode
  path?: string
  slow?: boolean
  // 确实，当我们恢复已经准备好的后端时，所以
  // 状态屏幕可以显示“正在重新连接”而不是“正在启动”。
  reconnecting?: boolean
}

export function useBackend() {
  const [state, setState] = useState<BackendState>({
    status: 'connecting',
    port: BACKEND_PORT,
  })
  const pollingRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const probeBackend = useCallback(async (port: number): Promise<boolean> => {
    try {
      // 探测未经身份验证的运行状况端点，而不是 /config：一次
      // web_password 已设置，/config 返回 401，我们会错误地对待
      // （健康）后端无法访问，挂在“连接”状态。
      const res = await fetch(`http://127.0.0.1:${port}/api/health`, {
        signal: AbortSignal.timeout(3000),
      })
      return res.ok
    } catch {
      return false
    }
  }, [])

  // 一旦后端至少应答一次，则为真。此后我们再也不会翻转
  // 回到轮询的“错误”——隐藏/背景窗口限制 JS
  // 计时器，因此尝试计数器不可靠，否则会产生
  // false“无法启动”，即使后端处于活动状态。
  const readyRef = useRef(false)
  // 保存最新解析的端口，以便可见性处理程序（注册一次）
  // 始终探测正确的端口而不重新运行效果。
  const portRef = useRef(BACKEND_PORT)

  useEffect(() => {
    let cancelled = false
    let offStatus: (() => void) | undefined
    const api = window.electronAPI

    // 使用挂钟截止时间而不是尝试计数器，以便计时器
    // 节流（当窗口位于后台时）无法快进
    // 陷入虚假的失败。只有当我们确实无法达到目标时才放弃
    // 后台搞了这么久。
    // 我们当前正在轮询的端口以及即将退休的一代计数器
    // 被取代的循环。 IPC 结果和“开始”事件都报告
    // 端口，通常是同一个端口，第一个探测需要几秒钟——没有
    // 这样，重复的调用将针对同一端口产生第二个循环。
    let activePort: number | null = null
    let pollGeneration = 0

    const startPolling = async (port: number) => {
      if (activePort === port) return
      activePort = port
      const generation = ++pollGeneration
      if (pollingRef.current) {
        clearTimeout(pollingRef.current)
        pollingRef.current = null
      }
      portRef.current = port
      setState((prev) => (prev.port === port ? prev : { ...prev, port }))
      const startedAt = Date.now()
      const deadline = startedAt + GIVE_UP_AFTER_MS

      const poll = async () => {
        if (cancelled || generation !== pollGeneration) return

        const ready = await probeBackend(port)
        // 探测器是异步的：端口交换机可能在处于状态时已着陆
        // 飞行，在这种情况下，这个循环是陈旧的，不能报告状态。
        if (cancelled || generation !== pollGeneration) return

        if (ready) {
          readyRef.current = true
          activePort = null
          setState({ status: 'ready', port })
          return
        }

        // 询问主进程是否已经放弃。这是一个拉力，
        // 所以无论失败何时发生，相对于我们的
        // 订阅，它可以报告损坏的安装
        // 在得知结果的那一刻，而不是在完整的投票截止日期之后。
        const failure = !readyRef.current ? await api?.getBackendError?.().catch(() => null) : null
        if (cancelled || generation !== pollGeneration) return
        if (failure && UNRECOVERABLE_CODES.has(failure.code)) {
          activePort = null
          setState({ status: 'error', port, error: failure.message, code: failure.code, path: failure.path })
          return
        }

        // 后端之前已应答，但短暂无法访问（例如
        // 窗口睡着了）：继续重试，永远不会出现错误。
        if (!readyRef.current && Date.now() >= deadline) {
          activePort = null
          // 更喜欢主进程知道的任何内容：它的诊断名称
          // 实际原因，而局部回退只能说
          // 出了问题。
          setState((prev) => ({
            ...prev,
            status: 'error',
            port,
            error: failure?.message ?? prev.error,
            code: failure?.code ?? prev.code,
            path: failure?.path ?? prev.path,
          }))
          return
        }

        if (!readyRef.current && Date.now() - startedAt >= SLOW_START_AFTER_MS) {
          setState((prev) => (prev.slow ? prev : { ...prev, slow: true }))
        }

        pollingRef.current = setTimeout(poll, 1000)
      }

      await poll()
    }

    if (api) {
      // 立即在首选端口上启动，无需等待 IPC：
      // 探索是通往“准备就绪”的自给自足的道路，绝不能依赖于
      // 往返成功（否则应用程序可能会挂在“连接”状态）。
      // IPC 结果和“开始”事件都将我们重定向到真实的
      // 如果主进程必须退回到另一个进程，则使用该端口。
      startPolling(BACKEND_PORT)

      api
        .getBackendPort()
        .then((port) => {
          if (port) startPolling(port)
        })
        .catch(() => {
          // 首选端口轮询已在运行；没有什么可恢复的。
        })

      offStatus = api.onBackendStatus((data) => {
        if (data.status === 'ready' && data.port) {
          readyRef.current = true
          portRef.current = data.port
          setState({ status: 'ready', port: data.port })
          // 退出轮询循环，以便稍后重新启动可以启动新的轮询循环。
          pollGeneration++
          activePort = null
          if (pollingRef.current) {
            clearTimeout(pollingRef.current)
            pollingRef.current = null
          }
        } else if (data.status === 'starting' && data.port) {
          startPolling(data.port)
        } else if (data.status === 'lost') {
          // 主进程发现先前准备好的后端无法访问，并且是
          // 重新启动它。释放就绪闩锁：按住它会保持
          // 整个 UI 安装在一个不回答任何问题的后端，即
          // 死掉的后端如何在任何地方都显示为“无法获取”。
          readyRef.current = false
          pollGeneration++
          activePort = null
          if (pollingRef.current) {
            clearTimeout(pollingRef.current)
            pollingRef.current = null
          }
          setState((prev) => ({
            ...prev,
            status: 'connecting',
            reconnecting: true,
            error: undefined,
            slow: false,
          }))
        } else if (data.status === 'error' && !readyRef.current) {
          // 一旦我们准备好，就忽略主流程中的晚期“错误” -
          // 这通常意味着窗口是背景的，而不是真正的失败。
          // 保留消息和代码：将它们放在一起是唯一的诊断方法
          // 当 UI 从未出现时，用户就会执行此操作。
          setState((prev) => ({ ...prev, status: 'error', error: data.error, code: data.code, path: data.path }))
        }
      })
    } else {
      startPolling(BACKEND_PORT)
    }

    // 当窗口回到前台时，立即重新探测，以便
    // 一段时间后返回的用户立即看到真正的（就绪）状态
    // 而不是等待节流计时器赶上。
    const onVisible = () => {
      if (cancelled || document.visibilityState !== 'visible') return
      probeBackend(portRef.current).then((ready) => {
        if (cancelled || !ready) return
        readyRef.current = true
        setState((prev) => ({ ...prev, status: 'ready' }))
      })
    }
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      cancelled = true
      if (pollingRef.current) {
        clearTimeout(pollingRef.current)
      }
      offStatus?.()
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [probeBackend])

  const restart = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'connecting', error: undefined, code: undefined, path: undefined, slow: false }))
    if (window.electronAPI) {
      await window.electronAPI.restartBackend()
    }
  }, [])

  const baseUrl = `http://127.0.0.1:${state.port}`

  return { ...state, baseUrl, restart }
}
