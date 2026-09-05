# 编码：utf-8

import ast
import copy
import json
import logging
import os
import pickle
import sys
import time

from common.log import logger
from common import i18n

# 所有可用的配置键都列在该字典中（使用小写键）。
# 这里的值只是占位符；程序不会读取它们。
# 它们只是记录预期的格式——将实际值放入 config.json 中。
available_setting = {
    # CLI、启动日志、错误消息、代理提示的全局 UI 语言
    # 以及频道回复。选项：“auto”（从系统区域设置检测，默认），
    # “zh”（中文）或“en”（英文）。显式值锁定语言。
    # 值：自动/en/zh
    "cow_lang": "auto",
    # openai API配置
    "open_ai_api_key": "",  # openai api 密钥
    # openai api 库；当use_azure_chatgpt为true时，设置匹配的api库
    "open_ai_api_base": "https://api.openai.com/v1",
    "claude_api_base": "https://api.anthropic.com/v1",  # 克劳德 API 基础
    "gemini_api_base": "https://generativelanguage.googleapis.com",  # Gemini API 基础
    "custom_api_key": "",  # 自定义 OpenAI 兼容提供商 api 密钥（当 bot_type 为“自定义”时使用）；传统单一提供商领域
    "custom_api_base": "",  # 自定义 OpenAI 兼容提供者 api 库（当 bot_type 为“自定义”时使用）；传统单一提供商领域
    # 多个自定义（兼容 OpenAI）提供商。通过 bot_type 激活：“custom:<id>”。
    # 每一项：{"id": "3f2a9c1b", "name": "my-provider", "api_key": "sk-...", "api_base": "https://api.example.com/v1", "model": "model-name"}
    "custom_providers": [],
    "proxy": "",  # openai 使用的代理
    # chatgpt模型；当 use_azure_chatgpt 为 true 时，这是 Azure 模型部署名称
    "model": "deepseek-v4-flash",  # 选项：gpt-4o、gpt-4o-mini、gpt-4-turbo、claude-3-sonnet、wenxin、moonshot、qwen-turbo、xunfei、glm-4、minimax、gemini 等。完整列表请参见 common/const.py
    "bot_type": "",  # 可选；对于OpenAI兼容的第三方服务设置“openai”或“custom”（在自定义模式下切换模型不会自动切换bot_type）。有关机器人名称，请参阅 common/const.py；如果留空，则从模型名称推断
    # 后备聊天模型，仅在主聊天模型失败后使用
    # 永久持续一回合（所有重试均已用尽）。选择加入：空
    # 提供者/模型像以前一样禁用开关和错误表面。
    # {“enabled”：bool，“provider”：str，“model”：str，“max_switches”：int}
    "chat_fallback": {
        "enabled": False,
        "provider": "",  # `bot_type` 使用的提供商 ID（例如“openai”、“qianfan”、“custom:<id>”）
        "model": "",  # 例如“gpt-4o-迷你”
        "max_switches": 1,  # 一回合可以倒退多少次，防乒乓球
    },
    "use_azure_chatgpt": False,  # 是否使用 Azure chatgpt
    "azure_deployment_id": "",  # 天蓝色模型部署名称
    "azure_api_version": "",  # 天蓝色 API 版本
    # 机器人触发配置
    "single_chat_prefix": ["bot", "@bot"],  # 文本必须包含此前缀才能在单个聊天中触发回复
    "single_chat_reply_prefix": "[bot] ",  # 单聊自动回复前缀，用于与真人区分
    "single_chat_reply_suffix": "",  # 单聊自动回复后缀； \n 插入换行符
    "group_chat_prefix": ["@bot"],  # 包含此前缀的消息会在群聊中触发回复
    "no_need_at": False,  # 在群聊中回复是否不需要@提及
    "group_chat_reply_prefix": "",  # 群聊中自动回复前缀
    "group_chat_reply_suffix": "",  # 群聊自动回复后缀； \n 插入换行符
    "group_chat_keyword": [],  # 包含该关键字的消息会触发群聊回复
    "group_at_off": False,  # 是否在群聊中禁用@bot触发
    "group_name_white_list": ["group1", "group2"],  # 启用自动回复的群组名称
    "group_name_keyword_white_list": [],  # 启用自动回复的组名关键字
    "group_chat_in_one_session": ["group1"],  # 共享对话上下文的组名称
    "group_shared_session": False,  # 群聊是否共享对话上下文（所有成员共享）。当为 False 时，每个用户在组中都有一个独立的会话
    "nick_name_black_list": [],  # 用户昵称黑名单
    "group_welcome_msg": "",  # 固定新群组成员的欢迎信息；空时使用随机样式
    "trigger_by_self": False,  # 机器人是否可以自行触发
    "text_to_image": "dall-e-2",  # 图像生成模型，选项：dall-e-2、dall-e-3
    # Azure OpenAI dall-e-3 配置
    "dalle3_image_style": "vivid", # dalle3图像风格，选项：生动、自然
    "dalle3_image_quality": "hd", # dalle3 图像质量，选项：标准、高清
    # Azure OpenAI DALL-E API 配置；当 use_azure_chatgpt 为 true 时，将文本回复资源与 DALL-E 资源分开
    "azure_openai_dalle_api_base": "", # [可选] 用于图像回复的 azure openai 端点；默认为 open_ai_api_base
    "azure_openai_dalle_api_key": "", # [可选] 用于图像回复的 azure openai 键；默认为 open_ai_api_key
    "azure_openai_dalle_deployment_id":"", # [可选] 用于图像回复的 azure openai 部署 ID；默认为文本到图像
    "image_proxy": True,  # 是否需要图像代理；从中国大陆访问LinkAI时需要
    "image_create_prefix": ["画", "看", "找"],  # 启用图像回复的前缀
    "concurrency_in_session": 1,  # 每个会话的最大传输消息数；值 >1 可能会导致无序回复
    "image_create_size": "256x256",  # 图像大小，选项：256x256、512x512、1024x1024（dall-e-3 默认为 1024x1024）
    "group_chat_exit_group": False,
    # chatgpt 会话参数
    "expires_in_seconds": 3600,  # 空闲会话到期时间
    # 角色描述（仅在聊天模式下使用）
    "character_desc": "You are a helpful AI assistant. You aim to answer and solve any questions people have, and can communicate in multiple languages.",
    "conversation_max_tokens": 1000,  # 上下文内存的最大字符数
    # chatgpt 速率限制配置
    "rate_limit_chatgpt": 20,  # chatgpt 呼叫速率限制
    "rate_limit_dalle": 50,  # openai dalle 呼叫速率限制
    # chatgpt api 参数，请参阅 https://platform.openai.com/docs/api-reference/chat/create
    "temperature": 0.9,
    "top_p": 1,
    "frequency_penalty": 0,
    "presence_penalty": 0,
    "request_timeout": 180,  # chatgpt 请求超时； openai api默认为600，困难的问题通常需要更长的时间
    "timeout": 120,  # chatgpt 重试超时；将在此窗口内自动重试
    # 百度文信(ERNIE)参数
    "baidu_wenxin_model": "eb-instant",  # 默认为 ERNIE-Bot-turbo 模型
    "baidu_wenxin_api_key": "",  # 百度API密钥
    "baidu_wenxin_secret_key": "",  # 百度秘钥
    "baidu_wenxin_prompt_enabled": False,  # 如果您使用 ernie 角色模型，请启用提示
    # 百度千帆/ERNIE OpenAI兼容API
    "qianfan_api_key": "",  # bce-v3 格式的百度千帆 API 密钥
    "qianfan_api_base": "https://qianfan.baidubce.com/v2",  # 千帆OpenAI兼容API库
    # 讯飞Spark API
    "xunfei_app_id": "",  # 讯飞应用id
    "xunfei_api_key": "",  # 讯飞API密钥
    "xunfei_api_secret": "",  # 讯飞API揭秘
    "xunfei_domain": "",  # 讯飞模型域参数； Spark4.0 Ultra为4.0Ultra，其他请参见https://www.xfyun.cn/doc/spark/Web.html
    "xunfei_spark_url": "",  # 讯飞模型请求url； Spark4.0 Ultra 为 wss://spark-api.xf-yun.com/v4.0/chat，其他请参见 https://www.xfyun.cn/doc/spark/Web.html
    # 克劳德配置
    "claude_api_cookie": "",
    "claude_uuid": "",
    # 克劳德 API 密钥
    "claude_api_key": "",
    # 统一钱文API，获取方式见https://help.aliyun.com/document_detail/2587494.html
    "qwen_access_key_id": "",
    "qwen_access_key_secret": "",
    "qwen_agent_key": "",
    "qwen_app_id": "",
    "qwen_node_id": "",  # 工作流程编排模型使用的 id；如果 qwen_node_id 未使用，请将其保留为空字符串
    # 阿里巴巴灵机（统一新sdk）模型api key
    "dashscope_api_key": "",
    # 谷歌 Gemini Api 密钥
    "gemini_api_key": "",
    # 嵌入模型配置
    "embedding_provider": "",  # 显式设置提供程序：openai / linkai / dashscope / doubao / zhipu（与bot_type命名一致）
    "embedding_model": "",     # 留空以使用提供商的默认模型
    "embedding_dimensions": 0, # 留空/0 以使用提供程序的默认维度（建议使用 1024 以保持一致性）
    # 语音配置
    "speech_recognition": True,  # 是否启用语音识别
    "group_speech_recognition": False,  # 是否开启群组语音识别
    "voice_reply_voice": False,  # 是否用语音回复语音；需要匹配的 TTS 引擎 api 密钥
    "always_reply_voice": False,  # 是否总是语音回复
    "voice_to_text": "openai",  # 语音识别引擎：openai、baidu、google、azure、xunfei、ali
    "text_to_voice": "openai",  # TTS引擎：openai、baidu、google、azure、讯飞、ali、pytts（离线）、elevenlabs、edge（在线）
    "text_to_voice_model": "tts-1",
    "tts_voice_id": "alloy",
    # 百度语音api配置；使用百度语音识别和TTS时需要
    "baidu_app_id": "",
    "baidu_api_key": "",
    "baidu_secret_key": "",
    # 1536 普通话（带基础英语） 1737 英语 1637 粤语 1837 四川话 1936 普通话远场
    "baidu_dev_pid": 1536,
    # 天蓝色语音 API 配置；使用 Azure 语音识别和 TTS 时需要
    "azure_voice_api_key": "",
    "azure_voice_region": "japaneast",
    # Elevenlabs 语音 API 配置
    "xi_api_key": "",  # 请参阅 https://docs.elevenlabs.io/api-reference/quick-start/authentication 了解如何获取 api 密钥
    "xi_voice_id": "",  # ElevenLabs 提供 9 个英文语音 ID：Adam/Antoni/Arnold/Bella/Domi/Elli/Josh/Rachel/Sam
    # 服务时限
    "chat_time_module": False,  # 是否启用服务时间限制
    "chat_start_time": "00:00",  # 服务开始时间
    "chat_stop_time": "24:00",  # 服务停止时间
    # 翻译API
    "translate": "baidu",  # 翻译API：百度、有道
    # 百度翻译api配置
    "baidu_translate_app_id": "",  # 百度翻译api appid
    "baidu_translate_app_key": "",  # 百度翻译api秘钥
    # 有道翻译api配置
    "youdao_translate_app_key": "",  # 有道翻译api应用id
    "youdao_translate_app_secret": "",  # 有道翻译API应用秘笈
    # 微信配置
    "wechatmp_token": "",  # 微信公众号令牌
    "wechatmp_port": 8080,  # 微信公众号端口；需要端口转发到 80 或 443
    "wechatmp_app_id": "",  # 微信公众号appID
    "wechatmp_app_secret": "",  # 微信公众号appsecret
    "wechatmp_aes_key": "",  # 微信公众号编码AESKey；加密模式下需要
    # 微信共享配置
    "wechatcom_corp_id": "",  # 微康公司 ID
    # wechatcomapp配置
    "wechatcomapp_token": "",  # WeCom 应用令牌
    "wechatcomapp_port": 9898,  # 微信应用服务端口；无需端口转发
    "wechatcomapp_secret": "",  # 微信应用秘密
    "wechatcomapp_agent_id": "",  # 微信应用agent_id
    "wechatcomapp_aes_key": "",  # 微信应用aes_key
    # 微信客服(wechat_kf)配置
    "wechat_kf_corp_id": "",  # 微信客服所属公司corp_id
    "wechat_kf_token": "",  # 微信客服回调token
    "wechat_kf_port": 9888,  # 微信客服回调服务端口
    "wechat_kf_secret": "",  # 微信客服小程序秘籍
    "wechat_kf_aes_key": "",  # 微信客服回调aes_key
    "wechat_kf_cursor_path": "~/.wechat_kf_cursors.json",  # 微信客服sync_msg游标持久化路径
    # 飞书配置
    "feishu_port": 80,  # 飞书bot监听端口；仅在 webhook 模式下需要
    "feishu_app_id": "",  # 飞书机器人应用id
    "feishu_app_secret": "",  # 飞书机器人应用秘密
    "feishu_token": "",  # 飞书验证令牌；仅在 webhook 模式下需要
    "feishu_event_mode": "websocket",  # 飞书事件模式：webhook（HTTP服务器）或websocket（长连接）
    # 飞书流式回复（基于官方cardkit流式卡API；需要cardkit:card:write权限和飞书客户端7.20+）
    "feishu_stream_reply": True,  # 是否启用流式回复（打字机效果）；自动降级为非流式传输或在故障/旧客户端上显示升级提示
    "feishu_detailed_card": True,  # 将正常的聊天流呈现为详细的卡片（状态标题、思考/工具面板、经过的时间）； off 保留普通打字机卡
    # 钉钉配置
    "dingtalk_client_id": "",  # 钉钉机器人客户端ID
    "dingtalk_client_secret": "",  # 钉钉机器人客户端秘钥
    "dingtalk_card_enabled": False,
    # WeCom智能机器人配置（长连接模式）
    "wecom_bot_id": "",  # WeCom智能机器人BotID
    "wecom_bot_secret": "",  # WeCom智能机器人长连接秘籍
    # WeCom智能机器人传输模式：“websocket”（长连接）或“webhook”（HTTP回调）
    "wecom_bot_mode": "websocket",
    "wecom_bot_token": "",  # webhook 模式：在机器人的接收消息 URL 上配置的令牌
    "wecom_bot_encoding_aes_key": "",  # webhook 模式：在机器人的接收消息 URL 上配置 EncodingAESKey
    "wecom_bot_port": 9892,  # webhook 模式：接收消息 URL 的本地 HTTP 服务器端口
    # 电报配置
    "telegram_token": "",  # 来自 @BotFather 的机器人令牌
    "telegram_proxy": "",  # 可选的 HTTP/SOCKS5 代理，例如http://127.0.0.1:7890 或ocks5://127.0.0.1:1080（空回落到环境变量）
    "telegram_group_trigger": "mention_or_reply",  # 群组触发：mention_or_reply(@或回复，推荐) |仅提及（仅@）|全部（每条消息）
    "telegram_register_commands": True,  # 启动时自动注册 BotFather 命令菜单（与 Web 斜杠命令对齐）
    # Slack 配置（套接字模式，无需公共 IP）
    "slack_bot_token": "",  # 机器人用户 OAuth 令牌，如 xoxb-...
    "slack_app_token": "",  # 应用程序级令牌（启用Socket模式后生成），例如xapp-...
    "slack_group_trigger": "mention_or_reply",  # 频道触发：mention_or_reply（@或在话题中回复，推荐）|仅提及（仅@）|全部（每条消息）
    # Discord 配置（网关连接，无需公共 IP）
    "discord_token": "",  # Discord 机器人令牌（在开发者门户的机器人页面上生成）
    "discord_group_trigger": "mention_or_reply",  # 频道触发：mention_or_reply（@或回复机器人，推荐）|仅提及（仅@）|全部（每条消息）
    # 微信配置
    "weixin_token": "",  # 微信登录后获取的bot_token；留空以在启动时自动扫描登录
    "weixin_base_url": "https://ilinkai.weixin.qq.com",  # 微信ilink API基址
    "weixin_cdn_base_url": "https://novac2c.cdn.weixin.qq.com/c2c",  # CDN 基本 URL
    "weixin_credentials_path": "~/.weixin_cow_credentials.json",  # 凭证文件路径
    # chatgpt 命令的自定义触发词
    "clear_memory_commands": ["#清除记忆"],  # 会话重置命令；必须以 # 开头
    # 通道配置
    "channel_type": "",  # 渠道类型；支持同时运行多个通道。单数：“feishu”，多数：“feishu、dingtalk”或[“feishu”、“dingtalk”]。选项：web、飞书、钉钉、wecom_bot、微信、wechatmp、wechatmp_service、wechatcom_app、wechat_kf、telegram、slack、discord
    "web_console": True,  # 是否自动启动 Web 控制台（默认打开）。设置 False 禁用
    "subscribe_msg": "",  # 订阅消息；支持者：wechatmp、wechatmp_service、wechatcom_app
    "debug": False,  # 是否启用调试模式；打开时打印更多日志
    "appdata_dir": "",  # 数据目录
    # 插件配置
    "plugin_trigger_prefix": "$",  # 插件聊天命令的前缀；避免与管理命令前缀“#”冲突
    # 是否使用全局插件配置
    "use_global_plugin_config": False,
    "max_media_send_count": 3,  # 一次发送的最大媒体资源数
    "media_send_interval": 1,  # 发送图像的间隔，以秒为单位
    # 智浦AI平台配置
    "zhipu_ai_api_key": "",
    "zhipu_ai_api_base": "https://open.bigmodel.cn/api/paas/v4",
    "moonshot_api_key": "",
    "moonshot_base_url": "https://api.moonshot.cn/v1",
    # 豆宝（火山方舟）平台配置
    "ark_api_key": "",
    "ark_base_url": "https://ark.cn-beijing.volces.com/api/v3",
    # ModelScope 社区平台配置
    "modelscope_api_key": "",
    "modelscope_base_url": "https://api-inference.modelscope.cn/v1/chat/completions",
    # LinkAI平台配置
    "use_linkai": False,
    "linkai_api_key": "",
    "linkai_app_code": "",
    "linkai_api_base": "https://api.link-ai.tech",
    "cloud_host": "client.link-ai.tech",
    "cloud_port": None,
    "cloud_deployment_id": "",
    "minimax_api_key": "",
    "Minimax_group_id": "",
    "Minimax_base_url": "",
    "deepseek_api_key": "",
    "deepseek_api_base": "https://api.deepseek.com/v1",
    # 小米 MiMo 法学硕士
    "mimo_api_key": "",
    "mimo_api_base": "https://api.xiaomimimo.com/v1",
    "web_host": "",  # Web控制台绑定地址；空表示自动
    "web_port": 9899,
    "web_password": "",  # Web 控制台密码；空表示不需要认证
    "web_session_expire_days": 30,  # 身份验证会话在天后到期
    "web_file_serve_root": "~",  # /api/file 端点可以服务的根目录； “/”允许整个文件系统
    "mcp_oauth_redirect_base": "",  # MCP OAuth 回调的基本 URL（例如 http://your-ip:9899); 空使用本地 Web 控制台
    "agent": True,  # 是否开启Agent模式
    "agent_workspace": "~/cow",  # 代理工作空间路径，用于存储技能、记忆等。
    # 可选的本机多代理注册表。当为空或省略时，CowAgent
    # 从agent_workspace合成一个“默认”代理并且行为准确
    # 和以前一样。每个配置的工作区都是一个完整的 CowAgent 工作区。
    "agents": [],
    # 代理处理没有通道实例绑定的对话。默认为
    # 未设置时第一个配置的代理。
    "default_agent_id": "",
    "agent_max_context_tokens": 64000,  # 代理模式下的最大上下文令牌
    "agent_max_context_turns": 30,  # 代理模式下的最大上下文内存
    "agent_max_steps": 30,  # 代理模式下每次运行的最大决策步数
    # 未选择自己的会话之一的默认权限模式：
    # “只读” | “工作区写入” | “完全访问”。保持完全访问，以便
    # 现有安装的行为与升级之前完全相同。只有全新的桌面
    # 客户端（COW_DESKTOP=1，还没有 config.json）被收紧到更严格
    # load_config() 中的工作空间写入； docker/source 保持完全访问权限。
    "agent_permission_mode": "full-access",
    # 进程内子代理：代理将独立的任务交给
    # 具有自己的上下文的短命工作者，并且只返回结果。
    # 将启用设置为 false 以完全保留子代理工具。
    # 类型与内置类型一起存在于 <workspace>/subagents/*.md 中。
    "subagent": {
        "enabled": True,
        "max_depth": 1,          # 1 = 只有主代理可以生成（范围 1-5）
        "max_concurrent": 3,     # 每个生成调用的并行子代理（范围 1-10）
        "timeout_seconds": 300,  # 一次生成呼叫的预算（范围 10-3600）
    },
    # 配置的代理之间的委派。与子代理不同，目标是
    # 站立的同伴在自己的工作空间中回答。调用是同步的：
    # 委托代理等待队友的结果。仅工具
    # 出现在团队对话中（两个以上启用的代理与成员）。设置为
    # 错误地完全保留它。
    "agent_delegation": {
        "enabled": True,
        # {"<source>": ["<target>", ...]} 或 "*" 任意。未设置意味着每个
        # 代理人可以委托给其他所有人。目标进一步限定为
        # 当前对话中的队友。
        "allowed_targets": None,
        "max_depth": 3,               # 一条链中的委托跳跃（范围 1-8）
        "timeout_seconds": 600,       # 一次委托运行的预算（范围 0.01-600）
        "max_message_chars": 8000,    # 一项委派任务的大小限制
    },
    "enable_thinking": False,  # 为具有思考能力的模型启用深度思考模式
    "reasoning_effort": "high",  # 提供者原生推理深度；允许的值取决于活动的提供商/模型
    "reasoning_effort_by_model": {},  # 每个模型的工作意图：{"<provider>:<model>": "<value>"};覆盖每个模型的全局密钥
    "knowledge": True,  # 是否启用知识库功能
    # 自我进化：回顾闲聊来学习记忆/技能。平键。
    "self_evolution_enabled": True,         # 切换启用/禁用自我进化
    "self_evolution_idle_minutes": 10,      # 审查会话之前的空闲时间
    "self_evolution_min_turns": 6,          # 触发的最小用户转动（或上下文压力）
    # Deep Dream：每晚记忆升华成MEMORY.md + 梦日记。
    "deep_dream_enabled": True,             # 预定深梦开关；手动/记忆梦不受影响
    "skill": {},  # 每技能运行时配置；嵌套键在启动时展平为 SKILL_<NAME>_<KEY> 环境变量
    "mcp_servers": [],  # MCP服务器列表；每个条目支持类型“stdio”（本地进程）或“sse”（远程 URL）
    # 按需MCP工具检索：当连接多个MCP工具时，注入
    # 仅显示与查询最相关的，而不是全部。内置工具
    # 总是完全注入；禁用时降级为完全注入，
    # 低于阈值，或者没有可用的嵌入提供程序时。
    "mcp_tool_retrieval_enabled": False,    # 用于按需 MCP 工具检索的开关
    "mcp_tool_retrieval_threshold": 20,     # 仅当 MCP 刀具数量超过此值时才检索
    "mcp_tool_retrieval_top_k": 10,         # 每转注入的最大相关 MCP 工具
}


