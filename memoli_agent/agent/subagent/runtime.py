"""SubAgent 运行时。

SubAgentRuntime 只负责执行一个已经创建好的子任务。任务目录、task_id、
后台回流等生命周期由 SubAgentManager 管理。
"""

from __future__ import annotations

from dataclasses import dataclass

from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.subagent.events import SubAgentResult, SubAgentTask
from memoli_agent.agent.subagent.profiles import SubAgentProfile
from memoli_agent.agent.types import ChatMessage


@dataclass(slots=True)
class SubAgentRuntime:
    """进程内子 agent 运行时。"""

    reasoner: Reasoner
    profiles: dict[str, SubAgentProfile]

    async def run(self, task: SubAgentTask) -> SubAgentResult:
        """执行子任务并返回结果。"""

        profile = self.profiles.get(task.profile_name)
        if profile is None:
            return SubAgentResult(
                task_id=task.task_id,
                content=f"子 agent profile 不存在：{task.profile_name}",
                success=False,
                profile_name=task.profile_name,
                task_dir=task.task_dir,
                metadata={"error": "UnknownProfile"},
            )

        try:
            response = await self.reasoner.generate(
                [
                    ChatMessage(
                        role="system",
                        content=_build_subagent_system_prompt(profile),
                    ),
                    ChatMessage(role="user", content=task.instruction),
                ]
            )
        except Exception as exc:
            return SubAgentResult(
                task_id=task.task_id,
                content=f"子 agent 执行失败：{exc}",
                success=False,
                profile_name=profile.name,
                task_dir=task.task_dir,
                metadata={"error": type(exc).__name__},
            )

        return SubAgentResult(
            task_id=task.task_id,
            content=response.content,
            success=True,
            profile_name=profile.name,
            task_dir=task.task_dir,
            metadata={
                "provider": response.provider,
                "fallback_used": response.fallback_used,
            },
        )


def _build_subagent_system_prompt(profile: SubAgentProfile) -> str:
    """构建子 agent 的独立系统提示词。"""

    allowed_tools = ", ".join(profile.allowed_tools) or "无"
    return (
        f"你是 Memoli 的本地子 agent，当前 profile 是 {profile.name}。\n"
        f"profile 说明：{profile.description}\n"
        f"允许的工具范围：{allowed_tools}\n"
        f"最大迭代次数：{profile.max_iterations}\n"
        "请专注完成主 agent 委派的任务，输出清晰、可直接交回主 agent 使用的结果。\n"
        "不要声称你拥有系统级沙箱权限；如果信息不足，请说明限制。"
    )
