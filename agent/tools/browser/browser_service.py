"""
Browser service - Playwright wrapper managing browser lifecycle and page operations.

All Playwright calls run on a dedicated background thread so that callers from
any worker thread can safely use the service.  An idle-timeout mechanism
automatically shuts down the browser (and its thread) after a configurable
period of inactivity to free resources.
"""

import os
import sys
import json
import uuid
import queue
import signal
import threading
from typing import Optional, Dict, Any, List, Callable

from common.log import logger
from common.utils import expand_path, is_cloud_deployment, memory_headroom_mb


_DEFAULT_USER_DATA_DIR = "~/.cow/browser_profile"

# 渲染器 JS 堆上限的上下界。下限是简单页面要能跑起来
# 所需的最低内存；上限是继续调高便不再有意义的阈值。
# fraction 用于把剩余的可用内存留给渲染器的非 JS
# 分配以及浏览器/驱动程序进程。
_V8_HEAP_MIN_MB = 128
_V8_HEAP_MAX_MB = 512
_V8_HEAP_DEFAULT_MB = 256
_V8_HEAP_FRACTION = 0.4

try:
    from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False


# ---------------------------------------------------------------------------
# 快照 DOM 助手
# ---------------------------------------------------------------------------

# 通常为代理携带有用内容的标签
_INTERACTIVE_TAGS = {
    "a", "button", "input", "textarea", "select", "option",
    "label", "details", "summary",
}
_SEMANTIC_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "li", "td", "th", "caption", "figcaption", "blockquote", "pre", "code",
    "nav", "main", "article", "section", "header", "footer", "form", "table",
    "img", "video", "audio",
}
_KEEP_TAGS = _INTERACTIVE_TAGS | _SEMANTIC_TAGS

_SNAPSHOT_JS = """
() => {
    const KEEP = new Set(%s);
    const INTERACTIVE = new Set(%s);
    const SKIP = new Set(["script","style","noscript","svg","path","meta","link","br","hr"]);
    const CLICKABLE_ROLES = new Set([
        "button","link","tab","menuitem","menuitemcheckbox","menuitemradio",
        "option","switch","checkbox","radio","combobox","searchbox","slider",
        "spinbutton","textbox","treeitem"
    ]);
    let refCounter = 0;
    const refMap = {};

    function visible(el) {
        if (!(el instanceof HTMLElement)) return true;
        const st = window.getComputedStyle(el);
        if (st.display === "none" || st.visibility === "hidden") return false;
        if (parseFloat(st.opacity) === 0) return false;
        return true;
    }

    // Strong signals: these attributes alone are enough to mark as interactive
    function hasStrongInteractiveSignal(el) {
        const role = el.getAttribute("role");
        if (role && CLICKABLE_ROLES.has(role)) return true;
        if (el.hasAttribute("onclick") || el.hasAttribute("tabindex")) return true;
        if (el.hasAttribute("data-click") || el.hasAttribute("data-action")) return true;
        if (el.getAttribute("contenteditable") === "true") return true;
        return false;
    }

    // Check if cursor:pointer is set directly (not just inherited from parent)
    function hasOwnPointerCursor(el) {
        try {
            const st = window.getComputedStyle(el);
            if (st.cursor !== "pointer") return false;
            const parent = el.parentElement;
            if (parent) {
                const pst = window.getComputedStyle(parent);
                if (pst.cursor === "pointer") return false;
            }
            return true;
        } catch(e) {}
        return false;
    }

    function hasTextOrContent(el) {
        const t = el.textContent || "";
        if (t.trim().length > 0) return true;
        if (el.querySelector("img,video,audio,canvas")) return true;
        const ariaLabel = el.getAttribute("aria-label");
        if (ariaLabel && ariaLabel.trim()) return true;
        const title = el.getAttribute("title");
        if (title && title.trim()) return true;
        return false;
    }

    function isImplicitInteractive(el) {
        if (hasStrongInteractiveSignal(el)) return true;
        if (hasOwnPointerCursor(el) && hasTextOrContent(el)) return true;
        return false;
    }

    function getTextContent(el) {
        let text = "";
        for (const ch of el.childNodes) {
            if (ch.nodeType === Node.TEXT_NODE) {
                text += ch.textContent;
            }
        }
        return text.trim();
    }

    function walk(node) {
        if (node.nodeType === Node.TEXT_NODE) {
            const t = node.textContent.trim();
            return t ? t : null;
        }
        if (node.nodeType !== Node.ELEMENT_NODE) return null;
        const tag = node.tagName.toLowerCase();
        if (SKIP.has(tag)) return null;
        if (!visible(node)) return null;

        const children = [];
        for (const ch of node.childNodes) {
            const r = walk(ch);
            if (r !== null) {
                if (typeof r === "string") children.push(r);
                else children.push(r);
            }
        }

        const nativeInteractive = INTERACTIVE.has(tag);
        const implicitInteractive = !nativeInteractive && (node instanceof HTMLElement) && isImplicitInteractive(node);
        const keep = KEEP.has(tag) || implicitInteractive;

        if (!keep) {
            if (children.length === 0) return null;
            if (children.length === 1) return children[0];
            return children;
        }

        const obj = { tag };
        if (nativeInteractive || implicitInteractive) {
            refCounter++;
            obj.ref = refCounter;
            refMap[refCounter] = node;
        }

        if (implicitInteractive) {
            const role = node.getAttribute("role");
            if (role) obj.role = role;
            const directText = getTextContent(node);
            if (!directText && children.length === 0) {
                const ariaLabel = node.getAttribute("aria-label");
                const title = node.getAttribute("title");
                if (ariaLabel) obj.ariaLabel = ariaLabel;
                else if (title) obj.ariaLabel = title;
            }
        }

        // Attributes
        if (tag === "a" && node.href) obj.href = node.getAttribute("href");
        if (tag === "img") {
            obj.alt = node.alt || "";
            obj.src = node.getAttribute("src") || "";
        }
        if (tag === "input" || tag === "textarea" || tag === "select") {
            obj.type = node.type || "text";
            obj.name = node.name || undefined;
            obj.value = node.value || undefined;
            obj.placeholder = node.placeholder || undefined;
            if (node.disabled) obj.disabled = true;
            if (tag === "input" && node.type === "checkbox") obj.checked = node.checked;
        }
        if (tag === "button") {
            if (node.disabled) obj.disabled = true;
        }
        if (tag === "option") {
            obj.value = node.value;
            if (node.selected) obj.selected = true;
        }
        if (tag === "label" && node.htmlFor) obj.for = node.htmlFor;

        // Role / aria-label for native interactive & semantic elements
        if (!implicitInteractive) {
            const role = node.getAttribute("role");
            if (role) obj.role = role;
            const ariaLabel = node.getAttribute("aria-label");
            if (ariaLabel) obj.ariaLabel = ariaLabel;
        }

        // Children
        if (children.length === 1 && typeof children[0] === "string") {
            obj.text = children[0];
        } else if (children.length > 0) {
            obj.children = children;
        }

        return obj;
    }

    const result = walk(document.body);
    window.__cowRefMap = refMap;
    return { tree: result, refCount: refCounter };
}
""" % (
    str(list(_KEEP_TAGS)),
    str(list(_INTERACTIVE_TAGS)),
)

