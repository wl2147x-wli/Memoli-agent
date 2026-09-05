#!/usr/bin/env node
// 在包装之前将风味暂存或清除到资源中。
//
// 风味存在于flavors/<name>/中，并且可能包含：
//   app-config.json → 复制到 resources/app-config.json
//   theme/<id>/... → 复制到 resources/themes/<id>/...
//
// 用途：
//   node scripts/apply-flavor.mjs <name> # 将flavor/<name>放入resources/
//   node scripts/apply-flavor.mjs --clear # 删除暂存的 app-config.json + 主题/
//
// 标准构建既不提供 app-config.json 也不提供资源/主题，因此它
// 保持默认主题并自由切换。调味后始终--clear
// 构建以使存储库的资源/保持干净。

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '..')
const resourcesDir = path.join(root, 'resources')
const configFile = path.join(resourcesDir, 'app-config.json')
const resThemesDir = path.join(resourcesDir, 'themes')

function rimraf(target) {
  fs.rmSync(target, { recursive: true, force: true })
}

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true })
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name)
    const d = path.join(dest, entry.name)
    if (entry.isDirectory()) copyDir(s, d)
    else fs.copyFileSync(s, d)
  }
}

function clear() {
  rimraf(configFile)
  rimraf(resThemesDir)
  console.log('[flavor] cleared resources/app-config.json and resources/themes')
}

function apply(name) {
  const flavorDir = path.join(root, 'flavors', name)
  if (!fs.existsSync(flavorDir)) {
    console.error(`[flavor] no such flavor: flavors/${name}`)
    process.exit(1)
  }
  clear()
  const srcConfig = path.join(flavorDir, 'app-config.json')
  if (fs.existsSync(srcConfig)) {
    fs.mkdirSync(resourcesDir, { recursive: true })
    fs.copyFileSync(srcConfig, configFile)
    console.log(`[flavor] staged app-config.json from flavors/${name}`)
  }
  const srcThemes = path.join(flavorDir, 'themes')
  if (fs.existsSync(srcThemes)) {
    copyDir(srcThemes, resThemesDir)
    console.log(`[flavor] staged themes from flavors/${name}`)
  }
}

const arg = process.argv[2]
if (!arg || arg === '--clear') clear()
else apply(arg)
