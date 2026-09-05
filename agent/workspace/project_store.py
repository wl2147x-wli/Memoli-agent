"""Session-scoped project workspace store.

A "project workspace" is a working directory the user points a conversation at,
the way a coding agent opens a folder. It is deliberately separate from the
Agent's ``state_root`` (``~/cow``): memory, skills, MCP and the session database
stay anchored to ``state_root``, while only the *working directory* — bash cwd,
relative file paths, preview root and the ``@`` picker — follows the project.

What lives where:

- ``projects.json`` (under ``shared_root``): the session -> project mapping and
  a recents list. Instance-level config, so it sits beside the other shared
  assets rather than under one Agent.
- Projects root (``<shared_root>/projects`` by default): where "new project"
  creates folders. Browsing/opening an arbitrary directory is also allowed;
  the projects root is just a convenient default home.

Selecting nothing keeps ``project_dir == state_root``, so a session that never
picks a project behaves exactly as before.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Dict, List, Optional

from common.log import logger

# 最近记录数量上限：要足够多，在选择器里才够用；
# 也要足够少，让每次对该文件的读写都足够轻量。
MAX_RECENTS = 20

# 侧边栏排序中代表“默认工作区”的哨兵值，
# 这样默认空间就能在实际项目之间拖动，而不必固定在顶部。
DEFAULT_SPACE_KEY = "__default__"


def _store_file() -> str:
    from common.state_dir import shared_root
    return str(shared_root() / "projects.json")


def projects_root() -> str:
    """Default home for freshly created projects.

    Configurable via ``project_workspace_root``; defaults to
    ``<shared_root>/projects``. Browsing to an arbitrary directory is still
    allowed — this only decides where "new project" lands.
    """
    from config import conf
    from common.state_dir import shared_root
    from common.utils import expand_path

    configured = conf().get("project_workspace_root")
    if configured:
        return os.path.realpath(expand_path(configured))
    return str(shared_root() / "projects")


_lock = threading.Lock()


def _load() -> Dict:
    path = _store_file()
    if not os.path.isfile(path):
        return {"sessions": {}, "recents": [], "meta": {}, "order": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception as e:
        logger.warning(f"[ProjectStore] Could not read {path}: {e}")
        return {"sessions": {}, "recents": [], "meta": {}, "order": []}
    data.setdefault("sessions", {})
    data.setdefault("recents", [])
    # ``meta``：路径 -> {“display_name”: str}。重命名记录保存在这里，从不写回
    # 磁盘，因此文件夹本身保持原名，已有的绑定也始终有效。
    data.setdefault("meta", {})
    # ``order``：用户自选的侧边栏 space 顺序（由项目路径和
    # DEFAULT_SPACE_KEY 哨兵组成）。未列入的条目将按最近使用顺序排列。
    data.setdefault("order", [])
    return data


def _save(data: Dict) -> None:
    path = _store_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.warning(f"[ProjectStore] Could not write {path}: {e}")


def _normalize(path: str) -> str:
    from common.utils import expand_path
    return os.path.realpath(expand_path((path or "").strip()))


def _session_key(session_id: str, agent_id: Optional[str]) -> str:
    """Namespace by agent so identical session ids across Agents don't collide."""
    return f"{agent_id or 'default'}::{session_id}"


def get_project_dir(session_id: str, agent_id: Optional[str] = None) -> Optional[str]:
    """Return the project directory selected for a session, or None.

    None means "use the default workspace" and the caller should fall back to
    ``state_root``. A path that no longer exists on disk also returns None so a
    deleted project silently reverts to the default instead of erroring.
    """
    if not session_id:
        return None
    with _lock:
        data = _load()
        entry = data["sessions"].get(_session_key(session_id, agent_id))
    if not entry:
        return None
    path = entry.get("path") if isinstance(entry, dict) else entry
    if path and os.path.isdir(path):
        return path
    return None


def get_project_map(agent_id: Optional[str] = None) -> Dict[str, str]:
    """Every session -> project binding for one agent, in a single file read.

    Used when the session list needs each conversation's project: asking
    ``get_project_dir`` per row would re-read and re-parse the store each time.
    Bindings whose directory is gone are dropped, matching ``get_project_dir``.
    """
    prefix = f"{agent_id or 'default'}::"
    with _lock:
        data = _load()
        sessions = dict(data.get("sessions") or {})

    out: Dict[str, str] = {}
    for key, entry in sessions.items():
        if not key.startswith(prefix):
            continue
        path = entry.get("path") if isinstance(entry, dict) else entry
        if path and os.path.isdir(path):
            out[key[len(prefix):]] = path
    return out


def forget_session(session_id: str, agent_id: Optional[str] = None) -> None:
    """Drop a session's binding (called when the conversation is deleted).

    The recents list is left alone: the project itself still exists and the user
    will likely open it again.
    """
    if not session_id:
        return
    key = _session_key(session_id, agent_id)
    with _lock:
        data = _load()
        if data["sessions"].pop(key, None) is not None:
            _save(data)


