"""独立宿主 Skill 管理 CLI。"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from memoli_agent.bootstrap.config import AppConfig, load_config
from memoli_agent.bootstrap.skills import build_skill_components


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    config = load_config(arguments.config)
    components = build_skill_components(config, force=True)
    assert components is not None
    try:
        try:
            command = arguments.command
            if command == "validate":
                package = components.admin.validate(arguments.source)
                _print(
                    {
                        "success": True,
                        "name": package.manifest.name,
                        "version": package.manifest.version,
                        "description": package.manifest.description,
                        "requirements": package.manifest.requirements.to_dict(),
                        "requested_permissions": (
                            package.manifest.requested_permissions
                        ),
                        "risk": package.manifest.risk,
                        "content_hash": package.content_hash,
                        "files": list(package.files),
                        "total_bytes": package.total_bytes,
                    }
                )
            elif command == "install":
                _print(asdict(components.admin.install(arguments.source)))
            elif command == "list":
                _print(
                    [
                        components.admin.inspect(
                            item, tools=_configured_tool_names(config)
                        )
                        for item in components.admin.list(arguments.name)
                    ]
                )
            elif command == "show":
                item = components.admin.show(arguments.name, arguments.version)
                if item is None:
                    raise ValueError("Skill 版本不存在。")
                _print(
                    components.admin.inspect(item, tools=_configured_tool_names(config))
                )
            elif command in {"activate", "deprecate", "revoke", "rollback"}:
                operation = getattr(components.admin, command)
                if command == "rollback":
                    result = operation(
                        arguments.name,
                        actor=arguments.actor,
                        reason=arguments.reason,
                    )
                else:
                    result = operation(
                        arguments.name,
                        arguments.version,
                        actor=arguments.actor,
                        reason=arguments.reason,
                    )
                _print(asdict(result))
            else:  # pragma: no cover - argparse 已限制选择
                parser.error("未知命令。")
        except (OSError, sqlite3.Error, ValueError) as exc:
            _print(
                {
                    "success": False,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            return 2
    finally:
        components.close()
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memoli-skills")
    parser.add_argument("--config", default="config.toml", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="静态校验 Skill 包")
    validate.add_argument("source", type=Path)
    install = commands.add_parser("install", help="安装不可变 Skill 版本")
    install.add_argument("source", type=Path)
    listing = commands.add_parser("list", help="列出注册版本")
    listing.add_argument("--name")
    show = commands.add_parser("show", help="查看 Skill 版本")
    show.add_argument("name")
    show.add_argument("version", nargs="?")
    for name in ("activate", "deprecate", "revoke", "rollback"):
        command = commands.add_parser(name)
        command.add_argument("name")
        if name != "rollback":
            command.add_argument("version")
        command.add_argument("--actor", default="cli")
        command.add_argument("--reason", required=True)
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _configured_tool_names(config: AppConfig) -> set[str]:
    """返回不需要外部连接即可确定的本地工具名称。"""

    names = {
        "code_run",
        "file_read",
        "file_patch",
        "file_write",
        "update_working_checkpoint",
        "ask_user",
        "start_long_term_update",
        "time",
        "memory_recall",
        "skill_load",
    }
    tools = config.tools
    if tools.memory_manage_enabled:
        names.add("memory_manage")
    if tools.subagent_tool_enabled:
        names.update({"spawn_subagent", "manage_subagent"})
    return names


if __name__ == "__main__":
    raise SystemExit(main())
