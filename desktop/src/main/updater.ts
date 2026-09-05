import { app, BrowserWindow } from 'electron'
import fs from 'fs'
import os from 'os'
import path from 'path'
// Electron-updater 是 CommonJS：它的成员位于 module.exports 上，没有
// 有意义的默认导出。在 module=commonjs + esModuleInterop 下，一个名为
// import 编译为 `electron_updater_1.autoUpdater` 并正确解析，
// 而 `import pkg from 'electron-updater'` 产生未定义。
import { autoUpdater } from 'electron-updater'
import { loadAppConfig } from './themes'

// 状态有效负载通过“更新状态”通道推送到渲染器。
// 渲染器从这些驱动 NavRail 徽章 + 更新面板。
export type UpdateStatus =
  | { state: 'checking' }
  // userInitiated：检查来自明确的“检查更新”点击
  // （不是启动/间隔轮询）。渲染器使用它来决定是否
  // 自动打开面板：自动检查保持静默（仅点）一次
  // 版本被驳回；手动检查总是会重新打开。
  | { state: 'available'; version: string; notes?: string; userInitiated?: boolean }
  | { state: 'not-available' }
  | { state: 'downloading'; percent: number }
  | { state: 'downloaded'; version: string }
  | { state: 'error'; message: string }

let getWindow: () => BrowserWindow | null = () => null

// 旧版 Windows (7/8/8.1) 运行单独的 Electron-22 版本，该版本必须
// 更新到其他遗留版本 - 永远不会更新标准版本（Electron 33 不会
// 在 Win7 上启动）。更新功能服务于 /update/legacy/ 下的构建。
// 我们在运行时检测旧操作系统（os.release() 报告 Windows NT 版本：
// 6.1 = Win7、6.2/6.3 = Win8/8.1、10.x = Win10/11）而不是通过构建
// 标志，因此同一个源可以为其运行的任何内容提供正确的提要。
function isLegacyWindows(): boolean {
  if (process.platform !== 'win32') return false
  const major = Number((os.release() || '').split('.')[0])
  // NT 6.x=Win7/8/8.1； NT 10.x = Win10/11。旧 = 主要 < 10。
  return Number.isFinite(major) && major < 10
}

// 捆绑的应用程序配置可能会将更新程序指向不同的源。当
// 设置后，按原样使用单个 URL（没有 China/R2 双源切换，这
// 特定于默认构建的基础设施）。缺席 -> 默认提要。
const CONFIGURED_FEED = (loadAppConfig()?.updateFeedUrl || '').trim()

// 更新源。两个条目都达到相同的页面功能
// (https://cowagent.ai/update/); ?lang=zh 查询告诉 302 安装程序
// 下载到中国CDN镜像而不是R2。提要元数据是
// 两种方式都相同，因此我们可以在尝试之间自由切换提要 URL
// 从一个下载源回退到另一个下载源。旧版 Windows 会附加一个
// /legacy/ 段，因此它获得 win-legacy 版本而不是标准版本。
const FEED_BASE = 'https://cowagent.ai/update/' + (isLegacyWindows() ? 'legacy/' : '')
const feedUrlFor = (china: boolean) => {
  if (CONFIGURED_FEED) return CONFIGURED_FEED
  return china ? `${FEED_BASE}?lang=zh` : FEED_BASE
}

// 当前会话更喜欢哪个来源，源自应用程序 UI 语言
// （zh -> 中国镜报）。在首选源上失败的下载重试一次
// 在出现错误之前先检查另一台。
let preferChina = false
// 保护单个下载只回退一次（避免乒乓）。
let downloadFellBack = false

function applyFeedUrl(): void {
  const url = feedUrlFor(preferChina)
  try {
    autoUpdater.setFeedURL({ provider: 'generic', url })
    log(`feed url set: ${url} (preferChina=${preferChina})`)
  } catch (err) {
    log(`feed url set failed: ${(err as Error)?.message || String(err)}`)
  }
}

// 使用渲染器的当前 UI 语言从检查/下载 IPC 调用。
export function setUpdateLanguage(lang: string | undefined): void {
  const china = (lang || '').toLowerCase().startsWith('zh')
  if (china !== preferChina) {
    preferChina = china
    if (app.isPackaged) applyFeedUrl()
  }
}

// 将更新日志保留到文件中，这样用户就不会点击静默的“旋转器”
// 解决”可以只向我们发送 userData/logs/updater.log。我们不能依赖
// 日志记录部门，所以这是一个小型的仅附加编写器，加上控制台
// 应用程序内日志视图/终端。
let logFile: string | null = null

