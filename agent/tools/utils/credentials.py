"""
Shared credential-path guard for file tools.

The agent's API keys live in ~/.cow/.env and must only ever be reached through
the env_config tool. Every tool that can surface file contents to the model has
to apply the same check - guarding only the read tool leaves the others as
bypasses (a successful edit, for example, returns a diff containing the
surrounding lines).

Scope is deliberately narrow (the credential file and its process-environment
aliases) so this does not re-broaden the block that issue #2863 intentionally
narrowed to ~/.cow/.env. See also issue #2913 for the bypasses handled here.
"""

import os
import re

from common.utils import expand_path

# 内容会镜像进程环境变量（包括从 ~/.cow/.env 加载的各类机密）的
# 路径。读取它们等于绕过 env_config 的访问边界。
# 匹配 /proc/self/environ、/proc/thread-self/environ 和 /proc/<pid>/environ。
_PROC_ENVIRON_RE = re.compile(r"^/proc/(\d+|self|thread-self)/environ$")

DENIED_MESSAGE = (
    "Error: Access denied. API keys and credentials must be accessed "
    "through the env_config tool only."
)


def is_credential_path(absolute_path: str) -> bool:
    """Return True if *absolute_path* points at protected credential data.

    Beyond the literal ~/.cow/.env file, this also blocks two real bypass
    surfaces reported in issue #2913:
      1. /proc/<pid|self|thread-self>/environ - a second view of the
         process environment that leaks secrets loaded from ~/.cow/.env.
      2. Symlinks resolving to ~/.cow/.env; an exact abspath match keeps the
         link target and can be bypassed.
    """
    # 比较规范化路径和符号链接解析路径，
    # 采用 POSIX 形式，因此 /proc 正则表达式无论 os.sep 为何都会匹配。
    candidates = set()
    try:
        candidates.add(os.path.normpath(absolute_path).replace(os.sep, "/"))
        candidates.add(os.path.realpath(absolute_path).replace(os.sep, "/"))
    except OSError:
        candidates.add(absolute_path.replace(os.sep, "/"))

    # 1. /proc 环境别名（在原始和符号链接解析形式上检查）。
    for candidate in candidates:
        if _PROC_ENVIRON_RE.match(candidate):
            return True

    # 2. 凭证文件本身，位于两侧的符号链接之后。
    env_real = os.path.realpath(expand_path("~/.cow/.env")).replace(os.sep, "/")
    return env_real in candidates
