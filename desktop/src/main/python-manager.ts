import { app } from 'electron'
import { ChildProcess, spawn, execFileSync } from 'child_process'
import { EventEmitter } from 'events'
import path from 'path'
import os from 'os'
import fs from 'fs'
import http from 'http'
import net from 'net'

// 打包应用程序的可写数据目录（config.json、run.log、用户数据）。
// 存在于用户家中，因此它可以在应用程序更新后继续存在并避免写入
// 只读应用程序包。 Source/dev 运行继续使用 repo CWD。
const COW_DATA_DIR = path.join(os.homedir(), '.cow')

// 桌面后端的首选端口。故意不是9899（网络
// 控制台的默认值），因此源运行 `python app.py` 永远不会与
// 打包的应用程序。渲染器首先探测这个端口，但它只是一个
// 偏好，而不是保证——请参阅 pickPort() 了解原因，并注意真正的
// 端口始终通过“port”事件/whenPortReady 发布到渲染器。
export const DESKTOP_BACKEND_PORT = 9876

// 当首选端口无法绑定时按顺序尝试。 Windows 保留
// Hyper-V/WSL2/Docker 的伪随机端口范围（netsh“排除端口
// range"): 绑定失败并显示 WinError 10013，即使没有任何内容
// 监听，所以 freePort() 没有什么可杀死的，而且旧的固定端口设计
// 让这些用户永远停留在“初始化”状态。候选人是
// 分散得很远，因此单个保留块无法吞没所有它们。
const FALLBACK_PORTS = [19876, 29876, 39876, 49876, 55876]

// 渲染器在回退到端口决定之前可以等待多长时间
// 首选端口。选择端口仅涉及本地绑定探针，因此这
// 是针对挂起探针的安全网，而不是正常的代码路径。
const PORT_READY_TIMEOUT_MS = 15_000

// 活跃度监控，仅在后端准备好一次后才有效。
// 如果没有它，几个小时后死亡或楔入的后端就会被忽视：
// shell 一直报告“就绪”，窗口看起来很好，每个渲染器
// 请求失败，并显示“无法获取”。
const HEALTH_PROBE_INTERVAL_MS = 15_000
const HEALTH_PROBE_TIMEOUT_MS = 4_000
// 在我们称后端死亡之前，未命中必须持续这么长时间。从中醒来
// sleep 丢失第一个探测（并延长间隔），这一定不能
// 被误认为是车祸。
const HEALTH_GRACE_MS = 45_000
// 重新启动是有限的，因此后端在每次启动后立即死亡
// 变成带有重试按钮的报告错误，而不是无休止的重生循环。
const MAX_RECOVERIES = 3
const RECOVERY_WINDOW_MS = 10 * 60_000

/**
 * Why startup failed, as a stable identifier the renderer can map to specific,
 * actionable advice. The raw message alone is not enough: "app.py not found at
 * <install dir>" told a customer nothing, and the generic localized fallback
 * ("the client failed to start") told them even less.
 */
export type BackendErrorCode =
  // 该捆绑包已安装，但其可执行文件消失了。在 Windows 上这是
  // 本质上总是防病毒软件隔离 PyInstaller 引导加载程序。
  | 'backend_removed'
  // 在预期位置没有安装任何可用的东西。
  | 'backend_missing'
  // 可执行文件存在，但操作系统拒绝启动它。
  | 'backend_blocked'
  // 它启动了，然后在回答之前就退出了。
  | 'backend_crashed'
  // 它仍然活着，但从未回复/api/health。
  | 'backend_timeout'
  // 它服务了请求，然后停止并且无法重新启动。
  | 'backend_unresponsive'

export interface BackendError {
  code: BackendErrorCode
  /** Technical detail, shown verbatim; the renderer localizes from `code`. */
  message: string
  /** Path the failure is about (the missing executable, etc.), if any. */
  path?: string
}

