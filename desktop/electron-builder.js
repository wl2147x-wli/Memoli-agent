/**
 * Dynamic electron-builder config.
 *
 * We keep the base config in package.json's "build" field and extend it here
 * only to populate `mac.binaries` — the list of extra Mach-O files that must
 * be signed with hardened runtime + entitlements.
 *
 * Why this is needed:
 * The Python backend is a PyInstaller onedir bundle shipped via extraResources
 * into Contents/Resources/backend/. electron-builder only hands the top-level
 * `.app` to codesign, which does NOT deep-sign the ~180 nested .so/.dylib
 * files under Resources/. Left unsigned (or without hardened runtime), Apple
 * notarization rejects the whole app.
 *
 * `mac.binaries` is the officially supported way to sign extra binaries: they
 * are signed inside electron-builder's own signing pass, AFTER it has created
 * the temporary keychain and imported the Developer ID cert (from CSC_LINK).
 * A previous afterPack approach failed because afterPack runs BEFORE that
 * keychain exists, so `codesign` couldn't find the identity.
 *
 * Paths are resolved relative to the `.app` at signing time. We enumerate the
 * pre-build backend source dir (build/dist/cowagent-backend, produced by
 * PyInstaller before packaging) — its layout mirrors the in-app copy — and map
 * each Mach-O to its in-app relative path.
 *
 * Never pin `arch` on mac.target in package.json: an arch listed there wins over
 * the --arm64/--x64 CLI flag, so every runner would build every arch and pair a
 * foreign shell with the backend PyInstaller just built for the host. The arch
 * has to come from the CLI, one per CI job.
 */
const { execFileSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const config = require('./package.json').build

// PyInstaller 输出被复制到应用程序中
// Contents/Resources/backend/cowagent-backend（请参阅 extraResources）。
const backendSrc = path.join(__dirname, 'build', 'dist', 'cowagent-backend')
const inAppPrefix = path.join('Contents', 'Resources', 'backend', 'cowagent-backend')

function isMachO(file) {
  try {
    return execFileSync('file', ['-b', file], { encoding: 'utf8' }).includes('Mach-O')
  } catch {
    return false
  }
}

function collectBackendBinaries() {
  if (!fs.existsSync(backendSrc)) {
    console.warn(`[electron-builder.js] backend not found at ${backendSrc}; mac.binaries left empty`)
    return []
  }
  const rels = []
  const walk = (dir) => {
    for (const name of fs.readdirSync(dir)) {
      const full = path.join(dir, name)
      const st = fs.lstatSync(full)
      if (st.isSymbolicLink()) continue
      if (st.isDirectory()) {
        walk(full)
        continue
      }
      if (isMachO(full)) {
        // 映射源路径 -> 应用内相对路径（针对 .app 解析）。
        const rel = path.relative(backendSrc, full)
        rels.push(path.join(inAppPrefix, rel))
      }
    }
  }
  walk(backendSrc)
  return rels
}

if (process.platform === 'darwin') {
  const binaries = collectBackendBinaries()
  console.log(`[electron-builder.js] injecting ${binaries.length} backend binaries into mac.binaries`)
  // 在这里签署后端二进制文件，但不要在 CI 中进行公证：Apple 的公证人
  // 服务通常会将这个大型 PyInstaller 包保持在“进行中”状态
  // 时间，这是任何 CI 工作都无法承受的。公证解耦
  // 进入 CI 生成后运行的手动本地步骤 (build/notarize-dmg.sh)
  // 已签名的 dmg。该 dmg 已进行代码签名并在此处启用了强化运行时，
  // 所以只需要事后装订的公证票即可。
  config.mac = { ...config.mac, binaries, notarize: false }
}

module.exports = config
