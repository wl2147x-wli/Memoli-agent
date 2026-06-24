"""Memoli-agent 命令行入口。

第二阶段开始，入口文件只负责顶层启动流程：

1. 加载 config.toml，缺失时使用默认配置。
2. 构建 AppRuntime。
3. 启动 runtime 并在退出时关闭后台任务。

具体对象装配逻辑放在 memoli_agent.bootstrap 包中。
"""

from __future__ import annotations

import asyncio

from memoli_agent.bootstrap.app import build_app_runtime
from memoli_agent.bootstrap.config import load_config


async def main() -> None:
    """启动 Memoli-agent。"""

    config = load_config()
    runtime = build_app_runtime(config)

    await runtime.start()
    try:
        await runtime.run()
    finally:
        await runtime.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