def set_project_dir(
    session_id: str, project_dir: Optional[str], agent_id: Optional[str] = None
) -> Optional[str]:
    """Bind a session to a project directory (or clear it when None/empty).

    Returns the normalized absolute path that was stored, or None when cleared.
    """
    if not session_id:
        raise ValueError("session_id is required")

    key = _session_key(session_id, agent_id)
    with _lock:
        data = _load()
        if not project_dir:
            data["sessions"].pop(key, None)
            _save(data)
            return None

        real = _normalize(project_dir)
        if not os.path.isdir(real):
            raise FileNotFoundError(f"Not a directory: {project_dir}")

        data["sessions"][key] = {"path": real, "ts": time.time()}
        _touch_recent(data, real)
        _save(data)
        return real


def _touch_recent(data: Dict, real_path: str) -> None:
    recents: List[Dict] = [
        r for r in data.get("recents", [])
        if (r.get("path") if isinstance(r, dict) else r) != real_path
    ]
    recents.insert(0, {"path": real_path, "name": os.path.basename(real_path) or real_path, "ts": time.time()})
    data["recents"] = recents[:MAX_RECENTS]


def _display_name(data: Dict, path: str) -> str:
    """The user-facing name for a project path: rename override, else basename."""
    meta = data.get("meta") or {}
    entry = meta.get(path)
    if isinstance(entry, dict) and (entry.get("display_name") or "").strip():
        return entry["display_name"].strip()
    return os.path.basename(path.rstrip(os.sep)) or path


def display_name_for(path: str) -> str:
    """Public helper: the user-facing name for a project path (rename-aware)."""
    if not path:
        return ""
    with _lock:
        data = _load()
    return _display_name(data, os.path.realpath(path))


def list_recents() -> List[Dict]:
    """Recently used projects, most recent first, pruning ones now gone."""
    with _lock:
        data = _load()
        recents = data.get("recents", [])
        out: List[Dict] = []
        for r in recents:
            path = r.get("path") if isinstance(r, dict) else r
            if path and os.path.isdir(path):
                out.append({"path": path, "name": _display_name(data, path)})
    return out


def rename_project(path: str, display_name: str) -> str:
    """Give a project a display name without touching its folder on disk.

    Passing an empty name clears the override (falls back to the folder name).
    Returns the resulting display name.
    """
    real = _normalize(path)
    name = (display_name or "").strip()
    with _lock:
        data = _load()
        meta = data.setdefault("meta", {})
        if name:
            meta[real] = {**(meta.get(real) or {}), "display_name": name}
        else:
            entry = meta.get(real) or {}
            entry.pop("display_name", None)
            if entry:
                meta[real] = entry
            else:
                meta.pop(real, None)
        _save(data)
        return _display_name(data, real)


def delete_project(path: str, agent_id: Optional[str] = None) -> int:
    """Forget a project: drop it from recents/meta/order and unbind sessions.

    Nothing on disk is removed — the folder and its files stay. Sessions bound
    to it revert to the default workspace (their binding is cleared). Returns the
    number of sessions that were unbound.

    ``agent_id`` scopes which sessions are unbound; None means the default agent.
    """
    real = _normalize(path)
    prefix = f"{agent_id or 'default'}::"
    with _lock:
        data = _load()

        unbound = 0
        for key, entry in list(data.get("sessions", {}).items()):
            if not key.startswith(prefix):
                continue
            bound = entry.get("path") if isinstance(entry, dict) else entry
            if bound == real:
                data["sessions"].pop(key, None)
                unbound += 1

        data["recents"] = [
            r for r in data.get("recents", [])
            if (r.get("path") if isinstance(r, dict) else r) != real
        ]
        (data.get("meta") or {}).pop(real, None)
        data["order"] = [k for k in data.get("order", []) if k != real]
        _save(data)
    logger.info(f"[ProjectStore] Deleted project record: {real} (unbound {unbound} sessions)")
    return unbound


def get_order() -> List[str]:
    """User-chosen sidebar order of spaces (paths + DEFAULT_SPACE_KEY)."""
    with _lock:
        data = _load()
        return list(data.get("order") or [])


def set_order(order: List[str]) -> List[str]:
    """Persist the sidebar order of spaces. Unknown/blank entries are dropped."""
    cleaned: List[str] = []
    seen = set()
    for key in order or []:
        if not isinstance(key, str):
            continue
        k = key.strip()
        if not k or k in seen:
            continue
        # 真实项目路径标准化；默认哨兵保持原样。
        norm = k if k == DEFAULT_SPACE_KEY else _normalize(k)
        if norm in seen:
            continue
        seen.add(norm)
        cleaned.append(norm)
    with _lock:
        data = _load()
        data["order"] = cleaned
        _save(data)
    return cleaned


def create_project(name: str) -> str:
    """Create a new project folder under the projects root and return its path.

    Only a bare folder name is accepted; a name containing path separators is
    rejected so this can't be used to create directories anywhere on disk.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("project name is required")
    if os.sep in name or (os.altsep and os.altsep in name) or name in (".", ".."):
        raise ValueError("project name must not contain path separators")

    root = projects_root()
    os.makedirs(root, exist_ok=True)
    target = os.path.realpath(os.path.join(root, name))
    # 纵深防御：该文件夹必须直接位于项目根目录下。
    if os.path.dirname(target) != os.path.realpath(root):
        raise ValueError("invalid project name")
    if os.path.exists(target):
        raise FileExistsError(f"Project already exists: {name}")
    os.makedirs(target)
    logger.info(f"[ProjectStore] Created project: {target}")
    return target
