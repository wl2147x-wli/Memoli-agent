import { create } from 'zustand'

// 入门是配置驱动的：只要聊天模型，向导就会自动打开
// 尚未配置，一旦配置就停止出现 - 没有持续的“看到”
// 可能会使未完成设置而跳过的用户陷入困境的标志。
//
// `dismissedThisSession` 是内存中的保护，因此跳过不会
// 在同一次运行中立即重新打开向导；重新启动时会重置，
// 因此，未配置的应用程序下次会再次引导用户。

interface OnboardingState {
  // 向导叠加层当前是否可见。
  open: boolean
  // 如果用户在此应用程序会话期间跳过/完成（未持久），则为 True。
  dismissedThisSession: boolean
  // 决定是否在启动时自动打开。仅在不聊天时打开
  // 已配置并且在本次会议之前没有被驳回。
  maybeOpen: (chatConfigured: boolean) => void
  // 手动打开（例如，稍后从“设置指南”入口点）。
  openWizard: () => void
  // 完成/跳过：关闭并且不自动重新打开此会话。
  finish: () => void
  // 关闭而不标记被驳回（很少使用；保持对称）。
  close: () => void
}

export const useOnboardingStore = create<OnboardingState>((set) => ({
  open: false,
  dismissedThisSession: false,

  maybeOpen: (chatConfigured) =>
    set((s) => {
      if (chatConfigured || s.dismissedThisSession) return { open: false }
      return { open: true }
    }),

  openWizard: () => set({ open: true }),

  finish: () => set({ open: false, dismissedThisSession: true }),

  close: () => set({ open: false }),
}))
