// ============================================================
// 可选的延期合同。
//
// 核心从“@product”导入单个 `product` 对象。默认情况下
// 该别名解析为product/default（空对象→无变化）。
// 备用构建可以将别名指向另一个模块（请参阅
// vite.config.ts COW_PRODUCT_DIR) 并填写以下字段。每个
// 字段是可选的；缺席意味着“保持默认行为”。核心
// 当字段丢失时必须优雅地降级。
// ============================================================
import type React from 'react'

// 在主 UI 之前呈现的可选门。当存在时，核心显示
// <Gate/> 直到扩展报告会话不再需要它。
export interface ProductAuth {
  Gate: React.FC<{ onAuthenticated: () => void }>
  // 目前是否需要该门。实现可以使用他们的
  // 内部拥有自己的钩子/状态。
  useRequiresAuth: () => boolean
}

// 核心呈现的可选 UI 安装点（如果提供）。
export interface ProductSlots {
  // 渲染在导航栏的底部。
  NavRailFooter?: React.FC
  // 呈现在顶部标题栏条的右侧。
  HeaderRight?: React.FC
  // 在 nav-rail 品牌区域（左上角，仅限 Windows/Linux）中渲染
  // 默认徽标+应用程序名称。那么接收铁轨是否塌陷
  // 它可以呈现紧凑的标记。让构建显示自定义文字标记。
  NavRailBrand?: React.FC<{ collapsed: boolean }>
  // 呈现为助手消息头像代替默认应用程序图标。
  // 让构建在回复旁边显示自己的（或 OEM 的）方形徽标。
  AssistantAvatar?: React.FC
  // 在空的新聊天主屏幕上呈现为徽标，而不是
  // 默认应用程序徽标。让构建也可以在那里显示自己的方形徽标。
  HomeLogo?: React.FC
  // 在启动/连接状态屏幕上呈现为徽标，而不是
  // 默认应用程序徽标。让构建也可以在那里显示自己的方形徽标。
  StatusLogo?: React.FC
}

// 附加到核心 <Routes> 的额外路由。 Path是HashRouter路径。
export interface ProductRoute {
  path: string
  element: React.ReactNode
}

export interface ProductOnboarding {
  // 设置 false 以禁用内置设置向导。默认为启用。
  enabled?: boolean
}

export interface ProductModels {
  // 设置 false 以隐藏“添加自定义提供程序”条目。默认为允许。
  allowCustomProviders?: boolean
  // 设置 true 以隐藏独立的“模型”设置选项卡。默认显示。
  hideModelsTab?: boolean
  // 设置 true 以隐藏基本设置中的提供程序下拉列表（例如，当
  // 模型列表来自单一托管源）。默认显示。
  hideProviderSelect?: boolean
  // 可选替换基本设置中的模型选择控件。
  // 受控：接收当前模型 ID 并报告更改。设置后，
  // 核心渲染它而不是其内置模型下拉列表。
  ModelPicker?: React.FC<{ value: string; onChange: (model: string) => void }>
  // 设置 true 以显示当前提供商的屏蔽+可编辑 API 密钥字段
  // 在基本设置中，当独立模型选项卡隐藏时很有用。
  showManagedApiKey?: boolean
  // 聊天编辑器中每会话模型芯片的可选替换。
  // 设置后，核心将呈现此内容而不是其内置的提供者分组
  // 菜单，因此模型来自不同来源的构建可以呈现它们
  // 然而它喜欢。 `sessionId` 标识正在编辑的对话。
  SessionModelPicker?: React.FC<{ sessionId: string }>
}

// 可选的导航轨道定制。让构建定制页脚菜单
// 外部目的地而不触及核心代码。
export interface ProductNav {
  // 设置 true 以隐藏内置外部链接组（技能中心、文档、
  // 网站、反馈）。默认显示。
  hideExternalLinks?: boolean
  // 设置 true 以隐藏内置页脚“更多”条目（版本标签+菜单），
  // 例如当扩展提供自己的页脚菜单时。折叠切换
  // 留下来。默认显示。
  hideFooterMenu?: boolean
}

// 构建可以覆盖的可选外部链接（例如不同品牌的
// 文档站点）。每个都返回 null 以回退到核心默认值。
export interface ProductLinks {
  // 给定版本的“新增内容”页面。 `lang` 是 UI 语言
  // （例如“zh”）。返回 null 以使用核心文档站点。
  releaseNotesUrl?: (version: string, lang: string) => string | null
}

export interface ProductExtension {
  auth?: ProductAuth
  slots?: ProductSlots
  routes?: ProductRoute[]
  onboarding?: ProductOnboarding
  models?: ProductModels
  nav?: ProductNav
  links?: ProductLinks
}
