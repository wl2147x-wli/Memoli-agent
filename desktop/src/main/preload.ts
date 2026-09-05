import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  getBackendPort: () => ipcRenderer.invoke('get-backend-port'),
  getBackendStatus: () => ipcRenderer.invoke('get-backend-status'),
  getBackendError: () => ipcRenderer.invoke('get-backend-error'),
  getDataDir: () => ipcRenderer.invoke('get-data-dir') as Promise<string>,
  restartBackend: () => ipcRenderer.invoke('restart-backend'),
  selectDirectory: () => ipcRenderer.invoke('select-directory'),
  selectFile: (filters?: Electron.FileFilter[]) => ipcRenderer.invoke('select-file', filters),
  openPath: (targetPath: string) => ipcRenderer.invoke('open-path', targetPath) as Promise<string>,

  // 每个侦听器注册器都会返回一个取消订阅 fn，以便渲染器可以清理
  // 卸载/影响重新运行并避免累积重复的处理程序。
  onBackendStatus: (
    callback: (data: { status: string; port?: number; error?: string; code?: string; path?: string }) => void,
  ) => {
    const handler = (
      _event: unknown,
      data: { status: string; port?: number; error?: string; code?: string; path?: string },
    ) => callback(data)
    ipcRenderer.on('backend-status', handler)
    return () => ipcRenderer.removeListener('backend-status', handler)
  },

  onBackendLog: (callback: (line: string) => void) => {
    const handler = (_event: unknown, line: string) => callback(line)
    ipcRenderer.on('backend-log', handler)
    return () => ipcRenderer.removeListener('backend-log', handler)
  },

  // 窗口控件（Windows 上的自定义标题栏）
  windowMinimize: () => ipcRenderer.invoke('window-minimize'),
  windowMaximize: () => ipcRenderer.invoke('window-maximize'),
  windowClose: () => ipcRenderer.invoke('window-close'),
  windowIsMaximized: () => ipcRenderer.invoke('window-is-maximized'),
  onMaximizeChange: (callback: (maximized: boolean) => void) => {
    const handler = (_event: unknown, max: boolean) => callback(max)
    ipcRenderer.on('window-maximize-changed', handler)
    return () => ipcRenderer.removeListener('window-maximize-changed', handler)
  },

  // 从主进程转发的应用程序菜单/快捷操作。
  onMenuAction: (callback: (action: string) => void) => {
    const handler = (_event: unknown, action: string) => callback(action)
    ipcRenderer.on('menu-action', handler)
    return () => ipcRenderer.removeListener('menu-action', handler)
  },

  // 当前应用程序版本（例如“0.0.5”），显示在 NavRail 页脚中。
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),

  // 登录时启动切换 (macOS + Windows)。 get 返回有效状态；
  // set 返回真实结果，以便 UI 可以显示拒绝/错误。
  getLoginItemEnabled: () => ipcRenderer.invoke('get-login-item') as Promise<boolean>,
  setLoginItemEnabled: (enabled: boolean) =>
    ipcRenderer.invoke('set-login-item', enabled) as Promise<{
      ok: boolean
      enabled: boolean
      error: string
    }>,

  // 主题（来自 ~/.cow/themes 的捆绑+用户主题），内联资产。
  listThemes: () => ipcRenderer.invoke('themes-list') as Promise<Record<string, unknown>[]>,
  getThemesDir: () => ipcRenderer.invoke('themes-dir') as Promise<string>,
  // 可选的应用程序配置（首次运行默认主题+显示名称）。为空
  // 标准构建。
  getAppConfig: () =>
    ipcRenderer.invoke('app-config-get') as Promise<{ defaultTheme?: string; appName?: string } | null>,

  // 通过主进程的通用 HTTPS 中继（绕过渲染器的 CORS）
  // 外部端点的限制）。可选扩展可以使用它。
  httpRelay: (req: {
    url: string
    method?: string
    headers?: Record<string, string>
    body?: string
  }) =>
    ipcRenderer.invoke('http-relay', req) as Promise<{
      ok: boolean
      status: number
      headers: Record<string, string>
      body: string
    }>,

  // 自动更新：触发检查/下载/安装并订阅状态。的
  // 可选的 lang 路由安装程序下载到中国 CDN 镜像 (zh) 或 R2。
  checkForUpdate: (lang?: string) => ipcRenderer.invoke('update-check', lang),
  downloadUpdate: (lang?: string) => ipcRenderer.invoke('update-download', lang),
  installUpdate: () => ipcRenderer.invoke('update-install'),
  onUpdateStatus: (callback: (status: unknown) => void) => {
    const handler = (_event: unknown, status: unknown) => callback(status)
    ipcRenderer.on('update-status', handler)
    return () => ipcRenderer.removeListener('update-status', handler)
  },

  setAppIcon: (iconUrl: string, icoUrl?: string) =>
    ipcRenderer.invoke('set-app-icon', iconUrl, icoUrl) as Promise<boolean>,
  setAppTitle: (title: string) => ipcRenderer.invoke('set-app-title', title) as Promise<boolean>,

  // 显示本机操作系统通知；单击它会使窗口聚焦并询问
  // 渲染器（通过 onOpenSession）打开给定的会话。
  notify: (payload: { title?: string; body?: string; sessionId?: string; silent?: boolean }) =>
    ipcRenderer.invoke('notify', payload) as Promise<boolean>,
  onOpenSession: (callback: (sessionId: string) => void) => {
    const handler = (_event: unknown, sessionId: string) => callback(sessionId)
    ipcRenderer.on('open-session', handler)
    return () => ipcRenderer.removeListener('open-session', handler)
  },

  platform: process.platform,
  // 操作系统 UI 语言（例如“zh-CN”），同步读取，以便渲染器可以选择
  // 首次运行时的默认语言。如果不可用则返回到 ''。
  systemLocale: (() => {
    try {
      return ipcRenderer.sendSync('get-system-locale') as string
    } catch {
      return ''
    }
  })(),
})
