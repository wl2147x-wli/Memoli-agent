"""生命周期 phase 执行器。

第五阶段先提供最小 phase 协议和顺序执行函数。后续插件阶段可以在
这个协议上增加 slot、requires、produces 和依赖排序。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from memoli_agent.agent.lifecycle.types import PassiveTurnContext


class PhaseModule(Protocol):
    """生命周期阶段模块协议。"""

    async def run(self, ctx: PassiveTurnContext) -> None:
        """执行阶段逻辑，并把结果写入 ctx。"""

        ...


async def run_phase_modules(
    ctx: PassiveTurnContext,
    modules: Sequence[PhaseModule],
) -> None:
    """按顺序执行一组 phase module。"""

    for module in modules:
        await module.run(ctx)