class Config(dict):
    def __init__(self, d=None):
        super().__init__()
        if d is None:
            d = {}
        for k, v in d.items():
            self[k] = v
        # user_datas：每个用户的数据； key 是用户名，value 是用户的数据（也是一个字典）
        self.user_datas = {}

    def __getitem__(self, key):
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        return super().__setitem__(key, value)

    def get(self, key, default=None):
        # 跳过以下划线开头的注释字段
        if key.startswith("_"):
            return super().get(key, default)
        
        # 如果键不在 available_setting 中，则返回 dict.get 并返回实际从 config.json 加载的值（如果不存在则返回默认值）
        if key not in available_setting:
            return super().get(key, default)
        
        try:
            return self[key]
        except KeyError as e:
            return default
        except Exception as e:
            raise e

    # 确保返回一个字典以确保原子性
    def get_user_data(self, user) -> dict:
        if self.user_datas.get(user) is None:
            self.user_datas[user] = {}
        return self.user_datas[user]

    # 安全注意事项：pickle.load() 可以在期间执行任意代码
    # 反序列化。只要 user_datas.pkl 受信任，这就是安全的
    # （本地应用程序数据目录，仅由该进程写入）。为了未来
    # 强化过程，如果满足以下条件，请考虑迁移到 JSON (json.load/json.dump)：
    # 数据结构是 JSON 可序列化的，或者添加 HMAC 签名
    # 检测 pickle 文件的篡改。
    def load_user_datas(self):
        try:
            with open(os.path.join(get_appdata_dir(), "user_datas.pkl"), "rb") as f:
                self.user_datas = pickle.load(f)
                logger.debug("[Config] User datas loaded.")
        except FileNotFoundError as e:
            logger.debug("[Config] User datas file not found, ignore.")
        except Exception as e:
            logger.warning("[Config] User datas error: {}".format(e))
            self.user_datas = {}

    def save_user_datas(self):
        try:
            # 安全：pickle.dump 输出只能由该相同的程序加载
            # 过程。请参阅上面有关 load_user_datas() 的注释。
            with open(os.path.join(get_appdata_dir(), "user_datas.pkl"), "wb") as f:
                pickle.dump(self.user_datas, f)
                logger.info("[Config] User datas saved.")
        except Exception as e:
            logger.info("[Config] User datas error: {}".format(e))


