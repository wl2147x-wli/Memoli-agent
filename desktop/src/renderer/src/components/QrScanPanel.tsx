import React, { useEffect, useRef, useState } from 'react'
import { Loader2, Check, RotateCcw } from 'lucide-react'
import { t } from '../i18n'
import apiClient from '../api/client'

type Provider = 'weixin' | 'feishu'
// 'downloading'：仅限飞书，在二维码存在之前获取 SDK 包。
type Phase = 'loading' | 'downloading' | 'waiting' | 'scanned' | 'success' | 'error'

interface QrScanPanelProps {
  provider: Provider
  // 连接通道后触发，以便页面可以刷新。
  onConnected: () => void
  // 仅限多代理：当为 true 时，成功扫描后的连接
  // 创建一个新的通道实例（instance_id ''）而不是编辑
  // 单一遗产之一。 Undefined/false 保留旧的单实例路径。
  newInstance?: boolean
}

const POLL_INTERVAL = 2000

// 共享内嵌二维码面板，用于微信登录和飞书应用注册。镜子
// Web 控制台：获取 QR，轮询其状态，然后连接通道。的
// 面板安装后立即开始扫描，以便调用者决定何时显示
// 它而不是连接一个单独的“开始”按钮。
const QrScanPanel: React.FC<QrScanPanelProps> = ({ provider, onConnected, newInstance }) => {
  // 铸造新实例时，传递instance_id ''；否则省略它，所以
  // 旧的每种类型路径保持不变。
  const instanceArg = newInstance ? '' : undefined
  const [phase, setPhase] = useState<Phase>('loading')
  const [qr, setQr] = useState('')
  const [openLink, setOpenLink] = useState('')
  const [errMsg, setErrMsg] = useState('')
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const aliveRef = useRef(true)

  const stopPoll = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  const fail = (msg: string) => {
    if (!aliveRef.current) return
    setPhase('error')
    setErrMsg(msg)
  }

  // ----微信：GET qr，POST投票{已扫描|已确认|已过期} -----------------
  const pollWeixin = () => {
    timerRef.current = setTimeout(async () => {
      if (!aliveRef.current) return
      try {
        const data = await apiClient.weixinQrAction('poll')
        if (!aliveRef.current) return
        if (data.status !== 'success') return pollWeixin()
        const s = data.qr_status as string
        if (s === 'confirmed') {
          setPhase('success')
          await apiClient.channelAction('connect', 'weixin', {}, instanceArg)
          if (aliveRef.current) onConnected()
        } else if (s === 'expired' && (data.qr_image || data.qrcode_url)) {
          setQr((data.qr_image as string) || (data.qrcode_url as string))
          setPhase('waiting')
          pollWeixin()
        } else if (s === 'scaned') {
          setPhase('scanned')
          pollWeixin()
        } else {
          pollWeixin()
        }
      } catch {
        pollWeixin()
      }
    }, POLL_INTERVAL)
  }

  // ----微信、跑步频道拥有的二维码------------------------------
  // 失去登录的直播频道会运行自己的扫描循环，因此控制台
  // 没有要轮询的 QR 会话 — 请查看通道的 login_status。的
  // 当旧的 QR 过期时，频道还会交换新的 QR，因此请重新阅读
  // 每几个刻度。

  // 一旦通道放弃自己的扫描循环并且
  // 相反，控制台拥有 QR 会话，因此轮询必须切换。
  const refreshChannelQr = async (): Promise<boolean> => {
    try {
      const data = await apiClient.getWeixinQr()
      if (!aliveRef.current || data.status !== 'success') return true
      const img = data.qr_image || data.qrcode_url
      if (img) setQr(img)
      return data.source === 'channel'
    } catch {
      return true
    }
  }

  const pollWeixinChannel = (tick = 0) => {
    timerRef.current = setTimeout(async () => {
      if (!aliveRef.current) return
      let handedOver = false
      try {
        const list = await apiClient.getChannels()
        if (!aliveRef.current) return
        const wx = list?.find((c) => c.name === 'weixin')
        if (wx?.login_status === 'logged_in') {
          setPhase('success')
          onConnected()
          return
        }
        setPhase(wx?.login_status === 'scanned' ? 'scanned' : 'waiting')
        if (tick % 5 === 4) handedOver = !(await refreshChannelQr())
      } catch {
        // 继续关注：短暂的 API 故障不应该终止面板。
      }
      if (!aliveRef.current) return
      if (handedOver) pollWeixin()
      else pollWeixinChannel(tick + 1)
    }, POLL_INTERVAL)
  }

  const startWeixin = async () => {
    setPhase('loading')
    try {
      const data = await apiClient.getWeixinQr()
      if (!aliveRef.current) return
      if (data.status !== 'success') return fail(data.message || t('weixin_scan_fail'))
      setQr(data.qr_image || data.qrcode_url || '')
      setPhase('waiting')
      if (data.source === 'channel') pollWeixinChannel()
      else pollWeixin()
    } catch {
      fail(t('weixin_scan_fail'))
    }
  }

  // ---- 飞书: GET qr, POST poll {done|expired|denied|error} ----------------
  const pollFeishu = () => {
    timerRef.current = setTimeout(async () => {
      if (!aliveRef.current) return
      try {
        const data = await apiClient.feishuRegisterPoll()
        if (!aliveRef.current) return
        if (data.status !== 'success') return fail((data.message as string) || t('feishu_scan_fail'))
        const rs = data.register_status as string
        if (rs === 'downloading') {
          setPhase('downloading')
          return pollFeishu()
        }
        // 二维码可能仅在捆绑包下载完成后出现，在
        // 这种情况下初始的GET就无法携带它。
        const img = (data.qr_image as string) || (data.qrcode_url as string)
        if (img) {
          setQr(img)
          setOpenLink((data.qrcode_url as string) || '')
          setPhase((p) => (p === 'downloading' ? 'waiting' : p))
        }
        if (rs === 'done') {
          setPhase('success')
          await apiClient.channelAction(
            'connect',
            'feishu',
            {
              feishu_app_id: data.app_id,
              feishu_app_secret: data.app_secret,
            },
            instanceArg
          )
          if (aliveRef.current) onConnected()
        } else if (rs === 'expired') {
          fail(t('feishu_scan_expired'))
        } else if (rs === 'denied') {
          fail(t('feishu_scan_denied'))
        } else if (rs === 'error') {
          fail((data.message as string) || t('feishu_scan_fail'))
        } else {
          pollFeishu()
        }
      } catch {
        pollFeishu()
      }
    }, POLL_INTERVAL)
  }

  const startFeishu = async () => {
    setPhase('loading')
    try {
      const data = await apiClient.getFeishuRegister()
      if (!aliveRef.current) return
      if (data.status !== 'success') return fail(data.message || t('feishu_scan_fail'))
      if (data.register_status === 'downloading') {
        // 首次在桌面版本中运行：SDK 捆绑包位于 QR 之前。
        setPhase('downloading')
        return pollFeishu()
      }
      setQr(data.qr_image || data.qrcode_url || '')
      setOpenLink(data.qrcode_url || '')
      setPhase('waiting')
      pollFeishu()
    } catch {
      fail(t('feishu_scan_fail'))
    }
  }

  const start = () => {
    stopPoll()
    if (provider === 'weixin') void startWeixin()
    else void startFeishu()
  }

  useEffect(() => {
    aliveRef.current = true
    start()
    return () => {
      aliveRef.current = false
      stopPoll()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider])

  const isWeixin = provider === 'weixin'
  const desc = isWeixin ? t('weixin_scan_desc') : t('feishu_scan_desc')
  const tip = isWeixin ? t('weixin_qr_tip') : t('feishu_scan_tip')
  const statusText = isWeixin
    ? phase === 'scanned'
      ? t('weixin_scan_scanned')
      : t('weixin_scan_waiting')
    : t('feishu_scan_waiting')

  return (
    <div className="flex flex-col items-center py-2">
      {phase === 'loading' && (
        <div className="flex items-center text-content-tertiary py-10 text-sm">
          <Loader2 size={16} className="animate-spin mr-2" />
          {isWeixin ? t('weixin_scan_loading') : t('feishu_scan_loading')}
        </div>
      )}

      {phase === 'downloading' && (
        <div className="flex flex-col items-center py-10">
          <div className="flex items-center text-content-tertiary text-sm">
            <Loader2 size={16} className="animate-spin mr-2" />
            {t('feishu_sdk_downloading')}
          </div>
          <p className="text-xs text-content-tertiary mt-2">{t('feishu_sdk_downloading_tip')}</p>
        </div>
      )}

      {(phase === 'waiting' || phase === 'scanned') && (
        <>
          <p className="text-sm text-content-secondary mb-3 text-center">{desc}</p>
          <div className="bg-white p-2.5 rounded-card border border-subtle mb-3">
            {qr ? (
              <img src={qr} alt="QR" className="w-44 h-44" style={{ imageRendering: 'pixelated' }} />
            ) : (
              <div className="w-44 h-44 flex items-center justify-center text-content-tertiary text-xs">QR</div>
            )}
          </div>
          <p className={`text-xs mb-1 ${phase === 'scanned' ? 'text-accent' : 'text-warning'}`}>{statusText}</p>
          <p className="text-xs text-content-tertiary">{tip}</p>
          {openLink && (
            <a
              href={openLink}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-info hover:underline mt-2"
            >
              {t('feishu_scan_open_link')}
            </a>
          )}
        </>
      )}

      {phase === 'success' && (
        <div className="flex flex-col items-center py-8">
          <div className="w-12 h-12 rounded-full bg-accent-soft flex items-center justify-center mb-3">
            <Check size={22} className="text-accent" />
          </div>
          <p className="text-sm font-medium text-accent">
            {isWeixin ? t('weixin_scan_success') : t('feishu_scan_success')}
          </p>
        </div>
      )}

      {phase === 'error' && (
        <div className="flex flex-col items-center py-8">
          <p className="text-sm text-danger text-center mb-3">{errMsg}</p>
          <button
            onClick={start}
            className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-btn border border-strong text-sm text-content-secondary hover:bg-inset-2 cursor-pointer transition-colors"
          >
            <RotateCcw size={13} />
            {t('feishu_scan_retry')}
          </button>
        </div>
      )}
    </div>
  )
}

export default QrScanPanel