export class PythonBackend extends EventEmitter {
  private process: ChildProcess | null = null
  private backendPath: string
  // 我们是否在已安装的应用程序中运行（而不是在源应用程序中运行）
  // 结帐）。由调用者决定，而不是从捆绑包中推断出来
  // 目前：推断这意味着静默隔离的可执行文件
  // 将已安装的应用程序降级为“开发模式”，它在其中寻找
  // app.py 位于只读安装目录中，并将其日志也写入其中。
  private packaged: boolean
  private port: number = DESKTOP_BACKEND_PORT
  private status: 'stopped' | 'starting' | 'ready' | 'error' = 'stopped'
  // 一旦 start() 确定了端口就解决。渲染器正在等待这个
  // 而不是假设 DESKTOP_BACKEND_PORT，因此后备端口永远不是
  // 猜猜它必须做出。
  private portReady: Promise<number>
  private markPortReady!: (port: number) => void
  // 后端输出的滚动尾部。一家从未达到“准备就绪”状态的初创公司是
  // 否则报告为纯粹的超时，以及实际原因（绑定错误、
  // 配置异常）仅在 run.log 中可见 - 用户无法打开
  // 从 UI 来看，因为 UI 正是未能出现的内容。
  private recentLogs: string[] = []
  // 准备就绪后的活性监督。请参阅startHealthMonitor()。
  private healthTimer: ReturnType<typeof setInterval> | null = null
  private consecutiveHealthMisses = 0
  private lastHealthyAt = 0
  // 确实，当我们故意破坏进程（退出或重新启动）时，
  // 因此退出处理程序和飞行中的探测器都不会将其视为崩溃。
  private shuttingDown = false
  // 在恢复重启正在进行时确实如此，以保持单次飞行。
  private recovering = false
  private recoveryAttempts = 0
  private recoveryWindowStart = 0
  // 将流附加到 run.log，以便后端自己的 stdout/stderr 被持久化
  // 外壳也是如此。一旦 Python 日志记录完成，后端就会自行写入 run.log
  // 启动 — 但引导程序崩溃（缺少 DLL、更新后损坏的 onedir、
  // 防病毒块）在此之前就死掉了，只向 stderr 透露真正的原因。
  // 我们已经捕获了该 stderr，但从未将其写入任何持久的地方，因此
  // “打开日志文件夹”按钮显示陈旧的 run.log，没有崩溃的痕迹。
  // 这里的镜像弥补了这一差距，而无需触及 Python 端。
  private logStream: fs.WriteStream | null = null
  // 导致我们陷入“错误”的故障将被保留，以便以后可以获取。这
  // 渲染器仅在 React 安装后订阅“backend-status”，即
  // 启动后数百毫秒 - 在此之前出现的每个错误
  // （并且几乎立即检测到丢失的可执行文件）用于发出
  // 进入空白，给用户留下一个简单的“初始化失败”。
  private lastError: BackendError | null = null

  constructor(backendPath: string, packaged = false) {
    super()
    this.backendPath = backendPath
    this.packaged = packaged
    this.portReady = new Promise<number>((resolve) => {
      this.markPortReady = resolve
    })
  }

  getPort(): number {
    return this.port
  }

  /** The failure that put the backend in 'error', or null if none. */
  getLastError(): BackendError | null {
    return this.lastError
  }

  /**
   * The port the backend will actually use, once known. Times out to the
   * current best guess so a stalled startup can never leave the renderer
   * waiting forever on a promise that never settles.
   */
  whenPortReady(): Promise<number> {
    return Promise.race([
      this.portReady,
      new Promise<number>((resolve) => setTimeout(() => resolve(this.port), PORT_READY_TIMEOUT_MS)),
    ])
  }

  /**
   * Writable data dir the backend runs against (holds config.json + run.log),
   * and the folder the failure screen's "open log folder" button reveals.
   *
   * Keyed on how the app was built, never on whether the bundle is currently
   * intact: when the executable went missing this used to return the read-only
   * install dir, so a user following the on-screen instructions opened a folder
   * that had no run.log in it at all.
   */
  getDataDir(): string {
    return this.packaged ? COW_DATA_DIR : this.backendPath
  }

  // 来自捆绑的应用程序配置的可选运行时来源标签，转发到
  // 后端，以便它可以附加到统计数据的出站请求。
  private clientSource(): string {
    try {
      const cfgPath = this.packaged
        ? path.join(process.resourcesPath, 'app-config.json')
        : path.resolve(__dirname, '../../resources', 'app-config.json')
      const raw = fs.readFileSync(cfgPath, 'utf8')
      const val = JSON.parse(raw)?.clientSource
      return typeof val === 'string' ? val.trim() : ''
    } catch {
      return ''
    }
  }

  getStatus(): string {
    return this.status
  }

  private recordLog(line: string) {
    this.recentLogs.push(line)
    if (this.recentLogs.length > 80) {
      this.recentLogs.shift()
    }
  }

  /**
   * Open an append stream to <dataDir>/run.log so we can persist the backend's
   * stdout/stderr from the shell side. This is the same file the backend writes
   * once its Python logging initializes, and the same file the "open log folder"
   * button reveals — so a bootstrap crash's stderr lands exactly where the user
   * (and we) already look. Best-effort: any failure just disables mirroring.
   */
  private openLogStream(dataDir: string): void {
    this.closeLogStream()
    try {
      fs.mkdirSync(dataDir, { recursive: true })
      const logPath = path.join(dataDir, 'run.log')
      // 追加（不是截断）：后端追加到同一个文件，所以我们必须
      // 不要破坏它的历史，并且交错也很好——两者都是基于行的。
      this.logStream = fs.createWriteStream(logPath, { flags: 'a' })
      // 日志记录错误绝不能导致应用程序崩溃；而是删除流。
      this.logStream.on('error', () => {
        this.logStream = null
      })
      const stamp = new Date().toISOString()
      this.logStream.write(`\n[SHELL][${stamp}] --- launching backend (stdout/stderr mirrored below) ---\n`)
    } catch {
      this.logStream = null
    }
  }

