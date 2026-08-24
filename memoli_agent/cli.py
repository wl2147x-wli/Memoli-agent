"""Memoli 可安装命令入口。"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from memoli_agent.agent.working.models import WorkingStateSnapshot
from memoli_agent.agent.working.presentation import (
    render_working_card,
    snapshot_to_json,
)
from memoli_agent.agent.working.repository import (
    WorkingStateReadError,
    read_checkpoint_readonly,
)
from memoli_agent.bootstrap.app import build_app_runtime
from memoli_agent.bootstrap.config import AppConfig, load_config


def main(argv: Sequence[str] | None = None) -> int:
    """解析命令并只在 chat 路径创建 Runtime。"""

    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    command = args.command or "chat"
    try:
        config = _load_cli_config(args)
        if command == "checkpoint":
            return _run_checkpoint(config, args)
        asyncio.run(_run_chat(config, args.session))
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, TypeError, ValueError) as exc:
        print(f"配置或启动失败：{_safe_error(exc)}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"运行失败：{type(exc).__name__}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memoli")
    _add_common_arguments(parser, suppress_defaults=False)
    parser.add_argument("--version", action="version", version=_version())
    subparsers = parser.add_subparsers(dest="command")
    chat = subparsers.add_parser("chat", help="启动前台 CLI 对话")
    _add_common_arguments(chat, suppress_defaults=True)
    checkpoint = subparsers.add_parser(
        "checkpoint",
        help="只读查询工作 checkpoint",
    )
    _add_common_arguments(checkpoint, suppress_defaults=True)
    checkpoint.add_argument("--json", action="store_true", help="输出单个 JSON 对象")
    return parser


def _add_common_arguments(
    parser: argparse.ArgumentParser,
    *,
    suppress_defaults: bool,
) -> None:
    default_none: object = argparse.SUPPRESS if suppress_defaults else None
    default_session: object = argparse.SUPPRESS if suppress_defaults else "local"
    parser.add_argument("--config", default=default_none, help="TOML 配置文件")
    parser.add_argument(
        "--workspace",
        default=default_none,
        help="覆盖 runtime workspace",
    )
    parser.add_argument(
        "--session",
        default=default_session,
        help="本地 CLI 会话标识",
    )


def _load_cli_config(args: argparse.Namespace) -> AppConfig:
    config_arg = getattr(args, "config", None)
    if config_arg is not None and not Path(config_arg).is_file():
        raise ValueError("显式配置文件不存在。")
    config = load_config(config_arg or "config.toml")
    workspace = getattr(args, "workspace", None)
    if workspace is not None:
        if not str(workspace).strip():
            raise ValueError("workspace 不能为空。")
        config.runtime.workspace = str(workspace)
    args.session = _normalize_session_id(str(getattr(args, "session", "local")))
    return config


async def _run_chat(config: AppConfig, session_id: str) -> None:
    runtime = build_app_runtime(config)
    try:
        await runtime.start()
        await runtime.run(chat_id=session_id)
    finally:
        await runtime.shutdown()


def _run_checkpoint(config: AppConfig, args: argparse.Namespace) -> int:
    session_key = f"cli:{args.session}"
    if not config.working_memory.enabled:
        snapshot = WorkingStateSnapshot(session_key, "disabled")
        _print_snapshot(snapshot, bool(args.json))
        return 3
    try:
        checkpoint = read_checkpoint_readonly(
            config.working_memory.database,
            session_key,
        )
    except WorkingStateReadError as exc:
        snapshot = WorkingStateSnapshot(session_key, exc.code)
        _print_snapshot(snapshot, bool(args.json))
        return 1
    snapshot = WorkingStateSnapshot(
        session_key,
        "available" if checkpoint is not None else "not-found",
        checkpoint=checkpoint,
        runtime_status=None,
    )
    _print_snapshot(snapshot, bool(args.json))
    return 0 if checkpoint is not None else 3


def _print_snapshot(snapshot: WorkingStateSnapshot, as_json: bool) -> None:
    print(snapshot_to_json(snapshot) if as_json else render_working_card(snapshot))


def _normalize_session_id(value: str) -> str:
    session = value.strip()
    if (
        not session
        or len(session) > 128
        or ":" in session
        or any(ord(char) < 32 for char in session)
    ):
        raise ValueError("session 必须是 1-128 字符且不能包含冒号或控制字符。")
    return session


def _version() -> str:
    try:
        return version("memoli-agent")
    except PackageNotFoundError:
        return "0.1.0"


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    text = re.sub(
        r"(?i)(api[_-]?key|authorization|cookie)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        text,
    )
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", text)
    return text[:500] or type(exc).__name__


if __name__ == "__main__":
    raise SystemExit(main())
