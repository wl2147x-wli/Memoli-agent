"""资源边界夹具：覆盖循环、内存、进程、输出和超大 RPC。"""

import subprocess
import sys

from memoli_agent.agent.tools.base import ToolResult


class ResourceBombTool:
    name = "resource_bomb"
    description = "仅用于容器资源边界回归"
    parameters = {
        "type": "object",
        "properties": {"mode": {"type": "string"}},
        "required": ["mode"],
    }

    async def run(self, arguments):
        mode = arguments["mode"]
        if mode == "memory":
            blocks = []
            while True:
                blocks.append(bytearray(8 * 1024 * 1024))
        if mode == "process":
            children = []
            while True:
                children.append(
                    subprocess.Popen(
                        [sys.executable, "-c", "import time;time.sleep(60)"]
                    )
                )
        if mode == "output":
            while True:
                print("x" * 4096, file=sys.stderr, flush=True)
        if mode == "rpc":
            return ToolResult("x" * 100_000)
        while True:
            pass


class Plugin:
    def register(self, registrar):
        from memoli_agent.agent.plugins.events import HookName

        registrar.add_observer(HookName.TURN_AFTER, self.loop)
        registrar.add_tool(ResourceBombTool())

    async def initialize(self, context):
        pass

    async def terminate(self):
        pass

    def loop(self, event):
        while True:
            pass


def create_plugin():
    return Plugin()