  /**
   * Write one line to run.log from the shell side, opening the file if the
   * failure happened before (or instead of) a spawn. Everything we report to
   * the user must also land here: the failure screen tells them to read
   * run.log, so a diagnosis that exists only in an IPC message is a diagnosis
   * they can never send us.
   */
  private writeLog(line: string): void {
    if (!this.logStream) {
      this.openLogStream(this.getDataDir())
    }
    try {
      this.logStream?.write(`[SHELL][${new Date().toISOString()}] ${line}\n`)
    } catch {
      // 忽略 - 日志记录绝不能中断启动
    }
  }

  /**
   * Record a startup/liveness failure: remember it, persist it, and announce
   * it. Single entry point so no failure can reach the user without also
   * reaching run.log and getLastError().
   */
  private fail(code: BackendErrorCode, message: string, failedPath?: string): void {
    this.status = 'error'
    this.lastError = { code, message, ...(failedPath ? { path: failedPath } : {}) }
    this.writeLog(`${code}: ${message}${failedPath ? ` [${failedPath}]` : ''}`)
    // “错误”对于 EventEmitter 来说是特殊的：在没有附加侦听器的情况下发出它
    // THROWS，这会将“后端未启动”变成“主要后端”
    // 进程死掉了，没有窗口出现”——比
    // 我们正在尝试报告的失败。故障已被存储并且
    // 持久化，渲染器通过 getLastError() 拉取它，因此跳过
    // 发射不会损失任何东西。
    if (this.listenerCount('error') > 0) {
      this.emit('error', this.lastError)
    }
  }

  private closeLogStream(): void {
    if (this.logStream) {
      try {
        this.logStream.end()
      } catch {
        // 忽略
      }
      this.logStream = null
    }
  }

  /**
   * Append the most recent backend error line to a message, so the UI can show
   * what actually went wrong instead of just "startup timed out".
   */
  private withLastError(message: string): string {
    for (let i = this.recentLogs.length - 1; i >= 0; i--) {
      const line = this.recentLogs[i]
      if (/\[ERROR\]|Error:|OSError|Traceback/.test(line)) {
        return `${message}: ${line.trim().slice(0, 300)}`
      }
    }
    return message
  }

  // 缓存已解析的 PATH，以便每个进程只生成一次登录 shell。
  private resolvedPath: string | null = null

  /**
   * Build the PATH the backend should run with.
   *
   * When launched from Finder/Dock, a GUI app inherits launchd's minimal PATH
   * (/usr/bin:/bin:...) and never loads ~/.zshrc, so user-installed CLIs like
   * `linkai`, `node`, or Homebrew tools are invisible to the agent's bash tool.
   * We recover the real login-shell PATH (macOS/Linux) and merge in common bin
   * dirs, so the agent can find these commands regardless of how the app started.
   */
  private resolveEnvPath(): string {
    if (this.resolvedPath !== null) {
      return this.resolvedPath
    }

    const sep = path.delimiter
    const existing = process.env.PATH || ''
    const parts: string[] = existing ? existing.split(sep) : []

    // 预先添加捆绑的 ripgrep 目录（如果已提供），以便 search_files 工具的
    // Shutil.which("rg") 找到我们的副本并使用快速 rg 后端而不是
    // 缓慢的 PowerShell 回退。目前只有 Windows 提供 rg（macOS 依赖于
    // 其系统 grep);的existsSync守卫在其他地方都保持此操作为空。
    // backendPath 是 <resources>/backend，因此 rg 位于上一级
    // <资源>/bin。以下重复数据删除后第一个条目获胜。
    const rgDir = path.join(path.dirname(this.backendPath), 'bin')
    const rgExe = process.platform === 'win32' ? 'rg.exe' : 'rg'
    if (fs.existsSync(path.join(rgDir, rgExe))) {
      parts.unshift(rgDir)
    }

    // Windows GUI 应用程序已经继承了完整的系统路径；没什么可修复的。
    if (process.platform !== 'win32') {
      // 向用户的登录 shell 询问其 PATH。 `-ilc` 运行交互式
      // 登录 shell，因此它来源 ~/.zshrc / ~/.zprofile 等。
      try {
        const shell = process.env.SHELL || '/bin/zsh'
        const out = execFileSync(shell, ['-ilc', 'echo -n "__PATH__$PATH"'], {
          encoding: 'utf8',
          timeout: 5000,
          stdio: ['ignore', 'pipe', 'ignore'],
        })
        const marker = out.lastIndexOf('__PATH__')
        if (marker !== -1) {
          const shellPath = out.slice(marker + '__PATH__'.length).trim()
          if (shellPath) {
            parts.push(...shellPath.split(sep))
          }
        }
      } catch {
        // Shell 探测失败（异常 shell、超时）。跌回到
        // 下面是常见的目录，因此至少典型的安装路径可以工作。
      }

      const home = os.homedir()
      parts.push(
        path.join(home, '.local/bin'),
        '/usr/local/bin',
        '/opt/homebrew/bin',
        '/usr/bin',
        '/bin',
        '/usr/sbin',
        '/sbin',
      )
    }

    // 去重复，同时保留顺序（第一次出现优先）。
    const seen = new Set<string>()
    const merged: string[] = []
    for (const p of parts) {
      const dir = p.trim()
      if (dir && !seen.has(dir)) {
        seen.add(dir)
        merged.push(dir)
      }
    }

    this.resolvedPath = merged.join(sep)
    return this.resolvedPath
  }

