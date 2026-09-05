"""
search_files tool - search inside workspace files, or find files by name.

Two questions, one tool: target='content' greps file contents, target='files'
matches file names. They are packaged together because "find the thing" is one
intent from the model's point of view, and because a tool named `grep` never
cued the model to try it for a filename lookup - it would burn turns grepping
for the name, then fall back to shelling out to `find`.

The name-matching path is plain Python (see _find_by_name). Everything below
concerns content search.

Backend strategy (4-tier, first available wins):
    1. ripgrep (rg)               - fastest; respects .gitignore natively
    2. grep -E                    - POSIX systems always have it
    3. PowerShell Select-String   - Windows without rg/grep (.NET regex)
    4. pure Python (os.walk + re) - last-resort fallback, always works

The external backends (1-3) keep search fast on every platform that ships a
real search tool; the pure-Python tier guarantees the tool still returns
results on a bare Windows box where none of them exist (that was the original
motivation for this tool). Only tier 1 honors .gitignore; all tiers additionally
skip a fixed VCS/dependency directory denylist so results stay comparable across
backends. no_ignore=true lifts both. A search that finds nothing while such a
directory is present says so, naming it - which is the only time the exclusion
is worth a word.
"""

import fnmatch
import os
import shutil
import subprocess
import sys
import time
from typing import Dict, Any, List, Tuple

import regex as re  # 用的是第三方 regex，而非标准库 re：.search() 需要真正的单次调用超时，stdlib re 做不到

from agent.tools.base_tool import BaseTool, ToolResult
from agent.tools.utils.truncate import truncate_line
from common.log import logger
from common.utils import expand_path

# 各后端方法的简短标签，会出现在调试日志里，
# 排查与平台相关的问题时可借此看出是哪个搜索引擎在运行。
_BACKEND_LABELS = {
    "_backend_rg": "rg",
    "_backend_grep": "grep",
    "_backend_powershell": "powershell",
    "_backend_python": "python",
}

DEFAULT_MAX_RESULTS = 50
MAX_RESULTS_CAP = 500
MAX_FILE_BYTES = 2 * 1024 * 1024
SEARCH_TIMEOUT_SECONDS = 30
REGEX_MATCH_TIMEOUT_SECONDS = 1  # python 后端中单次 regex.search() 调用的超时上限

_IS_WIN = sys.platform == "win32"

# 与 read.py 中 #2913 的修复保持一致：/proc/<pid|self|thread-self>/environ
# 会把 ~/.cow/.env 里的机密镜像到进程环境中。
_PROC_ENVIRON_RE = re.compile(r"^/proc/(\d+|self|thread-self)/environ$")

# VCS 与依赖/构建目录会被非 rg 的后端排除（rg 则依据
# .gitignore）。该清单与 rg 按项目 .gitignore 通常跳过的内容
# 保持同步，从而保证各后端结果可比。
_SKIP_DIR_NAMES = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".next",
    "target", "vendor", ".tox", "coverage", ".idea",
}

def _pruned_dirs(root: str, max_depth: int = 2) -> List[str]:
    """Denylisted directory names actually present under ``root``.

    The external backends prune inside their own subprocess and cannot report
    back, so we look for ourselves. Only called on an empty result, and only a
    couple of levels deep - which is where these directories sit in practice.
    """
    start = root if os.path.isdir(root) else os.path.dirname(root)
    found = set()

    def scan(path: str, depth: int) -> None:
        try:
            entries = list(os.scandir(path))
        except OSError:
            return
        for entry in entries:
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if entry.name in _SKIP_DIR_NAMES:
                found.add(entry.name)
            elif depth < max_depth:
                scan(entry.path, depth + 1)

    scan(start, 1)
    return sorted(found)


