import { create } from 'zustand'
import type { UpdateStatus } from '../types'
import { getLang } from '../i18n'

interface UpdateState {
  status: UpdateStatus | null
  /** Latest available version, kept across download progress updates. */
  version: string | null
  /** Download progress 0-100 while state === 'downloading'. */
  percent: number
  /** User clicked "download" but no progress event has arrived yet. Gives the
   *  button an instant busy state so it can't be clicked again during the 1-2s
   *  lead-up to the first progress event. Cleared on the first 'downloading'. */
  preparing: boolean
  /** The download progress already reached ~100% once. macOS (Squirrel.Mac)
   *  emits a SECOND progress pass (verify / block-map) after the first, which
   *  used to make the bar visibly restart from 0. Once peaked we render an
   *  indeterminate "verifying" state instead of a confusing second bar. */
  progressPeaked: boolean
  /** User clicked "restart to install"; show a full-screen "installing…"
   *  overlay for the brief window before the app quits to swap the bundle. */
  installing: boolean
  /** User dismissed the badge for this version (don't nag again until next). */
  dismissedVersion: string | null
  /** Whether the update panel is currently shown. Lifted here so the "check
   *  for update" menu item can re-open it on demand. */
  panelOpen: boolean

  setStatus: (s: UpdateStatus) => void
  /** Dismiss the floating badge/panel for the current version (footer dot goes
   *  away), but keep the update itself known so the menu can still surface it. */
  dismiss: () => void
  openPanel: () => void
  closePanel: () => void
  /** User explicitly clicked "check for update": ask main to re-check, and if
   *  an update is already known, re-open the panel immediately (undismiss). */
  recheck: () => void

  // 通过预加载桥代理到主进程的操作。
  download: () => void
  install: () => void
}

export const useUpdateStore = create<UpdateState>((set, get) => ({
  status: null,
  version: null,
  percent: 0,
  preparing: false,
  progressPeaked: false,
  installing: false,
  dismissedVersion: null,
  panelOpen: false,

  setStatus: (s) =>
    set((st) => {
      if (s.state === 'available') {
        // 每个版本自动打开一次面板，但不要唠叨：自动
        // 检查（启动/4小时轮询）是否找到用户已经存在的版本
        // 关闭后，面板关闭，仅使点保持点亮。一个
        // 不同（较新）版本，或明确的“检查更新”点击
        // （用户启动），重新打开它。 recheck() 清除解雇版本，所以
        // 手动检查也始终满足“未驳回”条件。
        const alreadyDismissed = st.dismissedVersion === s.version
        const shouldOpen = s.userInitiated === true || !alreadyDismissed
        return {
          status: s,
          version: s.version,
          percent: 0,
          preparing: false,
          progressPeaked: false,
          panelOpen: shouldOpen,
        }
      }
      if (s.state === 'downloading') {
        // 第一个真正的进度事件清除“准备”忙碌状态。追踪
        // 当我们达到 ~100% 时，Squirrel.Mac 第二遍渲染为
        // 不确定的“验证”状态，而不是从 0 重新开始的条。
        const peaked = st.progressPeaked || s.percent >= 99
        return { status: s, percent: s.percent, preparing: false, progressPeaked: peaked }
      }
      if (s.state === 'downloaded')
        return { status: s, version: s.version, percent: 100, preparing: false }
      if (s.state === 'error') return { status: s, preparing: false, installing: false }
      return { status: s }
    }),

  dismiss: () => set((st) => ({ dismissedVersion: st.version, panelOpen: false })),
  openPanel: () => set({ panelOpen: true }),
  closePanel: () => set({ panelOpen: false }),

  recheck: () => {
    // 清除任何关闭，以便已知的更新再次出现。只能重新打开面板
    // 当更新实际存在时 - 如果我们已经是最新的，打开
    // 面板只会闪烁它（横幅不会呈现不可用的任何内容）
    // 并且“最新”反馈属于菜单，而不是面板。菜单
    // (NavRail)据此决定是否关闭自身+显示面板。
    const known = hasAvailableUpdate(get())
    set({ dismissedVersion: null, panelOpen: known })
    // 也始终进行新的检查（选择较新的版本/恢复错误）。
    // 通过 UI 语言，以便相应地下载到中国 CDN/R2 的路线。
    window.electronAPI?.checkForUpdate?.(getLang())
  },

  download: () => {
    // 立即进入忙碌状态，这样按钮就不能在该状态下被点击两次
    // 我们等待（1-2 秒）第一个下载进度事件到达。
    set({ preparing: true, progressPeaked: false })
    window.electronAPI?.downloadUpdate?.(getLang())
  },
  install: () => {
    // 在应用程序退出以交换捆绑包之前显示“正在安装...”叠加层。
    set({ installing: true })
    window.electronAPI?.installUpdate?.()
  },
}))

// 订阅主进程更新事件。返回取消订阅 fn。
export function initUpdateListener(): (() => void) | undefined {
  return window.electronAPI?.onUpdateStatus?.((status) => {
    useUpdateStore.getState().setStatus(status as UpdateStatus)
  })
}

// 更新是否存在（可用/正在下载/已下载），
// 不论解雇。驱动“检查更新”菜单项的点，该点
// 只要更新实际可用，就应该持续存在。
export function hasAvailableUpdate(state: UpdateState): boolean {
  const s = state.status
  if (!s) return false
  return s.state === 'available' || s.state === 'downloading' || s.state === 'downloaded'
}

// 是否应在浮动页脚徽章中显示新版本：
// 该版本可用且不会被驳回。解雇仅隐藏这一点，
// 不是菜单点（hasAvailableUpdate）。
export function hasPendingUpdate(state: UpdateState): boolean {
  return hasAvailableUpdate(state) && state.dismissedVersion !== state.version
}