  /**
   * Inspect the packaged onedir backend on disk.
   *
   * `hasPayload` (the PyInstaller support files: _internal, DLLs, base_library)
   * is reported separately from `hasExe` on purpose. Antivirus quarantine
   * deletes ONLY the bootloader executable — it matches the heuristic, the
   * hundreds of DLLs beside it do not — so "payload intact, executable gone" is
   * a signature we can recognise and explain, rather than a generic failure.
   */
  private inspectBundle(): { exePath: string; hasExe: boolean; hasPayload: boolean } {
    const exeName = process.platform === 'win32' ? 'cowagent-backend.exe' : 'cowagent-backend'
    const dirs = [path.join(this.backendPath, 'cowagent-backend'), this.backendPath]
    for (const dir of dirs) {
      const exePath = path.join(dir, exeName)
      const hasExe = fs.existsSync(exePath)
      let hasPayload = false
      try {
        hasPayload = fs.readdirSync(dir).some((entry) => entry !== exeName)
      } catch {
        // 目录丢失/无法读取 — 将 hasPayload 保留为 false。
      }
      if (hasExe || hasPayload) {
        return { exePath, hasExe, hasPayload }
      }
    }
    return { exePath: path.join(dirs[0], exeName), hasExe: false, hasPayload: false }
  }

  /**
   * Path to the packaged backend executable, or null when it isn't there
   * (a source checkout, or an install whose executable was removed).
   */
  private findBundledBackend(): string | null {
    const bundle = this.inspectBundle()
    return bundle.hasExe ? bundle.exePath : null
  }

  private findPython(): string {
    const venvPaths = [
      path.join(this.backendPath, '.venv', 'bin', 'python'),
      path.join(this.backendPath, '.venv', 'Scripts', 'python.exe'),
      path.join(this.backendPath, 'venv', 'bin', 'python'),
      path.join(this.backendPath, 'venv', 'Scripts', 'python.exe'),
    ]

    for (const p of venvPaths) {
      if (fs.existsSync(p)) {
        return p
      }
    }

    return process.platform === 'win32' ? 'python' : 'python3'
  }

  /**
   * Read an explicit `web_port` from config.json, if the user pinned one. The
   * packaged build keeps config in COW_DATA_DIR (~/.cow); dev reads it from the
   * repo path. Returns null when unset, so the caller can auto-pick a free port
   * instead of fighting over a fixed one.
   */
  private readConfiguredPort(dataDir: string): number | null {
    try {
      const configPath = path.join(dataDir, 'config.json')
      if (fs.existsSync(configPath)) {
        const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'))
        const p = Number(config.web_port)
        if (Number.isInteger(p) && p > 0 && p < 65536) {
          return p
        }
      }
    } catch {
      // 忽略 — 进入自动选择
    }
    return null
  }

  /**
   * Pick a port the backend can actually bind, preferring the pinned/default
   * one. Each candidate is probed for real (bind + close); a busy one gets a
   * freePort() pass first, since the usual cause is a stale backend from a
   * previous run. Anything still unusable is skipped rather than fought over:
   * on Windows a port can be permanently unbindable (reserved by Hyper-V/WSL2)
   * with no process to kill, which used to strand the app on "initializing".
   *
   * The result is the single source of truth handed to both the backend
   * (COW_WEB_PORT) and the renderer (whenPortReady / the 'port' event).
   */
  private async pickPort(dataDir: string): Promise<number> {
    const pinned = this.readConfiguredPort(dataDir)
    const preferred = pinned !== null ? pinned : DESKTOP_BACKEND_PORT
    const candidates = [preferred, ...FALLBACK_PORTS.filter((p) => p !== preferred)]

    for (const port of candidates) {
      if (await this.isPortFree(port)) {
        return port
      }
      await this.freePort(port)
      if (await this.isPortFree(port)) {
        return port
      }
      this.emit('log', `Port ${port} is unusable — trying the next candidate`)
    }

    // 每个候选人都拒绝了。让操作系统命名一个空闲端口：它不太稳定
    // across 重新启动，但渲染器被告知是哪一个，因此它仍然有效。
    const ephemeral = await this.findEphemeralPort()
    if (ephemeral) {
      this.emit('log', `All candidate ports refused — using OS-assigned port ${ephemeral}`)
      return ephemeral
    }
    // 根本就没有什么可绑定的。无论如何返回首选端口，以便后端
    // 运行并记录一个真正的绑定错误，而不是我们在这里默默地失败。
    return preferred
  }

