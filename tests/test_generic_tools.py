from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

from memoli_agent.agent.subagent.manager import SubAgentManager
from memoli_agent.agent.tools.browser import (
    BrowserAdapter,
    WebExecuteJSTool,
    WebScanTool,
)
from memoli_agent.agent.tools.control import WorkingStateStore
from memoli_agent.agent.tools.execution import ToolExecutionContext
from memoli_agent.agent.tools.generic import (
    CodeRunTool,
    FilePatchTool,
    FileReadTool,
    FileWriteTool,
)
from memoli_agent.bootstrap.config import AppConfig, RuntimeConfig, ToolsConfig
from memoli_agent.bootstrap.tools import build_tool_registry


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


def test_file_tools_preserve_text_and_support_three_write_modes(
    tmp_path: Path,
) -> None:
    target = tmp_path / "note.txt"
    write = FileWriteTool(tmp_path)
    patch = FilePatchTool(tmp_path)

    assert run(write.run({"path": "note.txt", "content": "中“文”\n"})).success
    assert run(
        write.run({"path": "note.txt", "content": "尾部\n", "mode": "append"})
    ).success
    assert run(
        write.run({"path": "note.txt", "content": "头部\n", "mode": "prepend"})
    ).success
    assert run(
        patch.run(
            {
                "path": "note.txt",
                "old_content": "中“文”",
                "new_content": "中‘文’",
            }
        )
    ).success
    assert target.read_text(encoding="utf-8") == "头部\n中‘文’\n尾部\n"


def test_file_write_does_not_implicitly_expand_reference_like_text(
    tmp_path: Path,
) -> None:
    literal = "{{file:other.txt:1:2}}"
    result = run(
        FileWriteTool(tmp_path).run({"path": "literal.txt", "content": literal})
    )

    assert result.success
    assert (tmp_path / "literal.txt").read_text(encoding="utf-8") == literal


