"""Query Builder 单元测试：覆盖空查询、CJK 边界、短 ASCII、term 上限、
辅助工作上下文隔离与确定性重复。"""

from __future__ import annotations

from memoli_agent.agent.memory.models import MemoryQuery, QueryPlan
from memoli_agent.agent.memory.query_plan import (
    build_query_plan,
    fts_match_for,
    pattern_terms_for,
)


def _plan(query: str = "", **kwargs: object) -> QueryPlan:
    return build_query_plan(MemoryQuery(query=query, **kwargs))  # type: ignore[arg-type]


def test_empty_query_yields_no_terms() -> None:
    plan = _plan("")
    assert plan.primary_text == ""
    assert plan.fts_match == '"__empty__"'
    assert plan.fts_term_count == 0
    assert plan.pattern_terms == ()
    assert plan.pattern_term_count == 0
    assert plan.pattern_truncated is False
    assert plan.summary["has_embedding_text"] is False


def test_two_char_cjk_goes_to_pattern_only() -> None:
    # 2 字 CJK 低于 trigram 窗口：进入 Pattern，不进入严格 FTS。
    plan = _plan("清华")
    assert plan.pattern_terms == ("清华",)
    assert plan.fts_match == '"__empty__"'
    assert plan.fts_term_count == 0


def test_three_plus_char_cjk_enters_strict_lane() -> None:
    plan = _plan("清华镜像源")
    # 严格 lane 包含整词；Pattern 取相邻 bigram。
    assert plan.fts_match == '"清华镜像源"'
    assert plan.fts_term_count == 1
    assert plan.pattern_terms == ("清华", "华镜", "镜像", "像源")


def test_omitted_middle_phrase_recovers_via_pattern() -> None:
    # "清华源" 在权威记忆 "清华镜像源" 中不连续出现：严格 FTS 不应注入无关 unigram，
    # Pattern bigram 覆盖中间插词召回。
    plan = _plan("清华源")
    assert plan.fts_match == '"清华源"'
    assert plan.pattern_terms == ("清华", "华源")
    # 严格 lane 不为制造 FTS 命中而注入 unigram OR 条件：MATCH 是单短语，无 OR。
    assert " OR " not in plan.fts_match


def test_short_ascii_term_goes_to_pattern_only() -> None:
    plan = _plan("ai")
    assert plan.pattern_terms == ("ai",)
    assert plan.fts_match == '"__empty__"'
    assert plan.fts_term_count == 0


def test_longer_ascii_enters_strict_lane() -> None:
    plan = _plan("memory")
    assert plan.fts_match == '"memory"'
    assert plan.fts_term_count == 1
    assert plan.pattern_terms == ()


def test_pattern_term_limit_truncates_deterministically() -> None:
    # 17 个互不相同的 2 字 CJK token → 17 个 Pattern term，超出 16 项上限。
    chars = (
        "青蓝绿紫红橙黄粉黑白灰金银铜铁锡铅汞铂"
        "锰铬镍钴锌铋碲氙氪氩氖氢氦氧氮氯碳硫磷"
    )
    tokens = [chars[i : i + 2] for i in range(0, 34, 2)]
    assert len(tokens) == 17
    query = " ".join(tokens)
    plan = _plan(query)
    assert len(plan.pattern_terms) == 16
    assert plan.pattern_truncated is True
    # 截断是确定性的：稳定排序后取前 16 项。
    terms, truncated = pattern_terms_for(query)
    assert len(terms) == 16
    assert truncated is True
    assert tuple(terms) == plan.pattern_terms


def test_auxiliary_working_context_does_not_expand_text_lanes() -> None:
    plan = _plan(
        "清华源",
        objective="工作目标记忆",
        current_step="当前步骤画像",
    )
    # FTS / Pattern 只消费当前用户 query，不包含 objective/current-step。
    assert "目标" not in plan.fts_match
    assert "步骤" not in plan.fts_match
    assert "目标" not in plan.pattern_terms
    assert "步骤" not in plan.pattern_terms
    # embedding 文本保留字段边界并包含辅助上下文。
    assert "清华源" in plan.embedding_text
    assert "工作目标记忆" in plan.embedding_text
    assert "当前步骤画像" in plan.embedding_text
    assert plan.enabled_fields == ("query", "objective", "current_step")
    # 摘要不泄露 query 正文副本。
    assert "query_text" not in plan.summary
    assert plan.summary["fts_term_count"] == 1


def test_embedding_text_is_truncated_to_limit() -> None:
    long_query = "目标" * 2000  # 远超 1500 字符
    plan = _plan(long_query)
    assert len(plan.embedding_text) <= 1500


def test_repeated_build_is_deterministic() -> None:
    request = MemoryQuery(query="清华镜像源 memory ai", objective="工作目标")
    first = build_query_plan(request)
    second = build_query_plan(request)
    assert first == second
    # 同一 query 的 fts_match / pattern_terms 多次调用稳定。
    assert fts_match_for("清华镜像源 memory ai")[0] == fts_match_for(
        "清华镜像源 memory ai"
    )[0]
    assert pattern_terms_for("清华镜像源 memory ai")[0] == pattern_terms_for(
        "清华镜像源 memory ai"
    )[0]


def test_mixed_cjk_ascii_does_not_cross_boundary() -> None:
    # "用户wang的记忆"：CJK 与 ASCII 分离，不在边界生成跨类型 n-gram。
    plan = _plan("用户wang的记忆")
    # "用户" (2 CJK) → Pattern；"wang" (4 ASCII) → FTS；
    # "的记忆" (3 CJK) → FTS + bigram。
    assert "用户" in plan.pattern_terms
    assert '"wang"' in plan.fts_match
    assert '"的记忆"' in plan.fts_match