config = Config()


def _mask_value(val):
    """Mask a sensitive string value, keeping first 3 and last 3 chars."""
    if not isinstance(val, str) or len(val) <= 8:
        return val
    return val[0:3] + "*" * 5 + val[-3:]


def _mask_sensitive_recursive(obj):
    """Recursively mask values whose keys contain 'key' or 'secret'."""
    if isinstance(obj, dict):
        masked = {}
        for k, v in obj.items():
            if ("key" in k or "secret" in k) and isinstance(v, str):
                masked[k] = _mask_value(v)
            else:
                masked[k] = _mask_sensitive_recursive(v)
        return masked
    elif isinstance(obj, list):
        return [_mask_sensitive_recursive(item) for item in obj]
    return obj


def drag_sensitive(config):
    try:
        if isinstance(config, str):
            conf_dict: dict = json.loads(config)
            conf_dict_copy = _mask_sensitive_recursive(conf_dict)
            return json.dumps(conf_dict_copy, indent=4)

        elif isinstance(config, dict):
            return _mask_sensitive_recursive(config)
    except ValueError:
        # 无法解析的配置字符串（例如损坏的 config.json）。这是
        # 由load_config的自愈路径处理和报告，所以不要害怕
        # 此处具有完整回溯的日志 - 只需将其未屏蔽即可返回。
        return config
    except Exception as e:
        logger.exception(e)
        return config
    return config


