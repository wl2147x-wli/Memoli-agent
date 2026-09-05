import { useState, useEffect, useCallback } from 'react'
import {
  COLOR_KEYS,
  DEFAULT_THEME_ID,
  getAllThemes,
  getTheme,
  registerRuntimeThemes,
  SHAPE_KEYS,
  tokenToCssVar,
  type Theme,
  type Wallpaper,
} from '../theme/themes'

export type ThemePref = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

// 外观偏好（浅色/深色/系统）。
const PREF_KEY = 'cow_theme'
// 选定的主题 ID（哪个视觉主题处于活动状态）。
const THEME_ID_KEY = 'cow_theme_id'

function getSystemTheme(): ResolvedTheme {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function readStoredPref(): ThemePref {
  const saved = localStorage.getItem(PREF_KEY)
  if (saved === 'dark' || saved === 'light' || saved === 'system') return saved
  // 首次运行：遵循操作系统外观，而不是强制使用固定主题。
  return 'system'
}

function readStoredThemeId(): string {
  return localStorage.getItem(THEME_ID_KEY) || DEFAULT_THEME_ID
}

// 用户是否曾经明确选择过主题。使用如此捆绑
// 首次运行默认值仅在用户尚未做出选择时适用。
function hasStoredThemeId(): boolean {
  return localStorage.getItem(THEME_ID_KEY) != null
}

// 主题可能注入的所有 CSS 变量，因此我们可以在之前完全重置
// 应用其中之一（防止过时的覆盖在交换机之间泄漏）。
const WALLPAPER_VARS = [
  '--wallpaper-image',
  '--wallpaper-position',
  '--wallpaper-overlay',
  '--glass-fill',
  '--glass-blur',
  '--surface-alpha',
] as const

function hexToRgb(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return null
  const n = parseInt(m[1], 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

// 将解析的外观（亮/暗）应用为 .dark 类，加上
// 活动主题的覆盖。主题是纯数据：我们只写合约
// 标记作为 <html> 上的内联 CSS 变量（并打开壁纸标志
// <body>)，因此无需更改任何代码即可重新调整组件的样式。
function applyAppearanceAndTheme(resolved: ResolvedTheme, themeId: string) {
  const root = document.documentElement
  root.classList.toggle('dark', resolved === 'dark')

  const theme = getTheme(themeId)
  if (theme.id === DEFAULT_THEME_ID) root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', theme.id)

  activeSurface = {
    light: theme.light?.colors?.bgSurface,
    dark: theme.dark?.colors?.bgSurface,
  }

  // 重置主题可以触及的所有内容，然后重新应用活动主题。
  for (const key of COLOR_KEYS) root.style.removeProperty(tokenToCssVar(key))
  for (const key of SHAPE_KEYS) root.style.removeProperty(tokenToCssVar(key))
  for (const v of WALLPAPER_VARS) root.style.removeProperty(v)

  // 形状标记与外观无关。
  if (theme.shape) {
    for (const [k, v] of Object.entries(theme.shape)) {
      if (v) root.style.setProperty(tokenToCssVar(k), v)
    }
  }

  const appearance = resolved === 'dark' ? theme.dark : theme.light
  if (appearance?.colors) {
    for (const [k, v] of Object.entries(appearance.colors)) {
      if (v) root.style.setProperty(tokenToCssVar(k), v)
    }
  }

  applyWallpaper(resolved, appearance?.wallpaper)
}

// 渲染（或清除）环境壁纸+磨砂玻璃面板。
function applyWallpaper(resolved: ResolvedTheme, wp?: Wallpaper) {
  const root = document.documentElement
  const body = document.body
  if (!wp?.image) {
    body.removeAttribute('data-wallpaper')
    return
  }
  body.setAttribute('data-wallpaper', 'on')
  root.style.setProperty('--wallpaper-image', `url("${wp.image}")`)

  const fx = clamp01(wp.focusX ?? 0.5) * 100
  const fy = clamp01(wp.focusY ?? 0.5) * 100
  root.style.setProperty('--wallpaper-position', `${fx}% ${fy}%`)

  // 默认稀松布：深色模式下较深，浅色模式下较浅。
  const opacity = clamp01(wp.overlayOpacity ?? (resolved === 'dark' ? 0.4 : 0.5))
  const scrim = resolved === 'dark' ? '0, 0, 0' : '255, 255, 255'
  root.style.setProperty('--wallpaper-overlay', `rgba(${scrim}, ${opacity})`)

  if (wp.glass) {
    // 磨砂玻璃：表面变得半透明（所以壁纸显示
    // 通过）+模糊。我们从主题本身的表面得出色调
    // 颜色，使其保留在调色板上，然后通过 --surface-alpha 驱动 alpha。
    const themeSurface =
      (resolved === 'dark' ? getThemeSurface('dark') : getThemeSurface('light')) ??
      (resolved === 'dark' ? '#141416' : '#ffffff')
    const rgb = hexToRgb(themeSurface) ?? (resolved === 'dark' ? [20, 20, 22] : [255, 255, 255])
    const alpha = resolved === 'dark' ? 0.55 : 0.62
    root.style.setProperty('--glass-fill', `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`)
    root.style.setProperty('--glass-blur', '20px')
    // 还使通用表面令牌半透明，以便现有的卡片
    // (bg-surface) 读取为玻璃而不接触组件代码。
    root.style.setProperty('--surface-alpha', String(alpha))
  }
}

// 缓存玻璃着色的活动主题的表面颜色。
let activeSurface: { light?: string; dark?: string } = {}
function getThemeSurface(mode: 'light' | 'dark'): string | undefined {
  return activeSurface[mode]
}

function clamp01(n: number): number {
  return Math.min(1, Math.max(0, n))
}

// 在 React 渲染之前应用一次持久化外观 + 主题，因此
// 第一个油漆已经有了正确的颜色（默认主题没有闪光）。
export function initThemeEarly() {
  const pref = readStoredPref()
  const resolved: ResolvedTheme = pref === 'system' ? getSystemTheme() : pref
  applyAppearanceAndTheme(resolved, readStoredThemeId())
}

export function useTheme() {
  const [pref, setPref] = useState<ThemePref>(readStoredPref)
  const [themeId, setThemeIdState] = useState<string>(readStoredThemeId)
  const [themes, setThemes] = useState<Theme[]>(getAllThemes)
  const [resolved, setResolved] = useState<ResolvedTheme>(() =>
    readStoredPref() === 'system' ? getSystemTheme() : (readStoredPref() as ResolvedTheme)
  )
  // 显示名称；捆绑的应用程序配置可能会覆盖默认值。
  const [appName, setAppName] = useState<string>('CowAgent')
  // 任何效果之前的快照都会保留一个值，这样我们就可以辨别出真实的效果
  // 第一次从明确选择主题的用户运行（没有事先选择）。
  const [firstRun] = useState(() => !hasStoredThemeId())

  // 安装后加载主题（捆绑+用户）和可选的应用程序配置。
  // 在真正的第一次运行时，应用配置的默认主题（如果已设置）；
  // 否则，只需重新应用当前选择即可加载其定义。
  useEffect(() => {
    let cancelled = false
    Promise.all([
      window.electronAPI?.listThemes?.() ?? Promise.resolve([]),
      window.electronAPI?.getAppConfig?.() ?? Promise.resolve(null),
    ])
      .then(([remote, config]) => {
        if (cancelled) return
        registerRuntimeThemes(remote)
        setThemes(getAllThemes())
        if (config?.appName) setAppName(config.appName)

        // 应用程序配置中的首次运行默认值（如果主题存在）。
        if (firstRun && config?.defaultTheme && getTheme(config.defaultTheme).id === config.defaultTheme) {
          setThemeIdState(config.defaultTheme) // 触发下面的应用效果
          return
        }
        // 现在已加载其定义，请重新应用当前选择。
        const next: ResolvedTheme = readStoredPref() === 'system' ? getSystemTheme() : (readStoredPref() as ResolvedTheme)
        applyAppearanceAndTheme(next, readStoredThemeId())
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [firstRun])

  // 每当外观偏好或主题发生变化时重新应用。
  useEffect(() => {
    const next: ResolvedTheme = pref === 'system' ? getSystemTheme() : pref
    setResolved(next)
    applyAppearanceAndTheme(next, themeId)
    localStorage.setItem(PREF_KEY, pref)
    localStorage.setItem(THEME_ID_KEY, themeId)
  }, [pref, themeId])

  // 仅当首选项为“系统”时才遵循系统更改。
  useEffect(() => {
    if (pref !== 'system') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => {
      const next = getSystemTheme()
      setResolved(next)
      applyAppearanceAndTheme(next, themeId)
    }
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [pref, themeId])

  const toggleTheme = useCallback(() => {
    setPref(resolved === 'dark' ? 'light' : 'dark')
  }, [resolved])

  const setTheme = useCallback((next: ThemePref) => setPref(next), [])
  const setThemeId = useCallback((next: string) => setThemeIdState(next), [])

  return { theme: resolved, pref, themeId, themes, appName, toggleTheme, setTheme, setThemeId }
}
