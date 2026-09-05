import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// “@product”解析为内置默认值（空）。替代构建
// 可以将 COW_PRODUCT_DIR 设置为指向另一个模块。
const productDir =
  process.env.COW_PRODUCT_DIR || path.resolve(__dirname, 'src/renderer/src/product/default')

// 当“@product”指向该项目之外时，其文件无法解析共享
// 依赖于他们自己的树。共享运行时的别名取决于该项目的
// node_modules，因此树外产品模块导入相同的实例。
const nodeModules = path.resolve(__dirname, 'node_modules')
const sharedDepAliases = process.env.COW_PRODUCT_DIR
  ? {
      react: path.join(nodeModules, 'react'),
      'react-dom': path.join(nodeModules, 'react-dom'),
      'react/jsx-runtime': path.join(nodeModules, 'react/jsx-runtime'),
      'react-router-dom': path.join(nodeModules, 'react-router-dom'),
      'lucide-react': path.join(nodeModules, 'lucide-react'),
    }
  : {}

export default defineConfig({
  plugins: [react()],
  root: path.resolve(__dirname, 'src/renderer'),
  base: './',
  publicDir: path.resolve(__dirname, '../channel/web/static'),
  build: {
    outDir: path.resolve(__dirname, 'dist/renderer'),
    emptyOutDir: true,
  },
  server: {
    // 与 src/main/index.ts 中的 VITE_DEV_PORTS 保持同步。 strictPort 使
    // 冲突大声失败，而不是漂流到下一个自由港，
    // 主要流程就不看了。
    port: 5173,
    strictPort: true,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src/renderer/src'),
      '@product': productDir,
      ...sharedDepAliases,
    },
  },
})
