"""Regression tests: assistant reply must be captured even when context is trimmed.

Reproduces the bug where a context trim (turns > agent_max_context_turns) made
run_stream compute an empty _last_run_new_messages, so the assistant reply was
never persisted and disappeared after a page refresh.
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent.protocol.agent as agent_mod
from agent.protocol.agent import Agent


class _FakeExecutor:
    """Stand-in for AgentStreamExecutor that optionally trims context.

    It appends the user query, optionally drops the oldest turns to simulate
    _trim_messages(), then appends an assistant reply -- mirroring the real
    executor's timeline.
    """

    def __init__(self, *, messages, trim_to=None, **_):
        self.messages = list(messages)
        self._trim_to = trim_to

    def run_stream(self, user_message):
        # 1.追加新的用户查询（在修剪之前，像真正的执行者一样）
        self.messages.append(
            {"role": "user", "content": [{"type": "text", "text": user_message}]}
        )
        # 2. 如果此运行溢出上下文窗口，则修剪最旧的转弯
        if self._trim_to is not None:
            self.messages = self.messages[-self._trim_to:]
        # 3.追加助理回复
        reply = "assistant answer"
        self.messages.append(
            {"role": "assistant", "content": [{"type": "text", "text": reply}]}
        )
        return reply


def _make_agent(history):
    agent = Agent.__new__(Agent)
    agent.model = object()  # 诚实； run_stream 只检查 `if not self.model`
    agent.tools = []
    agent.max_steps = 100
    agent.messages = list(history)
    agent.messages_lock = threading.Lock()
    agent.get_full_system_prompt = lambda skill_filter=None: "sys"
    agent._execute_post_process_tools = lambda: None
    return agent


def _run(agent, monkeypatch_executor):
    orig = agent_mod.AgentStreamExecutor
    agent_mod.AgentStreamExecutor = monkeypatch_executor
    try:
        return agent.run_stream("hi")
    finally:
        agent_mod.AgentStreamExecutor = orig


def _make_history(turns):
    """Build `turns` prior user/assistant pairs."""
    history = []
    for i in range(turns):
        history.append({"role": "user", "content": [{"type": "text", "text": f"q{i}"}]})
        history.append({"role": "assistant", "content": [{"type": "text", "text": f"a{i}"}]})
    return history


def test_new_messages_captured_without_trim():
    agent = _make_agent(_make_history(3))

    def factory(**kw):
        return _FakeExecutor(messages=kw["messages"], trim_to=None)

    _run(agent, factory)

    roles = [m["role"] for m in agent._last_run_new_messages]
    assert roles == ["user", "assistant"], roles
    assert agent._last_run_new_messages[-1]["content"][0]["text"] == "assistant answer"


def test_new_messages_captured_when_trimmed():
    """The bug case: history overflows and gets trimmed mid-run.

    Before the fix, _last_run_new_messages was empty here and the assistant
    reply was silently dropped from persistence.
    """
    # 21 先前回合 -> 42 条消息；修剪仅保留最后 11 圈的价值。
    agent = _make_agent(_make_history(21))

    def factory(**kw):
        # 修剪后保留 22 条信息（约 11 圈），就像真正的修剪一样
        return _FakeExecutor(messages=kw["messages"], trim_to=22)

    _run(agent, factory)

    roles = [m["role"] for m in agent._last_run_new_messages]
    # 必须包含本次运行的用户查询+助理回复，不能为空。
    assert "assistant" in roles, roles
    assert agent._last_run_new_messages[-1]["content"][0]["text"] == "assistant answer"
    # 捕获的切片必须从新用户查询开始，而不是更早的轮次。
    assert roles[0] == "user"
    assert agent._last_run_new_messages[0]["content"][0]["text"] == "hi"


if __name__ == "__main__":
    test_new_messages_captured_without_trim()
    test_new_messages_captured_when_trimmed()
    print("all passed")