class SearchFiles(BaseTool):
    """Tool for searching file contents by pattern across a directory tree."""

    name: str = "search_files"
    description: str = (
        "Search file contents, or find files by name. Prefer this over running "
        "grep/rg/find in the bash tool.\n"
        "Content search (target='content', default): regex search inside files, returning "
        "matching lines with their file path and line number. Narrow with file_glob, "
        "choose the result shape with output_mode.\n"
        "File search (target='files'): find files by a name glob such as '*.py' or "
        "'*report*', recursively under path, ordered most-recently-modified first."
    )

    params: dict = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex to search for inside files, or - when target='files' - a glob matched against the file name, e.g. '*.py' or '*report*'."
            },
            "target": {
                "type": "string",
                "enum": ["content", "files"],
                "description": "'content' searches inside files (default); 'files' finds files by name."
            },
            "path": {
                "type": "string",
                "description": "File or directory to search in (default: workspace root). Relative paths are based on the workspace directory."
            },
            "file_glob": {
                "type": "string",
                "description": "Glob to filter which files are searched, e.g. '*.py' or '*.{ts,tsx}' (default: all files)."
            },
            "output_mode": {
                "type": "string",
                "enum": ["content", "files", "count"],
                "description": "content = matching lines with line numbers (default); files = only file paths that contain a match; count = number of matches per file."
            },
            "ignore_case": {
                "type": "boolean",
                "description": "Case-insensitive match (default false)."
            },
            "no_ignore": {
                "type": "boolean",
                "description": "When true, search everywhere: files ignored via .gitignore, plus dependency/build directories (node_modules, dist, vendor, .venv, ...) that are skipped by default. Default false."
            },
            "max_results": {
                "type": "integer",
                "description": f"Maximum number of results to return (default: {DEFAULT_MAX_RESULTS}, capped at {MAX_RESULTS_CAP})."
            }
        },
        "required": ["pattern"]
    }

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd", os.getcwd())
        self.timeout = self.config.get("timeout", SEARCH_TIMEOUT_SECONDS)
        # 路径只解析一次（假定 ~/.cow 在本次会话内固定不变），不必每次都重算。
        self._cow_dir = os.path.realpath(expand_path("~/.cow")).replace(os.sep, "/")

    # --------------------------------------------------------- 文件名搜索
    def _find_by_name(self, pattern: str, root: str, ignore_case: bool,
                      no_ignore: bool, max_results: int) -> ToolResult:
        """Find files whose name matches a glob.

        Answers "where is that file?", which content search cannot: grepping for
        a filename only finds files that mention it, not the file itself.

        Pure Python rather than shelling out to find/rg: the tree walk is the
        cheap part, and it keeps the denylist and result ordering identical on
        every platform.

        Results are ordered most-recently-modified first - when several files
        match, the one just worked on is almost always the one wanted.
        """
        matcher = fnmatch.fnmatch if ignore_case else fnmatch.fnmatchcase
        # 不带通配符的模式（比如 “report”）通常意味着“名称中包含 report”，
        # 而非精确匹配某个文件名；否则这类模式会匹配不到
        # 任何文件，看起来就像文件不存在一样。
        if not any(ch in pattern for ch in "*?["):
            pattern = f"*{pattern}*"

        deadline = time.monotonic() + self.timeout
        hits = []
        timed_out = False

        if os.path.isfile(root):
            walk_root, only = os.path.dirname(root), os.path.basename(root)
        else:
            walk_root, only = root, None

        for dirpath, dirnames, filenames in os.walk(walk_root):
            if time.monotonic() > deadline:
                timed_out = True
                break
            kept = []
            for d in dirnames:
                if d in _SKIP_DIR_NAMES and not no_ignore:
                    continue
                if self._is_credential_path(os.path.join(dirpath, d)):
                    continue
                kept.append(d)
            dirnames[:] = sorted(kept)

            for filename in filenames:
                if only and filename != only:
                    continue
                if not matcher(filename, pattern):
                    continue
                full = os.path.join(dirpath, filename)
                if self._is_credential_path(full):
                    continue
                try:
                    mtime = os.path.getmtime(full)
                except OSError:
                    continue
                hits.append((mtime, self._rel(full, root)))

        hits.sort(key=lambda h: (-h[0], h[1]))
        files = [rel for _, rel in hits[:max_results]]

        payload = {"files": files, "match_count": len(files)}
        notices = []
        if len(hits) > max_results:
            notices.append(
                f"{len(hits)} files matched, showing the {max_results} most recently "
                f"modified. Narrow `pattern` or `path`, or raise max_results."
            )
        if timed_out:
            notices.append(
                f"Search stopped after {self.timeout}s - results may be incomplete. "
                f"Narrow `path`."
            )
        if not files and not no_ignore:
            pruned = _pruned_dirs(root)
            if pruned:
                notices.append(
                    f"Skipped {', '.join(pruned)}. Use no_ignore=true to search them too."
                )
        if notices:
            payload["notice"] = " ".join(notices)
        return ToolResult.success(payload)

    # ------------------------------------------------------------------ 执行
    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """Execute a content search. See params for arguments.

        Returns a ToolResult whose payload shape depends on output_mode:
          content -> {matches: [{file, line, match}], match_count, notice?}
          files   -> {files: [path, ...], match_count, notice?}
          count   -> {counts: [{file, count}], match_count, notice?}
        """
        pattern = args.get("pattern", "")
        if not isinstance(pattern, str) or not pattern:
            return ToolResult.fail("Error: pattern parameter is required")

        target = args.get("target", "content") or "content"
        if target not in ("content", "files"):
            return ToolResult.fail(f"Error: target must be content/files, got: {target!r}")

        path = args.get("path", ".") or "."
        file_glob = args.get("file_glob", "*") or "*"
        if not isinstance(file_glob, str):
            return ToolResult.fail(f"Error: file_glob must be a string, got: {file_glob!r}")

        output_mode = args.get("output_mode", "content") or "content"
        if output_mode not in ("content", "files", "count"):
            return ToolResult.fail(f"Error: output_mode must be content/files/count, got: {output_mode!r}")

        ignore_case = bool(args.get("ignore_case", False))
        no_ignore = bool(args.get("no_ignore", False))

        max_results = args.get("max_results", DEFAULT_MAX_RESULTS)
        if isinstance(max_results, float) and not max_results.is_integer():
            return ToolResult.fail(f"Error: max_results must be an integer, got: {max_results!r}")
        try:
            max_results = int(max_results)
        except (TypeError, ValueError):
            return ToolResult.fail(f"Error: max_results must be an integer, got: {max_results!r}")
        if max_results <= 0:
            return ToolResult.fail("Error: max_results must be a positive integer")
        max_results = min(max_results, MAX_RESULTS_CAP)

        # 提前校验正则表达式，让有问题的模式在每种后端下都以同样的方式
        # 失败（否则外部工具会各自输出自己的错误文本）。
        # 文件模式下 pattern 是 glob，而非正则表达式。
        if target == "content":
            try:
                re.compile(pattern)
            except re.error as e:
                return ToolResult.fail(f"Error: invalid regex pattern: {e}")

        root = self._resolve_path(path)
        if self._is_credential_path(root):
            return ToolResult.fail(
                "Error: Access denied. API keys and credentials must be accessed through the env_config tool only."
            )
        if not os.path.exists(root):
            return ToolResult.fail(
                f"Error: path not found: {path}\nResolved to: {root}\n"
                f"Hint: Relative paths are based on workspace ({self.cwd}). For directories outside workspace, use absolute paths."
            )

        if target == "files":
            return self._find_by_name(pattern, root, ignore_case, no_ignore, max_results)

        opts = _SearchOptions(
            pattern=pattern, root=root, file_glob=file_glob,
            output_mode=output_mode, ignore_case=ignore_case,
            no_ignore=no_ignore, max_results=max_results, deadline=time.monotonic() + self.timeout,
        )

        backend = self._pick_backend()
        used = _BACKEND_LABELS.get(backend.__name__, backend.__name__)
        try:
            outcome = backend(opts)
        except Exception as e:
            # 非 python 后端的故障会统一改由 python 兜底，这样工具不会
            # 仅仅因为外部可执行文件行为异常就直接硬失败。
            if backend is not self._backend_python:
                logger.warning(f"[SearchFiles] backend '{used}' failed ({e}); falling back to python")
                used = "python(fallback)"
                outcome = self._backend_python(opts)
            else:
                return ToolResult.fail(f"Error searching files: {e}")

        logger.debug(f"[SearchFiles] backend={used} mode={opts.output_mode} matches={len(outcome.rows)}")
        return self._format(outcome, opts)

    # ------------------------------------------------------------- 后端选择
    def _pick_backend(self):
        """Return the best available backend callable for this machine."""
        if shutil.which("rg"):
            return self._backend_rg
        if not _IS_WIN and shutil.which("grep"):
            return self._backend_grep
        if _IS_WIN and (shutil.which("powershell") or shutil.which("pwsh")):
            return self._backend_powershell
        return self._backend_python

    # ------------------------------------------------------------------ 帮助者
    def _resolve_path(self, path: str) -> str:
        """Resolve to absolute path (same convention as read/ls/write, no workspace jail)."""
        path = expand_path(path)
        if os.path.isabs(path):
            return path
        return os.path.abspath(os.path.join(self.cwd, path))

    def _is_credential_path(self, absolute_path: str) -> bool:
        """Block ~/.cow (like ls.py) and /proc/*/environ (like read.py #2913)."""
        candidates = set()
        try:
            candidates.add(os.path.normpath(absolute_path).replace(os.sep, "/"))
            candidates.add(os.path.realpath(absolute_path).replace(os.sep, "/"))
        except OSError:
            candidates.add(absolute_path.replace(os.sep, "/"))
        for candidate in candidates:
            if _PROC_ENVIRON_RE.match(candidate):
                return True
        return any(c == self._cow_dir or c.startswith(self._cow_dir + "/") for c in candidates)

    def _rel(self, file_path: str, root: str) -> str:
        # 一律输出正斜杠，保证跨平台路径一致（Windows 下
        # os.path.relpath 会产生 'sub\\b.py'），同时可安全回传给
        # 读取/编辑等工具，它们都接受 “/”。
        try:
            base = root if os.path.isdir(root) else os.path.dirname(root)
            rel = os.path.relpath(file_path, base)
        except ValueError:
            rel = file_path
        return rel.replace(os.sep, "/")

    # ------------------------------------------------------------- rg 后端
    def _backend_rg(self, opts: "_SearchOptions") -> "_BackendResult":
        cmd = ["rg", "--line-number", "--no-heading", "--with-filename", "--color", "never"]
        # 排除与其它后端硬编码相同的 VCS/依赖目录，这样即使
        # 仓库没有 .gitignore，各后端结果也一致（否则只有 rg
        # 会跳过 .gitignore 列出的内容）。
        if not opts.no_ignore:
            for d in _SKIP_DIR_NAMES:
                cmd += ["--glob", f"!{d}"]
        cmd += ["--max-columns", "1000"]
        if opts.ignore_case:
            cmd.append("-i")
        if opts.no_ignore:
            cmd.append("--no-ignore")
        if opts.file_glob and opts.file_glob != "*":
            cmd += ["--glob", opts.file_glob]
        if opts.output_mode == "files":
            cmd.append("-l")
        elif opts.output_mode == "count":
            cmd.append("-c")
        # `--` 用于防止以破折号开头的模式被当作参数。
        cmd += ["-e", opts.pattern, "--", opts.root]
        rows, timed_out = self._run_external(cmd, opts)
        return _BackendResult(rows, timed_out)

    # ------------------------------------------------------------ grep 后端
    def _backend_grep(self, opts: "_SearchOptions") -> "_BackendResult":
        # -H：即使目标是单个文件也强制带文件名；-r：递归；-E = ERE
        # （使“或”与量词语法对齐 rg）。-n 只在内容模式下追加，
        # 与 -c/-l 混用会破坏它们的输出。
        cmd = ["grep", "-rH", "-E"]
        if not opts.no_ignore:
            for d in _SKIP_DIR_NAMES:
                cmd.append(f"--exclude-dir={d}")
        if opts.ignore_case:
            cmd.append("-i")
        if opts.file_glob and opts.file_glob != "*":
            cmd.append(f"--include={opts.file_glob}")
        if opts.output_mode == "files":
            cmd.append("-l")
        elif opts.output_mode == "count":
            cmd.append("-c")
        else:
            cmd.append("-n")
        cmd += ["-e", opts.pattern, opts.root]
        rows, timed_out = self._run_external(cmd, opts)
        return _BackendResult(rows, timed_out)

    # ------------------------------------------------ powershell 后端 (win)
    def _backend_powershell(self, opts: "_SearchOptions") -> "_BackendResult":
        shell = shutil.which("powershell") or shutil.which("pwsh")
        # Select-String 没有 grep -l/-c 这类按模式输出的标志，因此它
        # 一律输出 `path:line:content`；文件/计数结果由 _parse_powershell
        # 据此汇总（而非共享的 _parse_lines——后者的文件/计数解析器
        # 是按 grep 原生输出形状写的）。路径与 line:content 之间显式加 \t，
        # 这样 Windows 盘符冒号 (C:\...) 永远不会被
        # 误当成字段分隔符。
        ci = "-CaseSensitive" if not opts.ignore_case else ""
        glob_filter = ""
        if opts.file_glob and opts.file_glob != "*":
            glob_filter = f"-Filter '{opts.file_glob}' "
        prune = "" if opts.no_ignore else (
            f"| Where-Object {{ $_.FullName -notmatch '\\\\({'|'.join(_SKIP_DIR_NAMES)})\\\\' }} "
        )
        script = (
            # 在标准输出上强制使用 UTF-8，好让非 ASCII 文件名/内容能
            # 正确进入我们的子进程读取端（Windows PowerShell 默认使用系统
            # 代码页，如 cp936，会被我们误当作 UTF-8 解码 → 乱码）。
            f"[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
            f"$ErrorActionPreference='SilentlyContinue';"
            f"Get-ChildItem -LiteralPath '{opts.root}' -Recurse -File {glob_filter}"
            f"{prune}"
            f"| Select-String -Pattern @'\n{opts.pattern}\n'@ {ci} "
            f"| ForEach-Object {{ \"$($_.Path)`t$($_.LineNumber):$($_.Line)\" }}"
        )
        cmd = [shell, "-NoProfile", "-NonInteractive", "-Command", script]
        remaining = max(0.1, opts.deadline - time.monotonic())
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=remaining,
            )
        except subprocess.TimeoutExpired:
            return _BackendResult([], True)
        rows = self._parse_powershell((proc.stdout or "").splitlines(), opts)
        return _BackendResult(rows, False)

    def _parse_powershell(self, lines: List[str], opts: "_SearchOptions") -> List[dict]:
        """Parse Select-String's `path\\tline:content` and aggregate into the
        shape output_mode asks for. The tab guards against ':' inside a Windows
        path (drive letter); line:content is split on the first ':' after it."""
        content_rows: List[dict] = []
        counts: Dict[str, int] = {}
        for line in lines:
            if not line or "\t" not in line:
                continue
            path_part, rest = line.split("\t", 1)
            head, sep, body = rest.partition(":")
            if not sep or not head.isdigit():
                continue
            rel = self._rel(path_part, opts.root)
            counts[rel] = counts.get(rel, 0) + 1
            truncated, _ = truncate_line(body)
            content_rows.append({"file": rel, "line": int(head), "match": truncated})

        if opts.output_mode == "files":
            seen = []
            for r in content_rows:
                if r["file"] not in seen:
                    seen.append(r["file"])
            rows = [{"file": f} for f in sorted(seen)]
        elif opts.output_mode == "count":
            rows = [{"file": f, "count": c} for f, c in sorted(counts.items())]
        else:
            content_rows.sort(key=lambda r: (r["file"], r["line"]))
            rows = content_rows
        return rows[:opts.max_results]

    # ----------------------------------------------- 外部运行器 + 解析器
    def _run_external(self, cmd: List[str], opts: "_SearchOptions") -> Tuple[List[dict], bool]:
        remaining = max(0.1, opts.deadline - time.monotonic())
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=remaining,
            )
        except subprocess.TimeoutExpired:
            return [], True
        # 无论退出码如何都解析标准输出：rg/grep 在“无匹配”时会以退出码 1 结束
        # （stdout 为空 → 空行，这正是期望的结果）。真正出错（退出码 > 1）
        # 时的诊断信息可能打印在 stdout 上，会在 _parse_lines 里被丢弃。
        stdout = proc.stdout or ""
        rows = self._parse_lines(stdout.splitlines(), opts)
        return rows, False

    def _parse_lines(self, lines: List[str], opts: "_SearchOptions") -> List[dict]:
        """Parse `path:line:content` (content) / `path` (files) / `path:count`
        (count) output shared by rg, grep and the PowerShell shim. Drops the
        backend's own diagnostic lines (rg:/grep: prefixes) so they never reach
        the model."""
        rows: List[dict] = []
        for line in lines:
            if not line or line.startswith(("rg:", "grep:")):
                continue
            if opts.output_mode == "files":
                p = line.strip()
                if p:
                    rows.append({"file": self._rel(p, opts.root)})
                continue
            if opts.output_mode == "count":
                # path:count —— 从右侧切分，以容忍路径里出现 “:”。
                # grep -c 会对每个扫描过的文件都输出一行，包括计数为 0 的；
                # 而 rg -c 只列出有匹配的文件，因此去掉 0 计数行使两者对齐。
                head, sep, tail = line.rpartition(":")
                if sep and tail.isdigit() and int(tail) > 0:
                    rows.append({"file": self._rel(head, opts.root), "count": int(tail)})
                continue
            # 内容模式：路径：行：内容
            first = line.find(":")
            second = line.find(":", first + 1)
            if first == -1 or second == -1:
                continue
            file_part = line[:first]
            line_no = line[first + 1:second]
            content = line[second + 1:]
            if not line_no.isdigit():
                continue
            truncated, _ = truncate_line(content)
            rows.append({
                "file": self._rel(file_part, opts.root),
                "line": int(line_no),
                "match": truncated,
            })
        # 跨后端的确定性顺序。
        if opts.output_mode == "content":
            rows.sort(key=lambda r: (r["file"], r["line"]))
        else:
            rows.sort(key=lambda r: r["file"])
        return rows[:opts.max_results]

    # ------------------------------------------------------- python 后备
    def _backend_python(self, opts: "_SearchOptions") -> "_BackendResult":
        flags = re.IGNORECASE if opts.ignore_case else 0
        compiled = re.compile(opts.pattern, flags)
        rows: List[dict] = []
        pattern_timeout = False
        root = opts.root

        walk_root = root if os.path.isdir(root) else os.path.dirname(root)
        single_file = None if os.path.isdir(root) else os.path.basename(root)

        for dirpath, dirnames, filenames in os.walk(walk_root):
            kept = []
            for d in dirnames:
                if d in _SKIP_DIR_NAMES and not opts.no_ignore:
                    continue
                if self._is_credential_path(os.path.join(dirpath, d)):
                    continue
                kept.append(d)
            dirnames[:] = sorted(kept)

            for filename in sorted(filenames):
                if single_file and filename != single_file:
                    continue
                if len(rows) >= opts.max_results:
                    return _BackendResult(self._python_finalize(rows, opts), False, pattern_timeout)
                if time.monotonic() >= opts.deadline:
                    return _BackendResult(self._python_finalize(rows, opts), True, pattern_timeout)
                if opts.file_glob and opts.file_glob != "*" and not fnmatch.fnmatch(filename, opts.file_glob):
                    continue
                fp = os.path.join(dirpath, filename)
                if self._is_credential_path(fp):
                    continue
                file_rows, hit_deadline, hit_pattern_timeout = self._python_scan_file(fp, compiled, opts)
                rows.extend(file_rows)
                pattern_timeout = pattern_timeout or hit_pattern_timeout
                if hit_deadline:
                    return _BackendResult(self._python_finalize(rows, opts), True, pattern_timeout)

        return _BackendResult(self._python_finalize(rows, opts), False, pattern_timeout)

    def _python_scan_file(self, fp: str, compiled, opts: "_SearchOptions") -> Tuple[List[dict], bool, bool]:
        try:
            if os.path.getsize(fp) > MAX_FILE_BYTES:
                return [], False, False
        except OSError:
            return [], False, False
        try:
            with open(fp, "r", encoding="utf-8-sig") as f:
                content = f.read()
        except (UnicodeDecodeError, OSError):
            return [], False, False

        out: List[dict] = []
        count = 0
        for line_no, raw in enumerate(content.split("\n"), start=1):
            line = raw[:-1] if raw.endswith("\r") else raw
            if time.monotonic() >= opts.deadline:
                return out, True, False
            try:
                matched = compiled.search(line, timeout=REGEX_MATCH_TIMEOUT_SECONDS)
            except TimeoutError:
                # 返回该文件已扫到的结果，但打上超时标记，以便调用方
                # 提醒模型：结果可能不完整。
                return out, False, True
            if matched:
                count += 1
                if opts.output_mode == "content":
                    truncated, _ = truncate_line(line)
                    out.append({"file": self._rel(fp, opts.root), "line": line_no, "match": truncated})
                elif opts.output_mode == "files":
                    out.append({"file": self._rel(fp, opts.root)})
                    break
        if opts.output_mode == "count" and count:
            out.append({"file": self._rel(fp, opts.root), "count": count})
        return out, False, False

    @staticmethod
    def _python_finalize(rows: List[dict], opts: "_SearchOptions") -> List[dict]:
        if opts.output_mode == "content":
            rows.sort(key=lambda r: (r["file"], r["line"]))
        else:
            rows.sort(key=lambda r: r["file"])
        return rows[:opts.max_results]

    # ------------------------------------------------------------- 格式
    def _format(self, outcome: "_BackendResult", opts: "_SearchOptions") -> ToolResult:
        rows = outcome.rows
        notices: List[str] = []
        if opts.output_mode == "files":
            payload = {"files": [r["file"] for r in rows], "match_count": len(rows)}
        elif opts.output_mode == "count":
            payload = {"counts": rows, "match_count": sum(r.get("count", 0) for r in rows)}
        else:
            payload = {"matches": rows, "match_count": len(rows)}

        if len(rows) >= opts.max_results:
            if opts.max_results >= MAX_RESULTS_CAP:
                notices.append(f"{opts.max_results} result limit reached (hard maximum). Narrow `path` or `file_glob`.")
            else:
                notices.append(
                    f"{opts.max_results} result limit reached. "
                    f"Use max_results={min(opts.max_results * 2, MAX_RESULTS_CAP)} to see more."
                )
        if outcome.timed_out:
            notices.append(
                f"Search stopped after {self.timeout}s — results may be incomplete. "
                f"Narrow `path` or `file_glob`."
            )
        if outcome.pattern_timeout:
            notices.append(
                f"Pattern took longer than {REGEX_MATCH_TIMEOUT_SECONDS}s on a line in one or more "
                f"files — the rest of that file was not searched. Results may be incomplete. "
                f"Simplify `pattern` to avoid catastrophic backtracking."
            )
        # 只有结果为空、且拒绝名单中的目录确实存在时才值得提醒用户，
        # 否则每次调用都会产生噪音；而目录树里根本没有这类目录时，
        # 提示“已跳过某些目录”就完全与事实不符了。
        if not rows and not opts.no_ignore:
            pruned = _pruned_dirs(opts.root)
            if pruned:
                notices.append(
                    f"Skipped {', '.join(pruned)}. Use no_ignore=true to search them too."
                )
        if notices:
            payload["notice"] = " ".join(notices)
        return ToolResult.success(payload)


class _BackendResult:
    """What a backend returns: rows plus the signals _format turns into notices."""
    __slots__ = ("rows", "timed_out", "pattern_timeout")

    def __init__(self, rows, timed_out=False, pattern_timeout=False):
        self.rows = rows
        self.timed_out = timed_out
        self.pattern_timeout = pattern_timeout


class _SearchOptions:
    """Plain container for a single search invocation's resolved options."""
    __slots__ = ("pattern", "root", "file_glob", "output_mode",
                 "ignore_case", "no_ignore", "max_results", "deadline")

    def __init__(self, pattern, root, file_glob, output_mode,
                 ignore_case, no_ignore, max_results, deadline):
        self.pattern = pattern
        self.root = root
        self.file_glob = file_glob
        self.output_mode = output_mode
        self.ignore_case = ignore_case
        self.no_ignore = no_ignore
        self.max_results = max_results
        self.deadline = deadline