  /** Ask the OS for any free loopback port. Null if even that fails. */
  private findEphemeralPort(): Promise<number | null> {
    return new Promise((resolve) => {
      const tester = net
        .createServer()
        .once('error', () => resolve(null))
        .once('listening', () => {
          const addr = tester.address()
          const port = addr && typeof addr === 'object' ? addr.port : null
          tester.close(() => resolve(port))
        })
        .listen(0, '127.0.0.1')
    })
  }

  /** True if we can bind 127.0.0.1:port right now (i.e. it's free). */
  private isPortFree(port: number): Promise<boolean> {
    return new Promise((resolve) => {
      const tester = net
        .createServer()
        .once('error', () => resolve(false))
        .once('listening', () => {
          tester.close(() => resolve(true))
        })
        .listen(port, '127.0.0.1')
    })
  }

  /**
   * Make sure our fixed port is usable before launch by killing whatever is
   * holding it (almost always a stale backend from a previous run that didn't
   * shut down cleanly). We only ever target a process actually listening on
   * 127.0.0.1:<port>, so we won't touch unrelated apps. Best-effort: if we
   * can't free it we still try to bind and let the backend surface EADDRINUSE.
   */
  private async freePort(port: number): Promise<void> {
    if (await this.isPortFree(port)) {
      return
    }
    this.emit('log', `Port ${port} is busy — clearing stale process before launch`)
    const pids = await this.findListenerPids(port)
    for (const pid of pids) {
      // 永远不要向自己发出信号（理论上，Electron 可以成为监听者）。
      if (pid === process.pid) continue
      try {
        process.kill(pid, 'SIGTERM')
      } catch {
        // 已经走了/没有许可——忽略
      }
    }
    // 给操作系统一点时间来释放套接字，然后强制杀死剩余的。
    await new Promise((r) => setTimeout(r, 600))
    if (!(await this.isPortFree(port))) {
      for (const pid of await this.findListenerPids(port)) {
        if (pid === process.pid) continue
        try {
          process.kill(pid, 'SIGKILL')
        } catch {
          // 忽略
        }
      }
      await new Promise((r) => setTimeout(r, 400))
    }
  }

  /** PIDs listening on 127.0.0.1:<port>, via lsof (POSIX) / netstat (Windows). */
  private findListenerPids(port: number): Promise<number[]> {
    return new Promise((resolve) => {
      const isWin = process.platform === 'win32'
      const cmd = isWin ? 'netstat' : 'lsof'
      const args = isWin
        ? ['-ano', '-p', 'tcp']
        : ['-nP', `-iTCP:${port}`, '-sTCP:LISTEN', '-t']
      let out = ''
      try {
        const child = spawn(cmd, args)
        child.stdout?.on('data', (d: Buffer) => (out += d.toString()))
        child.on('error', () => resolve([]))
        child.on('close', () => {
          const pids = new Set<number>()
          if (isWin) {
            // 匹配如下行： TCP 127.0.0.1:9876 ... LISTENING 12345
            for (const line of out.split('\n')) {
              if (!/LISTENING/i.test(line)) continue
              if (!new RegExp(`[:.]${port}\\b`).test(line)) continue
              const pid = Number(line.trim().split(/\s+/).pop())
              if (Number.isInteger(pid) && pid > 0) pids.add(pid)
            }
          } else {
            for (const tok of out.split(/\s+/)) {
              const pid = Number(tok)
              if (Number.isInteger(pid) && pid > 0) pids.add(pid)
            }
          }
          resolve([...pids])
        })
      } catch {
        resolve([])
      }
    })
  }

  /** One-shot /api/health probe. Never throws; false means "unreachable". */
  private probeHealth(): Promise<boolean> {
    return new Promise((resolve) => {
      let settled = false
      const done = (ok: boolean) => {
        if (settled) return
        settled = true
        resolve(ok)
      }
      const req = http.get(`http://127.0.0.1:${this.port}/api/health`, (res) => {
        // 耗尽主体：未读的响应使其套接字保持检查状态
        // 保持活动池，因此重复探测会泄漏套接字。
        res.resume()
        done(res.statusCode === 200)
      })
      req.on('error', () => done(false))
      req.setTimeout(HEALTH_PROBE_TIMEOUT_MS, () => {
        req.destroy()
        done(false)
      })
    })
  }

  /**
   * Start watching a backend that has reached 'ready'. The renderer trusts
   * 'ready' for the rest of the session, so this is the only thing that can
   * notice a backend which dies or stops answering later on.
   */
  private startHealthMonitor(): void {
    this.stopHealthMonitor()
    this.lastHealthyAt = Date.now()
    this.consecutiveHealthMisses = 0
    this.healthTimer = setInterval(() => {
      void this.checkHealth()
    }, HEALTH_PROBE_INTERVAL_MS)
  }

