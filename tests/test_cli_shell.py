from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import subprocess
import sys
import threading
import tomllib
from pathlib import Path
from typing import Any

import pytest

import memoli_agent.cli as cli_entry
from memoli_agent.agent.context import ContextBuilder
from memoli_agent.agent.core.passive_turn import PassiveTurnPipeline
from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.loop import AgentLoop
from memoli_agent.agent.provider import EchoProvider
from memoli_agent.agent.runner import AgentRunner
from memoli_agent.agent.session import SessionManager
from memoli_agent.agent.tools.control import WorkingStateStore
from memoli_agent.agent.working.models import (
    CheckpointPatch,
    RuntimeStatus,
)
from memoli_agent.agent.working.presentation import (
    render_working_card,
    snapshot_to_dict,
)
from memoli_agent.agent.working.repository import (
    WorkingStateReadError,
    WorkingStateRepository,
    read_checkpoint_readonly,
)
from memoli_agent.bootstrap.config import AppConfig
from memoli_agent.bootstrap.inspection import RuntimeInspector
from memoli_agent.bus.events import OutboundMessage
from memoli_agent.bus.queue import MessageBus
from memoli_agent.channels.cli import CLIState, run_cli
from memoli_agent.channels.commands import CommandContext, build_command_registry
from memoli_agent.presentation.events import (
    PresentationEvent,
    PresentationEventHub,
    PresentationEventKind,
)
from memoli_agent.presentation.renderer import TerminalRenderer


def _write_config(path: Path, database: Path, *, enabled: bool = True) -> None:
    escaped = database.as_posix()
    path.write_text(
        f'[working_memory]\nenabled = {str(enabled).lower()}\ndatabase = "{escaped}"\n',
        encoding="utf-8",
    )


def _write_echo_chat_config(path: Path, workspace: Path) -> None:
    path.write_text(
        f'[runtime]\nworkspace = "{workspace.as_posix()}"\n'
        '[llm]\nprovider = "echo"\nmodel = "echo"\n'
        "[trajectory]\nenabled = false\n"
        "[memory]\nenabled = false\n"
        "[working_memory]\nenabled = false\n"
        '[tools]\ncode_runner = "disabled"\n'
        "[skills]\nenabled = false\n"
        "[plugins]\nenabled = []\ntrusted = []\n"
        "[subagent]\nenabled = false\n"
        "[proactive]\nenabled = false\n"
        "[mcp]\nenabled = false\n",
        encoding="utf-8",
    )


def test_pyproject_exposes_both_console_scripts_and_valid_authors() -> None:
    with Path("pyproject.toml").open("rb") as file:
        project = tomllib.load(file)["project"]

    assert project["scripts"] == {
        "memoli": "memoli_agent.cli:main",
        "memoli-skills": "memoli_agent.skills_cli:main",
    }
    assert project["authors"] == [{"name": "Memoli-agent contributors"}]


def test_parser_accepts_common_options_before_or_after_subcommand() -> None:
    parser = cli_entry._build_parser()
    before = parser.parse_args(["--session", "before", "chat"])
    after = parser.parse_args(["chat", "--session", "after"])

    assert before.session == "before"
    assert after.session == "after"


def test_help_and_version_do_not_build_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(_: AppConfig) -> None:
        raise AssertionError("不应构建 Runtime")

    monkeypatch.setattr(cli_entry, "build_app_runtime", forbidden)
    with pytest.raises(SystemExit) as help_exit:
        cli_entry.main(["--help"])
    with pytest.raises(SystemExit) as version_exit:
        cli_entry.main(["--version"])

    assert help_exit.value.code == 0
    assert version_exit.value.code == 0


def test_chat_start_failure_still_shuts_down_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingRuntime:
        shutdown_called = False

        async def start(self) -> None:
            raise RuntimeError("start failed")

        async def run(self, *, chat_id: str) -> None:
            raise AssertionError(chat_id)

        async def shutdown(self) -> None:
            self.shutdown_called = True

    runtime = FailingRuntime()
    monkeypatch.setattr(cli_entry, "build_app_runtime", lambda _: runtime)

    with pytest.raises(RuntimeError, match="start failed"):
        asyncio.run(cli_entry._run_chat(AppConfig(), "local"))
    assert runtime.shutdown_called is True


