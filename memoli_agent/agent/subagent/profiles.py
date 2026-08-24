"""SubAgent profile 与不可绕过的工具装配边界。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memoli_agent.agent.memory.governance import (
    MemoryGovernanceService,
    governance_tools,
)
from memoli_agent.agent.plugins.hooks import HookBus
from memoli_agent.agent.skills.tool import SkillLoadTool
from memoli_agent.agent.tools.base import Tool, ToolResult
from memoli_agent.agent.tools.generic import (
    CodeRunTool,
    FilePatchTool,
    FileReadTool,
    FileWriteTool,
)
from memoli_agent.agent.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class SubAgentProfile:
    """子 Agent 的能力与预算画像。"""

    name: str
    description: str
    allowed_tools: tuple[str, ...]
    max_iterations: int = 6
    max_elapsed_seconds: float = 180.0
    can_write_files: bool = False
    can_use_network: bool = False
    can_delegate: bool = False
    max_depth: int = 1


def default_subagent_profiles() -> dict[str, SubAgentProfile]:
    """返回最小权限的内置 profile。"""

    profiles = (
        SubAgentProfile(
            name="research",
            description="只读调研：读取工作区、召回记忆和使用已启用的网页读取工具。",
            allowed_tools=(
                "time",
                "memory_recall",
                "file_read",
                "web_scan",
                "skill_load",
            ),
            max_iterations=8,
            max_elapsed_seconds=240.0,
            can_use_network=True,
        ),
        SubAgentProfile(
            name="coding",
            description="受限编码：读取工作区，只在独立任务目录写入和执行代码。",
            allowed_tools=(
                "time",
                "file_read",
                "file_patch",
                "file_write",
                "code_run",
                "skill_load",
            ),
            max_iterations=10,
            max_elapsed_seconds=300.0,
            can_write_files=True,
        ),
        SubAgentProfile(
            name="general",
            description="显式选择的通用任务：组合只读调研与任务目录执行能力。",
            allowed_tools=(
                "time",
                "memory_recall",
                "file_read",
                "web_scan",
                "file_patch",
                "file_write",
                "code_run",
                "skill_load",
            ),
            max_iterations=8,
            max_elapsed_seconds=240.0,
            can_write_files=True,
            can_use_network=True,
        ),
        SubAgentProfile(
            name="memory-governor",
            description=(
                "Review exactly one bound offline-memory candidate and submit a "
                "structured decision through the deterministic policy gate."
            ),
            allowed_tools=(
                "governance_candidate_read",
                "governance_evidence_read",
                "governance_related_claims",
                "governance_decide",
            ),
            max_iterations=5,
            max_elapsed_seconds=90.0,
            can_write_files=False,
            can_use_network=False,
            can_delegate=False,
            max_depth=1,
        ),
    )
    return {profile.name: profile for profile in profiles}


@dataclass(frozen=True, slots=True)
class ProfileToolRegistryFactory:
    """为每个任务创建新的 allowlist ToolRegistry。"""

    source_registry: ToolRegistry
    workspace: Path
    hook_bus: HookBus | None = None
    governance_service: MemoryGovernanceService | None = None
    code_timeout_seconds: int = 60
    code_max_output_chars: int = 10_000
    file_read_max_lines: int = 2_000
    file_max_output_chars: int = 15_000

    def build(
        self,
        profile: SubAgentProfile,
        task_dir: Path,
        memory_refs: tuple[str, ...] = (),
        *,
        inherit_hook_bus: bool = True,
    ) -> ToolRegistry:
        """装配实际工具；写工具永远重新绑定到 task_dir。"""

        registry = ToolRegistry(
            hook_bus=self.hook_bus if inherit_hook_bus else None
        )
        source = {tool.name: tool for tool in self.source_registry.list_tools()}
        for name in profile.allowed_tools:
            if name == "skill_load":
                continue
            tool = self._build_scoped_tool(name, task_dir, source, memory_refs)
            if tool is not None:
                registry.register(tool)
        source_loader = source.get("skill_load")
        if "skill_load" in profile.allowed_tools and isinstance(
            source_loader, SkillLoadTool
        ):
            registry.register(
                SkillLoadTool(
                    runtime=source_loader.runtime,
                    tool_names_provider=lambda: {
                        tool.name for tool in registry.list_tools()
                    },
                    mcp_names_provider=lambda: set(),
                    trajectory_store=source_loader.trajectory_store,
                )
            )
        return registry

    def _build_scoped_tool(
        self,
        name: str,
        task_dir: Path,
        source: dict[str, Tool],
        memory_refs: tuple[str, ...],
    ) -> Tool | None:
        if name.startswith("governance_"):
            delegate = next(
                (
                    tool
                    for tool in (
                        governance_tools(self.governance_service)
                        if self.governance_service is not None
                        else ()
                    )
                    if tool.name == name
                ),
                None,
            )
            binding = next(
                (
                    reference.removeprefix("governance-job:")
                    for reference in memory_refs
                    if reference.startswith("governance-job:")
                ),
                "",
            )
            binder = getattr(delegate, "bind", None)
            return (
                binder(binding) if delegate is not None and binding and binder else None
            )
        if name == "file_read":
            return FileReadTool(
                self.workspace,
                max_lines=self.file_read_max_lines,
                max_output_chars=self.file_max_output_chars,
            )
        if name == "file_patch":
            return FilePatchTool(task_dir)
        if name == "file_write":
            return FileWriteTool(task_dir)
        if name == "code_run":
            return CodeRunTool(
                task_dir,
                default_timeout_seconds=self.code_timeout_seconds,
                max_output_chars=self.code_max_output_chars,
                runner="container",
                allow_network=False,
            )
        if name == "memory_recall":
            delegate = source.get(name)
            if delegate is None or not memory_refs:
                return None
            return ContextBoundMemoryRecallTool(delegate, memory_refs)
        # time、memory_recall、web_scan 等只读工具可安全复用已装配实例。
        return source.get(name)


@dataclass(frozen=True, slots=True)
class ContextBoundMemoryRecallTool:
    """只允许检索 Context Package 明确给出的记忆引用。"""

    delegate: Tool
    allowed_refs: tuple[str, ...]
    name: str = "memory_recall"
    description: str = "检索 Context Package 明确授权的长期记忆引用。"

    @property
    def parameters(self) -> dict[str, Any]:
        return self.delegate.parameters

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or "")
        if not any(reference in query for reference in self.allowed_refs):
            return ToolResult(
                "检索请求未包含 Context Package 授权的记忆引用。",
                success=False,
                status="denied",
                metadata={"tool": self.name},
            )
        return await self.delegate.run(arguments)
