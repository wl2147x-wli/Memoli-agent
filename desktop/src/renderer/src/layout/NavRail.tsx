import React, { useState, useRef, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  MessageSquare,
  BookOpen,
  Brain,
  Zap,
  Radio,
  Clock,
  Users,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
  Sun,
  Moon,
  ScrollText,
  MoreHorizontal,
  Languages,
  Download,
  Loader2,
  Globe,
  FileText,
  Store,
  MessageSquareWarning,
  Palette,
  Check,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { Theme } from '../theme/themes'
// 桌面应用程序自己的品牌图标（透明PNG），由Vite捆绑。
import brandLogo from '../assets/logo.png'
import { t, getLang, setLang, Lang } from '../i18n'
import { useUIStore } from '../store/uiStore'
import { guardDocEditors } from '../store/docEditorStore'
import { useTheme } from '../hooks/useTheme'
import { usePlatform } from '../hooks/usePlatform'
import { useUpdateStore, hasPendingUpdate, hasAvailableUpdate } from '../store/updateStore'
import UpdateBanner from '../components/UpdateBanner'
import { selectMultiAgent } from '../store/agentStore'
import { useAgentStore } from '../store/agentStore'
import { product } from '@product'

// 当 app.getVersion() 不可用时显示回退（开发/网络预览）。保留
// 与desktop/package.json“版本”同步；打包的应用程序会覆盖此
// 通过 IPC 具有真正的价值，因此它只在打包构建之外才重要。
const FALLBACK_VERSION = '2.1.5'

// 在用户的默认浏览器中打开的外部链接。窗口打开处理程序
// 在主进程中通过 shell.openExternal 路由 window.open() 。
// 默认英文（无后缀）；中文有 /zh 后缀。技能中心是
// 与语言无关。
const SKILL_HUB_URL = 'https://skills.cowagent.ai/'
// GitHub 问题 — 用户报告错误/请求功能的地方。
const FEEDBACK_URL = 'https://github.com/zhayujie/CowAgent/issues'

const websiteUrl = () => (getLang() === 'zh' ? 'https://cowagent.ai/zh' : 'https://cowagent.ai')
const docsUrl = () => (getLang() === 'zh' ? 'https://docs.cowagent.ai/zh' : 'https://docs.cowagent.ai')

const openExternal = (url: string) => {
  window.open(url, '_blank', 'noopener,noreferrer')
}

interface NavItem {
  path: string
  labelKey: string
  icon: LucideIcon
}

const NAV_ITEMS: NavItem[] = [
  { path: '/', labelKey: 'menu_chat', icon: MessageSquare },
  { path: '/knowledge', labelKey: 'menu_knowledge', icon: BookOpen },
  { path: '/memory', labelKey: 'menu_memory', icon: Brain },
  { path: '/skills', labelKey: 'menu_skills', icon: Zap },
  { path: '/channels', labelKey: 'menu_channels', icon: Radio },
  { path: '/tasks', labelKey: 'menu_tasks', icon: Clock },
  { path: '/settings', labelKey: 'menu_settings', icon: Settings },
]

// 仅当安装运行多个代理时，团队条目才存在，因此
// 单代理客户端完全显示原始菜单。聊天后插入。
const AGENTS_ITEM: NavItem = { path: '/agents', labelKey: 'menu_agents', icon: Users }

interface NavRailProps {
  onLangChange: () => void
}

const NavRail: React.FC<NavRailProps> = ({ onLangChange }) => {
  const location = useLocation()
  const navigate = useNavigate()
  const { navCollapsed, toggleNav } = useUIStore()
  const { theme, toggleTheme, themeId, themes, appName, setThemeId } = useTheme()
  // 在 macOS 上，左上角被本机交通灯占据，因此
  // 品牌标记仅在 Windows/Linux 上显示，否则该角会显示
  // 空（镜像 Web 控制台的侧边栏徽标）。
  const { isMac } = usePlatform()

  const collapsed = navCollapsed
  const width = collapsed ? 'w-[56px]' : 'w-[208px]'

  // 离开页面会卸载其文档编辑器，因此请解决所有未保存的工作
  // 首先-在这里，虽然下降仍然可以停止导航。
  const go = async (path: string) => {
    if (!(await guardDocEditors())) return
    navigate(path)
  }

  // 仅在多代理模式（源自名册）下显示“团队”页面。
  const multiAgent = useAgentStore(selectMultiAgent)
  const navItems = multiAgent
    ? [NAV_ITEMS[0], AGENTS_ITEM, ...NAV_ITEMS.slice(1)]
    : NAV_ITEMS

  const updateState = useUpdateStore()
  // 页脚点：此版本一旦取消则隐藏（用户要求这样做）。
  const pendingUpdate = hasPendingUpdate(updateState)
  // 菜单“检查更新”点：只要更新实际存在，就会保留，
  // 即使在取消页脚徽章之后也是如此。
  const availableUpdate = hasAvailableUpdate(updateState)
  const checking = updateState.status?.state === 'checking'

  const [menuOpen, setMenuOpen] = useState(false)
  // 本地回退，因此即使主进程 IPC 已关闭，版本也始终显示
  // 不可用（例如开发/网络预览）。真正的价值来自于
  // app.getVersion()（打包的package.json），绝不来自远程服务。
  const [version, setVersion] = useState(FALLBACK_VERSION)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    window.electronAPI
      ?.getAppVersion?.()
      .then((v) => v && setVersion(v))
      .catch(() => {})
  }, [])

  // 在任何外部单击/退出时关闭弹出窗口。
  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  const toggleLanguage = () => {
    const next: Lang = getLang() === 'zh' ? 'en' : 'zh'
    setLang(next)
    onLangChange()
  }

  // 跟踪用户发起的检查，以便我们可以在
  // 当结果返回为不可用时菜单（自动轮询保持
  // 沉默）。不久之后以及每当菜单关闭时都会被清除。
  const [checkedManually, setCheckedManually] = useState(false)
  const updateStatusState = updateState.status?.state

  useEffect(() => {
    if (!checkedManually) return
    if (updateStatusState === 'not-available') {
      const id = setTimeout(() => setCheckedManually(false), 4000)
      return () => clearTimeout(id)
    }
    // 待处理的更新会打开自己的面板；不需要内联提示。
    if (updateStatusState === 'available' || updateStatusState === 'downloaded') {
      setCheckedManually(false)
    }
    return
  }, [checkedManually, updateStatusState])

  useEffect(() => {
    if (!menuOpen) setCheckedManually(false)
  }, [menuOpen])

  const checkUpdate = () => {
    setCheckedManually(true)
    // 如果更新已知，则 recheck() 重新打开其面板，因此关闭
    // 菜单来揭示它。否则保持菜单打开：“最新”结果
    // 显示内联作为菜单标签 - 关闭它（这会重置checkManually）
    // 这正是使盒子闪烁并且从不显示“最新”的原因。
    if (availableUpdate) setMenuOpen(false)
    updateState.recheck()
  }

  return (
    <aside className={`${width} flex flex-col flex-shrink-0 h-full bg-base transition-[width] duration-200`}>
      {/* 顶部：全宽拖条；底部边框延续标题分隔线
          横跨整个窗户。没有右边框，因此不会遮挡灯光。
          在 Windows/Linux 上，左上角是空的（没有红绿灯），所以
          我们在这里显示品牌标记，就像网络控制台的侧边栏一样。 */}
      <div
        className={`titlebar-drag h-[44px] flex-shrink-0 border-b border-default flex items-center ${
          collapsed ? 'justify-center px-0' : 'px-3'
        }`}
      >
        {!isMac &&
          (product.slots?.NavRailBrand ? (
            // 构建可以在品牌区域呈现自己的文字标记。
            <product.slots.NavRailBrand collapsed={collapsed} />
          ) : (
            <div className="flex items-center gap-2 min-w-0 select-none">
              <BrandLogo />
              {!collapsed && (
                <span className="text-[14px] font-semibold text-content truncate">{appName}</span>
              )}
            </div>
          ))}
      </div>

      {/* 内容区域带有右侧分隔线，从标题栏下方开始 */}
      <div className="flex-1 flex flex-col min-h-0 border-r border-default">
      {/* 导航项目 */}
      <nav className="flex-1 overflow-y-auto px-2 py-2 space-y-0.5">
        {navItems.map((item) => {
          const Icon = item.icon
          const isActive = location.pathname === item.path
          return (
            <button
              key={item.path}
              onClick={() => void go(item.path)}
              title={collapsed ? t(item.labelKey) : undefined}
              className={`group w-full flex items-center gap-3 rounded-btn cursor-pointer transition-colors h-9 ${
                collapsed ? 'justify-center px-0' : 'px-3'
              } ${
                isActive
                  ? 'bg-accent-soft text-accent'
                  : 'text-content-secondary hover:bg-surface-2 hover:text-content'
              }`}
            >
              <Icon size={18} strokeWidth={isActive ? 2.2 : 1.8} className="flex-shrink-0" />
              {!collapsed && <span className="text-[13px] truncate">{t(item.labelKey)}</span>}
            </button>
          )
        })}
      </nav>

      {/* 当新版本待定时，更新横幅会浮动在页脚上方 */}
      <div className="relative">
        {!collapsed && <UpdateBanner />}
      </div>

      {/* 页脚操作：单个“更多”条目（带有版本+更新点）
          打开一个向上的弹出窗口，以及始终可见的折叠开关。安
          可选的“@product”插槽位于左侧（例如帐户头像），
          占据“更多”条目原本会占据的位置。 */}
      <div className="flex-shrink-0 px-2 py-2 border-t border-subtle relative" ref={menuRef}>
        {menuOpen && (
          <FooterMenu
            theme={theme}
            checking={checking}
            pendingUpdate={availableUpdate}
            upToDate={checkedManually && updateStatusState === 'not-available' && !availableUpdate}
            onLogs={() => {
              setMenuOpen(false)
              void go('/logs')
            }}
            onTheme={toggleTheme}
            themeId={themeId}
            themes={themes}
            onThemeId={setThemeId}
            onLanguage={toggleLanguage}
            onCheckUpdate={checkUpdate}
            onOpenLink={(url) => {
              setMenuOpen(false)
              openExternal(url)
            }}
          />
        )}

        <div className={collapsed ? 'space-y-0.5' : 'flex items-center gap-1'}>
          {/* 左侧：内置的“更多”条目（版本+点）或者，
              当扩展提供一个并隐藏内置菜单时，它的
              页脚槽（例如帐户头像）。 */}
          {product.slots?.NavRailFooter && product.nav?.hideFooterMenu ? (
            <div className={collapsed ? '' : 'flex-1 min-w-0'}>
              <product.slots.NavRailFooter />
            </div>
          ) : (
            !product.nav?.hideFooterMenu && (
              <button
                onClick={() => setMenuOpen((o) => !o)}
                title={t('menu_more')}
                className={`relative inline-flex items-center rounded-btn cursor-pointer transition-colors ${
                  menuOpen ? 'bg-surface-2 text-content' : 'text-content-tertiary hover:text-content hover:bg-surface-2'
                } ${collapsed ? 'w-full h-9 justify-center' : 'h-8 px-2 gap-1.5'}`}
              >
                {!collapsed && version && (
                  <span className="text-[12px] truncate">{`v${version}`}</span>
                )}
                <MoreHorizontal size={17} className="flex-shrink-0" />
                {pendingUpdate && (
                  <span className="absolute top-1 right-1 h-2 w-2 rounded-full bg-danger" />
                )}
              </button>
            )
          )}

          {!collapsed && !(product.slots?.NavRailFooter && product.nav?.hideFooterMenu) && (
            <div className="flex-1" />
          )}

          <FooterBtn collapsed={collapsed} onClick={toggleNav} title={collapsed ? t('nav_expand') : t('nav_collapse')}>
            {collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
          </FooterBtn>
        </div>
      </div>
      </div>
    </aside>
  )
}