def _quarantine_corrupted_config(config_path):
    """Move a corrupted config.json aside so startup can reinitialize cleanly.

    Renames the bad file to ``config.json.corrupted-<timestamp>`` (kept for
    inspection rather than deleted) and never raises: recovery must proceed even
    if the rename fails, in which case the fresh config is written over it.
    """
    try:
        backup_path = "{}.corrupted-{}".format(config_path, time.strftime("%Y%m%d%H%M%S"))
        os.replace(config_path, backup_path)
        logger.warning("[INIT] backed up corrupted config to {}".format(backup_path))
    except Exception as e:
        logger.warning("[INIT] failed to back up corrupted config: {}".format(e))


def load_config():
    global config

    # 打印 ASCII 标志
    logger.info("  ____                _                    _   ")
    logger.info(" / ___|_____      __ / \\   __ _  ___ _ __ | |_ ")
    logger.info("| |   / _ \\ \\ /\\ / // _ \\ / _` |/ _ \\ '_ \\| __|")
    logger.info("| |__| (_) \\ V  V // ___ \\ (_| |  __/ | | | |_ ")
    logger.info(" \\____\\___/ \\_/\\_//_/   \\_\\__, |\\___|_| |_|\\__|")
    logger.info("                          |___/                 ")
    logger.info("")
    # 用户配置位于数据根中：源部署使用 CWD (./)，而
    # 桌面版本将 COW_DATA_DIR 指向 ~/.cow，因此配置可以在更新后继续存在。
    user_config_path = os.path.join(get_data_root(), "config.json")
    config_path = user_config_path
    if not os.path.exists(config_path):
        logger.info("config file not found, falling back to config-template.json")
        config_path = get_config_template_path()

    config_str = read_file(config_path)
    logger.debug("[INIT] config str: {}".format(drag_sensitive(config_str)))

    # 将 json 字符串反序列化为字典。
    # `object_pairs_hook` 让我们捕获不小心输入了
    # 相同的密钥两次（例如两个 `"tools"` 块） - json.loads 会
    # 否则默默地删除除最后一次出现之外的所有内容。
    #
    # 自我修复损坏的用户 config.json，而不是在启动时崩溃 —
    # 但仅适用于打包的桌面客户端 (COW_DESKTOP=1)。被截断或
    # 否则，无效文件（例如，上次更新期间写入错误）
    # 让 json.loads 引发并将桌面应用程序搁置在“初始化”上
    # 永远失败，最终用户无法手动恢复
    # 删除文件。源部署有意保留原始版本
    # 行为（引发）：编辑 config.json 的开发人员想要一个明确的错误
    # 修复，不要默认备份和替换他们的文件。
    desktop_mode = os.environ.get("COW_DESKTOP") == "1"
    try:
        config = Config(json.loads(config_str, object_pairs_hook=_merge_duplicate_keys))
    except ValueError as parse_err:
        if not desktop_mode or config_path != user_config_path:
            # 源运行，或者捆绑的模板本身已损坏（包装
            # 我们无法通过进一步后退来治愈这个错误）——让它浮出水面。
            raise
        logger.error(
            "[INIT] config.json is corrupted ({}); backing it up and "
            "reinitializing from config-template.json".format(parse_err)
        )
        _quarantine_corrupted_config(user_config_path)
        template_str = read_file(get_config_template_path())
        config = Config(json.loads(template_str, object_pairs_hook=_merge_duplicate_keys))
        # 保留新的配置，以便恢复的默认值在下一个配置中继续存在
        # 启动（并且应用程序有一个有效的文件可以将用户更改写回到其中）。
        try:
            with open(user_config_path, mode="w", encoding="utf-8") as f:
                json.dump(dict(config), f, ensure_ascii=False, indent=2)
        except Exception as write_err:
            # 失败的重写不得重新导致启动崩溃：我们已经持有有效的
            # 内存中配置，因此使用它运行并在下次启动时重试写入。
            logger.warning("[INIT] failed to write recovered config.json: {}".format(write_err))

    # 将遗留单数密钥 (`tool`、`skill`) 迁移到规范中
    # 多个存储桶，因此代码库的其余部分仅读取一个模式。
    # 深度合并，以便保留现有的 `tools`/`skills` 条目并
    # 仅从遗留部分填充缺少的名称空间。
    _merge_legacy_namespace(config, legacy="tool",  canonical="tools")
    _merge_legacy_namespace(config, legacy="skill", canonical="skills")

    # 全新桌面安装默认为更严格的“工作区写入”；每个
    # 其他情况保留模板的“完全访问权限”。仅打包客户端
    # 第一次启动时缺少 config.json （config_path 回退到
    # 捆绑模板）——一旦用户配置了任何东西（例如模型）
    # 控制台会保留 config.json，因此现有安装始终会包含它并且
    # 永远不会因升级而默默收紧。非桌面（docker、源）是
    # 未受影响。放置在 env 覆盖之前，因此 AGENT_PERMISSION_MODE 仍然存在
    # 如果明确设置则获胜。
    if os.environ.get("COW_DESKTOP") == "1" and config_path != user_config_path:
        config["agent_permission_mode"] = "workspace-write"

    # 使用环境变量覆盖配置。
    # 一些在线部署平台（例如Railway）直接从github部署项目。因此，您不应将 api 密钥等机密信息放入配置文件中，而应使用环境变量来覆盖默认配置。
    for name, value in os.environ.items():
        name = name.lower()
        # 跳过以下划线开头的注释字段
        if name.startswith("_"):
            continue
        if name in available_setting:
            logger.info("[INIT] override config by environ args: {}={}".format(name, value))
            try:
                # 安全：使用 ast.literal_eval 而不是 eval()。
                # ast.literal_eval 只解析 Python 文字（字符串、数字、
                # 元组、列表、字典、布尔值、无）且无法执行
                # 任意代码，防止环境变量注入。
                config[name] = ast.literal_eval(value)
            except Exception:
                # literal_eval 可以引发非文字的 ValueError/SyntaxError
                # 字符串，还有格式错误的输入上的 TypeError/RecursionError
                # （例如不可散列的字典键）；广泛捕捉以避免崩溃
                # 启动，然后回退到将值视为普通字符串。
                if value.lower() == "false":
                    config[name] = False
                elif value.lower() == "true":
                    config[name] = True
                else:
                    config[name] = value

    if config.get("debug", False):
        logger.setLevel(logging.DEBUG)
        logger.debug("[INIT] set log level to DEBUG")

    # 注册表会在首次访问时缓存配置文件。任何解决了
    # 在此之前的路径缓存了预配置工作区，因此请将其删除。
    # 此处重建还会在启动时显示无效的“代理”块
    # 而不是在第一条入站消息上。
    from agent.registry import get_agent_registry, set_agent_registry

    set_agent_registry(None)
    agent_registry = get_agent_registry()

    # 尽早解决全球UI语言问题，让每个人
    # 下游层（日志、CLI、代理提示、通道回复）共享它。
    resolved_lang = i18n.resolve_language(config.get("cow_lang", "auto"))

    logger.info("[INIT] load config: {}".format(drag_sensitive(config)))

    # 打印系统初始化信息
    logger.info("[INIT] ========================================")
    logger.info("[INIT] System Initialization")
    logger.info("[INIT] ========================================")
    logger.info("[INIT] Language: {}".format(resolved_lang))
    logger.info("[INIT] Channel: {}".format(config.get("channel_type", "unknown")))
    logger.info("[INIT] Model: {}".format(config.get("model", "unknown")))

    # 代理模式信息
    if config.get("agent", True):
        profiles = agent_registry.list(include_disabled=False)
        if len(profiles) == 1:
            logger.info("[INIT] Mode: Agent (workspace: {})".format(profiles[0].workspace))
        else:
            logger.info("[INIT] Mode: Agent ({} agents)".format(len(profiles)))
            for profile in profiles:
                marker = " (default)" if profile.id == agent_registry.default_agent_id else ""
                logger.info(
                    "[INIT]   - {}{}: {}".format(profile.id, marker, profile.workspace)
                )
    else:
        logger.info("[INIT] Mode: Chat (set \"agent\":true in config.json to enable Agent mode)")

    logger.info("[INIT] Debug: {}".format(config.get("debug", False)))
    logger.info("[INIT] ========================================")

    # 将选定的配置值同步到环境变量，以便
    # 子进程（例如 shell 技能脚本）可以直接访问它们。
    # 现有的环境变量不会被覆盖（环境优先）。
    _CONFIG_TO_ENV = {
        "open_ai_api_key": "OPENAI_API_KEY",
        "open_ai_api_base": "OPENAI_API_BASE",
        "linkai_api_key": "LINKAI_API_KEY",
        "linkai_api_base": "LINKAI_API_BASE",
        "claude_api_key": "CLAUDE_API_KEY",
        "claude_api_base": "CLAUDE_API_BASE",
        "gemini_api_key": "GEMINI_API_KEY",
        "gemini_api_base": "GEMINI_API_BASE",
        "minimax_api_key": "MINIMAX_API_KEY",
        "minimax_api_base": "MINIMAX_API_BASE",
        "deepseek_api_key": "DEEPSEEK_API_KEY",
        "deepseek_api_base": "DEEPSEEK_API_BASE",
        "mimo_api_key": "MIMO_API_KEY",
        "mimo_api_base": "MIMO_API_BASE",
        "qianfan_api_key": "QIANFAN_API_KEY",
        "qianfan_api_base": "QIANFAN_API_BASE",
        "zhipu_ai_api_key": "ZHIPU_AI_API_KEY",
        "zhipu_ai_api_base": "ZHIPU_AI_API_BASE",
        "moonshot_api_key": "MOONSHOT_API_KEY",
        "moonshot_api_base": "MOONSHOT_API_BASE",
        "ark_api_key": "ARK_API_KEY",
        "ark_api_base": "ARK_API_BASE",
        "dashscope_api_key": "DASHSCOPE_API_KEY",
        "dashscope_api_base": "DASHSCOPE_API_BASE",
        # 通道凭证（由检查环境变量的技能使用）
        "feishu_app_id": "FEISHU_APP_ID",
        "feishu_app_secret": "FEISHU_APP_SECRET",
        "dingtalk_client_id": "DINGTALK_CLIENT_ID",
        "dingtalk_client_secret": "DINGTALK_CLIENT_SECRET",
        "wechatmp_app_id": "WECHATMP_APP_ID",
        "wechatmp_app_secret": "WECHATMP_APP_SECRET",
        "wechatcomapp_agent_id": "WECHATCOMAPP_AGENT_ID",
        "wechatcomapp_secret": "WECHATCOMAPP_SECRET",
        "wechatcom_corp_id": "WECHATCOM_CORP_ID",
        "wechat_kf_corp_id": "WECHAT_KF_CORP_ID",
        "wechat_kf_secret": "WECHAT_KF_SECRET",
        "wechat_kf_token": "WECHAT_KF_TOKEN",
        "wechat_kf_aes_key": "WECHAT_KF_AES_KEY",
        "qq_app_id": "QQ_APP_ID",
        "qq_app_secret": "QQ_APP_SECRET",
        "weixin_token": "WEIXIN_TOKEN",
    }
    injected = 0
    for conf_key, env_key in _CONFIG_TO_ENV.items():
        if env_key not in os.environ:
            val = config.get(conf_key, "")
            if val:
                os.environ[env_key] = str(val)
                injected += 1

    injected += _sync_skill_config_to_env(config.get("skills", {}))
    injected += sync_image_generation_custom_provider_env(config)

    if injected:
        logger.info("[INIT] Synced {} config values to environment variables".format(injected))

    config.load_user_datas()