def test_file_patch_rejects_missing_or_ambiguous_match(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("same\nsame\n", encoding="utf-8")
    tool = FilePatchTool(tmp_path)

    ambiguous = run(
        tool.run({"path": "note.txt", "old_content": "same", "new_content": "x"})
    )
    missing = run(
        tool.run({"path": "note.txt", "old_content": "none", "new_content": "x"})
    )

    assert not ambiguous.success
    assert not missing.success
    assert target.read_text(encoding="utf-8") == "same\nsame\n"


def test_file_read_pages_numbers_and_keeps_raw_truncated_content(
    tmp_path: Path,
) -> None:
    (tmp_path / "note.txt").write_text("甲\n乙\n丙\n", encoding="utf-8")
    result = run(
        FileReadTool(tmp_path, max_output_chars=12).run(
            {"path": "note.txt", "start": 2, "count": 2, "show_linenos": True}
        )
    )

    assert result.success
    assert result.raw_content == "2|乙\n3|丙\n"
    assert result.metadata["truncated"] is False

    long_result = run(
        FileReadTool(tmp_path, max_output_chars=8).run({"path": "note.txt"})
    )
    assert long_result.metadata["truncated"] is True
    assert len(long_result.content) <= 8
    assert long_result.raw_content is not None
    assert "丙" in long_result.raw_content


def test_file_tools_reject_outside_and_non_utf8_targets(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "binary.bin").write_bytes(b"\xff\xfe")

    escaped = run(FileReadTool(tmp_path).run({"path": str(outside)}))
    binary = run(FileReadTool(tmp_path).run({"path": "binary.bin"}))

    assert not escaped.success
    assert not binary.success


def test_file_tools_reject_link_that_resolves_outside_workspace(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    link = tmp_path / "outside-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("当前 Windows 账户不能创建符号链接")

    result = run(
        FileWriteTool(tmp_path).run(
            {"path": "outside-link/escaped.txt", "content": "blocked"}
        )
    )

    assert not result.success
    assert not (outside / "escaped.txt").exists()


def test_code_run_returns_stdout_stderr_exit_code_and_truncation(
    tmp_path: Path,
) -> None:
    tool = CodeRunTool(
        tmp_path,
        max_output_chars=80,
        runner="trusted-host",
        python_executable=sys.executable,
    )
    success = run(tool.run({"script": "print('ok')"}))
    failed = run(
        tool.run({"script": "import sys; print('bad', file=sys.stderr); sys.exit(3)"})
    )
    long_output = run(tool.run({"script": "print('x' * 500)"}))

    assert success.success
    assert json.loads(success.raw_content or "{}")["stdout"] == "ok\r\n"
    assert not failed.success
    assert failed.metadata["exit_code"] == 3
    assert "bad" in (failed.raw_content or "")
    assert long_output.metadata["truncated"] is True
    assert len(long_output.content) <= 80


def test_code_run_timeout_and_workspace_cwd_boundary(tmp_path: Path) -> None:
    tool = CodeRunTool(
        tmp_path,
        default_timeout_seconds=1,
        runner="trusted-host",
        python_executable=sys.executable,
    )

    timeout = run(tool.run({"script": "import time; time.sleep(3)", "timeout": 1}))
    escaped = run(tool.run({"script": "print(1)", "cwd": str(tmp_path.parent)}))

    assert timeout.status == "timeout"
    assert not timeout.success
    assert not escaped.success


def test_code_run_powershell_and_unavailable_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = CodeRunTool(
        tmp_path, runner="trusted-host", python_executable=sys.executable
    )
    powershell = run(tool.run({"type": "powershell", "script": "Write-Output 'ok'"}))
    assert powershell.success
    assert "ok" in (powershell.raw_content or "")

    monkeypatch.setattr("memoli_agent.agent.tools.generic.shutil.which", lambda _: None)
    unavailable = run(tool.run({"type": "powershell", "script": "Write-Output 'no'"}))
    assert not unavailable.success
    assert unavailable.metadata["error"] == "OSError"


def test_container_code_run_is_fail_closed_and_resource_bounded(
    tmp_path: Path,
) -> None:
    image = "memoli-code-runner@sha256:" + "a" * 64
    tool = CodeRunTool(
        tmp_path,
        container_cli="definitely-missing-container-cli",
        container_image=image,
    )
    command = tool._command("python", "print('ok')", tmp_path)  # noqa: SLF001
    joined = " ".join(command)

    for expected in (
        "--network none",
        "--read-only",
        "--user 65532:65532",
        "--cap-drop ALL",
        "no-new-privileges:true",
        "--pids-limit 64",
        "--memory 256m",
        "--memory-swap 256m",
        "--cpus 0.5",
        "dst=/workspace",
    ):
        assert expected in joined
    unavailable = run(tool.run({"script": "print('never on host')"}))
    assert unavailable.success is False
    assert unavailable.metadata["error"] == "FileNotFoundError"
    powershell = run(tool.run({"type": "powershell", "script": "Get-ChildItem"}))
    assert powershell.success is False


def test_code_runner_profiles_require_immutable_or_explicit_runtime(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="digest"):
        CodeRunTool(tmp_path, container_image="runner:latest")
    with pytest.raises(ValueError, match="绝对路径"):
        CodeRunTool(tmp_path, runner="trusted-host", python_executable="python")
    disabled = CodeRunTool(tmp_path, runner="disabled")
    assert run(disabled.run({"script": "print('no')"})).success is False


@dataclass
class FakeBrowser:
    async def scan(
        self, *, tabs_only: bool, switch_tab_id: str | None, text_only: bool
    ) -> dict[str, Any]:
        return {"tabs": [], "content": "page", "tabs_only": tabs_only}

    async def execute_js(
        self,
        script: str,
        *,
        switch_tab_id: str | None,
        no_monitor: bool,
    ) -> dict[str, Any]:
        return {"js_return": script}


def test_default_registry_is_exact_nine_tools_and_optionals_are_explicit(
    tmp_path: Path,
) -> None:
    config = AppConfig(runtime=RuntimeConfig(workspace=str(tmp_path)))
    state = WorkingStateStore()
    registry = build_tool_registry(config, working_state=state)

    assert [tool.name for tool in registry.list_tools()] == [
        "code_run",
        "file_read",
        "file_patch",
        "file_write",
        "update_working_checkpoint",
        "ask_user",
        "start_long_term_update",
        "time",
        "memory_recall",
    ]

    optional_config = AppConfig(
        runtime=RuntimeConfig(workspace=str(tmp_path)),
        tools=ToolsConfig(browser_enabled=True, subagent_tool_enabled=True),
    )
    optional = build_tool_registry(
        optional_config,
        subagent_manager=cast(SubAgentManager, object()),
        working_state=state,
        browser_adapter=cast(BrowserAdapter, FakeBrowser()),
    )
    names = [tool.name for tool in optional.list_tools()]
    assert names[-4:] == [
        "web_scan",
        "web_execute_js",
        "spawn_subagent",
        "manage_subagent",
    ]

    unavailable = build_tool_registry(optional_config, working_state=state)
    assert len(unavailable.list_tools()) == 9


def test_browser_tools_scan_and_save_long_result_inside_workspace(
    tmp_path: Path,
) -> None:
    adapter = FakeBrowser()
    scan = run(WebScanTool(adapter).run({"tabs_only": True}))
    execute = run(
        WebExecuteJSTool(adapter, tmp_path).run(
            {"script": "long-result", "save_to_file": "browser.txt"}
        )
    )
    escaped = run(
        WebExecuteJSTool(adapter, tmp_path).run(
            {"script": "secret", "save_to_file": str(tmp_path.parent / "x.txt")}
        )
    )

    assert scan.success
    assert (tmp_path / "browser.txt").read_text(encoding="utf-8") == "long-result"
    assert execute.success
    assert not escaped.success


def test_checkpoint_ask_user_and_long_term_request_use_runtime_context(
    tmp_path: Path,
) -> None:
    state = WorkingStateStore()
    registry = build_tool_registry(
        AppConfig(runtime=RuntimeConfig(workspace=str(tmp_path))),
        working_state=state,
    )
    context = ToolExecutionContext("a" * 32, "session-1", "call-1")

    checkpoint = run(
        registry.execute(
            "update_working_checkpoint",
            {"key_info": "先读文件", "related_sop": "coding"},
            context=context,
        )
    )
    question = run(
        registry.execute(
            "ask_user",
            {"question": "选择？", "candidates": ["A", "B"]},
            context=context,
        )
    )
    request = run(registry.execute("start_long_term_update", {}, context=context))
    repeated = run(registry.execute("start_long_term_update", {}, context=context))

    assert checkpoint.success
    assert "先读文件" in state.render_checkpoint("session-1")
    assert question.metadata["needs_user"] is True
    assert question.status == "needs-user"
    assert request.content == repeated.content
    assert len(state.requests) == 1
