"""确定性 MemOS 风格查询计划构建器。

将结构化 ``MemoryQuery`` 一次性构建为不可变 ``QueryPlan``，使严格 FTS、宽松 Pattern
与语义通道共享同一份规范化与 term 生成实现。辅助工作上下文
(objective/current-step) 只进入 ``embedding_text``，绝不扩大严格或
Pattern 文本匹配范围。

设计要点：

- ``primary_text``：仅当前用户查询的规范化文本，用于严格 FTS 和 Pattern；
- ``embedding_text``：带字段边界的 query/objective/current-step 文本，截断到 1500 字符；
- ``fts_match``：完整 term 与适合 trigram 窗口的 term 组成的 FTS5 MATCH 表达式，
  不含 bigram OR 放宽；长度低于 trigram 窗口 (2 字 CJK / 2 字 ASCII) 的 term 不进入；
- ``pattern_terms``：CJK bigram、2 字 CJK 整词与 2 字 ASCII term，去重、稳定排序、
  最多 16 项，超出则确定性截断并标记 truncation。
"""

from __future__ import annotations

import re

from memoli_agent.agent.memory.models import MemoryQuery, QueryPlan

_CJK_RUN = re.compile(r"[㐀-鿿]+")
# 将连续 CJK 与 ASCII/数字分开，避免跨边界 n-gram 漂移。
_TOKEN = re.compile(r"[A-Za-z0-9_]+|[㐀-鿿]+")
_PATTERN_TERM_LIMIT = 16
_EMBEDDING_TEXT_LIMIT = 1500
_FTS_QUOTE_ESCAPE = str.maketrans({'"': " "})
_EMPTY_FTS_MATCH = '"__empty__"'


def _is_cjk(token: str) -> bool:
    return _CJK_RUN.fullmatch(token) is not None


def normalize_query_text(text: str) -> str:
    """共享规范化：去除 CJK 标点、casefold、压缩空白。"""

    cleaned = text.replace("，", " ").replace("。", " ").replace("、", " ")
    return " ".join(cleaned.casefold().split())


def query_tokens(text: str) -> list[str]:
    """共享分词：CJK run 与 ASCII token 分离，去重且保留稳定顺序。"""

    return list(dict.fromkeys(_TOKEN.findall(normalize_query_text(text))))


def cjk_runs(text: str) -> list[str]:
    """提取所有连续 CJK run，供 lane 复用。"""

    return _CJK_RUN.findall(normalize_query_text(text))


def pattern_terms_for(query: str) -> tuple[list[str], bool]:
    """生成 Pattern lane 的 term：CJK bigram、2 字 CJK 整词与 2 字 ASCII term。

    返回 ``(terms, truncated)``：term 去重、稳定排序、最多 16 项，超出则截断并标记。
    """

    terms: list[str] = []
    for token in query_tokens(query):
        if _is_cjk(token):
            if len(token) >= 3:
                # 长度 >= 3 的 CJK run：取相邻 bigram，覆盖中间插词场景。
                terms.extend(token[i : i + 2] for i in range(len(token) - 1))
            elif len(token) == 2:
                # 2 字 CJK 整词低于 trigram 窗口，作为 Pattern term。
                terms.append(token)
        elif len(token) == 2:
            # 2 字 ASCII term 同样低于 trigram 窗口。
            terms.append(token)
    unique = list(dict.fromkeys(terms))
    truncated = len(unique) > _PATTERN_TERM_LIMIT
    return unique[:_PATTERN_TERM_LIMIT], truncated


def fts_match_for(query: str) -> tuple[str, int]:
    """生成严格 FTS lane 的 MATCH 表达式。

    只包含完整 term 与适合 trigram 窗口的 term (CJK run >= 3 字、ASCII token >= 3 字)；
    2 字 CJK / 2 字 ASCII 不进入严格 lane，避免把宽松召回伪装成 BM25 命中。
    返回 ``(match_expression, term_count)``。
    """

    terms: list[str] = []
    for token in query_tokens(query):
        if _is_cjk(token):
            if len(token) >= 3:
                terms.append(token)
        elif len(token) >= 3:
            terms.append(token)
    unique = list(dict.fromkeys(terms))
    match = " OR ".join(f'"{t.translate(_FTS_QUOTE_ESCAPE)}"' for t in unique)
    return (match or _EMPTY_FTS_MATCH), len(unique)


def _embedding_text(request: MemoryQuery) -> str:
    """带字段边界的语义文本，截断到 1500 字符；保留 query/objective/current-step。"""

    return request.semantic_text[:_EMBEDDING_TEXT_LIMIT]


def build_query_plan(request: MemoryQuery) -> QueryPlan:
    """从 ``MemoryQuery`` 构建不可变 ``QueryPlan``。"""

    pattern, truncated = pattern_terms_for(request.query)
    fts_match, fts_count = fts_match_for(request.query)
    enabled = request.context_fields
    return QueryPlan(
        primary_text=normalize_query_text(request.query),
        embedding_text=_embedding_text(request),
        fts_match=fts_match,
        pattern_terms=tuple(pattern),
        fts_term_count=fts_count,
        pattern_term_count=len(pattern),
        pattern_truncated=truncated,
        enabled_fields=enabled,
        summary={
            "enabled_fields": list(enabled),
            "fts_term_count": fts_count,
            "pattern_term_count": len(pattern),
            "pattern_truncated": truncated,
            "has_embedding_text": bool(request.query.strip()),
        },
    )
