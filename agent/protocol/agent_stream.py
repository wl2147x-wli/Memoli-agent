"""
Agent Stream Execution Module - Multi-turn reasoning based on tool-call

Provides streaming output, event system, and complete tool-call loop
"""
import contextvars
import copy
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional, Callable, Tuple

from agent.protocol.cancel import AgentCancelledError
from agent.protocol.models import LLMRequest, LLMModel
from agent.protocol.message_utils import (
    sanitize_claude_messages,
    compress_turn_to_text_only,
    identify_complete_turns,
    build_compaction_summary_text,
    find_first_user_text_block,
)
from agent.tools.base_tool import BaseTool, ToolResult, is_tool_available, renders_own_cards
from common.log import logger
from common.i18n import t as _t

# 可选：修复非严格厂商输出的格式错误的 JSON 参数（例如长内容里的未转义引号）。
try:
    from json_repair import repair_json as _repair_json
    _HAS_JSON_REPAIR = True
except ImportError:
    _HAS_JSON_REPAIR = False


# 在对话历史中为模型的“推理/思考”内容保留的最大字符数。
# 完整推理仍会实时传到 UI（受其自身 SSE/渲染上限的限制）；
# 该界限只控制存进数据库、供历史回放的部分。
# 过长的推理对后续上下文没有价值（LLM 反正永远看不到思考块），
# 只会撑大数据库。
# 与前端 REASONING_RENDER_CAP、SSE 的 MAX_REASONING_STREAM_CHARS
# 保持一致，让存储/流式传输/显示三者统一。
MAX_STORED_REASONING_CHARS = 4 * 1024  # 4KB

# 当推理被截断时，在头部和尾部之间插入标记。
_REASONING_TRUNCATE_MARKER = "\n\n... [reasoning truncated, {omitted} chars omitted] ...\n\n"

# --------------------------------------------------------------------------
# 致命错误分类。
#
# 下面两个分支都会丢弃整个内存中的上下文，一旦误判，
# 用户正在进行的对话就会付出代价。因此每个标记都必须
# 足够具体，不能出现在无关的失败中：像 “没有”、“每个”、
# “必须有”、“未找到” 这类通用词匹配范围太广；裸的 “400”
# 子串也会误伤 4000 之类的计数。
# --------------------------------------------------------------------------

# 使用词边界匹配，因此 “4000”/“40096” 不会被误判为 HTTP 400。
_RE_HTTP_400 = re.compile(r"\b400\b")

_CONTEXT_OVERFLOW_MARKERS = (
    "context length exceeded", "maximum context length", "prompt is too long",
    "context overflow", "context window", "exceeds model context",
    "request_too_large", "request exceeds the maximum size",
    "too many tokens", "input is too long", "tokens exceed",
)

# 仅用于识别 tool_use/tool_result 配对出错之类的结构性报错。
_MESSAGE_FORMAT_MARKERS = (
    "tool_use", "tool_result", "tool_call_id", "tool_calls",
    "tool result", "tool id",
    "must be a response to a preceeding message",
)


def _is_context_overflow(error_str_lower: str) -> bool:
    if "[context_overflow]" in error_str_lower:
        return True
    return any(m in error_str_lower for m in _CONTEXT_OVERFLOW_MARKERS)


def _is_message_format_error(error_str_lower: str) -> bool:
    """Detect broken tool_use/tool_result pairing rejected by the provider.

    Requires both a structural marker and a 400-class signal, so an unrelated
    400 (bad model name, missing parameter, oversized upload) never qualifies.
    """
    if not any(m in error_str_lower for m in _MESSAGE_FORMAT_MARKERS):
        return False
    return bool(
        _RE_HTTP_400.search(error_str_lower)
        or "invalid_request" in error_str_lower
        or "invalidparameter" in error_str_lower
    )


def _truncate_reasoning_for_storage(text: str) -> str:
    """Trim long reasoning to head + tail with an omission marker.

    Keeps the first and last halves of MAX_STORED_REASONING_CHARS so both the
    initial chain-of-thought and the final conclusions are preserved for UI
    replay, without storing the entire (often very large) middle.
    """
    if not text:
        return text
    if len(text) <= MAX_STORED_REASONING_CHARS:
        return text
    half = MAX_STORED_REASONING_CHARS // 2
    head = text[:half]
    tail = text[-half:]
    omitted = len(text) - len(head) - len(tail)
    return head + _REASONING_TRUNCATE_MARKER.format(omitted=omitted) + tail


# 429 递增退避的上限。基础曲线为 30+retry_count*15，
# 若无上限，到第 8 次重试就会超过 Web 通道 600 秒的 SSE 空闲超时；
# 把单次等待封顶在 60 秒，可让累计等待时间保持可控。
RATE_LIMIT_MAX_WAIT = 60  # 秒


# 仅附加给文件写入类工具：对它们说“少发一点”时，需要解释具体该怎么做。
_SPLIT_WRITE_ADVICE = (
    "To change an existing file, use edit rather than rewriting the whole file. "
    "To create a large file, write the first part, then append each remaining part "
    "with edit using an empty oldText (calling write again would overwrite what you "
    "just wrote)."
)


def _cut_off_message(cause: str, tool_name: Optional[str]) -> str:
    message = (
        f"Your tool call was cut off by {cause}, so it did not run and nothing was written. "
        "Repeating the same call will be cut off again - send less in one call instead."
    )
    if tool_name in ("write", "edit"):
        message += " " + _SPLIT_WRITE_ADVICE
    return message


def _parse_tool_args(args_str: str, finish_reason: Optional[str],
                     tool_name: Optional[str] = None) -> Tuple[dict, Optional[str]]:
    """Parse tool args JSON. Returns (args, error_msg); error_msg is None on success.

    On JSONDecodeError: detect truncation first (skip repair, surface max_tokens hint);
    otherwise try json-repair for escape issues; finally fall back to the raw decoder error.
    """
    truncated_by_limit = finish_reason in ("length", "max_tokens")
    if not args_str:
        # 对不需要参数的工具来说，没有参数是合法的，因此只有当
        # 明确的 finish_reason 表明截断时，才能在这里判定为问题。
        # 其余情况交由 _execute_tool 按工具必需的参数去校验调用。
        if truncated_by_limit:
            return {}, _cut_off_message("the output token limit", tool_name)
        return {}, None
    try:
        return json.loads(args_str), None
    except json.JSONDecodeError as e:
        if truncated_by_limit or not args_str.rstrip().endswith("}"):
            cause = "the output token limit" if truncated_by_limit else "arguments ending mid-JSON"
            return {}, _cut_off_message(cause, tool_name)
        if _HAS_JSON_REPAIR:
            try:
                repaired = _repair_json(args_str, return_objects=True)
                if isinstance(repaired, dict):
                    logger.warning(f"Tool args JSON repaired ({len(args_str)} chars)")
                    return repaired, None
            except Exception:
                pass
        return {}, f"Invalid JSON in tool arguments: {e.msg}"


