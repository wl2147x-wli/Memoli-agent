import { app, BrowserWindow, session, shell, ipcMain, dialog, nativeImage, Notification, systemPreferences, crashReporter } from 'electron'
import path from 'path'
import fs from 'fs'
import os from 'os'
import http from 'http'
import { PythonBackend, BackendError } from './python-manager'
import { buildAppMenu } from './menu'
import { createTray, destroyTray, getTray } from './tray'
import { initUpdater, checkForUpdates, startDownload, quitAndInstall, setUpdateLanguage } from './updater'
import { setupThemeIPC, loadAppConfig } from './themes'
import { setupHttpRelayIPC } from './http-relay'
import {
  setupAppIconIPC,
  applyCachedAppIcon,
  applyCachedAppName,
  repairWindowsShortcuts,
  getRuntimeAppIcon,
} from './app-icon'

// 打包后端保存其可写数据（config.json、run.log）的地方。
// 与 python-manager.ts 中的 COW_DATA_DIR 保持同步，以便桌面 shell
// 将自己的诊断写入相同的 run.log 中的“打开日志文件夹”按钮
// 显示和应用程序内日志页面尾部 - 一个可以查找两个层的地方。
const COW_DATA_DIR = path.join(os.homedir(), '.cow')

// 将主进程的控制台输出和任何未捕获的崩溃镜像到 run.log。
// 打包的构建没有终端，因此每个 console.log/error 和每个
// 电子层崩溃（渲染器/GPU 消失，主进程异常）用于
// 消失：后端的run.log覆盖了Python故障，但白屏或
// 一个无声的应用程序退出没有留下任何痕迹。这缩小了差距而不会发生崩溃
// 服务器——证据到达本地，用户已经可以找到它。
function initDesktopLogging(): void {
  let stream: fs.WriteStream | null = null
  try {
    fs.mkdirSync(COW_DATA_DIR, { recursive: true })
    // 追加，这样我们就不会破坏后端自己的 run.log 历史记录；双方
    // 是基于行的，所以交错很好。
    stream = fs.createWriteStream(path.join(COW_DATA_DIR, 'run.log'), { flags: 'a' })
    stream.on('error', () => { stream = null })
  } catch {
    stream = null
  }

  const write = (level: string, args: unknown[]) => {
    if (!stream) return
    const text = args
      .map((a) => (typeof a === 'string' ? a : a instanceof Error ? a.stack || a.message : JSON.stringify(a)))
      .join(' ')
    try {
      stream.write(`[MAIN][${new Date().toISOString()}] [${level}] ${text}\n`)
    } catch {
      // 日志记录绝不能破坏应用程序
    }
  }

  // 包装控制台，以便现有的 console.* 整个 main 中的调用也持续存在，
  // 同时仍然打印到 `npm run dev` 的标准输出。
  const patch = (name: 'log' | 'warn' | 'error') => {
    const original = console[name].bind(console)
    console[name] = (...args: unknown[]) => {
      write(name.toUpperCase(), args)
      original(...args)
    }
  }
  patch('log')
  patch('warn')
  patch('error')

  // 用于硬崩溃的本机小型转储（Electron/Chromium 中的段错误）。已存储
  // 本地位于 userData/Crashpad 下；没有配置上传服务器。
  try {
    crashReporter.start({ uploadToServer: false })
  } catch {
    // crashReporter 是尽力而为的；永远不要让它阻止启动
  }

  // 主进程 JS 错误，否则会默默地终止应用程序。
  process.on('uncaughtException', (err) => {
    console.error('[crash] uncaughtException:', err?.stack || err)
  })
  process.on('unhandledRejection', (reason) => {
    console.error('[crash] unhandledRejection:', reason instanceof Error ? reason.stack : reason)
  })

  // 渲染器/GPU/实用程序进程崩溃。这些是“白屏”和
  // 用户看到“窗口消失”的情况，但默认情况下不会留下任何痕迹。
  app.on('render-process-gone', (_e, _wc, details) => {
    console.error(`[crash] render-process-gone: reason=${details.reason} exitCode=${details.exitCode}`)
  })
  app.on('child-process-gone', (_e, details) => {
    console.error(`[crash] child-process-gone: type=${details.type} reason=${details.reason} exitCode=${details.exitCode}`)
  })

  app.on('before-quit', () => {
    try {
      stream?.end()
    } catch {
      // 忽略
    }
  })
}

