from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_web_backend_exposes_agent_and_core_file_routes():
    source = _read("channel/web/web_channel.py")
    assert "'/api/agents', 'AgentsHandler'" in source
    assert "'/api/agents/([^/]+)/files/([^/]+)', 'AgentCoreFileHandler'" in source
    assert "'/api/agents/([^/]+)/avatar', 'AgentAvatarHandler'" in source
    assert "class AgentsHandler:" in source
    assert "class AgentCoreFileHandler:" in source
    assert "scope" in source and "_list_sessions_across_agents" in source


def test_console_has_agent_cards_not_a_tenant_switcher():
    html = _read("channel/web/chat.html")
    assert 'id="agent-selector"' not in html
    # 团队现在是它自己的顶级视图，而不是“设置”面板：它是
    # 您可以在其中组成和管理与您一起工作的代理。
    assert 'data-view="agents"' in html
    assert 'id="view-agents"' in html
    assert 'id="agents-grid"' in html
    assert 'id="agent-core-editor"' in html
    assert 'id="composer-agent-btn"' in html
    # 核心文件选择器与其他地方使用的下拉组件相同。
    # 控制台，不是原生的 <select>；它的选项是用 JS 构建的
    # _agentCoreFileOptions() 而不是标记中硬编码的 <option> 标记。
    assert 'id="agent-core-file" class="cfg-dropdown cfg-dropdown-xs"' in html
    js = _read("channel/web/static/js/console.js")
    for filename in ("AGENT.md", "USER.md", "RULE.md", "MEMORY.md"):
        assert f"value: '{filename}'" in js
    # BOOTSTRAP.md 是内部的，故意排除在手动编辑之外
    # 选择器。
    assert "value: 'BOOTSTRAP.md'" not in js


def test_console_carries_agent_id_through_existing_feature_requests():
    source = _read("channel/web/static/js/console.js")
    assert "body.agent_id = activeAgentId" in source
    assert "agent_id=${encodeURIComponent(activeAgentId)}" in source
    assert "function runtimeSessionKey" in source
    assert "scope=all" in source
    assert "function startChatWithAgent" in source
    assert "function bindChannelAgent" in source


def test_workspace_scoped_web_services_resolve_selected_agent():
    source = _read("channel/web/web_channel.py")
    assert "def _get_workspace_root(session_id: str = None, agent_id: str = None)" in source
    assert "project_store.get_project_dir(session_id, agent_id)" in source
    assert "get_agent_registry().get(agent_id).workspace" in source
    assert "get_conversation_store(_get_workspace_root(agent_id=agent_id))" in source
    assert "_get_workspace_root(agent_id=agent_id)" in source
    assert "get_scheduler_service(agent_id=agent_id)" in source
