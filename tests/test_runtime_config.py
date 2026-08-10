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