// 在运行其他程序之前设置主进程日志记录 + 崩溃捕获，因此
// 最早的控制台输出和任何启动崩溃都已被保留。
initDesktopLogging()

// 强制使用产品名称，以便即使在开发模式下 Dock/菜单也显示应用程序名称，
// 否则，默认的 Electron 二进制文件将报告“Electron”。名称
// 可以被捆绑的应用程序配置（appName）覆盖；默认为 CowAgent。
app.setName(loadAppConfig()?.appName || 'CowAgent')
  // Web 层可能在运行时覆盖了该名称。在这里重新应用它，
  // 在任何地方读取 app.getPath('userData') 之前，因为 setName 会移动它。
applyCachedAppName()

// 仅当设置了 AppUserModelID 时，Windows 才会显示通知；没有它
// 它们被悄然丢弃。在 macOS/Linux 上无害。
if (process.platform === 'win32') {
  app.setAppUserModelId('com.cowagent.desktop')
}

let mainWindow: BrowserWindow | null = null
let pythonBackend: PythonBackend | null = null
// 一旦用户明确退出（菜单/托盘），则为真，因此会绕过接近托盘。
let isQuitting = false

const isDev = !app.isPackaged
// 必须匹配 vite.config.ts 中的 `server.port`。单个端口，而不是范围：
// strictPort 意味着我们的服务器永远不会漂移，因此相邻端口可以
// 永远只属于别人。
const VITE_DEV_PORTS = [5173]

// 由操作系统在登录时启动（Windows 通过 --hidden；macOS 通过
// getLoginItemSettings().wasOpenedAsHidden)。开始最小化到托盘，这样
// 自动启动并不引人注目。
function launchedHidden(): boolean {
  if (process.argv.includes('--hidden')) return true
  try {
    return app.getLoginItemSettings().wasOpenedAsHidden === true
  } catch {
    return false
  }
}

// 渲染器的入口模块，如 Vite 服务的 index.html 中所示。
// 用于区分我们自己的开发服务器与持有端口的不相关服务器
// （另一个项目的Vite，静态文件服务器）。回答探头不是
// 足够的测试：将陌生人的页面加载到窗口中看起来完全一样
// 就像应用程序被破坏一样。
const RENDERER_MARKER = 'src/main.tsx'

function probeViteDevServer(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(`http://localhost:${port}`, (res) => {
      if (res.statusCode !== 200) {
        res.resume()
        resolve(false)
        return
      }
      let body = ''
      res.setEncoding('utf8')
      res.on('data', (chunk) => {
        body += chunk
        // 我们要查找的文档只有几 KB。更大的东西不是吗
        // 因此，停止阅读而不是缓冲不相关的响应。
        if (body.length > 64 * 1024) {
          req.destroy()
          resolve(false)
        }
      })
      res.on('end', () => resolve(body.includes(RENDERER_MARKER)))
      res.on('error', () => resolve(false))
    })
    req.on('error', () => resolve(false))
    req.setTimeout(500, () => { req.destroy(); resolve(false) })
  })
}

async function findViteDevServer(): Promise<string | null> {
  for (const port of VITE_DEV_PORTS) {
    if (await probeViteDevServer(port)) {
      return `http://localhost:${port}`
    }
  }
  return null
}

function getIconPath(ext: string = 'png'): string | undefined {
  const iconFile = `icon.${ext}`
  const iconPath = isDev
    ? path.resolve(__dirname, '../../resources', iconFile)
    : path.join(process.resourcesPath, iconFile)
  if (fs.existsSync(iconPath)) return iconPath
  return undefined
}

