import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Loader2,
  Plug,
  Plus,
  X,
  ChevronDown,
  Check,
  MessageCircle,
  MessageSquare,
  Bot,
  Building2,
  Headset,
  Hash,
  AtSign,
  RadioTower,
  QrCode,
  KeyRound,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { t, localizedLabel, getLang } from '../i18n'
import apiClient from '../api/client'
import type { ChannelInfo, ChannelField } from '../types'
import { Toggle, Btn, FieldTip } from './settings/primitives'
import QrScanPanel from '../components/QrScanPanel'
import { PaperPlaneIcon } from '../components/icons'
import ChannelTeamSelect from '../components/ChannelTeamSelect'
import { useAgentStore } from '../store/agentStore'

// 通过 QR 扫描而不是凭证字段进行连接的通道。
const QR_PROVIDERS: Record<string, 'weixin' | 'feishu'> = { weixin: 'weixin', feishu: 'feishu' }

// 正在运行的微信频道会报告自己的登录状态，这并不总是
// 匹配“已连接”：它仍然可以启动，或者正在等待有人启动
// 扫描其二维码。其他任何东西（包括所有其他通道）都没有
// 待处理，并且仅显示为已连接。
type Pending = 'none' | 'scanning' | 'starting'

const pendingState = (ch: ChannelInfo): Pending => {
  const s = ch.login_status
  if (ch.name !== 'weixin' || !ch.active || !s || s === 'logged_in') return 'none'
  // 'idle'/'unknown' 表示通道仍在启动（连接处理程序
  // 启动前等待几秒钟）——不需要扫描。
  return s === 'waiting_scan' || s === 'scanned' ? 'scanning' : 'starting'
}

// 一个带有 `size` 属性的图标组件（清晰的图标和我们的 PaperPlaneIcon）。
type IconComponent = React.FC<{ size?: number }>

// 每通道图标 + 强调色，镜像 Web 控制台的 FontAwesome
// 图标 + Tailwind 调色板（我们在这里使用 lucide，具有十六进制颜色，因此
// 有色图标背景不会被 Tailwind 的 JIT 清除）。飞书/Telegram使用
// 与 Web 控制台相同的纸飞机。
const CHANNEL_STYLE: Record<string, { Icon: IconComponent; color: string }> = {
  weixin: { Icon: MessageCircle, color: '#10b981' },
  feishu: { Icon: PaperPlaneIcon, color: '#3b82f6' },
  dingtalk: { Icon: MessageSquare, color: '#3b82f6' },
  wecom_bot: { Icon: Bot, color: '#10b981' },
  qq: { Icon: MessageCircle, color: '#3b82f6' },
  wechatcom_app: { Icon: Building2, color: '#10b981' },
  wechat_kf: { Icon: Headset, color: '#10b981' },
  wechatmp: { Icon: MessageCircle, color: '#10b981' },
  telegram: { Icon: PaperPlaneIcon, color: '#0ea5e9' },
  slack: { Icon: Hash, color: '#a855f7' },
  discord: { Icon: AtSign, color: '#6366f1' },
}

const channelStyle = (name: string) => CHANNEL_STYLE[name] ?? { Icon: Plug, color: '#94a3b8' }

interface ChannelsPageProps {
  baseUrl: string
}

// 隐藏的秘密看起来像“abcd****wxyz”；后端会跳过这些值。
const MASK_RE = /\*{2,}/

