"""
Cheap, in-process syntax validation for files the agent writes.

The agent has no compiler, test runner or language server to tell it that an
edit broke a file, so a mistake can sit unnoticed until something tries to load
the file much later. Parsing what we are about to write costs a millisecond and
catches the most common self-inflicted damage: truncated generation, mashed
quotes, a replacement pasted at the wrong indentation.

Two tiers, split by whether "does not parse" is ever a legitimate state:

* Structured data (JSON/YAML/TOML) is an atomic blob - half a JSON document is
  never something anyone meant to write, so a parse failure blocks the write.
* Source code can legitimately be mid-construction, so it only ever produces a
  warning, and only when the edit *introduced* the breakage (a file that was
  already unparseable stays quiet).
"""

import ast
import json
import os
from typing import Optional, Tuple

# 内容属于原子结构块（blob）的扩展名：解析不过就拒绝写入。
BLOCKING_EXTS = frozenset({'.json', '.yaml', '.yml', '.toml'})


def _check_json(text: str) -> Optional[str]:
    try:
        json.loads(text)
    except ValueError as e:
        return str(e)
    return None


def _check_yaml(text: str) -> Optional[str]:
    try:
        import yaml
    except ImportError:
        return None
    try:
        # 用 parse() 而不是 safe_load()：这里只想要一个语法判决，
        # 而 safe_load 还会额外拒绝那些格式完全合法、
        # 只是 loader 不认识的带标签 YAML。
        for _ in yaml.parse(text):
            pass
    except Exception as e:
        return str(e).replace('\n', ' ')
    return None


def _check_toml(text: str) -> Optional[str]:
    try:
        import tomllib
    except ImportError:
        return None
    try:
        tomllib.loads(text)
    except Exception as e:
        return str(e)
    return None


def _check_python(text: str) -> Optional[str]:
    try:
        ast.parse(text)
    except SyntaxError as e:
        where = f" (line {e.lineno})" if e.lineno else ""
        return f"{e.msg}{where}"
    except ValueError as e:
        # 例如包含空字节的源
        return str(e)
    return None


_CHECKERS = {
    '.json': _check_json,
    '.yaml': _check_yaml,
    '.yml': _check_yaml,
    '.toml': _check_toml,
    '.py': _check_python,
}


def check(path: str, text: str) -> Optional[str]:
    """Return a syntax error message for *text*, or None if it is fine.

    None is also returned for file types we cannot check, so callers can treat
    "no error" and "not checked" the same way.
    """
    checker = _CHECKERS.get(os.path.splitext(path)[1].lower())
    if checker is None:
        return None
    try:
        return checker(text)
    except Exception:
        # 检查器崩溃绝不能阻止代理写入文件。
        return None


def is_blocking(path: str) -> bool:
    """Whether a parse failure for this path should refuse the write."""
    return os.path.splitext(path)[1].lower() in BLOCKING_EXTS


def review(path: str, old_text: Optional[str], new_text: str) -> Tuple[Optional[str], Optional[str]]:
    """Judge a pending write of *new_text* over *old_text*.

    :return: (blocking_error, warning) - at most one is set.
    """
    error = check(path, new_text)
    if error is None:
        return None, None

    if is_blocking(path):
        return (
            f"Refusing to write {os.path.basename(path)}: the content is not valid "
            f"{os.path.splitext(path)[1].lstrip('.').upper()} ({error}). "
            f"The file was left unchanged - fix the content and retry."
        ), None

    # 源码文件：只要本次修改没有把它改坏，就保持沉默。
    # 一个本来就解析不过的文件，要么还在编写中、要么根本不算源码；
    # 要是对每个例行步骤都告警，等于天天狼来了。
    if old_text is not None and check(path, old_text) is not None:
        return None, None

    return None, (
        f"This edit leaves {os.path.basename(path)} with a syntax error: {error}. "
        f"The write was applied - re-read the file and fix it if that was not intended."
    )