# 在冻结的桌面构建里，把快照作为一个 JSON 字符串返回而不是嵌套对象，
# 是一笔不小的收益：Playwright 会逐个节点地序列化嵌套返回值，
# 产生大量 driver<->python 协议往返，而每轮往返的固定开销
# 在冻结后的打包产物中会急剧累积（大约 300 个节点的树就可能
# 需要 20 秒以上）。页面内用 JSON.stringify 把它折叠成单个字符串
# 传输；再由 Python 用 json.loads 解析。行为完全一致。
_SNAPSHOT_JS_STR = "() => JSON.stringify((%s)())" % _SNAPSHOT_JS.strip()


_BROWSER_DEAD_HINTS = (
    "has been closed",
    "browser has disconnected",
    "target closed",
    "browser closed",
    "context or browser has been closed",
)


def _is_browser_dead_error(err: Exception) -> bool:
    """Return True if *err* indicates the browser / page died out from under us."""
    msg = str(err).lower()
    return any(h in msg for h in _BROWSER_DEAD_HINTS)


def _should_use_headless() -> bool:
    """Decide headless mode: headless on Linux servers without display, headed elsewhere."""
    if sys.platform in ("win32", "darwin"):
        return False
    # Linux：检查显示
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return False
    return True


# 用命令行标记来识别本次启动产生的进程（引擎
# 本身，以及调度它的 driver）。只有我们自己进程的后代
# 才会被纳入考虑，所以只要匹配这些标记就够了，不会误伤
# 无关的子进程——例如由 bash 工具单独启动的任何东西。
_BROWSER_PROCESS_MARKERS = (
    "ms-playwright",
    "playwright/driver",
    "headless_shell",
    "chrome-linux",
    "chrome.exe",
    "chromium",
    "Google Chrome",
    "Microsoft Edge",
)


def _process_table() -> Dict[int, tuple]:
    """Map pid -> (ppid, cmdline) for every visible process.

    Reads /proc directly where available, so this keeps working on minimal images
    that ship no process utilities, and falls back to `ps` elsewhere.
    """
    table: Dict[int, tuple] = {}
    if os.path.isdir("/proc"):
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            pid = int(entry)
            try:
                with open(f"/proc/{pid}/stat", "rb") as f:
                    stat = f.read().decode("utf-8", "replace")
                # comm 字段外面有括号、本身也可能含空格，因此要从
                # 最后一个右括号之后解析数字字段；
                # 其中的第二个就是 ppid。
                ppid = int(stat[stat.rfind(")") + 1:].split()[1])
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    cmdline = f.read().decode("utf-8", "replace").replace("\0", " ")
            except (OSError, ValueError, IndexError):
                continue
            table[pid] = (ppid, cmdline)
        return table

    try:
        import subprocess
        out = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,command="],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception as e:
        logger.debug(f"[Browser] process listing unavailable: {e}")
        return table
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 2:
            continue
        try:
            table[int(parts[0])] = (int(parts[1]), parts[2] if len(parts) > 2 else "")
        except ValueError:
            continue
    return table


def _kill_browser_descendants(root_pid: int) -> int:
    """Force-kill every browser process descended from *root_pid*.

    Returns how many were killed. Used when the launch thread is wedged and will
    never run its own teardown, in which case these processes would otherwise
    hold their memory for the remaining lifetime of the parent process.
    """
    table = _process_table()
    children: Dict[int, List[int]] = {}
    for pid, (ppid, _cmdline) in table.items():
        children.setdefault(ppid, []).append(pid)

    ordered: List[int] = []
    pending = list(children.get(root_pid, []))
    while pending:
        pid = pending.pop(0)
        ordered.append(pid)
        pending.extend(children.get(pid, []))

    sig = getattr(signal, "SIGKILL", signal.SIGTERM)
    killed = 0
    # 从最深的子进程开始，这样父进程在我们清理期间无法再产生替代进程。
    for pid in reversed(ordered):
        cmdline = table.get(pid, (0, ""))[1]
        if not any(marker in cmdline for marker in _BROWSER_PROCESS_MARKERS):
            continue
        try:
            os.kill(pid, sig)
            killed += 1
        except OSError:
            pass
    return killed


