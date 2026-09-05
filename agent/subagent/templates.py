"""Sub agent types: what kinds of worker the main Agent can spawn.

A template is a role, not an identity. It carries a system prompt and a tool
allowlist, and nothing else: no memory, no channel, no place in the Agent
registry. Users add their own as markdown files under ``<workspace>/subagents``,
the same shape skills already use.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from common.log import logger

# 无论使用哪个模板，以下这些工具都禁止子代理调用。
#
# 它们都会越出委派的任务范围：`send` 和 `scheduler` 会以父代理的
# 名义在用户的频道上行动，而 `env_config` 和
# `evolution_undo` 则会改动代理自身。`subagent` 工具本身也被禁用，
# 这样即使模板被授予“全部工具”也无法无限递归；
# 实际允许的嵌套深度由深度限制来控制。
#
# 内存类工具则有意不加拦截：子代理应当能够搜索并阅读
# 共享知识库，为其工作提供依据；但它仍然没有自己的记忆
# （memory_manager 为 None），因此只能读取、永远不会写回。
BLOCKED_TOOLS = frozenset(
    {
        "subagent",
        "send",
        "scheduler",
        "env_config",
        "evolution_undo",
    }
)

READ_ONLY_TOOLS = (
    "read", "ls", "search_files", "web_search", "web_fetch", "vision",
    "memory_search", "memory_get",
)

_ALL_TOOLS = "*"


@dataclass(frozen=True)
class SubagentTemplate:
    """One spawnable role."""

    name: str
    # 这段描述会展示在生成子代理的工具说明中，主代理正是
    # 依据它来做路由，因此它应说明“何时选用此类型”，而不是“此类型是什么”。
    description: str
    prompt: str
    # 允许使用的工具名，或用 ["*"] 表示继承父代理拥有的全部工具；
    # 无论哪种情况，都还要减去 BLOCKED_TOOLS。
    tools: List[str] = field(default_factory=lambda: [_ALL_TOOLS])
    source: str = "builtin"

    def allows_all_tools(self) -> bool:
        return _ALL_TOOLS in self.tools

    def inherits_skills(self) -> bool:
        """Whether the parent's skills are worth putting in front of this type.

        A skill is a workflow written end to end, and most of them finish by
        writing something down. Shown to a sub agent that had those tools
        taken away, it reads as an instruction that cannot be carried out: the
        agent spends turns preparing for a step it will never reach, then says
        so in the report the parent has to read. Full tool set, full skills;
        anything narrower, none.
        """
        return self.allows_all_tools()

    def select_tools(self, available: List) -> List:
        """Pick this template's tools out of the parent's set."""
        allowed = []
        for tool in available:
            if tool.name in BLOCKED_TOOLS:
                continue
            if self.allows_all_tools() or tool.name in self.tools:
                allowed.append(tool)
        return allowed


GENERAL_PURPOSE = SubagentTemplate(
    name="general-purpose",
    description=(
        "Multi-step work that needs both investigation and action: search, read, "
        "run commands, write files. Use when you know the goal but not how many "
        "steps it takes to get there."
    ),
    prompt=(
        "You are a focused sub agent. You have been given one task by the agent "
        "that spawned you, and you cannot see its conversation or ask the user "
        "anything, so work from the task and context you were given. You can "
        "search and read the shared memory / knowledge base for background you "
        "need.\n\n"
        "Finish the task and nothing beyond it, then reply with what you found "
        "or changed, the paths of any files you touched, and anything you could "
        "not resolve. Your reply is the only thing that reaches the agent that "
        "spawned you: intermediate steps are discarded, so leave nothing "
        "important out. Do not pad it either — it lands in that agent's "
        "context window."
    ),
)

EXPLORE = SubagentTemplate(
    name="explore",
    description=(
        "Read-only investigation: find files, search code or documents, gather "
        "facts from the web. Use when the answer is somewhere and needs finding, "
        "and nothing needs to change."
    ),
    prompt=(
        "You are a read-only sub agent. You investigate and report; you never "
        "modify anything. You cannot see the conversation of the agent that "
        "spawned you and cannot ask the user anything, but you can search and "
        "read the shared memory / knowledge base.\n\n"
        "Report what you found, with concrete file paths, line numbers, URLs or "
        "quotes so the answer can be checked without redoing your search. Say so "
        "plainly when you did not find something, rather than guessing."
    ),
    tools=list(READ_ONLY_TOOLS),
)

BUILTIN_TEMPLATES = (GENERAL_PURPOSE, EXPLORE)
DEFAULT_TEMPLATE_NAME = GENERAL_PURPOSE.name


def _parse_tools(raw) -> List[str]:
    if raw is None:
        return [_ALL_TOOLS]
    if isinstance(raw, str):
        names = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, (list, tuple)):
        names = [str(part).strip() for part in raw]
    else:
        return [_ALL_TOOLS]
    names = [name for name in names if name]
    return names or [_ALL_TOOLS]


def parse_template(content: str, fallback_name: str, source: str) -> Optional[SubagentTemplate]:
    """Parse one markdown template. Returns None when it is unusable."""
    from agent.skills.frontmatter import parse_frontmatter

    frontmatter = parse_frontmatter(content) or {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) == 3:
            body = parts[2]
    body = body.strip()

    name = str(frontmatter.get("name") or fallback_name).strip()
    description = str(frontmatter.get("description") or "").strip()
    if not name or not description or not body:
        # 这三者都必不可少：没有描述，主代理就缺乏
        # 路由到该类型的依据；没有正文，子代理就没有
        # 可据以执行的指令。
        return None

    return SubagentTemplate(
        name=name,
        description=description,
        prompt=body,
        tools=_parse_tools(frontmatter.get("tools")),
        source=source,
    )


def load_templates(workspace_dir: Optional[str] = None) -> Dict[str, SubagentTemplate]:
    """Built-in types plus any the user defined, keyed by name.

    A user file reusing a built-in name replaces it, which is how a built-in
    gets customized rather than worked around.
    """
    templates: Dict[str, SubagentTemplate] = {t.name: t for t in BUILTIN_TEMPLATES}

    from common.state_dir import subagents_dir

    directory = subagents_dir(base=workspace_dir) if workspace_dir else subagents_dir()
    if not os.path.isdir(directory):
        return templates

    for entry in sorted(os.listdir(directory)):
        if not entry.endswith(".md"):
            continue
        # 随附的格式说明文档也放在这个目录里，但它只是文档，并不是
        # 模板：若把它加载进来，每一轮都会在代理面前
        # 多出一个多余的条目。
        if entry.lower() == "readme.md":
            continue
        path = os.path.join(directory, entry)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except OSError as e:
            logger.warning(f"[SubAgent] Cannot read template {path}: {e}")
            continue

        template = parse_template(content, os.path.splitext(entry)[0], source=path)
        if template is None:
            logger.warning(
                f"[SubAgent] Ignoring {path}: a template needs a 'description' "
                f"in its frontmatter and a non-empty body"
            )
            continue
        templates[template.name] = template

    return templates
