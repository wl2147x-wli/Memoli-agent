import type { ProductExtension } from '../types'

// 默认：无扩展名。所有行为保持原样。替代构建可以
// 覆盖“@product”别名以指向其自己的模块（请参阅
// vite.config.ts) 导出填充的 ProductExtension。
export const product: ProductExtension = {}
