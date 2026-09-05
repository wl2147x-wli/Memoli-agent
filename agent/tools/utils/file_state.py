"""
Cross-tool record of when the agent last read each file.

The tool manager builds a fresh tool instance per call, so this state has to
live at module level to be shared between read, edit and write.

It powers a staleness warning: if a file changed on disk after the agent read
it, the agent is probably about to overwrite someone else's change (the user
editing by hand, a scheduled task, or a concurrent agent). We warn rather than
block - unlike a single-user coding CLI, this agent runs across channels where
legitimate outside edits are common, and hard-failing would strand the model
with no way forward.
"""

import os
import threading
from collections import OrderedDict
from typing import Optional

# 一场对话的量足矣；设上限约束，因此长时间运行的进程不会
# 无限制地增长。
_MAX_TRACKED = 512

_lock = threading.Lock()
_read_mtimes = OrderedDict()  # realpath -> 我们读取它时的 mtime


def _key(path: str) -> Optional[str]:
    try:
        return os.path.realpath(path)
    except OSError:
        return None


def _current_mtime(path: str) -> Optional[float]:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def note_read(path: str) -> None:
    """Record that the agent has just seen the current contents of *path*."""
    key = _key(path)
    if not key:
        return
    mtime = _current_mtime(key)
    if mtime is None:
        return
    with _lock:
        _read_mtimes[key] = mtime
        _read_mtimes.move_to_end(key)
        while len(_read_mtimes) > _MAX_TRACKED:
            _read_mtimes.popitem(last=False)


# 写入同样会让“我们对文件的认知”变为最新，
# 因此随后的编辑不应再被标记为过期。
note_write = note_read


def staleness_warning(path: str) -> Optional[str]:
    """Warn if *path* changed since the agent last read it.

    Returns None when the file is unchanged, or when the agent never read it -
    an unread file carries no expectation to violate, and warning there would
    fire on every legitimate first write.
    """
    key = _key(path)
    if not key:
        return None
    with _lock:
        seen = _read_mtimes.get(key)
    if seen is None:
        return None
    current = _current_mtime(key)
    if current is None or current <= seen:
        return None
    return (
        f"{os.path.basename(key)} was modified after you last read it "
        "(by the user, a scheduled task, or another agent). Your change was "
        "applied on top of the older content - read the file again to confirm "
        "the result is what you intended."
    )


def reset() -> None:
    """Clear all tracked state. For tests."""
    with _lock:
        _read_mtimes.clear()
