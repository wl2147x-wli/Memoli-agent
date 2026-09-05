/**
 * Dynamic electron-builder config for WINDOWS code signing.
 *
 * Mirrors electron-builder.js (which handles mac.binaries) but for Windows.
 * It wires a signing CLI into electron-builder so that every .exe is signed,
 * with the private key kept in hardware per the post-2023 code-signing rules.
 *
 * A SINGLE sign hook (win.signtoolOptions.sign) covers everything: electron-
 * builder calls it for EVERY .exe it processes, which includes the app
 * launcher, the packaged PyInstaller backend (extraResources/backend/
 * cowagent-backend.exe) and the NSIS installer. We deliberately do NOT add an
 * afterPack pass — that would sign the backend a second time and waste a paid
 * signing call on every release.
 *
 * PRIVACY: the CLI path and all credentials come from env vars only. Nothing in
 * this file (or the public workflow) is hardcoded, so a public repo never leaks
 * any signing configuration.
 *
 * DRY-RUN / SKIP: when SIGNTOOL_CERT_CODE is absent we skip signing entirely
 * (unsigned dev/dry builds keep working). When COW_SIGN_DRY_RUN=1 we pass
 * --dry-run so the WHOLE pipeline can be validated in CI with a self-signed
 * cert, WITHOUT a real certificate and WITHOUT consuming any signing quota.
 */
const { execFileSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const config = require('./package.json').build

// 运行器上签名 CLI 的绝对路径。由CI注入所以这个文件
// 从不硬编码下载 URL。例如C:\signtool\signtool.exe
const SIGNTOOL = process.env.SIGNTOOL_PATH || ''
// 空运行使用自签名证书验证管道（没有配额，没有真正的
// 需要证书）。任何真实的值都可以实现它。
const DRY_RUN = !!process.env.COW_SIGN_DRY_RUN

// 在空运行中，CLI 仍然要求这些标志为非空（它验证
// 存在，而不是值，并使用自签名证书进行签名）。所以当没有真正的
// 凭证是在试运行期间提供的，回退到无害的占位符
// 以满足 CLI 的 arg 检查。真实的运行会传递实际的秘密。
const PLACEHOLDER = DRY_RUN ? 'dry-run' : ''
const ACCESS_KEY = process.env.SIGNTOOL_ACCESS_KEY || PLACEHOLDER
const ACCESS_SECRET = process.env.SIGNTOOL_ACCESS_SECRET || PLACEHOLDER
const CERT_CODE = process.env.SIGNTOOL_CERT_CODE || PLACEHOLDER

// SHA256 的 RFC3161 时间戳服务器。 Microsoft 的 CI 运行者非常可靠
// 全球；如果需要的话可以通过 env 覆盖。
const TIMESTAMP = process.env.SIGNTOOL_TIMESTAMP || 'http://timestamp.acs.microsoft.com'

// 当我们有 CLI 加上真实的证书代码或
// 显式试运行模式（试运行接受占位符凭据）。
function canSign() {
  if (!SIGNTOOL || !fs.existsSync(SIGNTOOL)) return false
  if (DRY_RUN) return true
  return !!(ACCESS_KEY && ACCESS_SECRET && CERT_CODE)
}

/**
 * Sign a single file in place using the signing CLI. The CLI writes to a
 * separate --out path (it refuses to overwrite an existing file), so we sign to
 * a temp file and atomically move it back over the original.
 */
function signFile(filePath) {
  const tmpOut = `${filePath}.signed`
  // 从先前失败的运行中删除陈旧的临时文件（如果 --out 存在，则出现 CLI 错误）。
  try {
    if (fs.existsSync(tmpOut)) fs.rmSync(tmpOut)
  } catch {
    /* 忽略 */
  }

  const args = [
    'sign',
    ...(DRY_RUN ? ['--dry-run'] : []),
    `--access-key=${ACCESS_KEY}`,
    `--access-secret=${ACCESS_SECRET}`,
    `--cert-code=${CERT_CODE}`,
    `--file=${filePath}`,
    `--out=${tmpOut}`,
    '--sha1=false',
    '--sha2=true',
    '--timestamp-rfc3161',
    TIMESTAMP,
  ]

  // 从不打印凭据：仅记录正在签名的文件。
  console.log(`[win-sign] signing ${path.basename(filePath)}${DRY_RUN ? ' (dry-run)' : ''}`)
  execFileSync(SIGNTOOL, args, { stdio: ['ignore', 'inherit', 'inherit'] })

  if (!fs.existsSync(tmpOut)) {
    throw new Error(`[win-sign] signed output not produced for ${filePath}`)
  }
  // 用签名的副本替换原件。
  fs.rmSync(filePath)
  fs.renameSync(tmpOut, filePath)
}

// Electron-builder 为它生成的每个工件（应用程序 exe、NSIS
// 安装程序、卸载程序）。签名：（配置）=> void，其中
// configuration.path 是要签名的文件。
async function customSign(configuration) {
  if (!canSign()) {
    console.warn('[win-sign] signing skipped (no signtool/credentials)')
    return
  }
  signFile(configuration.path)
}

// 扩展基本配置：附加标志钩。仅在 Windows 上有意义
// 构建（此配置仅通过获胜矩阵腿上的 --config 传递）。
//
// Electron-builder 为它接触到的每个 .exe 调用 customSign——这已经
// 包括打包的后端（extraResources/backend/cowagent-backend.exe）
// 和 NSIS 安装程序，而不仅仅是应用程序启动器。所以没有单独的
// afterPack pass：添加一个将会对后端签名两次（浪费付费的
// 每个版本的签名呼叫）。保留嵌套的 PyInstaller .dll/.pyd 文件
// 未签名，Windows Authenticode 可以容忍（与 macOS 不同，它不
// 需要对每个嵌套库进行深度签名 - 一个签名的顶级 exe 就足够了
// SmartScreen/Defender 归因于发布者）。
config.win = { ...config.win, signtoolOptions: { sign: customSign, signingHashAlgorithms: ['sha256'] } }

// 捆绑 ripgrep — 仅限 Windows。 “捆绑 ripgrep 二进制文件”CI 步骤下载
// rg.exe 到资源/bin；将其发送到 <resources>/bin 下，以便 python-manager 可以
// 将其放在后端的 PATH 上 (shutil.which("rg") -> fast rg backend
// 缓慢的 PowerShell 回退）。在这里声明，而不是在 package.json 中，所以
// macOS 构建（从不创建资源/bin）从不引用它。
config.extraResources = [
  ...(config.extraResources || []),
  { from: 'resources/bin', to: 'bin', filter: ['rg.exe'] },
]

module.exports = config