def _deep_merge_dicts(base: dict, incoming: dict) -> dict:
    """Recursively merge ``incoming`` into ``base`` (incoming wins on leaves)."""
    for key, val in incoming.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(val, dict)
        ):
            _deep_merge_dicts(base[key], val)
        else:
            base[key] = val
    return base


def _merge_duplicate_keys(pairs):
    """object_pairs_hook for json.loads: deep-merge duplicate top-level keys
    (lists concat, dicts merge, scalars take the latter) instead of dropping."""
    out = {}
    duplicates = []
    for key, val in pairs:
        if key not in out:
            out[key] = val
            continue
        duplicates.append(key)
        prev = out[key]
        if isinstance(prev, dict) and isinstance(val, dict):
            _deep_merge_dicts(prev, val)
        elif isinstance(prev, list) and isinstance(val, list):
            prev.extend(val)
        else:
            out[key] = val
    if duplicates:
        # 记录器可能还没有连接——回退到打印，这样我们就不会丢失警告。
        unique = sorted(set(duplicates))
        try:
            logger.warning("[INIT] config.json has duplicate keys (merged): %s", unique)
        except Exception:
            print("[INIT] config.json has duplicate keys (merged):", unique)
    return out


def _merge_legacy_namespace(cfg, legacy: str, canonical: str) -> None:
    """Fold deprecated singular keys (``tool`` / ``skill``) into their plural
    canonical counterparts at load time. Canonical entries always win."""
    legacy_section = cfg.get(legacy)
    if not isinstance(legacy_section, dict) or not legacy_section:
        cfg.pop(legacy, None)
        return
    canonical_section = cfg.get(canonical)
    if not isinstance(canonical_section, dict):
        canonical_section = {}
    merged_keys = []
    for name, val in legacy_section.items():
        if name in canonical_section:
            if isinstance(canonical_section[name], dict) and isinstance(val, dict):
                for sub_key, sub_val in val.items():
                    if (
                        sub_key in canonical_section[name]
                        and isinstance(canonical_section[name][sub_key], dict)
                        and isinstance(sub_val, dict)
                    ):
                        _deep_merge_dicts(sub_val, canonical_section[name][sub_key])
                        canonical_section[name][sub_key] = sub_val
                    else:
                        canonical_section[name].setdefault(sub_key, sub_val)
            continue
        canonical_section[name] = val
        merged_keys.append(name)
    cfg[canonical] = canonical_section
    cfg.pop(legacy, None)
    if merged_keys:
        logger.warning(
            "[INIT] Legacy config key '{}' is deprecated; merged into '{}': {}. "
            "Please rename '{}' to '{}' in your config.json.".format(
                legacy, canonical, merged_keys, legacy, canonical,
            )
        )