def _flatten_tree(node, indent=0) -> List[str]:
    """Convert snapshot tree to compact text lines for LLM consumption."""
    if node is None:
        return []
    if isinstance(node, str):
        return [" " * indent + node]
    if isinstance(node, list):
        lines = []
        for child in node:
            lines.extend(_flatten_tree(child, indent))
        return lines
    if not isinstance(node, dict):
        return []

    tag = node.get("tag", "?")
    ref = node.get("ref")
    parts = [tag]
    if ref:
        parts[0] = f"[{ref}] {tag}"

    # 内联属性
    for attr in ("type", "name", "href", "alt", "role", "ariaLabel", "placeholder", "value"):
        val = node.get(attr)
        if val:
            # 截断长值
            s = str(val)
            if len(s) > 80:
                s = s[:77] + "..."
            parts.append(f'{attr}="{s}"')

    for flag in ("disabled", "checked", "selected"):
        if node.get(flag):
            parts.append(flag)

    prefix = " " * indent
    header = prefix + " ".join(parts)

    text = node.get("text")
    if text:
        # 截断长文本
        if len(text) > 120:
            text = text[:117] + "..."
        header += f": {text}"

    lines = [header]
    children = node.get("children", [])
    for child in children:
        lines.extend(_flatten_tree(child, indent + 2))
    return lines


