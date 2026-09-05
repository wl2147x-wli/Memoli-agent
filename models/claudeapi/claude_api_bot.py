# 编码：utf-8

import base64
import json
import re
import time
from typing import Optional

import requests

from models.baidu.baidu_wenxin_session import BaiduWenxinSession
from models.bot import Bot
from models.session_manager import SessionManager
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common import const
from common.log import logger
from config import conf

# 可选的 OpenAI 图像支持
try:
    from models.openai.open_ai_image import OpenAIImage
    _openai_image_available = True
except Exception as e:
    logger.warning(f"OpenAI image support not available: {e}")
    _openai_image_available = False
    OpenAIImage = object  # 回退到对象

user_session = dict()

# Anthropic 提供了两种互斥的“思维控制”方式：第 4.6 代及更新版本
# 只接受 ``adaptive``（强度由 ``output_config.effort`` 决定），并拒绝
# ``enabled``；第 4.5 代及更早版本只接受 ``enabled``，并要求显式提供
# ``budget_tokens``，同时拒绝 ``adaptive``。
ADAPTIVE_THINKING_MODELS = (
    "claude-fable-5-1",
    "claude-fable-5",
    "claude-mythos-5",
    "claude-mythos-preview",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
)

# 仅采用 ``enabled`` + ``budget_tokens`` 形式的模型。检查后
# ADAPTIVE_THINKING_MODELS，因为 4.6 代名称共享这些前缀。
BUDGET_THINKING_MODELS = (
    "claude-3-7",
    "claude-opus-4",
    "claude-sonnet-4",
    "claude-haiku-4",
)

# 遗留预算的上限，因此较大的 max_tokens 不会许可
# 无界思维通行证。
MAX_THINKING_BUDGET = 16000


