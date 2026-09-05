# 编码：utf-8

import time
import json
from typing import Optional

from models.bot import Bot
from models.zhipuai.zhipu_ai_session import ZhipuAISession
from models.zhipuai.zhipu_ai_image import ZhipuAIImage
from models.session_manager import SessionManager
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf, load_config
from zai import ZhipuAiClient


# 本机接受聊天/完成端点上的图像输入的 GLM 模型。
# glm-5.3-flash 是多模态的（图像理解）；专用glm-5v-turbo
# 仅纯文本聊天模型（glm-5-turbo、glm-5.2 等）需要。
_VISION_CAPABLE_MODEL_PREFIXES = ("glm-5.3-flash", "glm-5v")

# 用于无法看到图像的纯文本主模型的后备视觉模型。
_DEFAULT_VISION_MODEL = "glm-5v-turbo"


def _is_vision_capable_model(model_name: Optional[str]) -> bool:
    """Whether the given GLM model can accept image input directly."""
    name = (model_name or "").strip().lower()
    return bool(name) and name.startswith(_VISION_CAPABLE_MODEL_PREFIXES)


# ZhipuAI对话模型API
class ZHIPUAIBot(Bot, ZhipuAIImage):
    def __init__(self):
        super().__init__()
        self.sessions = SessionManager(ZhipuAISession, model=conf().get("model") or "ZHIPU_AI")
        self.args = {
            "model": conf().get("model") or "glm-4",  # 对话模型的名称
            "temperature": conf().get("temperature", 0.9),  # 值在(0,1)之间(智谱AI 的温度不能取 0 或者 1)
            "top_p": conf().get("top_p", 0.7),  # 值在(0,1)之间(智谱AI 的 top_p 不能取 0 或者 1)
        }
        # 初始化客户端，支持自定义 API base URL（例如智谱国际版 z.ai）
        api_key = conf().get("zhipu_ai_api_key")
        api_base = conf().get("zhipu_ai_api_base")
        
        if api_base:
            self.client = ZhipuAiClient(api_key=api_key, base_url=api_base)
        else:
            self.client = ZhipuAiClient(api_key=api_key)

    def reply(self, query, context=None):
        # 获取回复内容
        if context.type == ContextType.TEXT:
            logger.info("[ZHIPU_AI] query={}".format(query))

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
            logger.debug("[ZHIPU_AI] session query={}".format(session.messages))

            model = context.get("gpt_model")
            new_args = None
            if model:
                new_args = self.args.copy()
                new_args["model"] = model

            reply_content = self.reply_text(session, args=new_args)
            logger.debug(
                "[ZHIPU_AI] new_query={}, session_id={}, reply_cont={}, completion_tokens={}".format(
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
                logger.debug("[ZHIPU_AI] reply {} used 0 tokens.".format(reply_content))
            return reply
        elif context.type == ContextType.IMAGE_CREATE:
            ok, retstring = self.create_img(query, 0)
            reply = None
            if ok:
                reply = Reply(ReplyType.IMAGE_URL, retstring)
            else:
                reply = Reply(ReplyType.ERROR, retstring)
            return reply

        else:
            reply = Reply(ReplyType.ERROR, "Bot不支持处理{}类型的消息".format(context.type))
            return reply

    def reply_text(self, session: ZhipuAISession, args=None, retry_count=0) -> dict:
        """
        Call ZhipuAI API to get the answer
        :param session: a conversation session
        :param args: request arguments
        :param retry_count: retry count
        :return: {}
        """
        try:
            if args is None:
                args = self.args
            response = self.client.chat.completions.create(messages=session.messages, **args)
            # logger.debug("[ZHIPU_AI] 响应={}".format(response))
            # logger.info("[ZHIPU_AI]回复={},total_tokens={}".format(response.choices[0]['message']['content'],response["usage"]["total_tokens"]))

            return {
                "total_tokens": response.usage.total_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "content": response.choices[0].message.content,
            }
        except Exception as e:
            need_retry = retry_count < 2
            result = {"completion_tokens": 0, "content": "我现在有点累了，等会再来吧"}
            error_str = str(e).lower()
            
            # 通过错误信息内容判断错误类型
            if "rate" in error_str and "limit" in error_str:
                logger.warn("[ZHIPU_AI] RateLimitError: {}".format(e))
                result["content"] = "提问太快啦，请休息一下再问我吧"
                if need_retry:
                    time.sleep(20)
            elif "timeout" in error_str or "timed out" in error_str:
                logger.warn("[ZHIPU_AI] Timeout: {}".format(e))
                result["content"] = "我没有收到你的消息"
                if need_retry:
                    time.sleep(5)
            elif "api" in error_str and ("error" in error_str or "gateway" in error_str):
                logger.warn("[ZHIPU_AI] APIError: {}".format(e))
                result["content"] = "请再问我一次"
                if need_retry:
                    time.sleep(10)
            elif "connection" in error_str or "network" in error_str:
                logger.warn("[ZHIPU_AI] ConnectionError: {}".format(e))
                result["content"] = "我连接不到你的网络"
                if need_retry:
                    time.sleep(5)
            else:
                logger.exception("[ZHIPU_AI] Exception: {}".format(e), e)
                need_retry = False
                self.sessions.clear_session(session.session_id)

            if need_retry:
                logger.warn("[ZHIPU_AI] 第{}次重试".format(retry_count + 1))
                return self.reply_text(session, args, retry_count + 1)
            else:
                return result

    def call_vision(self, image_url: str, question: str,
                    model: Optional[str] = None,
                    max_tokens: int = 1000) -> dict:
        """Analyze an image using ZhipuAI OpenAI-compatible SDK.

        Multimodal chat models (e.g. glm-5.3-flash) accept image input directly,
        so we honor the requested model when it is vision-capable. Text-only chat
        models (glm-5-turbo, glm-5.2, etc.) fall back to the dedicated
        glm-5v-turbo vision model.
        """
        try:
            vision_model = model if _is_vision_capable_model(model) else _DEFAULT_VISION_MODEL
            response = self.client.chat.completions.create(
                model=vision_model,
                max_tokens=max_tokens,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }],
            )
            content = response.choices[0].message.content or ""
            usage = response.usage
            return {
                "model": vision_model,
                "content": content,
                "usage": {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                    "total_tokens": getattr(usage, "total_tokens", 0),
                },
            }
        except Exception as e:
            logger.error(f"[ZHIPU_AI] call_vision error: {e}")
            return {"error": True, "message": str(e)}

    def call_with_tools(self, messages, tools=None, stream=False, **kwargs):
        """
        Call ZhipuAI API with tool support for agent integration
        
        This method handles:
        1. Format conversion (Claude format → ZhipuAI format)
        2. System prompt injection
        3. API calling with ZhipuAI SDK
        4. Tool stream support (tool_stream=True for GLM-4.7)
        
        Args:
            messages: List of messages (may be in Claude format from agent)
            tools: List of tool definitions (may be in Claude format from agent)
            stream: Whether to use streaming
            **kwargs: Additional parameters (max_tokens, temperature, system, etc.)
            
        Returns:
            Formatted response or generator for streaming
        """
        try:
            # 将消息从Claude格式转换为ZhipuAI格式
            messages = self._convert_messages_to_zhipu_format(messages)
            
            # 将工具从Claude格式转换为ZhipuAI格式
            if tools:
                tools = self._convert_tools_to_zhipu_format(tools)
            
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
            request_params = {
                "model": kwargs.get("model", self.args.get("model", "glm-4")),
                "messages": messages,
                "temperature": kwargs.get("temperature", self.args.get("temperature", 0.9)),
                "top_p": kwargs.get("top_p", self.args.get("top_p", 0.7)),
                "stream": stream
            }
            
            # 添加 max_tokens（如果指定）
            if kwargs.get("max_tokens"):
                request_params["max_tokens"] = kwargs["max_tokens"]
            
            # 添加工具（如果提供）
            if tools:
                request_params["tools"] = tools
                # 带有zai-sdk的GLM-4.7支持tool_stream用于流式工具调用
                if stream:
                    request_params["tool_stream"] = kwargs.get("tool_stream", True)
            
            # GLM-5.3（以及后来始终思考的 GLM）拒绝
            # thinking.type="disabled" 错误 1210。他们总是思考并
            # 只接受低/高/最大的reasoning_effort。在这里标准化，这样
            # 上游“禁用”切换永远不会到达 API。
            model_name = request_params["model"]
            always_thinking = self._is_always_thinking_model(model_name)

            # 添加深度思考模式的思考参数（GLM-4.7）
            thinking = kwargs.get("thinking")
            reasoning_effort = kwargs.get("reasoning_effort")
            if always_thinking:
                request_params["thinking"] = {"type": "enabled"}
                # 努力程度必须是低/高/最大之一；回退到文档默认值。
                effort = reasoning_effort if reasoning_effort in ("low", "high", "max") else "max"
                request_params["reasoning_effort"] = effort
            elif thinking:
                request_params["thinking"] = thinking
                # 当思考启用时，Zhipu仅接受reasoning_effort。
                if thinking.get("type") == "enabled" and reasoning_effort:
                    request_params["reasoning_effort"] = reasoning_effort
            elif "glm-4.7" in model_name:
                # 默认为 GLM-4.7 启用思考
                request_params["thinking"] = {"type": "disabled"}
            
            # 使用ZhipuAI SDK进行API调用
            if stream:
                return self._handle_stream_response(request_params)
            else:
                return self._handle_sync_response(request_params)
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[ZHIPU_AI] call_with_tools error: {error_msg}")
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
    
    @staticmethod
    def _is_always_thinking_model(model_name: str) -> bool:
        """Whether the model always thinks and rejects thinking.type="disabled".

        GLM-5.3 (and any later glm-5.3.* variants) always reason and only accept
        reasoning_effort in low/high/max. See the GLM-5.3 release notes.
        """
        name = (model_name or "").strip().lower()
        return name.startswith("glm-5.3")

    def _create_completion(self, request_params):
        """Call the SDK, degrading gracefully on older zai-sdk versions.

        ``reasoning_effort`` requires zai-sdk>=0.2.3. Older SDKs raise
        ``TypeError: ... unexpected keyword argument 'reasoning_effort'``. Rather
        than fail the whole request (and every retry), drop the unsupported
        kwarg and retry once so the model still answers.
        """
        try:
            return self.client.chat.completions.create(**request_params)
        except TypeError as e:
            if "reasoning_effort" in str(e) and "reasoning_effort" in request_params:
                logger.warning(
                    "[ZHIPU_AI] installed zai-sdk does not support 'reasoning_effort'; "
                    "retrying without it. Upgrade to zai-sdk>=0.2.3 for GLM-5.3."
                )
                params = dict(request_params)
                params.pop("reasoning_effort", None)
                return self.client.chat.completions.create(**params)
            raise

    def _handle_sync_response(self, request_params):
        """Handle synchronous ZhipuAI API response"""
        try:
            response = self._create_completion(request_params)
            
            # 将ZhipuAI响应转换为OpenAI兼容格式
            return {
                "id": response.id,
                "object": "chat.completion",
                "created": response.created,
                "model": response.model,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": response.choices[0].message.role,
                        "content": response.choices[0].message.content,
                        "tool_calls": self._convert_tool_calls_to_openai_format(
                            getattr(response.choices[0].message, 'tool_calls', None)
                        )
                    },
                    "finish_reason": response.choices[0].finish_reason
                }],
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }
            
        except Exception as e:
            logger.error(f"[ZHIPU_AI] sync response error: {e}")
            return {
                "error": True,
                "message": str(e),
                "status_code": 500
            }
    
    def _handle_stream_response(self, request_params):
        """Handle streaming ZhipuAI API response"""
        try:
            stream = self._create_completion(request_params)
            
            # 将块传输给调用者，转换为 OpenAI 格式
            for chunk in stream:
                if not chunk.choices:
                    continue
                
                delta = chunk.choices[0].delta
                
                # 转换为 OpenAI 兼容格式
                openai_chunk = {
                    "id": chunk.id,
                    "object": "chat.completion.chunk",
                    "created": chunk.created,
                    "model": chunk.model,
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": chunk.choices[0].finish_reason
                    }]
                }
                
                # 添加角色（如果存在）
                if hasattr(delta, 'role') and delta.role:
                    openai_chunk["choices"][0]["delta"]["role"] = delta.role
                
                # 添加内容（如果存在）
                if hasattr(delta, 'content') and delta.content:
                    openai_chunk["choices"][0]["delta"]["content"] = delta.content
                
                # 将 Reasoning_content 添加为单独的字段（如果存在）（GLM-5/GLM-4.7 思考）
                if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                    openai_chunk["choices"][0]["delta"]["reasoning_content"] = delta.reasoning_content
                
                # 添加 tool_calls（如果存在）
                if hasattr(delta, 'tool_calls') and delta.tool_calls:
                    # 对于流式传输，tool_calls 需要特殊处理
                    openai_tool_calls = []
                    for tc in delta.tool_calls:
                        tool_call_dict = {
                            "index": getattr(tc, 'index', 0),
                            "id": getattr(tc, 'id', None),
                            "type": "function",
                            "function": {}
                        }
                        
                        # 添加函数名称（如果存在）
                        if hasattr(tc, 'function') and hasattr(tc.function, 'name') and tc.function.name:
                            tool_call_dict["function"]["name"] = tc.function.name
                        
                        # 添加函数参数（如果存在）
                        if hasattr(tc, 'function') and hasattr(tc.function, 'arguments') and tc.function.arguments:
                            tool_call_dict["function"]["arguments"] = tc.function.arguments
                        
                        openai_tool_calls.append(tool_call_dict)
                    
                    openai_chunk["choices"][0]["delta"]["tool_calls"] = openai_tool_calls
                
                yield openai_chunk
                
        except Exception as e:
            logger.error(f"[ZHIPU_AI] stream response error: {e}")
            yield {
                "error": True,
                "message": str(e),
                "status_code": 500
            }
    
    def _convert_tools_to_zhipu_format(self, tools):
        """
        Convert tools from Claude format to ZhipuAI format
        
        Claude format: {name, description, input_schema}
        ZhipuAI format: {type: "function", function: {name, description, parameters}}
        """
        if not tools:
            return None
        
        zhipu_tools = []
        for tool in tools:
            # 检查是否已经是ZhipuAI/OpenAI格式
            if 'type' in tool and tool['type'] == 'function':
                zhipu_tools.append(tool)
            else:
                # 从克劳德格式转换
                zhipu_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.get("name"),
                        "description": tool.get("description"),
                        "parameters": tool.get("input_schema", {})
                    }
                })
        
        return zhipu_tools
    
    def _convert_messages_to_zhipu_format(self, messages):
        """
        Convert messages from Claude format to ZhipuAI format
        
        Claude uses content blocks with types like 'tool_use', 'tool_result'
        ZhipuAI uses 'tool_calls' in assistant messages and 'tool' role for results
        """
        if not messages:
            return []
        
        zhipu_messages = []
        
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            
            # 处理字符串内容（已经采用正确的格式）
            if isinstance(content, str):
                zhipu_messages.append(msg)
                continue
            
            # 处理列表内容（带有内容块的克劳德格式）
            if isinstance(content, list):
                # 检查这是否是工具结果消息（具有 tool_result 块的用户角色）
                if role == "user" and any(block.get("type") == "tool_result" for block in content):
                    # 将每个 tool_result 块转换为单独的工具消息
                    for block in content:
                        if block.get("type") == "tool_result":
                            zhipu_messages.append({
                                "role": "tool",
                                "tool_call_id": block.get("tool_use_id"),
                                "content": block.get("content", "")
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
                    
                    # 构建ZhipuAI格式助手消息
                    zhipu_msg = {
                        "role": "assistant",
                        "content": " ".join(text_parts) if text_parts else None
                    }
                    
                    if tool_calls:
                        zhipu_msg["tool_calls"] = tool_calls
                    
                    zhipu_messages.append(zhipu_msg)
                else:
                    # 其他列表内容，保持原样
                    zhipu_messages.append(msg)
            else:
                # 其他格式，保持原样
                zhipu_messages.append(msg)
        
        return zhipu_messages
    
    def _convert_tool_calls_to_openai_format(self, tool_calls):
        """Convert ZhipuAI tool_calls to OpenAI format"""
        if not tool_calls:
            return None
        
        openai_tool_calls = []
        for tool_call in tool_calls:
            openai_tool_calls.append({
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments
                }
            })
        
        return openai_tool_calls
