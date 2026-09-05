import { app, ipcMain } from 'electron'
import path from 'path'
import fs from 'fs'
import os from 'os'

// 主题来自两个来源并在加载时合并：
//
//   1. 捆绑主题 — 资源/主题/在应用程序包内提供
//      （只读）。仅存在于由风味产生的构建中；缺席
//      在标准构建中。
//   2. 用户主题 — ~/.cow/themes/，用户可以添加的共享数据目录
//      （通过未来的应用内商店/导入）。每个主题都有自己的文件夹：
//
//        <id>/
//          ├── theme.json (必填)
//          ├── 壁纸.jpg（可选）
//          └── logo.svg（可选）
//
// 可选的应用程序配置（resources/app-config.json）可以设置首次运行
// 默认主题和显示名称。当它不存在时，应用程序的行为完全一样
// 作为标准构建（默认主题，自由切换）。

const THEMES_DIRNAME = 'themes'
// 内联图像的最大字节数（反映主题规范限制）。
const MAX_IMAGE_BYTES = 16 * 1024 * 1024
const IMAGE_MIME: Record<string, string> = {
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
  '.gif': 'image/gif',
}

function cowRoot(): string {
  // 遵循显式覆盖，否则默认为 ~/.cow 以匹配后端。
  return process.env.COW_HOME || path.join(os.homedir(), '.cow')
}

export function themesDir(): string {
  return path.join(cowRoot(), THEMES_DIRNAME)
}

// 包含应用程序包内捆绑的主题的目录（只读）。开发中
// 它映射到存储库的资源/；在打包的应用程序中到 process.resourcesPath。
// 当该文件夹不存在时返回 null（标准版本）。
function bundledThemesDir(): string | null {
  const base = app.isPackaged
    ? path.join(process.resourcesPath, THEMES_DIRNAME)
    : path.resolve(__dirname, '../../resources', THEMES_DIRNAME)
  try {
    return fs.statSync(base).isDirectory() ? base : null
  } catch {
    return null
  }
}

// 与应用程序捆绑在一起的可选应用程序配置。标准版本中不存在。
export interface AppConfig {
  defaultTheme?: string
  appName?: string
  // 可选的运行时源标签转发到后端进行统计。
  clientSource?: string
  // 自动更新源基本 URL 的可选覆盖。设置后，更新程序
  // 按原样使用它而不是默认构建的提要。
  updateFeedUrl?: string
}

function appConfigPath(): string {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'app-config.json')
    : path.resolve(__dirname, '../../resources', 'app-config.json')
}

export function loadAppConfig(): AppConfig | null {
  try {
    const raw = fs.readFileSync(appConfigPath(), 'utf8')
    const parsed = JSON.parse(raw) as AppConfig
    if (!parsed || typeof parsed !== 'object') return null
    return parsed
  } catch {
    return null // 没有应用程序配置 → 标准行为
  }
}

function ensureThemesDir(): string {
  const dir = themesDir()
  try {
    fs.mkdirSync(dir, { recursive: true })
  } catch {
    // 非致命：扫描不会返回任何主题。
  }
  return dir
}

// 读取主题文件夹内的图像并返回 data: URL 或 null。的
// 路径被限制为主题文件夹以避免通过“..”转义。
function inlineImage(themeFolder: string, rel: string): string | null {
  if (!rel || typeof rel !== 'string') return null
  const resolved = path.resolve(themeFolder, rel)
  if (resolved !== themeFolder && !resolved.startsWith(themeFolder + path.sep)) return null
  let stat: fs.Stats
  try {
    stat = fs.statSync(resolved)
  } catch {
    return null
  }
  if (!stat.isFile() || stat.size === 0 || stat.size > MAX_IMAGE_BYTES) return null
  const ext = path.extname(resolved).toLowerCase()
  const mime = IMAGE_MIME[ext]
  if (!mime) return null
  try {
    const buf = fs.readFileSync(resolved)
    return `data:${mime};base64,${buf.toString('base64')}`
  } catch {
    return null
  }
}

// 遍历主题对象并替换任何壁纸/徽标图像*文件引用*
// 具有内联数据 URL，以便渲染器可以直接使用它们。
function inlineThemeAssets(theme: Record<string, unknown>, themeFolder: string) {
  for (const appearance of ['light', 'dark'] as const) {
    const app_ = theme[appearance] as Record<string, unknown> | undefined
    const wp = app_?.wallpaper as Record<string, unknown> | undefined
    if (wp && typeof wp.image === 'string') {
      const url = inlineImage(themeFolder, wp.image)
      if (url) wp.image = url
      else delete wp.image
    }
  }
  const identity = theme.identity as Record<string, unknown> | undefined
  if (identity && typeof identity.logo === 'string') {
    const url = inlineImage(themeFolder, identity.logo)
    if (url) identity.logo = url
    else delete identity.logo
  }
}

// 扫描一个目录中的主题文件夹并返回经过验证的、资产内嵌的主题。
function scanDir(dir: string): Record<string, unknown>[] {
  let entries: fs.Dirent[]
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true })
  } catch {
    return []
  }
  const themes: Record<string, unknown>[] = []
  for (const entry of entries) {
    if (!entry.isDirectory()) continue
    const folder = path.join(dir, entry.name)
    const jsonPath = path.join(folder, 'theme.json')
    let raw: string
    try {
      raw = fs.readFileSync(jsonPath, 'utf8')
    } catch {
      continue // 该文件夹中没有 theme.json
    }
    let theme: Record<string, unknown>
    try {
      theme = JSON.parse(raw)
    } catch (e) {
      console.warn(`[themes] invalid theme.json in ${entry.name}:`, (e as Error).message)
      continue
    }
    // 默认 id 为文件夹名称，因此它始终稳定/唯一。
    if (!theme.id || typeof theme.id !== 'string') theme.id = entry.name
    if (!theme.name || typeof theme.name !== 'string') theme.name = String(theme.id)
    inlineThemeAssets(theme, folder)
    themes.push(theme)
  }
  return themes
}

// 将捆绑主题（只读，随包提供）与用户主题合并
// （~/.cow/themes）。捆绑主题优先于 ID 冲突，因此已发货
// 主题不能被相同 ID 的用户文件夹遮蔽。
export function loadThemes(): Record<string, unknown>[] {
  ensureThemesDir()
  const byId = new Map<string, Record<string, unknown>>()
  for (const theme of scanDir(themesDir())) byId.set(String(theme.id), theme)
  const bundled = bundledThemesDir()
  if (bundled) {
    for (const theme of scanDir(bundled)) byId.set(String(theme.id), theme)
  }
  return [...byId.values()]
}

export function setupThemeIPC() {
  ipcMain.handle('themes-list', () => {
    try {
      return loadThemes()
    } catch (e) {
      console.warn('[themes] load failed:', (e as Error).message)
      return []
    }
  })
  ipcMain.handle('themes-dir', () => themesDir())
  ipcMain.handle('app-config-get', () => loadAppConfig())
}