  private stopHealthMonitor(): void {
    if (this.healthTimer) {
      clearInterval(this.healthTimer)
      this.healthTimer = null
    }
  }

  private async checkHealth(): Promise<void> {
    if (this.shuttingDown || this.recovering) {
      return
    }
    if (await this.probeHealth()) {
      this.consecutiveHealthMisses = 0
      this.lastHealthyAt = Date.now()
      return
    }
    this.consecutiveHealthMisses++
    // 需要重复错过和实际经过的时间：睡眠/唤醒节流
    // 间隔，因此单个丢失的探针无法说明后端的情况。
    if (this.consecutiveHealthMisses < 2 || Date.now() - this.lastHealthyAt < HEALTH_GRACE_MS) {
      return
    }
    await this.recover()
  }

  /**
   * Rebuild a backend that stopped answering. Announces 'lost' first so the
   * renderer drops its cached "ready" and shows the reconnect screen instead of
   * failing every request behind an intact-looking UI.
   */
  private async recover(): Promise<void> {
    if (this.recovering) {
      return
    }
    this.recovering = true
    this.stopHealthMonitor()
    try {
      // 在预算检查之前宣布：后端无论如何都消失了，并且
      // 即使我们放弃尝试，渲染器也必须保持“就绪”状态 -
      // 否则它会忽略我们要报告的错误。
      this.emit('lost')
      const now = Date.now()
      if (now - this.recoveryWindowStart > RECOVERY_WINDOW_MS) {
        this.recoveryWindowStart = now
        this.recoveryAttempts = 0
      }
      this.recoveryAttempts++
      if (this.recoveryAttempts > MAX_RECOVERIES) {
        this.fail(
          'backend_unresponsive',
          this.withLastError('The app stopped responding and could not be restarted'),
        )
        return
      }
      this.emit(
        'log',
        `Backend stopped responding — restarting (attempt ${this.recoveryAttempts}/${MAX_RECOVERIES})`,
      )
      await this.restart()
    } finally {
      this.recovering = false
    }
  }

