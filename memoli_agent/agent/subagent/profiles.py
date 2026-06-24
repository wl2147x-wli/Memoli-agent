"""SubAgent 权限配置。

第九阶段的 profile 只做进程内逻辑约束，用来描述子 agent 的能力边界。
它不是系统级沙箱，但可以让后续工具过滤、MCP 权限和外部 agent 接入有稳定入口。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SubAgentProfile:
    """子 agent 权限画像。"""

    name: str
    description: str
    allowed_tools: list[str] = field(default_factory=list)
    max_iterations: int = 4
    can_write_files: bool = False
    can_use_network: bool = False


def default_subagent_profiles() -> dict[str, SubAgentProfile]:
    """返回内置子 agent profile。"""

    profiles = [
        SubAgentProfile(
            name="general",
            description="通用分析型子 agent，适合总结、拆解和轻量推理任务。",
            allowed_tools=["time", "calculator", "memory_recall"],
            max_iterations=4,
        ),
        SubAgentProfile(
            name="research",
            description="研究型子 agent，适合围绕已有上下文进行检索、归纳和报告。",
            allowed_tools=["time", "memory_recall", "filesystem_read"],
            max_iterations=6,
            can_use_network=False,
        ),
        SubAgentProfile(
            name="coding",
            description="代码阅读型子 agent，适合阅读 workspace 内文件并给出实现建议。",
            allowed_tools=["time", "calculator", "filesystem_read"],
            max_iterations=6,
            can_write_files=False,
        ),
    ]
    return {profile.name: profile for profile in profiles}
