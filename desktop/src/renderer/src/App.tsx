import React, { useState, useCallback, useEffect } from 'react'
import { Routes, Route, useLocation, useNavigate } from 'react-router-dom'
import { History, FolderTree } from 'lucide-react'
import NavRail from './layout/NavRail'
import SessionList from './layout/SessionList'
import WindowControls from './layout/WindowControls'
import StatusScreen from './components/StatusScreen'
import LoginGate from './components/LoginGate'
import { useBackend } from './hooks/useBackend'
import { usePlatform } from './hooks/usePlatform'
import { usePushPoll } from './hooks/usePushPoll'
import { useUIStore } from './store/uiStore'
import { useSessionStore } from './store/sessionStore'
import { useWorkspaceStore } from './store/workspaceStore'
import { guardDocEditors } from './store/docEditorStore'
import WorkspacePanel from './components/WorkspacePanel'
import Lightbox from './components/Lightbox'
import ConfirmDialog from './components/ConfirmDialog'
import { initUpdateListener } from './store/updateStore'
import { useOnboardingStore } from './store/onboardingStore'
import OnboardingWizard from './components/OnboardingWizard'
import apiClient from './api/client'
import { t } from './i18n'
import ChatPage from './pages/ChatPage'
import SettingsPage from './pages/SettingsPage'
import KnowledgePage from './pages/KnowledgePage'
import SkillsPage from './pages/SkillsPage'
import MemoryPage from './pages/MemoryPage'
import ChannelsPage from './pages/ChannelsPage'
import TasksPage from './pages/TasksPage'
import LogsPage from './pages/LogsPage'
import AgentsPage from './pages/AgentsPage'
import { useAgentStore } from './store/agentStore'
import { product } from '@product'

