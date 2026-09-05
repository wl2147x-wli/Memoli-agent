"""Portable local backup and restore commands for CowAgent user data."""

import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional, Set

import click

from cli.utils import _ensure_project_on_path, get_project_root


def _team():
    """The team file module.

    Imported on use, not at module load: the CLI is installed as its own
    package and only puts the project root on ``sys.path`` when it needs
    something from it.
    """
    _ensure_project_on_path()
    from agent import team

    return team


BACKUP_FORMAT = "cowagent-backup"
# v2仅描述了多Agent布局。单一工作空间存档是
# 结构与 v1 生成的相同，因此它不断声明 v1 和
# 保持可通过较旧的 CowAgent 版本恢复。
BACKUP_VERSION = 2
_SINGLE_WORKSPACE_VERSION = 1
_SUPPORTED_BACKUP_VERSIONS = {_SINGLE_WORKSPACE_VERSION, BACKUP_VERSION}
_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SKIP_DIRS = {".git", "__pycache__", "tmp"}
_SKIP_FILES = {".DS_Store"}


def _data_root() -> Path:
    configured = os.environ.get("COW_DATA_DIR")
    return Path(configured).expanduser().resolve() if configured else Path(get_project_root()).resolve()


def _read_config(data_root: Path) -> dict:
    path = data_root / "config.json"
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _workspace_from_config(config: dict) -> Path:
    return Path(config.get("agent_workspace") or "~/cow").expanduser().resolve()


def _configured_workspaces(config: dict, fallback: Path):
    """Return archive profiles and whether config uses the explicit registry."""
    if config.get("agents"):
        from agent.registry import AgentRegistry

        registry = AgentRegistry.from_config(config)
        return registry.list(), True
    from agent.registry import AgentProfile

    return [
        AgentProfile("default", "Default", str(Path(fallback).resolve()))
    ], False


def _legacy_user_data_path(data_root: Path, config: dict) -> Path:
    appdata_dir = config.get("appdata_dir") or ""
    return (data_root / appdata_dir / "user_datas.pkl").resolve()


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([str(path.resolve()), str(root.resolve())]) == str(root.resolve())
    except (OSError, ValueError):
        return False


def _iter_workspace_files(
    workspace: Path,
    excluded: Set[Path],
    pruned_dirs: Optional[Set[Path]] = None,
):
    pruned = {Path(path).resolve() for path in (pruned_dirs or ())}
    if not workspace.is_dir():
        return
    for current, dirnames, filenames in os.walk(str(workspace), followlinks=False):
        current_path = Path(current)
        dirnames[:] = [
            name for name in dirnames
            if name not in _SKIP_DIRS
            and not (current_path / name).is_symlink()
            and (current_path / name).resolve() not in pruned
        ]
        for name in filenames:
            path = current_path / name
            if name in _SKIP_FILES or name.endswith((".pyc", ".pyo")):
                continue
            if path.is_symlink() or path.resolve() in excluded:
                continue
            if path.is_file():
                yield path


