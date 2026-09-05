"""
Workspace file service - browse, search and edit the agent workspace.

Backs the file manager tab, the preview panel editor and the `@` file
reference picker in the web UI.

Every path goes through :meth:`WorkspaceService.resolve`, which rejects
anything that escapes the workspace root after `..` and symlinks are resolved.

Only :meth:`write_text` mutates anything, and only for a file that already
exists and holds plain text. It is reachable from the web console but *not*
from :meth:`dispatch`, so remote transports keep the read-only surface.
"""

import base64
import mimetypes
import os
import tempfile
import time
from typing import Dict, List, Optional

from common.log import logger

from agent.protocol.artifact import classify_kind, is_editable, is_previewable

# 体积大、有噪音或纯属内部的目录，用户显式进入时依然可以列出，
# 只是递归搜索会跳过它们。
SEARCH_SKIP_DIRS = {"tmp", "node_modules", "__pycache__", "venv", ".git", ".venv"}

# 代理自身的簿记目录：仍可通过搜索访问，但排名会低于面向用户的文件，
# 以免它们淹没 `@` 选择器中的真实结果。
SEARCH_DEMOTE_DIRS = {"memory", "skills", "knowledge", "scheduler", "plans"}
SEARCH_DEMOTE_PENALTY = 25

MAX_ENTRIES = 500
MAX_SEARCH_WALK = 20000

# `read` 在单次响应中返回的最大文本长度；更长的文件会被截断，
# 并标记为 truncated，而不是直接拒绝。
MAX_TEXT_BYTES = 1024 * 1024

# `file` 按块传输字节，因为远端调用方可能处在
# 单条消息有大小限制的传输通道上。768 KiB 原始字节
# 经 Base64 编码后约为 1 MiB，留有充足余量。
DEFAULT_CHUNK_BYTES = 768 * 1024
MAX_CHUNK_BYTES = 2 * 1024 * 1024

# 超过此大小的文件直接拒绝返回；该值远高于浏览器预览所需。
MAX_FILE_BYTES = 64 * 1024 * 1024

# mtime 比较时，两侧都是经过 JSON 往返的 float，
# 因此允许时间戳末位存在误差，而不要求逐位相等。
MTIME_EPSILON = 1e-6


class WorkspaceConflictError(Exception):
    """The file changed on disk since the caller read it."""


def _decode_utf8(raw: bytes):
    """
    Decode as UTF-8, reporting whether anything had to be replaced.

    A file that isn't valid UTF-8 - a legacy GBK or Latin-1 document, or a
    binary that slipped past the extension check - still has to preview, but an
    editor must not offer to save it: the round-trip would write a replacement
    character over every byte that failed to decode.

    :return: ``(text, lossy)``
    """
    try:
        return raw.decode("utf-8"), False
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace"), True


