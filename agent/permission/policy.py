"""Permission modes: how much a session is allowed to change.

Three modes, ordered from most to least restrictive:

- ``read-only``       Look, don't touch. File writes are refused, shell commands
                      are limited to an allowlist of read-only utilities, and
                      tool actions with side effects (browser clicks, scheduler
                      writes, env edits) are refused.
- ``workspace-write`` Free rein inside the session's working directory (the
                      project, plus the Agent's own state dir and the system
                      temp dir); writes that land outside it are refused.
                      Reading anywhere is still allowed.
- ``full-access``     No confinement. The historical behavior, kept as the
                      default so existing installs are untouched.

The mode is resolved per session (see ``agent.workspace.session_prefs``) and
falls back to the global ``agent_permission_mode`` setting.

Scope, and honesty about it: these checks are argument-level, not an OS sandbox.
``write``/``edit`` are exact - the target path is a parameter we resolve. ``bash``
is best effort: we parse the command line and refuse the recognizable
out-of-scope cases (redirects, ``rm``/``mv`` outside the roots, privilege
escalation), but a program the shell starts can still write wherever the OS lets
it. The UI says as much; anyone who needs a hard boundary wants a container.
"""

from __future__ import annotations

import os
import re
import shlex
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

READ_ONLY = "read-only"
WORKSPACE_WRITE = "workspace-write"
FULL_ACCESS = "full-access"

MODES: Tuple[str, ...] = (READ_ONLY, WORKSPACE_WRITE, FULL_ACCESS)

# 保留既有安装的行为：除非用户主动开启，否则不拦截任何操作。
# 全新安装则通过 config-template.json 提供更严格的默认值。
DEFAULT_MODE = FULL_ACCESS

CONFIG_KEY = "agent_permission_mode"

_ALIASES = {
    "readonly": READ_ONLY,
    "read_only": READ_ONLY,
    "ro": READ_ONLY,
    "workspace": WORKSPACE_WRITE,
    "workspace_write": WORKSPACE_WRITE,
    "workspacewrite": WORKSPACE_WRITE,
    "write": WORKSPACE_WRITE,
    "full": FULL_ACCESS,
    "full_access": FULL_ACCESS,
    "fullaccess": FULL_ACCESS,
    "danger-full-access": FULL_ACCESS,
    "all": FULL_ACCESS,
}

_IS_WIN = sys.platform == "win32"


def normalize_mode(value: Any, default: Optional[str] = None) -> str:
    """Coerce anything the API or config may hold into a known mode id."""
    fallback = default if default in MODES else DEFAULT_MODE
    if not isinstance(value, str):
        return fallback
    v = value.strip().lower()
    if v in MODES:
        return v
    return _ALIASES.get(v, fallback)


def global_mode() -> str:
    """The instance-wide default, used by sessions with no override."""
    try:
        from config import conf

        return normalize_mode(conf().get(CONFIG_KEY))
    except Exception:
        return DEFAULT_MODE


@dataclass
class Decision:
    """Outcome of a permission check."""

    allowed: bool
    reason: str = ""

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return self.allowed


ALLOW = Decision(True)


# ---------------------------------------------------------------------------
# 工具分类
# ---------------------------------------------------------------------------

# 这些工具唯一的作用，就是修改我们可从参数中解析出的路径所指向的文件。
_FILE_WRITE_TOOLS = frozenset({"write", "edit"})

# 这些工具的状态变更，用户在本对话之外也能察觉。
_MUTATING_TOOLS = frozenset({"evolution_undo"})

# 只有部分子操作会改动状态的工具：（参数名, 有副作用的取值）。
_ACTION_TOOLS: Dict[str, Tuple[str, frozenset]] = {
    # 在页面上点击、输入、按键、执行脚本等操作会改动页面状态；
    # 单纯的导航与阅读则不会。
    "browser": ("action", frozenset({"click", "fill", "select", "press", "evaluate"})),
    "scheduler": ("action", frozenset({"create", "delete", "enable", "disable"})),
    "env_config": ("action", frozenset({"set", "delete"})),
}

