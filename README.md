<p align="center"><strong>Memoli-agent</strong></p>

<p align="center">
  一个开源的个人 AI 助理（Agent Harness）：主动规划任务、操作电脑与外部服务、创建并运行技能、
  构建个人知识库与长期记忆，并在日常使用中自我演化。
</p>

Memoli-agent 轻量、易部署、易于扩展：可接入主流大模型厂商，7×24 小时运行在个人电脑或服务器上，
同时服务 Web 控制台与主流 IM 渠道。

---

## ✨ 核心特性

| 能力 | 说明 |
| :--- | :--- |
| 规划与执行 | 分解复杂任务并逐步执行，围绕工具循环推理直至达成目标 |
| 记忆 | 三层记忆架构（上下文 → 每日记忆 → MEMORY.md），夜间 Deep Dream 自动蒸馏，关键词 + 向量混合检索 |
| 知识库 | 自动把对话中的结构化知识整理为 Markdown 知识库，并维护可浏览的知识图谱 |
| 自我演化 | 自动评审对话以改进技能、跟进未完成任务、沉淀记忆与知识，随使用不断成长 |
| 技能（Skills） | 以 SKILL.md 清单定义的工作流；支持从 GitHub 等来源安装，或通过对话创建自定义技能 |
| 工具（Tools） | 内置文件读写、终端、浏览器、定时任务、记忆检索、联网搜索等 10+ 工具，并原生集成 MCP 协议 |
| 渠道（Channels) | Web 控制台、微信、飞书、钉钉、企业微信、QQ、公众号、Telegram、Slack 等 |
| 多模态 | 文本、图片、语音、文件的识别、生成与发送 |
| 模型 | Claude、GPT、Gemini、DeepSeek、Qwen、GLM、Kimi、MiniMax、豆包等主流模型，可在 Web 控制台一键切换 |
| 部署 | 源码 / Docker 多种部署方式，统一 Web 控制台管理 |

## 🏗️ 架构

Memoli-agent 是一套完整的 **Agent Harness**：消息经由 **Channels（渠道层）** 进入；**Agent 核心**
（`agent/`）基于记忆、知识库、可用工具与技能进行规划与推理；**Models（模型层）** 生成响应并经原渠道返回。
各层解耦、可独立扩展。

代码结构概览：

```text
Memoli-agent/
├── app.py                  # 进程入口：启动顺序编排（证书→配置→迁移→通道→预热）
├── config.py               # 配置加载与默认值
├── run.sh                  # 启动/管理脚本
│
├── bridge/                 # 桥接层：连接渠道与 Agent 核心
│   ├── bridge.py           #   Bot 类型选择与模型路由
│   ├── agent_bridge.py     #   请求生命周期：路由、运行记录、消息持久化、文件回复
│   ├── agent_initializer.py#   Agent 初始化：工作区、记忆、工具、技能、系统提示
│   ├── agent_event_handler.py # 运行事件转发（含流式/中间思考节流）
│   ├── context.py / reply.py  # 上下文与回复数据结构
│
├── agent/                  # Agent 核心
│   ├── registry.py / routing.py / team.py   # 代理注册表、路由、团队名册
│   ├── protocol/           #   Agent 抽象与执行器（agent_stream：工具循环、
│   │                       #   上下文修剪/压缩、重试与后备切换、流式处理）
│   ├── memory/             #   长期记忆：三层架构、混合检索、切块、嵌入、摘要、Deep Dream
│   │   └── embedding/      #     嵌入提供者与向量后端
│   ├── knowledge/          #   个人知识库（Markdown wiki + 知识图谱）
│   ├── skills/             #   技能系统（SKILL.md 加载、依赖检测、提示注入）
│   ├── tools/              #   内置工具：bash / 浏览器 / 文件读写 / 搜索 / 定时任务 /
│   │                       #   视觉 / 联网搜索 / MCP / 发送 / 子代理等
│   ├── permission/         #   权限模式与路径防护
│   ├── prompt/             #   系统提示构建与工作区上下文文件
│   ├── subagent/           #   子代理（并行委派、预算控制）
│   ├── evolution/          #   自我演化（空闲触发、评审代理、撤销）
│   ├── chat/ workspace/    #   会话服务与工作区管理
│   └── observability/      #   （规划中）Langfuse 可观测层
│
├── models/                 # 模型层：各厂商适配
│   ├── openai_compatible_bot.py  # OpenAI 兼容协议统一实现（工具调用/流式）
│   ├── claudeapi/ chatgpt/ gemini/ openai/ linkai/    # 各厂商 Bot
│   ├── zhipuai/ dashscope/ doubao/ minimax/ moonshot/ deepseek/
│   ├── qianfan/ xunfei/ mimo/ modelscope/ baidu/
│   └── bot_factory.py      #   模型工厂
│
├── channel/                # 渠道层
│   ├── web/                #   Web 控制台（默认渠道，SSE 流式）
│   ├── feishu/ dingtalk/ wecom_bot/ wechatmp/ wechatcom/ wechat_kf/ weixin/
│   ├── telegram/ slack/ discord/ qq/
│   └── channel_instances.py #  多实例渠道管理（多飞书机器人等）
│
├── plugins/                # 插件系统（cow_cli / godcmd / banwords 等）
├── cli/                    # cow 命令行工具（start/stop/skill/backup 等）
├── skills/                 # 内置技能
├── common/                 # 公共组件（配置、日志、常量、状态目录、工具函数）
├── voice/ translate/       # 语音与翻译子模块
├── tests/                  # 测试
└── docs/                   # 文档
```

## 🚀 快速开始

### 源码运行

