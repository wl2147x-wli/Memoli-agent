import { app, BrowserWindow, ipcMain, nativeImage, NativeImage, net, shell } from 'electron'
import { execFile } from 'child_process'
import path from 'path'
import fs from 'fs'
import os from 'os'

// 让web层在运行时覆盖窗口图标/标题并记住它，
// 因此它也适用于页面加载之前的下一次启动。

const CACHE_DIRNAME = 'app-icon'
const ICON_FILE = 'icon.png'
const ICO_FILE = 'icon.ico'
const META_FILE = 'meta.json'
const MAX_ICON_BYTES = 4 * 1024 * 1024
const DOWNLOAD_TIMEOUT_MS = 10 * 1000

interface CachedMeta {
  title?: string
  // 上次恢复桌面快捷方式的应用程序版本，因此快捷方式
  // 故意删除的用户不会在每次启动时都回来。
  shortcutRestoredFor?: string
  // 最后写入 NSIS 注册表的快捷方式名称的“<version>:<name>”
  // 值。版本范围，因为每个安装程序运行都会重置该值，因此
  // 每次更新后都必须再次进行同步。
  shortcutNameSyncedFor?: string
  // 上次扫描快捷方式的应用程序版本。改变意味着这是
  // 更新后首次启动，这是他们可以拥有的唯一点
  // 被损坏。
  shortcutsCheckedFor?: string
}

let getMainWindow: (() => BrowserWindow | null) | null = null
let getTrayIcon: (() => Electron.Tray | null) | null = null

function cacheDir(): string {
  const root = process.env.COW_HOME || path.join(os.homedir(), '.cow')
  return path.join(root, CACHE_DIRNAME)
}

function iconCachePath(): string {
  return path.join(cacheDir(), ICON_FILE)
}

function metaCachePath(): string {
  return path.join(cacheDir(), META_FILE)
}

function icoCachePath(): string {
  return path.join(cacheDir(), ICO_FILE)
}

// 在主进程中下载，这样字节就不会被文本传输破坏。
function downloadBuffer(url: string): Promise<Buffer | null> {
  return new Promise((resolve) => {
    let parsed: URL
    try {
      parsed = new URL(url)
    } catch {
      resolve(null)
      return
    }
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
      resolve(null)
      return
    }
    let done = false
    const finish = (buf: Buffer | null) => {
      if (done) return
      done = true
      resolve(buf)
    }
    const request = net.request({ method: 'GET', url })
    const timer = setTimeout(() => {
      request.abort()
      finish(null)
    }, DOWNLOAD_TIMEOUT_MS)
    request.on('response', (response) => {
      const chunks: Buffer[] = []
      let size = 0
      response.on('data', (chunk: Buffer) => {
        size += chunk.length
        if (size > MAX_ICON_BYTES) {
          request.abort()
          clearTimeout(timer)
          finish(null)
          return
        }
        chunks.push(chunk)
      })
      response.on('end', () => {
        clearTimeout(timer)
        finish(Buffer.concat(chunks))
      })
    })
    request.on('error', () => {
      clearTimeout(timer)
      finish(null)
    })
    request.end()
  })
}

async function downloadImage(url: string): Promise<NativeImage | null> {
  const buf = await downloadBuffer(url)
  if (!buf) return null
  const img = nativeImage.createFromBuffer(buf)
  return img.isEmpty() ? null : img
}

// 获取现成的多尺寸 .ico 并逐字缓存它，以便 Windows
// 快捷方式获得清晰的图标，无需有损 PNG 转换。拒绝有效负载
// 这不是真正的 .ico 文件（魔术字节 00 00 01 00）。
async function downloadIco(url: string): Promise<string | null> {
  const buf = await downloadBuffer(url)
  if (!buf || buf.length < 4 || buf.readUInt32LE(0) !== 0x00010000) return null
  try {
    fs.mkdirSync(cacheDir(), { recursive: true })
    fs.writeFileSync(icoCachePath(), buf)
    return icoCachePath()
  } catch (e) {
    console.warn('[app-icon] ico download write failed:', (e as Error).message)
    return null
  }
}

