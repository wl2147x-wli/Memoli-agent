# 编码：utf-8

"""
OpenAI-Compatible Bot Base Class

Provides a common implementation for bots that are compatible with OpenAI's API format.
This includes: OpenAI, LinkAI, Azure OpenAI, and many third-party providers.
"""

import json
import requests
from typing import Optional
from common.log import logger
from agent.protocol.message_utils import drop_orphaned_tool_results_openai
from models.openai.openai_http_client import OpenAIHTTPClient, OpenAIHTTPError


class OpenAICompatibleBot:
    """
    Base class for OpenAI-compatible bots.
    
    Provides common tool calling implementation that can be inherited by:
    - ChatGPTBot
    - LinkAIBot  
    - OpenAIBot
    - AzureChatGPTBot
    - Other OpenAI-compatible providers
    
    Subclasses only need to override get_api_config() to provide their specific API settings.
    """
    
    @staticmethod
    def _is_gpt5_reasoning_model(model_name: str) -> bool:
        """Whether the model is a GPT-5.x / o-series reasoning model.

        Covers gpt-5, gpt-5.4/5.5/5.6 (including suffixed variants like
        gpt-5.6-sol / gpt-5.6-luna) and the o1/o3/o4 families. These models
        only accept default sampling params and, on /v1/chat/completions,
        reject reasoning_effort together with function tools.
        """
        if not model_name or not isinstance(model_name, str):
            return False
        name = model_name.lower()
        if name.startswith("gpt-5"):
            return True
        if name.startswith(("o1", "o3", "o4")):
            return True
        return False

    def get_api_config(self):
        """
        Get API configuration for this bot.
        
        Subclasses should override this to provide their specific config.
        
        Returns:
            dict: {
                'api_key': str,
                'api_base': str (optional),
                'model': str,
                'default_temperature': float,
                'default_top_p': float,
                'default_frequency_penalty': float,
                'default_presence_penalty': float,
            }
        """
        raise NotImplementedError("Subclasses must implement get_api_config()")
    
    def call_with_tools(self, messages, tools=None, stream=False, **kwargs):
        """
        Call OpenAI-compatible API with tool support for agent integration
        
        This method handles:
        1. Format conversion (Claude format → OpenAI format)
        2. System prompt injection
        3. API calling with proper configuration
        4. Error handling
        
        Args:
            messages: List of messages (may be in Claude format from agent)
            tools: List of tool definitions (may be in Claude format from agent)
            stream: Whether to use streaming
            **kwargs: Additional parameters (max_tokens, temperature, system, etc.)
            
        Returns:
            Formatted response in OpenAI format or generator for streaming
        """
        try:
            # 从子类获取API配置
            api_config = self.get_api_config()
            
            # 将消息从 Claude 格式转换为 OpenAI 格式
            messages = self._convert_messages_to_openai_format(messages)
            
            # 将工具从 Claude 格式转换为 OpenAI 格式
            if tools:
                tools = self._convert_tools_to_openai_format(tools)
            
            # 处理系统提示（OpenAI使用系统消息，Claude使用单独参数）
            system_prompt = kwargs.get('system')
            if system_prompt:
                # 如果系统消息尚不存在，请在开头添加
                if not messages or messages[0].get('role') != 'system':
                    messages = [{"role": "system", "content": system_prompt}] + messages
                else:
                    # 替换现有的系统消息
                    messages[0] = {"role": "system", "content": system_prompt}
            
            # 构建请求参数
            model_name = kwargs.get("model", api_config.get('model', 'gpt-5.4'))
            request_params = {
                "model": model_name,
                "messages": messages,
                "temperature": kwargs.get("temperature", api_config.get('default_temperature', 0.9)),
                "top_p": kwargs.get("top_p", api_config.get('default_top_p', 1.0)),
                "frequency_penalty": kwargs.get("frequency_penalty", api_config.get('default_frequency_penalty', 0.0)),
                "presence_penalty": kwargs.get("presence_penalty", api_config.get('default_presence_penalty', 0.0)),
                "stream": stream
            }
            # GPT-5.x/o系列推理模型仅接受默认
            # 温度/top_p 和拒绝惩罚参数。
            is_gpt5_reasoning = self._is_gpt5_reasoning_model(model_name)
            if is_gpt5_reasoning:
                for key in ("temperature", "top_p", "frequency_penalty", "presence_penalty"):
                    request_params.pop(key, None)
            
            # 添加 max_tokens（如果指定）
            if kwargs.get("max_tokens"):
                request_params["max_tokens"] = kwargs["max_tokens"]
            
            # 添加工具（如果提供）
            if tools:
                request_params["tools"] = tools
                request_params["tool_choice"] = kwargs.get("tool_choice", "auto")
                # GPT-5.x 推理模型拒绝函数工具结合
                # /v1/chat/completions 上的 Reasoning_effort 除非它是“none”。
                # 强制“无”，以便代理工具调用无需迁移即可工作
                # 响应 API。
                if is_gpt5_reasoning:
                    request_params["reasoning_effort"] = "none"
            
            # 通过正确的配置进行 API 调用
            api_key = api_config.get('api_key')
            api_base = api_config.get('api_base')
            
            if stream:
                return self._handle_stream_response(request_params, api_key, api_base)
            else:
                return self._handle_sync_response(request_params, api_key, api_base)
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[{self.__class__.__name__}] call_with_tools error: {error_msg}")
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
    
    def _get_http_client(self) -> OpenAIHTTPClient:
        """Build an HTTP client honoring the global proxy config.

        Subclasses can override this for custom auth headers (e.g. Azure's
        ``api-key`` header) by returning a pre-configured client.
        """
        from config import conf
        proxy = conf().get("proxy") or None
        return OpenAIHTTPClient(proxy=proxy)

    def _handle_sync_response(self, request_params, api_key, api_base):
        """Handle synchronous chat-completion via HTTP."""
        params = dict(request_params)
        params.pop("stream", None)
        # 将旧版 SDK 超时 kwarg 转换为我们的 HTTP 客户端 kwarg。
        timeout = params.pop("request_timeout", None) or params.pop("timeout", None)
        try:
            client = self._get_http_client()
            return client.chat_completions(
                api_key=api_key,
                api_base=api_base,
                timeout=timeout,
                stream=False,
                **params,
            )
        except OpenAIHTTPError as e:
            logger.error(
                f"[{self.__class__.__name__}] sync response error: "
                f"HTTP {e.status_code}: {e.message}"
            )
            return {
                "error": True,
                "message": e.message,
                "status_code": e.status_code or 500,
            }
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] sync response error: {e}")
            return {
                "error": True,
                "message": str(e),
                "status_code": 500,
            }

    def _handle_stream_response(self, request_params, api_key, api_base):
        """Handle streaming chat-completion via HTTP (SSE).

        Yields dict chunks in OpenAI's standard streaming shape:
          {"choices": [{"delta": {...}, "finish_reason": ...}], ...}
        On error, yields a single ``{"error": ..., "status_code": ...}`` chunk
        — the same contract :mod:`agent.protocol.agent_stream` already handles.
        """
        params = dict(request_params)
        params.pop("stream", None)
        timeout = params.pop("request_timeout", None) or params.pop("timeout", None)
        try:
            client = self._get_http_client()
            stream = client.chat_completions(
                api_key=api_key,
                api_base=api_base,
                timeout=timeout,
                stream=True,
                **params,
            )
            for chunk in stream:
                yield chunk
        except OpenAIHTTPError as e:
            logger.error(
                f"[{self.__class__.__name__}] stream response error: "
                f"HTTP {e.status_code}: {e.message}"
            )
            yield {
                "error": True,
                "message": e.message,
                "status_code": e.status_code or 500,
            }
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] stream response error: {e}")
            yield {
                "error": True,
                "message": str(e),
                "status_code": 500,
            }
    
    def _convert_tools_to_openai_format(self, tools):
        """
        Convert tools from Claude format to OpenAI format
        
        Claude format: {name, description, input_schema}
        OpenAI format: {type: "function", function: {name, description, parameters}}
        """
        if not tools:
            return None
        
        openai_tools = []
        for tool in tools:
            # 检查是否已经是 OpenAI 格式
            if 'type' in tool and tool['type'] == 'function':
                openai_tools.append(tool)
            else:
                # 从克劳德格式转换
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.get("name"),
                        "description": tool.get("description"),
                        "parameters": tool.get("input_schema", {})
                    }
                })
        
        return openai_tools
    
    def _convert_messages_to_openai_format(self, messages):
        """
        Convert messages from Claude format to OpenAI format

        Claude content blocks (tool_use / tool_result / thinking) → OpenAI
        tool_calls / tool role / reasoning_content. Some thinking-mode
        providers require reasoning_content on assistant messages after a
        tool_call appears in history; back-fill with empty string when the
        trace was not captured.
        """
        if not messages:
            return []

        # 检测任何先前的工具调用回合 - 门推理_内容回填如下。
        has_tool_call_history = False
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            if msg.get("tool_calls"):
                has_tool_call_history = True
                break
            inner = msg.get("content")
            if isinstance(inner, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_use" for b in inner
            ):
                has_tool_call_history = True
                break

        openai_messages = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            # 处理字符串内容（已经采用正确的格式）
            if isinstance(content, str):
                if (role == "assistant" and has_tool_call_history
                        and isinstance(msg, dict)
                        and "reasoning_content" not in msg):
                    patched = dict(msg)
                    patched["reasoning_content"] = ""
                    openai_messages.append(patched)
                else:
                    openai_messages.append(msg)
                continue

            # 处理列表内容（带有内容块的克劳德格式）
            if isinstance(content, list):
                # 检查这是否是工具结果消息（具有 tool_result 块的用户角色）
                if role == "user" and any(block.get("type") == "tool_result" for block in content):
                    # 单独的文本内容和tool_result块
                    text_parts = []
                    tool_results = []

                    for block in content:
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_result":
                            tool_results.append(block)

                    # 首先，添加工具结果消息（必须在 Assistant with tool_calls 之后立即出现）
                    for block in tool_results:
                        tool_call_id = block.get("tool_use_id") or ""
                        if not tool_call_id:
                            logger.warning(f"[OpenAICompatible] tool_result missing tool_use_id, using empty string")
                        # 确保内容是字符串（某些提供商需要字符串内容）
                        result_content = block.get("content", "")
                        if not isinstance(result_content, str):
                            result_content = json.dumps(result_content, ensure_ascii=False)
                        openai_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": result_content
                        })

                    # 然后，将文本内容添加为单独的用户消息（如果存在）
                    if text_parts:
                        openai_messages.append({
                            "role": "user",
                            "content": " ".join(text_parts)
                        })

                # 检查这是否是带有 tool_use 块的辅助消息
                elif role == "assistant":
                    text_parts = []
                    tool_calls = []
                    reasoning_parts = []

                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == "text":
                            text_parts.append(block.get("text", ""))
                        elif btype == "tool_use":
                            tool_id = block.get("id") or ""
                            if not tool_id:
                                logger.warning(f"[OpenAICompatible] tool_use missing id for '{block.get('name')}'")
                            tool_calls.append({
                                "id": tool_id,
                                "type": "function",
                                "function": {
                                    "name": block.get("name"),
                                    "arguments": json.dumps(block.get("input", {}))
                                }
                            })
                        elif btype == "thinking":
                            reasoning_parts.append(block.get("thinking", ""))

                    # 构建OpenAI格式助手消息
                    openai_msg = {
                        "role": "assistant",
                        "content": " ".join(text_parts) if text_parts else None
                    }

                    if tool_calls:
                        openai_msg["tool_calls"] = tool_calls

                    # 往返推理_内容；缺失时为空字符串
                    # 在工具调用转向之后，严格的提供者会感到高兴。
                    if reasoning_parts:
                        openai_msg["reasoning_content"] = "\n".join(reasoning_parts)
                    elif has_tool_call_history:
                        openai_msg["reasoning_content"] = ""

                    if msg.get("_gemini_raw_parts"):
                        openai_msg["_gemini_raw_parts"] = msg["_gemini_raw_parts"]

                    openai_messages.append(openai_msg)
                else:
                    # 其他列表内容，保持原样
                    openai_messages.append(msg)
            else:
                # 其他格式，保持原样
                openai_messages.append(msg)

        return drop_orphaned_tool_results_openai(openai_messages)

    def call_vision(self, image_url: str, question: str,
                    model: Optional[str] = None,
                    max_tokens: int = 1000) -> dict:
        """Analyze an image using the OpenAI-compatible /chat/completions endpoint."""
        try:
            api_config = self.get_api_config()
            vision_model = model or api_config.get("model", "gpt-4o")
            api_key = api_config.get("api_key", "")
            api_base = (api_config.get("api_base") or "https://api.openai.com/v1").rstrip("/")

            payload = {
                "model": vision_model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }],
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            resp = requests.post(
                f"{api_base}/chat/completions",
                headers=headers, json=payload, timeout=180,
            )
            if resp.status_code != 200:
                body = resp.text[:500]
                logger.error(f"[{self.__class__.__name__}] call_vision HTTP {resp.status_code}: {body}")
                return {"error": True, "message": f"HTTP {resp.status_code}: {body}"}
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            return {
                "model": vision_model,
                "content": content,
                "usage": {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
            }
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] call_vision error: {e}")
            return {"error": True, "message": str(e)}