const App: React.FC = () => {
  const backend = useBackend()
  const location = useLocation()
  const navigate = useNavigate()
  const { isWin, isMac } = usePlatform()
  const { sessionsCollapsed, toggleSessions, navCollapsed } = useUIStore()
  const toggleWorkspace = useWorkspaceStore((s) => s.togglePanel)
  const workspaceOpen = useWorkspaceStore((s) => s.open)
  const onboardingOpen = useOnboardingStore((s) => s.open)
  const maybeOpenOnboarding = useOnboardingStore((s) => s.maybeOpen)
  const [, forceUpdate] = useState(0)
  // 受 web_password 保护的后端的身份验证门。 “检查”直到我们知道
  // 是否需要登录； 'need_login' 显示密码屏幕； ‘好吧’让
  // 主 UI 渲染。
  const [authState, setAuthState] = useState<'checking' | 'need_login' | 'ok'>('checking')
  const [productAuthed, setProductAuthed] = useState(false)
  // 可选门由“@product”提供。 `product.auth` 是常数
  // 整个构建，因此有条件地调用其钩子在渲染之间是稳定的。
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const productRequiresAuth = product.auth ? product.auth.useRequiresAuth() : false

  useEffect(() => {
    if (backend.status === 'ready') apiClient.setBaseUrl(backend.baseUrl)
  }, [backend.status, backend.baseUrl])

  // 在没有放置区域处理的地方放置的文件会使 Chromium 导航到
  // 该文件，替换应用程序。吞掉那些文档级别的内容；页面
  // 接受文件（聊天输入、知识导入）的仍然首先获取事件。
  useEffect(() => {
    const swallow = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes('Files')) e.preventDefault()
    }
    document.addEventListener('dragover', swallow)
    document.addEventListener('drop', swallow)
    return () => {
      document.removeEventListener('dragover', swallow)
      document.removeEventListener('drop', swallow)
    }
  }, [])

  // 后端准备就绪后，检查是否设置了 web_password。如果是这样并且
  // 此会话未经过身份验证，在应用程序之前显示登录门。
  useEffect(() => {
    if (backend.status !== 'ready') {
      setAuthState('checking')
      return
    }
    let cancelled = false
    apiClient
      .authCheck()
      .then((res) => {
        if (cancelled) return
        const needLogin = res.auth_required && !res.authenticated
        setAuthState(needLogin ? 'need_login' : 'ok')
      })
      .catch(() => {
        // 如果检查本身失败，不要硬阻止用户 - 假设没有身份验证
        // 是必需的（没有 web_password 的后端永远不会在此处返回错误）。
        if (!cancelled) setAuthState('ok')
      })
    return () => {
      cancelled = true
    }
  }, [backend.status, backend.baseUrl])

  // 首次运行检查：一旦后端准备就绪，决定是否显示
  // 入职向导。它是配置驱动的——只要聊天模型不存在就会显示
  // 已配置（且未在本次会议早些时候取消）；没有持久的标志。
  useEffect(() => {
    if (backend.status !== 'ready' || authState !== 'ok') return
    // 扩展程序可以选择退出内置设置向导。
    if (product.onboarding?.enabled === false) return
    let cancelled = false
    apiClient
      .getModels()
      .then((data) => {
        if (cancelled) return
        const chat = data.capabilities?.chat
        // “已配置”需要聊天提供商+模型以及该提供商的 API 密钥
        // 设置。默认配置可以发送没有密钥的模型名称，这
        // 不应该算作准备就绪——否则我们会跳过用户的入职培训
        // 谁仍然需要输入密钥。
        const providerId = chat?.current_provider
        const provider = data.providers?.find((p) => p.id === providerId)
        const keyReady = !!provider && (provider.configured || (provider.is_custom && !!provider.custom_name))
        const configured = !!providerId && !!chat?.current_model && keyReady
        maybeOpenOnboarding(configured)
      })
      .catch(() => {
        // 如果无法加载模型，则退回到仅使用标志的决策。
        if (!cancelled) maybeOpenOnboarding(false)
      })
    return () => {
      cancelled = true
    }
  }, [backend.status, authState, maybeOpenOnboarding])

  // 后端和身份验证确定后加载团队名单。这是
  // 尽力而为：商店吞掉所有错误并降级为单一代理，
  // 因此遗留后端（无 /api/agents）或暂时性故障永远不会阻塞
  // 该应用程序——团队的可供性只是隐藏起来。
  const refreshRoster = useAgentStore((s) => s.refresh)
  useEffect(() => {
    if (backend.status === 'ready' && authState === 'ok') void refreshRoster()
  }, [backend.status, authState, backend.baseUrl, refreshRoster])

  // 后端和身份验证解决后，轮询调度程序/推送消息。
  usePushPoll(backend.status === 'ready' && authState === 'ok')

  // 单击的操作系统通知要求我们打开其会话。
  useEffect(() => {
    const off = window.electronAPI?.onOpenSession?.((sessionId) => {
      useSessionStore.getState().setActive(sessionId)
      navigate('/')
    })
    return off
  }, [navigate])

  // 从主进程订阅自动更新状态（开发中无操作）。
  useEffect(() => initUpdateListener(), [])

  // 处理从主进程转发的应用程序菜单/快捷方式操作。
  useEffect(() => {
    const off = window.electronAPI?.onMenuAction?.(async (action) => {
      // 其中每一个都会离开当前页面，并带走任何打开的编辑器。
      if (!(await guardDocEditors())) return
      if (action === 'new-chat') {
        if (!(await useWorkspaceStore.getState().guardUnsavedEdit())) return
        useSessionStore.getState().newSession()
        navigate('/')
      } else if (action === 'open-settings') {
        navigate('/settings')
      } else if (action === 'view-logs') {
        navigate('/logs')
      }
    })
    return off
  }, [navigate])

  const handleLangChange = useCallback(() => forceUpdate((n) => n + 1), [])

  if (backend.status !== 'ready') {
    return (
      <StatusScreen
        status={backend.status}
        error={backend.error}
        code={backend.code}
        path={backend.path}
        slow={backend.slow}
        reconnecting={backend.reconnecting}
        onRetry={backend.restart}
      />
    )
  }

  // 后端已启动，但我们仍在解决身份验证问题 - 保留加载屏幕。
  if (authState === 'checking') {
    return <StatusScreen status="connecting" onRetry={backend.restart} />
  }

  if (authState === 'need_login') {
    return <LoginGate onAuthenticated={() => setAuthState('ok')} />
  }

  // 来自“@product”的可选门，在本地身份验证检查通过后显示。
  // 在布局内部渲染（导航栏保持可见），因此应用程序的功能
  // 当登录卡位于内容区域时显示。
  const ProductGate = product.auth?.Gate
  const showProductGate = !!(ProductGate && productRequiresAuth && !productAuthed)

  const isChat = location.pathname === '/'
  const showSessions = isChat && !sessionsCollapsed && !showProductGate

  return (
    <div className="flex h-screen overflow-hidden bg-base text-content">
      {onboardingOpen && <OnboardingWizard onDone={handleLangChange} />}
      <Lightbox />
      <ConfirmDialog />
      <NavRail onLangChange={handleLangChange} />

      {showSessions && <SessionList />}

      <div className="flex-1 flex flex-col min-w-0 h-screen">
        {/* 顶部标题栏条 — 拖动区域 + Windows 控件 */}
        <header className="h-[44px] flex items-center gap-1 px-2 flex-shrink-0 titlebar-drag bg-base border-b border-default">
          {isChat && sessionsCollapsed && (
            <button
              onClick={toggleSessions}
              title={t('session_history')}
              // Keep aligned with the SessionList history button: only nudge
              // right of the macOS traffic lights when the nav rail is collapsed
              // (otherwise the lights stay within the rail and don't overlap).
              className={`titlebar-no-drag inline-flex items-center justify-center w-7 h-7 rounded-btn text-content-tertiary hover:text-content hover:bg-surface-2 cursor-pointer transition-colors ${isMac ? 'mt-1' : ''} ${isMac && navCollapsed ? 'ml-2' : ''}`}
            >
              <History size={16} />
            </button>
          )}
          <div className="flex-1 min-w-0" />
          {isChat && !showProductGate && (
            <button
              onClick={toggleWorkspace}
              title={t('ws_toggle')}
              className={`titlebar-no-drag inline-flex items-center justify-center w-7 h-7 rounded-btn cursor-pointer transition-colors ${
                workspaceOpen
                  ? 'text-accent bg-accent-soft'
                  : 'text-content-tertiary hover:text-content hover:bg-surface-2'
              } ${isMac ? 'mt-1' : ''}`}
            >
              <FolderTree size={16} />
            </button>
          )}
          {product.slots?.HeaderRight && (
            <div className="titlebar-no-drag flex items-center">
              <product.slots.HeaderRight />
            </div>
          )}
          {isWin && <WindowControls />}
        </header>

        {/* 内容 */}
        <div className="flex-1 flex min-h-0 overflow-hidden bg-base">
          <div className="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden">
          {showProductGate && ProductGate ? (
            <ProductGate onAuthenticated={() => setProductAuthed(true)} />
          ) : (
          <Routes>
            <Route path="/" element={<ChatPage baseUrl={backend.baseUrl} />} />
            <Route path="/knowledge" element={<KnowledgePage baseUrl={backend.baseUrl} />} />
            <Route path="/memory" element={<MemoryPage baseUrl={backend.baseUrl} />} />
            <Route path="/skills" element={<SkillsPage baseUrl={backend.baseUrl} />} />
            <Route path="/channels" element={<ChannelsPage baseUrl={backend.baseUrl} />} />
            <Route path="/agents" element={<AgentsPage baseUrl={backend.baseUrl} />} />
            <Route path="/tasks" element={<TasksPage baseUrl={backend.baseUrl} />} />
            <Route path="/settings" element={<SettingsPage baseUrl={backend.baseUrl} onLangChange={handleLangChange} />} />
            {/* 旧版 /models 路线现在作为设置内的选项卡存在 */}
            <Route path="/models" element={<SettingsPage baseUrl={backend.baseUrl} onLangChange={handleLangChange} />} />
            <Route path="/logs" element={<LogsPage baseUrl={backend.baseUrl} />} />
            {product.routes?.map((r) => (
              <Route key={r.path} path={r.path} element={r.element} />
            ))}
          </Routes>
          )}
          </div>
          {isChat && !showProductGate && <WorkspacePanel />}
        </div>
      </div>
    </div>
  )
}

export default App
