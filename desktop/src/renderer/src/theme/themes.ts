// ============================================================
// 主题契约——主题的单一事实来源。
//
// “主题”是纯粹的数据：它覆盖语义设计标记
// （颜色、半径、阴影、字体）和可选背景
// 壁纸。它从不触及组件代码或 DOM 结构，
// 因此主题在 UI 重构中保持稳定——只要
// 组件继续消耗这些令牌，旧主题继续工作。
//
// 合同规则：主题只能设置此处定义的字段。添加一个
// 新令牌是附加的、版本化的更改（凹凸THEME_SPEC_VERSION）。
//
// 主题未捆绑到应用程序中。他们住在 ~/.cow/themes/<id>/
// （theme.json + 图像）并在运行时通过主进程加载，
// 它将图像内嵌为数据 URL。唯一的内置主题是“默认”
// （始终离线工作的纯色后备）。
// ============================================================

// ---- 颜色标记（每次出现）-------------------------
export const COLOR_KEYS = [
  'accent',
  'accentHover',
  'accentActive',
  'accentSoft',
  'accentContrast',
  'bubbleUserBg',
  'bubbleUserText',
  'bgBase',
  'bgSurface',
  'bgSurface2',
  'bgElevated',
  'bgInset',
  'textPrimary',
  'textSecondary',
  'textTertiary',
  'textDisabled',
  'borderDefault',
  'borderStrong',
  'borderSubtle',
  'shadowSm',
  'shadowMd',
  'shadowLg',
] as const
export type ColorKey = (typeof COLOR_KEYS)[number]

// ---- 形状标记（与外观无关）-----------------
// 无论浅色还是深色，半径/字体都适用。
export const SHAPE_KEYS = ['radiusCard', 'radiusBtn', 'radiusSm', 'fontSans', 'fontMono'] as const
export type ShapeKey = (typeof SHAPE_KEYS)[number]

// 驼峰命名法标记 -> --kebab-case CSS 变量
export function tokenToCssVar(key: string): string {
  return '--' + key.replace(/[A-Z0-9]/g, (m) => '-' + m.toLowerCase())
}

// ---- 壁纸（Codex 风格环境背景）------------
export interface Wallpaper {
  // 图像 URL（捆绑的资源路径或数据/文件 URL）。空=纯色。
  image?: string
  focusX?: number // 0..1水平焦点，默认0.5
  focusY?: number // 0..1垂直焦点，默认0.5
  overlayOpacity?: number // 图像上的 0..1 稀松布强度，每次外观的默认值
  // 面板变得半透明+模糊（磨砂玻璃），所以壁纸
  // 显示通过。当为 false 时，面板保持坚固（壁纸仅位于底座后面）。
  glass?: boolean
}

export interface ThemeAppearance {
  colors?: Partial<Record<ColorKey, string>>
  wallpaper?: Wallpaper
}

// 可选的每个主题身份覆盖（徽标+显示名称）。
export interface ThemeIdentity {
  logo?: string // 数据 URL（由 main 内联）或资产 URL
  appName?: string
}

export interface Theme {
  id: string
  name: string
  specVersion?: number
  // 可选预览样本；当不存在时，它源自颜色。
  preview?: { accent: string; bg: string; surface: string }
  identity?: ThemeIdentity
  // 与外观无关的形状标记。
  shape?: Partial<Record<ShapeKey, string>>
  // 每个外观颜色+壁纸。
  light?: ThemeAppearance
  dark?: ThemeAppearance
}

// 当合同发生破坏性变化时，就会发生碰撞。 theme.json 文件声明
// 他们针对哪个版本以便可以验证导入。
export const THEME_SPEC_VERSION = 1

// 'default' 使用 index.css 中内置的 :root / .dark 值
// 不应用数据主题属性也不覆盖。
export const DEFAULT_THEME_ID = 'default'

// 唯一的内置主题：“默认”映射到基本 :root / .dark 值
// index.css（无覆盖）。其他所有内容都是在运行时加载的
// 〜/.cow/主题。这使得应用程序包不含主题资源。
export const DEFAULT_THEME: Theme = {
  id: DEFAULT_THEME_ID,
  name: 'Meadow',
  preview: { accent: '#4abe6e', bg: '#f9fafb', surface: '#ffffff' },
}

// 运行时注册表：首先是默认值，然后是从 ~/.cow 加载的内容。
let runtimeThemes: Theme[] = [DEFAULT_THEME]

// 基本形状验证，因此格式错误的 theme.json 不会破坏应用程序。
function isValidTheme(x: unknown): x is Theme {
  if (!x || typeof x !== 'object') return false
  const s = x as Record<string, unknown>
  return typeof s.id === 'string' && s.id.length > 0
}

// 当主题未发布时，从其颜色中获取预览样本。
function derivePreview(theme: Theme): { accent: string; bg: string; surface: string } {
  if (theme.preview) return theme.preview
  const c = theme.dark?.colors ?? theme.light?.colors ?? {}
  return {
    accent: c.accent ?? '#4abe6e',
    bg: c.bgBase ?? '#111111',
    surface: c.bgSurface ?? '#1c1c1f',
  }
}

// 将运行时主题列表替换为默认+经过验证的远程主题。
export function registerRuntimeThemes(themes: unknown[]): void {
  const valid = (themes ?? []).filter(isValidTheme).filter((t) => t.id !== DEFAULT_THEME_ID)
  for (const t of valid) t.preview = derivePreview(t)
  runtimeThemes = [DEFAULT_THEME, ...valid]
}

export function getAllThemes(): Theme[] {
  return runtimeThemes
}

export function getTheme(id: string): Theme {
  return runtimeThemes.find((t) => t.id === id) ?? runtimeThemes[0]
}
