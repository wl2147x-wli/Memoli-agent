# Memoli-agent 本地启动说明

本文档适用于以下本地服务：

- 对话模型：`qwen3-1.7b`，API 位于 `http://localhost:8000/v1`
- Embedding 模型：`qwen3-embedding-0.6b`，API 位于 `http://127.0.0.1:7997/v1`
- 项目目录：`D:\project\Memoli-agent`

命令以 Windows PowerShell 为例。每个长期运行的服务应使用独立终端。

## 1. 启动 Embedding 服务

在第一个 PowerShell 终端中进入已安装 `infinity_emb` 的 Python 环境，然后运行：

```powershell
conda activate embedding-gpu

cd D:\project\embedding

$env:HF_HOME = "D:\project\embedding\cache"
$env:INFINITY_ANONYMOUS_USAGE_STATS = "0"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$env:TOKENIZERS_PARALLELISM = "false"

Remove-Item Env:TRANSFORMERS_CACHE -ErrorAction SilentlyContinue

infinity_emb v2 `
  --model-id Qwen/Qwen3-Embedding-0.6B `
  --served-model-name qwen3-embedding-0.6b `
  --engine torch `
  --device cuda `
  --device-id 0 `
  --dtype bfloat16 `
  --batch-size 8 `
  --no-compile `
  --no-bettertransformer `
  --host 127.0.0.1 `
  --port 7997 `
  --url-prefix /v1
```

首次运行可能需要下载模型。看到服务监听 `127.0.0.1:7997` 后保持终端运行。

检查模型列表：

```powershell
Invoke-RestMethod http://127.0.0.1:7997/v1/models
```

检查 Embedding 输出维度：

```powershell
python -c "from openai import OpenAI; c=OpenAI(base_url='http://127.0.0.1:7997/v1', api_key='EMPTY'); r=c.embeddings.create(model='qwen3-embedding-0.6b', input=['记忆系统测试']); print(len(r.data[0].embedding))"
```

正常结果应为 `1024`。

## 2. 确认对话模型服务

主对话和离线记忆 Extractor 使用 `qwen3-1.7b`：

```powershell
Invoke-RestMethod http://localhost:8000/v1/models
```

返回结果中应包含 `qwen3-1.7b`。Memoli 使用自动工具调用，因此 vLLM 服务必须启用：

```text
--enable-auto-tool-choice --tool-call-parser hermes
```

Qwen3 默认开启 thinking。Memoli 的本地端点必须配置
`dialect = "qwen-vllm"`，并把模型窗口配置为实际的 `32768`：

```toml
[llm.providers.local]
protocol = "openai-compatible"
base_url = "http://localhost:8000/v1"
api_key = "EMPTY"
dialect = "qwen-vllm"

[llm.models.main]
provider = "local"
model = "qwen3-1.7b"
context_window_tokens = 32768
context_safety_margin_tokens = 2048
max_output_tokens = 4096
reasoning_mode = "off"
reasoning_visibility = "hidden"
```

此配置会让每个请求显式携带
`chat_template_kwargs.enable_thinking = false`，不依赖服务端默认值。如果希望模型
内部进行推理，可改为 `reasoning_mode = "adaptive"`；Memoli 仍只发布最终回答。
服务端也可增加 `--reasoning-parser qwen3`，使推理进入独立字段，但这只是额外防线，
不能代替 `qwen-vllm` 方言。若 vLLM 版本不支持该 parser，保持硬关闭 thinking。

## 3. 安装项目依赖

首次运行或依赖更新后，在新的 PowerShell 终端执行：

```powershell
cd D:\project\Memoli-agent
python -m pip install -e .
```

已经安装过且 `pyproject.toml` 未变化时可以跳过。

## 4. 确认记忆服务凭据

当前本地 `config.toml` 已分别为 Embedding 和离线 Extractor 直接配置 `api_key = "EMPTY"`，因此不需要再设置环境变量。本地服务不校验认证，`EMPTY` 只是满足客户端非空凭据合同的占位值。

如果以后改用需要真实密钥的远程服务，建议清空 `api_key`，改填 `api_key_env` 并从进程环境提供秘密；`api_key` 和 `api_key_env` 不能同时非空。

## 5. 启动 Memoli-agent

在新的 PowerShell 终端运行：

```powershell
cd D:\project\Memoli-agent
python -m memoli_agent.cli chat `
  --config config.toml `
  --workspace workspace `
  --session local
```

也可以使用安装后的快捷命令：

```powershell
memoli chat --config config.toml --workspace workspace --session local
```

重启后会继续恢复 `cli:local` 的 conversation epoch 和历史，但每个新 turn 会核对
当前工具、Skill 与 system prompt 的 capability revision。配置中启用
`memory_manage_enabled = true` 后，下一 turn 会自动获得该工具，无需执行 `/clear`；
`/clear` 仅用于明确开始新的对话 epoch。可用 `/context` 查看当前 revision 和工具
schema hash。

若系统提示找不到 `memoli`，使用前一种启动方式。

## 6. 验证记忆功能

进入 CLI 后执行：

```text
/status
/tools
```

预期状态包括：

```text
memory: ON
embedding: ON
consolidation: ON
```

工具列表中应包含：

```text
memory_recall
memory_manage
start_long_term_update
```

测试显式在线记忆：

```text
请记住：我偏好使用 Python 编写后端程序。
```

然后询问：

```text
我偏好使用什么语言编写后端程序？
```

离线自动整理按当前配置每累计 20 个普通对话回合触发扫描，不保证每条普通消息都会成为长期记忆。候选记忆可用以下命令检查和审核：

```text
/memory candidates
/memory show <candidate-id>
/memory approve <candidate-id> <revision> confirm
/memory reject <candidate-id> <revision> confirm
```

## 7. 停止服务

在 Memoli CLI 中输入：

```text
/exit
```

Embedding 和对话模型服务分别在其终端按 `Ctrl+C` 停止。

## 当前记忆配置摘要

当前 `config.toml` 已开启：

- SQLite 长期记忆与自动召回
- FTS、Pattern、semantic、metadata 混合检索
- Qwen3 Embedding 语义索引
- 在线 `memory_manage` 显式记忆写入
- 离线对话自动扫描与 Qwen Extractor
- 记忆治理 SubAgent 与 Policy Gate
- Card Builder 和 Episode 投影
- Working Memory、上下文持久化和脱敏运行轨迹