const isMac = process.platform === 'darwin'
const isWin = process.platform === 'win32'

// 持久化窗口边界
const windowStateFile = () => path.join(app.getPath('userData'), 'window-state.json')

function loadWindowState(): { width: number; height: number; x?: number; y?: number } {
  try {
    const raw = fs.readFileSync(windowStateFile(), 'utf-8')
    const s = JSON.parse(raw)
    if (typeof s.width === 'number' && typeof s.height === 'number') return s
  } catch {
    /* 首次运行或无法读取 */
  }
  return { width: 1280, height: 800 }
}

function saveWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) return
  if (mainWindow.isMinimized() || mainWindow.isFullScreen()) return
  const b = mainWindow.getBounds()
  try {
    fs.writeFileSync(windowStateFile(), JSON.stringify(b))
  } catch {
    /* 忽略 */
  }
}

function createWindow() {
  const state = loadWindowState()

  mainWindow = new BrowserWindow({
    width: state.width,
    height: state.height,
    x: state.x,
    y: state.y,
    minWidth: 900,
    minHeight: 600,
    // macOS：本机交通灯嵌入到我们的自定义标题栏中。
    // 窗户：完全无框；我们在应用程序内渲染自定义窗口控件。
    titleBarStyle: isMac ? 'hiddenInset' : 'hidden',
    trafficLightPosition: isMac ? { x: 14, y: 16 } : undefined,
    frame: isMac ? undefined : false,
    backgroundColor: '#0e0e10',
    icon: getIconPath(),
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  const persist = () => saveWindowState()
  mainWindow.on('resize', persist)
  mainWindow.on('move', persist)
  mainWindow.on('maximize', emitMaximizeState)
  mainWindow.on('unmaximize', emitMaximizeState)

  const rendererHtml = path.join(__dirname, '../renderer/index.html')

  if (isDev) {
    findViteDevServer().then((devUrl) => {
      if (devUrl) {
        console.log(`[Electron] Loading Vite dev server: ${devUrl}`)
        mainWindow?.loadURL(devUrl)
        mainWindow?.webContents.openDevTools()
      } else if (fs.existsSync(rendererHtml)) {
        console.log('[Electron] Vite dev server not found, loading built files')
        mainWindow?.loadFile(rendererHtml)
      } else {
        console.error('[Electron] No renderer available. Run "npm run build:renderer" first.')
      }
    })
  } else {
    mainWindow.loadFile(rendererHtml)
  }

  // 表面渲染器端控制台输出和主进程加载失败
  // 标准输出。如果没有这个，“卡在初始化”挂起是不可见的
  // 终端，因为所有渲染器日志都保留在（关闭的）开发工具中。
  mainWindow.webContents.on('console-message', (_e, level, message, line, sourceId) => {
    console.log(`[renderer:${level}] ${message} (${sourceId}:${line})`)
  })
  mainWindow.webContents.on('did-fail-load', (_e, code, desc, url) => {
    console.error(`[renderer] did-fail-load ${code} ${desc} ${url}`)
  })

  // 将后端的当前状态重播到刚刚加载的渲染器。
  // 后端事件是“即发即忘”发送，但渲染器仅订阅
  // 一旦 React 安装完毕——因此在前几百年内检测到故障
  // 毫秒（几乎立即检测到丢失的可执行文件）
  // 向任何人宣布，用户只能盯着通用的
  // “初始化失败”，没有附加任何原因。
  mainWindow.webContents.on('did-finish-load', () => {
    sendBackendState()
  })

  mainWindow.once('ready-to-show', () => {
    // 自动启动隐藏时跳过初始绘制：窗口保留在
    // 托盘/扩展坞，直到用户打开它，符合“不引人注目”的意图。
    if (launchedHidden()) return
    mainWindow?.show()
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  // 防止杂散文件丢失的最后手段：Chromium 将导航
  // 渲染器添加到删除的文件中，并且 UI 将消失，直到重新启动为止。
  // 渲染器重新加载保留相同的 URL，因此不受影响。
  mainWindow.webContents.on('will-navigate', (e, url) => {
    if (url.startsWith('file:') && url !== mainWindow?.webContents.getURL()) {
      console.warn(`[Electron] Blocked navigation to dropped file: ${url}`)
      e.preventDefault()
    }
  })

  // 靠近托盘：隐藏窗口而不是破坏它，因此托盘的
  // “表演”可以把它带回来。只有真正的退出（菜单/托盘/Cmd+Q）才会破坏它。
  mainWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault()
      mainWindow?.hide()
    }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function getBackendPath(): string {
  if (isDev) {
    return path.resolve(__dirname, '../../..')
  }
  return path.join(process.resourcesPath, 'backend')
}

/**
 * Push the backend's current state to the renderer. Used both for the initial
 * replay after a page load and as the shape every live status event follows.
 */
function sendBackendState() {
  if (!pythonBackend || !mainWindow || mainWindow.isDestroyed()) return
  const status = pythonBackend.getStatus()
  if (status === 'ready') {
    mainWindow.webContents.send('backend-status', { status: 'ready', port: pythonBackend.getPort() })
    return
  }
  if (status === 'error') {
    const err = pythonBackend.getLastError()
    mainWindow.webContents.send('backend-status', {
      status: 'error',
      error: err?.message,
      code: err?.code,
      path: err?.path,
    })
    return
  }
  mainWindow.webContents.send('backend-status', { status: 'starting', port: pythonBackend.getPort() })
}

async function startBackend() {
  const backendPath = getBackendPath()
  // isDev 将源签出与已安装的应用程序区分开来。后端
  // 经理需要知道：已安装的应用程序绝不能退回到查看
  // 对于Python解释器来说，它的可写数据总是位于~/.cow中。
  pythonBackend = new PythonBackend(backendPath, !isDev)

  pythonBackend.on('ready', (port: number) => {
    console.log(`[backend] ready on port ${port}`)
    mainWindow?.webContents.send('backend-status', { status: 'ready', port })
  })

  // 端口不是一个常量：pickPort() 可能会在以下情况下回退：
  // 首选之一是不可绑定的（Windows 保留范围）。告诉渲染器
  // 一旦我们知道，它就会在第一次尝试时探测正确的端口。
  pythonBackend.on('port', (port: number) => {
    console.log(`[backend] using port ${port}`)
    mainWindow?.webContents.send('backend-status', { status: 'starting', port })
  })

  // 后端在处理完请求后就消失了。告诉渲染器这样
  // 删除其缓存的“就绪” - 否则窗口在
  // 每个请求都会失败，这就是死后端如何以裸露的方式出现的方式
  // 聊天中出现“TypeError：无法获取”。
  pythonBackend.on('lost', () => {
    console.warn('[backend] stopped responding')
    mainWindow?.webContents.send('backend-status', { status: 'lost' })
  })

  pythonBackend.on('error', (error: BackendError) => {
    // 也镜像到主进程标准输出：否则后端启动错误
    // 仅在渲染器开发工具中可见，导致 `npm run dev` 挂起
    // 无法从终端进行诊断。
    console.error(`[backend] error: ${error.code} — ${error.message}${error.path ? ` [${error.path}]` : ''}`)
    sendBackendState()
  })

  pythonBackend.on('log', (line: string) => {
    console.log(`[backend] ${line}`)
    mainWindow?.webContents.send('backend-log', line)
  })

  await pythonBackend.start()
}

function setupIPC() {
  // 等待端口决定而不是阅读当前的猜测：渲染器
  // 通常在 startBackend() 探测任何内容之前询问，并且给出错误的答案
  // 这里的意思是它轮询一个没有任何东西会监听的端口。
  ipcMain.handle('get-backend-port', async () => {
    return pythonBackend ? pythonBackend.whenPortReady() : null
  })

  ipcMain.handle('get-backend-status', () => {
    return pythonBackend?.getStatus() ?? 'stopped'
  })

  // 基于拉取的访问最后一次失败的方法，因此渲染器可以随时询问原因
  // 启动失败而不是依赖于在确切的订阅时间
  // 事件触发的那一刻。
  ipcMain.handle('get-backend-error', () => {
    return pythonBackend?.getLastError() ?? null
  })

  // 其中 config.json 和 run.log 存在，因此错误屏幕可以打开该文件夹
  // 对于 UI 从未出现过的用户。
  ipcMain.handle('get-data-dir', () => {
    return pythonBackend?.getDataDir() ?? ''
  })

  ipcMain.handle('restart-backend', async () => {
    await pythonBackend?.restart()
    return true
  })

  ipcMain.handle('select-directory', async () => {
    const result = await dialog.showOpenDialog({
      properties: ['openDirectory'],
    })
    return result.canceled ? null : result.filePaths[0]
  })

  ipcMain.handle('select-file', async (_event, filters?: Electron.FileFilter[]) => {
    const result = await dialog.showOpenDialog({
      properties: ['openFile'],
      filters: filters || [{ name: 'All Files', extensions: ['*'] }],
    })
    return result.canceled ? null : result.filePaths[0]
  })

  // 使用操作系统默认应用程序打开本地文件；回落到揭示它
  // 当不存在处理程序时文件管理器。成功则返回 ''。
  ipcMain.handle('open-path', async (_event, targetPath: string) => {
    if (!targetPath) return 'empty path'
    const err = await shell.openPath(targetPath)
    if (err) shell.showItemInFolder(targetPath)
    return err
  })

  // 自定义窗口控件（由 Windows 无框标题栏使用）
  ipcMain.handle('window-minimize', () => mainWindow?.minimize())
  ipcMain.handle('window-maximize', () => {
    if (!mainWindow) return false
    if (mainWindow.isMaximized()) mainWindow.unmaximize()
    else mainWindow.maximize()
    return mainWindow.isMaximized()
  })
  ipcMain.handle('window-close', () => mainWindow?.close())
  ipcMain.handle('window-is-maximized', () => mainWindow?.isMaximized() ?? false)

  // 当前应用程序版本，显示在 NavRail 页脚中。
  ipcMain.handle('get-app-version', () => app.getVersion())

  // 登录时启动：由 macOS 上的操作系统登录项注册表支持
  // 在 Windows 上运行注册表项（均由 Electron 本地处理）。 Linux 有
  // 没有可靠的跨桌面机制，因此它不报告/接受任何内容。
  //
  // Windows 警告：我们用 `args: ['--hidden']` 注册我们的运行密钥。根据
  // Electron 文档，`openAtLogin` 仅在 getLoginItemSettings() 时报告 true
  // 使用相同的 `args` 进行调用 - 所以我们必须将它们传递到这里来匹配，或者
  // 将“弹回”切换为关闭（错误的回读会覆盖翻转）。我们不
  // 使用 `executableWillLaunchAtLogin`：它忽略参数并为 ANY 报告 true
  // 此 exe 的启动条目（例如，由安装程序/启动文件夹添加的启动条目）
  // 快捷方式），这使得切换默认显示为打开。匹配参数保留
  // 默认关闭，仅反映此应用程序实际创建的条目。
  const WIN_LOGIN_ARGS = ['--hidden']
  const isLaunchAtLoginEnabled = (): boolean => {
    if (isWin) return app.getLoginItemSettings({ args: WIN_LOGIN_ARGS }).openAtLogin === true
    if (isMac) return app.getLoginItemSettings().openAtLogin
    return false
  }
  ipcMain.handle('get-login-item', () => isLaunchAtLoginEnabled())
  // 返回真实结果，因此 UI 永远不会说谎：{ ok,enabled,error }。
  // - ok = false + error：写入登录项抛出（表面它，不要吞下）。
  // - ok=true 但已启用！=请求：操作系统/策略默默地拒绝更改。
  // 渲染器会显示原因，而不仅仅是将切换按钮弹回。
  ipcMain.handle('set-login-item', (_event, enabled: boolean) => {
    if (!isMac && !isWin) {
      return { ok: false, enabled: false, error: 'unsupported-platform' }
    }
    try {
      app.setLoginItemSettings({
        openAtLogin: !!enabled,
        // 隐藏/最小化启动，因此自动启动不引人注目；窗户可以
        // 仍然可以从 Dock/托盘中调出。
        openAsHidden: isMac ? true : undefined,
        args: isWin ? WIN_LOGIN_ARGS : undefined,
      })
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err)
      console.error('[login-item] setLoginItemSettings failed:', error)
      return { ok: false, enabled: isLaunchAtLoginEnabled(), error }
    }
    const effective = isLaunchAtLoginEnabled()
    return { ok: effective === !!enabled, enabled: effective, error: '' }
  })

  // 自动更新控件（渲染器驱动：检查，然后选择下载/安装）。
  // 渲染器传递其当前的 UI 语言，以便下载可以路由到
  // 中国 CDN 镜像 (zh) 或 R2（其他）。
  ipcMain.handle('update-check', (_event, lang?: string) => {
    setUpdateLanguage(lang)
    // 该通道仅受到明确的“检查更新”点击的影响，因此
    // 即使该版本之前已被驳回，面板也应重新打开。
    checkForUpdates(true)
  })
  ipcMain.handle('update-download', (_event, lang?: string) => {
    setUpdateLanguage(lang)
    startDownload()
  })
  ipcMain.handle('update-install', () => {
    // 让窗口真正关闭，以便应用程序可以完全退出 - 否则
    // close-to-tray handler PreventDefault()s it，进程保持活动状态，并且
    // Squirrel.Mac 无法交换应用程序包（静默更新，无操作）
    // 重新启动仍然显示旧版本）。
    isQuitting = true
    // 在移交给安装程序之前同步终止后端。开
    // Windows NSIS 静默更新程序会立即删除旧安装，并且
    // 仍在运行的owagent-backend.exe会锁定这些文件，从而中止更新
    // with "卸载旧应用程序文件失败:2". before-quit's async stop() sends SIGTERM
    // 并立即返回（对于本机 Windows exe 来说是无操作），因此它会丢失
    // 比赛。 stopSync() 会阻塞，直到进程树消失。尽力而为：
    // 永远不要让拆卸过程中的小问题阻碍更新。
    try {
      pythonBackend?.stopSync()
    } catch {
      // 忽略 — 无论如何继续安装
    }
    quitAndInstall()
  })

  // 同步操作系统区域设置查找（例如“zh-CN”、“en-US”）。由渲染器使用
  // 在任何绘制之前首次运行时选择合理的默认 UI 语言。
  ipcMain.on('get-system-locale', (event) => {
    event.returnValue = app.getLocale() || app.getSystemLocale?.() || ''
  })

  // 显示本机操作系统通知（例如调度程序提醒或已完成的任务）
  // 任务）。单击它会将窗口向前推进并要求渲染器打开
  // 给定的会话。
  ipcMain.handle('notify', (_event, payload: { title?: string; body?: string; sessionId?: string; silent?: boolean }) => {
    if (!Notification.isSupported() || !payload?.body) return false
    // 当窗口聚焦时跳过：用户已经在观看，因此
    // 通知（和声音）只是噪音，尤其是对于短期任务。
    if (mainWindow?.isFocused()) return false
    // 如果设置了运行时应用程序图标（通过 set-app-icon），则使用运行时应用程序图标，因此
    // 通知与当前窗口/Dock 图标匹配。跌回到
    // 打包的图标。
    const iconOpt = getRuntimeAppIcon() || getIconPath('png')
    const n = new Notification({
      title: payload.title || app.name,
      body: payload.body,
      silent: !!payload.silent,
      ...(iconOpt ? { icon: iconOpt } : {}),
    })
    n.on('click', () => {
      if (mainWindow) {
        if (mainWindow.isMinimized()) mainWindow.restore()
        mainWindow.show()
        mainWindow.focus()
      }
      if (payload.sessionId) {
        mainWindow?.webContents.send('open-session', payload.sessionId)
      }
    })
    n.show()
    return true
  })
}

function emitMaximizeState() {
  const max = mainWindow?.isMaximized() ?? false
  mainWindow?.webContents.send('window-maximize-changed', max)
}

// 单实例锁定：聚焦现有窗口而不是打开第二个应用程序。
const gotTheLock = app.requestSingleInstanceLock()
if (!gotTheLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.show()
      mainWindow.focus()
    }
  })
}