def _sync_skill_config_to_env(skill_section) -> int:
    """Flatten skill-namespaced config into environment variables.

    Mapping rule: ``config["skills"][<name>][<key>]`` -> ``SKILL_<NAME>_<KEY>``
    (e.g. ``skills["image-generation"].model`` -> ``SKILL_IMAGE_GENERATION_MODEL``).

    This lets subprocess-based skill scripts read their own settings without
    importing project code. Existing env vars are NOT overwritten so the
    real environment always wins.

    Returns the number of variables actually injected.
    """
    if not isinstance(skill_section, dict):
        return 0
    injected = 0
    for skill_name, skill_conf in skill_section.items():
        if not isinstance(skill_conf, dict):
            continue
        name_part = str(skill_name).replace("-", "_").upper()
        for key, val in skill_conf.items():
            if val is None or val == "":
                continue
            env_key = "SKILL_{}_{}".format(name_part, str(key).upper())
            if env_key in os.environ:
                continue
            os.environ[env_key] = str(val)
            injected += 1
    return injected


def sync_image_generation_custom_provider_env(
    config_data,
    overwrite=False,
) -> int:
    """Expose the selected custom image provider to the skill subprocess."""
    env_key = "SKILL_IMAGE_GENERATION_CUSTOM_PROVIDER"
    skills = config_data.get("skills") if isinstance(config_data, dict) else {}
    image_config = (
        skills.get("image-generation")
        if isinstance(skills, dict)
        else {}
    )
    provider_id = (
        image_config.get("provider", "")
        if isinstance(image_config, dict)
        else ""
    )

    selected = None
    if isinstance(provider_id, str) and provider_id.startswith("custom:"):
        custom_id = provider_id[len("custom:"):]
        providers = config_data.get("custom_providers", [])
        if isinstance(providers, list):
            selected = next(
                (
                    provider
                    for provider in providers
                    if isinstance(provider, dict)
                    and provider.get("id") == custom_id
                ),
                None,
            )

    if selected is None:
        if overwrite:
            os.environ.pop(env_key, None)
        return 0
    if env_key in os.environ and not overwrite:
        return 0

    payload = {
        key: selected.get(key)
        for key in ("id", "name", "api_key", "api_base", "model")
        if selected.get(key) is not None
    }
    os.environ[env_key] = json.dumps(payload, ensure_ascii=False)
    return 1


