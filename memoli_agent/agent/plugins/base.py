"""插件基础协议。

第八阶段只实现本地 Python 插件，不做热加载、隔离进程或依赖安装。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PluginMeta:
    """插件元信息。"""

    name: str
    version: str = "0.1.0"
    description: str = ""


@dataclass(frozen=True, slots=True)
class PluginLoadResult:
    """插件加载结果。"""

    name: str
    success: bool
    error: str = ""


class Plugin(Protocol):
    """插件协议。"""

    name: str

    async def initialize(self, context: object) -> None:
        """初始化插件。"""

        ...

    async def terminate(self, context: object) -> None:
        """关闭插件。"""

        ...

    def register(self, context: object) -> None:
        """注册工具、hooks 或其他扩展。"""

        ...
