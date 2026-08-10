"""旧 Markdown 记忆的安全、可预览迁移。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from memoli_agent.agent.memory.models import MemoryScope
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore

_LEGACY_FILES = ("MEMORY.md", "HISTORY.md", "RECENT_CONTEXT.md")


@dataclass(frozen=True, slots=True)
class MigrationReport:
    manifest_hash: str
    parseable: int
    skipped: int
    malformed: int
    imported: int = 0
    duplicate: int = 0
    notes: tuple[str, ...] = (
        "HISTORY.md 仅备份，不提升为事实。",
        "RECENT_CONTEXT.md 仅备份，不提升为事实。",
    )


class LegacyMemoryMigrator:
    def __init__(
        self,
        root: Path,
        store: SQLiteMemoryStore,
        scope: MemoryScope | None = None,
    ) -> None:
        self.root = root
        self.store = store
        self.scope = scope or MemoryScope()

    def preview(self) -> MigrationReport:
        snapshot = self._snapshot()
        entries, malformed = self._parse_memory(snapshot)
        manifest_hash = self._manifest_hash(snapshot)
        return MigrationReport(
            manifest_hash=manifest_hash,
            parseable=len(entries),
            skipped=self._skipped_line_count(snapshot),
            malformed=malformed,
        )

    def import_memory(self, *, fail_after: int | None = None) -> MigrationReport:
        snapshot = self._snapshot()
        entries, malformed = self._parse_memory(snapshot)
        manifest_hash = self._manifest_hash(snapshot)
        preview = MigrationReport(
            manifest_hash=manifest_hash,
            parseable=len(entries),
            skipped=self._skipped_line_count(snapshot),
            malformed=malformed,
        )
        backup = self._backup(preview.manifest_hash, snapshot)
        imported, duplicate = self.store.import_legacy_claims(
            entries,
            manifest_hash=preview.manifest_hash,
            scope=self.scope,
            fail_after=fail_after,
        )
        report = MigrationReport(
            manifest_hash=preview.manifest_hash,
            parseable=preview.parseable,
            skipped=preview.skipped,
            malformed=preview.malformed,
            imported=imported,
            duplicate=duplicate,
        )
        (backup / "migration-manifest.json").write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return report

    def _parse_memory(
        self, snapshot: dict[str, bytes | None]
    ) -> tuple[list[tuple[str, str]], int]:
        raw_bytes = snapshot.get("MEMORY.md")
        if raw_bytes is None:
            return [], 0
        entries: list[tuple[str, str]] = []
        malformed = 0
        for number, raw in enumerate(
            raw_bytes.decode("utf-8").splitlines(), 1
        ):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith("- "):
                malformed += 1
                continue
            content = line[2:].strip()
            if content.startswith("[") and "]" in content:
                content = content.split("]", 1)[1].strip()
            if content.startswith("(") and ")" in content:
                content = content.split(")", 1)[1].strip()
            if " {" in content:
                content = content.split(" {", 1)[0].strip()
            if content:
                entries.append((content, f"MEMORY.md:{number}"))
            else:
                malformed += 1
        return entries, malformed

    def _manifest_hash(self, snapshot: dict[str, bytes | None]) -> str:
        digest = hashlib.sha256()
        for name in _LEGACY_FILES:
            digest.update(name.encode())
            digest.update(snapshot[name] or b"<missing>")
        return digest.hexdigest()

    def _backup(
        self, manifest_hash: str, snapshot: dict[str, bytes | None]
    ) -> Path:
        target = self.root / "legacy-backups" / manifest_hash[:16]
        target.mkdir(parents=True, exist_ok=True)
        for name in _LEGACY_FILES:
            content = snapshot[name]
            if content is not None and not (target / name).exists():
                (target / name).write_bytes(content)
        return target

    def _skipped_line_count(self, snapshot: dict[str, bytes | None]) -> int:
        count = 0
        for name in ("HISTORY.md", "RECENT_CONTEXT.md"):
            content = snapshot[name]
            if content is not None:
                count += len(content.decode("utf-8").splitlines())
        return count

    def _snapshot(self) -> dict[str, bytes | None]:
        return {
            name: (
                (self.root / name).read_bytes()
                if (self.root / name).exists()
                else None
            )
            for name in _LEGACY_FILES
        }