def get_root():
    return os.path.dirname(os.path.abspath(__file__))


def get_resource_root():
    """Directory holding bundled read-only resources (e.g. config-template.json).

    Under PyInstaller, data files live in sys._MEIPASS (the onedir _internal
    folder), which differs from get_root() — the latter is used for writable
    user data and should stay next to the executable, not inside the bundle.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def get_config_template_path():
    """Path to the bundled config-template.json.

    Resolved via get_resource_root() so it works both from source and from a
    frozen (PyInstaller) bundle, where the template ships inside sys._MEIPASS
    and CWD may differ.
    """
    template_path = os.path.join(get_resource_root(), "config-template.json")
    return template_path if os.path.exists(template_path) else "./config-template.json"


def read_config_template():
    """Load config-template.json as a dict; returns {} when unreadable."""
    try:
        return json.loads(read_file(get_config_template_path()))
    except Exception as e:
        logger.warning("[Config] failed to read config template: {}".format(e))
        return {}


def get_data_root():
    """Directory for writable user data (config.json, user_datas.pkl, run.log).

    The desktop build sets COW_DATA_DIR (e.g. ~/.cow) so data lives in the
    user's home rather than inside the read-only app bundle and survives app
    updates. When unset (source deployment), it falls back to get_root(), so
    existing behavior is unchanged.
    """
    data_dir = os.environ.get("COW_DATA_DIR")
    if data_dir:
        data_dir = os.path.expanduser(data_dir)
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    return get_root()


def read_file(path):
    with open(path, mode="r", encoding="utf-8-sig") as f:
        return f.read()


def conf():
    return config


def get_appdata_dir():
    data_path = os.path.join(get_data_root(), conf().get("appdata_dir", ""))
    if not os.path.exists(data_path):
        logger.info("[INIT] data path not exists, create it: {}".format(data_path))
        os.makedirs(data_path)
    return data_path


def get_weixin_credentials_path(instance_id: str = ""):
    """Resolve the Weixin credentials (token) file path.

    Honors an explicit ``weixin_credentials_path`` from config. Otherwise the
    packaged desktop build (COW_DATA_DIR set) keeps it under the data dir
    (~/.cow) so all user data stays together, while source deployments retain
    the legacy ~/.weixin_cow_credentials.json default unchanged.

    ``instance_id`` isolates the credentials file when several Weixin instances
    run in one process, each logged into a different account: their tokens must
    not share (and overwrite) one file. Empty (the single-instance default)
    keeps the legacy path byte-for-byte, so existing installs are untouched.
    """
    configured = conf().get("weixin_credentials_path")
    if configured:
        base = os.path.expanduser(configured)
    elif os.environ.get("COW_DATA_DIR"):
        base = os.path.join(get_data_root(), "weixin_credentials.json")
    else:
        base = os.path.expanduser("~/.weixin_cow_credentials.json")
    if not instance_id:
        return base
    root, ext = os.path.splitext(base)
    return f"{root}.{instance_id}{ext or '.json'}"


def subscribe_msg():
    trigger_prefix = conf().get("single_chat_prefix", [""])[0]
    msg = conf().get("subscribe_msg", "")
    return msg.format(trigger_prefix=trigger_prefix)


# 全局插件配置
plugin_config = {}


def write_plugin_config(pconf: dict):
    """
    Write the global plugin config.
    :param pconf: the full plugin config
    """
    global plugin_config
    for k in pconf:
        plugin_config[k.lower()] = pconf[k]

def remove_plugin_config(name: str):
    """
    Remove the global config of a plugin pending reload.
    :param name: name of the plugin to reload
    """
    global plugin_config
    plugin_config.pop(name.lower(), None)


def pconf(plugin_name: str) -> dict:
    """
    Get the config for a plugin by name.
    :param plugin_name: plugin name
    :return: the plugin's config
    """
    return plugin_config.get(plugin_name.lower())


# 全局配置保持全局有效状态
global_config = {"admin_users": []}
