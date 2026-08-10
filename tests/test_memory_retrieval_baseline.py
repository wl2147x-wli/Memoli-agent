from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from memoli_agent.agent.memory.models import (
    EvidenceRef,
    MemoryItem,
    MemoryMutation,
    MemoryQuery,
    MemoryQueryResult,
    MemoryScope,
)
from memoli_agent.agent.memory.runtime import MemoryRuntime
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore


def _explicit(content: str, *, scope: MemoryScope | None = None) -> MemoryMutation:
    return MemoryMutation(
        content=content,
        scope=scope or MemoryScope(),
        evidence=(EvidenceRef("message", f"msg-{content}", content),),
    )


def test_keyword_scope_type_quota_and_empty_result_baseline(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    default_claim = store.append_claim(_explicit("项目使用 SQLite 保存记忆"))
    store.append_claim(
        _explicit(
            "其他项目也使用 SQLite",
            scope=MemoryScope("project", "other"),
        )
    )
    store.create_card(
        title="存储偏好",
        content="长期记忆使用 SQLite",
        claim_relations=((default_claim.item_id, "supports"),),
    )

    result = store.search(
        MemoryQuery("SQLite", limit=2, card_limit=1, claim_limit=1, episode_limit=0)
    )
    assert [item.item_type for item in result.items] == ["card", "claim"]
    assert all(
        item.metadata.get("scope_id", "default") != "other" for item in result.items
    )
    assert store.search(MemoryQuery("完全不存在的词")).items == []


@dataclass
class _CaptureRetriever:
    request: MemoryQuery | None = None

    def query(self, request: MemoryQuery) -> MemoryQueryResult:
        self.request = request
        return MemoryQueryResult(
            [
                MemoryItem(
                    content="123456",
                    source="test",
                    timestamp=datetime.now(UTC),
                    item_id="one",
                ),
                MemoryItem(
                    content="abcdef",
                    source="test",
                    timestamp=datetime.now(UTC),
                    item_id="two",
                ),
            ],
            candidate_count=2,
            reason="baseline",
        )


class _NoCoreStore:
    def select_core_cards(
        self, scope: MemoryScope, *, limit: int, max_chars: int
    ) -> list[MemoryItem]:
        return []


def test_passive_recall_checkpoint_and_budget_baseline() -> None:
    retriever = _CaptureRetriever()
    runtime = MemoryRuntime(_NoCoreStore(), retriever, recall_chars=7)

    async def scenario() -> None:
        result = await runtime.pre_recall(
            user_message="继续实现",
            objective="完成记忆系统",
            current_step="增加检索测试",
        )
        assert retriever.request is not None
        assert retriever.request.query == "继续实现"
        assert retriever.request.objective == "完成记忆系统"
        assert retriever.request.current_step == "增加检索测试"
        assert [item.item_id for item in result.items] == ["one"]
        assert result.injected_chars == 6
        assert runtime.render_prompt_block(MemoryQueryResult([])) == ""

    asyncio.run(scenario())


def test_card_versions_and_database_reopen_baseline(tmp_path: Path) -> None:
    database = tmp_path / "memory.db"
    store = SQLiteMemoryStore(database)
    claim = store.append_claim(_explicit("使用中文注释"))
    card = store.create_card(
        title="代码偏好",
        content="使用中文注释",
        claim_relations=((claim.item_id, "supports"),),
    )
    revised = store.revise_card(
        card.card_id,
        title="代码偏好",
        content="核心代码使用中文注释",
        actor="human",
    )
    assert revised.current_version.version == 2
    store.close()

    reopened = SQLiteMemoryStore(database)
    assert reopened.search(MemoryQuery("中文注释")).items
    reopened.close()
    connection = sqlite3.connect(database)
    versions = connection.execute(
        "SELECT version FROM card_versions WHERE card_id=? ORDER BY version",
        (card.card_id,),
    ).fetchall()
    connection.close()
    assert versions == [(1,), (2,)]