  async start(): Promise<void> {
    if (this.status === 'ready' || this.status === 'starting') {
      return
    }

    this.shuttingDown = false
    this.status = 'starting'
    // 删除先前运行的输出，以便重试无法报告过时的错误。
    this.recentLogs = []
    this.lastError = null

    // 打包的应用程序将可写数据存储在 ~/.cow 中；开发人员将其保留在仓库中。
    const dataDir = this.getDataDir()

    // 在我们生成之前开始将后端输出镜像到 run.log，所以即使是
    // 即时引导程序崩溃（在 Python 日志记录启动之前）留下了 stderr
    // 用户可以从故障屏幕打开该文件。
    this.openLogStream(dataDir)

    // 更喜欢打包的独立后端（生产）；回落到
    // 使用 Python 解释器运行 app.py（本地开发）。
    const bundle = this.inspectBundle()
    const bundled = bundle.hasExe ? bundle.exePath : null

    // 已安装的应用程序没有其他方式运行：没有源代码树，也没有
    // 回退到Python。现在就这么说，命名丢失的文件，然后
    // 解决端口承诺，这样下游就不会等待启动
    // 永远不会发生。此前，这落到了开发阶段
    // 分支并报告“app.py not found at <install dir>”——一条消息
    // 描述了我们自己的后备方案，而不是用户的实际问题。
    if (!bundled && this.packaged) {
      this.markPortReady(this.port)
      if (bundle.hasPayload) {
        this.fail(
          'backend_removed',
          'The backend executable is missing while the rest of its files are intact, which is what antivirus quarantine looks like',
          bundle.exePath,
        )
      } else {
        this.fail('backend_missing', 'The backend is not present in this installation', bundle.exePath)
      }
      return
    }

    // 始终启动我们自己的后端（重新进入由上面的状态保护
    // 检查一下，这样我们就不会在这个实例中双重生成）。我们不重复使用
    // 无论端口上发生什么：这就是应用程序之前附加的方式
    // 到源运行的 Web 控制台并读取错误的配置。 pickPort() 释放
    // 陈旧的侦听器并跳过操作系统拒绝的端口，然后发布结果
    // 所以渲染器永远不必猜测我们选择了哪个端口。
    this.port = await this.pickPort(dataDir)
    this.markPortReady(this.port)
    this.emit('port', this.port)

    let command: string
    let args: string[]
    let cwd: string

    if (bundled) {
      command = bundled
      args = []
      // 从可写数据目录（~/.cow）运行，而不是从安装目录运行。当
      // 应用程序安装在Program Files下，非管理员用户无权写入
      // 对可执行文件文件夹的权限，因此任何相对路径写入
      // 在启动期间会使后端崩溃（仅以管理员身份工作）。的
      // Bundle 通过 sys._MEIPASS 读取其只读资源，因此 cwd 是免费的
      // 指向别处。
      try {
        fs.mkdirSync(COW_DATA_DIR, { recursive: true })
      } catch {
        // 忽略 — get_data_root() 还确保 Python 端的目录
      }
      cwd = COW_DATA_DIR
      this.emit('log', `Starting bundled backend: ${bundled} (cwd=${cwd})`)
    } else {
      const pythonPath = this.findPython()
      const appPath = path.join(this.backendPath, 'app.py')
      if (!fs.existsSync(appPath)) {
        this.fail('backend_missing', 'app.py not found — this is a source checkout with no backend', appPath)
        return
      }
      command = pythonPath
      args = [appPath]
      cwd = this.backendPath
      this.emit('log', `Starting Python backend: ${pythonPath} ${appPath}`)
    }

    this.process = spawn(command, args, {
      cwd,
      // COW_DESKTOP 支持更轻量的桌面运行时（无插件，无 MCP）。
      // COW_DATA_DIR（仅打包）将可写数据重定向到 ~/.cow，因此
      // 应用程序包保持只读状态； dev 运行忽略它并继续使用存储库。
      env: {
        ...process.env,
        // 恢复用户的真实路径（登录 shell + 公共 bin 目录），以便
        // 代理的 bash 工具可以找到像 `linkai`/`node` 这样的 CLI，即使
        // 应用程序是从 Finder/Dock 启动的，具有 launchd 的最小路径。
        PATH: this.resolveEnvPath(),
        PYTHONUNBUFFERED: '1',
        COW_DESKTOP: '1',
        // shell 拥有该端口：告诉后端在此处准确绑定，以便
        // 双方永远不会有分歧（我们避免了 9899 网络控制台冲突）。
        COW_WEB_PORT: String(this.port),
        ...(bundled ? { COW_DATA_DIR } : {}),
        ...(this.clientSource() ? { COW_CLIENT_SOURCE: this.clientSource() } : {}),
        COW_CLIENT_VERSION: app.getVersion(),
      },
      stdio: ['pipe', 'pipe', 'pipe'],
    })

    const onOutput = (data: Buffer) => {
      const text = data.toString()
      // 首先将原始输出保留到 run.log，因此即使
      // 每行处理低于抛出。后端已经自己写了
      // 这里的结构线条一次出现；这捕获了预记录引导程序
      // 输出（以及直接打印到 stdout/stderr 的任何内容）。
      if (this.logStream) {
        try {
          this.logStream.write(text)
        } catch {
          // 忽略 - 日志记录绝不能中断启动
        }
      }
      const lines = text.split('\n').filter(Boolean)
      for (const line of lines) {
        this.recordLog(line)
        this.emit('log', line)
      }
    }
    this.process.stdout?.on('data', onOutput)
    this.process.stderr?.on('data', onOutput)

    this.process.on('exit', (code) => {
      // 如果后端在准备好之前就死掉了，现在就会出现错误
      // 而不是让 waitForReady 旋转整个超时。干净的出口
      // （代码 0/null，例如我们自己的 stop()）只是标记停止。
      const wasReady = this.status === 'ready'
      this.status = 'stopped'
      if (this.logStream) {
        try {
          this.logStream.write(`[SHELL][${new Date().toISOString()}] backend process exited with code ${code}\n`)
        } catch {
          // 忽略
        }
      }
      this.emit('log', `Python process exited with code ${code}`)
      if (!wasReady && code !== 0 && code !== null) {
        this.fail('backend_crashed', this.withLastError(`The app exited during startup (code ${code})`))
        return
      }
      // 在处理请求后死亡（后期崩溃，或 app.py 自己的 os._exit）。
      // 没有其他事情会注意到，所以在这里恢复而不是等待
      // 下一个运行状况探测。
      if (wasReady && !this.shuttingDown) {
        this.stopHealthMonitor()
        void this.recover()
      }
    })

    this.process.on('error', (err) => {
      if (bundled) {
        // 当我们刚才检查时，可执行文件就在那里。 ENOENT 意味着
        // 它在中间消失了（扫描仪在我们启动时将其删除）；
        // EACCES/EPERM 意味着某些东西拒绝让它运行。从用户的
        // 这些都是同样的问题：安全软件妨碍了。
        this.fail('backend_blocked', `The backend could not be launched: ${err.message}`, bundled)
      } else {
        this.fail('backend_missing', `Failed to start Python: ${err.message}`, command)
      }
    })

    await this.waitForReady()
  }