function applyIcon(icon: NativeImage): void {
  if (process.platform === 'darwin') {
    app.dock?.setIcon(icon)
  } else {
    getMainWindow?.()?.setIcon(icon)
  }
  const tray = getTrayIcon?.()
  if (tray) tray.setImage(icon.resize({ width: 18, height: 18 }))
}

// 仅窗口标题。 app.setName 故意不在这里调用：它也会移动
// app.getPath('userData')，并且在运行时会话/窗口已经
// 已经在旧路径下打开的文件 - 这两个文件最终会分开
// 目录。该名称是在启动时从缓存应用的（请参阅
// applyCachedAppName)，因此从下次启动时生效。
function applyTitle(title: string): void {
  const trimmed = title.trim()
  if (!trimmed) return
  getMainWindow?.()?.setTitle(trimmed)
}

function cacheIcon(icon: NativeImage): void {
  try {
    fs.mkdirSync(cacheDir(), { recursive: true })
    fs.writeFileSync(iconCachePath(), icon.toPNG())
  } catch (e) {
    console.warn('[app-icon] icon cache write failed:', (e as Error).message)
  }
}

function cacheMeta(meta: CachedMeta): void {
  try {
    fs.mkdirSync(cacheDir(), { recursive: true })
    let existing: CachedMeta = {}
    try {
      existing = JSON.parse(fs.readFileSync(metaCachePath(), 'utf8')) as CachedMeta
    } catch {
      /* 第一次写入或不可读 */
    }
    fs.writeFileSync(metaCachePath(), JSON.stringify({ ...existing, ...meta }))
  } catch (e) {
    console.warn('[app-icon] meta cache write failed:', (e as Error).message)
  }
}

// 应用之前设置的应用程序名称。必须在任何接触之前调用
// app.getPath('userData') （即在 app.whenReady / 窗口创建之前），因为
// app.setName 更改该路径指向的位置：稍后调用它会搁浅
// 以以前的名称写入的数据。
export function applyCachedAppName(): void {
  try {
    const meta = JSON.parse(fs.readFileSync(metaCachePath(), 'utf8')) as CachedMeta
    const trimmed = meta.title?.trim()
    if (trimmed) app.setName(trimmed)
  } catch {
    /* 没有缓存的标题 */
  }
}

// 在页面加载之前应用缓存的图标/标题，以便显示自定义标记
// 从第一次绘制而不是默认闪烁。
export function applyCachedAppIcon(): void {
  let icon: NativeImage | null = null
  try {
    const buf = fs.readFileSync(iconCachePath())
    if (buf.length && buf.length <= MAX_ICON_BYTES) {
      const img = nativeImage.createFromBuffer(buf)
      if (!img.isEmpty()) icon = img
    }
  } catch {
    /* 没有缓存的图标 */
  }
  if (icon) applyIcon(icon)

  try {
    const meta = JSON.parse(fs.readFileSync(metaCachePath(), 'utf8')) as CachedMeta
    if (meta.title) applyTitle(meta.title)
  } catch {
    /* 没有缓存的标题 */
  }
}

// 通过 set-app-icon 设置的运行时图标（下载并缓存），以供重用
// 其他地方——例如作为本机通知上的图像，因此它们与
// 当前窗口/Dock 图标。当没有应用自定义图标时返回 null，
// 这样呼叫者就可以退回到捆绑图标。
export function getRuntimeAppIcon(): NativeImage | null {
  try {
    const buf = fs.readFileSync(iconCachePath())
    if (!buf.length || buf.length > MAX_ICON_BYTES) return null
    const img = nativeImage.createFromBuffer(buf)
    return img.isEmpty() ? null : img
  } catch {
    return null
  }
}

// Windows 快捷方式需要一个 .ico，因此可以从缓存中派生一个多尺寸的快捷方式
// 当未提供现成的 .ico 时为 PNG。
async function writeIcoFromCachedPng(): Promise<string | null> {
  const png = iconCachePath()
  if (!fs.existsSync(png)) return null
  try {
    const { default: pngToIco } = await import('png-to-ico')
    const buf = await pngToIco(png)
    fs.mkdirSync(cacheDir(), { recursive: true })
    fs.writeFileSync(icoCachePath(), buf)
    return icoCachePath()
  } catch (e) {
    console.warn('[app-icon] ico generation failed:', (e as Error).message)
    return null
  }
}

