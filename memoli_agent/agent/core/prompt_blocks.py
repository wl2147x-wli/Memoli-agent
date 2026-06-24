"""Prompt block 定义。

第三阶段先提供最小 system prompt。后续接入 memory、skills、tools 后，
可以继续把 system prompt 拆成多个 block，并按 token 预算裁剪。
"""

from __future__ import annotations


def build_system_prompt(agent_name: str) -> str:
    """构建基础 system prompt。"""

    return (
        f"你是 {agent_name}，一个重视长期记忆、清晰表达和持续学习的智能体。\n"
        "你会认真理解用户当前输入，并在后续阶段逐步结合会话历史、工具和记忆作答。"
    )
