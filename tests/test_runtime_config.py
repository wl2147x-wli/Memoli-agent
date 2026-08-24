from pathlib import Path

import pytest

from memoli_agent.bootstrap.config import load_config


def test_runtime_and_trajectory_defaults() -> None:
    config = load_config("missing-config.toml")

    assert config.agent.max_iterations == 12
    assert config.agent.max_elapsed_seconds == 300
    assert config.agent.no_progress_limit == 3
    assert config.trajectory.enabled is True
    assert config.trajectory.database == "workspace/trajectories.db"
    assert config.trajectory.capture_content == "redacted"
    assert config.tools.tool_search_enabled is False
    assert config.tools.code_runner == "container"
    assert config.tools.code_allow_network is False
    assert config.tools.code_timeout_seconds == 60
    assert config.tools.browser_enabled is False
    assert config.tools.subagent_tool_enabled is False
    assert config.llm.context_window_tokens == 131_072
    assert config.llm.context_safety_margin_tokens == 4_096
    assert config.context.enabled is True
    assert config.context.soft_threshold_ratio == 0.75
    assert config.context.database == "workspace/context-state.db"


def test_runtime_and_trajectory_toml_parsing(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[agent]
max_iterations = 5
max_elapsed_seconds = 12.5
no_progress_limit = 2

[trajectory]
enabled = false
database = "local/trace.db"
capture_content = "metadata-only"
max_inline_bytes = 128
max_payload_bytes = 1024
payload_directory = "local/payloads"
sensitive_keys = ["private_key"]

[tools]
code_timeout_seconds = 15
code_max_output_chars = 4096
file_read_max_lines = 300
file_max_output_chars = 5000
browser_enabled = true
subagent_tool_enabled = true
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.agent.max_iterations == 5
    assert config.agent.max_elapsed_seconds == 12.5
    assert config.trajectory.enabled is False
    assert config.trajectory.sensitive_keys == ["private_key"]
    assert config.tools.code_timeout_seconds == 15
    assert config.tools.browser_enabled is True
    assert config.tools.subagent_tool_enabled is True


def test_invalid_trajectory_config_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[trajectory]
capture_content = "unsafe"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="capture_content"):
        load_config(path)


def test_invalid_code_runner_configuration_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[tools]
code_runner = "container"
code_container_image = "runner:latest"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="digest"):
        load_config(path)


def test_context_management_config_is_parsed(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[context]
enabled = false
compaction_enabled = false
persistence_enabled = false
soft_threshold_ratio = 0.6
hard_threshold_ratio = 0.8
recent_tail_tokens = 2000
preview_tokens = 300
archive_tokens = 500
archive_frontier_tokens = 2000
archive_frontier_max_items = 4
source_read_max_turns = 5
source_read_max_bytes = 8192
compaction_batch_tokens = 10000
plugin_max_tokens = 200
emergency_retry_limit = 0
compaction_failure_limit = 3
""",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.context.enabled is False
    assert config.context.hard_threshold_ratio == 0.8
    assert config.context.compaction_failure_limit == 3
    # §8.1：frontier/source read/compaction batch 字段被严格解析
    assert config.context.archive_frontier_tokens == 2000
    assert config.context.archive_frontier_max_items == 4
    assert config.context.source_read_max_turns == 5
    assert config.context.source_read_max_bytes == 8192
    assert config.context.compaction_batch_tokens == 10000


def test_context_management_config_defaults(tmp_path: Path) -> None:
    """§8.1：新字段缺省时取保守默认（source read 不限、batch 32k）。"""

    path = tmp_path / "config.toml"
    path.write_text("[context]\n", encoding="utf-8")
    config = load_config(path)
    assert config.context.source_read_max_turns is None
    assert config.context.source_read_max_bytes is None
    assert config.context.compaction_batch_tokens == 32_000
    assert config.context.archive_frontier_tokens == 16_000
    assert config.context.archive_frontier_max_items == 8


@pytest.mark.parametrize(
    "body",
    [
        "soft_threshold_ratio = 0.9\nhard_threshold_ratio = 0.8",
        "preview_tokens = 0",
        "emergency_retry_limit = 2",
        # §8.1 严格校验：source read 仅接受正整数或留空；compaction batch > 0。
        "source_read_max_turns = 0",
        "source_read_max_bytes = -1",
        "compaction_batch_tokens = 0",
        "archive_frontier_tokens = 0",
        "archive_frontier_max_items = -2",
    ],
)
def test_invalid_context_management_config_is_rejected(
    tmp_path: Path, body: str
) -> None:
    path = tmp_path / "config.toml"
    path.write_text(f"[context]\n{body}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="context"):
        load_config(path)


@pytest.mark.parametrize(
    "body, message",
    [
        ("initial_delay_seconds = 0", "initial_delay_seconds"),
        ("quiet_hours_start = 22", "开始和结束"),
        (
            "quiet_hours_start = 22\n"
            "quiet_hours_end = 7\n"
            'quiet_hours_timezone = "Invalid/Zone"',
            "timezone",
        ),
    ],
)
def test_invalid_proactive_safety_config_is_rejected(
    tmp_path: Path, body: str, message: str
) -> None:
    path = tmp_path / "config.toml"
    path.write_text(f"[proactive]\n{body}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_config(path)