// 通过 Electron 解决，而不是从主目录组装：
// OneDrive文件夹备份使真正的桌面生活在OneDrive下
// 文件夹和 ~/Desktop 可能根本不存在。
function desktopDir(): string {
  try {
    return app.getPath('desktop')
  } catch {
    return path.join(os.homedir(), 'Desktop')
  }
}

// 可能包含此应用程序快捷方式的目录。
function shortcutDirs(): string[] {
  const home = os.homedir()
  const appData = process.env.APPDATA || path.join(home, 'AppData', 'Roaming')
  const dirs = [
    desktopDir(),
    path.join(home, 'Desktop'),
    path.join(appData, 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
  ]
  const seen = new Set<string>()
  return dirs.filter((dir) => {
    const key = path.resolve(dir).toLowerCase()
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function sanitizeShortcutName(title: string): string {
  return title.replace(/[<>:"/\\|?*\x00-\x1f]/g, '').trim()
}

// Electron-builder 的 NSIS 卸载程序通过移出每个文件来进行更新
// 将安装目录放入“$PLUGINSDIR\old-install”（%TEMP% 下的文件夹），
// 擦除安装目录，然后通知 shell。目标获得的捷径
// 在该窗口期间重新解析最终指向该暂存文件夹，
// 安装程序退出时会删除它 - 留下一个失败的快捷方式
// “该项目已被移动或重命名”。
const NSIS_UPDATE_STAGING_DIR = 'old-install'

type ShortcutKind =
  // 指向正在运行的可执行文件——没有什么需要修复的。
  | 'current'
  // 我们的，但目标不再解析（通常是 NSIS 暂存路径
  // 上面）。可以安全地重新指向正在运行的可执行文件。
  | 'stale'
  // 其他人的快捷方式，或者仍然存在的第二个安装。
  | 'foreign'

function classifyShortcut(target: string | undefined): ShortcutKind {
  if (!target) return 'foreign'
  let resolved: string
  try {
    resolved = path.resolve(target)
  } catch {
    return 'foreign'
  }
  if (resolved.toLowerCase() === path.resolve(process.execPath).toLowerCase()) return 'current'
  // 只采用命名我们自己的可执行文件的链接，因此是某些的快捷方式
  // 其他应用程序永远不会被重写。
  if (path.basename(resolved).toLowerCase() !== path.basename(process.execPath).toLowerCase()) {
    return 'foreign'
  }
  const inStagingDir = resolved
    .toLowerCase()
    .split(path.sep)
    .includes(NSIS_UPDATE_STAGING_DIR)
  if (inStagingDir || !fs.existsSync(resolved)) return 'stale'
  // 该应用程序的不同安装仍然存在 - 不要管它。
  return 'foreign'
}

// 在 Windows 上，现有快捷方式（桌面 + 开始菜单）保留图标和名称
// 它们是在安装时创建的。带上属于此的所有快捷方式
// 应用程序与运行时图标/标签一致，重新指向以前的任何图标/标签
// 更新悬空并恢复桌面（如果丢失）
// 完全。其他地方禁止操作。
function syncWindowsShortcuts(opts: {
  icoPath?: string | null
  title?: string
  // 即使没有任何明显变化，也要重写每个快捷方式。用于第一个
  // 更新后启动：链接可以携带看起来有效的目标，而其
  // shell 链接跟踪数据已经指向暂存目录，并且唯一的
  // 清除的方法是重新编写链接。
  force?: boolean
}): void {
  if (process.platform !== 'win32') return
  const icoPath = opts.icoPath
  const title = opts.title ? sanitizeShortcutName(opts.title) : ''
  const desktops = new Set(
    [desktopDir(), path.join(os.homedir(), 'Desktop')].map((d) => path.resolve(d).toLowerCase()),
  )
  let desktopLinks = 0
  let renamedTo = ''
  let template: Electron.ShortcutDetails | null = null

  for (const dir of shortcutDirs()) {
    let entries: string[]
    try {
      entries = fs.readdirSync(dir).filter((n) => n.toLowerCase().endsWith('.lnk'))
    } catch {
      continue
    }
    for (const name of entries) {
      let linkPath = path.join(dir, name)
      let details: Electron.ShortcutDetails
      try {
        details = shell.readShortcutLink(linkPath)
      } catch {
        continue
      }
      const kind = classifyShortcut(details.target)
      if (kind === 'foreign') continue
      if (desktops.has(path.resolve(dir).toLowerCase())) desktopLinks++

      // 在重命名之前修复悬空目标，因此重命名永远不会携带
      // 到新文件名的死路径。
      if (kind === 'stale') {
        details = { ...details, target: process.execPath, cwd: path.dirname(process.execPath) }
      }

      if (title) {
        const target = path.join(dir, `${title}.lnk`)
        if (path.resolve(target).toLowerCase() !== path.resolve(linkPath).toLowerCase()) {
          try {
            fs.renameSync(linkPath, target)
            linkPath = target
          } catch (e) {
            console.warn('[app-icon] shortcut rename failed:', (e as Error).message)
          }
        }
        // 仅当文件实际携带该名称时才声明该名称，因此失败
        // 重命名不能将安装程序指向不存在的东西。
        if (path.basename(linkPath) === `${title}.lnk`) renamedTo = title
      }

      const next: Electron.ShortcutDetails = { ...details }
      if (icoPath) next.icon = icoPath
      if (typeof next.iconIndex !== 'number') next.iconIndex = 0
      template = next
      // 重写 .lnk 会重新标记其 shell 链接跟踪数据，这就是
      // 让 shell 跟随可执行文件进入更新暂存目录
      // 第一名。所以只有在事情确实发生变化时才写。
      const iconChanged = !!next.icon && next.icon !== details.icon
      if (kind === 'stale' || iconChanged || opts.force) {
        try {
          shell.writeShortcutLink(linkPath, 'update', next)
        } catch (e) {
          console.warn('[app-icon] shortcut update failed:', (e as Error).message)
        }
      }
    }
  }

  // 从 NSIS 下重命名快捷方式的更新可能会保留
  // 桌面上根本没有可用的东西：安装程序仅刷新链接
  // 它记录了谁的名字，并且在更新时永远不会重新创建一个名字。放一个
  // 回馈用户而不是让用户无路可走。
  if (desktopLinks === 0) {
    restoreDesktopShortcut(desktopDir(), title, icoPath, template)
  }
  if (renamedTo) void recordShortcutName(renamedTo)
}

function restoreDesktopShortcut(
  desktop: string,
  title: string,
  icoPath: string | null | undefined,
  template: Electron.ShortcutDetails | null,
): void {
  if (!app.isPackaged) return
  const name = sanitizeShortcutName(title || app.getName())
  if (!name || !fs.existsSync(desktop)) return
  // 每个版本一次：足以消除更新造成的损害，无需
  // 恢复用户故意删除的快捷方式。
  let meta: CachedMeta = {}
  try {
    meta = JSON.parse(fs.readFileSync(metaCachePath(), 'utf8')) as CachedMeta
  } catch {
    /* 第一次运行 */
  }
  if (meta.shortcutRestoredFor === app.getVersion()) return

  const details: Electron.ShortcutDetails = {
    ...(template || {}),
    target: process.execPath,
    cwd: path.dirname(process.execPath),
  }
  if (icoPath) details.icon = icoPath
  if (details.icon && typeof details.iconIndex !== 'number') details.iconIndex = 0
  try {
    shell.writeShortcutLink(path.join(desktop, `${name}.lnk`), 'create', details)
    cacheMeta({ shortcutRestoredFor: app.getVersion() })
    console.log('[app-icon] restored missing desktop shortcut')
  } catch (e) {
    console.warn('[app-icon] desktop shortcut restore failed:', (e as Error).message)
  }
}

function reg(args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile('reg.exe', args, { windowsHide: true }, (err, stdout) => {
      if (err) reject(err)
      else resolve(stdout)
    })
  })
}

const UNINSTALL_KEY = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall'

// Electron-builder 的 NSIS 脚本通过以下方式找到现有的快捷方式
// 此应用程序的卸载密钥下的 ShortcutName 值（请参阅中的 setLinkVars
// 常见的.nsh）。重命名 .lnk 而不更新该值会使该文件
// 对于下一个安装程序/卸载程序不可见：它既不能刷新也不能清理
// 上快捷方式，这就是悬空的快捷方式在更新中幸存下来的方式。保留两个
// 同步，以便快捷方式保持在 NSIS 的管理之下。
//
// 密钥名称是生成的 GUID，因此可以通过安装位置找到它，而不是
// 猜测。尽力而为：每台机器安装在 HKLM 下并且需要
// 我们没有海拔，在这种情况下，这根本不起作用。
async function recordShortcutName(name: string): Promise<void> {
  const installDir = path.dirname(process.execPath)
  // 扫描整个卸载树并不是免费的，因此一旦该值达到，请跳过它
  // 已知此版本已到位。
  const stamp = `${app.getVersion()}:${name}`
  try {
    const meta = JSON.parse(fs.readFileSync(metaCachePath(), 'utf8')) as CachedMeta
    if (meta.shortcutNameSyncedFor === stamp) return
  } catch {
    /* 还没有缓存 */
  }
  try {
    const out = await reg(['query', `HKCU\\${UNINSTALL_KEY}`, '/s', '/v', 'InstallLocation'])
    let currentKey = ''
    for (const line of out.split(/\r?\n/)) {
      const key = line.match(/^(HKEY_CURRENT_USER\\.+)$/)
      if (key) {
        currentKey = key[1]
        continue
      }
      const value = line.match(/^\s+InstallLocation\s+REG_SZ\s+(.+?)\s*$/)
      if (!value || !currentKey) continue
      if (path.resolve(value[1]).toLowerCase() !== installDir.toLowerCase()) continue
      await reg(['add', currentKey, '/v', 'ShortcutName', '/t', 'REG_SZ', '/d', name, '/f'])
      cacheMeta({ shortcutNameSyncedFor: stamp })
      return
    }
  } catch (e) {
    console.warn('[app-icon] shortcut name registry sync failed:', (e as Error).message)
  }
}

// 修复了先前更新留下的快捷方式的问题。运行于每个
// 无论图标/标题是否被覆盖，Windows 都会启动：
// staging-dir 问题来自 NSIS 更新流程，因此任何安装都可以命中
// 它 - 并且用户无法使用无法使用的桌面快捷方式
// 预计用手修复。
export function repairWindowsShortcuts(): void {
  if (process.platform !== 'win32') return
  let title = ''
  let checkedFor = ''
  try {
    const meta = JSON.parse(fs.readFileSync(metaCachePath(), 'utf8')) as CachedMeta
    title = meta.title?.trim() || ''
    checkedFor = meta.shortcutsCheckedFor || ''
  } catch {
    /* 第一次运行 */
  }
  const ico = fs.existsSync(icoCachePath()) ? icoCachePath() : null
  syncWindowsShortcuts({ title, icoPath: ico, force: checkedFor !== app.getVersion() })
  cacheMeta({ shortcutsCheckedFor: app.getVersion() })
}

export function setupAppIconIPC(deps: {
  getWindow: () => BrowserWindow | null
  getTray: () => Electron.Tray | null
}): void {
  getMainWindow = deps.getWindow
  getTrayIcon = deps.getTray

  ipcMain.handle('set-app-icon', async (_event, iconUrl: unknown, icoUrl: unknown) => {
    if (typeof iconUrl !== 'string' || !iconUrl) return false
    const icon = await downloadImage(iconUrl)
    if (!icon) return false
    applyIcon(icon)
    cacheIcon(icon)
    if (process.platform === 'win32') {
      let icoPath: string | null = null
      if (typeof icoUrl === 'string' && icoUrl) icoPath = await downloadIco(icoUrl)
      if (!icoPath) icoPath = await writeIcoFromCachedPng()
      syncWindowsShortcuts({ icoPath })
    }
    return true
  })

  ipcMain.handle('set-app-title', (_event, title: unknown) => {
    if (typeof title !== 'string' || !title.trim()) return false
    applyTitle(title)
    cacheMeta({ title })
    // 重用缓存的图标（如果有），以便重命名的快捷方式保留它。
    const ico = fs.existsSync(icoCachePath()) ? icoCachePath() : null
    syncWindowsShortcuts({ title, icoPath: ico })
    return true
  })
}