def test_legacy_main_uses_unified_echo_chat_entry(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    _write_echo_chat_config(config, tmp_path / "workspace")
    result = subprocess.run(
        [
            sys.executable,
            str(Path("main.py").resolve()),
            "--config",
            str(config),
            "--session",
            "legacy",
        ],
        cwd=tmp_path,
        input="你好\n/exit\n",
        text=True,
        capture_output=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Memory-focused Agent Runtime" in result.stdout
    assert "cli:legacy" in result.stdout
    assert "再见。" in result.stdout


def test_main_maps_keyboard_interrupt_to_shell_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_entry, "_load_cli_config", lambda _: AppConfig())

    def interrupt(coroutine: Any) -> None:
        coroutine.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_entry.asyncio, "run", interrupt)

    assert cli_entry.main([]) == 130


def test_checkpoint_command_returns_single_json_without_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "working.db"
    config = tmp_path / "config.toml"
    _write_config(config, database)
    repository = WorkingStateRepository(database)
    repository.patch(
        "cli:demo",
        CheckpointPatch(
            objective="实现 CLI",
            current_step="查询 checkpoint",
            key_info="只读",
            status="completed",
        ),
    )
    repository.close()

    def forbidden(_: AppConfig) -> None:
        raise AssertionError("checkpoint 不应构建 Runtime")

    monkeypatch.setattr(cli_entry, "build_app_runtime", forbidden)
    code = cli_entry.main(
        ["checkpoint", "--config", str(config), "--session", "demo", "--json"]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 0
    assert captured.err == ""
    assert payload["schema_version"] == 1
    assert payload["session_key"] == "cli:demo"
    assert payload["checkpoint"]["trust"] == "agent"
    assert payload["checkpoint"]["status"] == "completed"
    assert payload["runtime_status"] is None


def test_checkpoint_missing_and_disabled_are_distinct_and_do_not_create_db(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "absent" / "working.db"
    config = tmp_path / "missing.toml"
    _write_config(config, missing)

    assert cli_entry.main(["checkpoint", "--config", str(config), "--json"]) == 3
    missing_payload = json.loads(capsys.readouterr().out)
    assert missing_payload["availability"] == "not-found"
    assert not missing.exists()
    assert not missing.parent.exists()

    disabled_config = tmp_path / "disabled.toml"
    _write_config(disabled_config, missing, enabled=False)
    assert (
        cli_entry.main(["checkpoint", "--config", str(disabled_config), "--json"]) == 3
    )
    disabled_payload = json.loads(capsys.readouterr().out)
    assert disabled_payload["availability"] == "disabled"


def test_readonly_checkpoint_rejects_unknown_schema(tmp_path: Path) -> None:
    database = tmp_path / "future.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA user_version=99")
    connection.close()

    with pytest.raises(WorkingStateReadError) as error:
        read_checkpoint_readonly(database, "cli:local")
    assert error.value.code == "unsupported-schema"


def test_readonly_checkpoint_reports_busy_without_mutation(tmp_path: Path) -> None:
    database = tmp_path / "busy.db"
    repository = WorkingStateRepository(database)
    repository.patch("cli:local", CheckpointPatch(objective="保持不变"))
    locker = sqlite3.connect(database)
    locker.execute("PRAGMA locking_mode=EXCLUSIVE")
    locker.execute("BEGIN EXCLUSIVE")
    locker.execute(
        "UPDATE working_checkpoints SET objective='未提交' "
        "WHERE session_key='cli:local'"
    )

    with pytest.raises(WorkingStateReadError) as error:
        read_checkpoint_readonly(database, "cli:local")
    assert error.value.code == "busy"

    locker.rollback()
    locker.close()
    committed = repository.get("cli:local")
    assert committed is not None and committed.objective == "保持不变"
    repository.close()


def test_readonly_checkpoint_sees_one_committed_revision(tmp_path: Path) -> None:
    database = tmp_path / "working.db"
    repository = WorkingStateRepository(database)
    first = repository.patch(
        "cli:local",
        CheckpointPatch(objective="已提交", key_info="v1"),
    )
    writer = sqlite3.connect(database)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute(
        "UPDATE working_checkpoints SET objective='未提交', revision=99 "
        "WHERE session_key='cli:local'"
    )

    read = read_checkpoint_readonly(database, "cli:local")
    assert read is not None
    assert read.objective == "已提交"
    assert read.revision == first.revision

    writer.rollback()
    writer.close()
    repository.close()


def test_snapshot_keeps_agent_and_runtime_trust_separate() -> None:
    state = WorkingStateStore()
    checkpoint = state.update_checkpoint(
        "cli:local",
        "模型声称已经完成",
        "cli-sop",
        objective="测试",
        current_step="完成",
        next_action="退出",
        constraints=("不能猜测",),
    )
    state.runtime_statuses["cli:local"] = RuntimeStatus(
        iteration=2,
        max_iterations=12,
        last_tool="file_read",
        last_tool_status="success",
    )

    snapshot = state.snapshot("cli:local")
    payload = snapshot_to_dict(snapshot)
    card = render_working_card(snapshot)

    assert payload["checkpoint"]["trust"] == "agent"
    assert payload["runtime_status"]["trust"] == "runtime"
    assert payload["checkpoint"]["revision"] == checkpoint.revision
    assert "Agent Checkpoint (trust=agent)" in card
    assert "Runtime Status (trust=runtime)" in card


def test_checkpoint_inspection_does_not_mutate_stale_or_completed() -> None:
    state = WorkingStateStore()
    completed = state.update_checkpoint("cli:one", "完成", "")
    completed = state.repository.complete("cli:one", completed.revision)
    state.update_checkpoint("cli:two", "另一个任务", "")
    state.repository.mark_stale_except("cli:two")
    before = state.get_checkpoint("cli:one")

    _ = state.snapshot("cli:one")
    after = state.get_checkpoint("cli:one")

    assert before == after
    assert after is not None and after.status == "completed" and after.stale is False


def test_local_commands_bypass_bus_and_clear_only_session_history() -> None:
    sessions = SessionManager()
    working = WorkingStateStore()
    working.update_checkpoint("cli:local", "保留 checkpoint", "")
    inspector = RuntimeInspector(AppConfig(), working)
    state = CLIState("local", last_trace_id="trace-1")
    context = CommandContext(state, inspector, sessions)
    registry = build_command_registry()

    assert "当前工作卡片" in registry.route("/checkpoint", context).message
    assert registry.route("/trace", context).message == "trace: trace-1"
    assert registry.route("/unknown", context).handled
    assert registry.route("//literal", context).forwarded_text == "/literal"
    assert "未删除" in registry.route("/clear", context).message
    # §3.1：Session 不再承载消息历史；未装配持久 epoch 存储时 /clear 保持旧 epoch。
    assert not hasattr(sessions.get_or_create("cli:local"), "get_history")
    assert working.get_checkpoint("cli:local") is not None


def test_context_command_renders_layered_diagnostics() -> None:
    """§8.2 /context 显示 epoch/恢复/压缩/各层/frontier/熔断/outbox 诊断。"""

    from memoli_agent.agent.context_management import (
        ConservativeTokenEstimator,
        ContextCompiler,
        ContextCompilerSettings,
        InMemoryContextStateRepository,
    )
    from memoli_agent.agent.trajectory import InMemoryTrajectoryStore
    from memoli_agent.agent.types import ChatMessage

    store = InMemoryTrajectoryStore()
    repo = InMemoryContextStateRepository()
    compiler = ContextCompiler(
        repo,
        ConservativeTokenEstimator(),
        ContextCompilerSettings(
            context_window_tokens=1_000,
            max_output_tokens=50,
            safety_margin_tokens=20,
            recent_tail_tokens=120,
            archive_tokens=80,
            plugin_max_tokens=30,
        ),
    )
    compiler.compile(
        session_key="cli:local",
        session_instance_id="i",
        messages=[ChatMessage("system", "security"), ChatMessage("user", "hello")],
        tools=[],
    )
    config = AppConfig()
    inspector = RuntimeInspector(
        config=config, working_state=None, context_compiler=compiler
    )
    sessions = SessionManager()
    state = CLIState("local")
    context = CommandContext(
        state, inspector, sessions, trajectory_store=store, context_repository=repo
    )
    registry = build_command_registry()
    result = registry.route("/context", context)

    assert result.handled
    message = result.message
    assert "context: ON" in message
    assert "epoch: 1" in message  # current_epoch_sync 纯读默认 1（未初始化 epoch）
    assert "recovery: redacted (restorable=true)" in message
    assert "reduction:" in message
    assert "compaction:" in message
    assert "circuit closed" in message
    assert "outbox:" in message
    assert "frontier:" in message
    assert "effective budget:" in message
    assert "hashes:" in message
    # §8.3 安全：诊断输出不含 payload/API key/隐藏 reasoning/embedding 原文
    for forbidden in ("Bearer", "api_key", "embedding", "reasoning"):
        assert forbidden not in message


def test_context_command_off_when_disabled() -> None:
    """§8.2 context 关闭时 /context 显示 OFF，不触碰编译器。"""

    config = AppConfig()
    config.context.enabled = False
    inspector = RuntimeInspector(config=config, working_state=None)
    registry = build_command_registry()
    state = CLIState("local")
    context = CommandContext(state, inspector, SessionManager())
    result = registry.route("/context", context)

    assert result.handled
    assert result.message == "context: OFF"


def test_context_command_unavailable_without_inspector() -> None:
    """§8.2 未装配 inspector 时 /context 降级为 unavailable（不抛错）。"""

    registry = build_command_registry()
    state = CLIState("local")
    context = CommandContext(state, None, SessionManager())
    result = registry.route("/context", context)

    assert result.handled
    assert result.message == "context: unavailable"


def test_context_command_does_not_leak_sensitive_content() -> None:
    """§8.3 /context 诊断输出只含哈希/计数/稳定原因——即便编译消息中含 API
    key、隐藏 reasoning、embedding 原文，渲染结果也不得回显这些原文。"""

    from memoli_agent.agent.context_management import (
        ConservativeTokenEstimator,
        ContextCompiler,
        ContextCompilerSettings,
        InMemoryContextStateRepository,
    )
    from memoli_agent.agent.trajectory import InMemoryTrajectoryStore
    from memoli_agent.agent.types import ChatMessage

    secret = "sk-test-secret-Bearer-key-1234567890abcdef"
    reasoning = "<hidden_reasoning>internal chain of thought</hidden_reasoning>"
    embedding = "EMBEDDING_VECTOR:[0.11,0.22,0.33,0.44]"
    store = InMemoryTrajectoryStore()
    repo = InMemoryContextStateRepository()
    compiler = ContextCompiler(
        repo,
        ConservativeTokenEstimator(),
        ContextCompilerSettings(
            context_window_tokens=4_000,
            max_output_tokens=50,
            safety_margin_tokens=20,
            recent_tail_tokens=120,
            archive_tokens=80,
            plugin_max_tokens=30,
        ),
    )
    # 这些敏感原文确实进入编译消息；诊断面只应记其哈希，不得回显原文。
    compiler.compile(
        session_key="cli:local",
        session_instance_id="i",
        messages=[
            ChatMessage("system", "security"),
            ChatMessage("user", f"my api key is {secret} please help"),
            ChatMessage("assistant", reasoning),
            ChatMessage("system", embedding),
        ],
        tools=[],
    )
    config = AppConfig()
    inspector = RuntimeInspector(
        config=config, working_state=None, context_compiler=compiler
    )
    sessions = SessionManager()
    state = CLIState("local")
    context = CommandContext(
        state, inspector, sessions, trajectory_store=store, context_repository=repo
    )
    registry = build_command_registry()
    result = registry.route("/context", context)

    assert result.handled
    message = result.message
    assert "context: ON" in message
    for forbidden in (secret, reasoning, embedding, "Bearer"):
        assert forbidden not in message, f"/context 泄露敏感原文：{forbidden}"


def test_cli_routes_only_literal_prompt_to_inbound_queue() -> None:
    bus = MessageBus()
    inputs = iter(["/status", "//literal", "/exit"])
    output: list[str] = []

    def reader(_: str) -> str:
        return next(inputs)

    def writer(*values: object, **_: Any) -> None:
        output.append("".join(str(value) for value in values))

    async def scenario() -> str:
        await run_cli(bus, input_reader=reader, writer=writer)
        return (await bus.consume_inbound()).content

    assert asyncio.run(scenario()) == "/literal"
    assert any("Runtime status: unavailable" in line for line in output)
    assert "\x1b" not in "".join(output)


def test_cli_eof_exits_without_publishing_a_turn() -> None:
    bus = MessageBus()
    output: list[str] = []

    def reader(_: str) -> str:
        raise EOFError

    asyncio.run(
        run_cli(
            bus,
            input_reader=reader,
            writer=lambda value, **_: output.append(str(value)),
        )
    )

    assert bus._inbound.empty()
    assert output[-1].strip() == "再见。"


def test_cli_echo_e2e_outputs_trace_and_stays_serial() -> None:
    bus = MessageBus()
    sessions = SessionManager()
    pipeline = PassiveTurnPipeline(
        session_manager=sessions,
        context_builder=ContextBuilder("Memoli", "system"),
        reasoner=Reasoner(EchoProvider()),
    )
    loop = AgentLoop(bus, AgentRunner(passive_turn_pipeline=pipeline))
    reply_ready = threading.Event()
    outputs: list[str] = []
    calls = 0

    def reader(_: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            return "你好"
        if calls == 2:
            assert reply_ready.wait(2)
            return "/trace"
        return "/exit"

    def writer(*values: object, **_: Any) -> None:
        line = "".join(str(value) for value in values)
        outputs.append(line)
        if "Echo: 你好" in line:
            reply_ready.set()

    async def scenario() -> None:
        await loop.start()
        try:
            await run_cli(
                bus,
                session_manager=sessions,
                input_reader=reader,
                writer=writer,
            )
        finally:
            await loop.stop()

    asyncio.run(scenario())
    assert any("Memoli > Echo: 你好" in line for line in outputs)
    trace_lines = [line for line in outputs if line.startswith("trace: ")]
    assert trace_lines and all("unavailable" not in line for line in trace_lines)
    # §3.1：Session 不再承载消息历史；该 echo 回路用 NullTrajectoryStore（不记录
    # committed turn），turn 事实由 echo 输出与 trace_id 共同体现，无需 Session 历史。
    assert not hasattr(sessions.get_or_create("cli:local"), "get_history")


def test_presentation_hub_filters_thinking_and_arguments() -> None:
    from memoli_agent.agent.llm.contracts import ModelEvent, ModelEventKind

    hub = PresentationEventHub()

    async def scenario() -> tuple[str, str]:
        await hub.publish_model_event(
            "cli:local",
            "trace",
            ModelEvent(ModelEventKind.THINKING_DELTA, text="hidden"),
        )
        await hub.publish_model_event(
            "cli:local",
            "trace",
            ModelEvent(
                ModelEventKind.TOOL_CALL_DELTA,
                tool_name="file_read",
                arguments_delta='{"path":"secret"}',
            ),
        )
        tool = await asyncio.wait_for(hub.consume(), 1)
        await hub.publish_model_event(
            "cli:local",
            "trace",
            ModelEvent(ModelEventKind.TEXT_DELTA, text="visible"),
        )
        text = await asyncio.wait_for(hub.consume(), 1)
        return tool.text, text.text

    assert asyncio.run(scenario()) == ("file_read", "visible")


def test_presentation_hub_labels_bounded_reasoning_summary() -> None:
    from memoli_agent.agent.llm.contracts import ModelEvent, ModelEventKind

    hub = PresentationEventHub(max_text_chars=8)

    async def scenario() -> PresentationEvent:
        await hub.publish_model_event(
            "cli:local",
            "trace",
            ModelEvent(
                ModelEventKind.REASONING_SUMMARY_DELTA,
                text="safe-summary-is-long",
            ),
        )
        return await asyncio.wait_for(hub.consume(), 1)

    event = asyncio.run(scenario())
    assert event.kind is PresentationEventKind.REASONING_SUMMARY
    assert event.text == "safe-sum"


def test_renderer_marks_reasoning_summary_without_mixing_final_answer() -> None:
    output: list[str] = []

    async def scenario() -> None:
        renderer = TerminalRenderer("cli:local", output.append, color=False)
        await renderer.start()
        renderer.submit_event(
            PresentationEvent(
                PresentationEventKind.REASONING_SUMMARY,
                "cli:local",
                "trace",
                "检查工具结果",
            )
        )
        renderer.submit_outbound(
            OutboundMessage("cli", "local", "最终回答", {"trace_id": "trace"})
        )
        await renderer.close()

    asyncio.run(scenario())
    rendered = "".join(output)
    assert "推理摘要：检查工具结果" in rendered
    assert "Memoli > 最终回答" in rendered


def test_stream_renderer_avoids_duplicate_final_text_and_bounds_tool_status() -> None:
    output: list[str] = []

    async def scenario() -> None:
        renderer = TerminalRenderer("cli:local", output.append, color=False)
        await renderer.start()
        renderer.submit_event(
            PresentationEvent(
                PresentationEventKind.TEXT_DELTA,
                "cli:local",
                "trace-1",
                "答案",
            )
        )
        renderer.submit_outbound(
            OutboundMessage(
                "cli",
                "local",
                "答案完成",
                {"trace_id": "trace-1"},
            )
        )
        await renderer.close()

    asyncio.run(scenario())

    rendered = "".join(output)
    assert "答案" in rendered
    assert "完成" in rendered
    assert rendered.count("答案") == 1
    assert rendered.count("Memoli > ") == 1
    assert rendered.count("trace: trace-1") == 1


def test_renderer_persists_submitted_input_and_never_leaks_rich_markup() -> None:
    output: list[str] = []

    async def scenario() -> None:
        renderer = TerminalRenderer("cli:local", output.append, color=True)
        await renderer.start()
        renderer.submit_input("你好[dim]\n第二行末字")
        renderer.submit_event(
            PresentationEvent(
                PresentationEventKind.MODEL_STARTED,
                "cli:local",
                "trace-styled",
            )
        )
        renderer.submit_event(
            PresentationEvent(
                PresentationEventKind.USAGE_UPDATED,
                "cli:local",
                "trace-styled",
                usage=(("input_tokens", 6047), ("output_tokens", 159)),
            )
        )
        renderer.submit_event(
            PresentationEvent(
                PresentationEventKind.TURN_COMPLETED,
                "cli:local",
                "trace-styled",
                status="completed",
            )
        )
        renderer.submit_outbound(
            OutboundMessage(
                "cli",
                "local",
                "完整回答末字",
                {"trace_id": "trace-styled"},
            )
        )
        await renderer.close()

    asyncio.run(scenario())
    rendered = "".join(output)
    visible = re.sub(r"\x1b\[[0-9;]*m", "", rendered)
    assert "╭─ 输入 " in visible
    assert "你 ▸ 你好[dim]" in visible
    assert "第二行末字" in visible
    assert "╰" in visible and "╯" in visible
    assert "完整回答末字" in visible
    assert "tokens: input=6,047 | output=159" in visible
    assert "trace: trace-styled" in visible
    assert "[/]" not in visible


def test_stream_fragments_wait_for_complete_outbound_before_terminal_write() -> None:
    output: list[str] = []

    async def scenario() -> str:
        renderer = TerminalRenderer("cli:local", output.append, color=False)
        await renderer.start()
        for fragment in ("我的核", "心特点", "：\n- 完", "整末字"):
            renderer.submit_event(
                PresentationEvent(
                    PresentationEventKind.TEXT_DELTA,
                    "cli:local",
                    "trace-chunks",
                    fragment,
                )
            )
        await asyncio.sleep(0.05)
        before_outbound = "".join(output)
        renderer.submit_outbound(
            OutboundMessage(
                "cli",
                "local",
                "我的核心特点：\n- 完整末字",
                {"trace_id": "trace-chunks"},
            )
        )
        await renderer.close()
        return before_outbound

    before_outbound = asyncio.run(scenario())
    rendered = "".join(output)
    assert before_outbound == ""
    assert "我的核心特点：" in rendered
    assert "完整末字" in rendered
    assert rendered.count("我的核心特点") == 1


def test_structured_turn_error_prints_only_safe_classification() -> None:
    output: list[str] = []

    async def scenario() -> None:
        renderer = TerminalRenderer("cli:local", output.append, color=False)
        await renderer.start()
        renderer.submit_outbound(
            OutboundMessage(
                "cli",
                "local",
                "本轮处理失败。",
                {
                    "status": "error",
                    "error_type": "provider-unavailable",
                    "retryable": True,
                    "internal": "Bearer top-secret",
                },
            )
        )
        await renderer.close()

    asyncio.run(scenario())

    rendered = "\n".join(output)
    assert "provider-unavailable" in rendered
    assert "可重试: 是" in rendered
    assert "top-secret" not in rendered


def test_working_card_marks_truncation() -> None:
    state = WorkingStateStore()
    state.update_checkpoint("cli:local", "x" * 500, "", objective="目标")
    rendered = render_working_card(state.snapshot("cli:local"), max_chars=120)
    assert len(rendered) <= 120
    assert "已省略" in rendered