```bash
# 1. 克隆仓库并安装依赖
git clone <your-repo-url> memoli-agent
cd memoli-agent
pip install -r requirements.txt

# 2. 生成配置
cp config-template.json config.json
# 编辑 config.json，至少填入一个模型的 api_key

# 3. 启动（Linux / macOS）
bash run.sh

# 或直接运行
python app.py
```

### Docker

```bash
docker build -t memoli-agent .
docker run -d -p 9899:9899 --name memoli memoli-agent
```

启动后访问 `http://localhost:9899` 打开 **Web 控制台**——聊天、配置模型、接入渠道、管理技能的一站式入口。

> 部署在服务器上时，请在 `config.json` 中把 `web_host` 设为 `0.0.0.0`，并设置 `web_password` 保护控制台；
> 记得在防火墙/安全组放行 `9899` 端口（默认端口，可在 `config.json` 的 `web_port` 修改）。

安装后可用 `cow` 命令行管理服务：

```bash
cow start | stop | restart        # 服务控制
cow status | logs                 # 状态与日志
cow skill install <name>          # 安装技能
cow install-browser               # 安装浏览器自动化
```

## 🤖 模型

支持主流大模型厂商。**对话、视觉、图像生成、语音识别/合成、嵌入**可以分别路由到不同厂商，
全部在 Web 控制台内配置，无需手改文件。

| 厂商 | 代表模型 | 对话 | 视觉 | 图像生成 | 语音识别 | 语音合成 | 嵌入 |
| --- | --- | :-: | :-: | :-: | :-: | :-: | :-: |
| DeepSeek | deepseek-v4 系列 | ✅ | | | | | |
| Claude | claude-opus / sonnet | ✅ | ✅ | | | | |
| OpenAI | gpt-5 系列 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Gemini | gemini 系列模型 | ✅ | ✅ | ✅ | | | |
| MiniMax | MiniMax-M3 | ✅ | ✅ | ✅ | | ✅ | |
| GLM | glm-5.3-flash | ✅ | ✅ | | ✅ | | ✅ |
| Qwen | qwen3.8-flash | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Kimi | kimi-k3 | ✅ | ✅ | | | | |
| 豆包 | doubao-seed 系列 | ✅ | ✅ | ✅ | | | ✅ |
| 文心 | ernie 系列 | ✅ | ✅ | | | | |
| MiMo | mimo 系列 | ✅ | ✅ | | | ✅ | |
| 自定义 | 本地模型 / 第三方代理（OpenAI 兼容） | ✅ | | | | | |

## 💬 渠道

单个 Agent 实例可同时服务多个渠道，大部分渠道可直接在 Web 控制台完成配置。

| 渠道 | 文本 | 图片 | 文件 | 语音 | 群聊 |
| --- | :-: | :-: | :-: | :-: | :-: |
| Web 控制台（默认） | ✅ | ✅ | ✅ | ✅ | |
| Telegram | ✅ | ✅ | ✅ | ✅ | ✅ |
| Slack | ✅ | ✅ | ✅ | | ✅ |
| Discord | ✅ | ✅ | ✅ | | ✅ |
| 微信 | ✅ | ✅ | ✅ | ✅ | |
| 飞书 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 钉钉 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 企业微信机器人 | ✅ | ✅ | ✅ | ✅ | ✅ |
| QQ | ✅ | ✅ | ✅ | | ✅ |
| 企业微信应用 | ✅ | ✅ | ✅ | ✅ | |
| 微信客服 | ✅ | ✅ | ✅ | ✅ | |
| 微信公众号 | ✅ | ✅ | | ✅ | |

## 🧠 记忆与知识库

**长期记忆**采用三层架构：会话上下文（短期）→ 每日记忆（中期）→ MEMORY.md（长期）。
每晚会执行一次 **Deep Dream**，把零散记忆蒸馏为精炼的长期条目与叙事日志。

**个人知识库**按主题（而非时间线）组织结构化知识：Agent 自动从对话中提炼有价值的信息、
维护交叉引用与索引，Web 控制台提供交互式知识图谱视图。

## 🔧 工具与技能

**工具**是 Agent 操作系统资源与外部服务的原子能力；**技能**是通过 SKILL.md 清单定义的
更高层工作流，组合多个工具完成复杂任务。

### 工具系统

内置工具覆盖：文件读写（`read` / `write` / `edit` / `ls`）、终端（`bash`）、文件发送（`send`）、
记忆检索（`memory`）、环境变量（`env_config`）、网页抓取（`web_fetch`）、定时任务（`scheduler`）、
联网搜索（`web_search`）、视觉（`vision`）、浏览器自动化（`browser`）等。

**MCP 协议**：一个 `mcp.json` 即可接入 Model Context Protocol 服务器的开放生态，
支持 stdio / SSE 传输、热重载与按需工具检索。

### 技能系统

- 从 GitHub 等任意来源安装技能，或使用 `skill-creator` 通过对话生成自定义技能
- 技能以 Markdown 清单描述依赖、安装方式与使用流程，Agent 自动判断可用性

```bash
/skill list                    # 查看已安装技能
/skill search <keyword>        # 搜索技能
/skill install <name>          # 一键安装
```

## 🛠️ 开发与贡献

欢迎各种形式的贡献：新功能、Bug 修复、性能优化、文档改进。请阅读
[CONTRIBUTING.md](CONTRIBUTING.md) 后提交 Issue 或 Pull Request。

## ⚠️ 免责声明

1. 本项目基于 MIT 许可证开源，仅供技术研究与学习使用。使用者需自行遵守所在地区的法律法规，
   项目维护者不对使用本项目产生的任何后果承担责任。
2. **成本与安全**：Agent 模式的 token 消耗显著高于普通对话，请选择质量与成本平衡的模型。
   Agent 可以访问本地操作系统，请只在受信任的环境中部署。
3. 本项目为纯开源项目，不参与、不授权、不发行任何加密货币。