// 左上角的品牌标记 (Windows/Linux)。使用桌面应用程序的
// 自己的图标（透明的PNG，有自己的圆形），所以它干净地坐落在
// 浅色和深色背景，无需额外的样式。
const BrandLogo: React.FC = () => (
  <img
    src={brandLogo}
    alt="CowAgent"
    draggable={false}
    className="flex-shrink-0 w-7 h-7 object-contain"
  />
)

const FooterBtn: React.FC<{
  collapsed: boolean
  onClick: () => void
  title: string
  active?: boolean
  children: React.ReactNode
}> = ({ collapsed, onClick, title, active, children }) => (
  <button
    onClick={onClick}
    title={title}
    className={`inline-flex items-center gap-1.5 rounded-btn cursor-pointer transition-colors ${
      active
        ? 'bg-accent-soft text-accent'
        : 'text-content-tertiary hover:text-content hover:bg-surface-2'
    } ${collapsed ? 'w-full h-9 justify-center' : 'h-8 px-2'}`}
  >
    {children}
  </button>
)

// 向上的弹出窗口保留了先前塞入的辅助操作
// 页脚（主题、语言、日志、更新检查）。将页脚保持为单一
// 入口，以便可以在此处添加新物品，而不会弄乱导轨。
const FooterMenu: React.FC<{
  theme: string
  checking: boolean
  pendingUpdate: boolean
  upToDate: boolean
  themeId: string
  themes: Theme[]
  onThemeId: (id: string) => void
  onLogs: () => void
  onTheme: () => void
  onLanguage: () => void
  onCheckUpdate: () => void
  onOpenLink: (url: string) => void
}> = ({ theme, checking, pendingUpdate, upToDate, themeId, themes, onThemeId, onLogs, onTheme, onLanguage, onCheckUpdate, onOpenLink }) => {
  const [themeMenuOpen, setThemeMenuOpen] = useState(false)
  const updateLabel = checking
    ? t('update_checking')
    : upToDate
      ? t('update_latest')
      : t('update_check')
  return (
  <div className="absolute bottom-full left-2 right-2 mb-2 z-50 rounded-lg border border-default bg-elevated shadow-lg py-1">
    {/* 外部目的地（技能中心、文档、网站、反馈）。安
        扩展程序可能会隐藏此组，以仅将菜单保留到应用程序操作。 */}
    {!product.nav?.hideExternalLinks && (
      <>
        <MenuItem icon={<Store size={16} />} label={t('menu_skill_hub')} onClick={() => onOpenLink(SKILL_HUB_URL)} />
        <MenuItem icon={<FileText size={16} />} label={t('menu_docs')} onClick={() => onOpenLink(docsUrl())} />
        <MenuItem icon={<Globe size={16} />} label={t('menu_website')} onClick={() => onOpenLink(websiteUrl())} />
        <MenuItem
          icon={<MessageSquareWarning size={16} />}
          label={t('menu_feedback')}
          onClick={() => onOpenLink(FEEDBACK_URL)}
        />
        <div className="my-1 border-t border-subtle" />
      </>
    )}

    {/* 以下应用程序操作：更新、主题、语言、日志 */}
    <MenuItem
      icon={checking ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
      label={updateLabel}
      onClick={onCheckUpdate}
      dot={pendingUpdate}
      disabled={checking || upToDate}
    />
    <MenuItem
      icon={theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
      label={theme === 'dark' ? t('menu_theme_light') : t('menu_theme_dark')}
      onClick={onTheme}
    />
    <MenuItem
      icon={<Palette size={16} />}
      label={t('menu_theme_picker')}
      trailing={themeMenuOpen ? '▾' : '▸'}
      onClick={() => setThemeMenuOpen((o) => !o)}
    />
    {themeMenuOpen &&
      themes.map((th) => (
        <button
          key={th.id}
          onClick={() => onThemeId(th.id)}
          className="w-full flex items-center gap-2.5 pl-8 pr-3 h-9 text-[13px] text-content-secondary hover:bg-surface-2 hover:text-content cursor-pointer transition-colors"
        >
          <ThemeSwatch preview={th.preview ?? { accent: '#4abe6e', bg: '#111', surface: '#1c1c1f' }} />
          <span className="flex-1 text-left truncate">{th.name}</span>
          {themeId === th.id && <Check size={14} className="flex-shrink-0 text-accent" />}
        </button>
      ))}
    <MenuItem
      icon={<Languages size={16} />}
      label={t('menu_language')}
      trailing={getLang() === 'zh' ? 'EN' : '中'}
      onClick={onLanguage}
    />
    <MenuItem icon={<ScrollText size={16} />} label={t('menu_logs')} onClick={onLogs} />
  </div>
  )
}

// 主题选择器的小型 3 色预览（背景/表面/强调）。
const ThemeSwatch: React.FC<{ preview: { accent: string; bg: string; surface: string } }> = ({
  preview,
}) => (
  <span className="flex-shrink-0 inline-flex h-4 w-4 rounded-full overflow-hidden border border-default">
    <span className="w-1/3 h-full" style={{ background: preview.bg }} />
    <span className="w-1/3 h-full" style={{ background: preview.surface }} />
    <span className="w-1/3 h-full" style={{ background: preview.accent }} />
  </span>
)

const MenuItem: React.FC<{
  icon: React.ReactNode
  label: string
  trailing?: string
  dot?: boolean
  disabled?: boolean
  onClick: () => void
}> = ({ icon, label, trailing, dot, disabled, onClick }) => (
  <button
    disabled={disabled}
    onClick={onClick}
    className="w-full flex items-center gap-2.5 px-3 h-9 text-[13px] text-content-secondary hover:bg-surface-2 hover:text-content cursor-pointer transition-colors disabled:cursor-default disabled:hover:bg-transparent disabled:hover:text-content-secondary"
  >
    <span className="flex-shrink-0 text-content-tertiary relative">
      {icon}
      {dot && <span className="absolute -top-0.5 -right-0.5 h-1.5 w-1.5 rounded-full bg-danger" />}
    </span>
    <span className="flex-1 text-left truncate">{label}</span>
    {trailing && <span className="text-[11px] font-medium text-content-tertiary">{trailing}</span>}
  </button>
)

export default NavRail