def create_backup_archive(
    output: Path,
    data_root: Path,
    workspace: Path,
    excluded_paths: Optional[Iterable[Path]] = None,
) -> dict:
    """Create a portable archive containing config and every agent workspace."""
    output = Path(output).expanduser().resolve()
    data_root = Path(data_root).expanduser().resolve()
    workspace = Path(workspace).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    excluded = {Path(path).expanduser().resolve() for path in (excluded_paths or [])}
    excluded.add(output)

    config_path = data_root / "config.json"
    config = _read_config(data_root)
    if config:
        # 花名册位于工作区旁边，因此请从树中读取它
        # 被存档，而不是从 config.json 恰好指向的任何地方存档。
        config = _team().resolve({**config, "agent_workspace": str(workspace)})
    legacy_path = _legacy_user_data_path(data_root, config)
    profiles, explicit_registry = _configured_workspaces(config, workspace)
    sources = {
        profile.id: Path(profile.workspace).expanduser().resolve()
        for profile in profiles
    }
    workspace_entries = []
    total_files = 0
    total_bytes = 0
    for profile in profiles:
        source = sources[profile.id]
        # 注册表仅拒绝完全相等的工作区，并且
        # 默认布局有意嵌套：默认代理拥有实例
        # root，而其他所有 Agent 都位于 `<root>/agents/<id>` 中。没有
        # 修剪，走默认 Agent 每隔一秒打包一次
        # 其存档根下的时间。
        nested = {
            other
            for other_id, other in sources.items()
            if other_id != profile.id and other != source and _is_within(other, source)
        }
        files = list(_iter_workspace_files(source, excluded, nested))
        size = sum(path.stat().st_size for path in files)
        archive_root = (
            f"agents/{profile.id}/workspace"
            if explicit_registry
            else "workspace"
        )
        workspace_entries.append((profile, source, archive_root, files, size))
        total_files += len(files)
        total_bytes += size

    manifest = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION if explicit_registry else _SINGLE_WORKSPACE_VERSION,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "layout": "agents" if explicit_registry else "workspace",
        "workspace_source": str(
            next(
                source
                for profile, source, _, _, _ in workspace_entries
                if profile.id
                == (config.get("default_agent_id") if explicit_registry else "default")
            )
        ),
        "agents": [
            {
                "id": profile.id,
                "name": profile.name,
                "enabled": profile.enabled,
                "workspace_source": str(source),
                "archive_root": archive_root,
                "workspace_files": len(files),
                "workspace_bytes": size,
            }
            for profile, source, archive_root, files, size in workspace_entries
        ],
        # 为用户维度保留。用户资产存在于
        # `<shared root>/users/<user_id>/`，所以今天他们在
        # 默认代理的工作区，此列表保持为空。宣布
        # 插槽现在意味着稍后添加每个用户存档根是一个附加项
        # 更改为 v2 清单而不是 v3 格式中断。
        "users": [],
        "contents": {
            "config": config_path.is_file(),
            "legacy_user_data": legacy_path.is_file(),
            "agent_workspaces": len(workspace_entries),
            "workspace_files": total_files,
            "workspace_bytes": total_bytes,
        },
    }

    temp_dir = Path(tempfile.mkdtemp(prefix="cowagent-backup-"))
    temp_archive = temp_dir / "backup.zip"
    try:
        with zipfile.ZipFile(
            str(temp_archive), "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            if config_path.is_file():
                # 存档将名册保留在 config.json 中，即使
                # live install 单独存储它。存档是快照，
                # 不是布局，将其折叠在这里保留一种格式
                # 每个版本都可以读写。
                if config:
                    archive.writestr(
                        "data/config.json",
                        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                    )
                else:
                    # 无法解析，所以没有什么可以折叠的，也没有办法折叠
                    # 重写它而不丢失它所包含的任何内容。
                    archive.write(str(config_path), "data/config.json")
            if legacy_path.is_file():
                archive.write(str(legacy_path), "data/user_datas.pkl")
            for _, source, archive_root, files, _ in workspace_entries:
                for path in files:
                    relative = path.relative_to(source).as_posix()
                    archive.write(str(path), f"{archive_root}/{relative}")
        os.replace(str(temp_archive), str(output))
        try:
            os.chmod(str(output), stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    finally:
        shutil.rmtree(str(temp_dir), ignore_errors=True)

    manifest["archive"] = str(output)
    return manifest


def _validate_archive(archive: zipfile.ZipFile) -> dict:
    names = {info.filename for info in archive.infolist()}
    if "manifest.json" not in names:
        raise ValueError("archive is missing manifest.json")
    try:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("archive manifest is invalid") from exc
    version = manifest.get("version")
    if (
        manifest.get("format") != BACKUP_FORMAT
        or version not in _SUPPORTED_BACKUP_VERSIONS
    ):
        raise ValueError("unsupported CowAgent backup format or version")

    # 用户维度已声明但尚未生成。检查过任何
    # 版本，因为该插槽也可以在单工作空间存档上移动。
    # 拒绝带有每个用户根的存档，而不是默默地拒绝
    # 删除它们：悄悄丢失用户记忆的恢复更糟糕
    # 比停止的那个。
    users = manifest.get("users", [])
    if not isinstance(users, list):
        raise ValueError("archive manifest has an invalid users list")
    if users:
        raise ValueError(
            "archive contains user-scoped workspaces, which this CowAgent "
            "version cannot restore; upgrade before restoring"
        )

    allowed_agent_roots = set()
    if version >= 2 and manifest.get("layout") == "agents":
        agents = manifest.get("agents")
        if not isinstance(agents, list) or not agents:
            raise ValueError("multi-agent archive manifest is missing agents")
        seen_ids = set()
        for item in agents:
            if not isinstance(item, dict):
                raise ValueError("multi-agent archive manifest is invalid")
            agent_id = item.get("id")
            root = item.get("archive_root")
            if not isinstance(agent_id, str) or not _AGENT_ID_RE.fullmatch(agent_id):
                raise ValueError("multi-agent archive contains an invalid Agent ID")
            if agent_id in seen_ids or root != f"agents/{agent_id}/workspace":
                raise ValueError("multi-agent archive contains duplicate or invalid roots")
            seen_ids.add(agent_id)
            allowed_agent_roots.add(root + "/")

    for info in archive.infolist():
        name = info.filename
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError(f"unsafe archive path: {name!r}")
        mode = (info.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK:
            raise ValueError(f"symbolic links are not allowed in backups: {name!r}")
        if allowed_agent_roots:
            allowed = name.startswith("data/") or any(
                name.startswith(root) for root in allowed_agent_roots
            )
        else:
            allowed = name.startswith(("data/", "workspace/"))
        if name != "manifest.json" and not allowed:
            raise ValueError(f"unexpected archive entry: {name!r}")
    return manifest


def _extract_validated(archive: zipfile.ZipFile, destination: Path) -> None:
    for info in archive.infolist():
        target = destination.joinpath(*PurePosixPath(info.filename).parts)
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info, "r") as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)


def _atomic_copy(source: Path, destination: Path, private: bool = False) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=destination.name + ".", dir=str(destination.parent))
    os.close(fd)
    try:
        shutil.copy2(str(source), temp_name)
        os.replace(temp_name, str(destination))
        if private:
            try:
                os.chmod(str(destination), stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def _multi_agent_destinations(
    manifest: dict,
    archived_config: dict,
    current_config: dict,
    workspace_root: Optional[Path],
):
    """Resolve safe restore destinations without trusting archived paths."""
    from agent.registry import AgentRegistry

    archived_registry = AgentRegistry.from_config(archived_config)
    manifest_ids = [item["id"] for item in manifest.get("agents", [])]
    configured_ids = [profile.id for profile in archived_registry.list()]
    if sorted(manifest_ids) != sorted(configured_ids):
        raise ValueError("archive Agent registry does not match its workspace manifest")

    current_registry = None
    if current_config.get("agents"):
        try:
            current_registry = AgentRegistry.from_config(current_config)
        except ValueError:
            current_registry = None

    # 显式的 --workspace 优先；否则在本机已经运行过时复用其实例根目录，
    # 只有在全新机器上才回退到单代理默认值。
    base = (
        Path(workspace_root).expanduser().resolve()
        if workspace_root is not None
        else _workspace_from_config(current_config)
    )
    default_agent_id = archived_registry.default_agent_id
    destinations = {}
    for agent_id in manifest_ids:
        current = None
        if workspace_root is None and current_registry is not None:
            try:
                current = current_registry.get(agent_id, require_enabled=False)
            except KeyError:
                pass
        if current is not None:
            destinations[agent_id] = current.workspace_path.resolve()
            continue
        # Mirror AgentRegistry.from_config：默认Agent拥有该实例
        # root，所有其他特工都会降落在 `agents/<id>` 中。恢复到
        # 注册表派生的相同布局将工作区键保留在
        # 恢复的配置是冗余的而不是承重的，因此需要手动删除
        # 稍后无法将代理从其恢复的数据中重新定位。
        destination = (
            base if agent_id == default_agent_id else base / "agents" / agent_id
        )
        if not _is_within(destination, base):
            raise ValueError(f"unsafe Agent workspace destination: {agent_id}")
        destinations[agent_id] = destination
    if len({str(path) for path in destinations.values()}) != len(destinations):
        raise ValueError("multiple Agents resolve to the same workspace destination")
    return archived_registry, destinations


def restore_backup_archive(
    archive_path: Path,
    data_root: Path,
    workspace: Optional[Path] = None,
) -> dict:
    """Merge a validated backup into the selected data root and workspace."""
    archive_path = Path(archive_path).expanduser().resolve()
    data_root = Path(data_root).expanduser().resolve()
    current_config = _read_config(data_root)

    temp_dir = Path(tempfile.mkdtemp(prefix="cowagent-restore-"))
    try:
        with zipfile.ZipFile(str(archive_path), "r") as archive:
            manifest = _validate_archive(archive)
            _extract_validated(archive, temp_dir)

        archived_config_path = temp_dir / "data" / "config.json"
        archived_config = {}
        if archived_config_path.is_file():
            with archived_config_path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            if not isinstance(value, dict):
                raise ValueError("archived config.json must contain an object")
            archived_config = value

        restored_config = dict(archived_config)
        multi_agent = (
            manifest.get("version", 1) >= 2
            and manifest.get("layout") == "agents"
        )
        destinations = {}
        if multi_agent:
            if not restored_config.get("agents"):
                raise ValueError("multi-agent archive is missing its Agent registry")
            archived_registry, destinations = _multi_agent_destinations(
                manifest, restored_config, current_config, workspace
            )
            restored_agents = []
            for raw in restored_config["agents"]:
                item = dict(raw)
                item["workspace"] = str(destinations[item["id"]])
                restored_agents.append(item)
            restored_config["agents"] = restored_agents
            default_agent_id = archived_registry.default_agent_id
            restored_config["default_agent_id"] = default_agent_id
            target_workspace = destinations[default_agent_id]
            # 保持单键与旧扩展保持一致
            # 即使配置了显式注册表，也要检查它。
            restored_config["agent_workspace"] = str(target_workspace)
            from agent.registry import AgentRegistry

            AgentRegistry.from_config(restored_config)
        else:
            if workspace is not None:
                target_workspace = Path(workspace).expanduser().resolve()
            elif current_config.get("agent_workspace"):
                target_workspace = _workspace_from_config(current_config)
            else:
                # 不要信任存档控制的绝对目的地
                # 新鲜机。 Portable 将默认恢复为 ~/cow，除非
                # 操作员提供--workspace。
                target_workspace = Path("~/cow").expanduser().resolve()
            if restored_config:
                restored_config["agent_workspace"] = str(target_workspace)

        if restored_config:
            appdata_dir = restored_config.get("appdata_dir") or ""
            if appdata_dir:
                archived_appdata = (data_root / appdata_dir).resolve()
                if not _is_within(archived_appdata, data_root):
                    # 将旧用户数据保留在选定的数据根下
                    # 而不是写入存档控制的路径。
                    restored_config["appdata_dir"] = ""
        restored_files = 0
        restored_agents = []
        if multi_agent:
            manifest_agents = {item["id"]: item for item in manifest["agents"]}
            for agent_id, target in destinations.items():
                archive_root = manifest_agents[agent_id]["archive_root"]
                source_root = temp_dir.joinpath(*PurePosixPath(archive_root).parts)
                agent_files = 0
                if source_root.is_dir():
                    for source in _iter_workspace_files(source_root, set()):
                        relative = source.relative_to(source_root)
                        destination = target / relative
                        if not _is_within(destination, target):
                            raise ValueError(
                                f"unsafe Agent workspace destination: {agent_id}/{relative}"
                            )
                        _atomic_copy(source, destination)
                        restored_files += 1
                        agent_files += 1
                restored_agents.append(
                    {"id": agent_id, "workspace": str(target), "files": agent_files}
                )
        else:
            source_root = temp_dir / "workspace"
            if source_root.is_dir():
                for source in _iter_workspace_files(source_root, set()):
                    relative = source.relative_to(source_root)
                    destination = target_workspace / relative
                    if not _is_within(destination, target_workspace):
                        raise ValueError(f"unsafe workspace destination: {relative}")
                    _atomic_copy(source, destination)
                    restored_files += 1

        # 仅在验证每个工作区文件后才发布配置
        # 并复制。复制失败不能使配置指向部分
        # 多代理恢复。
        if restored_config:
            # 将存档的单个 blob 实时拆分回两个文件
            # 安装保留：花名册在 config.json 中传播，但它是
            # 不再从那里阅读。
            team = _team()
            published = {
                key: value
                for key, value in restored_config.items()
                if key not in team.TEAM_KEYS
            }
            if multi_agent:
                team.write(
                    published,
                    {
                        "agents": team.compact(
                            restored_config["agents"], published, default_agent_id
                        ),
                        "default_agent_id": default_agent_id,
                        "channel_instances": restored_config.get("channel_instances") or [],
                    },
                )
            config_temp = temp_dir / "restored-config.json"
            with config_temp.open("w", encoding="utf-8") as handle:
                json.dump(published, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            _atomic_copy(config_temp, data_root / "config.json", private=True)

        legacy_source = temp_dir / "data" / "user_datas.pkl"
        if legacy_source.is_file():
            effective_config = restored_config or current_config
            legacy_destination = _legacy_user_data_path(data_root, effective_config)
            _atomic_copy(legacy_source, legacy_destination, private=True)

        return {
            "manifest": manifest,
            "workspace": str(target_workspace),
            "workspace_files": restored_files,
            "agents": restored_agents,
            "config_restored": bool(restored_config),
            "legacy_user_data_restored": legacy_source.is_file(),
        }
    finally:
        shutil.rmtree(str(temp_dir), ignore_errors=True)


@click.command("backup")
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output .zip path (default: ./cow-backup-<timestamp>.zip).",
)
def backup_command(output: Optional[Path]):
    """Back up config, persona, memory, skills, knowledge, and schedules."""
    data_root = _data_root()
    config = _read_config(data_root)
    workspace = _workspace_from_config(config)
    if output is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output = Path.cwd() / f"cow-backup-{stamp}.zip"
    result = create_backup_archive(output, data_root, workspace)
    click.echo(click.style("✓ Backup created", fg="green"))
    click.echo(f"  Archive: {result['archive']}")
    click.echo(f"  Agent workspaces: {result['contents']['agent_workspaces']}")
    click.echo(f"  Workspace files: {result['contents']['workspace_files']}")
    click.echo("  Keep this archive private: it may contain API keys and personal data.")


@click.command("restore")
@click.argument("archive", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--workspace",
    type=click.Path(file_okay=False, path_type=Path),
    help="Restore a single workspace here, or use this as the root for Agent subdirectories.",
)
@click.option("--yes", is_flag=True, help="Confirm overwriting matching files.")
def restore_command(archive: Path, workspace: Optional[Path], yes: bool):
    """Restore a backup without deleting unrelated destination files."""
    from cli.commands.process import _read_pid

    pid = _read_pid()
    if pid:
        raise click.ClickException(
            f"CowAgent is running (PID: {pid}). Run 'cow stop' before restoring."
        )
    if not yes:
        click.confirm(
            "Restore this archive and overwrite matching config/workspace files?",
            abort=True,
        )

    data_root = _data_root()
    current_config = _read_config(data_root)
    current_workspace = _workspace_from_config(current_config)
    has_current_data = (data_root / "config.json").is_file() or current_workspace.is_dir()
    if has_current_data:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        rollback = archive.resolve().parent / f"cow-pre-restore-{stamp}.zip"
        create_backup_archive(
            rollback,
            data_root,
            current_workspace,
            excluded_paths={archive.resolve()},
        )
        click.echo(f"Rollback backup: {rollback}")

    result = restore_backup_archive(archive, data_root, workspace)
    click.echo(click.style("✓ Backup restored", fg="green"))
    click.echo(f"  Workspace: {result['workspace']}")
    if result["agents"]:
        click.echo(f"  Agent workspaces: {len(result['agents'])}")
    click.echo(f"  Restored files: {result['workspace_files']}")
