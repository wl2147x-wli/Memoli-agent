"""§9.3 cache 稳定性测试。

验证稳定前缀与工具 schema 哈希不被动态尾部、archive 合并或重编译无故改写
（spec §9.3 / design 决策 4、8）。archive 内容经有界 frontier 层进入 context_hash，
但永不改写稳定前缀与工具 schema 哈希——这是 Provider prompt cache 命中的前提。

本文件刻意不导入 pytest，避免 pyright reportMissingImports 环境解析噪声
（与 test_context_frontier_bounds.py 的 _expect_raises 约定一致）。
"""

from __future__ import annotations

import json

from memoli_agent.agent.context_management import (
    ConservativeTokenEstimator,
    ContextArchive,
    ContextCompiler,
    ContextCompilerSettings,
    InMemoryContextStateRepository,
)
from memoli_agent.agent.types import ChatMessage

_SYSTEM = ChatMessage("system", "安全规则 security")
_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_records",
        "parameters": {"type": "object"},
    },
}


def _archive_json(refs: list[str]) -> str:
    """构造固定 schema 的 archive 内容 JSON（source_refs 与批次一致）。"""

    return json.dumps(
        {
            "goal_constraints": ["preserve constraint"],
            "decisions_reasons": ["decision because evidence"],
            "facts_evidence": ["payload:42"],
            "files_artifacts": ["result.txt"],
            "verification_status": ["tests passed"],
            "failure_paths": ["first attempt failed"],
            "todo_remaining": ["ship"],
            "source_refs": list(refs),
        }
    )


def _archive(
    archive_id: str,
    refs: list[str],
    *,
    level: int = 1,
    parents: tuple[str, ...] = (),
) -> ContextArchive:
    """直接提交用 archive（generation 由 commit_archive 事务分配）。"""

    return ContextArchive(
        archive_id,
        "s",
        0,
        _archive_json(refs),
        f"hash-{archive_id}",
        tuple(refs),
        coverage_hash=f"cov-{archive_id}",
        level=level,
        parent_archive_refs=tuple(parents),
    )


def _compiler() -> tuple[ContextCompiler, InMemoryContextStateRepository]:
    repo = InMemoryContextStateRepository()
    return (
        ContextCompiler(
            repo,
            ConservativeTokenEstimator(),
            ContextCompilerSettings(
                context_window_tokens=4_000,
                max_output_tokens=100,
                safety_margin_tokens=100,
                recent_tail_tokens=500,
                archive_tokens=250,
                archive_frontier_tokens=2_000,
                archive_frontier_max_items=8,
            ),
        ),
        repo,
    )


def _memory_block(content: str) -> str:
    """governed dynamic tail 的 memory_context XML（E501：抽字符串避免 CJK 撑宽行）。"""

    return f'<memory_context trust="data">{content}</memory_context>'


def test_stable_prefix_and_tool_hashes_survive_archive_merge() -> None:
    """§9.3 核心：提交 + 合并 archive 后重编译，stable_prefix_hash 与
    tool_schema_hash 不变（archive 只经 frontier 层进入 context_hash）。"""

    compiler, repo = _compiler()
    base = compiler.compile(
        session_key="s",
        session_instance_id="i",
        messages=[_SYSTEM, ChatMessage("user", "goal")],
        tools=[_SCHEMA],
    )
    prefix0 = base.stable_prefix_hash
    tool0 = base.tool_schema_hash

    # §6.5 提交两份活动 archive，再合并最旧相邻为高 level 节点
    a1, _ = repo.commit_archive(_archive("a1", ["r1"]))
    a2, _ = repo.commit_archive(_archive("a2", ["r2"]))
    merged = _archive(
        "m", ["r1", "r2"], level=2, parents=(a1.archive_id, a2.archive_id)
    )
    repo.merge_archives((a1, a2), merged)
    assert any(item.archive_id == "m" for item in repo.list_frontier("s"))

    after = compiler.compile(
        session_key="s",
        session_instance_id="i",
        messages=[_SYSTEM, ChatMessage("user", "goal")],
        tools=[_SCHEMA],
    )
    assert after.stable_prefix_hash == prefix0
    assert after.tool_schema_hash == tool0


def test_recompile_with_same_inputs_is_hash_idempotent() -> None:
    """§9.3 重编译稳定性：同输入重编译，prefix/tool/context hash 均不变。"""

    compiler, _ = _compiler()
    first = compiler.compile(
        session_key="s",
        session_instance_id="i",
        messages=[_SYSTEM, ChatMessage("user", "goal")],
        tools=[_SCHEMA],
    )
    second = compiler.compile(
        session_key="s",
        session_instance_id="i",
        messages=[_SYSTEM, ChatMessage("user", "goal")],
        tools=[_SCHEMA],
    )
    assert first.stable_prefix_hash == second.stable_prefix_hash
    assert first.tool_schema_hash == second.tool_schema_hash
    assert first.context_hash == second.context_hash


def test_dynamic_tail_change_keeps_prefix_and_tool_hashes() -> None:
    """§9.3 动态尾部变化只改写 context_hash，不改写稳定前缀与工具 schema。"""

    compiler, _ = _compiler()
    base = compiler.compile(
        session_key="s",
        session_instance_id="i",
        messages=[
            _SYSTEM,
            ChatMessage("user", "goal"),
            ChatMessage("system", _memory_block("旧记忆")),
        ],
        tools=[_SCHEMA],
    )
    changed = compiler.compile(
        session_key="s",
        session_instance_id="i",
        messages=[
            _SYSTEM,
            ChatMessage("user", "goal"),
            ChatMessage("system", _memory_block("新记忆")),
        ],
        tools=[_SCHEMA],
    )
    assert base.stable_prefix_hash == changed.stable_prefix_hash
    assert base.tool_schema_hash == changed.tool_schema_hash
    assert base.context_hash != changed.context_hash