# OpenAI对话模型API (可用)
class ClaudeAPIBot(Bot, OpenAIImage):
    def __init__(self):
        super().__init__()
        self.sessions = SessionManager(BaiduWenxinSession, model=conf().get("model") or "text-davinci-003")

    @property
    def api_key(self):
        return conf().get("claude_api_key")

    @property
    def api_base(self):
        return conf().get("claude_api_base") or "https://api.anthropic.com/v1"

    @property
    def proxy(self):
        return conf().get("proxy", None)

    def reply(self, query, context=None):
        # 获取回复内容
        if context and context.type:
            if context.type == ContextType.TEXT:
                logger.info("[CLAUDE_API] query={}".format(query))
                session_id = context["session_id"]
                reply = None
                if query == "#清除记忆":
                    self.sessions.clear_session(session_id)
                    reply = Reply(ReplyType.INFO, "记忆已清除")
                elif query == "#清除所有":
                    self.sessions.clear_all_session()
                    reply = Reply(ReplyType.INFO, "所有人记忆已清除")
                else:
                    session = self.sessions.session_query(query, session_id)
                    result = self.reply_text(session)
                    logger.info(result)
                    total_tokens, completion_tokens, reply_content = (
                        result["total_tokens"],
                        result["completion_tokens"],
                        result["content"],
                    )
                    logger.debug(
                        "[CLAUDE_API] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(str(session), session_id, reply_content, completion_tokens)
                    )

                    if total_tokens == 0:
                        reply = Reply(ReplyType.ERROR, reply_content)
                    else:
                        self.sessions.session_reply(reply_content, session_id, total_tokens)
                        reply = Reply(ReplyType.TEXT, reply_content)
                return reply
            elif context.type == ContextType.IMAGE_CREATE:
                ok, retstring = self.create_img(query, 0)
                reply = None
                if ok:
                    reply = Reply(ReplyType.IMAGE_URL, retstring)
                else:
                    reply = Reply(ReplyType.ERROR, retstring)
                return reply

    def reply_text(self, session: BaiduWenxinSession, retry_count=0, tools=None):
        try:
            actual_model = self._model_mapping(conf().get("model"))

            # 准备请求头
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }

            # 提取系统提示（如果存在）并准备克劳德兼容的消息
            system_prompt = conf().get("character_desc", "")
            claude_messages = []

            for msg in session.messages:
                if msg.get("role") == "system":
                    system_prompt = msg["content"]
                else:
                    claude_messages.append(msg)

            # 准备请求数据
            data = {
                "model": actual_model,
                "messages": claude_messages,
                "max_tokens": self._get_max_tokens(actual_model)
            }

            if system_prompt:
                data["system"] = system_prompt

            if tools:
                data["tools"] = tools

            # 发出 HTTP 请求
            proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
            response = requests.post(
                f"{self.api_base}/messages",
                headers=headers,
                json=data,
                proxies=proxies
            )

            if response.status_code != 200:
                raise Exception(f"API request failed: {response.status_code} - {response.text}")

            claude_response = response.json()
            # 处理响应内容和工具调用
            res_content = ""
            tool_calls = []

            content_blocks = claude_response.get("content", [])
            for block in content_blocks:
                if block.get("type") == "text":
                    res_content += block.get("text", "")
                elif block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "arguments": block.get("input", {})
                    })

            res_content = res_content.strip().replace("<|endoftext|>", "")
            usage = claude_response.get("usage", {})
            total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            completion_tokens = usage.get("output_tokens", 0)

            logger.info("[CLAUDE_API] reply={}".format(res_content))
            if tool_calls:
                logger.info("[CLAUDE_API] tool_calls={}".format(tool_calls))

            result = {
                "total_tokens": total_tokens,
                "completion_tokens": completion_tokens,
                "content": res_content,
            }

            if tool_calls:
                result["tool_calls"] = tool_calls

            return result
        except Exception as e:
            need_retry = retry_count < 2
            result = {"total_tokens": 0, "completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}

            # 处理不同类型的错误
            error_str = str(e).lower()
            if "rate" in error_str or "limit" in error_str:
                logger.warn("[CLAUDE_API] RateLimitError: {}".format(e))
                result["content"] = "提问太快啦，请休息一下再问我吧"
                if need_retry:
                    time.sleep(20)
            elif "timeout" in error_str:
                logger.warn("[CLAUDE_API] Timeout: {}".format(e))
                result["content"] = "我没有收到你的消息"
                if need_retry:
                    time.sleep(5)
            elif "connection" in error_str or "network" in error_str:
                logger.warn("[CLAUDE_API] APIConnectionError: {}".format(e))
                need_retry = False
                result["content"] = "我连接不到你的网络"
            else:
                logger.warn("[CLAUDE_API] Exception: {}".format(e))
                need_retry = False
                self.sessions.clear_session(session.session_id)

            if need_retry:
                logger.warn("[CLAUDE_API] 第{}次重试".format(retry_count + 1))
                return self.reply_text(session, retry_count + 1, tools)
            else:
                return result

    def _model_mapping(self, model) -> str:
        if model == "claude-3-opus":
            return const.CLAUDE_3_OPUS
        elif model == "claude-3-sonnet":
            return const.CLAUDE_3_SONNET
        elif model == "claude-3-haiku":
            return const.CLAUDE_3_HAIKU
        elif model == "claude-3.5-sonnet":
            return const.CLAUDE_35_SONNET
        return model

    def _get_max_tokens(self, model: str) -> int:
        """
        Get max_tokens for the model.
        Reference from pi-mono:
        - Claude 3.5/3.7: 8192
        - Claude 3 Opus: 4096
        - Default: 8192
        """
        if model and (model.startswith("claude-3-5") or model.startswith("claude-3-7")):
            return 8192
        elif model and model.startswith("claude-3") and "opus" in model:
            return 4096
        elif model and (model.startswith("claude-sonnet-4") or model.startswith("claude-sonnet-5")
                         or model.startswith("claude-opus-4") or model.startswith("claude-opus-5")
                         or model.startswith("claude-fable")):
            return 64000
        return 8192

    @staticmethod
    def _thinking_params(model: str, thinking: object, max_tokens: int) -> Optional[dict]:
        """Translate the generic thinking toggle into this model's native shape.

        ``display`` must be requested explicitly: without it the API returns
        thinking blocks whose ``thinking`` field is empty, carrying only a
        signature. Returns ``None`` whenever a valid config cannot be built —
        including for models with no thinking support at all — so the request
        goes out without the field rather than being rejected.
        """
        if not isinstance(thinking, dict):
            return None

        lowered = (model or "").lower()
        adaptive = lowered.startswith(ADAPTIVE_THINKING_MODELS)
        if not adaptive and not lowered.startswith(BUDGET_THINKING_MODELS):
            return None

        if adaptive:
            # 仅自适应模型拒绝“`thinking.type: disabled`”。当
            # 调用者要求禁用思考，完全省略该字段（API
            # 那么默认为自适应）而不是发送不支持的值。
            if thinking.get("type") == "disabled":
                return None
            return {"type": "adaptive", "display": "summarized"}
        if thinking.get("type") == "disabled":
            return {"type": "disabled"}

        # 旧型号需要至少 1024 的预算，并保持在以下水平
        # max_tokens，因为思考令牌计入相同的限制。
        if not isinstance(max_tokens, int):
            return None
        budget = min(max_tokens // 4, MAX_THINKING_BUDGET, max_tokens - 1)
        if budget < 1024:
            return None
        return {"type": "enabled", "budget_tokens": budget}

    @staticmethod
    def _parse_data_url(data_url: str):
        """Parse a data:<mime>;base64,<data> URL into (media_type, base64_data)."""
        m = re.match(r"^data:([^;]+);base64,(.+)$", data_url, re.DOTALL)
        if m:
            return m.group(1), m.group(2)
        return None, None

    def call_vision(self, image_url: str, question: str,
                    model: Optional[str] = None,
                    max_tokens: int = 1000) -> dict:
        """Analyze an image using Claude Messages API (native image blocks)."""
        try:
            actual_model = model or self._model_mapping(conf().get("model"))

            # 构建 Claude 原生图像内容块
            if image_url.startswith("data:"):
                media_type, b64_data = self._parse_data_url(image_url)
                if not b64_data:
                    return {"error": True, "message": "Invalid base64 data URL"}
                image_block = {
                    "type": "image",
                    "source": {"type": "base64",
                               "media_type": media_type or "image/jpeg",
                               "data": b64_data},
                }
            else:
                image_block = {
                    "type": "image",
                    "source": {"type": "url", "url": image_url},
                }

            data = {
                "model": actual_model,
                "max_tokens": max_tokens,
                "messages": [{
                    "role": "user",
                    "content": [
                        image_block,
                        {"type": "text", "text": question},
                    ],
                }],
            }

            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
            resp = requests.post(f"{self.api_base}/messages",
                                 headers=headers, json=data, proxies=proxies)

            if resp.status_code != 200:
                return {"error": True, "message": f"HTTP {resp.status_code}: {resp.text[:300]}"}

            body = resp.json()
            text_parts = [b.get("text", "") for b in body.get("content", [])
                          if b.get("type") == "text"]
            usage = body.get("usage", {})
            return {
                "model": actual_model,
                "content": "".join(text_parts),
                "usage": {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                },
            }
        except Exception as e:
            logger.error(f"[CLAUDE] call_vision error: {e}")
            return {"error": True, "message": str(e)}

    def call_with_tools(self, messages, tools=None, stream=False, **kwargs):
        """
        Call Claude API with tool support for agent integration

        Args:
            messages: List of messages
            tools: List of tool definitions
            stream: Whether to use streaming
            **kwargs: Additional parameters
            
        Returns:
            Formatted response compatible with OpenAI format or generator for streaming
        """
        # 每个会话模型覆盖以 kwargs["model"] 形式到达（请参阅
        # AgentLLMModel.call_stream）。比全局配置更喜欢它，所以
        # 一聊切换模型实际上到达了API；否则
        # 固定到另一个提供商的模型的会话将发送到这里
        # 错误的（全局）型号名称。
        actual_model = self._model_mapping(kwargs.get("model") or conf().get("model"))

        # 从消息中提取系统提示（如果存在）
        system_prompt = kwargs.get("system", conf().get("character_desc", ""))
        claude_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg["content"]
            else:
                claude_messages.append(self._sanitize_message(msg))

        request_params = {
            "model": actual_model,
            "max_tokens": kwargs.get("max_tokens", self._get_max_tokens(actual_model)),
            "messages": claude_messages,
            "stream": stream
        }

        if system_prompt:
            request_params["system"] = system_prompt

        if tools:
            request_params["tools"] = tools

        # 克劳德公开了在output_config下的努力，而不是通用的
        # OpenAI 兼容提供商使用的 Reasoning_effort 字段。
        output_config = dict(kwargs.get("output_config") or {})
        reasoning_effort = kwargs.get("reasoning_effort")
        if reasoning_effort:
            output_config["effort"] = reasoning_effort
        if output_config:
            request_params["output_config"] = output_config

        thinking_params = self._thinking_params(
            actual_model, kwargs.get("thinking"), request_params["max_tokens"]
        )
        if thinking_params:
            request_params["thinking"] = thinking_params

        try:
            if stream:
                return self._handle_stream_response(request_params)
            else:
                return self._handle_sync_response(request_params)
        except Exception as e:
            logger.error(f"Claude API call error: {e}")
            if stream:
                # 返回流的错误生成器
                def error_generator():
                    yield {
                        "error": True,
                        "message": str(e),
                        "status_code": 500
                    }

                return error_generator()
            else:
                # 返回同步错误响应
                return {
                    "error": True,
                    "message": str(e),
                    "status_code": 500
                }

    @staticmethod
    def _sanitize_message(msg: dict) -> dict:
        """Strip thinking blocks without a ``signature`` from assistant messages.

        When the session switches from another model (e.g. MiniMax) to Claude,
        the in-memory history may contain thinking blocks that lack the
        ``signature`` field required by the Anthropic API, causing 400 errors.
        We create a shallow copy so the original history is not mutated.
        """
        if msg.get("role") != "assistant":
            return msg
        content = msg.get("content")
        if not isinstance(content, list):
            return msg
        cleaned = [
            block for block in content
            if not (isinstance(block, dict)
                    and block.get("type") == "thinking"
                    and "signature" not in block)
        ]
        if len(cleaned) == len(content):
            return msg
        return {**msg, "content": cleaned}

    def _handle_sync_response(self, request_params):
        """Handle synchronous Claude API response"""
        # 准备请求头
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        # 发出 HTTP 请求
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        response = requests.post(
            f"{self.api_base}/messages",
            headers=headers,
            json=request_params,
            proxies=proxies
        )

        if response.status_code != 200:
            raise Exception(f"API request failed: {response.status_code} - {response.text}")

        claude_response = response.json()

        # 提取内容块
        text_content = ""
        reasoning_content = ""
        tool_calls = []

        content_blocks = claude_response.get("content", [])
        for block in content_blocks:
            if block.get("type") == "text":
                text_content += block.get("text", "")
            elif block.get("type") == "thinking":
                reasoning_content += block.get("thinking", "")
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {}))
                    }
                })

        # 以 OpenAI 格式构建消息
        message = {
            "role": "assistant",
            "content": text_content
        }
        if reasoning_content:
            message["reasoning_content"] = reasoning_content
        if tool_calls:
            message["tool_calls"] = tool_calls

        # 格式化响应以匹配 OpenAI 结构
        usage = claude_response.get("usage", {})
        formatted_response = {
            "id": claude_response.get("id", ""),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": claude_response.get("model", request_params["model"]),
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": claude_response.get("stop_reason", "stop")
                }
            ],
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            }
        }

        return formatted_response

    def _handle_stream_response(self, request_params):
        """Handle streaming Claude API response using HTTP requests"""
        # 准备请求头
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        # 添加流参数
        request_params["stream"] = True

        # 跟踪工具使用状态
        tool_uses_map = {}  # {索引：{id，名称，输入}}
        current_tool_use_index = -1
        stop_reason = None  # 克劳德追踪停止原因

        try:
            # 发出流式 HTTP 请求
            proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
            response = requests.post(
                f"{self.api_base}/messages",
                headers=headers,
                json=request_params,
                proxies=proxies,
                stream=True
            )

            if response.status_code != 200:
                error_text = response.text
                try:
                    error_data = json.loads(error_text)
                    error_msg = error_data.get("error", {}).get("message", error_text)
                except Exception:
                    error_msg = error_text or "Unknown error"

                yield {
                    "error": True,
                    "status_code": response.status_code,
                    "message": error_msg
                }
                return

            # 处理流式响应
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        line = line[6:]  # 删除“数据：”前缀
                        if line == '[DONE]':
                            break
                        try:
                            event = json.loads(line)
                            event_type = event.get("type")

                            if event_type == "content_block_start":
                                # 新内容块
                                block = event.get("content_block", {})
                                if block.get("type") == "tool_use":
                                    current_tool_use_index = event.get("index", 0)
                                    tool_uses_map[current_tool_use_index] = {
                                        "id": block.get("id", ""),
                                        "name": block.get("name", ""),
                                        "input": ""
                                    }

                            elif event_type == "content_block_delta":
                                delta = event.get("delta", {})
                                delta_type = delta.get("type")

                                if delta_type == "thinking_delta":
                                    thinking_text = delta.get("thinking", "")
                                    if thinking_text:
                                        yield {
                                            "choices": [{
                                                "index": 0,
                                                "delta": {
                                                    "role": "assistant",
                                                    "reasoning_content": thinking_text
                                                },
                                                "finish_reason": None
                                            }]
                                        }

                                elif delta_type == "text_delta":
                                    content = delta.get("text", "")
                                    yield {
                                        "id": event.get("id", ""),
                                        "object": "chat.completion.chunk",
                                        "created": int(time.time()),
                                        "model": request_params["model"],
                                        "choices": [{
                                            "index": 0,
                                            "delta": {"content": content},
                                            "finish_reason": None
                                        }]
                                    }

                                elif delta_type == "input_json_delta":
                                    # 工具输入累积
                                    if current_tool_use_index >= 0:
                                        tool_uses_map[current_tool_use_index]["input"] += delta.get("partial_json", "")

                            elif event_type == "message_delta":
                                # 从增量中提取 stop_reason
                                delta = event.get("delta", {})
                                if "stop_reason" in delta:
                                    stop_reason = delta.get("stop_reason")
                                    logger.info(f"[Claude] Stream stop_reason: {stop_reason}")
                                
                                # 消息完成 - 产量工具调用（如果有）
                                if tool_uses_map:
                                    for idx in sorted(tool_uses_map.keys()):
                                        tool_data = tool_uses_map[idx]
                                        yield {
                                            "id": event.get("id", ""),
                                            "object": "chat.completion.chunk",
                                            "created": int(time.time()),
                                            "model": request_params["model"],
                                            "choices": [{
                                                "index": 0,
                                                "delta": {
                                                    "tool_calls": [{
                                                        "index": idx,
                                                        "id": tool_data["id"],
                                                        "type": "function",
                                                        "function": {
                                                            "name": tool_data["name"],
                                                            "arguments": tool_data["input"]
                                                        }
                                                    }]
                                                },
                                                "finish_reason": stop_reason
                                            }]
                                        }
                            
                            elif event_type == "message_stop":
                                # 最终事件 - 日志完成
                                logger.debug(f"[Claude] Stream completed with stop_reason: {stop_reason}")

                        except json.JSONDecodeError:
                            continue

        except requests.RequestException as e:
            logger.error(f"Claude streaming request error: {e}")
            yield {
                "error": True,
                "message": f"Connection error: {str(e)}",
                "status_code": 0
            }
        except Exception as e:
            logger.error(f"Claude streaming error: {e}")
            yield {
                "error": True,
                "message": str(e),
                "status_code": 500
            }