# 已知的内置工具均为只读，因此下面针对 MCP 名称的启发式
# 从不会命中第一方工具，只会用来推断那些陌生的工具名。
_KNOWN_TOOLS = frozenset({
    "read", "ls", "search_files", "memory_search", "memory_get", "web_search",
    "web_fetch", "vision", "send", "subagent", "bash", "write", "edit",
    "browser", "scheduler", "env_config", "evolution_undo",
})

# MCP 工具的名字我们从未见过，不能猜测“安全”，而要读动词：
# `create_issue` 明显会改动内容，`list_repos` 显然不会。
# 这一判断只用于只读模式。
_MUTATING_NAME_RE = re.compile(
    r"(?:^|[_\-.])(create|new|add|insert|write|update|edit|modify|patch|set|put|post|"
    r"delete|remove|drop|destroy|purge|clear|reset|rename|move|upload|publish|deploy|"
    r"send|submit|execute|exec|run|invoke|install|approve|merge|revoke|grant)"
    r"(?:$|[_\-.]|\d)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Shell命令分类
# ---------------------------------------------------------------------------

# 只读命令白名单。不在名单之列的命令在只读模式下都会被拒绝，
# 因此未知命令默认拦截。
_READ_ONLY_COMMANDS = frozenset({
    # 列出/阅读
    "ls", "ll", "cat", "bat", "head", "tail", "nl", "wc", "less", "more", "tree",
    "file", "stat", "du", "df", "basename", "dirname", "realpath", "readlink",
    "pwd", "echo", "printf", "which", "type", "whereis", "locate",
    # 搜索/比较
    "grep", "egrep", "fgrep", "rg", "ag", "ack", "find", "fd", "diff", "cmp",
    # 文本处理（这些仅通过重定向写入，该重定向被拒绝）
    "sort", "uniq", "cut", "paste", "join", "comm", "column", "tr", "awk", "sed",
    "jq", "yq", "xxd", "od", "strings", "fold", "rev", "expand", "unexpand",
    # 散列
    "md5", "md5sum", "sha1sum", "sha256sum", "shasum", "cksum",
    # 环境/系统检查
    "date", "cal", "whoami", "id", "groups", "hostname", "uname", "printenv",
    "locale", "uptime", "ps", "free", "vm_stat", "sysctl", "lsof", "netstat",
    "ifconfig", "ip", "dig", "nslookup", "host", "sw_vers", "arch",
    "true", "false", "test", "seq", "sleep", "tty",
    # 版本控制（子命令单独检查）
    "git",
    # Windows 命令外壳
    "dir", "findstr", "where", "ver", "systeminfo", "tasklist", "chdir", "cd",
})

# 仅读取存储库的 git 子命令。
_GIT_READ_SUBCOMMANDS = frozenset({
    "status", "log", "diff", "show", "branch", "tag", "remote", "ls-files",
    "ls-tree", "ls-remote", "rev-parse", "rev-list", "describe", "blame",
    "shortlog", "cat-file", "reflog", "grep", "whatchanged", "name-rev",
    "symbolic-ref", "count-objects", "verify-commit", "version", "help",
    "stash", "worktree", "notes", "config", "show-ref", "for-each-ref",
})

# 能让原本只读的 git 子命令变成写入操作的标志。
_GIT_WRITE_FLAGS = frozenset({
    "-d", "-D", "--delete", "-m", "-M", "--move", "-f", "--force", "--set-upstream",
    "--set-upstream-to", "--unset", "--unset-all", "--add", "--replace-all",
    "--edit", "-e", "--prune", "--rename", "--create", "-c", "-C", "--amend",
})

# 仅以“list”子形式执行时才为只读的 git 子命令。
_GIT_LIST_ONLY = {"stash": "list", "worktree": "list", "notes": "list"}

# `git config` 只有带上了这些标志之一时才是只读操作。
_GIT_CONFIG_READ_FLAGS = frozenset({
    "--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l",
})

# 在命令行给出的路径上创建、删除或覆盖文件的命令。
# 工作区可写模式据此把改动约束在各根目录之内。
# 包管理器被有意排除：`pip install` 会按设计写入工作空间
# 之外的位置，拦下它反而会破坏正常的工作流，
# 而这种模式从未承诺强制这类边界。
_PATH_MUTATING_COMMANDS = frozenset({
    "rm", "rmdir", "unlink", "mv", "cp", "rsync", "install", "dd", "truncate",
    "shred", "ln", "mkdir", "touch", "chmod", "chown", "chgrp", "chflags",
    "tee", "sed", "zip", "unzip", "tar", "gzip", "gunzip", "del", "erase",
    "move", "copy", "ren", "rename", "md", "rd",
})

# 对这些命令，只有目的地（最后一个参数）会被写入；
# 从工作区外部读取源文件是允许的。
_DESTINATION_ONLY_COMMANDS = frozenset({
    "cp", "copy", "rsync", "install", "ln", "unzip", "tar", "zip",
})

# 权限提升操作在任何受限模式下都不被允许。
_ESCALATION_COMMANDS = frozenset({"sudo", "doas", "su", "runas", "pkexec"})

# 用于运行另一个命令的包装命令，其后才是真正要执行的命令。
_WRAPPER_COMMANDS = frozenset({
    "env", "nohup", "time", "timeout", "nice", "ionice", "stdbuf", "xargs",
    "command", "builtin", "exec", "watch", "setsid",
})

# 重定向到这些目标，并不算写入真实文件。
_NULL_SINKS = frozenset({
    "/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "/dev/fd/1", "/dev/fd/2",
    "nul", "NUL", "con", "CON",
})

# 用于结束一条命令、开启下一条的分隔符。重定向运算符
# 被有意排除在外：它们归属于所附着的那条命令。
_SEPARATORS = frozenset({";", "&&", "||", "|", "&", "|&", "(", ")", "{", "}", "\n"})

_OPERATOR_CHARS = set("<>&|;()")


def _is_operator(token: str) -> bool:
    return bool(token) and all(ch in _OPERATOR_CHARS for ch in token)


def _parse_segments(command: str) -> Optional[List[List[str]]]:
    """Split a command line into per-command token lists, honoring quotes.

    ``punctuation_chars`` makes the lexer emit ``&&``, ``|``, ``>`` and friends
    as their own tokens while leaving quoted text alone, so ``grep "a|b"`` is one
    command and not two. Returns None when the line cannot be lexed at all.
    """
    lexer = shlex.shlex(command or "", posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None

    segments: List[List[str]] = []
    current: List[str] = []
    for token in tokens:
        if token in _SEPARATORS:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _command_name(tokens: Sequence[str]) -> Tuple[Optional[str], List[str]]:
    """Return ``(command, args)``, unwrapping ``VAR=x``/``env``/``nohup``/... .

    So ``env FOO=1 nohup rm -rf /`` is classified as ``rm``.
    """
    args = list(tokens)
    while args:
        head = args[0]
        if _is_operator(head):
            args = args[1:]
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", head):
            args = args[1:]
            continue
        name = os.path.basename(head).lower()
        if name.endswith(".exe"):
            name = name[:-4]
        if name in _WRAPPER_COMMANDS:
            args = args[1:]
            while args and args[0].startswith("-"):
                args = args[1:]
            continue
        return name, args[1:]
    return None, []


def _redirect_targets(tokens: Sequence[str]) -> List[str]:
    """Paths this command redirects output into (fd duplications excluded)."""
    targets: List[str] = []
    for i, token in enumerate(tokens):
        if ">" not in token or not _is_operator(token):
            continue
        if i + 1 >= len(tokens):
            continue
        target = tokens[i + 1]
        # `2>&1` / `>&-`：复制或关闭描述符，而不是文件。
        if "&" in token and (target.isdigit() or target == "-"):
            continue
        if _is_operator(target):
            continue
        targets.append(target)
    return targets


def _positional_paths(args: Sequence[str]) -> List[str]:
    """Non-flag operands, which for file commands are the paths it touches."""
    out: List[str] = []
    skip_next = False
    for i, token in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if _is_operator(token):
            skip_next = True  # 它的操作数属于重定向
            continue
        if token.startswith("-"):
            continue
        nxt = args[i + 1] if i + 1 < len(args) else None
        # 紧挨着重定向符之前的裸 fd 编号（如 `2> log`）不是路径。
        if token.isdigit() and nxt and _is_operator(nxt):
            continue
        out.append(token)
    return out


# ---------------------------------------------------------------------------
# 路径约束
# ---------------------------------------------------------------------------

def _real(path: str, cwd: Optional[str]) -> str:
    expanded = os.path.expanduser(os.path.expandvars(path))
    if not os.path.isabs(expanded):
        expanded = os.path.join(cwd or os.getcwd(), expanded)
    return os.path.realpath(expanded)


def _normalize_roots(roots: Optional[Iterable[str]], cwd: Optional[str]) -> List[str]:
    """Absolute, de-duplicated write roots, always including cwd and temp."""
    out: List[str] = []
    for root in list(roots or []) + [cwd, tempfile.gettempdir()]:
        if not root:
            continue
        try:
            real = os.path.realpath(os.path.expanduser(root))
        except Exception:
            continue
        if real and real not in out:
            out.append(real)
    return out


def _inside_roots(path: str, roots: Sequence[str], cwd: Optional[str]) -> bool:
    real = _real(path, cwd)
    for root in roots:
        try:
            if os.path.commonpath([root, real]) == root:
                return True
        except ValueError:
            # Windows 上的不同驱动器：根本不在这个根目录内。
            continue
    return False


def _roots_hint(roots: Sequence[str]) -> str:
    return ", ".join(roots[:2]) if roots else "the working directory"


# ---------------------------------------------------------------------------
# 拒绝
# ---------------------------------------------------------------------------

def _switch_hint() -> str:
    """One line telling the model what to do, without a UI location that could
    mislead a channel user.

    The permission selector lives in the console — the desktop app or the Web
    console — so a user chatting through a channel (WeChat, Telegram, ...)
    cannot see anything "under the chat input". We name the console by build so
    the model can point the user to the right place, and keep it short.
    """
    where = "the desktop app" if os.environ.get("COW_DESKTOP") == "1" else "the Web console"
    return (
        f"To allow it, the user can change this session's permission in {where} "
        f"(or the global security setting). Do not retry the same call: use a "
        f"route the current mode allows, or tell the user which mode is needed."
    )


def _deny(what: str, mode: str) -> Decision:
    return Decision(False, f"Blocked by permission mode '{mode}': {what}\n\n{_switch_hint()}")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def check_tool_call(
    mode: str,
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
    cwd: Optional[str] = None,
    write_roots: Optional[Iterable[str]] = None,
) -> Decision:
    """Decide whether ``tool_name`` may run with ``arguments`` under ``mode``.

    Args:
        mode: one of :data:`MODES`; anything else is normalized.
        tool_name: the tool being called.
        arguments: the call's arguments (paths, commands, actions).
        cwd: working directory that relative paths resolve against.
        write_roots: directories writes are confined to in workspace-write mode.
            ``cwd`` and the system temp dir are always included.

    Returns:
        A :class:`Decision` whose ``reason`` is written for the model: what was
        refused, and what to do instead.
    """
    mode = normalize_mode(mode)
    if mode == FULL_ACCESS:
        return ALLOW

    tool_name = (tool_name or "").strip()
    args = arguments if isinstance(arguments, dict) else {}

    if mode == READ_ONLY:
        return _check_read_only(tool_name, args)
    return _check_workspace_write(tool_name, args, cwd, write_roots)


def _check_read_only(tool_name: str, args: Dict[str, Any]) -> Decision:
    if tool_name in _FILE_WRITE_TOOLS:
        path = str(args.get("path") or "")
        return _deny(
            f"this session cannot modify files, so {tool_name} did not run"
            + (f" (target: {path})" if path else "")
            + ". Nothing was written.",
            READ_ONLY,
        )

    if tool_name in _MUTATING_TOOLS:
        return _deny(f"{tool_name} changes state, which this session cannot do.", READ_ONLY)

    if tool_name in _ACTION_TOOLS:
        arg_name, mutating = _ACTION_TOOLS[tool_name]
        action = str(args.get(arg_name) or "").strip().lower()
        if action in mutating:
            return _deny(
                f"the {tool_name} action '{action}' changes state; its read-only "
                f"actions are still available.",
                READ_ONLY,
            )
        return ALLOW

    if tool_name == "bash":
        return _check_bash_read_only(args)

    if tool_name not in _KNOWN_TOOLS and _MUTATING_NAME_RE.search(tool_name):
        return _deny(
            f"'{tool_name}' looks like it changes state (judged from its name) and "
            f"this session is read-only.",
            READ_ONLY,
        )

    return ALLOW


def _check_workspace_write(
    tool_name: str,
    args: Dict[str, Any],
    cwd: Optional[str],
    write_roots: Optional[Iterable[str]],
) -> Decision:
    roots = _normalize_roots(write_roots, cwd)

    if tool_name in _FILE_WRITE_TOOLS:
        path = str(args.get("path") or "")
        if path and not _inside_roots(path, roots, cwd):
            return _deny(
                f"'{path}' is outside the writable area ({_roots_hint(roots)}), so "
                f"{tool_name} did not run and nothing was written. Reading it is "
                f"still allowed.",
                WORKSPACE_WRITE,
            )
        return ALLOW

    if tool_name == "bash":
        return _check_bash_workspace_write(args, cwd, roots)

    return ALLOW


def _check_bash_read_only(args: Dict[str, Any]) -> Decision:
    command = str(args.get("command") or "").strip()
    if not command:
        # 空命令可能用于读取或结束代理自己启动的后台任务，故放行。
        return ALLOW

    segments = _parse_segments(command)
    if segments is None:
        return _deny(
            "this command could not be parsed, and an unparsable command cannot be "
            "confirmed read-only.",
            READ_ONLY,
        )

    for tokens in segments:
        real_targets = [t for t in _redirect_targets(tokens) if t not in _NULL_SINKS]
        if real_targets:
            return _deny(
                f"the command redirects output into '{real_targets[0]}', which writes "
                f"a file.",
                READ_ONLY,
            )

        name, rest = _command_name(tokens)
        if name is None:
            continue
        if name in _ESCALATION_COMMANDS:
            return _deny(f"'{name}' escalates privileges.", READ_ONLY)
        if name == "git":
            decision = _check_git_read_only(rest)
            if not decision.allowed:
                return decision
            continue
        if name == "sed" and any(a.startswith("-i") for a in rest):
            return _deny("'sed -i' edits files in place.", READ_ONLY)
        if name not in _READ_ONLY_COMMANDS:
            return _deny(
                f"'{name}' is not on the read-only command allowlist, so it may change "
                f"something. Reading files (read / ls / search_files / grep) and "
                f"fetching pages (web_fetch / web_search) still work.",
                READ_ONLY,
            )
    return ALLOW


def _check_git_read_only(args: Sequence[str]) -> Decision:
    positional = [a for a in args if not a.startswith("-") and not _is_operator(a)]
    sub = positional[0].lower() if positional else ""
    if not sub:
        return ALLOW
    if sub not in _GIT_READ_SUBCOMMANDS:
        return _deny(f"'git {sub}' can change the repository.", READ_ONLY)
    if sub in _GIT_LIST_ONLY:
        second = positional[1].lower() if len(positional) > 1 else ""
        if second != _GIT_LIST_ONLY[sub]:
            return _deny(f"only 'git {sub} {_GIT_LIST_ONLY[sub]}' is read-only.", READ_ONLY)
        return ALLOW
    if sub == "config":
        if not any(a in _GIT_CONFIG_READ_FLAGS for a in args):
            return _deny("'git config' without --get/--list can write config.", READ_ONLY)
        return ALLOW
    offending = [a for a in args if a in _GIT_WRITE_FLAGS]
    if offending:
        return _deny(f"'git {sub} {offending[0]}' modifies the repository.", READ_ONLY)
    return ALLOW


def _check_bash_workspace_write(
    args: Dict[str, Any], cwd: Optional[str], roots: Sequence[str]
) -> Decision:
    command = str(args.get("command") or "").strip()
    if not command:
        return ALLOW

    segments = _parse_segments(command)
    if segments is None:
        # 这种模式显然是尽力而为，因此无法解析的行会转到
        # shell 而不是阻塞工作，这可能没问题。
        return ALLOW

    for tokens in segments:
        for target in _redirect_targets(tokens):
            if target in _NULL_SINKS:
                continue
            if not _inside_roots(target, roots, cwd):
                return _deny(
                    f"the command writes to '{target}', outside the writable area "
                    f"({_roots_hint(roots)}).",
                    WORKSPACE_WRITE,
                )

        name, rest = _command_name(tokens)
        if name is None:
            continue
        if name in _ESCALATION_COMMANDS:
            return _deny(f"'{name}' escalates privileges.", WORKSPACE_WRITE)
        if name not in _PATH_MUTATING_COMMANDS:
            continue
        if name == "sed" and not any(a.startswith("-i") for a in rest):
            continue

        paths = _positional_paths(rest)
        if name == "dd":
            paths = [a.split("=", 1)[1] for a in rest if a.startswith("of=")]
        elif name in _DESTINATION_ONLY_COMMANDS:
            paths = paths[-1:] if len(paths) > 1 else []

        for path in paths:
            if not path or path in _NULL_SINKS:
                continue
            if not _inside_roots(path, roots, cwd):
                return _deny(
                    f"'{name}' would change '{path}', outside the writable area "
                    f"({_roots_hint(roots)}). Reading it is still allowed.",
                    WORKSPACE_WRITE,
                )
    return ALLOW


# ---------------------------------------------------------------------------
# 权限提示文本
# ---------------------------------------------------------------------------

def describe_mode(mode: str, language: str = "zh", cwd: Optional[str] = None) -> List[str]:
    """Prompt lines telling the model what it may change this session.

    Empty for full-access: with nothing gated there is nothing to say, and the
    historical prompt stays byte-identical.
    """
    mode = normalize_mode(mode)
    if mode == FULL_ACCESS:
        return []

    if language == "en":
        if mode == READ_ONLY:
            body = [
                "This session is **read-only**: you cannot modify files, and shell "
                "commands are limited to read-only utilities.",
                "",
                "- Investigating, reading and explaining are unaffected: `read`, `ls`, "
                "`search_files`, `web_search`, `web_fetch` and read-only shell "
                "commands all work.",
                "- Do not attempt writes. If the task needs them, say so and ask the "
                "user to switch this session's permission mode.",
            ]
        else:
            area = f"`{cwd}`" if cwd else "the working directory"
            body = [
                f"This session is **workspace-write**: you may freely create and change "
                f"files inside {area}.",
                "",
                "- Writes outside it are refused; reading anywhere is fine.",
                "- If the task genuinely needs to write elsewhere, explain why and let "
                "the user switch the permission mode.",
            ]
        return ["## 🔐 Permissions", ""] + body + [""]

    if mode == READ_ONLY:
        body = [
            "当前会话为**只读模式**：不能修改任何文件，命令行也仅限只读类命令。",
            "",
            "- 查看、分析、解释都不受影响：`read`、`ls`、`search_files`、`web_search`、"
            "`web_fetch` 以及只读命令均可正常使用。",
            "- 不要尝试写入。如果任务确实需要写入，请说明原因并提示用户切换该会话的权限模式。",
        ]
    else:
        area = f"`{cwd}`" if cwd else "当前工作目录"
        body = [
            f"当前会话为**工作区可写模式**：可以在 {area} 内自由创建和修改文件。",
            "",
            "- 该目录之外的写入会被拒绝；读取不受限制。",
            "- 如果任务确实需要写到其他位置，请说明原因，由用户切换权限模式。",
        ]
    return ["## 🔐 权限", ""] + body + [""]
