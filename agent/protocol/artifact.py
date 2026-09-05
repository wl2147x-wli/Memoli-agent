"""
Artifact detection - decide which agent-written files are user-facing outputs.

The agent writes many files that are internal bookkeeping (memory logs, skills,
knowledge base pages). Only files a human would actually want to open should be
surfaced in the chat UI as previewable artifacts.
"""

import os
from typing import Dict, Optional

from common.log import logger
from common.utils import expand_path

# 工作区中存放代理内部状态（而非用户工件）的目录。
INTERNAL_DIRS = {
    "memory",
    "knowledge",
    "skills",
    "tmp",
    "scheduler",
    "plans",
}

# 工作区根文件是代理自身配置的一部分。
INTERNAL_FILES = {
    "AGENT.md",
    "RULE.md",
    "MEMORY.md",
    "USER.md",
    "BOOTSTRAP.md",
    "mcp.json",
}

_EXT_KINDS = {
    "html": {".html", ".htm"},
    "markdown": {".md", ".markdown"},
    "image": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".ico"},
    "video": {".mp4", ".webm", ".mov", ".avi", ".mkv", ".m4v"},
    "audio": {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"},
    "pdf": {".pdf"},
    "csv": {".csv", ".tsv"},
    "code": {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h", ".go",
        ".rs", ".rb", ".php", ".sh", ".sql", ".css", ".scss", ".json", ".yaml",
        ".yml", ".xml", ".toml", ".ini",
    },
    "text": {".txt", ".log"},
    "office": {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"},
}

# 前端可以在预览面板中内联渲染的类型。
PREVIEWABLE_KINDS = {
    "html", "markdown", "image", "video", "audio", "pdf", "csv", "code", "text",
}

# 这些类型的字节是纯文本，因此预览面板可提供文本编辑器。
# 刻意做成 PREVIEWABLE_KINDS 的子集：图像或 PDF 预览没问题，
# 但一旦经文本编辑框往返保存就会被破坏。
EDITABLE_KINDS = {"html", "markdown", "csv", "code", "text"}

_KIND_BY_EXT: Dict[str, str] = {
    ext: kind for kind, exts in _EXT_KINDS.items() for ext in exts
}


def get_workspace_root() -> str:
    """Absolute path of the routed Agent's workspace."""
    from common.state_dir import real_state_root

    return real_state_root()


def classify_kind(path: str) -> str:
    """Map a file extension to a coarse preview kind."""
    ext = os.path.splitext(path)[1].lower()
    return _KIND_BY_EXT.get(ext, "file")


def is_previewable(kind: str) -> bool:
    return kind in PREVIEWABLE_KINDS


def is_editable(kind: str) -> bool:
    return kind in EDITABLE_KINDS


def resolve_workspace_path(path: str, workspace_root: str) -> str:
    """Resolve a tool `path` argument the same way the file tools do."""
    expanded = expand_path(path)
    if os.path.isabs(expanded):
        return os.path.realpath(expanded)
    return os.path.realpath(os.path.join(workspace_root, expanded))


def _is_internal(abs_path: str, workspace_root: str) -> bool:
    """True when the file is agent bookkeeping rather than a user-facing output."""
    name = os.path.basename(abs_path)
    if name.startswith("."):
        return True

    try:
        rel = os.path.relpath(abs_path, workspace_root)
    except ValueError:
        # Windows 上跨驱动器：文件位于工作区之外，此时只能按名称判断。
        return False

    if rel.startswith(".."):
        # 落在工作区之外（例如编辑项目源码）：不算工件。
        return True

    parts = rel.split(os.sep)
    if len(parts) == 1:
        return name in INTERNAL_FILES
    if parts[0] in INTERNAL_DIRS:
        return True
    return any(p.startswith(".") for p in parts[:-1])


def build_artifact(path: str, workspace_root: Optional[str] = None) -> Optional[Dict]:
    """
    Build artifact metadata for a file the agent just wrote.

    Returns None when the file is internal, missing, or not worth surfacing.
    """
    if not path:
        return None

    root = workspace_root or get_workspace_root()
    # resolve_workspace_path() 会用真实路径解析文件（跟随符号链接），
    # 因此根目录也必须以同样方式解析，否则下面的相对路径检查会看到
    # 前缀不匹配（如 macOS 上的 /var 与 /private/var），从而把
    # 项目内的文件误判为“工作区之外”。
    try:
        root = os.path.realpath(expand_path(root))
    except Exception:
        pass
    try:
        abs_path = resolve_workspace_path(path, root)
    except Exception:
        return None

    if _is_internal(abs_path, root):
        return None
    if not os.path.isfile(abs_path):
        return None

    try:
        size = os.path.getsize(abs_path)
    except OSError:
        size = 0

    try:
        rel_path = os.path.relpath(abs_path, root)
    except ValueError:
        rel_path = abs_path

    kind = classify_kind(abs_path)
    return {
        "type": "artifact",
        "path": abs_path,
        "rel_path": rel_path,
        "dir": os.path.dirname(abs_path),
        "file_name": os.path.basename(abs_path),
        "kind": kind,
        "previewable": is_previewable(kind),
        "size": size,
    }


def safe_build_artifact(path: str, workspace_root: Optional[str] = None) -> Optional[Dict]:
    """build_artifact that never raises - artifact reporting must not break a tool call."""
    try:
        return build_artifact(path, workspace_root)
    except Exception as e:
        logger.debug(f"[Artifact] skipped {path}: {e}")
        return None
