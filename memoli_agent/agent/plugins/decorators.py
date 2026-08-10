"""兼容导入位置：公共实现已迁移到 :mod:`plugins.hooks`。"""

from memoli_agent.agent.plugins.hooks import HookBus, HookRegistration

__all__ = ["HookBus", "HookRegistration"]