class BrowserService:
    """Manages a Playwright browser on a dedicated background thread.

    All Playwright operations are dispatched to a single long-lived thread via
    a task queue.  Callers from *any* worker thread can use the public API
    safely.  An idle timer automatically shuts the browser down after
    ``idle_timeout`` seconds of inactivity (default 300 = 5 min).
    """

    _IDLE_TIMEOUT_DEFAULT = 300  # 秒
    # 足够大，能在负载较高的机器上完成冷启动，同时又给定了上限，
    # 约束一个永远无法完成的启动最多让调用者等多久。
    _STARTUP_TIMEOUT_DEFAULT = 60  # 秒

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._headless: Optional[bool] = None
        self._screenshot_dir: Optional[str] = None

        # 后台线程状态
        self._thread: Optional[threading.Thread] = None
        self._task_queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._alive = False
        self._ready = threading.Event()

        # Playwright 对象（仅在后台线程上访问）
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

        # 当我们驱动系统自带的 Chrome/Edge 时，会自行启动浏览器并开启
        # 调试端口，再通过 CDP 连接（参见 chrome_launcher）。这样能避开
        # chromium.launch(channel=...) 会触发的 macOS 自动化授权提示，
        # 以及随之而来的数秒停顿。这里持有子进程的所有者。
        self._chrome_launcher = None
        # 使用系统 Chrome 模式时，系统浏览器可执行文件的路径。
        self._system_exe: Optional[str] = None

        # 启动模式：取 "fresh" | "persistent" | "cdp" 之一。
        # - cdp：通过 CDP 端点连接外部启动的 Chrome。
        # - persistent：用 user_data_dir 调用 launch_persistent_context 启动，
        #   让 cookies/登录状态在多次运行之间得以保留（默认）。
        # - fresh：经典 launch + new_context，每次运行都是全新状态。
        #
        # persistent/fresh 模式下，实际使用的 Chromium 二进制由
        # browser_env.resolve_engine() 解析：优先采用系统 Chrome/Edge
        # （基于 channel，无需任何下载），否则回退到 Playwright 自行下载的
        # Chromium。驱动系统浏览器时，`self._channel` 保存 playwright 的
        # 频道（"chrome"/"msedge"），否则为 None（使用内置 Chromium）。
        cdp_endpoint = self._config.get("cdp_endpoint") or ""
        persistent_flag = self._config.get("persistent", True)
        user_data_dir_cfg = self._config.get("user_data_dir")
        if user_data_dir_cfg is None:
            user_data_dir_cfg = _DEFAULT_USER_DATA_DIR

        self._channel: Optional[str] = None
        self._cdp_endpoint: str = cdp_endpoint.strip() if isinstance(cdp_endpoint, str) else ""
        if self._cdp_endpoint:
            self._launch_mode = "cdp"
            self._user_data_dir: str = ""
        elif persistent_flag and user_data_dir_cfg:
            self._launch_mode = "persistent"
            self._user_data_dir = expand_path(str(user_data_dir_cfg))
        else:
            self._launch_mode = "fresh"
            self._user_data_dir = ""

        # 解析要驱动的浏览器引擎（系统 Chrome，还是 Playwright 下载的
        # Chromium）。探测失败会延迟到启动时才暴露。
        #
        # 对系统 Chrome/Edge，我们不使用 chromium.launch(channel=...)：
        # 那会“接管”另一个应用程序，并触发 macOS 自动化授权提示
        # 和长时间的停顿。相反，我们自行启动浏览器并开启
        # 调试端口，再通过 CDP 连接（self._launch_mode = "system-cdp"）。
        # `self._system_exe` 是浏览器可执行文件；persistent 模式下
        # 的 user_data_dir 负责保留跨会话的登录状态。
        if self._launch_mode != "cdp":
            try:
                from agent.tools.browser.browser_env import resolve_engine
                engine = resolve_engine(self._config)
                if engine["mode"] == "system-chrome":
                    self._channel = engine["channel"]
                    self._system_exe = engine.get("path")
                    # 只有当我们确实拿到可执行文件路径时才切到 spawn+CDP
                    # （macOS/Windows/Linux 的检测都会返回该路径）。
                    # 登录状态保存在专用的配置文件目录中。
                    if self._system_exe:
                        self._launch_mode = "system-cdp"
                        if not self._user_data_dir:
                            self._user_data_dir = expand_path(_DEFAULT_USER_DATA_DIR)
                    logger.info(f"[Browser] Engine resolved: {engine['reason']} "
                                f"(spawn+CDP={bool(self._system_exe)})")
                elif engine["mode"] == "playwright-chromium":
                    logger.info(f"[Browser] Engine resolved: {engine['reason']}")
                else:
                    logger.info(f"[Browser] No ready engine yet: {engine['reason']}")
            except Exception as e:
                logger.debug(f"[Browser] Engine resolution skipped: {e}")

        # 空闲自动释放
        idle_cfg = self._config.get("idle_timeout")
        self._idle_timeout: float = float(idle_cfg) if idle_cfg is not None else self._IDLE_TIMEOUT_DEFAULT
        self._idle_timer: Optional[threading.Timer] = None

        startup_cfg = self._config.get("startup_timeout")
        self._startup_timeout: float = (
            float(startup_cfg) if startup_cfg is not None else self._STARTUP_TIMEOUT_DEFAULT
        )

        # 在外部检测到浏览器/页面已死亡时置位
        # （例如用户手动关闭了窗口）。下一次 _submit() 会
        # 拆除过时的线程并重新启动浏览器。
        self._needs_restart = False

    # ------------------------------------------------------------------
    # 后台线程生命周期
    # ------------------------------------------------------------------

    def _start_thread(self):
        """Start the dedicated Playwright thread, blocking until it is usable.

        Raises if the browser does not become ready in time.
        """
        with self._lock:
            if self._alive and self._thread and self._thread.is_alive():
                return
            # 等待旧线程完全退出后再创建新线程
            old = self._thread
            if old and old.is_alive():
                old.join(timeout=5)
            # 新建队列，避开上一次 close() 遗留的过时哨兵
            self._task_queue = queue.Queue()
            self._alive = True
            self._ready = threading.Event()
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="BrowserThread")
            self._thread.start()
            ready = self._ready

        # 在锁外等待：永远无法完成的启动必须在这里被拆除，
        # 因为 close() 同样需要拿到这把锁。
        if not ready.wait(timeout=self._startup_timeout):
            # 挂起（而不是抛异常）的启动会让 _alive 保持置位，因此
            # 若少了这一步，调用者就会把任务排进一个永远不会消费
            # 它们的线程，然后还要再空等一个更长的超时。
            self.close()
            raise RuntimeError(
                f"Browser failed to start within {self._startup_timeout:.0f}s — "
                "not enough memory or CPU available for it. Use web_search instead "
                "and do not retry this tool."
            )

    def _run_loop(self):
        """Event loop running on the dedicated thread. Processes tasks until stopped."""
        logger.info("[Browser] Background thread started")
        try:
            self._launch_browser()
        except Exception as e:
            logger.error(f"[Browser] Failed to launch browser: {e}")
            self._alive = False
            self._ready.set()
            self._drain_queue(RuntimeError(f"Browser launch failed: {e}"))
            return
        self._ready.set()

        while self._alive:
            try:
                task = self._task_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if task is None:
                break
            fn, args, kwargs, result_slot = task
            try:
                result_slot["value"] = fn(*args, **kwargs)
            except Exception as e:
                result_slot["error"] = e
                if _is_browser_dead_error(e):
                    self._needs_restart = True
                    logger.warning(
                        f"[Browser] Detected closed page/context ({e}); "
                        "will relaunch on next request."
                    )
            finally:
                result_slot["event"].set()

        self._shutdown_browser()
        self._drain_queue(RuntimeError("Browser thread stopped"))
        logger.info("[Browser] Background thread exited")

    def _drain_queue(self, error: Exception):
        """Unblock all callers waiting on the queue with an error."""
        while True:
            try:
                task = self._task_queue.get_nowait()
            except queue.Empty:
                break
            if task is None:
                continue
            _, _, _, result_slot = task
            result_slot["error"] = error
            result_slot["event"].set()

    def _v8_heap_cap_mb(self) -> int:
        """Old-space cap for the renderer's JS heap, in MB.

        This bounds the blast radius of a runaway page: on hitting the cap the tab
        dies, which the agent can recover from, whereas letting it consume all
        remaining memory takes down everything else with it.

        Derived from the memory actually available rather than fixed, so a single
        setting behaves sensibly across allocation sizes. Override with
        ``v8_heap_mb`` under ``tools.browser``.
        """
        override = self._config.get("v8_heap_mb")
        if override:
            try:
                return max(_V8_HEAP_MIN_MB, int(override))
            except (TypeError, ValueError):
                logger.debug(f"[Browser] ignoring invalid v8_heap_mb: {override!r}")

        headroom = memory_headroom_mb()
        if headroom is None:
            return _V8_HEAP_DEFAULT_MB
        # 剩余的内存余量还必须覆盖渲染器的非 JS 内存，
        # 以及浏览器和驱动程序进程，因此 JS 堆只能分到其中一部分。
        return int(min(_V8_HEAP_MAX_MB, max(_V8_HEAP_MIN_MB, headroom * _V8_HEAP_FRACTION)))

    def _launch_browser(self):
        """Launch / connect Chromium on the background thread."""
        # 在任何启动之前，先把 Playwright 指向我们固定的下载目录，
        # 这样“内置 Chromium”这一回退方案能找到下载到 ~/.cow 的浏览器。
        try:
            from agent.tools.browser.browser_env import apply_browsers_path_env
            apply_browsers_path_env()
        except Exception as e:
            logger.debug(f"[Browser] apply_browsers_path_env skipped: {e}")

        if self._headless is None:
            headless_cfg = self._config.get("headless")
            self._headless = headless_cfg if headless_cfg is not None else _should_use_headless()

        launch_args = [
            "--disable-dev-shm-usage",
            # 削减首次启动开销：跳过首次运行向导、默认浏览器
            # 提示，以及 Chrome 的后台/组件联网行为。
            # 这些都不会影响页面交互，却能明显加快冷启动
            # 和每次导航的速度。
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
        ]
        disabled_features = ["Translate", "OptimizationHints"]
        if self._headless:
            launch_args.append("--no-sandbox")

        if is_cloud_deployment():
            launch_args.extend([
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-extensions",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--no-zygote",
                # 代理只驱动单个标签页，因此要防止跨源 frame
                # 在我们背后偷偷新增渲染进程。
                "--renderer-process-limit=1",
                # 缓存下来的页面会让整个渲染进程一直驻留内存。内存紧张时，
                # 与其用后退导航，不如重新加载页面更划算。
                "--disable-back-forward-cache",
                f"--js-flags=--max-old-space-size={self._v8_heap_cap_mb()}",
            ])
            disabled_features.extend(["site-per-process", "IsolateOrigins", "TranslateUI"])

        # Chromium 只认它收到的最后一个 --disable-features，因此每个
        # 功能都必须放进同一个开关里，否则先加进去的会被丢弃。
        launch_args.append("--disable-features=" + ",".join(disabled_features))

        extra_args = self._config.get("launch_args", [])
        if extra_args:
            launch_args.extend(extra_args)

        viewport_w = self._config.get("viewport_width", 1280)
        viewport_h = self._config.get("viewport_height", 720)
        viewport = {"width": viewport_w, "height": viewport_h}
        user_agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )

        self._playwright = sync_playwright().start()

        if self._launch_mode == "cdp":
            self._connect_cdp(viewport)
        elif self._launch_mode == "system-cdp":
            self._launch_system_cdp(launch_args, viewport)
        elif self._launch_mode == "persistent":
            self._launch_persistent(launch_args, viewport, user_agent)
        else:
            self._launch_fresh(launch_args, viewport, user_agent)

        logger.info("[Browser] Browser ready")

    def _launch_fresh(self, launch_args: List[str], viewport: Dict[str, int], user_agent: str):
        """Classic launch: brand new Chromium with an empty context.

        When `self._channel` is set (e.g. "chrome"/"msedge"), Playwright drives
        the user's installed system browser instead of its own Chromium.
        """
        engine_label = f"system:{self._channel}" if self._channel else "chromium"
        logger.info(f"[Browser] Launching {engine_label} (fresh, headless={self._headless})")
        launch_kwargs: Dict[str, Any] = {
            "headless": self._headless,
            "args": launch_args,
        }
        if self._channel:
            launch_kwargs["channel"] = self._channel
        self._browser = self._playwright.chromium.launch(**launch_kwargs)
        self._context = self._browser.new_context(
            viewport=viewport,
            user_agent=user_agent,
        )
        self._page = self._context.new_page()
        self._wire_close_listeners()

    def _launch_persistent(self, launch_args: List[str], viewport: Dict[str, int], user_agent: str):
        """Launch Chromium with a persistent user_data_dir so login state survives."""
        os.makedirs(self._user_data_dir, exist_ok=True)
        engine_label = f"system:{self._channel}" if self._channel else "chromium"
        logger.info(
            f"[Browser] Launching {engine_label} (persistent, headless={self._headless}, "
            f"profile={self._user_data_dir})"
        )
        persistent_kwargs: Dict[str, Any] = {
            "user_data_dir": self._user_data_dir,
            "headless": self._headless,
            "args": launch_args,
            "viewport": viewport,
            "user_agent": user_agent,
        }
        # 驱动系统浏览器时，让它使用自己真实的 UA，而不是那份
        # 伪装成 Chromium 的 UA（避免真实 Chrome/Edge 上出现 UA/引擎不匹配）。
        if self._channel:
            persistent_kwargs["channel"] = self._channel
            persistent_kwargs.pop("user_agent", None)
        try:
            self._context = self._playwright.chromium.launch_persistent_context(**persistent_kwargs)
        except Exception as e:
            # 当另一个 Chromium 实例已持有配置文件时，该配置文件将被锁定。
            msg = str(e).lower()
            if "singletonlock" in msg or "profile" in msg or "lock" in msg:
                raise RuntimeError(
                    f"Browser profile '{self._user_data_dir}' is in use by another process. "
                    "Close the other Chromium / cow instance, or set a different "
                    "tools.browser.user_data_dir."
                ) from e
            raise

        # 持久上下文没有父浏览器句柄；重用自动创建的页面。
        self._browser = None
        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        self._wire_close_listeners()

    def _launch_system_cdp(self, launch_args: List[str], viewport: Dict[str, int]):
        """Spawn the user's system Chrome/Edge with a debugging port, attach via CDP.

        This is the default for system browsers. Unlike launch(channel=...), it
        does not "take over" the browser app, so it avoids the macOS Automation
        prompt / long stall. Login state persists in the isolated user_data_dir.
        """
        from agent.tools.browser.chrome_launcher import ChromeLauncher

        os.makedirs(self._user_data_dir, exist_ok=True)
        logger.info(
            f"[Browser] Launching system:{self._channel} via spawn+CDP "
            f"(headless={self._headless}, profile={self._user_data_dir})"
        )
        self._chrome_launcher = ChromeLauncher(
            executable=self._system_exe,
            user_data_dir=self._user_data_dir,
            extra_args=launch_args,
            headless=self._headless,
        )
        endpoint = self._chrome_launcher.launch()

        try:
            self._browser = self._playwright.chromium.connect_over_cdp(endpoint)
        except Exception as e:
            if not self._chrome_launcher.adopted:
                raise
            # 我们复用了上一会话遗留的浏览器，但它却无法附加。
            # 若直接重试，仍会再次采用同一个实例，因此这里更换它。
            logger.warning(f"[Browser] cannot attach to the reused Chrome: {e}")
            endpoint = self._chrome_launcher.relaunch_fresh()
            self._browser = self._playwright.chromium.connect_over_cdp(endpoint)
        # 生成的 Chrome 打开自己的默认上下文（由
        # 用户数据目录）；重复使用它，以便 cookie/登录信息持续存在。
        contexts = self._browser.contexts
        self._context = contexts[0] if contexts else self._browser.new_context(viewport=viewport)
        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        try:
            self._page.set_viewport_size(viewport)
        except Exception:
            pass
        self._wire_close_listeners()

    def _connect_cdp(self, viewport: Dict[str, int]):
        """Attach to an existing Chrome started with --remote-debugging-port."""
        endpoint = self._cdp_endpoint
        logger.info(f"[Browser] Connecting to existing Chrome via CDP: {endpoint}")
        try:
            self._browser = self._playwright.chromium.connect_over_cdp(endpoint)
        except Exception as e:
            msg = str(e).lower()
            if "econnrefused" in msg or "connect" in msg or "refused" in msg:
                raise RuntimeError(
                    f"Cannot reach Chrome at {endpoint}. The CDP browser is not "
                    "running. Ask the user to launch Chrome with "
                    "--remote-debugging-port and --user-data-dir, then retry. "
                    "Do not retry this tool until the user confirms."
                ) from e
            raise

        contexts = self._browser.contexts
        if contexts:
            self._context = contexts[0]
        else:
            self._context = self._browser.new_context(viewport=viewport)

        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        self._wire_close_listeners()

    def _wire_close_listeners(self):
        """Mark needs_restart whenever the browser / context / page dies externally."""
        def _on_dead(_obj=None):
            self._needs_restart = True

        try:
            if self._browser:
                self._browser.on("disconnected", _on_dead)
            if self._context:
                self._context.on("close", _on_dead)
            if self._page:
                self._page.on("close", _on_dead)
        except Exception as e:
            logger.debug(f"[Browser] Failed to wire close listeners: {e}")

    def _shutdown_browser(self):
        """Shut down Playwright resources on the background thread.

        Mode-specific behavior:
        - cdp: only disconnect the Playwright client; leave the user's Chrome
          and its tabs untouched (do NOT close the context).
        - persistent: close the persistent context (no separate browser handle).
        - fresh: close context, then browser.
        """
        self._cancel_idle_timer()

        if self._launch_mode == "cdp":
            # 对外部 CDP 而言，browser.close() 只会断开 Playwright
            # 客户端；用户的 Chrome 进程及其标签页会继续保持运行。
            try:
                if self._browser:
                    self._browser.close()
            except Exception as e:
                logger.debug(f"[Browser] cdp disconnect error: {e}")
        elif self._launch_mode == "system-cdp":
            # Chrome 是我们启动的、归我们所有：先断开 CDP 客户端，
            # 再结束我们启动的进程，免得它一直滞留不退出。
            try:
                if self._browser:
                    self._browser.close()
            except Exception as e:
                logger.debug(f"[Browser] system-cdp disconnect error: {e}")
            try:
                if self._chrome_launcher:
                    self._chrome_launcher.close()
            except Exception as e:
                logger.debug(f"[Browser] chrome launcher close error: {e}")
            self._chrome_launcher = None
        else:
            for obj, label in [
                (self._context, "context"),
                (self._browser, "browser"),
            ]:
                try:
                    if obj:
                        obj.close()
                except Exception as e:
                    logger.debug(f"[Browser] {label} close error: {e}")

        try:
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            logger.debug(f"[Browser] playwright stop error: {e}")
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        logger.info("[Browser] Browser closed")

    def _submit(self, fn: Callable, *args, **kwargs):
        """Submit *fn* to the background thread and block until it completes."""
        # 如果浏览器已在外部死掉（例如用户关闭了窗口），就先把
        # 过时的线程拆掉，这样 _start_thread() 会重新启动一个新线程。
        if self._needs_restart:
            logger.info("[Browser] Restarting after detecting closed browser")
            self.close()
            self._needs_restart = False

        self._start_thread()

        if not self._alive:
            raise RuntimeError("Browser is not available")

        self._reset_idle_timer()

        result_slot: Dict[str, Any] = {"event": threading.Event()}
        self._task_queue.put((fn, args, kwargs, result_slot))

        # 如果后台线程崩溃，超时可防止永久挂起
        completed = result_slot["event"].wait(timeout=120)
        if not completed:
            raise TimeoutError("Browser operation timed out (120s)")

        if "error" in result_slot:
            raise result_slot["error"]
        return result_slot.get("value")

    # ------------------------------------------------------------------
    # 空闲自动释放
    # ------------------------------------------------------------------

    def _reset_idle_timer(self):
        self._cancel_idle_timer()
        if self._idle_timeout > 0:
            self._idle_timer = threading.Timer(self._idle_timeout, self._on_idle_timeout)
            self._idle_timer.daemon = True
            self._idle_timer.start()

    def _cancel_idle_timer(self):
        if self._idle_timer:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _on_idle_timeout(self):
        logger.info(f"[Browser] Idle for {self._idle_timeout}s, auto-releasing browser")
        self.close()

    # ------------------------------------------------------------------
    # 公共生命周期
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        """True when a browser is currently up and serving requests.

        The service object itself outlives any individual browser, so this asks
        about the browser rather than about the service.
        """
        with self._lock:
            return bool(
                self._alive
                and not self._needs_restart
                and self._thread is not None
                and self._thread.is_alive()
            )

    def close(self):
        """Shut down browser and background thread (safe from any thread)."""
        self._cancel_idle_timer()
        with self._lock:
            if not self._alive:
                self._needs_restart = False
                return
            self._alive = False
            t = self._thread
        if self._task_queue is not None:
            self._task_queue.put(None)
        if t is not None and t.is_alive():
            t.join(timeout=10)
            if t.is_alive():
                # 线程卡死在了启动流程里，_shutdown_browser() 永远不会
                # 执行，它启动出来的任何进程都会残留到本进程的剩余
                # 生命周期。因此这里直接回收它们。
                self._reap_spawned_processes()
        with self._lock:
            self._thread = None
            self._needs_restart = False

    def _reap_spawned_processes(self):
        """Force-kill browser processes left behind by a launch that never finished."""
        try:
            if self._chrome_launcher:
                self._chrome_launcher.close()
        except Exception as e:
            logger.debug(f"[Browser] launcher close error during reap: {e}")
        self._chrome_launcher = None

        # 卡死的线程可能仍持有半成品对象的引用，因此这里丢弃
        # 我们自己的引用，下面的进程清理才能真正把资源释放掉。
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

        try:
            killed = _kill_browser_descendants(os.getpid())
        except Exception as e:
            logger.warning(f"[Browser] Failed to reclaim browser processes: {e}")
            return
        if killed:
            logger.warning(
                f"[Browser] Launch did not finish; force-killed {killed} leftover "
                "browser process(es)"
            )

    # ------------------------------------------------------------------
    # 操作（每个方法都分派到后台线程）
    # ------------------------------------------------------------------

    def navigate(self, url: str, timeout: int = 30000) -> Dict[str, Any]:
        return self._submit(self._do_navigate, url, timeout)

    def _do_navigate(self, url: str, timeout: int) -> Dict[str, Any]:
        page = self._page
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            status = resp.status if resp else None
        except Exception as e:
            return {"error": f"Navigation failed: {e}"}

        # SPA 会一直保持长连接（Websocket、轮询、分析上报），几乎
        # 不会真正进入 “networkidle”，干等整个超时只会浪费时间。
        # domcontentloaded 时已经能得到可用的 DOM；给页面留一段
        # 短暂的宽限期完成初次渲染/XHR，然后再继续。
        try:
            page.wait_for_load_state("networkidle", timeout=1500)
        except Exception:
            pass
        page.wait_for_timeout(300)

        try:
            title = page.title()
        except Exception:
            title = ""
        try:
            current_url = page.url
        except Exception:
            current_url = url

        return {"url": current_url, "title": title, "status": status}

    def snapshot(self, selector: Optional[str] = None) -> str:
        return self._submit(self._do_snapshot, selector)

    def _do_snapshot(self, selector: Optional[str] = None) -> str:
        page = self._page
        try:
            # 返回单个 JSON 字符串（而非嵌套对象），避免冻结版构建里
            # Playwright 逐节点序列化往返的低效。请参阅 _SNAPSHOT_JS_STR。
            raw = page.evaluate(_SNAPSHOT_JS_STR)
            result = json.loads(raw) if isinstance(raw, str) else raw
        except Exception as e:
            return f"[Snapshot error: {e}]"

        tree = result.get("tree")
        ref_count = result.get("refCount", 0)
        lines = _flatten_tree(tree)

        try:
            title = page.title()
        except Exception:
            title = ""
        try:
            url = page.url
        except Exception:
            url = ""

        header = f"Page: {title}  ({url})\nInteractive elements: {ref_count}\n---"
        body = "\n".join(lines)

        max_chars = self._config.get("snapshot_max_chars", 30000)
        if len(body) > max_chars:
            body = body[:max_chars] + "\n... [snapshot truncated]"

        return f"{header}\n{body}"

    def screenshot(self, full_page: bool = False, cwd: str = "") -> str:
        return self._submit(self._do_screenshot, full_page, cwd)

    def _do_screenshot(self, full_page: bool = False, cwd: str = "") -> str:
        page = self._page
        save_dir = self._get_screenshot_dir(cwd)
        filename = f"screenshot_{uuid.uuid4().hex[:8]}.png"
        filepath = os.path.join(save_dir, filename)
        page.screenshot(path=filepath, full_page=full_page)
        logger.info(f"[Browser] Screenshot saved: {filepath}")
        return filepath

    def click(self, ref: Optional[int] = None, selector: Optional[str] = None,
              timeout: int = 5000) -> Dict[str, Any]:
        return self._submit(self._do_click, ref, selector, timeout)

    def _do_click(self, ref, selector, timeout) -> Dict[str, Any]:
        page = self._page
        try:
            if ref is not None:
                result = page.evaluate(f"""
                    () => {{
                        const el = window.__cowRefMap && window.__cowRefMap[{ref}];
                        if (!el) return {{ error: "ref {ref} not found. Run snapshot first." }};
                        el.click();
                        return {{ clicked: true, tag: el.tagName.toLowerCase() }};
                    }}
                """)
                if result.get("error"):
                    return result
                page.wait_for_timeout(500)
                return result
            elif selector:
                page.click(selector, timeout=timeout)
                return {"clicked": True, "selector": selector}
            else:
                return {"error": "Provide either ref (from snapshot) or selector"}
        except Exception as e:
            return {"error": f"Click failed: {e}"}

    def fill(self, text: str, ref: Optional[int] = None,
             selector: Optional[str] = None, timeout: int = 5000) -> Dict[str, Any]:
        return self._submit(self._do_fill, text, ref, selector, timeout)

    def _do_fill(self, text, ref, selector, timeout) -> Dict[str, Any]:
        page = self._page
        try:
            if ref is not None:
                result = page.evaluate(f"""
                    () => {{
                        const el = window.__cowRefMap && window.__cowRefMap[{ref}];
                        if (!el) return {{ error: "ref {ref} not found. Run snapshot first." }};
                        el.focus();
                        el.value = "";
                        return {{ tag: el.tagName.toLowerCase(), name: el.name || "" }};
                    }}
                """)
                if result.get("error"):
                    return result
                page.keyboard.type(text)
                return {"filled": True, "ref": ref, "text": text}
            elif selector:
                page.fill(selector, text, timeout=timeout)
                return {"filled": True, "selector": selector, "text": text}
            else:
                return {"error": "Provide either ref (from snapshot) or selector"}
        except Exception as e:
            return {"error": f"Fill failed: {e}"}

    def select(self, value: str, ref: Optional[int] = None,
               selector: Optional[str] = None, timeout: int = 5000) -> Dict[str, Any]:
        return self._submit(self._do_select, value, ref, selector, timeout)

    def _do_select(self, value, ref, selector, timeout) -> Dict[str, Any]:
        page = self._page
        try:
            if ref is not None:
                result = page.evaluate(f"""
                    () => {{
                        const el = window.__cowRefMap && window.__cowRefMap[{ref}];
                        if (!el || el.tagName.toLowerCase() !== "select")
                            return {{ error: "ref {ref} is not a <select> element" }};
                        el.value = {repr(value)};
                        el.dispatchEvent(new Event("change", {{ bubbles: true }}));
                        return {{ selected: true, value: el.value }};
                    }}
                """)
                return result
            elif selector:
                page.select_option(selector, value, timeout=timeout)
                return {"selected": True, "selector": selector, "value": value}
            else:
                return {"error": "Provide either ref (from snapshot) or selector"}
        except Exception as e:
            return {"error": f"Select failed: {e}"}

    def scroll(self, direction: str = "down", amount: int = 500) -> Dict[str, Any]:
        return self._submit(self._do_scroll, direction, amount)

    def _do_scroll(self, direction, amount) -> Dict[str, Any]:
        page = self._page
        delta_map = {
            "down": (0, amount),
            "up": (0, -amount),
            "right": (amount, 0),
            "left": (-amount, 0),
        }
        dx, dy = delta_map.get(direction, (0, amount))
        try:
            page.mouse.wheel(dx, dy)
            page.wait_for_timeout(300)
            scroll_info = page.evaluate("""
                () => ({
                    scrollX: window.scrollX,
                    scrollY: window.scrollY,
                    scrollHeight: document.documentElement.scrollHeight,
                    clientHeight: document.documentElement.clientHeight
                })
            """)
            return {"scrolled": direction, "amount": amount, **scroll_info}
        except Exception as e:
            return {"error": f"Scroll failed: {e}"}

    def wait(self, selector: Optional[str] = None, timeout: int = 5000,
             state: str = "visible") -> Dict[str, Any]:
        return self._submit(self._do_wait, selector, timeout, state)

    def _do_wait(self, selector, timeout, state) -> Dict[str, Any]:
        page = self._page
        try:
            if selector:
                page.wait_for_selector(selector, timeout=timeout, state=state)
                return {"waited": True, "selector": selector, "state": state}
            else:
                page.wait_for_timeout(timeout)
                return {"waited": True, "timeout_ms": timeout}
        except Exception as e:
            return {"error": f"Wait failed: {e}"}

    def go_back(self) -> Dict[str, Any]:
        return self._submit(self._do_go_back)

    def _do_go_back(self) -> Dict[str, Any]:
        page = self._page
        try:
            page.go_back(wait_until="domcontentloaded", timeout=10000)
            try:
                title = page.title()
            except Exception:
                title = ""
            try:
                url = page.url
            except Exception:
                url = ""
            return {"url": url, "title": title}
        except Exception as e:
            return {"error": f"Go back failed: {e}"}

    def go_forward(self) -> Dict[str, Any]:
        return self._submit(self._do_go_forward)

    def _do_go_forward(self) -> Dict[str, Any]:
        page = self._page
        try:
            page.go_forward(wait_until="domcontentloaded", timeout=10000)
            try:
                title = page.title()
            except Exception:
                title = ""
            try:
                url = page.url
            except Exception:
                url = ""
            return {"url": url, "title": title}
        except Exception as e:
            return {"error": f"Go forward failed: {e}"}

    def get_text(self, selector: str) -> Dict[str, Any]:
        return self._submit(self._do_get_text, selector)

    def _do_get_text(self, selector) -> Dict[str, Any]:
        page = self._page
        try:
            text = page.text_content(selector, timeout=5000)
            return {"text": text or ""}
        except Exception as e:
            return {"error": f"Get text failed: {e}"}

    def evaluate(self, script: str) -> Dict[str, Any]:
        return self._submit(self._do_evaluate, script)

    def _do_evaluate(self, script) -> Dict[str, Any]:
        page = self._page
        try:
            result = page.evaluate(script)
            return {"result": result}
        except Exception as e:
            # page.evaluate 接收的是一个表达式，因此按函数体书写的脚本
            # 若在顶层 return 就会失败。这里把它包进函数即可——
            # 反正调用方下一步也会这么做。
            if "Illegal return statement" in str(e):
                try:
                    return {"result": page.evaluate("(() => {\n%s\n})()" % script)}
                except Exception as retry_error:
                    e = retry_error
            return {"error": f"Evaluate failed: {e}"}

    def press(self, key: str) -> Dict[str, Any]:
        return self._submit(self._do_press, key)

    def _do_press(self, key) -> Dict[str, Any]:
        page = self._page
        try:
            page.keyboard.press(key)
            page.wait_for_timeout(300)
            return {"pressed": key}
        except Exception as e:
            return {"error": f"Press failed: {e}"}

    # ------------------------------------------------------------------
    # 帮手
    # ------------------------------------------------------------------

    def _get_screenshot_dir(self, cwd: str = "") -> str:
        if self._screenshot_dir and os.path.isdir(self._screenshot_dir):
            return self._screenshot_dir
        base = cwd or os.getcwd()
        d = os.path.join(base, "tmp")
        os.makedirs(d, exist_ok=True)
        self._screenshot_dir = d
        return d
