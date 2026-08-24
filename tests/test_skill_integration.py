import asyncio
import sqlite3
from pathlib import Path

import pytest

from memoli_agent.agent.context import ContextBuilder
from memoli_agent.agent.session import Session, SessionManager
from memoli_agent.agent.types import ContextRequest, TurnState
from memoli_agent.bootstrap.app import build_app_runtime
from memoli_agent.bootstrap.config import (
    AppConfig,
    MemoryConfig,
    PluginsConfig,
    RuntimeConfig,
    SkillsConfig,
    SubAgentConfig,
    TrajectoryConfig,
    WorkingMemoryConfig,
    load_config,
)
from memoli_agent.bootstrap.skills import build_skill_components
from memoli_agent.bootstrap.tools import build_tool_registry
from memoli_agent.bus.events import InboundMessage


def test_skills_toml_contract_and_unsafe_values(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[skills]
enabled = true
database = "data/skills.db"
artifact_root = "data/artifacts"
catalog_max_chars = 1234
skill_max_chars = 2345
reference_max_chars = 3456
include_unavailable_in_catalog = false
allow_runtime_management = false
""",
        encoding="utf-8",
    )
    config = load_config(config_file)
    assert config.skills.enabled is True
    assert config.skills.catalog_max_chars == 1234

    with pytest.raises(ValueError):
        SkillsConfig(allow_runtime_management=True)
    with pytest.raises(ValueError):
        SkillsConfig(database="../outside.db")
    with pytest.raises(ValueError):
        SkillsConfig(skill_max_chars=0)


def test_disabled_runtime_preserves_nine_tools_and_creates_nothing(
    tmp_path: Path,
) -> None:
    database = tmp_path / "skills.db"
    artifacts = tmp_path / "artifacts"
    config = AppConfig(
        runtime=RuntimeConfig(workspace=str(tmp_path)),
        skills=SkillsConfig(
            enabled=False,
            database=str(database),
            artifact_root=str(artifacts),
        ),
    )
    assert build_skill_components(config) is None
    registry = build_tool_registry(config)
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
    assert not database.exists()
    assert not artifacts.exists()


def test_enabled_runtime_registers_tenth_tool_and_orders_catalog_before_memory(
    tmp_path: Path,
) -> None:
    config = AppConfig(
        runtime=RuntimeConfig(workspace=str(tmp_path)),
        skills=SkillsConfig(
            enabled=True,
            database=str(tmp_path / "skills.db"),
            artifact_root=str(tmp_path / "artifacts"),
        ),
    )
    components = build_skill_components(config)
    assert components is not None
    try:
        registry = build_tool_registry(
            config,
            skill_runtime=components.runtime,
        )
        assert len(registry.list_tools()) == 10
        assert registry.list_tools()[-1].name == "skill_load"

        session = Session(session_key="cli:1")
        catalog = components.runtime.build_catalog(
            session_instance_id=session.session_instance_id,
            session_key=session.session_key,
            tools={tool.name for tool in registry.list_tools()},
            mcp_servers=set(),
        )
        assert "research-report@1.0.0" in catalog.content

        inbound = InboundMessage("cli", "1", "user", "research")
        rendered = ContextBuilder("Memoli", "base-system").render(
            ContextRequest(
                turn_state=TurnState("cli:1", inbound, session),
                agent_name="Memoli",
                system_prompt="base-system",
                skill_catalog_prompt_block=catalog.content,
                memory_prompt_block="memory-block",
            )
        )
        assert [message.content for message in rendered.messages[:3]] == [
            "base-system",
            catalog.content,
            "memory-block",
        ]
    finally:
        components.close()


def test_process_restart_creates_new_session_instance() -> None:
    first = SessionManager().get_or_create("cli:same")
    second = SessionManager().get_or_create("cli:same")
    assert first.session_key == second.session_key
    assert first.session_instance_id != second.session_instance_id


def test_unsupported_registry_degrades_without_rebuilding(tmp_path: Path) -> None:
    database = tmp_path / "future.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE skill_meta(key TEXT PRIMARY KEY, value TEXT)")
    connection.execute("INSERT INTO skill_meta VALUES ('schema_version', '99')")
    connection.commit()
    connection.close()
    config = AppConfig(
        runtime=RuntimeConfig(workspace=str(tmp_path)),
        skills=SkillsConfig(
            enabled=True,
            database=str(database),
            artifact_root=str(tmp_path / "artifacts"),
        ),
    )
    assert build_skill_components(config) is None
    registry = build_tool_registry(config)
    assert len(registry.list_tools()) == 9
    connection = sqlite3.connect(database)
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    connection.close()
    assert tables == [("skill_meta",)]


def test_app_runtime_owns_and_closes_skill_components(tmp_path: Path) -> None:
    config = AppConfig(
        runtime=RuntimeConfig(workspace=str(tmp_path)),
        trajectory=TrajectoryConfig(enabled=False),
        memory=MemoryConfig(enabled=False),
        working_memory=WorkingMemoryConfig(enabled=False),
        plugins=PluginsConfig(enabled=[], trusted=[]),
        subagent=SubAgentConfig(enabled=False),
        skills=SkillsConfig(
            enabled=True,
            database=str(tmp_path / "skills.db"),
            artifact_root=str(tmp_path / "artifacts"),
        ),
    )
    app = build_app_runtime(config)
    assert app.skill_components is not None
    assert app.tool_registry.list_tools()[-1].name == "skill_load"
    asyncio.run(app.shutdown())
