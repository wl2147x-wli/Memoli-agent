import json
import os
import time
import threading

from common.log import logger
from agent.protocol.models import LLMRequest, LLMModel
from agent.protocol.agent_stream import AgentStreamExecutor
from agent.protocol.result import AgentAction, AgentActionType, ToolResult, AgentResult
from agent.tools.base_tool import BaseTool, ToolStage, is_tool_available


class Agent:
    def __init__(self, system_prompt: str, description: str = "AI Agent", model: LLMModel = None,
                 tools=None, output_mode="print", max_steps=100, max_context_tokens=None, 
                 context_reserve_tokens=None, memory_manager=None, name: str = None,
                 workspace_dir: str = None, skill_manager=None, enable_skills: bool = True,
                 runtime_info: dict = None, skip_context_files: bool = False):
        """
        用系统提示、模型与描述初始化 Agent。

        :param system_prompt: 代理的系统提示词。
        :param description: 对该代理的描述。
        :param model: 代理使用的 LLMModel 实例。
        :param tools: 可选，供代理使用的工具列表。
        :param output_mode: 控制执行进度的展示方式：
                           "print" 为控制台输出，"logger" 为写日志。
        :param max_steps: 代理最多可执行的工具调用步数（默认 100）。
        :param max_context_tokens: 上下文中保留的最大 token 数
                           （默认 None，按模型自动计算）。
        :param context_reserve_tokens: 为新请求预留的 token 数
                           （默认 None，自动计算）。
        :param memory_manager: 可选的 MemoryManager 实例，用于记忆操作。
        :param name: [已废弃] 代理名称（单代理体系中已不再使用）。
        :param workspace_dir: 可选的工作区目录，用于加载该工作区专属的技能。
        :param skill_manager: 可选的 SkillManager 实例
                           （为 None 且 enable_skills=True 时会自动创建）。
        :param enable_skills: 是否启用技能支持（默认 True）。
        :param runtime_info: 可选的运行时信息字典
                           （含 _get_current_time 可调用项，用于动态时间）。
        :param skip_context_files: 构建系统提示时跳过 AGENT.md / USER.md /
                           RULE.md。子代理会置位此参数：它们向派生自己的
                           代理汇报、而不是向用户负责，人设是父代理的职责；
                           若继承这些文件，等于把上下文浪费在一段子代理
                           根本看不到的对话的指令上。
        """
        self.name = name or "Agent"
        self.system_prompt = system_prompt
        self.model: LLMModel = model  # LLM模型的实例
        self.description = description
        self.tools: list = []
        self.max_steps = max_steps  # 最大工具调用步骤，默认 100
        self.max_context_tokens = max_context_tokens  # 上下文的最大 token 数
        self.context_reserve_tokens = context_reserve_tokens  # 为新请求预留的 token 数
        self.captured_actions = []  # 初始化捕获的动作列表
        self.output_mode = output_mode
        self.last_usage = None  # 存储最后的 API 响应使用信息
        self.messages = []  # 流模式的统一消息历史记录
        self.messages_lock = threading.Lock()  # 线程安全消息操作的锁
        self.memory_manager = memory_manager  # 用于自动内存刷新的内存管理器
        self.workspace_dir = workspace_dir  # 工作区目录（状态根目录，例如 ~/.cow）
        # 可选的按会话项目目录：覆盖工作目录（bash 的 cwd、相对文件路径），
        # 而记忆/技能仍锚定在 workspace_dir。None 表示“使用 workspace_dir”。
        self.project_dir = None
        # 本会话可选的权限模式（参见 agent.permission）。None 表示
        # “跟随全局设置”，在检查时再行解析，
        # 这样对全局默认值的改动也能覆盖从未自选过模式的会话。
        self.permission_mode = None
        self.enable_skills = enable_skills  # 技能启用标志
        self.runtime_info = runtime_info  # 动态时间更新的运行时信息
        self.skip_context_files = skip_context_files
        # 在完整系统提示重建完成后，可追加的可选补充说明。
        # 由自我进化审查代理使用，用来在完整上下文
        # （工具、工作空间、用户偏好、时间）之上附加其任务简介，
        # 这样它既遵循用户的偏好，又清楚自己的进化任务。
        self.extra_system_suffix = None
        
        # 初始化技能管理器
        self.skill_manager = None
        if enable_skills:
            if skill_manager:
                self.skill_manager = skill_manager
            else:
                # 自动创建技能管理器
                try:
                    from agent.skills import build_skill_manager
                    self.skill_manager = build_skill_manager(workspace_dir=workspace_dir)
                    logger.debug(f"Initialized SkillManager with {len(self.skill_manager.skills)} skills")
                except Exception as e:
                    logger.warning(f"Failed to initialize SkillManager: {e}")
        
        if tools:
            for tool in tools:
                self.add_tool(tool)

    def add_tool(self, tool: BaseTool):
        """
        向代理添加一个工具。

        :param tool: 要添加的工具（工具实例）。
        """
        # 如果tool已经是实例，则直接使用它
        tool.model = self.model
        self.tools.append(tool)

    # 这些工具的 cwd 定义了工作目录。记忆等其它工具
    # 刻意保留各自的路径，不会在这里被重新定位。
    _CWD_TOOLS = frozenset(
        {"read", "write", "edit", "bash", "search_files", "ls", "web_fetch", "send", "browser"}
    )

    def effective_cwd(self) -> str:
        """当前生效的工作目录：有项目覆盖时用项目目录，否则用工作区目录。"""
        return self.project_dir or self.workspace_dir or os.getcwd()

    def apply_project_dir(self, project_dir):
        """把工作目录指向 ``project_dir``（传 None 则重置回工作区）。

        重新定向文件/终端类工具的 cwd，让 bash、read、write 等在项目内
        工作。记忆、技能与 MCP 仍指向代理的工作区——它们各自解析
        绝对路径，不依赖这里的 cwd。系统提示每轮都会经
        ``get_full_system_prompt`` 重建并在其中读取 ``effective_cwd``，
        因此这里无需额外刷新提示。
        """
        # 规范化：空或与工作空间相等的值意味着“无项目”。
        if project_dir:
            project_dir = os.path.realpath(os.path.expanduser(project_dir))
            if self.workspace_dir and project_dir == os.path.realpath(
                os.path.expanduser(self.workspace_dir)
            ):
                project_dir = None
        else:
            project_dir = None

        self.project_dir = project_dir
        cwd = self.effective_cwd()
        for tool in self.tools:
            name = getattr(tool, "name", None)
            if not (name in self._CWD_TOOLS or hasattr(tool, "cwd")):
                continue
            try:
                # 若工具提供了 set_cwd 则优先调用（bash 会据此重新渲染其
                # 描述）；否则直接改写 cwd 属性即可。
                setter = getattr(tool, "set_cwd", None)
                if callable(setter):
                    setter(cwd)
                else:
                    tool.cwd = cwd
                if isinstance(getattr(tool, "config", None), dict):
                    tool.config["cwd"] = cwd
            except Exception:
                pass
        return self.project_dir

    def effective_permission_mode(self) -> str:
        """当前生效的权限模式：本会话自选的，否则用全局默认。"""
        from agent.permission import global_mode, normalize_mode

        if self.permission_mode:
            return normalize_mode(self.permission_mode, global_mode())
        return global_mode()

    def apply_permission_mode(self, mode):
        """设置（传 None 则清除）本会话的权限模式。

        从下一次工具调用起生效：执行器按每次调用逐一解析模式，
        因此对话中途切换无需重建代理。系统提示每轮重建时
        会自动带上新模式。
        """
        from agent.permission import normalize_mode

        self.permission_mode = normalize_mode(mode) if mode else None
        return self.permission_mode

    def write_roots(self) -> list:
        """在 workspace-write（工作区可写）模式下保持可写的目录列表。

        工作目录是用户工作成果的归属地；而代理自身的状态根目录无论如何
        都必须保持可写，否则按设计存放在那里的记忆、技能与知识
        在项目模式下就会失效。
        """
        roots = [self.effective_cwd()]
        if self.workspace_dir:
            roots.append(self.workspace_dir)
        return roots

    def get_skills_prompt(self, skill_filter=None) -> str:
        """
        获取要附加到系统提示之后的技能提示。

        :param skill_filter: 可选，仅包含指定名称技能的过滤列表。
        :return: 格式化后的技能提示；构建失败或未启用技能时为空字符串。
        """
        if not self.skill_manager:
            return ""
        
        try:
            return self.skill_manager.build_skills_prompt(skill_filter=skill_filter)
        except Exception as e:
            logger.warning(f"Failed to build skills prompt: {e}")
            return ""
    
    def get_full_system_prompt(self, skill_filter=None) -> str:
        """
        每次都从零构建完整的系统提示。

        重新从磁盘读取 AGENT.md / USER.md / RULE.md，并刷新技能、
        工具与运行时信息，让任何改动立即生效。
        构建失败时回退到缓存的 self.system_prompt。
        """
        try:
            from agent.prompt import load_context_files, PromptBuilder

            if self.skill_manager:
                self.skill_manager.refresh_skills()

            context_files = None
            if self.workspace_dir and not self.skip_context_files:
                context_files = load_context_files(self.workspace_dir)

            try:
                from common import i18n
                lang = i18n.get_language()
            except Exception:
                lang = "zh"
            builder = PromptBuilder(workspace_dir=self.workspace_dir or "", language=lang)
            full = builder.build(
                # 传给模型的必须是本轮可用工具的同款列表：若在提示中
                # 描述了模型里并不存在的工具，就会诱导它调用
                # 那些并不存在的东西。
                tools=[tool for tool in self.tools if is_tool_available(tool)],
                context_files=context_files,
                skill_manager=self.skill_manager,
                memory_manager=self.memory_manager,
                runtime_info=self.runtime_info,
                project_dir=self.project_dir,
                permission_mode=self.effective_permission_mode(),
            )
            if self.extra_system_suffix:
                full = f"{full}\n\n{self.extra_system_suffix}"
            return full
        except Exception as e:
            logger.warning(f"Failed to rebuild system prompt, using cached version: {e}")
            if self.extra_system_suffix:
                return f"{self.system_prompt}\n\n{self.extra_system_suffix}"
            return self.system_prompt

    def refresh_skills(self):
        """重新加载已装载的技能。"""
        if self.skill_manager:
            self.skill_manager.refresh_skills()
            logger.info(f"Refreshed skills: {len(self.skill_manager.skills)} skills loaded")
    
    def list_skills(self):
        """
        列出所有已装载的技能。

        :return: 技能条目列表；未启用技能时为空列表。
        """
        if not self.skill_manager:
            return []
        return self.skill_manager.list_skills()

    def _get_model_context_window(self) -> int:
        """
        获取模型的*总*上下文窗口大小（输入 + 输出，单位 token）。
        按模型名称自动识别。

        这是提供商对“提示 token + 补全预算”强制执行的硬性上限。
        修剪时必须为补全留出空间（见 `_get_output_reserve_tokens`），
        否则占满整个窗口的提示再加上服务端默认的 `max_tokens`
        就会溢出，请求直接报 400。

        :return: 上下文窗口大小（token 数）
        """
        if self.model and hasattr(self.model, 'model'):
            model_name = self.model.model.lower()

            # Claude 模型：200K 上下文窗口
            if 'claude' in model_name:
                return 200000

            # GPT-4 系列
            elif 'gpt-4' in model_name:
                if 'turbo' in model_name or '128k' in model_name:
                    return 128000
                elif '32k' in model_name:
                    return 32000
                else:
                    return 8000

            # GPT-3.5
            elif 'gpt-3.5' in model_name:
                if '16k' in model_name:
                    return 16000
                else:
                    return 4000

            # DeepSeek：V4 系列提供 1M 窗口；旧版 chat/reasoner 为 64K。
            elif 'deepseek' in model_name:
                if 'v4' in model_name:
                    return 1000000
                return 64000

            # Gemini 模型
            elif 'gemini' in model_name:
                if '2.0' in model_name or 'exp' in model_name:
                    return 2000000  # Gemini 2.0：2M token
                else:
                    return 1000000  # Gemini 1.5：1M token

            # GLM：5.3 Flash 提供 1M 窗口；较旧的 glm-5.x 为 200K。
            elif 'glm' in model_name:
                if model_name.startswith('glm-5.3-flash'):
                    return 1000000
                return 200000

            # Qwen：3.8 Flash 提供 1M 窗口；其余保守取 128K。
            elif 'qwen' in model_name:
                if model_name.startswith('qwen3.8-flash'):
                    return 1000000
                return 128000

        # 默认保守值
        return 128000

    def _get_output_reserve_tokens(self) -> int:
        """
        从输入预算中为模型补全预留的 token 数。

        模型的上下文窗口由提示与回复共用。提供商（以及 LinkAI 之类的
        代理网关）会给 agent 模式模型附带很大的默认 `max_tokens`——
        例如 DeepSeek V4 最多可以要求 384K 输出 token。若放任修剪后的
        提示占满整个窗口，提示 + 这份补全预算就会超出窗口，请求被以
        “maximum context length ... you requested N tokens”拒绝，随后
        陷入循环。

        预留量随窗口大小缩放：小模型保留适度缓冲，大窗口模型
        （V4 的 1M）为其超大的补全默认值预留足够空间，
        同时绝不超过窗口的约 40%。
        """
        context_window = self._get_model_context_window()
        # 约为上下文窗口的 40%，并夹在常见的下限/上限之间：400K 上限
        # 足以覆盖大窗口 agent 模型默认要求高达 384K 的输出。
        reserve = int(context_window * 0.4)
        return max(8000, min(400000, reserve))

    def _get_context_reserve_tokens(self) -> int:
        """
        获取为新请求预留的 token 数量。
        通过保留一块缓冲区来防止上下文溢出。

        :return: 需要预留的 token 数量
        """
        if self.context_reserve_tokens is not None:
            return self.context_reserve_tokens

        # 保留约 10% 的上下文窗口，最小 10K，最大 200K
        context_window = self._get_model_context_window()
        reserve = int(context_window * 0.1)
        return max(10000, min(200000, reserve))

    def _estimate_message_tokens(self, message: dict) -> int:
        """
        估算一条消息的 token 数量。

        中文为主的内容按 字符数/3 估算，ASCII 为主的内容按 字符数/4，
        并为 tool_use / tool_result 结构叠加每块的固定开销。

        :param message: 含 'role' 与 'content' 的消息字典
        :return: 估算的 token 数量
        """
        content = message.get('content', '')
        if isinstance(content, str):
            return max(1, self._estimate_text_tokens(content))
        elif isinstance(content, list):
            total_tokens = 0
            for part in content:
                if not isinstance(part, dict):
                    continue
                block_type = part.get('type', '')
                if block_type == 'text':
                    total_tokens += self._estimate_text_tokens(part.get('text', ''))
                elif block_type == 'image':
                    total_tokens += 1200
                elif block_type == 'tool_use':
                    # tool_use 具有 id + 名称 + 输入（JSON 编码）
                    total_tokens += 50  # 结构开销
                    input_data = part.get('input', {})
                    if isinstance(input_data, dict):
                        import json
                        input_str = json.dumps(input_data, ensure_ascii=False)
                        total_tokens += self._estimate_text_tokens(input_str)
                elif block_type == 'tool_result':
                    # tool_result 具有 tool_use_id + 内容
                    total_tokens += 30  # 结构开销
                    result_content = part.get('content', '')
                    if isinstance(result_content, str):
                        total_tokens += self._estimate_text_tokens(result_content)
                else:
                    # 未知区块类型，保守估计
                    total_tokens += 10
            return max(1, total_tokens)
        return 1

    @staticmethod
    def _estimate_text_tokens(text: str) -> int:
        """
        估算一段文本的 token 数量。

        中文/中日韩字符通常每个约 1.5 token，
        ASCII 每个字符约 0.25 token（约 4 字符合 1 token）。
        这里按字符构成比例取加权平均。

        :param text: 输入文本
        :return: 估算的 token 数量
        """
        if not text:
            return 0
        # 计算非 ASCII 字符（CJK、表情符号等）
        non_ascii = sum(1 for c in text if ord(c) > 127)
        ascii_count = len(text) - non_ascii
        # CJK 字符：每个约 1.5 token；ASCII：每个字符约 0.25 token
        return int(non_ascii * 1.5 + ascii_count * 0.25) + 1

    def _find_tool(self, tool_name: str):
        """按名称查找并返回对应的工具"""
        for tool in self.tools:
            if tool.name == tool_name:
                # 只能主动调用预处理阶段工具
                if tool.stage == ToolStage.PRE_PROCESS:
                    tool.model = self.model
                    tool.context = self  # 设置工具上下文
                    return tool
                else:
                    # 如果是后处理工具，则返回None，防止直接调用
                    logger.warning(f"Tool {tool_name} is a post-process tool and cannot be called directly.")
                    return None
        return None

    # 基于模式的输出函数
    def output(self, message="", end="\n"):
        if self.output_mode == "print":
            print(message, end=end)
        elif message:
            logger.info(message)

    def _execute_post_process_tools(self):
        """执行所有后处理阶段的工具"""
        # 获取所有后期处理阶段工具
        post_process_tools = [tool for tool in self.tools if tool.stage == ToolStage.POST_PROCESS]

        # 执行每个工具
        for tool in post_process_tools:
            # 设置工具上下文
            tool.context = self

            # 记录执行计时的开始时间
            start_time = time.time()

            # 执行工具（使用空参数，工具将从上下文中提取所需的信息）
            result = tool.execute({})

            # 计算执行时间
            execution_time = time.time() - start_time

            # 记录本次工具调用，便于后续跟踪
            self.capture_tool_use(
                tool_name=tool.name,
                input_params={},  # 后处理工具通常不接受参数
                output=result.result,
                status=result.status,
                error_message=str(result.result) if result.status == "error" else None,
                execution_time=execution_time
            )

            # 记录结果
            if result.status == "success":
                # 按指定格式输出工具执行结果
                self.output(f"\n🛠️ {tool.name}: {json.dumps(result.result)}")
            else:
                # print 模式下打印失败提示
                self.output(f"\n🛠️ {tool.name}: {json.dumps({'status': 'error', 'message': str(result.result)})}")

    def capture_tool_use(self, tool_name, input_params, output, status, thought=None, error_message=None,
                         execution_time=0.0):
        """
        记录一次工具调用动作。

        :param thought: 思考内容
        :param tool_name: 所用工具的名称
        :param input_params: 传给工具的参数
        :param output: 工具的输出
        :param status: 工具执行状态
        :param error_message: 工具执行失败时的错误信息
        :param execution_time: 工具执行耗时
        """
        tool_result = ToolResult(
            tool_name=tool_name,
            input_params=input_params,
            output=output,
            status=status,
            error_message=error_message,
            execution_time=execution_time
        )

        action = AgentAction(
            agent_id=self.id if hasattr(self, 'id') else str(id(self)),
            agent_name=self.name,
            action_type=AgentActionType.TOOL_USE,
            tool_result=tool_result,
            thought=thought
        )

        self.captured_actions.append(action)

        return action

    def run_stream(self, user_message: str, on_event=None, clear_history: bool = False,
                   skill_filter=None, cancel_event=None, steer_inbox=None,
                   allow_empty_response: bool = False) -> str:
        """
        以流式方式执行单个代理任务（基于工具调用）。

        本方法支持：
        - 流式输出
        - 基于工具调用的多轮推理
        - 事件回调
        - 跨调用的持久化对话历史
        - 通过 ``cancel_event`` 由用户发起取消
        - 通过 ``steer_inbox`` 对进行中的轮次做显式引导

        Args:
            user_message: 用户消息
            on_event: 事件回调函数 callback(event: dict)，
                     event = {"type": str, "timestamp": float, "data": dict}
            clear_history: 为 True 时在本次调用前清空对话历史（默认 False）。
            skill_filter: 可选，本次运行仅包含指定名称技能的过滤列表。
            cancel_event: 可选的 threading.Event，在代理的各个检查点轮询。
                置位后，循环会在下一个安全点退出，注入一条
                “[Interrupted by user]”助手备注并返回已有部分响应。
                ``messages`` 仍保持有效状态（tool_use/tool_result 配对完整）。
            steer_inbox: 可选的 SteerInbox，在安全检查点取用。新的指令
                直接引导本次运行，而不进入常规消息队列。
            allow_empty_response: 为 True 时空回答按原样返回，而不是
                换成兜底文案。适用于无人等待结果的运行（定时任务），
                此时“什么都不发”本身就是合法结果。

        Returns:
            最终响应文本

        Example:
            # 带记忆的多轮对话
            response1 = agent.run_stream("My name is Alice")
            response2 = agent.run_stream("What's my name?")  # 会记得 Alice

            # 不带记忆的单轮对话
            response = agent.run_stream("Hello", clear_history=True)
        """
        # 如果需要清除历史记录
        if clear_history:
            with self.messages_lock:
                self.messages = []

        # 获取要使用的模型
        if not self.model:
            raise ValueError("No model available for agent")

        # 获得完整的系统提示与技能
        full_system_prompt = self.get_full_system_prompt(skill_filter=skill_filter)

        # 为此执行创建消息副本以避免并发修改
        # 记录原始长度以跟踪哪些消息是新的
        with self.messages_lock:
            messages_copy = self.messages.copy()
            original_length = len(self.messages)

        # 从配置中获取 max_context_turns
        from config import conf
        max_context_turns = conf().get("agent_max_context_turns", 20)
        
        # 使用复制的消息历史记录创建流执行器
        executor = AgentStreamExecutor(
            agent=self,
            model=self.model,
            system_prompt=full_system_prompt,
            tools=self.tools,
            max_turns=self.max_steps,
            on_event=on_event,
            messages=messages_copy,  # 传递复制的消息历史记录
            max_context_turns=max_context_turns,
            cancel_event=cancel_event,
            steer_inbox=steer_inbox,
            allow_empty_response=allow_empty_response,
        )

        # 执行
        try:
            response = executor.run_stream(user_message)
        except Exception:
            # 如果执行器清除了其消息（上下文溢出/消息格式错误），
            # 将其同步回代理自己的消息列表，以便下一个请求
            # 重新开始，而不是永远遇到相同的溢出。
            if len(executor.messages) == 0:
                with self.messages_lock:
                    self.messages.clear()
                    logger.info("[Agent] Cleared Agent message history after executor recovery")
            raise

        # 将执行器的消息同步回代理（线程安全）。
        # 如果执行器修剪了上下文，其消息列表会比
        # original_length 短，因此必须整体替换而不是追加。
        with self.messages_lock:
            # 跟踪本次运行新增的消息（用户查询 + 所有助手/工具消息）。
            # 当上下文被修剪后，executor.messages 会比 original_length 短，
            # 若仍按 original_length 切片会得到空列表，助理回复也就永远
            # 不会被保留。因此改为从尾部向前扫描，找到本次运行的用户查询
            # （它始终是最后一轮的第一条消息）。
            trimmed = len(executor.messages) < original_length
            if trimmed:
                new_start = original_length  # 兜底值
                for idx in range(len(executor.messages) - 1, -1, -1):
                    msg = executor.messages[idx]
                    if msg.get("role") != "user":
                        continue
                    content = msg.get("content", [])
                    is_user_query = False
                    if isinstance(content, list):
                        has_text = any(
                            isinstance(b, dict) and b.get("type") == "text"
                            for b in content
                        )
                        has_tool_result = any(
                            isinstance(b, dict) and b.get("type") == "tool_result"
                            for b in content
                        )
                        is_user_query = has_text and not has_tool_result
                    elif isinstance(content, str):
                        is_user_query = True
                    if is_user_query:
                        new_start = idx
                        break
                self._last_run_new_messages = list(executor.messages[new_start:])
            else:
                self._last_run_new_messages = list(executor.messages[original_length:])
            self.messages = list(executor.messages)
        
        # 保存执行器引用，供 agent_bridge 访问 files_to_send
        self.stream_executor = executor

        # 执行所有后处理工具
        self._execute_post_process_tools()

        return response

    def clear_history(self):
        """清空对话历史与已捕获的动作记录"""
        self.messages = []
        self.captured_actions = []

    def compact_context(self, keep_recent_turns: int = 2) -> dict:
        """立即手动压缩对话历史。

        复用与 AgentStreamExecutor 自动上下文修剪相同的按轮切分与
        摘要注入逻辑（经由 message_utils 中的共享辅助函数），唯一
        区别是这里同步执行摘要、且不管 token 占用多少都按需运行——
        因此 /compact 命令能立即、一致地释放上下文。

        :param keep_recent_turns: 原样保留最近多少轮对话。
        :return: 字典，键为 ok、reason、compacted_turns、before、after。
        """
        from agent.protocol.message_utils import (
            identify_complete_turns,
            build_compaction_summary_text,
            find_first_user_text_block,
            _extract_text_from_content,
        )

        with self.messages_lock:
            before = len(self.messages)
            turns = identify_complete_turns(self.messages)

            if len(turns) <= keep_recent_turns:
                return {
                    "ok": False,
                    "reason": "nothing_to_compact",
                    "compacted_turns": 0,
                    "before": before,
                    "after": before,
                }

            discarded_turns = turns[:-keep_recent_turns]
            kept_turns = turns[-keep_recent_turns:]
            discarded_messages = []
            for turn in discarded_turns:
                discarded_messages.extend(turn["messages"])

        # 同步地对被丢弃的回合做摘要，这样在本方法返回前，
        # 待注入的摘要文本就已经就绪。同一份摘要既用于上下文注入，
        # 也用于日常记忆持久化——一次 LLM 调用同时满足两者
        # （与自动修剪所用的 context_summary_callback 路径一致，只是同步执行）。
        # 当没有可用的 LLM 时，回退为纯文本摘要。
        summary = ""
        llm_summary = False
        flush_mgr = None
        if self.memory_manager:
            flush_mgr = getattr(self.memory_manager, "flush_manager", None)
        if flush_mgr:
            try:
                raw = flush_mgr._summarize_messages(discarded_messages, max_messages=0) or ""
                summary = flush_mgr._clean_summary_output(raw)
                llm_summary = bool(summary.strip())
            except Exception as e:
                logger.warning(f"[Agent] compact summarize failed: {e}")

        if not summary.strip():
            fragments = []
            for msg in discarded_messages:
                text = _extract_text_from_content(msg.get("content", ""))
                if text:
                    fragments.append(f"{msg.get('role', '?')}: {text[:200]}")
            summary = "\n".join(fragments[-20:])

        # 把同一份 LLM 摘要写入日常记忆（无需再发起第二次 LLM 调用）。
        # 若我们只有纯文本回退内容就跳过——它不值得被
        # 当作长期记忆记下来。
        if flush_mgr and llm_summary:
            try:
                user_id = getattr(self, "_current_user_id", None)
                flush_mgr.write_daily_summary(summary, user_id=user_id, reason="trim")
            except Exception as e:
                logger.debug(f"[Agent] compact write_daily_summary skipped: {e}")

        # 按轮重建消息，并把摘要注入第一个保留下来的用户文本块
        # （与自动修剪做法相同），以免出现两条相邻的用户消息——
        # 那会打破某些提供商对 user/assistant 严格交替的要求。
        turn_count = len(discarded_turns)
        with self.messages_lock:
            new_messages = []
            for turn in kept_turns:
                new_messages.extend(turn["messages"])

            target_block = find_first_user_text_block(kept_turns)
            if target_block is not None:
                target_block["text"] = build_compaction_summary_text(
                    summary, turn_count, target_block.get("text", "")
                )
            else:
                # 后备：没有可注入目标，在前面添加一个独立的注释。
                new_messages.insert(0, {
                    "role": "user",
                    "content": [{
                        "type": "text",
                        "text": build_compaction_summary_text(summary, turn_count, ""),
                    }],
                })

            self.messages = new_messages
            after = len(self.messages)

        logger.info(
            f"[Agent] Manual compact: {turn_count} turns summarized, "
            f"{before} -> {after} messages"
        )
        return {
            "ok": True,
            "reason": "compacted",
            "compacted_turns": turn_count,
            "before": before,
            "after": after,
        }
