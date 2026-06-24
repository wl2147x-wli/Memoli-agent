"""记忆存储层。

第七阶段使用 Markdown 文件作为长期记忆存储，保持简单、可读、可手工编辑。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memoli_agent.agent.memory.runtime import MemoryItem


@dataclass(frozen=True, slots=True)
class MarkdownMemoryStore:
    """Markdown 文件记忆存储。"""

    root: Path

    @property
    def memory_file(self) -> Path:
        """长期事实记忆文件。"""

        return self.root / "MEMORY.md"

    @property
    def history_file(self) -> Path:
        """对话流水历史文件。"""

        return self.root / "HISTORY.md"

    @property
    def recent_context_file(self) -> Path:
        """最近上下文摘要文件。"""

        return self.root / "RECENT_CONTEXT.md"

    def ensure_files(self) -> None:
        """创建记忆目录和默认文件。"""

        self.root.mkdir(parents=True, exist_ok=True)
        self._ensure_file(self.memory_file, "# 长期记忆\n\n")
        self._ensure_file(self.history_file, "# 对话历史\n\n")
        self._ensure_file(self.recent_context_file, "# 最近上下文\n\n")

    def append_memory(
        self,
        content: str,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryItem:
        """追加一条长期事实记忆。"""

        self.ensure_files()
        timestamp = utc_now()
        item = MemoryItem(
            content=content.strip(),
            source=source,
            timestamp=timestamp,
            metadata=dict(metadata or {}),
        )
        metadata_text = _format_metadata(item.metadata)
        line = (
            f"- [{timestamp.isoformat()}] ({source}) {item.content}"
            f"{metadata_text}\n"
        )
        self.memory_file.write_text(
            self.memory_file.read_text(encoding="utf-8") + line,
            encoding="utf-8",
        )
        return item

    def append_history(
        self,
        user_content: str,
        assistant_content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """追加一轮对话流水到 HISTORY.md。"""

        self.ensure_files()
        timestamp = utc_now()
        metadata_text = _format_metadata(dict(metadata or {}))
        block = (
            f"## {timestamp.isoformat()}{metadata_text}\n\n"
            f"- 用户：{user_content}\n"
            f"- 助手：{assistant_content}\n\n"
        )
        self.history_file.write_text(
            self.history_file.read_text(encoding="utf-8") + block,
            encoding="utf-8",
        )

    def load_memory_items(self) -> list[MemoryItem]:
        """读取长期记忆和最近上下文中的条目。"""

        self.ensure_files()
        items = [
            *self._load_items_from_file(self.memory_file, "memory"),
            *self._load_items_from_file(self.recent_context_file, "recent_context"),
        ]
        return items

    def _ensure_file(self, path: Path, default_content: str) -> None:
        """文件不存在时写入默认内容。"""

        if not path.exists():
            path.write_text(default_content, encoding="utf-8")

    def _load_items_from_file(self, path: Path, default_source: str) -> list[MemoryItem]:
        """从 Markdown 文件中读取 bullet 记忆条目。"""

        items: list[MemoryItem] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("- "):
                continue
            items.append(_parse_memory_line(line, default_source))
        return items


def utc_now() -> datetime:
    """返回当前 UTC 时间。"""

    return datetime.now(timezone.utc)


def _format_metadata(metadata: dict[str, Any]) -> str:
    """将元数据压缩成一段可读文本。"""

    if not metadata:
        return ""
    pairs = ", ".join(f"{key}={value}" for key, value in metadata.items())
    return f" {{{pairs}}}"


def _parse_memory_line(line: str, default_source: str) -> MemoryItem:
    """解析 Markdown bullet 记忆。"""

    content = line.removeprefix("- ").strip()
    timestamp = utc_now()
    source = default_source

    if content.startswith("[") and "]" in content:
        raw_timestamp, rest = content[1:].split("]", 1)
        try:
            timestamp = datetime.fromisoformat(raw_timestamp)
        except ValueError:
            timestamp = utc_now()
        content = rest.strip()

    if content.startswith("(") and ")" in content:
        raw_source, rest = content[1:].split(")", 1)
        source = raw_source.strip() or default_source
        content = rest.strip()

    if " {" in content:
        content = content.split(" {", 1)[0].strip()

    return MemoryItem(
        content=content,
        source=source,
        timestamp=timestamp,
    )
