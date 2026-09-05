# 编码：utf-8

import json
from typing import Optional

from models.bot import Bot
from models.session_manager import SessionManager
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf, load_config
from .dashscope_session import DashscopeSession
import os
import dashscope
from dashscope import MultiModalConversation
from http import HTTPStatus



# 旧版 dashscope SDK 常量的旧模型名称映射。
# 新模型不需要在这里添加——它们直接使用它们的名称字符串。
dashscope_models = {
    "qwen-turbo": dashscope.Generation.Models.qwen_turbo,
    "qwen-plus": dashscope.Generation.Models.qwen_plus,
    "qwen-max": dashscope.Generation.Models.qwen_max,
    "qwen-bailian-v1": dashscope.Generation.Models.bailian_v1,
}

# 需要 MultiModalConversation API 而不是 Generation API 的模型名称前缀。
# Qwen3.5+omni/max系列仅接受多模态生成端点；
# 调用文本生成端点返回“url error”。 qwen3.8-max是1
# 其中 - 所有官方示例都使用 MultiModalConversation.call。
MULTIMODAL_MODEL_PREFIXES = ("qwen3.5-", "qwen3.6-", "qwen3.7-plus", "qwen3.8-")


# Qwen对话模型API
class DashscopeBot(Bot):
    def __init__(self):
        super().__init__()
        self.sessions = SessionManager(DashscopeSession, model=conf().get("model") or "qwen3.7-plus")
        self.model_name = conf().get("model") or "qwen3.7-plus"
        self.client = dashscope.Generation
        api_key = conf().get("dashscope_api_key")
        if api_key:
            os.environ["DASHSCOPE_API_KEY"] = api_key
        self._apply_base_url()

    @property
    def api_key(self):
        return conf().get("dashscope_api_key")

    @staticmethod
    def _apply_base_url():
        """Apply the configured DashScope base URL to the SDK global.

        The DashScope SDK only honors ``dashscope.base_http_api_url`` (there is
        no per-call base_url arg). ``dashscope_api_base`` is exposed in config /
        the ``DASHSCOPE_API_BASE`` env var, so we must push it into the SDK here.
        When unset we leave the SDK default (public endpoint) untouched.

        Note: a custom base URL that points at a Bailian *dedicated deployment*
        endpoint (``*.maas.aliyuncs.com``) will only accept that deployment's
        own model id — calling it with a public model name (e.g. ``qwen3.8-max``)
        returns ``InvalidParameter - url error``. Leave this empty to use public
        models.
        """
        api_base = conf().get("dashscope_api_base")
        if api_base:
            dashscope.base_http_api_url = api_base

    @staticmethod
    def _is_multimodal_model(model_name: str) -> bool:
        """Check if the model requires MultiModalConversation API"""
        return model_name.startswith(MULTIMODAL_MODEL_PREFIXES)

    def reply(self, query, context=None):
        # 获取回复内容
        if context.type == ContextType.TEXT:
            logger.info("[DASHSCOPE] query={}".format(query))

            session_id = context["session_id"]
            reply = None
            clear_memory_commands = conf().get("clear_memory_commands", ["#清除记忆"])
            if query in clear_memory_commands:
                self.sessions.clear_session(session_id)
                reply = Reply(ReplyType.INFO, "记忆已清除")
            elif query == "#清除所有":
                self.sessions.clear_all_session()
                reply = Reply(ReplyType.INFO, "所有人记忆已清除")
            elif query == "#更新配置":
                load_config()
                reply = Reply(ReplyType.INFO, "配置已更新")
            if reply:
                return reply
            session = self.sessions.session_query(query, session_id)
            logger.debug("[DASHSCOPE] session query={}".format(session.messages))

            reply_content = self.reply_text(session)
            logger.debug(
                "[DASHSCOPE] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(
                    session.messages,
                    session_id,
                    reply_content["content"],
                    reply_content["completion_tokens"],
                )
            )
            if reply_content["completion_tokens"] == 0 and len(reply_content["content"]) > 0:
                reply = Reply(ReplyType.ERROR, reply_content["content"])
            elif reply_content["completion_tokens"] > 0:
                self.sessions.session_reply(reply_content["content"], session_id, reply_content["total_tokens"])
                reply = Reply(ReplyType.TEXT, reply_content["content"])
            else:
                reply = Reply(ReplyType.ERROR, reply_content["content"])
                logger.debug("[DASHSCOPE] reply {} used 0 tokens.".format(reply_content))
            return reply
        else:
            reply = Reply(ReplyType.ERROR, "Bot不支持处理{}类型的消息".format(context.type))
            return reply

    def reply_text(self, session: DashscopeSession, retry_count=0) -> dict:
        """
        call openai's ChatCompletion to get the answer
        :param session: a conversation session
        :param session_id: session id
        :param retry_count: retry count
        :return: {}
        """
        try:
            dashscope.api_key = self.api_key
            self._apply_base_url()
            model = dashscope_models.get(self.model_name, self.model_name)
            if self._is_multimodal_model(self.model_name):
                mm_messages = self._prepare_messages_for_multimodal(session.messages)
                response = MultiModalConversation.call(
                    model=model,
                    messages=mm_messages,
                    result_format="message"
                )
            else:
                response = self.client.call(
                    model,
                    messages=session.messages,
                    result_format="message"
                )
            if response.status_code == HTTPStatus.OK:
                resp_dict = self._response_to_dict(response)
                choice = resp_dict["output"]["choices"][0]
                content = choice.get("message", {}).get("content", "")
                # 多模式模型可能会以块列表的形式返回内容
                if isinstance(content, list):
                    content = "".join(
                        item.get("text", "") for item in content if isinstance(item, dict)
                    )
                usage = resp_dict.get("usage", {})
                return {
                    "total_tokens": usage.get("total_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "content": content,
                }
            else:
                logger.error('Request id: %s, Status code: %s, error code: %s, error message: %s' % (
                    response.request_id, response.status_code,
                    response.code, response.message
                ))
                result = {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}
                need_retry = retry_count < 2
                result = {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}
                if need_retry:
                    return self.reply_text(session, retry_count + 1)
                else:
                    return result
        except Exception as e:
            logger.exception(e)
            need_retry = retry_count < 2
            result = {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}
            if need_retry:
                return self.reply_text(session, retry_count + 1)
            else:
                return result

    def call_vision(self, image_url: str, question: str,
                    model: Optional[str] = None,
                    max_tokens: int = 1000) -> dict:
        """Analyze an image using DashScope MultiModalConversation API."""
        try:
            dashscope.api_key = self.api_key
            self._apply_base_url()
            vision_model = model or "qwen-vl-max"

            # DashScope 多模式格式：{"image": url} + {"text": Question}
            messages = [{
                "role": "user",
                "content": [
                    {"image": image_url},
                    {"text": question},
                ],
            }]

            response = MultiModalConversation.call(
                model=vision_model,
                messages=messages,
                max_tokens=max_tokens,
            )

            if response.status_code != HTTPStatus.OK:
                return {
                    "error": True,
                    "message": f"{response.code} - {response.message}",
                }

            resp_dict = self._response_to_dict(response)
            choice = resp_dict["output"]["choices"][0]
            content = choice.get("message", {}).get("content", "")
            if isinstance(content, list):
                content = "".join(
                    item.get("text", "") for item in content if isinstance(item, dict)
                )
            usage = resp_dict.get("usage", {})
            return {
                "model": vision_model,
                "content": content,
                "usage": {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
            }
        except Exception as e:
            logger.error(f"[DASHSCOPE] call_vision error: {e}")
            return {"error": True, "message": str(e)}

    def call_with_tools(self, messages, tools=None, stream=False, **kwargs):
        """
        Call DashScope API with tool support for agent integration
        
        This method handles:
        1. Format conversion (Claude format → DashScope format)
        2. System prompt injection
        3. API calling with DashScope SDK
        4. Thinking mode support (enable_thinking for Qwen3)
        
        Args:
            messages: List of messages (may be in Claude format from agent)
            tools: List of tool definitions (may be in Claude format from agent)
            stream: Whether to use streaming
            **kwargs: Additional parameters (max_tokens, temperature, system, etc.)
            
        Returns:
            Formatted response or generator for streaming
        """
        try:
            # 将消息从 Claude 格式转换为 DashScope 格式
            messages = self._convert_messages_to_dashscope_format(messages)
            
            # 将工具从 Claude 格式转换为 DashScope 格式
            if tools:
                tools = self._convert_tools_to_dashscope_format(tools)
            
            # 处理系统提示
            system_prompt = kwargs.get('system')
            if system_prompt:
                # 如果系统消息尚不存在，请在开头添加
                if not messages or messages[0].get('role') != 'system':
                    messages = [{"role": "system", "content": system_prompt}] + messages
                else:
                    # 替换现有的系统消息
                    messages[0] = {"role": "system", "content": system_prompt}
            
            # 构建请求参数
            model_name = kwargs.get("model", self.model_name)
            
            parameters = {
                "result_format": "message",  # 工具调用所需
                "temperature": kwargs.get("temperature", conf().get("temperature", 0.85)),
                "top_p": kwargs.get("top_p", conf().get("top_p", 0.8)),
            }
            
            # 添加 max_tokens（如果指定）
            if kwargs.get("max_tokens"):
                parameters["max_tokens"] = kwargs["max_tokens"]
            
            # 添加工具（如果提供）
            if tools:
                parameters["tools"] = tools
                # 添加 tool_choice（如果指定）
                if kwargs.get("tool_choice"):
                    parameters["tool_choice"] = kwargs["tool_choice"]
            
            # 为 DashScope 具有思考能力的模型添加思考参数。
            model_lower = model_name.lower()
            # qwen3.8-max / qwen3.8-flash（及其预览快照）始终
            # 思考并通过reasoning_effort（默认xhigh）控制，而不是
            # 启用/关闭思考。以同样的方式对待整个qwen3.8家族。
            is_qwen38_effort_model = model_lower.startswith("qwen3.8-")
            supports_thinking = (
                "qwen3" in model_lower
                or "qwq" in model_lower
                or model_lower.startswith(("glm-", "deepseek-v4-", "kimi/kimi-k3"))
            )
            if supports_thinking:
                if is_qwen38_effort_model:
                    # qwen3.8努力模型需要enable_thinking=True但是
                    # 不应在回复中暴露原始思维文本。
                    parameters["preserve_thinking"] = False
                thinking = kwargs.get("thinking", {"type": "enabled"})
                if thinking.get("type") == "enabled" or is_qwen38_effort_model:
                    parameters["enable_thinking"] = True
                    reasoning_effort = kwargs.get("reasoning_effort")
                    if reasoning_effort:
                        parameters["reasoning_effort"] = reasoning_effort
                    if kwargs.get("thinking_budget") and not is_qwen38_effort_model:
                        parameters["thinking_budget"] = kwargs["thinking_budget"]
                    if stream:
                        parameters["incremental_output"] = True
                else:
                    parameters["enable_thinking"] = False
            
            # 始终使用增量输出进行流式传输（以获得更好的逐个令牌流式传输）
            # 这对于工具调用尤其重要，以避免响应不完整
            if stream:
                parameters["incremental_output"] = True
            
            # 使用 DashScope SDK 进行 API 调用
            if stream:
                return self._handle_stream_response(model_name, messages, parameters)
            else:
                return self._handle_sync_response(model_name, messages, parameters)
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[DASHSCOPE] call_with_tools error: {error_msg}")
            if stream:
                def error_generator():
                    yield {
                        "error": True,
                        "message": error_msg,
                        "status_code": 500
                    }
                return error_generator()
            else:
                return {
                    "error": True,
                    "message": error_msg,
                    "status_code": 500
                }
    
    def _handle_sync_response(self, model_name, messages, parameters):
        """Handle synchronous DashScope API response"""
        try:
            # 调用前设置API密钥
            dashscope.api_key = self.api_key
            self._apply_base_url()
            model = dashscope_models.get(model_name, model_name)

            if self._is_multimodal_model(model_name):
                messages = self._prepare_messages_for_multimodal(messages)
                response = MultiModalConversation.call(
                    model=model,
                    messages=messages,
                    **parameters
                )
            else:
                response = dashscope.Generation.call(
                    model=model,
                    messages=messages,
                    **parameters
                )

            if response.status_code == HTTPStatus.OK:
                # 将响应转换为 dict 以避免 DashScope 对象 KeyError 问题
                resp_dict = self._response_to_dict(response)
                choice = resp_dict["output"]["choices"][0]
                message = choice.get("message", {})
                content = message.get("content", "")
                # 多模式模型可能会以块列表的形式返回内容
                if isinstance(content, list):
                    content = "".join(
                        item.get("text", "") for item in content if isinstance(item, dict)
                    )
                usage = resp_dict.get("usage", {})
                return {
                    "id": resp_dict.get("request_id"),
                    "object": "chat.completion",
                    "created": 0,
                    "model": model_name,
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": message.get("role", "assistant"),
                            "content": content,
                            "tool_calls": self._convert_tool_calls_to_openai_format(
                                message.get("tool_calls")
                            )
                        },
                        "finish_reason": choice.get("finish_reason")
                    }],
                    "usage": {
                        "prompt_tokens": usage.get("input_tokens", 0),
                        "completion_tokens": usage.get("output_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0)
                    }
                }
            else:
                logger.error(f"[DASHSCOPE] API error: {response.code} - {response.message}")
                return {
                    "error": True,
                    "message": response.message,
                    "status_code": response.status_code
                }

        except Exception as e:
            logger.error(f"[DASHSCOPE] sync response error: {e}")
            return {
                "error": True,
                "message": str(e),
                "status_code": 500
            }
    
    def _handle_stream_response(self, model_name, messages, parameters):
        """Handle streaming DashScope API response"""
        try:
            # 调用前设置API密钥
            dashscope.api_key = self.api_key
            self._apply_base_url()
            model = dashscope_models.get(model_name, model_name)

            if self._is_multimodal_model(model_name):
                messages = self._prepare_messages_for_multimodal(messages)
                responses = MultiModalConversation.call(
                    model=model,
                    messages=messages,
                    stream=True,
                    **parameters
                )
            else:
                responses = dashscope.Generation.call(
                    model=model,
                    messages=messages,
                    stream=True,
                    **parameters
                )
            
            # 将块传输给调用者，转换为 OpenAI 格式
            for response in responses:
                # 先转换为dict以避免DashScope代理对象KeyError
                resp_dict = self._response_to_dict(response)
                status_code = resp_dict.get("status_code", 200)

                if status_code != HTTPStatus.OK:
                    err_code = resp_dict.get("code", "")
                    err_msg = resp_dict.get("message", "Unknown error")
                    logger.error(f"[DASHSCOPE] Stream error: {err_code} - {err_msg}")
                    yield {
                        "error": True,
                        "message": err_msg,
                        "status_code": status_code
                    }
                    continue

                choices = resp_dict.get("output", {}).get("choices", [])
                if not choices:
                    continue

                choice = choices[0]
                finish_reason = choice.get("finish_reason")
                message = choice.get("message", {})

                # 转换为 OpenAI 兼容格式
                openai_chunk = {
                    "id": resp_dict.get("request_id"),
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": model_name,
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": finish_reason
                    }]
                }

                # 添加角色
                role = message.get("role")
                if role:
                    openai_chunk["choices"][0]["delta"]["role"] = role

                # 添加reasoning_content（来自qwen3.5等模型的思考过程）
                reasoning_content = message.get("reasoning_content")
                if reasoning_content:
                    openai_chunk["choices"][0]["delta"]["reasoning_content"] = reasoning_content

                # 添加内容（多模式模型可能返回块列表）
                content = message.get("content")
                if isinstance(content, list):
                    content = "".join(
                        item.get("text", "") for item in content if isinstance(item, dict)
                    )
                if content:
                    openai_chunk["choices"][0]["delta"]["content"] = content

                # 添加工具调用
                tool_calls = message.get("tool_calls")
                if tool_calls:
                    openai_chunk["choices"][0]["delta"]["tool_calls"] = self._convert_tool_calls_to_openai_format(tool_calls)

                yield openai_chunk

        except Exception as e:
            logger.error(f"[DASHSCOPE] stream response error: {e}", exc_info=True)
            yield {
                "error": True,
                "message": str(e),
                "status_code": 500
            }
    
    @staticmethod
    def _response_to_dict(response) -> dict:
        """
        Convert DashScope response object to a plain dict.

        DashScope SDK wraps responses in proxy objects whose __getattr__
        delegates to __getitem__, raising KeyError (not AttributeError)
        when an attribute is missing.  Standard hasattr / getattr only
        catch AttributeError, so we must use try-except everywhere.
        """
        _SENTINEL = object()

        def _safe_getattr(obj, name, default=_SENTINEL):
            """getattr that also catches KeyError from DashScope proxy objects."""
            try:
                return getattr(obj, name)
            except (AttributeError, KeyError, TypeError):
                return default

        def _has_attr(obj, name):
            return _safe_getattr(obj, name) is not _SENTINEL

        def _to_dict(obj):
            if isinstance(obj, (str, int, float, bool, type(None))):
                return obj
            if isinstance(obj, dict):
                return {k: _to_dict(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_to_dict(i) for i in obj]
            # DashScope 响应对象的行为类似于字典（具有 .keys()）
            if _has_attr(obj, "keys"):
                try:
                    return {k: _to_dict(obj[k]) for k in obj.keys()}
                except Exception:
                    pass
            return obj

        result = {}
        # 安全地提取已知的顶级字段
        for attr in ("request_id", "status_code", "code", "message", "output", "usage"):
            val = _safe_getattr(response, attr)
            if val is _SENTINEL:
                try:
                    val = response[attr]
                except (KeyError, TypeError, IndexError):
                    continue
            result[attr] = _to_dict(val)
        return result

    def _convert_tools_to_dashscope_format(self, tools):
        """
        Convert tools from Claude format to DashScope format
        
        Claude format: {name, description, input_schema}
        DashScope format: {type: "function", function: {name, description, parameters}}
        """
        if not tools:
            return None
        
        dashscope_tools = []
        for tool in tools:
            # 检查是否已采用 DashScope/OpenAI 格式
            if 'type' in tool and tool['type'] == 'function':
                dashscope_tools.append(tool)
            else:
                # 从克劳德格式转换
                dashscope_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.get("name"),
                        "description": tool.get("description"),
                        "parameters": tool.get("input_schema", {})
                    }
                })
        
        return dashscope_tools
    
    @staticmethod
    def _prepare_messages_for_multimodal(messages: list) -> list:
        """
        Ensure messages are compatible with MultiModalConversation API.

        MultiModalConversation._preprocess_messages iterates every message
        with ``content = message["content"]; for elem in content: ...``,
        which means:
          1. Every message MUST have a 'content' key.
          2. 'content' MUST be an iterable (list), not a plain string.
             The expected format is [{"text": "..."}, ...].

        Meanwhile the DashScope API requires role='tool' messages to follow
        assistant tool_calls, so we must NOT convert them to role='user'.
        We just ensure they have a list-typed 'content'.
        """
        result = []
        for msg in messages:
            msg = dict(msg)  # 浅拷贝

            # 将内容标准化为列表格式 [{"text": "..."}]
            content = msg.get("content")
            if content is None or (isinstance(content, str) and content == ""):
                msg["content"] = [{"text": ""}]
            elif isinstance(content, str):
                msg["content"] = [{"text": content}]
            # 如果内容已经是列表，请保持原样（已经采用多模式格式）

            result.append(msg)
        return result

    def _convert_messages_to_dashscope_format(self, messages):
        """
        Convert messages from Claude format to DashScope format
        
        Claude uses content blocks with types like 'tool_use', 'tool_result'
        DashScope uses 'tool_calls' in assistant messages and 'tool' role for results
        """
        if not messages:
            return []
        
        dashscope_messages = []
        
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            
            # 处理字符串内容（已经采用正确的格式）
            if isinstance(content, str):
                dashscope_messages.append(msg)
                continue
            
            # 处理列表内容（带有内容块的克劳德格式）
            if isinstance(content, list):
                # 检查这是否是工具结果消息（具有 tool_result 块的用户角色）
                if role == "user" and any(block.get("type") == "tool_result" for block in content):
                    # 将每个 tool_result 块转换为单独的工具消息
                    for block in content:
                        if block.get("type") == "tool_result":
                            dashscope_messages.append({
                                "role": "tool",
                                "content": block.get("content", ""),
                                "tool_call_id": block.get("tool_use_id")  # DashScope 使用“tool_call_id”
                            })
                
                # 检查这是否是带有 tool_use 块的辅助消息
                elif role == "assistant":
                    # 单独的文本内容和tool_use块
                    text_parts = []
                    tool_calls = []
                    
                    for block in content:
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block.get("id"),
                                "type": "function",
                                "function": {
                                    "name": block.get("name"),
                                    "arguments": json.dumps(block.get("input", {}))
                                }
                            })
                    
                    # 构建 DashScope 格式助手消息
                    dashscope_msg = {
                        "role": "assistant"
                    }
                    
                    # 仅当存在实际文本时才添加内容
                    # DashScope API：当存在 tool_calls 时，内容应为 None 或如果为空则省略
                    if text_parts:
                        dashscope_msg["content"] = " ".join(text_parts)
                    elif not tool_calls:
                        # 如果没有 tool_calls 也没有文本，则设置空字符串（罕见情况）
                        dashscope_msg["content"] = ""
                    # 如果有 tool_calls 但没有文本，则根本不要设置 content 字段
                    
                    if tool_calls:
                        dashscope_msg["tool_calls"] = tool_calls
                    
                    dashscope_messages.append(dashscope_msg)
                else:
                    # 其他列表内容，保持原样
                    dashscope_messages.append(msg)
            else:
                # 其他格式，保持原样
                dashscope_messages.append(msg)
        
        return dashscope_messages
    
    def _convert_tool_calls_to_openai_format(self, tool_calls):
        """Convert DashScope tool_calls to OpenAI format"""
        if not tool_calls:
            return None
        
        openai_tool_calls = []
        for tool_call in tool_calls:
            # DashScope 格式已经与 OpenAI 类似
            if isinstance(tool_call, dict):
                openai_tool_calls.append(tool_call)
            else:
                # 处理对象格式
                openai_tool_calls.append({
                    "id": getattr(tool_call, 'id', None),
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments
                    }
                })
        
        return openai_tool_calls