app.whenReady().then(async () => {
  // 在 macOS 上设置 Dock 图标（对于 nativeImage，PNG 最可靠）
  if (process.platform === 'darwin') {
    const pngPath = getIconPath('png')
    if (pngPath) {
      const icon = nativeImage.createFromPath(pngPath)
      if (!icon.isEmpty()) {
        app.dock.setIcon(icon)
        console.log('[Electron] Dock icon set:', pngPath)
      } else {
        console.warn('[Electron] Dock icon loaded but empty:', pngPath)
      }
    } else {
      console.warn('[Electron] Dock icon not found in resources/')
    }
  }

  // 聊天输入的录音使用 getUserMedia。媒体认可
  // 如果没有明确的处理程序，则无法保证权限请求
  // Electron 版本/平台，所以允许它们；其他权限类型保留
  // 与应用程序在没有处理程序的情况下具有相同的默认允许行为。
  session.defaultSession.setPermissionRequestHandler((_wc, _permission, callback) => callback(true))

  // 在 macOS 上，上面的 Chromium 层处理程序还不够：还有 getUserMedia
  // 需要系统级（TCC）麦克风授权，仅原生
  // AskForMediaAccess提示可以授予。预先请求，以便第一个麦克风
  // 单击将显示系统对话框，而不是因拒绝错误而失败。
  if (process.platform === 'darwin') {
    const micStatus = systemPreferences.getMediaAccessStatus('microphone')
    if (micStatus === 'not-determined') {
      systemPreferences.askForMediaAccess('microphone').catch(() => {})
    }
  }

  setupIPC()
  setupThemeIPC()
  setupHttpRelayIPC()
  setupAppIconIPC({ getWindow: () => mainWindow, getTray })
  createWindow()
  buildAppMenu(() => mainWindow)
  // macOS 上没有菜单栏托盘 - Dock + 窗口控件就足够了。
  // 将托盘保留在需要最小化为托盘图标的 Windows/Linux 上。
  if (!isMac) {
    createTray({
      getWindow: () => mainWindow,
      iconPath: getIconPath('png'),
      onQuit: () => {
        isQuitting = true
        app.quit()
      },
    })
  }
  // 在页面加载之前重新应用先前设置的图标/标题。
  applyCachedAppIcon()
  // 撤消上次更新对此应用程序的快捷方式造成的任何损坏。
  repairWindowsShortcuts()
  await startBackend()

  // 线路自动更新：启动后几秒钟进行第一次静默检查（所以它
  // 不与后端启动竞争），然后每 4 小时轮询一次，以便
  // 长时间运行的窗口仍然会出现新版本。两者都是自动检查
  // (userInitiated=false)：每个新版本面板自动打开一次，并且
  // 用户忽略它这些民意调查只会使页脚/菜单点保持点亮而不是
  // 而不是重新弹出面板。自动下载已关闭，因此任何更新都是选择加入的。
  initUpdater(() => mainWindow)
  setTimeout(() => checkForUpdates(), 5000)
  const UPDATE_POLL_MS = 4 * 60 * 60 * 1000
  setInterval(() => checkForUpdates(), UPDATE_POLL_MS)

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    } else {
      mainWindow?.show()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  isQuitting = true
  saveWindowState()
  destroyTray()
  pythonBackend?.stop()
})