const ChannelsPage: React.FC<ChannelsPageProps> = ({ baseUrl }) => {
  const [channels, setChannels] = useState<ChannelInfo[]>([])
  // 多代理附加功能。全部默认为单Agent形状（关闭/空），所以
  // 省略这些字段的遗留后端呈现与以前完全相同。
  const [multiAgent, setMultiAgent] = useState(false)
  const [multiInstanceTypes, setMultiInstanceTypes] = useState<string[]>([])
  const [instances, setInstances] = useState<ChannelInfo[]>([])
  const [loading, setLoading] = useState(true)
  // “添加频道”面板是否打开，以及其中选择的频道。
  // `selected` 开始为空，因此用户必须自己选择一个频道。
  const [addOpen, setAddOpen] = useState(false)
  const [selected, setSelected] = useState<string>('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  const isMultiInstanceType = (name: string) => multiInstanceTypes.includes(name)

  // `silent`刷新将当前列表保留在屏幕上（微信使用
  // 登录观察程序，不得每隔几秒闪烁一次旋转器）。
  const loadChannels = async (silent = false) => {
    try {
      if (!silent) setLoading(true)
      const data = await apiClient.getChannelsFull()
      setChannels(data.channels || [])
      setMultiAgent(!!data.multi_agent)
      setMultiInstanceTypes(data.multi_instance_types || [])
      setInstances(data.instances || [])
    } catch (err) {
      console.error('Failed to load channels:', err)
      if (!silent) {
        setChannels([])
        setMultiAgent(false)
        setMultiInstanceTypes([])
        setInstances([])
      }
    } finally {
      if (!silent) setLoading(false)
    }
  }

  // 语言切换时也重新获取：后端对列表进行排序
  // 我们询问时使用的语言，因此一旦发生变化，旧的响应就会过时。
  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    void loadChannels()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl, getLang()])

  // 当通道仍在稳定时（启动或等待可能会发生的扫描）
  // 发生在其他地方），轮询，使其卡自行翻转为“已连接”。
  const settling = channels.some((c) => pendingState(c) !== 'none')
  useEffect(() => {
    if (!settling) return
    const id = setInterval(() => void loadChannels(true), 3000)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settling])

  const { connected, available } = useMemo(() => {
    // 在多代理模式下，多实例就绪类型表示为
    // 来自 `instances` 的每个实例卡；他们的传统每种类型卡是
    // 从“已连接”中删除，因此带有两个机器人的飞书显示两张卡，而不是
    // 三.非多实例类型（以及单Agent模式）不变。
    const legacyConnected = channels.filter(
      (c) => c.active && !(multiAgent && isMultiInstanceType(c.name))
    )
    const connected: ChannelInfo[] = multiAgent
      ? [...legacyConnected, ...instances]
      : legacyConnected
    // 多实例就绪类型即使拥有实例也保持“可用”，
    // 因此用户可以添加第二个相同类型的机器人。
    const available = channels.filter(
      (c) => !c.active || (multiAgent && isMultiInstanceType(c.name))
    )
    return { connected, available }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channels, instances, multiAgent, multiInstanceTypes])

  // 如果所选通道已连接（或消失），请清除选择。
  useEffect(() => {
    if (selected && !available.some((c) => c.name === selected)) setSelected('')
  }, [available, selected])

  const openAdd = () => {
    setSelected('')
    setAddOpen(true)
    // 将新面板滚动到列表底部的视图中。
    requestAnimationFrame(() => {
      panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    })
  }

  const addingChannel = available.find((c) => c.name === selected)

  // 添加面板总是创建一个全新的实例，因此将其呈现为
  // 带有空白字段的未连接卡 — 绝不是存储的（屏蔽的）凭据
  // 相同类型的现有实例。
  const addChannelForPanel = (ch: ChannelInfo): ChannelInfo => {
    if (!(multiAgent && isMultiInstanceType(ch.name))) return ch
    return {
      ...ch,
      active: false,
      instance_id: undefined,
      agent_id: '',
      members: [],
      login_status: undefined,
      fields: ch.fields.map((f) => ({ ...f, value: f.type === 'bool' ? f.value : '' })),
    }
  }

  const onAdded = () => {
    setAddOpen(false)
    setSelected('')
    void loadChannels()
  }

  // 选择频道后，随着配置表单的增长，保持配置表单处于可见状态。
  useEffect(() => {
    if (selected) {
      requestAnimationFrame(() => {
        panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
      })
    }
  }, [selected])

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="px-6 pt-5 pb-3 flex-shrink-0 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-content">{t('channels_title')}</h2>
          <p className="text-xs text-content-tertiary mt-1">{t('channels_desc')}</p>
        </div>
        {!loading && available.length > 0 && !addOpen && (
          <Btn variant="primary" onClick={openAdd}>
            <span className="flex items-center gap-1.5">
              <Plus size={15} />
              {t('channels_add')}
            </span>
          </Btn>
        )}
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto border-t border-default">
        <div className="max-w-3xl mx-auto px-6 py-5">
          {loading ? (
            <div className="flex items-center justify-center py-20 text-content-tertiary">
              <Loader2 size={18} className="animate-spin mr-2" />
              {t('channels_loading')}
            </div>
          ) : (
            <div className="space-y-3">
              {connected.length === 0 && !addOpen ? (
                <div className="flex flex-col items-center justify-center text-center py-16 px-6">
                  <span className="w-16 h-16 rounded-2xl bg-info/10 flex items-center justify-center mb-4">
                    <RadioTower size={26} className="text-info" />
                  </span>
                  <p className="text-content-secondary font-medium">{t('channels_empty')}</p>
                  <p className="text-sm text-content-tertiary mt-1.5 max-w-sm leading-relaxed">
                    {t('channels_empty_desc')}
                  </p>
                  {available.length > 0 && (
                    <div className="mt-5">
                      <Btn variant="primary" onClick={openAdd}>
                        <span className="flex items-center gap-1.5">
                          <Plus size={15} />
                          {t('channels_add')}
                        </span>
                      </Btn>
                    </div>
                  )}
                </div>
              ) : (
                connected.map((ch) => (
                  <ChannelCard
                    key={ch.instance_id || ch.name}
                    channel={ch}
                    multiAgent={multiAgent}
                    onChanged={loadChannels}
                  />
                ))
              )}

              {/* 添加频道面板位于列表底部：选择一个
                  从下拉列表中选择通道，然后内联配置/连接它。 */}
              {addOpen && available.length > 0 && (
                <div ref={panelRef} className="rounded-card border border-accent/40 bg-surface p-4 space-y-4">
                  <div className="flex items-center justify-between gap-3">
                    <label className="text-sm font-medium text-content">{t('channels_select_label')}</label>
                    <button
                      onClick={() => setAddOpen(false)}
                      className="text-content-tertiary hover:text-content cursor-pointer"
                      title={t('channels_add_close')}
                    >
                      <X size={16} />
                    </button>
                  </div>
                  <ChannelDropdown
                    channels={available}
                    value={selected}
                    onChange={setSelected}
                    placeholder={t('channels_select_placeholder')}
                  />
                  {addingChannel && (
                    <ChannelCard
                      // For a multi-instance-ready type we always create a NEW
                      // instance from the add panel, so force a fresh card (no
                      // stored credentials, blank binding) with a stable key.
                      key={`add-${addingChannel.name}`}
                      channel={addChannelForPanel(addingChannel)}
                      multiAgent={multiAgent}
                      onChanged={onAdded}
                      defaultExpanded
                      forceNewInstance={multiAgent && isMultiInstanceType(addingChannel.name)}
                    />
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// 自定义下拉菜单的样式类似于 Web 控制台的 `.cfg-dropdown`（圆形，
// 绿色聚焦环，悬停/活动状态）而不是原生的 <select>。
const ChannelDropdown: React.FC<{
  channels: ChannelInfo[]
  value: string
  onChange: (name: string) => void
  placeholder: string
}> = ({ channels, value, onChange, placeholder }) => {
  const [open, setOpen] = useState(false)
  // 当扳机位置太低而菜单无法容纳在下方时，向上打开，因此
  // 最后一个频道的列表不会被剪切到窗口底部。
  const [dropUp, setDropUp] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  // 大致是菜单的最大高度（max-h-60 = 15rem = 240px）加上一个小间隙。
  const MENU_MAX = 248
  const toggleOpen = () => {
    if (!open && ref.current) {
      const rect = ref.current.getBoundingClientRect()
      const below = window.innerHeight - rect.bottom
      // 仅当上方空间明显大于下方空间时才向上翻转。
      setDropUp(below < MENU_MAX && rect.top > below)
    }
    setOpen((v) => !v)
  }

  const current = channels.find((c) => c.name === value)

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={toggleOpen}
        className={`w-full flex items-center justify-between gap-2 h-10 px-3 rounded-btn border bg-inset text-sm cursor-pointer transition-colors ${
          open ? 'border-accent ring-2 ring-accent/15' : 'border-strong hover:border-content-tertiary'
        } ${current ? 'text-content' : 'text-content-tertiary'}`}
      >
        {current ? (
          <span className="flex items-center gap-2 min-w-0">
            <ChannelIcon name={current.name} size={26} />
            <span className="truncate">{localizedLabel(current.label)}</span>
            <span className="text-content-tertiary font-mono text-xs">({current.name})</span>
          </span>
        ) : (
          <span>{placeholder}</span>
        )}
        <ChevronDown size={14} className={`flex-shrink-0 text-content-tertiary transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div
          className={`absolute left-0 right-0 z-50 max-h-60 overflow-y-auto rounded-btn border border-default bg-elevated shadow-lg p-1 ${
            dropUp ? 'bottom-[calc(100%+4px)]' : 'top-[calc(100%+4px)]'
          }`}
        >
          {channels.map((ch) => {
            const active = ch.name === value
            return (
              <button
                key={ch.name}
                type="button"
                onClick={() => {
                  onChange(ch.name)
                  setOpen(false)
                }}
                className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm cursor-pointer transition-colors ${
                  active ? 'bg-accent-soft text-accent font-medium' : 'text-content-secondary hover:bg-surface-2'
                }`}
              >
                <ChannelIcon name={ch.name} size={26} />
                <span className="truncate">{localizedLabel(ch.label)}</span>
                <span className="text-content-tertiary font-mono text-xs">({ch.name})</span>
                {active && <Check size={14} className="ml-auto flex-shrink-0" />}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

// 带有频道图标的有色正方形（网络控制台样式）。
const ChannelIcon: React.FC<{ name: string; size?: number }> = ({ name, size = 36 }) => {
  const { Icon, color } = channelStyle(name)
  return (
    <span
      className="rounded-lg flex items-center justify-center flex-shrink-0"
      style={{ width: size, height: size, backgroundColor: `${color}1a`, color }}
    >
      <Icon size={Math.round(size * 0.45)} />
    </span>
  )
}

// 支持多种连接模式的通道使用的分段选项卡。
const ModeTab: React.FC<{ icon: LucideIcon; label: string; active: boolean; onClick: () => void }> = ({
  icon: Icon,
  label,
  active,
  onClick,
}) => (
  <button
    type="button"
    onClick={onClick}
    className={`flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-[6px] text-sm font-medium cursor-pointer transition-colors ${
      active ? 'bg-elevated dark:bg-white/10 text-content shadow-sm' : 'text-content-tertiary hover:text-content-secondary'
    }`}
  >
    <Icon size={14} />
    {label}
  </button>
)

const ChannelCard: React.FC<{
  channel: ChannelInfo
  onChanged: () => void
  defaultExpanded?: boolean
  multiAgent?: boolean
  // 添加面板设置了这个，因此连接总是创建一个新实例而不是
  // 编辑现有的相同类型。
  forceNewInstance?: boolean
}> = ({ channel, onChanged, defaultExpanded = false, multiAgent = false, forceNewInstance = false }) => {
  // 没有字段的频道纯粹通过二维码连接（例如微信）。
  const isQrLogin = channel.fields.length === 0
  // 桌面扫描面板（微信/飞书）支持的二维码提供程序。
  const qrProvider = QR_PROVIDERS[channel.name]
  // 飞书可以通过扫描二维码（这会创建应用程序）来连接
  // 用户）或通过粘贴凭据，因此它会获得一个选项卡切换器。
  const dualMode = !!qrProvider && !isQrLogin
  const pending = pendingState(channel)
  // 微信直接扫二维码：添加时、运行时
  // 频道失去登录信息。无需单击（或双击）中间按钮。
  const weixinQr = qrProvider === 'weixin' && (pending === 'scanning' || (!channel.active && defaultExpanded))
  // 飞书的扫描创建了一个全新的应用程序，因此它保留在按钮后面。
  const [feishuScanning, setFeishuScanning] = useState(false)
  // 存储的凭据意味着用户最有可能想要编辑它们。
  const [mode, setMode] = useState<'scan' | 'manual'>(() =>
    channel.fields.some((f) => f.type !== 'bool' && !!f.value) ? 'manual' : 'scan'
  )
  const [expanded, setExpanded] = useState(defaultExpanded)
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(channel.fields.map((f) => [f.key, f.value != null ? String(f.value) : '']))
  )
  // 跟踪哪些秘密字段仍然保留服务器提供的掩码。
  const [masked, setMasked] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(
      channel.fields.map((f) => [f.key, f.type === 'secret' && !!f.value && MASK_RE.test(String(f.value))])
    )
  )
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')

  const setField = (key: string, val: string) => setValues((p) => ({ ...p, [key]: val }))

  // 只发送用户实际更改的字段；隐藏的秘密被跳过，所以
  // 后端保留存储的值（镜像 Web 控制台行为）。
  const buildConfig = (): Record<string, unknown> => {
    const cfg: Record<string, unknown> = {}
    channel.fields.forEach((f) => {
      const v = values[f.key]
      if (f.type === 'secret' && masked[f.key]) return
      if (v === '' || v == null) return
      cfg[f.key] = f.type === 'number' ? Number(v) : v
    })
    return cfg
  }

  // 这张卡的行动目标是哪个实例。 `undefined` 保留遗产
  // 每个类型的路径（单代理或非多实例类型）。空字符串
  // 意思是“创建一个新实例”；真实的 ID 可以编辑该特定的机器人。
  const instanceIdArg = (): string | undefined => {
    if (!multiAgent) return undefined
    if (forceNewInstance) return ''
    if (channel.instance_id) return channel.instance_id
    return undefined
  }

  const run = async (action: 'save' | 'connect' | 'disconnect') => {
    setBusy(true)
    setStatus('')
    try {
      const cfg = action === 'disconnect' ? undefined : buildConfig()
      const res = await apiClient.channelAction(action, channel.name, cfg, instanceIdArg())
      if (res.status === 'success') {
        if (action === 'save') {
          setStatus(t('channels_save_ok'))
          setTimeout(() => setStatus(''), 1600)
        } else if (action === 'connect' && res.downloading) {
          // 首次启用时，飞书会在后台获取其 SDK 包。
          setStatus(t('feishu_sdk_downloading_hint'))
          setTimeout(() => setStatus(''), 8000)
        }
        onChanged()
      } else {
        setStatus((res.message as string) || t(action === 'connect' ? 'channels_connect_error' : 'channels_save_error'))
      }
    } catch {
      setStatus(t(action === 'connect' ? 'channels_connect_error' : 'channels_save_error'))
    } finally {
      setBusy(false)
    }
  }

  const fieldEditor = (
    <div className="space-y-3">
      {channel.fields.map((f) => (
        <FieldRow
          key={f.key}
          field={f}
          value={values[f.key] ?? ''}
          onChange={(v) => setField(f.key, v)}
          onFocusSecret={() => {
            if (f.type === 'secret' && masked[f.key]) {
              setField(f.key, '')
              setMasked((p) => ({ ...p, [f.key]: false }))
            }
          }}
        />
      ))}
      <div className="flex items-center justify-end gap-3 pt-1">
        <span className={`text-xs transition-opacity ${status ? 'opacity-100' : 'opacity-0'} ${status === t('channels_save_ok') ? 'text-accent' : 'text-danger'}`}>
          {status || '\u00a0'}
        </span>
        {channel.active ? (
          <Btn variant="primary" onClick={() => run('save')} disabled={busy}>
            {t('channels_save')}
          </Btn>
        ) : (
          <Btn variant="primary" onClick={() => run('connect')} disabled={busy}>
            {t('channels_connect')}
          </Btn>
        )}
      </div>
    </div>
  )

  return (
    <div className={defaultExpanded ? '' : 'rounded-card border border-default bg-surface p-4'}>
      <div className="flex items-center gap-3">
        <ChannelIcon name={channel.name} size={40} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-sm text-content">{localizedLabel(channel.label)}</span>
            <span
              className={`w-2 h-2 rounded-full ${
                pending !== 'none'
                  ? 'bg-warning animate-pulse'
                  : channel.active
                    ? 'bg-accent'
                    : 'bg-content-tertiary'
              }`}
            />
            {pending === 'scanning' ? (
              <span className={`text-xs ${channel.login_status === 'scanned' ? 'text-accent' : 'text-warning'}`}>
                {channel.login_status === 'scanned' ? t('weixin_scan_scanned') : t('weixin_scan_waiting')}
              </span>
            ) : pending === 'starting' ? (
              <span className="text-xs text-warning">{t('channels_starting')}</span>
            ) : channel.active ? (
              <span className="text-xs text-accent">{t('channels_connected')}</span>
            ) : null}
          </div>
          <p className="text-xs text-content-tertiary font-mono mt-0.5">{channel.instance_id || channel.name}</p>
        </div>

        {channel.active ? (
          <Btn variant="danger" onClick={() => run('disconnect')} disabled={busy}>
            {t('channels_disconnect')}
          </Btn>
        ) : isQrLogin || dualMode || defaultExpanded ? null : (
          <Btn variant="ghost" onClick={() => setExpanded((v) => !v)}>
            {t('channels_add')}
          </Btn>
        )}
      </div>

      {/* Agent绑定：多Agent模式下连接的实例选择哪一个
          座席拥有对话权。在单代理模式下完全隐藏。 */}
      {multiAgent && channel.active && channel.instance_id && (
        <ChannelBinding channel={channel} />
      )}

      {/* 没有桌面支持的 QR 登录通道会回退到 Web 控制台。 */}
      {isQrLogin && !channel.active && !qrProvider && (
        <p className="text-xs text-content-tertiary mt-3 pl-12">{t('channels_qr_hint')}</p>
      )}

      {/* 微信：二维码就是整个流程，赶紧出示吧。琥珀
          “等待扫描”徽章告诉活卡为什么它重新出现。 */}
      {weixinQr && (
        <div className={channel.active ? 'mt-4 pt-4 border-t border-subtle' : 'mt-2'}>
          <QrScanPanel provider="weixin" onConnected={onChanged} newInstance={multiAgent && (forceNewInstance || !channel.instance_id)} />
        </div>
      )}

      {/* 飞书：选择一键式二维码注册和手动凭据。 */}
      {dualMode && (
        <div className="mt-4">
          <div className="flex items-center gap-1 bg-inset-2 rounded-btn p-0.5 mb-4">
            <ModeTab
              icon={QrCode}
              label={t('feishu_mode_scan')}
              active={mode === 'scan'}
              onClick={() => setMode('scan')}
            />
            <ModeTab
              icon={KeyRound}
              label={t('feishu_mode_manual')}
              active={mode === 'manual'}
              onClick={() => {
                setMode('manual')
                // 删除挂起的扫描，这样返回就不会默默开始
                // 第二个应用程序注册。
                setFeishuScanning(false)
              }}
            />
          </div>
          {mode !== 'scan' ? (
            fieldEditor
          ) : feishuScanning ? (
            <QrScanPanel provider="feishu" onConnected={onChanged} newInstance={multiAgent && (forceNewInstance || !channel.instance_id)} />
          ) : (
            <div className="flex flex-col items-center py-3">
              <p className="text-sm text-content-secondary mb-4 text-center max-w-sm leading-relaxed">
                {channel.active ? t('feishu_scan_replace_desc') : t('feishu_scan_panel_desc')}
              </p>
              <Btn variant="primary" onClick={() => setFeishuScanning(true)}>
                <span className="flex items-center gap-1.5">
                  <QrCode size={15} />
                  {t('feishu_scan_btn')}
                </span>
              </Btn>
            </div>
          )}
        </div>
      )}

      {/* 字段编辑器：始终适用于具有字段的连接通道，按需适用于可用字段。 */}
      {!isQrLogin && !dualMode && (channel.active || expanded) && <div className="mt-4">{fieldEditor}</div>}
    </div>
  )
}

// 连接的实例卡上的代理绑定块。坚持楼主+
// 通过名册的 `bind_channel_instance` 操作选择成员，其中
// 热更新正在运行的通道，无需重启（匹配web
// 控制台），因此切换代理是即时且无中断的。
const ChannelBinding: React.FC<{ channel: ChannelInfo }> = ({ channel }) => {
  const agents = useAgentStore((s) => s.agents)
  const defaultAgentId = useAgentStore((s) => s.defaultAgentId)

  // 本地乐观值，以便拾取器立即响应；坚持的
  // 真相仍然来自重新加载的频道。每当服务器重新播种
  // 绑定更改（所有者或成员），而不仅仅是实例本身发生更改时，
  // 所以这里反映了外部编辑。
  const initial = useMemo(() => {
    const owner = channel.agent_id ? [channel.agent_id] : []
    return [...owner, ...(channel.members || [])]
  }, [channel.agent_id, channel.members])
  const [value, setValue] = useState<string[]>(initial)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setValue(initial)
  }, [initial])

  const persist = async (next: string[]) => {
    setValue(next)
    setBusy(true)
    try {
      const owner = next[0] || ''
      const members = next.slice(1)
      await apiClient.agentAction({
        action: 'bind_channel_instance',
        channel_type: channel.channel_type || channel.name,
        instance_id: channel.instance_id,
        agent_id: owner,
        members,
      })
      // 保持名册的channel_instances 与其他视图同步。一个沉默的
      // 故意跳过频道重新加载：这会与乐观者作斗争
      // 值，并且绑定已应用于服务器端（热更新）。
      void useAgentStore.getState().refresh()
    } catch {
      // 发生故障时恢复到最后一个服务器已知值。
      setValue(initial)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-4 pt-4 border-t border-subtle">
      <div className="flex items-center gap-1.5 mb-1.5">
        <label className="block text-xs font-medium text-content-secondary">{t('channel_bind_agent')}</label>
        <FieldTip tip={t('channel_bound_agent_hint')} />
      </div>
      <ChannelTeamSelect
        agents={agents}
        defaultAgentId={defaultAgentId}
        value={value}
        onChange={persist}
        disabled={busy}
      />
    </div>
  )
}

const FieldRow: React.FC<{
  field: ChannelField
  value: string
  onChange: (v: string) => void
  onFocusSecret: () => void
}> = ({ field, value, onChange, onFocusSecret }) => {
  if (field.type === 'bool') {
    return (
      <div className="flex items-center justify-between">
        <span className="text-sm text-content-secondary">{field.label}</span>
        <Toggle checked={value === 'true' || value === '1'} onChange={(v) => onChange(v ? 'true' : 'false')} />
      </div>
    )
  }
  return (
    <div>
      <label className="block text-sm text-content-secondary mb-1.5">{field.label}</label>
      <input
        type={field.type === 'number' ? 'number' : 'text'}
        value={value}
        placeholder={field.label}
        onChange={(e) => onChange(e.target.value)}
        onFocus={onFocusSecret}
        className="w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary focus:outline-none focus:border-accent font-mono transition-colors"
      />
    </div>
  )
}

export default ChannelsPage
