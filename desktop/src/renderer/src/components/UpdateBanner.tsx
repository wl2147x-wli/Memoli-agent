import React from 'react'
import { Download, RefreshCw, X, Loader2, AlertTriangle, FileText } from 'lucide-react'
import { t, getLang } from '../i18n'
import { useUpdateStore, hasAvailableUpdate } from '../store/updateStore'
import { product } from '@product'

// 版本的“新增内容”页面。产品构建可以指出这一点
// 自己的文档网站；默认是核心文档。在用户的浏览器中打开
// （window.open 由主进程通过 shell.openExternal 路由）。
function releaseNotesUrl(version: string): string {
  const lang = getLang()
  const override = product.links?.releaseNotesUrl?.(version, lang)
  if (override) return override
  const base = lang === 'zh' ? 'https://docs.cowagent.ai/zh' : 'https://docs.cowagent.ai'
  return `${base}/releases/v${version}`
}

// 紧凑的更新面板固定在 NavRail 页脚上。每当更新时显示
// 可用且面板已打开（检测到时自动打开，可通过
// “检查更新”）。关闭 (×) 只是将其关闭；菜单可以重新打开它。
const UpdateBanner: React.FC = () => {
  const state = useUpdateStore()
  const open = state.panelOpen

  const available = hasAvailableUpdate(state)
  const status = state.status
  const errored = status?.state === 'error'

  // 全屏“正在安装...”覆盖：桥接原本空白的窗口
  // 在单击“重新启动安装”和应用程序实际退出之间
  // 交换捆绑包。 （退出之后、重新启动之前的差距是操作系统级别的，
  // 无法覆盖。）
  if (state.installing) {
    return (
      <div className="fixed inset-0 z-[100] flex flex-col items-center justify-center gap-3 bg-base/90 backdrop-blur-sm">
        <Loader2 size={28} className="animate-spin text-accent" />
        <p className="text-sm text-content-secondary">{t('update_installing')}</p>
      </div>
    )
  }

  // 当面板打开并且我们知道有更新或点击时显示面板
  // 错误。保持错误状态很重要：失败的下载必须浮出水面
  // 一条可见的信息，而不是默默地什么也不做。
  if (!open || (!available && !errored)) return null

  const version = state.version
  const preparing = state.preparing
  const downloading = status?.state === 'downloading'
  const downloaded = status?.state === 'downloaded'
  // macOS 在达到 100% 后发出第二个进度传递（验证）；显示为
  // 不确定的“验证”状态而不是从 0 重新开始的条。
  const verifying = downloading && state.progressPeaked
  const busy = preparing || downloading

  return (
    <div className="absolute bottom-2 left-2 right-2 z-40">
      <div className="rounded-lg border border-default bg-elevated shadow-lg p-3 space-y-2.5">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[13px] font-semibold text-content min-w-0 truncate">
            {errored ? t('update_failed') : t('update_available')}
          </p>
          <button
            onClick={() => state.dismiss()}
            className="text-content-tertiary hover:text-content cursor-pointer flex-shrink-0"
            title={t('update_later')}
          >
            <X size={15} />
          </button>
        </div>

          {errored && (
            <div className="space-y-2.5">
              <div className="flex items-start gap-2 text-xs text-content-secondary">
                <AlertTriangle size={13} className="text-amber-500 flex-shrink-0 mt-0.5" />
                <span className="break-words">
                  {status?.state === 'error' ? status.message : ''}
                </span>
              </div>
              <button
                onClick={() => state.download()}
                className="w-full inline-flex items-center justify-center gap-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover px-3 py-2 text-[13px] font-medium cursor-pointer transition-colors"
              >
                <RefreshCw size={15} />
                {t('update_retry')}
              </button>
            </div>
          )}

          {!errored && preparing && (
            <div className="flex items-center gap-2 text-xs text-content-secondary py-1">
              <Loader2 size={13} className="animate-spin" />
              <span>{t('update_preparing')}</span>
            </div>
          )}

          {!errored && downloading && verifying && (
            <div className="flex items-center gap-2 text-xs text-content-secondary py-1">
              <Loader2 size={13} className="animate-spin" />
              <span>{t('update_verifying')}</span>
            </div>
          )}

          {!errored && downloading && !verifying && (
            <div className="space-y-1">
              <div className="flex items-center gap-2 text-xs text-content-secondary">
                <Loader2 size={13} className="animate-spin" />
                <span>{t('update_downloading')} {state.percent}%</span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-surface-2 overflow-hidden">
                <div className="h-full bg-accent transition-[width] duration-200" style={{ width: `${state.percent}%` }} />
              </div>
            </div>
          )}

          {!errored && !busy && !downloaded && (
            <div className="space-y-2">
              {version && (
                <div className="flex items-center justify-between gap-2 text-xs">
                  <span className="text-content-tertiary">v{version}</span>
                  <button
                    onClick={() => window.open(releaseNotesUrl(version), '_blank', 'noopener,noreferrer')}
                    className="inline-flex items-center gap-1 text-content-tertiary hover:text-content-secondary hover:underline cursor-pointer transition-colors"
                  >
                    <FileText size={12} />
                    {t('update_release_notes')}
                  </button>
                </div>
              )}
              <button
                onClick={() => state.download()}
                className="w-full inline-flex items-center justify-center gap-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover px-3 py-2 text-[13px] font-medium cursor-pointer transition-colors"
              >
                <Download size={15} />
                {t('update_download')}
              </button>
            </div>
          )}

          {!errored && downloaded && (
            <button
              onClick={() => state.install()}
              className="w-full inline-flex items-center justify-center gap-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover px-3 py-2 text-[13px] font-medium cursor-pointer transition-colors"
            >
              <RefreshCw size={15} />
              {t('update_restart')}
            </button>
          )}
        </div>
    </div>
  )
}

export default UpdateBanner
