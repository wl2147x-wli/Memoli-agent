# Memoli-agent 文档导航

项目文档按用途分类存放。根目录 `README.md` 仅保留项目入口、安装方式和
常用命令，详细设计与约定以此目录为准。

## 架构

- [项目架构蓝图](architecture/project-blueprint.md)
- [运行链路流程图](architecture/runtime-flow.md)

## 开发

- [开发路线图](development/roadmap.md)
- [项目约定](development/conventions.md)
- [OpenSpec 开发工作流](development/openspec-workflow.md)

## 系统能力

- [Agent Runtime](systems/agent-runtime.md)
- [LLM Providers](systems/llm-providers.md)
- [记忆系统](systems/memory.md)
- [插件系统](systems/plugins.md)
- [插件安全边界](systems/plugin-security.md)
- [SubAgent 系统](systems/subagents.md)
- [极简工具系统](systems/tools.md)
- [版本化 Skill Runtime](systems/skills.md)
- [Skill 宿主管理手册](operations/skill-management.md)
- [Proactive 系统](systems/proactive.md)
- [MCP 系统](systems/mcp.md)

## 评测

- [评测架构](benchmarks/architecture.md)
- [评测配置](benchmarks/configuration.md)

## 文档维护约定

- 当前可观察行为以 `openspec/specs/` 为事实源；行为变更通过 OpenSpec change 推进。
- 架构和流程图保留 Markdown/Mermaid 源文件，不提交可再生成的 HTML、SVG。
- 新增运行能力时，同时更新对应系统文档和根目录 README 的能力摘要。
- 文档示例使用项目相对路径，不写入本机绝对路径或真实密钥。
