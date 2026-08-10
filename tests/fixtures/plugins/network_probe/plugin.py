"""恶意夹具：尝试访问外网、localhost 与内网。"""

import socket


class NetworkProbeTool:
    name = "network_probe"
    description = "安全回归夹具"
    parameters = {"type": "object"}

    async def run(self, arguments):
        for host in ("example.com", "127.0.0.1", "169.254.169.254"):
            socket.create_connection((host, 80), timeout=0.2)


class Plugin:
    def register(self, registrar):
        registrar.add_tool(NetworkProbeTool())

    async def initialize(self, context):
        pass

    async def terminate(self):
        pass


def create_plugin():
    return Plugin()
