"""File backup / rollback support for self-evolution.

Before the evolution agent edits MEMORY.md or a skill file, we snapshot the
current state into ``memory/.evolution_backups/<backup_id>/`` so a later "undo"
can restore it. File-level restore only — simple and reliable.
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from common.log import logger

_BACKUP_DIRNAME = ".evolution_backups"
_MANIFEST_NAME = "manifest.json"
# 仅保留最近的 N 个备份以限制磁盘使用。
_MAX_BACKUPS = 10


def _backups_root(workspace_dir: Path) -> Path:
    return Path(workspace_dir) / "memory" / _BACKUP_DIRNAME


def create_backup(workspace_dir: Path, files: List[Path]) -> Optional[str]:
    """Snapshot ``files`` (those that exist) under a new backup id.

    Returns the backup_id, or None when there is nothing to back up.
    """
    existing = [Path(f) for f in files if Path(f).exists()]
    if not existing:
        return None

    backup_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + str(int(time.time() * 1000) % 1000)
    root = _backups_root(workspace_dir)
    target = root / backup_id
    try:
        target.mkdir(parents=True, exist_ok=True)
        ws = Path(workspace_dir)
        manifest = []
        for idx, src in enumerate(existing):
            # 以扁平序号加相对路径的方式存放，这样即使面对嵌套的
            # 技能文件，恢复时也知道每个文件原本来自哪里。
            try:
                rel = str(src.relative_to(ws))
            except ValueError:
                rel = src.name
            dst = target / f"{idx}.bak"
            shutil.copy2(src, dst)
            manifest.append({"rel": rel, "bak": f"{idx}.bak"})
        (target / _MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _prune_old_backups(root)
        # 调用方会记录“备份 + 审查”的汇总行；这里只保留在 debug 级别。
        logger.debug(f"[Evolution] Created backup {backup_id} ({len(manifest)} file(s))")
        return backup_id
    except Exception as e:
        logger.warning(f"[Evolution] Failed to create backup: {e}")
        return None


def restore_backup(workspace_dir: Path, backup_id: str) -> bool:
    """Restore all files captured under ``backup_id``. Returns success."""
    if not backup_id:
        return False
    target = _backups_root(workspace_dir) / backup_id
    manifest_path = target / _MANIFEST_NAME
    if not manifest_path.exists():
        logger.warning(f"[Evolution] Backup not found: {backup_id}")
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ws = Path(workspace_dir)
        for entry in manifest:
            bak = target / entry["bak"]
            dst = ws / entry["rel"]
            if bak.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bak, dst)
        logger.info(f"[Evolution] Restored backup {backup_id} ({len(manifest)} file(s))")
        return True
    except Exception as e:
        logger.warning(f"[Evolution] Failed to restore backup {backup_id}: {e}")
        return False


def _prune_old_backups(root: Path) -> None:
    """Drop the oldest backups beyond _MAX_BACKUPS (sorted by name = chronological)."""
    try:
        dirs = sorted(
            [d for d in root.iterdir() if d.is_dir()],
            key=lambda p: p.name,
        )
        for old in dirs[:-_MAX_BACKUPS]:
            shutil.rmtree(old, ignore_errors=True)
    except Exception as e:
        logger.debug(f"[Evolution] Backup prune skipped: {e}")
