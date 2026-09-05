import React, { useCallback, useEffect, useState } from 'react'
import { t } from '../i18n'
import { product } from '@product'
import type { BackendErrorCode } from '../types'

interface StatusScreenProps {
  status: 'connecting' | 'error'
  error?: string
  // 为什么启动失败（已知）。驱动说明和建议：
  // 隔离的可执行文件和崩溃的可执行文件需要完全不同
  // 来自用户的东西，而一个通用的句子则无济于事。
  code?: BackendErrorCode
  // 失败的文件（通常是丢失的可执行文件）。如此所示
  // 用户可以在其防病毒隔离列表中准确查找该名称。
  path?: string
  slow?: boolean
  // 恢复已经在服务的后端，而不是冷的
  // 开始 - 副本有所不同，因为用户正在会话中。
  reconnecting?: boolean
  onRetry: () => void
}

// 按原因复制。此处未列出的任何内容（或来自较新版本的未知代码）
// 主进程）退回到通用对。
const CAUSE_COPY: Record<BackendErrorCode, { desc: string; hint: string }> = {
  backend_removed: { desc: 'status_error_removed_desc', hint: 'status_error_removed_hint' },
  backend_missing: { desc: 'status_error_missing_desc', hint: 'status_error_missing_hint' },
  backend_blocked: { desc: 'status_error_blocked_desc', hint: 'status_error_blocked_hint' },
  backend_crashed: { desc: 'status_error_crashed_desc', hint: 'status_error_hint' },
  backend_timeout: { desc: 'status_error_timeout_desc', hint: 'status_error_hint' },
  backend_unresponsive: { desc: 'status_error_unresponsive_desc', hint: 'status_error_hint' },
}

const StatusScreen: React.FC<StatusScreenProps> = ({ status, error, code, path, slow, reconnecting, onRetry }) => {
  const [dataDir, setDataDir] = useState('')
  const copy = (code && CAUSE_COPY[code]) || { desc: 'status_error_desc', hint: 'status_error_hint' }

  useEffect(() => {
    if (status !== 'error') return
    window.electronAPI?.getDataDir().then(setDataDir).catch(() => setDataDir(''))
  }, [status])

  const openLogs = useCallback(() => {
    if (!dataDir) return
    void window.electronAPI?.openPath(dataDir)
  }, [dataDir])

  return (
    <div className="h-screen w-screen flex items-center justify-center bg-gray-50 dark:bg-[#111111]">
      <div className="text-center space-y-6 max-w-md px-8">
        {product.slots?.StatusLogo ? (
          <div className="w-16 h-16 rounded-2xl mx-auto shadow-lg shadow-primary-500/20 overflow-hidden">
            <product.slots.StatusLogo />
          </div>
        ) : (
          <img src="./logo.jpg" alt="Agent" className="w-16 h-16 rounded-2xl mx-auto shadow-lg shadow-primary-500/20" />
        )}

        {status === 'connecting' && (
          <>
            <div className="space-y-2">
              <h1 className="text-xl font-bold text-slate-800 dark:text-slate-100">
                {reconnecting ? t('status_reconnecting') : t('status_starting')}
              </h1>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {slow
                  ? t('status_starting_slow')
                  : reconnecting
                    ? t('status_reconnecting_desc')
                    : t('status_starting_desc')}
              </p>
            </div>
            <div className="flex justify-center gap-1">
              <span className="w-2 h-2 rounded-full bg-primary-400 animate-pulse-dot" style={{ animationDelay: '0s' }} />
              <span className="w-2 h-2 rounded-full bg-primary-400 animate-pulse-dot" style={{ animationDelay: '0.2s' }} />
              <span className="w-2 h-2 rounded-full bg-primary-400 animate-pulse-dot" style={{ animationDelay: '0.4s' }} />
            </div>
          </>
        )}

        {status === 'error' && (
          <>
            <div className="space-y-2">
              <h1 className="text-xl font-bold text-slate-800 dark:text-slate-100">
                {t('status_error')}
              </h1>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {t(copy.desc)}
              </p>
            </div>

            {/* 失败的文件。对于隔离的可执行文件，此
                是屏幕上最有用的东西：它的名字
                在防病毒隔离列表中查找。 */}
            {path && (
              <p className="text-xs text-left break-all text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-white/5 rounded-lg px-3 py-2">
                <span className="block mb-1 text-slate-400 dark:text-slate-500">{t('status_error_file')}</span>
                <span className="font-mono">{path}</span>
              </p>
            )}

            {/* 后端自己的错误行。没有它，用户就无法联系
                （未启动的）UI 无法查看失败的原因。 */}
            {error && (
              <p className="text-xs text-left font-mono break-words text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-white/5 rounded-lg px-3 py-2 max-h-32 overflow-auto">
                {error}
              </p>
            )}

            <div className="flex justify-center gap-2">
              <button
                onClick={onRetry}
                className="inline-flex items-center gap-2 px-4 py-2 bg-primary-500 hover:bg-primary-600 text-white rounded-lg transition-colors text-sm font-medium cursor-pointer"
              >
                <i className="fas fa-rotate-right text-xs" />
                {t('status_retry')}
              </button>
              {dataDir && (
                <button
                  onClick={openLogs}
                  className="inline-flex items-center gap-2 px-4 py-2 border border-slate-300 dark:border-white/15 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-white/5 rounded-lg transition-colors text-sm font-medium cursor-pointer"
                >
                  <i className="fas fa-folder-open text-xs" />
                  {t('status_open_logs')}
                </button>
              )}
            </div>

            <p className="text-xs text-slate-400 dark:text-slate-500">{t(copy.hint)}</p>
          </>
        )}
      </div>
    </div>
  )
}

export default StatusScreen