function initLogFile() {
  try {
    const dir = path.join(app.getPath('userData'), 'logs')
    fs.mkdirSync(dir, { recursive: true })
    logFile = path.join(dir, 'updater.log')
  } catch {
    logFile = null
  }
}

function log(...parts: unknown[]) {
  const line = `[${new Date().toISOString()}] [updater] ${parts
    .map((p) => (typeof p === 'string' ? p : safeStringify(p)))
    .join(' ')}`
  // 控制台：显示在终端 (dev) 和打包应用程序的标准输出中。
  console.log(line)
  if (logFile) {
    try {
      fs.appendFileSync(logFile, line + '\n')
    } catch {
      // 忽略磁盘错误 - 日志记录绝不能破坏更新程序
    }
  }
}

function safeStringify(v: unknown): string {
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

function send(status: UpdateStatus) {
  getWindow()?.webContents.send('update-status', status)
}

export function initUpdater(windowGetter: () => BrowserWindow | null): void {
  getWindow = windowGetter
  initLogFile()

  log(`init: appVersion=${app.getVersion()} packaged=${app.isPackaged} logFile=${logFile ?? '<none>'}`)

  // 在开发（未打包）中没有更新源；完全跳过接线
  // Electron-updater 不会抛出丢失的 app-update.yml。
  if (!app.isPackaged) {
    log('not packaged — updater wiring skipped')
    return
  }

  // 用户驱动的流程：我们显示“可用”并让用户选择加入
  // 下载，而不是在后台默默地拉取字节。
  autoUpdater.autoDownload = false
  autoUpdater.autoInstallOnAppQuit = true
  // 桌面频道提供预发布标记的版本（例如 0.0.8-test），因此
  // 必须允许与当前版本（例如 0.0.7-test）进行比较，并且
  // 提供的其他预发布版本。没有这个电子更新器的 semver
  // 比较可以默默地跳过预发布，既不“可用”也不
  // “不可用”触发——用户界面永远旋转。
  autoUpdater.allowPrerelease = true
  autoUpdater.allowDowngrade = false
  // 预先指向首选起点（默认为 R2；切换到 CN
  // 一旦渲染器通过 setUpdateLanguage 报告 zh UI 语言就进行镜像）。
  applyFeedUrl()
  // 将电子更新程序自己的内部日志记录也路由到我们的文件，所以我们
  // 捕获提要 URL、解析的版本以及它记录的任何堆栈跟踪。
  autoUpdater.logger = {
    info: (m: unknown) => log('eu-info:', m),
    warn: (m: unknown) => log('eu-warn:', m),
    error: (m: unknown) => log('eu-error:', m),
    debug: (m: unknown) => log('eu-debug:', m),
  } as unknown as typeof autoUpdater.logger

  autoUpdater.on('checking-for-update', () => {
    log(`checking-for-update: current=${app.getVersion()}`)
    send({ state: 'checking' })
  })
  autoUpdater.on('update-available', (info) => {
    log(`update-available: current=${app.getVersion()} remote=${info.version} userInitiated=${userInitiatedCheck} -> update needed`)
    send({
      state: 'available',
      version: info.version,
      notes: typeof info.releaseNotes === 'string' ? info.releaseNotes : undefined,
      userInitiated: userInitiatedCheck,
    })
  })
  autoUpdater.on('update-not-available', (info) => {
    log(`update-not-available: current=${app.getVersion()} remote=${info?.version ?? '<unknown>'} -> up to date`)
    send({ state: 'not-available' })
  })
  autoUpdater.on('download-progress', (p) => {
    log(`download-progress: ${Math.round(p.percent)}% (${p.transferred}/${p.total} bytes, ${Math.round(p.bytesPerSecond / 1024)} KB/s)`)
    send({ state: 'downloading', percent: Math.round(p.percent) })
  })
  autoUpdater.on('update-downloaded', (info) => {
    log(`update-downloaded: version=${info.version} -> ready to install`)
    send({ state: 'downloaded', version: info.version })
  })
  autoUpdater.on('error', (err) => {
    const message = err == null ? 'unknown' : err.message || String(err)
    log(`error: ${message}`, err instanceof Error && err.stack ? err.stack : '')
    send({ state: 'error', message })
  })
}

// 跟踪运行中检查是否由明确的用户点击触发。
// 标记到生成的“可用”事件上，以便渲染器知道是否
// 自动打开面板（手动）或仅用点保持沉默（自动）。
let userInitiatedCheck = false

// 启动后不久进行静默检查。未打包时没有更新源，
// 但手动点击仍然应该得到可见的反馈，而不是看起来死了：
// 回复“不可用”，以便菜单可以显示“最新”。
//   userInitiated：传递 true 来明确“检查更新”单击，以便
//   即使该版本之前被驳回，面板也会重新打开。启动+
//   间隔民意调查传递错误，因此被驳回的版本只会点亮点。
export function checkForUpdates(userInitiated = false): void {
  userInitiatedCheck = userInitiated
  if (!app.isPackaged) {
    // 仅限开发的 UI 工具：设置 COW_MOCK_UPDATE=1 来模拟可用的
    // 更新，以便可以在以下位置执行更新面板/菜单交互
    // `npm run dev`（没有真正的提要）。永远不会在打包的应用程序中运行。
    if (process.env.COW_MOCK_UPDATE) {
      const version = process.env.COW_MOCK_UPDATE_VERSION || '9.9.9'
      log(`checkForUpdates: not packaged, MOCK available version=${version}`)
      send({ state: 'available', version, userInitiated: userInitiatedCheck })
      return
    }
    log('checkForUpdates: not packaged, replying not-available')
    send({ state: 'not-available' })
    return
  }
  log(`checkForUpdates: requesting feed, current=${app.getVersion()}`)
  autoUpdater.checkForUpdates().catch((err) => {
    const message = err?.message || String(err)
    log(`checkForUpdates: request failed: ${message}`, err instanceof Error && err.stack ? err.stack : '')
    send({ state: 'error', message })
  })
}

export function startDownload(): void {
  if (!app.isPackaged) return
  downloadFellBack = false
  log(`startDownload: user requested download (preferChina=${preferChina})`)
  attemptDownload()
}

// 从当前来源下载；失败时，切换到 OTHER 原点一次
// 并重试。这是客户端“互为镜像”的后备方案：R2 和
// 中国 CDN 持有相同的字节，因此可以交换缓慢/阻塞的源
// 透明地在用户不注意的情况下。
function attemptDownload(): void {
  autoUpdater.downloadUpdate().catch((err) => {
    const message = err?.message || String(err)
    log(`startDownload: failed on ${preferChina ? 'CN' : 'R2'}: ${message}`, err instanceof Error && err.stack ? err.stack : '')
    if (!downloadFellBack) {
      downloadFellBack = true
      preferChina = !preferChina
      applyFeedUrl()
      log(`startDownload: retrying on ${preferChina ? 'CN' : 'R2'} mirror`)
      // 首先重新检查，以便电子更新程序从新源重新读取提要
      // 下载之前（其缓存的 updateInfo 与来源无关，但是
      // 新鲜检查保持内部状态一致）。
      autoUpdater
        .checkForUpdates()
        .then(() => autoUpdater.downloadUpdate())
        .catch((err2) => {
          const m2 = err2?.message || String(err2)
          log(`startDownload: fallback also failed: ${m2}`, err2 instanceof Error && err2.stack ? err2.stack : '')
          send({ state: 'error', message: m2 })
        })
      return
    }
    send({ state: 'error', message })
  })
}

export function quitAndInstall(): void {
  if (!app.isPackaged) return
  log('quitAndInstall: relaunching to install update')
  // 首先删除窗口全部关闭的处理程序：延迟处理程序可以保留窗口
  // 进程处于活动状态并阻止安装程序替换文件/重新启动
  // （记录在案的电子更新程序陷阱，尤其是在 Windows NSIS 上）。
  app.removeAllListeners('window-all-closed')
  // 在 Windows 上 isSilent=TRUE。我们的安装程序现在已被协助（nsis.oneClick=false
  // +allowToChangeInstallationDirectory) 因此第一次安装显示
  // 目录/模式向导。但更新不得重新显示该向导 — isSilent
  // 跳过它并就地更新。 isForceRunAfter=true 后重新启动
  // 无声更新。 （旧的辅助+静音强制运行错误，＃2179，已修复
  // PR #2278 中的上游；我们使用的是 electro-updater 6.8.9，已经过去了。）
  // setImmediate + removeAllListeners 是记录的先决条件
  // 重新启动即可可靠地开火。 macOS 完全忽略 isSilent。
  setImmediate(() => autoUpdater.quitAndInstall(true, true))
}
