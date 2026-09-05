#!/bin/bash
set -e

# 构建前缀
CHATGPT_ON_WECHAT_PREFIX=${CHATGPT_ON_WECHAT_PREFIX:-""}
# config.json 的路径
CHATGPT_ON_WECHAT_CONFIG_PATH=${CHATGPT_ON_WECHAT_CONFIG_PATH:-""}
# 执行命令行
CHATGPT_ON_WECHAT_EXEC=${CHATGPT_ON_WECHAT_EXEC:-""}

# 使用环境变量传递参数
# 如果您还没有定义环境变量，请在下面设置它们
# 导出 OPEN_AI_API_KEY=${OPEN_AI_API_KEY:-'YOUR API KEY'}
# 导出 OPEN_AI_PROXY=${OPEN_AI_PROXY:-""}
# 导出 SINGLE_CHAT_PREFIX=${SINGLE_CHAT_PREFIX:-'["bot", "@bot"]'}
# 导出 SINGLE_CHAT_REPLY_PREFIX=${SINGLE_CHAT_REPLY_PREFIX:-'"[bot] "'}
# 导出 GROUP_CHAT_PREFIX=${GROUP_CHAT_PREFIX:-'["@bot"]'}
# export GROUP_NAME_WHITE_LIST=${GROUP_NAME_WHITE_LIST:-'["ChatGPT测试群", "ChatGPT测试群2"]'}
# export IMAGE_CREATE_PREFIX=${IMAGE_CREATE_PREFIX:-'["画", "看", "找"]'}
# 导出 CONVERSATION_MAX_TOKENS=${CONVERSATION_MAX_TOKENS:-"1000"}
# 导出 SPEECH_RECOGNITION=${SPEECH_RECOGNITION:-"False"}
# export CHARACTER_DESC=${CHARACTER_DESC:-"你是ChatGPT, 一个由OpenAI训练的大型语言模型, 你旨在回答并解决人们的任何问题，并且可以使用多种语言与人交流。"}
# 导出 EXPIRES_IN_SECONDS=${EXPIRES_IN_SECONDS:-"3600"}

# CHATGPT_ON_WECHAT_PREFIX 为空，使用 /app
if [ "$CHATGPT_ON_WECHAT_PREFIX" == "" ] ; then
    CHATGPT_ON_WECHAT_PREFIX=/app
fi

# CHATGPT_ON_WECHAT_CONFIG_PATH 为空，请使用 '/app/config.json'
if [ "$CHATGPT_ON_WECHAT_CONFIG_PATH" == "" ] ; then
    CHATGPT_ON_WECHAT_CONFIG_PATH=$CHATGPT_ON_WECHAT_PREFIX/config.json
fi

# CHATGPT_ON_WECHAT_EXEC为空，使用‘python app.py’
if [ "$CHATGPT_ON_WECHAT_EXEC" == "" ] ; then
    CHATGPT_ON_WECHAT_EXEC="python app.py"
fi

# 修改config.json中的内容
# if [ "$OPEN_AI_API_KEY" == "您的 API 密钥" ] || [“$OPEN_AI_API_KEY”==“”];那么
#     echo -e "\033[31m[警告]运行前需要设置OPEN_AI_API_KEY！\033[0m"
# 菲


# 从 TZ env 应用运行时时区，因此 datetime.now() 使用本地时间
if [ -n "$TZ" ] && [ -f "/usr/share/zoneinfo/$TZ" ]; then
    ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime 2>/dev/null || true
    echo "$TZ" > /etc/timezone 2>/dev/null || true
fi

# 修复已安装卷的所有权，然后将其交给非 root 用户
if [ "$(id -u)" = "0" ]; then
    mkdir -p /home/agent/cow "${COW_DATA_DIR:-/home/agent/.cow}"
    chown agent:agent /home/agent/cow "${COW_DATA_DIR:-/home/agent/.cow}"
    exec su agent -s /bin/bash -c "cd $CHATGPT_ON_WECHAT_PREFIX && $CHATGPT_ON_WECHAT_EXEC"
fi

# 后备：已经作为代理运行
cd $CHATGPT_ON_WECHAT_PREFIX
$CHATGPT_ON_WECHAT_EXEC


