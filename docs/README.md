# Memoli-agent 文档导航

项目文档按用途分类存放。根目录 `README.md` 仅保留项目入口、安装方式和
常用命令，详细设计与约定以此目录为准。

## 架构

- [项目架构蓝图](architecture/project-blueprint.md)
- [运行链路流程图](architecture/runtime-flow.md)

## 开发

- [开发路线图](development/roadmap.md)
- [项目约定](development/conventions.md)

## 系统能力

- [记忆系统](systems/memory.md)
- [插件系统](systems/plugins.md)
- [SubAgent 系统](systems/subagents.md)
- [Proactive 系统](systems/proactive.md)
- [MCP 系统](systems/mcp.md)

## 评测

- [评测架构](benchmarks/architecture.md)
- [评测配置](benchmarks/configuration.md)

## 文档维护约定

- 架构和流程图保留 Markdown/Mermaid 源文件，不提交可再生成的 HTML、SVG。
- 新增运行能力时，同时更新对应系统文档和根目录 README 的能力摘要。
- 文档示例使用项目相对路径，不写入本机绝对路径或真实密钥。
