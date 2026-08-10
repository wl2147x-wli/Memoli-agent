"""插件公共协议与元数据。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from memoli_agent.agent.plugins.context import PluginRuntimeContext
    from memoli_agent.agent.plugins.registrar import PluginRegistrar


class PluginExecutionMode(StrEnum):
    """插件执行模式。"""

    IN_PROCESS = "in_process"
    SANDBOX = "sandbox"


@dataclass(frozen=True, slots=True)
class PluginLoadResult:
    """插件加载或激活结果。"""

    name: str
    success: bool
    stage: str = "load"
    error: str = ""
    backend: str = ""


class Plugin(Protocol):
    """进程内与沙箱 runner 共同遵守的插件协议。"""

    def register(self, registrar: PluginRegistrar) -> None:
        """声明 hooks、工具或其他贡献。"""

        ...

    async def initialize(self, context: PluginRuntimeContext) -> None:
        """在贡献提交前完成运行期初始化。"""

        ...

    async def terminate(self) -> None:
        """释放插件自身资源。"""

        ...