class AgentStreamExecutor:
    """
    Agent Stream Executor
    
    Handles multi-turn reasoning loop based on tool-call:
    1. LLM generates response (may include tool calls)
    2. Execute tools
    3. Return results to LLM
    4. Repeat until no more tool calls
    """

    def __init__(
            self,
            agent,  # 代理实例
            model: LLMModel,
            system_prompt: str,
            tools: List[BaseTool],
            max_turns: int = 50,
            on_event: Optional[Callable] = None,
            messages: Optional[List[Dict]] = None,
            max_context_turns: int = 30,
            cancel_event=None,
            steer_inbox=None,
            allow_empty_response: bool = False,
    ):
        """
        Initialize stream executor
        
        Args:
            agent: Agent instance (for accessing context)
            model: LLM model
            system_prompt: System prompt
            tools: List of available tools
            max_turns: Maximum number of turns
            on_event: Event callback function
            messages: Optional existing message history (for persistent conversations)
            max_context_turns: Maximum number of conversation turns to keep in context
            cancel_event: Optional threading.Event used to signal user cancel.
                Checked at every safe point (turn boundary, before tool execution,
                during LLM streaming). When set, raises AgentCancelledError which
                run_stream catches to gracefully wind down.
            steer_inbox: Optional SteerInbox for explicit instructions sent to
                this active run. Drained only at message-safe checkpoints.
            allow_empty_response: When True, an empty final answer is a valid
                outcome and is returned as-is instead of being replaced with
                fallback text. Set for runs with no human waiting on a reply
                (scheduled tasks), where silence can be the intended result.
        """
        self.agent = agent
        self.model = model
        self.system_prompt = system_prompt
        # 将工具列表转换为字典
        self.tools = {tool.name: tool for tool in tools} if isinstance(tools, list) else tools
        self.max_turns = max_turns
        self.on_event = on_event
        self.max_context_turns = max_context_turns
        self.cancel_event = cancel_event
        self.steer_inbox = steer_inbox
        self.allow_empty_response = allow_empty_response

        # 消息历史记录 - 使用提供的消息或创建新列表
        self.messages = messages if messages is not None else []
        
        # 用于重试保护的工具故障跟踪
        self.tool_failure_history = []  # (tool_name, args_hash, success) 元组列表
        
        # 跟踪要发送的文件（由读取工具填充）
        self.files_to_send = []  # 文件元数据字典列表

        # 绝对路径已报告为工件，因此先写后编辑
        # 同一文件上的序列仅在 UI 中显示一张卡。
        self._emitted_artifacts = set()

    def _check_cancelled(self) -> None:
        """Raise AgentCancelledError if the user requested cancellation.

        Called at safe points (turn start, between tool calls, between LLM
        chunks). Cheap to call: just an Event.is_set() probe.
        """
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise AgentCancelledError("agent cancelled by user")

    def _drain_steering(self) -> List[str]:
        if self.steer_inbox is None:
            return []
        return self.steer_inbox.drain()

    def _explicit_response_prompt(self) -> str:
        """Prompt that asks a silent model for its final answer.

        When silence is a valid outcome the model has to be told so, or it
        writes filler text just to satisfy the request.
        """
        if self.allow_empty_response:
            return (
                "请说明刚才工具执行的结果。如果本次无需向用户发送任何内容"
                "（例如任务只要求在满足特定条件时才通知，而当前条件不满足），"
                "直接返回空即可，不要输出任何文字。"
            )
        return "请向用户说明刚才工具执行的结果或回答用户的问题。"

    def _empty_response_fallback(self) -> str:
        """Text to return when the model produced no answer at all.

        Stays empty for runs that allow silence, so a scheduled task whose
        notify condition wasn't met delivers nothing instead of an apology
        addressed to a user who never asked anything.
        """
        if self.allow_empty_response:
            logger.info("[Agent] Empty response kept as-is (silence allowed for this run)")
            return ""
        logger.info("Generated fallback response for empty LLM output")
        return _t(
            "抱歉，我暂时无法生成回复。请尝试换一种方式描述你的需求，或稍后再试。",
            "Sorry, I can't generate a reply right now. Please try rephrasing your request, or try again later.",
        )

    @staticmethod
    def _steering_text(updates: List[str]) -> str:
        if len(updates) == 1:
            body = updates[0]
        else:
            body = "\n".join(f"{idx}. {text}" for idx, text in enumerate(updates, 1))
        return (
            "[Steering update for the active task]\n"
            "Use this new instruction for the current task before continuing.\n\n"
            f"{body}"
        )

    def _append_steering(
        self,
        updates: List[str],
        pending_tool_calls: Optional[List[Dict]] = None,
        content_blocks: Optional[List[Dict]] = None,
    ) -> None:
        """Append guidance, closing any tool_use blocks that will be skipped."""
        if not updates:
            return
        blocks = content_blocks if content_blocks is not None else []
        for tool_call in pending_tool_calls or []:
            blocks.append({
                "type": "tool_result",
                "tool_use_id": tool_call["id"],
                "content": "Skipped because the user redirected the active task.",
                "is_error": True,
            })
        blocks.append({"type": "text", "text": self._steering_text(updates)})
        if content_blocks is None:
            self.messages.append({"role": "user", "content": blocks})
        self._emit_event("agent_steered", {"count": len(updates)})
        logger.info(f"[Agent] Applied {len(updates)} steering update(s)")

    def _close_or_apply_final_steering(self) -> bool:
        """Return True only when the run can finish without losing a steer."""
        updates = self._drain_steering()
        if updates:
            self._append_steering(updates)
            return False
        if self.steer_inbox is None:
            return True
        if self.steer_inbox.close_if_empty():
            return True
        updates = self._drain_steering()
        if updates:
            self._append_steering(updates)
        return False

    def _drain_and_close_steering(self) -> None:
        """Preserve any final guidance before the max-step summary call."""
        if self.steer_inbox is None:
            return
        while True:
            updates = self._drain_steering()
            if updates:
                self._append_steering(updates)
            if self.steer_inbox.close_if_empty():
                return

    def _handle_cancelled(self, partial_response: str) -> None:
        """Wind down ``self.messages`` after a user-initiated cancel.

        The messages list may be in any of these states when we get here:
          (a) Last message is an assistant message containing tool_use
              blocks but the matching tool_result has not been appended yet.
          (b) Last message is an assistant text-only reply (cancel happened
              right before the next turn started).
          (c) Last message is a user tool_result message and we cancelled
              between turns.

        For (a) we MUST synthesise tool_result blocks, otherwise the next
        request will fail Claude/OpenAI's strict pairing validation. For
        (b)/(c) the state is already valid and we just append a small
        cancellation note so the user/LLM both see the boundary clearly.
        """
        try:
            # 第 1 步：收尾末尾助手消息里所有孤立的 tool_use，
            # 通过注入与之匹配的 tool_result 块来补全。
            if self.messages and isinstance(self.messages[-1], dict) \
                    and self.messages[-1].get("role") == "assistant":
                last = self.messages[-1]
                content = last.get("content")
                if isinstance(content, list):
                    pending_tool_use_ids = [
                        block.get("id")
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "tool_use"
                    ]
                    pending_tool_use_ids = [tid for tid in pending_tool_use_ids if tid]
                    if pending_tool_use_ids:
                        tool_result_blocks = [
                            {
                                "type": "tool_result",
                                "tool_use_id": tid,
                                "content": "Cancelled by user before this tool finished.",
                                "is_error": True,
                            }
                            for tid in pending_tool_use_ids
                        ]
                        self.messages.append({
                            "role": "user",
                            "content": tool_result_blocks,
                        })
                        logger.info(
                            f"[Agent] Injected {len(tool_result_blocks)} cancellation "
                            f"tool_result blocks to keep message history valid"
                        )

            # 第 2 步：追加一个固定的“已中断”标记，让 LLM 在
            # 下一轮能看到清晰的停止边界。
            self.messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": self._cancellation_marker()}],
            })
        except Exception as e:
            logger.warning(f"[Agent] _handle_cancelled cleanup failed: {e}")

    @staticmethod
    def _cancellation_marker() -> str:
        """Stop-boundary note, listing background jobs a cancel does not kill."""
        marker = "_(Cancelled by user)_"
        try:
            from agent.tools.bash import background
            running = [job for job in background.list_jobs() if job["running"]]
        except Exception:
            return marker
        if not running:
            return marker
        lines = "\n".join(
            f"- {job['id']}: {job['command']} ({job['elapsed']}s elapsed)"
            for job in running
        )
        return (
            f"{marker}\nBackground commands are still running - cancelling does not "
            f"stop them. Use bash(bash_id=..., kill=true) to stop one.\n{lines}"
        )

    def _emit_event(self, event_type: str, data: dict = None):
        """Emit event"""
        if self.on_event:
            try:
                self.on_event({
                    "type": event_type,
                    "timestamp": time.time(),
                    "data": data or {}
                })
            except Exception as e:
                logger.error(f"Event callback error: {e}")

    # 成功执行的工具可能会生成面向用户的文件。
    _ARTIFACT_TOOLS = ("write", "edit")

    def _maybe_emit_artifact(self, tool_call: dict, result: dict) -> None:
        """Report a file written by `write`/`edit` so clients can preview it."""
        if not self.on_event:
            return
        if tool_call.get("name") not in self._ARTIFACT_TOOLS:
            return
        if result.get("status") != "success":
            return

        data = result.get("result")
        path = data.get("path") if isinstance(data, dict) else None
        if not path:
            path = (tool_call.get("arguments") or {}).get("path")
        if not path:
            return

        from agent.protocol.artifact import safe_build_artifact

        # 将工件检测锚定到会话的工作目录。项目模式下
        # 工作目录即项目目录，写入其中的文件会以卡片形式呈现；
        # 当没有项目打开时，则使用默认的 state_root。
        art_root = None
        try:
            eff = getattr(self.agent, "effective_cwd", None)
            if callable(eff):
                art_root = eff()
        except Exception:
            art_root = None
        artifact = safe_build_artifact(path, art_root)
        if not artifact:
            return
        if artifact["path"] in self._emitted_artifacts:
            return
        self._emitted_artifacts.add(artifact["path"])
        logger.info(f"🗂  Artifact: {artifact['rel_path']} ({artifact['kind']})")
        self._emit_event("artifact", artifact)

    def _is_thinking_enabled(self) -> bool:
        """Whether deep-thinking mode is on at the model layer.

        Mirrors the global toggle used by ``bridge.agent_bridge`` when deciding
        whether to send ``thinking={"type": "enabled"}`` to the model. Used for
        logging and reasoning-update event emission across all channels.
        """
        from config import conf
        return bool(conf().get("enable_thinking", False))

    def _should_render_thinking_inline(self) -> bool:
        """Whether ``<think>...</think>`` blocks embedded directly in ``content``
        (MiniMax, some third-party proxies) should be surfaced to the channel.

        Only the Web console can render them in a collapsible panel. IM channels
        (WeChat/WeCom/DingTalk/Feishu) must strip them, otherwise users see raw
        XML tags in their chat.
        """
        from config import conf
        channel_type = getattr(self.model, 'channel_type', '') or ''
        return conf().get("enable_thinking", False) and channel_type == 'web'

    def _filter_think_tags(self, text: str) -> str:
        """
        Handle <think>...</think> blocks in content returned by some LLM providers
        (e.g., MiniMax).

        - When inline thinking rendering is allowed (Web + thinking enabled):
          remove only the tags, keep the content inside.
        - Otherwise (IM channels, or thinking disabled globally): remove both
          the tags and the content entirely.
        """
        if not text:
            return text
        import re
        if self._should_render_thinking_inline():
            text = re.sub(r'<think>', '', text)
            text = re.sub(r'</think>', '', text)
        else:
            text = re.sub(r'<think>[\s\S]*?</think>', '', text)
            # 同时删除末尾未闭合的 <think> 标签（流式传输中断产生的残留）
            text = re.sub(r'<think>[\s\S]*$', '', text)
        return text

    @staticmethod
    def _split_content_blocks(content) -> Tuple[str, str]:
        """Split a content-blocks list into (visible_text, reasoning_text).

        Some providers (Anthropic-shaped adapters, MiMo sync wrappers) stream
        ``content`` as a list of blocks instead of a string. Thinking/reasoning
        blocks must never be treated as the visible reply — that is what leaked
        CoT into IM channels as an "Agent Reply". A plain string passes through
        unchanged as visible text.
        """
        if isinstance(content, str):
            return content, ""
        if not isinstance(content, list):
            return "", ""
        text_parts = []
        reasoning_parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype in ("thinking", "reasoning"):
                thinking_text = (
                    block.get("thinking")
                    or block.get("reasoning")
                    or block.get("text")
                    or ""
                )
                if thinking_text:
                    reasoning_parts.append(thinking_text)
                continue
            if btype in ("text", "text_delta", None):
                text_parts.append(block.get("text") or "")
        return "".join(text_parts), "".join(reasoning_parts)

    def _hash_args(self, args: dict) -> str:
        """Generate a simple hash for tool arguments"""
        import hashlib
        # 对键进行排序以实现一致的散列
        args_str = json.dumps(args, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(args_str.encode()).hexdigest()[:8]
    
    def _check_consecutive_failures(self, tool_name: str, args: dict) -> Tuple[bool, str, bool]:
        """
        Check if tool has failed too many times consecutively or called repeatedly with same args
        
        Returns:
            (should_stop, reason, is_critical)
            - should_stop: Whether to stop tool execution
            - reason: Reason for stopping
            - is_critical: Whether to abort entire conversation (True for 8+ failures)
        """
        args_hash = self._hash_args(args)
        
        # 统计同一工具+参数被连续调用的次数（含成功与失败）
        # 这能抓住工具明明成功、LLM 却反复调用它的死循环
        same_args_calls = 0
        for name, ahash, success in reversed(self.tool_failure_history):
            if name == tool_name and ahash == args_hash:
                same_args_calls += 1
            else:
                break  # 不同的工具或参数，停止计数
        
        # 在具有相同参数的连续 5 次调用处停止（无论成功还是失败）
        if same_args_calls >= 5:
            return True, f"工具 '{tool_name}' 使用相同参数已被调用 {same_args_calls} 次，停止执行以防止无限循环。如果需要查看配置，结果已在之前的调用中返回。", False
        
        # 计算同一工具+参数的连续失败次数
        same_args_failures = 0
        for name, ahash, success in reversed(self.tool_failure_history):
            if name == tool_name and ahash == args_hash:
                if not success:
                    same_args_failures += 1
                else:
                    break  # 遇到第一次成功即停止
            else:
                break  # 不同的工具或参数，停止计数
        
        if same_args_failures >= 3:
            return True, f"工具 '{tool_name}' 使用相同参数连续失败 {same_args_failures} 次，停止执行以防止无限循环", False
        
        # 计算同一工具的连续失败次数（任何参数）
        same_tool_failures = 0
        for name, ahash, success in reversed(self.tool_failure_history):
            if name == tool_name:
                if not success:
                    same_tool_failures += 1
                else:
                    break  # 遇到第一次成功即停止
            else:
                break  # 不同的工具，停止计数
        
        # 出现 8 次故障时硬停止 - 中止并显示关键消息
        if same_tool_failures >= 8:
            return True, _t(
                "抱歉，我没能完成这个任务。可能是我理解有误或者当前方法不太合适。\n\n建议你：\n• 换个方式描述需求试试\n• 把任务拆分成更小的步骤\n• 或者换个思路来解决",
                "Sorry, I couldn't complete this task. I may have misunderstood, or my current approach isn't quite right.\n\nYou could try:\n• Rephrasing your request\n• Breaking the task into smaller steps\n• Taking a different approach",
            ), True
        
        # 6次失败警告
        if same_tool_failures >= 6:
            return True, f"工具 '{tool_name}' 连续失败 {same_tool_failures} 次（使用不同参数），停止执行以防止无限循环", False
        
        return False, "", False
    
    def _record_tool_result(self, tool_name: str, args: dict, success: bool):
        """Record tool execution result for failure tracking"""
        args_hash = self._hash_args(args)
        self.tool_failure_history.append((tool_name, args_hash, success))
        # 仅保留最后 50 条记录以避免内存膨胀
        if len(self.tool_failure_history) > 50:
            self.tool_failure_history = self.tool_failure_history[-50:]

    def run_stream(self, user_message: str) -> str:
        """
        Execute streaming reasoning loop
        
        Args:
            user_message: User message
            
        Returns:
            Final response text
        """
        # 记录用户消息并附上模型信息。对过长的消息（例如注入的
        # 记录文本/超大提示词）做截断，让日志保持可读。
        thinking_enabled = self._is_thinking_enabled()
        thinking_label = " | 💭 thinking" if thinking_enabled else ""
        # 开启深度思考时，同时显示该模型实际解析出的推理努力级别
        # （各模型不尽相同），方便操作者确认生效的强度。
        effort_label = ""
        if thinking_enabled:
            try:
                effort = self.model._normalized_reasoning_effort()
                if effort:
                    effort_label = f" | effort={effort}"
            except Exception:
                effort_label = ""
        _log_msg = user_message if len(user_message) <= 500 else (
            user_message[:500] + f" …(+{len(user_message) - 500} chars)"
        )
        logger.info(f"🤖 {self.model.model}{thinking_label}{effort_label} | 👤 {_log_msg}")
        
        # 添加用户消息（Claude 格式 - 使用内容块以保持一致性）
        self.messages.append({
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": user_message
                }
            ]
        })

        # 在代理循环开始前只修剪一次上下文，而不是在工具执行过程中修剪。
        # 这样才能保证本次运行期间产生的 tool_use/tool_result 链
        # 不会在执行中途被剥离（否则会导致 LLM 陷入循环）。
        self._trim_messages()

        # 修剪后的校验：修剪可能恰好落在回合边界上
        # （例如保留下来的最后一轮以助手的 tool_use 结尾，
        # 而对应的 tool_result 却处在被丢弃的轮次里）。
        self._validate_and_fix_messages()

        self._emit_event("agent_start")

        # 重置本次运行作用域内的 MCP 工具检索累加器。按需检索
        # 在单次运行内只会不断扩充该集合，因此已产生过 tool_use 的
        # 工具绝不会在运行中途从 schema 中消失
        # （否则 Claude/MiniMax 会抛出消息格式错误）。
        self._retrieved_mcp_names = set()

        final_response = ""
        turn = 0

        # 尊重外层作用域已设置的运行 ID（子代理派生或委托任务
        # 传入的）；只有在自己是某次运行的最顶层时，才新生成一个 ID。
        # 通过 set_agent_run_id 写入，可让出站头部标记路径与
        # RuntimeIdentity 始终处于同一个 ID 上。
        import uuid as _uuid
        from common.utils import set_agent_run_id, clear_agent_run_id, current_agent_run_id
        # 在生成新 ID 之前先记录：一旦本次运行设定自己的 id，
        # 下游就无法再判断它是否嵌套。子代理通过 identity_scope
        # 继承父级的运行 ID，因此此刻 ID 已存在，
        # 恰恰就意味着“这是嵌套运行”。
        _nested_run = bool(current_agent_run_id())
        _run_token = None
        if not _nested_run:
            _run_token = set_agent_run_id(_uuid.uuid4().hex)

        # 清除*上一次*运行遗留的任何后备路由：新的用户消息
        # 总是从主模型重新开始。但在本次运行内部，后备策略
        # 是刻意“粘性”的——一旦主模型确实彻底失败，剩余步骤
        # 就继续沿用备用模型，而不是在已经确认宕机的提供商上
        # 每步都重试（遇到持续故障——密钥失效、IP 被封、
        # 区域性宕机——否则会白费每一步的主模型调用）。
        # 主模型要到下一条用户消息时才获得新的机会。
        #
        # 这一步必须放在上面的运行 ID *之后*执行，而不是之前：
        # 对嵌套运行而言该重置是无操作（见 _reset_model_fallback），
        # 只有运行 ID 能区分二者。嵌套运行会继续沿用父级的
        # 后备——子代理处于同一次故障之中，理应继承备用模型，
        # 而不是在刚刚失败的提供商上重新开始。
        self._reset_model_fallback(nested_run=_nested_run)

        cancelled = False
        try:
            while turn < self.max_turns:
                # 在每一轮的最开始检查取消标志，让取消请求
                # 能在轮与轮之间被干净地短路处理。
                self._check_cancelled()

                steering_updates = self._drain_steering()
                if steering_updates:
                    self._append_steering(steering_updates)

                turn += 1
                logger.info(f"[Agent] Turn {turn}")
                self._emit_event("turn_start", {"turn": turn})

                # 调用LLM（启用retry_on_empty以获得更好的可靠性）
                assistant_msg, tool_calls, stop_reason = self._call_llm_stream(retry_on_empty=True)
                final_response = assistant_msg

                # 若模型正在流式输出时到来一条转向指令，它需要
                # 优先于模型提出的后续内容。此时工具调用
                # 已经被写入历史，所以每条转向都会携带
                # 已合成好的工具结果，再要求模型重新考虑。
                steering_updates = self._drain_steering()
                if steering_updates:
                    self._append_steering(
                        steering_updates,
                        pending_tool_calls=tool_calls,
                    )
                    self._emit_event("turn_end", {
                        "turn": turn,
                        "has_tool_calls": bool(tool_calls),
                        "tool_count": len(tool_calls),
                        "stop_reason": stop_reason,
                        "steered": True,
                    })
                    continue

                # 没有工具调用，结束循环
                if not tool_calls:
                    # 检查是否返回了空响应
                    if not assistant_msg:
                        logger.warning(f"[Agent] LLM returned empty response after retry (no content and no tool calls)")
                        logger.info(f"[Agent] This usually happens when LLM thinks the task is complete after tool execution")
                        
                        # 如果之前有工具调用，强制要求 LLM 生成文本回复
                        if turn > 1:
                            logger.info(f"[Agent] Requesting explicit response from LLM...")
                            
                            # 记住位置，以便我们稍后可以删除注入的提示
                            prompt_insert_idx = len(self.messages)
                            
                            # 添加一条消息，明确要求回复用户
                            self.messages.append({
                                "role": "user",
                                "content": [{
                                    "type": "text",
                                    "text": self._explicit_response_prompt()
                                }]
                            })
                            
                            # 再调用一次 LLM
                            assistant_msg, tool_calls, stop_reason = self._call_llm_stream(retry_on_empty=False)
                            final_response = assistant_msg
                            
                            # 从历史中移除注入的提示，这样它不会作为用户消息
                            # 出现在持久对话里。
                            # _call_llm_stream 可能在提示之后又附加了一条助手消息，
                            # 所以这里只定位并删除提示本身。
                            if (prompt_insert_idx < len(self.messages)
                                    and self.messages[prompt_insert_idx].get("role") == "user"):
                                self.messages.pop(prompt_insert_idx)
                                logger.debug("[Agent] Removed injected explicit-response prompt from message history")
                            
                            # 如果 LLM 用 tool_calls 而非文本回应，就继续
                            # 落入下方的工具执行分支（不要跳出循环）。
                            if tool_calls:
                                logger.info(
                                    f"[Agent] LLM returned tool_calls in explicit-response retry, "
                                    f"continuing to execute tools instead of breaking"
                                )
                            elif not assistant_msg:
                                # 仍然为空（没有文本，也没有 tool_calls）：使用后备
                                logger.warning(f"[Agent] Still empty after explicit request")
                                final_response = self._empty_response_fallback()
                        else:
                            # 首轮即空回复，直接回退到后备文案
                            final_response = self._empty_response_fallback()
                    else:
                        logger.info(f"💭 {assistant_msg[:150]}{'...' if len(assistant_msg) > 150 else ''}")
                    
                    # 如果显式请求重试返回了 tool_calls，则跳过上面的跳出，
                    # 在同一轮迭代里继续向下进入工具执行分支。
                    if not tool_calls:
                        steering_updates = self._drain_steering()
                        if steering_updates:
                            self._append_steering(steering_updates)
                            self._emit_event("turn_end", {
                                "turn": turn,
                                "has_tool_calls": False,
                                "stop_reason": stop_reason,
                                "steered": True,
                            })
                            continue
                        if not self._close_or_apply_final_steering():
                            self._emit_event("turn_end", {
                                "turn": turn,
                                "has_tool_calls": False,
                                "stop_reason": stop_reason,
                                "steered": True,
                            })
                            continue
                        logger.debug(f"✅ Done (no tool calls, stop_reason={stop_reason or 'none'})")
                        self._emit_event("turn_end", {
                            "turn": turn,
                            "has_tool_calls": False,
                            "stop_reason": stop_reason
                        })
                        break

                # 使用参数记录工具调用（截断长值，如 base64）
                tool_calls_str = []
                for tc in tool_calls:
                    args = tc.get('arguments') or {}
                    if isinstance(args, dict):
                        parts = []
                        for k, v in args.items():
                            v_str = str(v)
                            if len(v_str) > 200:
                                v_str = v_str[:200] + f"...({len(v_str)} chars)"
                            parts.append(f"{k}={v_str}")
                        args_str = ', '.join(parts)
                        if args_str:
                            tool_calls_str.append(f"{tc['name']}({args_str})")
                        else:
                            tool_calls_str.append(tc['name'])
                    else:
                        tool_calls_str.append(tc['name'])
                logger.info(f"🔧 {', '.join(tool_calls_str)}")

                # 执行工具
                tool_results = []
                tool_result_blocks = []

                try:
                    already_run = self._run_parallel_calls(tool_calls)
                    for tool_index, tool_call in enumerate(tool_calls):
                        # 同一轮内的各工具调用之间也要响应取消请求
                        self._check_cancelled()
                        steering_updates = self._drain_steering()
                        if steering_updates:
                            self._append_steering(
                                steering_updates,
                                pending_tool_calls=tool_calls[tool_index:],
                                content_blocks=tool_result_blocks,
                            )
                            break
                        if tool_call["id"] in already_run:
                            result = already_run[tool_call["id"]]
                        else:
                            result = self._execute_tool(tool_call)
                        tool_results.append(result)
                        
                        # 调试：检查是否使用相同的参数重复调用工具
                        if turn > 2:
                            # 检查最后 N 个工具调用是否重复
                            repeat_count = sum(
                                1 for name, ahash, _ in self.tool_failure_history[-10:]
                                if name == tool_call["name"] and ahash == self._hash_args(tool_call["arguments"])
                            )
                            if repeat_count >= 3:
                                logger.warning(
                                    f"⚠️  Tool '{tool_call['name']}' has been called {repeat_count} times "
                                    f"with same arguments. This may indicate a loop."
                                )
                        
                        # 检查这是否是要发送的文件
                        if result.get("status") == "success" and isinstance(result.get("result"), dict):
                            result_data = result.get("result")
                            if result_data.get("type") == "file_to_send":
                                self.files_to_send.append(result_data)
                                logger.info(f"📎 File queued for sending: {result_data.get('file_name', result_data.get('path'))}")
                                self._emit_event("file_to_send", result_data)

                        # 显示代理编写的面向用户的文件
                        self._maybe_emit_artifact(tool_call, result)
                        
                        # 检查严重错误 - 中止整个对话
                        if result.get("status") == "critical_error":
                            logger.error(f"💥 Fatal error detected, aborting conversation")
                            final_response = result.get('result') or _t("任务执行失败", "Task execution failed")
                            return final_response
                        
                        # 以紧凑格式记录工具结果
                        status_emoji = "✅" if result.get("status") == "success" else "❌"
                        result_data = result.get('result', '')
                        # 以 UTF-8（ensure_ascii=False）格式化结果字符串，保证中文字符正常
                        if isinstance(result_data, (dict, list)):
                            result_str = json.dumps(result_data, ensure_ascii=False)
                        else:
                            result_str = str(result_data)
                        logger.info(f"  {status_emoji} {tool_call['name']} ({result.get('execution_time', 0):.2f}s): {result_str[:200]}{'...' if len(result_str) > 200 else ''}")

                        # 构建工具结果块（Claude 格式）
                        # 以 LLM 易于理解的方式格式化内容
                        is_error = result.get("status") == "error"

                        if is_error:
                            # 对于错误，提供明确的错误消息
                            result_content = f"Error: {result.get('result', 'Unknown error')}"
                        elif isinstance(result.get('result'), dict):
                            # 对于 dict 结果，使用 JSON 格式
                            result_content = json.dumps(result.get('result'), ensure_ascii=False)
                        elif isinstance(result.get('result'), str):
                            # 对于字符串结果，直接使用
                            result_content = result.get('result')
                        else:
                            # 回退到完整 JSON
                            result_content = json.dumps(result, ensure_ascii=False)

                        # 截断当前轮次过大的工具结果
                        # 历史轮次的结果将在 _trim_messages() 中被进一步截断
                        MAX_CURRENT_TURN_RESULT_CHARS = 50000
                        if len(result_content) > MAX_CURRENT_TURN_RESULT_CHARS:
                            truncated_len = len(result_content)
                            result_content = result_content[:MAX_CURRENT_TURN_RESULT_CHARS] + \
                                f"\n\n[Output truncated: {truncated_len} chars total, showing first {MAX_CURRENT_TURN_RESULT_CHARS} chars]"
                            logger.info(f"📎 Truncated tool result for '{tool_call['name']}': {truncated_len} -> {MAX_CURRENT_TURN_RESULT_CHARS} chars")

                        tool_result_block = {
                            "type": "tool_result",
                            "tool_use_id": tool_call["id"],
                            "content": result_content
                        }
                        
                        # 为 Claude API 添加 is_error 字段（帮助模型理解故障）
                        if is_error:
                            tool_result_block["is_error"] = True
                        
                        tool_result_blocks.append(tool_result_block)
                
                finally:
                    # 关键：始终追加 tool_result，以维持消息历史的完整性
                    # 即使工具执行失败，也必须添加错误结果来与 tool_use 配对
                    if tool_result_blocks:
                        # 将工具结果作为用户消息添加到消息历史记录（Claude 格式）
                        self.messages.append({
                            "role": "user",
                            "content": tool_result_blocks
                        })
                        
                        # 检测潜在的无限循环：同一工具成功调用多次
                        # 如果检测到，向 LLM 添加提示以停止调用工具并提供响应
                        if turn >= 3 and len(tool_calls) > 0:
                            tool_name = tool_calls[0]["name"]
                            args_hash = self._hash_args(tool_calls[0]["arguments"])
                            
                            # 使用相同的工具+参数计算最近成功的调用
                            recent_success_count = 0
                            for name, ahash, success in reversed(self.tool_failure_history[-10:]):
                                if name == tool_name and ahash == args_hash and success:
                                    recent_success_count += 1
                            
                            # 若同一参数下成功调用工具 3 次以上，就追加提示要求模型停止循环
                            if recent_success_count >= 3:
                                logger.warning(
                                    f"⚠️  Detected potential loop: '{tool_name}' called {recent_success_count} times "
                                    f"with same args. Adding hint to LLM to provide final response."
                                )
                                # 添加温和的提示信息，引导LLM做出回应
                                self.messages.append({
                                    "role": "user",
                                    "content": [{
                                        "type": "text",
                                        "text": "工具已成功执行并返回结果。请基于这些信息向用户做出回复，不要重复调用相同的工具。"
                                    }]
                                })
                    elif tool_calls:
                        # 如果我们有 tool_calls 但没有 tool_result_blocks （意外错误），
                        # 为所有工具调用创建错误结果以维护消息完整性
                        logger.warning("⚠️ Tool execution interrupted, adding error results to maintain message history")
                        emergency_blocks = []
                        for tool_call in tool_calls:
                            emergency_blocks.append({
                                "type": "tool_result",
                                "tool_use_id": tool_call["id"],
                                "content": "Error: Tool execution was interrupted",
                                "is_error": True
                            })
                        self.messages.append({
                            "role": "user",
                            "content": emergency_blocks
                        })

                self._emit_event("turn_end", {
                    "turn": turn,
                    "has_tool_calls": True,
                    "tool_count": len(tool_calls),
                    "stop_reason": stop_reason
                })

            if turn >= self.max_turns:
                logger.warning(f"⚠️  Reached max decision step limit: {self.max_turns}")
                self._drain_and_close_steering()
                
                # 强制模型在不调用工具的情况下进行总结
                logger.info(f"[Agent] Requesting summary from LLM after reaching max steps...")
                
                # 在注入提示之前记住位置，以便我们稍后可以将其删除
                prompt_insert_idx = len(self.messages)
                
                # 添加临时提示强制汇总
                self.messages.append({
                    "role": "user",
                    "content": [{
                        "type": "text",
                        "text": f"你已经执行了{turn}个决策步骤，达到了单次运行的最大步数限制。请总结一下你目前的执行过程和结果，告诉用户当前的进展情况。不要再调用工具，直接用文字回复。"
                    }]
                })
                
                # 再次调用LLM以获取摘要（无需重试以避免循环）
                try:
                    summary_response, summary_tools, _ = self._call_llm_stream(retry_on_empty=False)
                    if summary_response:
                        final_response = summary_response
                        logger.info(f"💭 Summary: {summary_response[:150]}{'...' if len(summary_response) > 150 else ''}")
                    else:
                        # 如果模型仍然没有响应则回退
                        final_response = _t(
                            f"我已经执行了{turn}个决策步骤，达到了单次运行的步数上限。任务可能还未完全完成，建议你将任务拆分成更小的步骤，或者换一种方式描述需求。",
                            f"I've taken {turn} decision steps and reached the per-run limit. The task may not be fully complete — try breaking it into smaller steps, or describe your request differently.",
                        )
                except Exception as e:
                    logger.warning(f"Failed to get summary from LLM: {e}")
                    final_response = _t(
                        f"我已经执行了{turn}个决策步骤，达到了单次运行的步数上限。任务可能还未完全完成，建议你将任务拆分成更小的步骤，或者换一种方式描述需求。",
                        f"I've taken {turn} decision steps and reached the per-run limit. The task may not be fully complete — try breaking it into smaller steps, or describe your request differently.",
                    )
                finally:
                    # 从历史中删除注入的用户提示，避免污染
                    # 保存下来的对话记录。助手摘要（如果有）
                    # 已由 _call_llm_stream 追加，会予以保留。
                    if (prompt_insert_idx < len(self.messages)
                            and self.messages[prompt_insert_idx].get("role") == "user"):
                        self.messages.pop(prompt_insert_idx)
                        logger.debug("[Agent] Removed injected max-steps prompt from message history")

        except AgentCancelledError:
            # 用户主动取消：妥善收尾消息历史，确保
            # 下一轮不受影响；由通道对外发出“已取消”的 UI 事件。
            cancelled = True
            logger.info(f"[Agent] 🛑 Cancelled by user (turn {turn})")
            self._handle_cancelled(final_response)
            if not final_response or not final_response.strip():
                final_response = "_(Cancelled)_"

        except Exception as e:
            logger.error(f"❌ Agent execution error: {e}")
            self._emit_event("error", {"error": str(e)})
            raise

        finally:
            if _run_token is not None:
                clear_agent_run_id(_run_token)
            if self.steer_inbox is not None:
                self.steer_inbox.close()
            final_response = final_response.strip() if final_response else final_response
            if cancelled:
                # 在 agent_end 之前发出，便于通道把 UI 标记为“已取消”
                self._emit_event("agent_cancelled", {"final_response": final_response})
            logger.info(f"[Agent] 🏁 Done ({turn} turns)" + (" [cancelled]" if cancelled else ""))
            self._emit_event("agent_end", {"final_response": final_response, "cancelled": cancelled})

        return final_response

    def _select_tools_for_injection(self) -> list:
        """Decide which tools to inject into the current LLM turn.

        A tool behind a setting is left out while that setting is off, and
        picked up again on the turn after it is switched back on.

        Built-in tools are ALWAYS injected in full (skills and core flows hard
        depend on them). MCP tools are also injected in full UNLESS on-demand
        retrieval is enabled AND the MCP tool count exceeds the configured
        threshold — then only the most relevant MCP tools are injected, unioned
        with those already selected earlier in this run (only-grows, so a tool
        that already produced a tool_use never vanishes from the schema).

        Degrades safely: disabled feature, no embedding provider, embedding
        failure, count below threshold, or any error → inject all tools. Tools
        are never silently dropped.
        """
        all_tools = [tool for tool in self.tools.values() if is_tool_available(tool)]
        try:
            from config import conf
            if not conf().get("mcp_tool_retrieval_enabled", False):
                return all_tools

            from agent.tools.mcp.mcp_tool import McpTool
            mcp_tools = [t for t in all_tools if isinstance(t, McpTool)]
            builtin_tools = [t for t in all_tools if not isinstance(t, McpTool)]

            threshold = int(conf().get("mcp_tool_retrieval_threshold", 20) or 20)
            if len(mcp_tools) <= threshold:
                return all_tools

            top_k = int(conf().get("mcp_tool_retrieval_top_k", 10) or 10)

            from agent.tools import ToolManager
            from agent.tools.mcp.tool_retrieval import (
                build_retrieval_query,
                select_mcp_tools_with_metadata,
            )

            tm = ToolManager()
            tool_vectors = tm.get_mcp_tool_vectors()
            query = build_retrieval_query(self.messages)
            query_vector = tm.embed_query(query)

            decision = select_mcp_tools_with_metadata(
                query_vector,
                tool_vectors,
                top_k,
                getattr(self, "_retrieved_mcp_names", set()),
            )
            if decision is None or decision.fallback_reason is not None:
                # 无提供者/空索引/错误→完全注入。
                self._emit_tool_retrieval_event(
                    mcp_tools,
                    builtin_tools,
                    top_k,
                    decision=decision,
                    mode="fallback",
                )
                return all_tools

            # 保留后续回合的累积选择。
            self._retrieved_mcp_names = decision.selected

            selected_mcp = [t for t in mcp_tools if t.name in decision.selected]
            self._emit_tool_retrieval_event(
                mcp_tools,
                builtin_tools,
                top_k,
                decision=decision,
                mode="retrieved",
            )
            logger.info(
                f"[ToolRetrieval] Injecting {len(builtin_tools)} built-in + "
                f"{len(selected_mcp)}/{len(mcp_tools)} MCP tool(s) (top_k={top_k})"
            )
            return builtin_tools + selected_mcp
        except Exception as e:
            logger.debug(f"[ToolRetrieval] full injection (retrieval skipped): {e}")
            self._emit_tool_retrieval_event(
                mcp_tools if "mcp_tools" in locals() else [],
                builtin_tools if "builtin_tools" in locals() else [],
                top_k if "top_k" in locals() else 0,
                mode="fallback",
                fallback_reason="retrieval_error",
            )
            return all_tools

    def _emit_tool_retrieval_event(
        self,
        mcp_tools: List[BaseTool],
        builtin_tools: List[BaseTool],
        top_k: int,
        decision=None,
        mode: str = "fallback",
        fallback_reason: Optional[str] = None,
    ) -> None:
        """Expose sanitized MCP retrieval metadata to streaming consumers."""
        if not callable(getattr(self, "_emit_event", None)):
            return

        try:
            fallback_reason = fallback_reason or (
                decision.fallback_reason
                if decision is not None
                else "selection_unavailable"
            )
            selected = decision.selected if decision is not None else set()
            ranked = decision.ranked if decision is not None else []
            candidate_count = decision.candidate_count if decision is not None else 0
            rank_limit = max(top_k, 0)
            injected_names = (
                sorted(tool.name for tool in mcp_tools)
                if mode == "fallback" else sorted(selected)
            )
            self._emit_event("tool_retrieval", {
                "enabled": True,
                "mode": mode,
                "total_mcp_tools": len(mcp_tools),
                "selected_mcp_tools": (
                    len([tool for tool in mcp_tools if tool.name in selected])
                    if mode == "retrieved" else len(mcp_tools)
                ),
                "builtin_tools": len(builtin_tools),
                "top_k": top_k,
                "candidate_count": candidate_count,
                "selected_tools": injected_names,
                "ranked_tools": [
                    {"name": name, "score": round(float(score), 6)}
                    for name, score in ranked[:rank_limit]
                ],
                "fallback_reason": fallback_reason,
            })
        except Exception as e:
            # 可观测性绝不能把本应安全兜底的检索流程变成
            # 代理故障，即使自定义的事件消费者有缺陷也一样。
            logger.debug(f"[ToolRetrieval] event emission skipped: {e}")

    def _reset_model_fallback(self, nested_run: bool = False) -> None:
        """Drop any fallback routing so the next call uses the primary model.

        ``nested_run`` marks a run that inherited its run id from an outer
        scope — a sub agent spawn or a delegated task. Those must leave the
        parent's routing alone: a sub agent is built with the parent's *same*
        model object, so resetting here would clear the fallback the parent is
        mid-way through relying on and send both of them back to the provider
        that just failed.

        Fallback is opt-in and this is a no-op on models that don't support it,
        so it is safe to call unconditionally at the top of a run.
        """
        # 调用方需在生成自己的运行 ID *之前*捕获这一标记——一旦
        # ID 被设定，下游就无法区分嵌套运行与顶层运行，
        # 因此必须把这一区别显式传入。
        if nested_run:
            return

        model = getattr(self, "model", None)
        reset = getattr(model, "reset_fallback", None)
        if not callable(reset):
            return
        try:
            reset()
        except Exception as e:
            logger.debug(f"[Agent] fallback reset skipped: {e}")

    def _switch_to_fallback(self, fallback_reason: str = "") -> bool:
        """Try to reroute the rest of this turn onto the configured fallback.

        Returns True only when the switch actually happened, so the caller can
        retry the turn on the new model. Every guard lives in
        ``AgentLLMModel.use_fallback``; this wrapper only covers the cases
        where there is no such model to ask (tests pass doubles, and the
        fallback is opt-in so a plain LLMModel simply has no support for it).

        Context-overflow and message-format errors are deliberately NOT
        candidates: they are caused by the conversation, not the provider, and
        the recovery paths above already rewrite the history for them.
        """
        model = getattr(self, "model", None)
        use_fallback = getattr(model, "use_fallback", None)
        if not callable(use_fallback):
            return False
        try:
            return bool(use_fallback())
        except Exception as e:
            logger.warning(f"[Agent] chat fallback unavailable: {e}")
            return False

    def _call_llm_stream(self, retry_on_empty=True, retry_count=0, max_retries=3,
                         _overflow_stage: int = 0) -> Tuple[str, List[Dict], Optional[str]]:
        """
        Call LLM with streaming and automatic retry on errors

        Args:
            retry_on_empty: Whether to retry once if empty response is received
            retry_count: Current retry attempt (internal use)
            max_retries: Maximum number of retries for API errors
            _overflow_stage: Context-overflow recovery escalation level (internal):
                0 = first hit, 1 = after aggressive trim, 2 = after hard compaction.

        Returns:
            (response_text, tool_calls, stop_reason), where stop_reason is the
            provider's finish_reason for this generation, or None when it
            reported none. A turn that returns text and no tool calls looks
            finished either way, so stop_reason is the only thing separating a
            model that chose to stop from one cut off at the output token limit
            ("length" / "max_tokens").
        """
        # 校验并修复消息历史（例如孤立的 tool_result 块）。
        # 上下文修剪只在 run_stream() 里、循环开始之前执行一次，
        # 而非在这里——在执行途中修剪会剥掉当前运行的
        # tool_use/tool_result 链并导致 LLM 循环。
        self._validate_and_fix_messages()

        # 准备消息
        messages = self._prepare_messages()
        turns = self._identify_complete_turns()
        logger.info(f"Sending {len(messages)} messages ({len(turns)} turns) to LLM")

        # 拉取自本轮开始以来已完成加载的任何 MCP 工具。
        # 这只是一次廉价的字典核对（微秒级）——让代理能在对话进行中
        # 识别到新可用的 MCP 工具，而无需重启会话。
        try:
            from agent.tools import ToolManager
            ToolManager().sync_mcp_into_agent(self)
        except Exception as e:
            logger.debug(f"[Agent] MCP sync skipped: {e}")

        # 准备工具定义。当 get_json_schema() 能产出真实属性时优先采用
        # （让工具能在运行时增强 schema），否则
        # 回退到静态的 `tool.params`（MCP 工具依赖此项）。
        tools_schema = None
        if self.tools:
            tools_schema = []
            for tool in self._select_tools_for_injection():
                input_schema = tool.params
                try:
                    dynamic = (tool.get_json_schema() or {}).get("parameters") or {}
                    if dynamic.get("properties"):
                        input_schema = dynamic
                except Exception:
                    pass
                tools_schema.append({
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": input_schema,
                })

        # 调试：把发送给 LLM 的完整系统提示与消息转储出来。
        # 由 `debug` 配置项控制开关，以免刷屏普通日志。
        # try:
        #     from config import conf
        #     if conf().get("debug", False):
        #         logger.debug(
        #             "[Agent][debug] system_prompt sent to LLM"
        #             f"({len(self.system_prompt or '')} chars):\n"
        #             "================ system prompt start ================\n"
        #             f"{self.system_prompt}\n"
        #             "================ system prompt end =================="
        #         )
        #         logger.info(f"[Agent][debug] messages sent to LLM: {messages}")
        # except Exception:
        #     pass

        # 创建请求
        request = LLMRequest(
            messages=messages,
            temperature=0,
            stream=True,
            tools=tools_schema,
            system=self.system_prompt  # Claude API 单独传递系统提示
        )

        self._emit_event("message_start", {"role": "assistant"})

        # 流式响应
        full_content = ""
        full_reasoning = ""
        tool_calls_buffer = {}  # {索引：{id，名称，参数}}
        gemini_raw_parts = None  # 保留 Gemini 的 thoughtSignature 以便原样往返
        stop_reason = None  # 跟踪流停止的原因

        try:
            stream = self.model.call_stream(request)

            # 每 N 个块探测一次取消标志，以约束响应延迟，而不必
            # 逐 token 检查。
            _cancel_probe_counter = 0
            _CANCEL_PROBE_EVERY = 8

            for chunk in stream:
                _cancel_probe_counter += 1
                if _cancel_probe_counter >= _CANCEL_PROBE_EVERY:
                    _cancel_probe_counter = 0
                    if self.cancel_event is not None and self.cancel_event.is_set():
                        # 只保留部分文本；tool_use 的参数可能
                        # 在中途被截断而无法通过校验。
                        logger.info("[Agent] cancel detected mid-stream, aborting LLM call")
                        if full_content:
                            partial_msg = {
                                "role": "assistant",
                                "content": [{"type": "text", "text": full_content}],
                            }
                            self.messages.append(partial_msg)
                        self._emit_event("message_end", {
                            "content": full_content,
                            "tool_calls": [],
                            "cancelled": True,
                        })
                        raise AgentCancelledError("cancelled during LLM streaming")

                # 检查是否有错误
                if isinstance(chunk, dict) and chunk.get("error"):
                    # 从嵌套结构中提取错误消息
                    error_data = chunk.get("error", {})
                    if isinstance(error_data, dict):
                        error_msg = error_data.get("message", chunk.get("message", "Unknown error"))
                        error_code = error_data.get("code", "")
                        error_type = error_data.get("type", "")
                    else:
                        error_msg = chunk.get("message", str(error_data))
                        error_code = ""
                        error_type = ""
                    
                    status_code = chunk.get("status_code", "N/A")
                    
                    # 记录错误以及所有可用信息
                    logger.error(f"🔴 Stream API Error:")
                    logger.error(f"   Message: {error_msg}")
                    logger.error(f"   Status Code: {status_code}")
                    logger.error(f"   Error Code: {error_code}")
                    logger.error(f"   Error Type: {error_type}")
                    logger.error(f"   Full chunk: {chunk}")
                    
                    # 判断这是否属于上下文溢出错误。这里统一使用同一个
                    # 共享分类器（_is_context_overflow），让标记词集中在一处、永不漂移。
                    # 刻意不去匹配裸的 “too large”：过大的上传
                    # （413 “file too large”/“image too large”）绝不能算作上下文溢出，
                    # 否则我们会把一段完全健康的对话压缩/清理掉，去“恢复”
                    # 一个与上下文长度无关的问题。
                    # 不要依赖具体的状态码——各家提供商不尽相同。
                    error_msg_lower = error_msg.lower()
                    is_overflow = _is_context_overflow(error_msg_lower)

                    if is_overflow:
                        # 标记为上下文溢出以进行特殊处理
                        raise Exception(f"[CONTEXT_OVERFLOW] {error_msg} (Status: {status_code})")
                    else:
                        # 抛出带完整错误信息的异常，供重试逻辑使用
                        raise Exception(f"{error_msg} (Status: {status_code}, Code: {error_code}, Type: {error_type})")

                # 解析块
                if isinstance(chunk, dict) and chunk.get("choices"):
                    choice = chunk["choices"][0]
                    delta = choice.get("delta", {})
                    
                    # 捕获 finish_reason（如果存在）
                    finish_reason = choice.get("finish_reason")
                    if finish_reason:
                        stop_reason = finish_reason

                    reasoning_delta = delta.get("reasoning_content") or ""
                    if reasoning_delta:
                        full_reasoning += reasoning_delta
                        if self._is_thinking_enabled():
                            self._emit_event("reasoning_update", {"delta": reasoning_delta})

                    # 处理文本内容。某些提供商（仿 Anthropic 结构的适配器、
                    # MiMo 同步包装器）会以块列表而非字符串的形式流式传输内容。
                    # 思考/推理块绝不能当作可见回复——
                    # 正是这一点曾把 CoT 以“Agent Reply”的形式
                    # 泄漏进 IM 渠道。
                    content_delta = delta.get("content") or ""
                    if isinstance(content_delta, list):
                        content_delta, thinking_text = self._split_content_blocks(content_delta)
                        if thinking_text:
                            full_reasoning += thinking_text
                            if self._is_thinking_enabled():
                                self._emit_event("reasoning_update", {"delta": thinking_text})
                    if content_delta:
                        # 从内容中过滤掉 <think> 标签
                        filtered_delta = self._filter_think_tags(content_delta)
                        full_content += filtered_delta
                        if filtered_delta:  # 仅当过滤后有内容时才发出
                            self._emit_event("message_update", {"delta": filtered_delta})

                    # 处理工具调用
                    if "tool_calls" in delta and delta["tool_calls"]:
                        for tc_delta in delta["tool_calls"]:
                            index = tc_delta.get("index", 0)

                            if index not in tool_calls_buffer:
                                tool_calls_buffer[index] = {
                                    "id": "",
                                    "name": "",
                                    "arguments": ""
                                }

                            if tc_delta.get("id"):
                                tool_calls_buffer[index]["id"] = tc_delta["id"]

                            if "function" in tc_delta:
                                func = tc_delta["function"]
                                if func.get("name"):
                                    tool_calls_buffer[index]["name"] = func["name"]
                                if func.get("arguments"):
                                    tool_calls_buffer[index]["arguments"] += func["arguments"]

                    # 保留 _gemini_raw_parts 以支持 Gemini thoughtSignature 的往返
                    # （原生 Gemini：parts 列表；LinkAI 代理：parts 的 JSON base64 字符串）
                    if "_gemini_raw_parts" in delta:
                        gemini_raw_parts = delta["_gemini_raw_parts"]
                    elif isinstance(choice, dict) and choice.get("_gemini_raw_parts"):
                        gemini_raw_parts = choice["_gemini_raw_parts"]

        except AgentCancelledError:
            # 必须原样向上抛出；绝不能把它当作可重试的错误。
            raise

        except Exception as e:
            error_str = str(e)
            error_str_lower = error_str.lower()
            
            # 上下文溢出是不可重试的，需要重置工作上下文。
            is_context_overflow = _is_context_overflow(error_str_lower)

            # 不完整的 tool_use/tool_result 配对会被提供商拒绝。
            # MiniMax 的 “tool result with tool id(...) not found”（代码 2013）
            # 由 “tool result”/“tool id” 标记覆盖。
            is_message_format_error = _is_message_format_error(error_str_lower)
            
            if is_context_overflow or is_message_format_error:
                error_type = "context overflow" if is_context_overflow else "message format error"
                logger.error(f"💥 {error_type} detected: {e}")

                # 修剪前先把即将丢失的上下文刷入记忆，以作保留
                if is_context_overflow and self.agent.memory_manager:
                    user_id = getattr(self.agent, '_current_user_id', None)
                    self.agent.memory_manager.flush_memory(
                        messages=self.messages, user_id=user_id,
                        reason="overflow", max_messages=0
                    )

                # 智能压缩恢复——沿用与主动修剪 _trim_messages 相同的策略
                # （丢弃较旧的一半并注入 LLM 摘要，
                # 或当轮次很少时压缩成纯文本），
                # 但以提供商报告的实际上限来驱动它，这样我们能
                # 收缩到精确的天花板，而不是反复重试同一个
                # 超大请求（正是用户在 LinkAI 后端看到的死循环）。
                # 消息格式错误没有可触及的 token 预算，因此会直接
                # 跳到下方的上下文重置。
                if is_context_overflow and _overflow_stage == 0:
                    if self._smart_compact_to_budget(error_str):
                        logger.warning("🔄 Smart-compacted context to fit the reported limit, retrying...")
                        return self._call_llm_stream(
                            retry_on_empty=retry_on_empty,
                            retry_count=retry_count,
                            max_retries=max_retries,
                            _overflow_stage=1,
                        )

                # 修剪已到极限，或者这是消息格式错误。
                # 这里只重置内存中的工作上下文：持久化历史
                # 不可重建，且损坏的工具对永远无法重新引入，
                # 因为每条加载路径都会剥除 tool_use/tool_result 块。
                logger.warning("🔄 Resetting in-memory context to recover (stored history kept)")
                self.messages.clear()
                if is_context_overflow:
                    raise Exception(_t(
                        "抱歉，对话历史过长导致上下文溢出。我已重置当前上下文（历史记录仍然保留），请重新描述你的需求。",
                        "Sorry, the conversation history got too long and overflowed the context. I've reset the current context (your history is kept) — please describe your request again.",
                    ))
                else:
                    raise Exception(_t(
                        "抱歉，之前的对话出现了问题。我已重置当前上下文（历史记录仍然保留），请重新发送你的消息。",
                        "Sorry, something went wrong with the earlier conversation. I've reset the current context (your history is kept) — please send your message again.",
                    ))
            
            # 检查错误是否为速率限制 (429)
            is_rate_limit = '429' in error_str_lower or 'rate limit' in error_str_lower
            
            # 检查错误是否可重试（超时、连接、服务器繁忙等）
            is_retryable = any(keyword in error_str_lower for keyword in [
                'timeout', 'timed out', 'connection', 'network', 
                'rate limit', 'overloaded', 'unavailable', 'busy', 'retry',
                '429', '500', '502', '503', '504', '512'
            ])
            
            if is_retryable and retry_count < max_retries:
                # 速率限制需要较长的等待时间，但设有上限，使累计退避
                # 保持在网络流的空闲超时范围内（参见上文
                # 关于 RATE_LIMIT_MAX_WAIT 的注释）。
                if is_rate_limit:
                    wait_time = min(30 + (retry_count * 15), RATE_LIMIT_MAX_WAIT)  # 30秒..60秒
                else:
                    wait_time = (retry_count + 1) * 2  # 其他错误为 2 秒、4 秒、6 秒
                
                logger.warning(f"⚠️ LLM API error (attempt {retry_count + 1}/{max_retries}): {e}")
                logger.info(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)
                return self._call_llm_stream(
                    retry_on_empty=retry_on_empty, 
                    retry_count=retry_count + 1,
                    max_retries=max_retries
                )

            # 重试次数已耗尽（或该错误不可重试）。在彻底失败之前，
            # 尝试一次配置好的备用模型——提供商级别的故障
            # 正是反复重试同一端点永远无法解决的问题。
            if self._switch_to_fallback(fallback_reason=error_str):
                self._emit_event("model_fallback", {
                    "reason": error_str,
                    "model": getattr(self.model, "model", ""),
                })
                return self._call_llm_stream(
                    retry_on_empty=retry_on_empty,
                    retry_count=0,          # 新模式的新尝试
                    max_retries=max_retries,
                )

            if retry_count >= max_retries:
                logger.error(f"❌ LLM API error after {max_retries} retries: {e}", exc_info=True)
            else:
                logger.error(f"❌ LLM call error (non-retryable): {e}", exc_info=True)
            raise

        # 解析工具调用
        tool_calls = []
        for idx in sorted(tool_calls_buffer.keys()):
            tc = tool_calls_buffer[idx]

            # 确保工具调用具有有效的 ID（某些提供程序返回空/无 ID）
            tool_id = tc.get("id") or ""
            if not tool_id:
                import uuid
                tool_id = f"call_{uuid.uuid4().hex[:24]}"

            args_str = tc.get("arguments") or ""
            arguments, parse_err = _parse_tool_args(args_str, stop_reason, tc["name"])
            if parse_err:
                logger.error(
                    f"Tool args parse failed for {tc['name']} ({len(args_str)} chars): {parse_err}"
                )
                tool_calls.append({
                    "id": tool_id,
                    "name": tc["name"],
                    "arguments": {},
                    "_parse_error": parse_err,
                })
                continue

            tool_calls.append({
                "id": tool_id,
                "name": tc["name"],
                "arguments": arguments
            })

        # 检查空响应并重试一次（如果启用）
        if retry_on_empty and not full_content and not tool_calls:
            logger.warning(f"⚠️  LLM returned empty response (stop_reason: {stop_reason}), retrying once...")
            self._emit_event("message_end", {
                "content": "",
                "tool_calls": [],
                "empty_retry": True,
                "stop_reason": stop_reason
            })
            # 重试时不带重试标志以避免无限循环
            return self._call_llm_stream(
                retry_on_empty=False, 
                retry_count=retry_count,
                max_retries=max_retries
            )

        # 再次过滤 full_content（以防 <think> 标签被切分进多个块中）
        full_content = self._filter_think_tags(full_content)
        
        # 将助手消息加入历史（Claude 格式采用内容块）
        assistant_msg = {"role": "assistant", "content": []}

        if full_reasoning:
            stored_reasoning = _truncate_reasoning_for_storage(full_reasoning)
            if len(stored_reasoning) < len(full_reasoning):
                logger.info(
                    f"[reasoning] truncated for storage: "
                    f"{len(full_reasoning)} -> {len(stored_reasoning)} chars"
                )
            assistant_msg["content"].append({
                "type": "thinking",
                "thinking": stored_reasoning
            })

        if full_content:
            assistant_msg["content"].append({
                "type": "text",
                "text": full_content
            })

        # 添加 tool_use 块（如果存在）
        if tool_calls:
            for tc in tool_calls:
                assistant_msg["content"].append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc.get("name", ""),
                    "input": tc.get("arguments", {})
                })
        
        if gemini_raw_parts:
            assistant_msg["_gemini_raw_parts"] = gemini_raw_parts

        # 仅当内容不为空时才追加
        if assistant_msg["content"]:
            self.messages.append(assistant_msg)

        self._emit_event("message_end", {
            "content": full_content,
            "tool_calls": tool_calls,
            "stop_reason": stop_reason
        })

        return full_content, tool_calls, stop_reason

    def _required_params(self, tool_name: str) -> list:
        """Parameter names a tool's schema declares as required."""
        tool = self.tools.get(tool_name)
        params = getattr(tool, "params", None)
        required = params.get("required") if isinstance(params, dict) else None
        return list(required) if isinstance(required, list) else []

    def _run_parallel_calls(self, tool_calls: List[Dict]) -> Dict[str, Dict[str, Any]]:
        """Start every parallel-safe call of this turn at once, keyed by call id.

        Tools otherwise run strictly in the order the model asked for them.
        That is the right default, but a model that splits independent work
        across several calls - the usual way of expressing it - would then have
        the second wait out the first. For a tool that declares itself
        parallel_safe the wait buys nothing, so those calls are run together
        here and the loop below picks up the finished results in place.

        Each call gets its own copy of the tool: the loop drives tools by
        assigning `cancel_event` and `progress_callback` before a call and
        clearing them after, which two concurrent calls on one instance would
        do to each other.
        """
        eligible = [
            call for call in tool_calls
            if getattr(self.tools.get(call["name"]), "parallel_safe", False)
        ]
        if len(eligible) < 2:
            return {}

        logger.info(f"[Agent] Running {len(eligible)} tool calls in parallel")
        pool = ThreadPoolExecutor(
            max_workers=len(eligible), thread_name_prefix="parallel-tool"
        )
        try:
            futures = {}
            for call in eligible:
                # copy_context 会把运行时身份——是哪个代理、哪个会话——
                # 带入工作线程，因此该工具在本次调用中写入的任何内容，
                # 都会正确地落到这个线程所对应的位置上。
                ctx = contextvars.copy_context()
                futures[call["id"]] = pool.submit(
                    ctx.run, self._execute_tool, call, copy.copy(self.tools[call["name"]])
                )
            return {call_id: future.result() for call_id, future in futures.items()}
        finally:
            pool.shutdown(wait=False)

    def _execute_tool(self, tool_call: Dict, tool_override: Optional[BaseTool] = None) -> Dict[str, Any]:
        """
        Execute tool

        Args:
            tool_call: {"id": str, "name": str, "arguments": dict}
            tool_override: run against this instance instead of the shared one

        Returns:
            Tool execution result
        """
        tool_name = tool_call["name"]
        tool_id = tool_call["id"]
        arguments = tool_call["arguments"]

        if "_parse_error" in tool_call:
            result = {
                "status": "error",
                "result": tool_call["_parse_error"],
                "execution_time": 0,
            }
            self._record_tool_result(tool_name, arguments, False)
            return result

        # 参数根本没送达的调用会被解析成空字典，若不处理，
        # 它会照常到达工具，然后被报成“缺了某个字段”——
        # 这会让模型去“修正”它从未发送过的参数。
        missing = self._required_params(tool_name) if not arguments else []
        if missing:
            result = {
                "status": "error",
                "result": (
                    f"Your {tool_name} call arrived with no arguments at all, so it did not "
                    f"run and nothing was written. It requires: {', '.join(missing)}. "
                    "The arguments were most likely cut off before they were sent."
                    + (" " + _SPLIT_WRITE_ADVICE if tool_name in ("write", "edit") else "")
                ),
                "execution_time": 0,
            }
            logger.error(f"Tool {tool_name} called with no arguments (required: {missing})")
            self._record_tool_result(tool_name, arguments, False)
            return result

        # 权限门。每次调用单独判定，因此对话中途切换权限模式
        # 会立即作用于下一个工具调用。拒绝按普通工具错误呈现：
        # 模型能读到原因，既可以改走被允许的路径，
        # 也可以告诉用户该任务需要哪种权限模式。
        denial = self._permission_denial(tool_name, arguments)
        if denial:
            logger.info(f"🔐 Permission denied for tool {tool_name}: {denial}")
            result = {"status": "error", "result": denial, "execution_time": 0}
            self._emit_event("tool_execution_start", {
                "tool_call_id": tool_id,
                "tool_name": tool_name,
                "arguments": arguments,
            })
            # 将其标记为权限拒绝（而非普通工具错误），并附上
            # 当时生效的权限模式，以便 UI 能给出可操作的
            # “切换权限”提示，而不是笼统的失败信息。
            try:
                denied_mode = self.agent.effective_permission_mode()
            except Exception:
                denied_mode = None
            self._emit_event("tool_execution_end", {
                "tool_call_id": tool_id,
                "tool_name": tool_name,
                "permission_denied": True,
                "permission_mode": denied_mode,
                **result,
            })
            # 刻意不把拒绝计为工具故障：拒绝不代表
            # 工具行为异常，也不应计入会中止整个对话的
            # 连续失败次数。
            return result

        # 检查连续失败（重试保护）
        should_stop, stop_reason, is_critical = self._check_consecutive_failures(tool_name, arguments)
        if should_stop:
            logger.error(f"🛑 {stop_reason}")
            self._record_tool_result(tool_name, arguments, False)
            
            if is_critical:
                # 严重失败 - 中止整个对话
                result = {
                    "status": "critical_error",
                    "result": stop_reason,
                    "execution_time": 0
                }
            else:
                # 正常失败——让LLM尝试不同的方法
                result = {
                    "status": "error",
                    "result": f"{stop_reason}\n\n当前方法行不通，请尝试完全不同的方法或向用户询问更多信息。",
                    "execution_time": 0
                }
            return result

        tool = tool_override or self.tools.get(tool_name)
        start_event = {
            "tool_call_id": tool_id,
            "tool_name": tool_name,
            "arguments": arguments,
        }
        # 自行渲染卡片的调用不应再额外获得一张卡片，否则
        # 同一结果会在界面上出现两次。信任但也要验证：有的工具可能
        # 退回自己的处理流程——比如环境已关闭、参数越界——
        # 全程不发出任何事件，那么它的拒绝必须从其他途径呈现出来。
        own_cards = renders_own_cards(tool, arguments)
        emitted_own = False

        def emit_from_tool(event_type, data):
            nonlocal emitted_own
            if event_type == "tool_execution_start":
                emitted_own = True
            self._emit_event(event_type, data)

        if not own_cards:
            self._emit_event("tool_execution_start", start_event)

        try:
            if not tool:
                raise ValueError(self._build_tool_not_found_message(tool_name))

            # 设置工具上下文
            tool.model = self.model
            tool.context = self.agent
            tool.cancel_event = self.cancel_event
            tool.progress_callback = lambda message: self._emit_event(
                "tool_execution_progress",
                {
                    "tool_call_id": tool_id,
                    "tool_name": tool_name,
                    "message": message,
                }
            )
            tool.event_callback = emit_from_tool if own_cards else self._emit_event
            tool.tool_call_id = tool_id

            # 执行工具
            start_time = time.time()
            try:
                result: ToolResult = tool.execute_tool(arguments)
            finally:
                tool.progress_callback = None
                tool.cancel_event = None
                tool.event_callback = None
                tool.tool_call_id = None
            execution_time = time.time() - start_time

            result_dict = {
                "status": result.status,
                "result": result.result,
                "execution_time": execution_time
            }

            # 记录工具结果以进行故障跟踪
            success = result.status == "success"
            self._record_tool_result(tool_name, arguments, success)

            # 检测到创建技能后，自动刷新技能列表
            if tool_name == "bash" and result.status == "success":
                command = arguments.get("command", "")
                if "init_skill.py" in command and self.agent.skill_manager:
                    logger.info("Detected skill creation, refreshing skills...")
                    self.agent.refresh_skills()
                    logger.info(f"Skills refreshed! Now have {len(self.agent.skill_manager.skills)} skills")

            # `display` 只走事件通道：result_dict 才是模型读取的
            # tool_result，若再在那边渲染一遍同样的结果，
            # 只会白白消耗上下文。
            end_event = {"tool_call_id": tool_id, "tool_name": tool_name, **result_dict}
            if getattr(result, "display", None):
                end_event["display"] = result.display
            if not own_cards:
                self._emit_event("tool_execution_end", end_event)
            elif not emitted_own:
                self._emit_event("tool_execution_start", start_event)
                self._emit_event("tool_execution_end", end_event)

            return result_dict

        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            error_result = {
                "status": "error",
                "result": str(e),
                "execution_time": 0
            }
            # 记录失败
            self._record_tool_result(tool_name, arguments, False)

            # 该工具被信任会自行渲染卡片，随后却抛出了异常。
            # 它之前已经画出的内容如今悬在半空没有着落，因此
            # 再补一张说明出错原因的卡片是值得的。
            if own_cards:
                self._emit_event("tool_execution_start", start_event)
            self._emit_event("tool_execution_end", {
                "tool_call_id": tool_id,
                "tool_name": tool_name,
                **error_result
            })
            return error_result

    def _permission_denial(self, tool_name: str, arguments: Dict) -> Optional[str]:
        """Reason this call is not allowed, or None when it may run.

        Never raises: a broken permission check must not take the conversation
        down with it, so an error here falls through to the historical
        unrestricted behavior.
        """
        agent = self.agent
        if agent is None:
            return None
        try:
            from agent.permission import FULL_ACCESS, check_tool_call

            mode = agent.effective_permission_mode()
            if mode == FULL_ACCESS:
                return None
            decision = check_tool_call(
                mode,
                tool_name,
                arguments,
                cwd=agent.effective_cwd(),
                write_roots=agent.write_roots(),
            )
            return None if decision.allowed else decision.reason
        except Exception as e:
            logger.warning(f"[Permission] Check skipped for {tool_name}: {e}")
            return None

    def _build_tool_not_found_message(self, tool_name: str) -> str:
        """Build a helpful error message when a tool is not found.

        If a skill with the same name exists in skill_manager, read its
        SKILL.md and include the content so the LLM knows how to use it.
        """
        available_tools = list(self.tools.keys())
        base_msg = f"Tool '{tool_name}' not found. Available tools: {available_tools}"

        skill_manager = getattr(self.agent, 'skill_manager', None)
        if not skill_manager:
            return base_msg

        skill_entry = skill_manager.get_skill(tool_name)
        if not skill_entry:
            return base_msg

        skill = skill_entry.skill
        skill_md_path = skill.file_path
        skill_content = ""
        try:
            with open(skill_md_path, 'r', encoding='utf-8') as f:
                skill_content = f.read()
        except Exception:
            skill_content = skill.description

        logger.info(
            f"[Agent] Tool '{tool_name}' not found, but matched skill '{skill.name}'. "
            f"Guiding LLM to use the skill instead."
        )

        return (
            f"Tool '{tool_name}' is not a built-in tool, but a matching skill "
            f"'{skill.name}' is available. You should use existing tools (e.g. bash with curl) "
            f"to accomplish this task following the skill instructions below:\n\n"
            f"--- SKILL: {skill.name} (path: {skill_md_path}) ---\n"
            f"{skill_content}\n"
            f"--- END SKILL ---\n\n"
            f"Available tools: {available_tools}"
        )

    def _validate_and_fix_messages(self):
        """Delegate to the shared sanitizer (see message_sanitizer.py)."""
        sanitize_claude_messages(self.messages)

    def _identify_complete_turns(self) -> List[Dict]:
        """
        识别完整的对话轮次
        
        一个完整轮次包括：
        1. 用户消息（text）
        2. AI 回复（可能包含 tool_use）
        3. 工具结果（tool_result，如果有）
        4. 后续 AI 回复（如果有）
        
        Returns:
            List of turns, each turn is a dict with 'messages' list
        """
        return identify_complete_turns(self.messages)
    
    def _estimate_turn_tokens(self, turn: Dict) -> int:
        """估算一个轮次的 tokens"""
        return sum(
            self.agent._estimate_message_tokens(msg) 
            for msg in turn['messages']
        )

    def _truncate_historical_tool_results(self):
        """
        Truncate tool_result content in historical messages to reduce context size.

        Current turn results are kept at 30K chars (truncated at creation time).
        Historical turn results are further truncated to 10K chars here.
        This runs before token-based trimming so that we first shrink oversized
        results, potentially avoiding the need to drop entire turns.
        """
        MAX_HISTORY_RESULT_CHARS = 20000

        if len(self.messages) < 2:
            return

        # 定位最后一条用户文本消息的起始位置（即当前轮次的边界）
        # 跳过当前轮次的消息，以保留它们的完整内容
        current_turn_start = len(self.messages)
        for i in range(len(self.messages) - 1, -1, -1):
            msg = self.messages[i]
            if msg.get("role") == "user":
                content = msg.get("content", [])
                if isinstance(content, list) and any(
                    isinstance(b, dict) and b.get("type") == "text" for b in content
                ):
                    current_turn_start = i
                    break
                elif isinstance(content, str):
                    current_turn_start = i
                    break

        truncated_count = 0
        for i in range(current_turn_start):
            msg = self.messages[i]
            if msg.get("role") != "user":
                continue
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue

            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                result_str = block.get("content", "")
                if isinstance(result_str, str) and len(result_str) > MAX_HISTORY_RESULT_CHARS:
                    original_len = len(result_str)
                    block["content"] = result_str[:MAX_HISTORY_RESULT_CHARS] + \
                        f"\n\n[Historical output truncated: {original_len} -> {MAX_HISTORY_RESULT_CHARS} chars]"
                    truncated_count += 1

        if truncated_count > 0:
            logger.info(f"📎 Truncated {truncated_count} historical tool result(s) to {MAX_HISTORY_RESULT_CHARS} chars")

    # 解析形如 “...maximum context length is 1048576 tokens. However, you
    # requested 1276733 tokens (892733 in the messages, 384000 in the
    # completion)...” 的报错，从而以提供商上报的真实数字为重试目标，而不是靠猜测。
    _RE_OVERFLOW_LIMIT = re.compile(r"maximum context length is\s+(\d+)\s*tokens", re.I)
    _RE_OVERFLOW_COMPLETION = re.compile(r"(\d+)\s+in the completion", re.I)

    def _overflow_input_budget(self, error_str: str) -> int:
        """
        Compute the input-token budget to compact toward after an overflow.

        Prefer the concrete numbers the provider reported in the error
        ("maximum context length is X ... N in the completion"); fall back to
        the model window minus our output reserve. A 10% safety margin absorbs
        the gap between our estimate and the provider's real tokenizer.
        """
        window = self.agent._get_model_context_window()
        limit_match = self._RE_OVERFLOW_LIMIT.search(error_str or "")
        if limit_match:
            window = int(limit_match.group(1))

        completion = None
        comp_match = self._RE_OVERFLOW_COMPLETION.search(error_str or "")
        if comp_match:
            completion = int(comp_match.group(1))
        if completion is None:
            completion = self.agent._get_output_reserve_tokens()

        system_tokens = self.agent._estimate_message_tokens(
            {"role": "system", "content": self.system_prompt}
        )
        budget = int((window - completion - system_tokens) * 0.9)
        return max(2000, budget)

    def _smart_compact_to_budget(self, error_str: str) -> bool:
        """
        Compact the working context toward the provider's reported limit using
        the SAME smart strategy as the proactive _trim_messages, just repeated
        until the estimate fits:

          - Many turns (>= COMPRESS_THRESHOLD): discard the older half and flush
            them to daily memory + inject an LLM summary into the kept turns.
          - Few turns (< COMPRESS_THRESHOLD): compress every turn to text-only
            (strip tool chains, keep user query + final reply), never discard.

        Keeps at least the most recent turn so the user's latest request is not
        lost. Returns True if it reduced the context (worth retrying), else
        False (nothing left to shrink -> caller resets).
        """
        COMPRESS_THRESHOLD = 5

        input_budget = self._overflow_input_budget(error_str)
        original_count = len(self.messages)

        turns = self._identify_complete_turns()
        if not turns:
            return False

        current = sum(self._estimate_turn_tokens(t) for t in turns)
        logger.warning(
            f"🔄 Context overflow recovery: compacting toward ~{input_budget} "
            f"input tokens (currently ~{current} over {len(turns)} turns)"
        )

        # 反复应用智能策略，直到上下文放得下或无法再缩小为止。
        # 每次迭代中：当轮次足够多时，丢弃较旧的一半（并注入摘要）；
        # 否则把保留下来的轮次压缩成纯文本。
        guard = 0
        while turns and guard < 32:
            guard += 1
            current = sum(self._estimate_turn_tokens(t) for t in turns)
            if current <= input_budget:
                break

            if len(turns) >= COMPRESS_THRESHOLD:
                # 丢弃较旧的一半并生成摘要，与 _trim_messages 的做法保持一致。
                removed_count = len(turns) // 2
                discarded_turns = turns[:removed_count]
                kept_turns = turns[removed_count:]

                if self.agent.memory_manager:
                    discarded_messages = []
                    for turn in discarded_turns:
                        discarded_messages.extend(turn["messages"])
                    if discarded_messages:
                        user_id = getattr(self.agent, "_current_user_id", None)
                        cb = self._build_context_summary_callback(discarded_turns, kept_turns)
                        self.agent.memory_manager.flush_memory(
                            messages=discarded_messages, user_id=user_id,
                            reason="overflow", max_messages=0,
                            context_summary_callback=cb,
                        )
                turns = kept_turns
            else:
                # 轮次很少：把全部内容压缩成纯文本。若仍然放不下，
                # 就丢弃最旧的一轮，但始终保留最后一轮。
                compressed = []
                for t in turns:
                    c = compress_turn_to_text_only(t)
                    if c["messages"]:
                        compressed.append(c)
                if compressed and sum(self._estimate_turn_tokens(t) for t in compressed) < current:
                    turns = compressed
                elif len(turns) > 1:
                    turns = turns[1:]
                else:
                    # 即使压缩成纯文本、仅一个轮次仍会溢出——
                    # 这个策略已经无能为力了。
                    turns = compressed or turns
                    break

        new_messages = []
        for turn in turns:
            new_messages.extend(turn["messages"])

        if not new_messages or len(new_messages) >= original_count:
            # 无法缩减任何内容（单个超大轮次）→ 交由调用方重置。
            if not new_messages:
                logger.warning("🧹 Smart compaction produced no messages, will clear history")
                return False
            if len(new_messages) >= original_count:
                logger.warning("🧹 Smart compaction could not reduce the context, will clear history")
                return False

        self.messages[:] = new_messages
        new_tokens = sum(self._estimate_turn_tokens(t) for t in turns)
        logger.info(
            f"🔄 Smart compaction: {original_count} -> {len(self.messages)} messages "
            f"(~{new_tokens} tokens, target ~{input_budget})"
        )
        return True

    def _build_context_summary_callback(self, discarded_turns: list, kept_turns: list):
        """
        Build a callback that injects an LLM summary into the first user
        message of *kept_turns*. Returns None if no valid injection target.

        The callback is passed to flush_from_messages so that the same LLM
        call that writes daily memory also provides the in-context summary.
        """
        if not kept_turns:
            return None

        # 在 kept_turns 中寻找第一个用户文本块，作为摘要的注入目标
        target_block = find_first_user_text_block(kept_turns)
        if not target_block:
            return None

        turn_count = len(discarded_turns)
        original_text = target_block["text"]

        def _on_summary_ready(summary: str):
            if not summary or not summary.strip():
                return
            target_block["text"] = build_compaction_summary_text(
                summary, turn_count, original_text
            )
            logger.info(
                f"📝 Context summary injected "
                f"({len(summary)} chars, {turn_count} turns)"
            )

        return _on_summary_ready

    def _trim_messages(self):
        """
        智能清理消息历史，保持对话完整性

        使用完整轮次作为清理单位，确保：
        1. 不会在对话中间截断
        2. 工具调用链（tool_use + tool_result）保持完整
        3. 每轮对话都是完整的（用户消息 + AI回复 + 工具调用）
        """
        if not self.messages or not self.agent:
            return

        # 步骤 0：截断历史轮次中的大型工具结果 (30K -> 10K)
        self._truncate_historical_tool_results()

        # 步骤 1：识别完整轮次
        turns = self._identify_complete_turns()
        
        if not turns:
            return
        
        # 步骤 2：轮次限制——超限时移除前一半，保留后一半
        if len(turns) > self.max_context_turns:
            removed_count = len(turns) // 2
            keep_count = len(turns) - removed_count
            
            discarded_turns = turns[:removed_count]
            turns = turns[-keep_count:]

            logger.info(
                f"💾 Context turns exceeded: {keep_count + removed_count} > {self.max_context_turns}, "
                f"trimmed to {keep_count} turns (removed {removed_count})"
            )

            # 刷入日常记忆，并注入上下文摘要（通过一次异步 LLM 调用完成）
            if self.agent.memory_manager:
                discarded_messages = []
                for turn in discarded_turns:
                    discarded_messages.extend(turn["messages"])
                if discarded_messages:
                    user_id = getattr(self.agent, '_current_user_id', None)
                    cb = self._build_context_summary_callback(discarded_turns, turns)
                    self.agent.memory_manager.flush_memory(
                        messages=discarded_messages, user_id=user_id,
                        reason="trim", max_messages=0,
                        context_summary_callback=cb,
                    )

        # 步骤 3：token 限制——按完整轮次保留
        # 从代理获取上下文窗口（基于模型）
        context_window = self.agent._get_model_context_window()

        # 上下文窗口由提示与补全共用。务必让输入预算
        # 始终低于（窗口 − 输出预留），这样完整的提示加上
        # 提供商默认的补全预算，就不会撑爆窗口、也不会触发
        # “maximum context length ... you requested N tokens” 的 400
        # （否则会陷入死循环），哪怕用户配置了
        # 很大的 agent_max_context_tokens 也一样。
        output_reserve = self.agent._get_output_reserve_tokens()
        input_ceiling = max(1, context_window - output_reserve)

        # 若配置了 max_context_tokens 就采用它，但绝不能高于
        # 输入上限，要为补全预留空间。
        if hasattr(self.agent, 'max_context_tokens') and self.agent.max_context_tokens:
            max_tokens = min(self.agent.max_context_tokens, input_ceiling)
        else:
            max_tokens = input_ceiling

        # 估算系统提示占用的 token 数
        system_tokens = self.agent._estimate_message_tokens({"role": "system", "content": self.system_prompt})
        available_tokens = max_tokens - system_tokens

        # 统计当前各轮占用的 token 数
        current_tokens = sum(self._estimate_turn_tokens(turn) for turn in turns)
        
        # 若未超过限制，则重建消息并返回
        if current_tokens + system_tokens <= max_tokens:
            # 由各轮次重建消息列表
            new_messages = []
            for turn in turns:
                new_messages.extend(turn['messages'])
            
            old_count = len(self.messages)
            self.messages = new_messages
            
            # 记录我们是否因回合限制而删除消息
            if old_count > len(self.messages):
                logger.info(f"   Rebuilt message list: {old_count} -> {len(self.messages)} messages")
            return

        # 超过 token 上限——按轮次数分层的策略：
        #
        #   轮次很少（<5）：把所有轮次压缩成纯文本（剥除工具链，
        #                    保留用户提问 + 最终回复）。绝不要丢弃轮次
        #                    ——上下文本来就单薄时，丢掉任何一轮都太伤。
        #
        #   轮次较多（>=5）：直接丢弃前一半轮次。
        #                     轮次足够多时，最旧的几轮价值较低，
        #                     而完整保留较新的一半
        #                     （含完整工具链）更有用。

        COMPRESS_THRESHOLD = 5

        if len(turns) < COMPRESS_THRESHOLD:
            # --- 几轮：将所有轮压缩为纯文本，切勿丢弃 ---
            compressed_turns = []
            for t in turns:
                compressed = compress_turn_to_text_only(t)
                if compressed["messages"]:
                    compressed_turns.append(compressed)

            new_messages = []
            for turn in compressed_turns:
                new_messages.extend(turn["messages"])

            new_tokens = sum(self._estimate_turn_tokens(t) for t in compressed_turns)
            old_count = len(self.messages)
            self.messages = new_messages

            logger.info(
                f"📦 Context tokens exceeded (turns<{COMPRESS_THRESHOLD}): "
                f"~{current_tokens + system_tokens} > {max_tokens}, "
                f"compressed all {len(turns)} turns to plain text "
                f"({old_count} -> {len(self.messages)} messages, "
                f"~{current_tokens + system_tokens} -> ~{new_tokens + system_tokens} tokens)"
            )
            return

        # --- 许多回合（>=5）：丢弃较旧的一半，保留较新的一半 ---
        removed_count = len(turns) // 2
        keep_count = len(turns) - removed_count
        discarded_turns = turns[:removed_count]
        kept_turns = turns[-keep_count:]
        kept_tokens = sum(self._estimate_turn_tokens(t) for t in kept_turns)

        logger.info(
            f"🔄 Context tokens exceeded: ~{current_tokens + system_tokens} > {max_tokens}, "
            f"trimmed to {keep_count} turns (removed {removed_count})"
        )

        if self.agent.memory_manager:
            discarded_messages = []
            for turn in discarded_turns:
                discarded_messages.extend(turn["messages"])
            if discarded_messages:
                user_id = getattr(self.agent, '_current_user_id', None)
                cb = self._build_context_summary_callback(discarded_turns, kept_turns)
                self.agent.memory_manager.flush_memory(
                    messages=discarded_messages, user_id=user_id,
                    reason="trim", max_messages=0,
                    context_summary_callback=cb,
                )

        new_messages = []
        for turn in kept_turns:
            new_messages.extend(turn['messages'])

        old_count = len(self.messages)
        self.messages = new_messages

        logger.info(
            f"   Removed {removed_count} turns "
            f"({old_count} -> {len(self.messages)} messages, "
            f"~{current_tokens + system_tokens} -> ~{kept_tokens + system_tokens} tokens)"
        )

    def _prepare_messages(self) -> List[Dict[str, Any]]:
        """
        Prepare messages to send to LLM
        
        Note: For Claude API, system prompt should be passed separately via system parameter,
        not as a message. The AgentLLMModel will handle this.
        """
        # 不要在此处添加系统消息 - 它将由 LLM 适配器单独处理
        return self.messages