  private waitForReady(): Promise<void> {
    return new Promise((resolve) => {
      // 挂钟截止时间而不是尝试计数器：如果机器
      // 睡眠/挂起，1s 定时器超时，计数器将放弃
      // 太早了。基于时间的边界会跟踪实际经过的时间。
      // 仅当进程处于活动状态但从未回复 /api/health 时才可访问：
      // 崩溃立即退出，楔形启动被杀死
      // 后端自己的看门狗，两条路径都报告真正的原因。所以这是
      // 一个后挡板，放置在看门狗的正上方，这样它的信息就能赢得比赛。
      const timeoutMs = 30_000
      const startedAt = Date.now()

      const check = () => {
        // 探测未经身份验证的运行状况端点，而不是 /config：/config
        // 一旦设置了 web_password，就需要进行身份验证，这将使此轮询
        // 永远 401 并挂起启动。
        const req = http.get(`http://127.0.0.1:${this.port}/api/health`, (res) => {
          // 排空主体，这样套接字就不会被保留在保持活动池之外。
          res.resume()
          if (res.statusCode === 200) {
            this.status = 'ready'
            this.emit('log', `Backend ready on port ${this.port}`)
            this.emit('ready', this.port)
            // 从这里开始，渲染器信任“就绪”，因此该监视器是
            // 唯一可以注意到后端稍后消失的事情。
            this.startHealthMonitor()
            resolve()
          } else {
            retry()
          }
        })

        req.on('error', () => retry())
        req.setTimeout(2000, () => {
          req.destroy()
          retry()
        })
      }

      const retry = () => {
        // 后端已解决：准备好（完成），或因退出而停止/出错
        // 处理程序（不要继续轮询死进程 - 错误已发出）。
        if (this.status === 'ready' || this.status === 'stopped' || this.status === 'error') {
          resolve()
          return
        }
        if (Date.now() - startedAt >= timeoutMs) {
          this.fail(
            'backend_timeout',
            this.withLastError(`The app failed to start within ${Math.round(timeoutMs / 1000)} seconds`),
          )
          resolve()
          return
        }
        setTimeout(check, 1000)
      }

      setTimeout(check, 2000)
    })
  }

  stop(): void {
    // 在终止之前设置，以便退出处理程序将其视为故意的
    // 拆解并且不会尝试“恢复”我们刚刚要求终止的进程。
    this.shuttingDown = true
    this.stopHealthMonitor()
    this.closeLogStream()
    const proc = this.process
    if (proc) {
      proc.kill('SIGTERM')
      // 保留本地引用，以便 SIGKILL 回退仍然可以到达进程
      // 即使我们清除了 `this.process`;否则后端会卡住
      // 永远不会像僵尸一样被强制杀死和泄漏。
      setTimeout(() => {
        if (!proc.killed) {
          proc.kill('SIGKILL')
        }
      }, 5000)
      this.process = null
    }
    this.status = 'stopped'
  }

  /**
   * Synchronously, forcefully tear the backend down and BLOCK until its files
   * are no longer held. Used only on the update-install path: the NSIS silent
   * updater starts deleting the old install almost immediately, and on Windows a
   * still-running cowagent-backend.exe (plus the hundreds of DLLs it maps from
   * _internal) keeps those files locked, so the installer aborts with "卸载旧
   * 应用程序文件失败:2". The normal stop() only sends SIGTERM and returns before
   * the process is actually gone — which on Windows is a no-op for a native exe.
   *
   * Best-effort throughout: any failure here must never block the update, so we
   * still fall through to quitAndInstall even if the kill didn't fully succeed.
   */
  stopSync(): void {
    this.shuttingDown = true
    this.stopHealthMonitor()
    this.closeLogStream()
    const proc = this.process
    this.process = null
    this.status = 'stopped'
    const pid = proc?.pid
    if (process.platform === 'win32') {
      // SIGTERM/SIGKILL 对于本机 Windows exe 实际上毫无意义，因此
      // 使用taskkill强制结束整个进程TREE(/T)(/F)。这个
      // 到达后端可能已生成的子进程（rg.exe、agent bash
      // 工具等），否则会使文件保持锁定状态。任务终止是
      // 同步，因此一旦返回，句柄就会被释放。
      try {
        if (pid) {
          execFileSync('taskkill', ['/pid', String(pid), '/T', '/F'], {
            stdio: 'ignore',
            timeout: 5000,
          })
        }
      } catch {
        // 已经消失/访问被拒绝 - 落入名义扫描
      }
      // 腰带：也可以通过图像名称杀死任何杂散的后端，以防万一
      // 树上散步错过了一个重新养育的孩子。作用域为我们的 exe 名称，因此
      // 不能触及不相关的进程。
      try {
        execFileSync('taskkill', ['/im', 'cowagent-backend.exe', '/T', '/F'], {
          stdio: 'ignore',
          timeout: 5000,
        })
      } catch {
        // 没有这样的过程/无事可做
      }
    } else if (proc) {
      // POSIX：SIGKILL 立即且可靠；没有文件锁定问题
      // 就地捆绑交换，但我们仍然希望孩子在退出之前消失。
      try {
        proc.kill('SIGKILL')
      } catch {
        // 已经走了——忽略
      }
    }
  }

  async restart(): Promise<void> {
    // 从 UI 手动重试可以获得新的恢复预算；重新启动
    // 本身触发的恢复路径必须持续计数到极限。
    if (!this.recovering) {
      this.recoveryAttempts = 0
      this.recoveryWindowStart = Date.now()
    }
    this.stop()
    await new Promise((resolve) => setTimeout(resolve, 2000))
    await this.start()
  }
}
