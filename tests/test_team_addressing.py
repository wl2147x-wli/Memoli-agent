"""Matching a leading @mention against a conversation's roster.

Channel-agnostic: the Web console and IM channels (Feishu, ...) all decide who
a turn is addressed to with the same rule, so a name resolves the same way
whether it was typed in a browser or an IM group.
"""

from agent.team_addressing import addressed_agent_id


ROSTER = [
    {"id": "leader", "name": "队长"},
    {"id": "ops", "name": "运维"},
    {"id": "ops-lead", "name": "运维主管"},
]


def test_leading_mention_by_name():
    assert addressed_agent_id("@运维 帮我查一下", ROSTER) == "ops"


def test_leading_mention_by_id():
    assert addressed_agent_id("@ops please help", ROSTER) == "ops"


def test_longest_label_wins_when_names_overlap():
    # "运维主管" contains "运维"; the longer, exact label must win.
    assert addressed_agent_id("@运维主管 处理下", ROSTER) == "ops-lead"


def test_mention_must_lead():
    # 在句子中间说出某人的名字是在谈论他们，而不是交出发言权。
    assert addressed_agent_id("帮我 @运维 一下", ROSTER) == ""


def test_no_mention_returns_empty():
    assert addressed_agent_id("你好", ROSTER) == ""


def test_unknown_name_returns_empty():
    assert addressed_agent_id("@财务 报销", ROSTER) == ""


def test_empty_roster_returns_empty():
    assert addressed_agent_id("@ops hi", []) == ""


def test_boundary_requires_separator_or_end():
    # “@opsx”不是“@ops”：裸前缀不能匹配不同的名称。
    assert addressed_agent_id("@opsx hi", ROSTER) == ""
    # 冒号/逗号/空格/CJK 标点符号都算作边界
    assert addressed_agent_id("@ops：查一下", ROSTER) == "ops"
    assert addressed_agent_id("@ops", ROSTER) == "ops"