class WorkspaceService:
    def __init__(self, workspace_root: str):
        self.root = os.path.realpath(os.path.expanduser(workspace_root))

    # ------------------------------------------------------------------
    # 路径助手
    # ------------------------------------------------------------------
    def resolve(self, rel_path: str) -> str:
        """Resolve a workspace-relative path, rejecting anything that escapes."""
        rel_path = (rel_path or "").replace("\\", "/").strip("/")
        full = os.path.realpath(os.path.join(self.root, rel_path))
        if full != self.root and os.path.commonpath([full, self.root]) != self.root:
            raise ValueError(f"Path escapes the workspace: {rel_path}")
        return full

    def to_workspace_rel(self, path: str) -> str:
        """
        Accept either form of path from a caller and return a relative one.

        An absolute path is only accepted when it points inside the workspace;
        otherwise `resolve` would silently reinterpret it as relative to the
        root (leading slashes are stripped) and read the wrong file.
        """
        path = (path or "").strip()
        expanded = os.path.expanduser(path)
        if not os.path.isabs(expanded):
            return path
        full = os.path.realpath(expanded)
        if full != self.root and os.path.commonpath([full, self.root]) != self.root:
            raise ValueError("Path is outside the workspace")
        return self.to_rel(full)

    def to_rel(self, abs_path: str) -> str:
        try:
            rel = os.path.relpath(abs_path, self.root)
        except ValueError:
            return abs_path
        return "" if rel == "." else rel.replace(os.sep, "/")

    # ------------------------------------------------------------------
    # 目录列表
    # ------------------------------------------------------------------
    def list_dir(self, rel_path: str = "", show_hidden: bool = False) -> Dict:
        """List one directory level, directories first then files by mtime desc."""
        full = self.resolve(rel_path)
        if not os.path.isdir(full):
            raise FileNotFoundError(f"Not a directory: {rel_path}")

        dirs: List[Dict] = []
        files: List[Dict] = []
        truncated = False
        try:
            with os.scandir(full) as it:
                for entry in it:
                    if not show_hidden and entry.name.startswith("."):
                        continue
                    if len(dirs) + len(files) >= MAX_ENTRIES:
                        truncated = True
                        break
                    item = self._describe(entry)
                    if item is None:
                        continue
                    (dirs if item["is_dir"] else files).append(item)
        except PermissionError:
            raise ValueError(f"Permission denied: {rel_path}")

        dirs.sort(key=lambda x: x["name"].lower())
        files.sort(key=lambda x: x["mtime"], reverse=True)

        return {
            "path": self.to_rel(full),
            "root": self.root,
            "entries": dirs + files,
            "truncated": truncated,
        }

    def _describe(self, entry) -> Optional[Dict]:
        try:
            stat = entry.stat(follow_symlinks=False)
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            return None
        kind = "directory" if is_dir else classify_kind(entry.name)
        return {
            "name": entry.name,
            "path": self.to_rel(entry.path),
            "abs_path": entry.path,
            "is_dir": is_dir,
            "kind": kind,
            "previewable": (not is_dir) and is_previewable(kind),
            "size": 0 if is_dir else stat.st_size,
            "mtime": stat.st_mtime,
        }

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 30) -> Dict:
        """
        Subsequence match on the workspace-relative path, scored so that
        prefix matches on the entry name rank highest.

        Directories are included so a whole folder can be referenced (e.g. `@`
        a project dir); a matching folder naturally outranks the files inside it
        because those only match on the path, not the name.
        """
        query = (query or "").strip().lower()
        results: List[Dict] = []
        walked = 0

        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d not in SEARCH_SKIP_DIRS
            ]
            for name in dirnames + filenames:
                is_dir = name in dirnames
                if name.startswith("."):
                    continue
                walked += 1
                if walked > MAX_SEARCH_WALK:
                    break
                entry = self._match(query, os.path.join(dirpath, name), name, is_dir)
                if entry:
                    results.append(entry)
            if walked > MAX_SEARCH_WALK:
                break

        results.sort(key=lambda x: (-x["_score"], -x["mtime"]))
        for r in results:
            r.pop("_score", None)
        return {"query": query, "results": results[:limit]}

    def _match(self, query: str, full: str, name: str, is_dir: bool) -> Optional[Dict]:
        """Score one entry against the query. None means it doesn't match."""
        rel = self.to_rel(full)
        score = self._score(query, name.lower(), rel.lower())
        if score < 0:
            return None

        parts = rel.split("/")
        # 目录自身的名称也包含在路径片段里，因此 `memory/` 本身也会被降权。
        if SEARCH_DEMOTE_DIRS.intersection(parts if is_dir else parts[:-1]):
            score -= SEARCH_DEMOTE_PENALTY

        kind = "directory" if is_dir else classify_kind(name)
        if kind == "file":
            # 扩展名无法识别（或没有扩展名）：通常没人会想去引用这类文件，
            # 所以把它们排到真正的文档之下。
            score -= SEARCH_DEMOTE_PENALTY

        try:
            stat = os.stat(full)
        except OSError:
            return None

        return {
            "name": name,
            "path": rel,
            "abs_path": full,
            "is_dir": is_dir,
            "kind": kind,
            "previewable": (not is_dir) and is_previewable(kind),
            "size": 0 if is_dir else stat.st_size,
            "mtime": stat.st_mtime,
            "_score": score,
        }

    @staticmethod
    def _score(query: str, name: str, rel: str) -> int:
        """Higher is better; -1 means no match."""
        if not query:
            return 0
        if name.startswith(query):
            return 100
        if query in name:
            return 80
        if query in rel:
            return 60
        # 子序列匹配作为兜底：让 “idxhtml” 也能命中 “index.html”。
        pos = 0
        for ch in query:
            pos = name.find(ch, pos)
            if pos < 0:
                return -1
            pos += 1
        return 30

    # ------------------------------------------------------------------
    # 元数据
    # ------------------------------------------------------------------
    def meta(self) -> Dict:
        return {
            "root": self.root,
            "exists": os.path.isdir(self.root),
            "server_time": time.time(),
        }

    # ------------------------------------------------------------------
    # 行动调度
    # ------------------------------------------------------------------
    def dispatch(self, action: str, payload: Optional[dict] = None) -> dict:
        """
        Dispatch one read-only workspace action.

        Shared by every caller that reaches the workspace over a transport
        rather than in-process, so the path checks and size caps below apply
        uniformly. Actions: ``tree`` ``search`` ``resolve`` ``meta`` ``read``
        ``file``.

        Read-only by design: ``write_text`` is intentionally not dispatchable,
        so adding it here would hand write access to every remote transport
        that forwards its action string straight through.
        """
        payload = payload or {}
        try:
            if action == "tree":
                rel = self.to_workspace_rel(payload.get("path", ""))
                show_hidden = str(payload.get("show_hidden", "")).lower() in ("1", "true", "yes")
                result = self.list_dir(rel, show_hidden=show_hidden)

            elif action == "search":
                query = (payload.get("q") or payload.get("query") or "").strip()
                if not query:
                    return self._ok(action, {"query": "", "results": []})
                limit = max(1, min(int(payload.get("limit") or 30), 100))
                result = self.search(query, limit=limit)

            elif action == "resolve":
                rel = self.to_workspace_rel(payload.get("path", ""))
                result = {"file": self.stat_file(rel)}

            elif action == "meta":
                result = self.meta()

            elif action == "read":
                rel = self.to_workspace_rel(payload.get("path", ""))
                if not rel:
                    return self._err(action, 400, "path is required")
                result = self.read_text(rel, max_bytes=payload.get("max_bytes") or MAX_TEXT_BYTES)

            elif action == "file":
                rel = self.to_workspace_rel(payload.get("path", ""))
                if not rel:
                    return self._err(action, 400, "path is required")
                result = self.read_chunk(
                    rel,
                    offset=payload.get("offset") or 0,
                    chunk_size=payload.get("chunk_size") or DEFAULT_CHUNK_BYTES,
                )

            else:
                return self._err(action, 400, f"unknown action: {action}")

            return self._ok(action, result)

        except FileNotFoundError as e:
            return self._err(action, 404, str(e))
        except ValueError as e:
            # 路径转义、条目类型错误、文件过大。
            return self._err(action, 403, str(e))
        except PermissionError:
            return self._err(action, 403, "permission denied")
        except Exception as e:
            logger.error(f"[WorkspaceService] dispatch error: action={action}, error={e}")
            return self._err(action, 500, str(e))

    @staticmethod
    def _ok(action: str, payload) -> dict:
        return {"action": action, "code": 200, "message": "success", "payload": payload}

    @staticmethod
    def _err(action: str, code: int, message: str) -> dict:
        return {"action": action, "code": code, "message": message, "payload": None}

    def _resolve_file(self, rel_path: str) -> str:
        """Resolve a path that must point at a regular file."""
        full = self.resolve(rel_path)
        if os.path.isdir(full):
            raise ValueError(f"Not a file: {rel_path}")
        if not os.path.isfile(full):
            raise FileNotFoundError(f"File not found: {rel_path}")
        return full

    def read_text(self, rel_path: str, max_bytes: int = MAX_TEXT_BYTES) -> Dict:
        """
        Read a text file as a string.

        Undecodable bytes are replaced rather than raising, so a file with a
        stray encoding still previews instead of erroring out. `mtime` is the
        baseline an editor passes back to :meth:`write_text`, and `editable`
        says whether saving would be accepted at all.
        """
        full = self._resolve_file(rel_path)
        max_bytes = max(1, min(int(max_bytes or MAX_TEXT_BYTES), MAX_TEXT_BYTES))
        size = os.path.getsize(full)
        with open(full, "rb") as f:
            raw = f.read(max_bytes)
        truncated = size > len(raw)
        content, lossy = _decode_utf8(raw)
        return {
            "path": self.to_rel(full),
            "content": content,
            "truncated": truncated,
            "lossy": lossy,
            "size": size,
            "mtime": os.path.getmtime(full),
            # 部分读取或有损解码的结果都不能编辑：前者保存会截断文件尾部，
            # 后者则会把每个无法解码的字节
            # 都替换成占位字符，损坏内容。
            "editable": is_editable(classify_kind(full)) and not truncated and not lossy,
        }

    def write_text(self, rel_path: str, content: str,
                   expected_mtime: Optional[float] = None) -> Dict:
        """
        Overwrite an existing text file with `content`.

        The file must already exist: the preview panel edits what it shows, and
        a path that no longer resolves means the caller's view is stale rather
        than that a new file is wanted.

        :param expected_mtime: the mtime the caller last read. When given and
            the file has since changed - typically because the agent rewrote it
            while the user was typing - raise :class:`WorkspaceConflictError`
            instead of dropping those changes on the floor.
        """
        full = self._resolve_file(rel_path)

        kind = classify_kind(full)
        if not is_editable(kind):
            raise ValueError(f"Not an editable text file: {self.to_rel(full)}")

        if expected_mtime is not None:
            current = os.path.getmtime(full)
            if abs(current - float(expected_mtime)) > MTIME_EPSILON:
                raise WorkspaceConflictError(
                    f"File changed on disk since it was read: {self.to_rel(full)}"
                )

        # 两条可编辑性规则都从磁盘重新判定，而不是信任调用方
        # 会遵守 `read_text` 返回的 `editable` 标志。
        size = os.path.getsize(full)
        if size > MAX_TEXT_BYTES:
            raise ValueError(f"File too large to edit: {size} bytes")
        with open(full, "rb") as f:
            existing = f.read()
        if _decode_utf8(existing)[1]:
            raise ValueError(f"Not a UTF-8 text file: {self.to_rel(full)}")

        # 编辑框中的文本一律按 LF 回传；若原文件用的是 CRLF，
        # 保存时再还原成 CRLF，这样只改一行就不会把每行都重写一遍。
        newline = "\r\n" if b"\r\n" in existing else "\n"
        data = (content or "").replace("\r\n", "\n").replace("\r", "\n")
        if newline != "\n":
            data = data.replace("\n", newline)
        encoded = data.encode("utf-8")
        if len(encoded) > MAX_TEXT_BYTES:
            raise ValueError(f"Content too large: {len(encoded)} bytes")

        self._replace_atomically(full, encoded)
        return {
            "path": self.to_rel(full),
            "size": os.path.getsize(full),
            "mtime": os.path.getmtime(full),
        }

    @staticmethod
    def _replace_atomically(full: str, data: bytes) -> None:
        """
        Write via a sibling temp file and rename over the target.

        A crash or a full disk then leaves the original file intact instead of
        half-written, and a reader never observes a partial document.
        """
        directory = os.path.dirname(full)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".cow-edit-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            # mkstemp 建出的临时文件权限是 0600；这里继承原文件的权限模式，
            # 以免编辑后静默丢失可执行位或组访问权限。
            try:
                os.chmod(tmp_path, os.stat(full).st_mode & 0o7777)
            except OSError:
                pass
            os.replace(tmp_path, full)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def read_chunk(self, rel_path: str, offset: int = 0,
                   chunk_size: int = DEFAULT_CHUNK_BYTES) -> Dict:
        """
        Read one base64 chunk of a file.

        Callers pull successive offsets until `eof`, which keeps any single
        response small enough for a size-limited transport.
        """
        full = self._resolve_file(rel_path)
        size = os.path.getsize(full)
        if size > MAX_FILE_BYTES:
            raise ValueError(f"File too large: {size} bytes")

        offset = max(0, int(offset or 0))
        chunk_size = max(1, min(int(chunk_size or DEFAULT_CHUNK_BYTES), MAX_CHUNK_BYTES))
        with open(full, "rb") as f:
            f.seek(offset)
            raw = f.read(chunk_size)

        mime, _ = mimetypes.guess_type(full)
        return {
            "path": self.to_rel(full),
            "name": os.path.basename(full),
            "mime": mime or "application/octet-stream",
            "total_size": size,
            "offset": offset,
            "length": len(raw),
            "eof": offset + len(raw) >= size,
            "content_b64": base64.b64encode(raw).decode("ascii"),
        }

    def stat_file(self, rel_path: str) -> Dict:
        """
        Metadata for one entry, used when opening something by path.

        Directories resolve too: callers that reference a folder (drag, `@`)
        need to learn it's a folder rather than get an error.
        """
        full = self.resolve(rel_path)
        is_dir = os.path.isdir(full)
        if not is_dir and not os.path.isfile(full):
            raise FileNotFoundError(f"File not found: {rel_path}")
        stat = os.stat(full)
        kind = "directory" if is_dir else classify_kind(full)
        return {
            "name": os.path.basename(full) or self.to_rel(full),
            "path": self.to_rel(full),
            "abs_path": full,
            "is_dir": is_dir,
            "kind": kind,
            "previewable": (not is_dir) and is_previewable(kind),
            "size": 0 if is_dir else stat.st_size,
            "mtime": stat.st_mtime,
        }
