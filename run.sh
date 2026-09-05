#!/bin/bash
set -e

# ============================
# CowAgent管理脚本
# ============================

# ANSI 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# 表情符号
EMOJI_ROCKET="🚀"
EMOJI_COW="🐄"
EMOJI_CHECK="✅"
EMOJI_CROSS="❌"
EMOJI_WARN="⚠️"
EMOJI_STOP="🛑"
EMOJI_WRENCH="🔧"

# 检查是否使用 Bash
if [ -z "$BASH_VERSION" ]; then
    echo -e "${RED}❌ Please run this script with Bash.${NC}"
    exit 1
fi

# ============================
# i18n：安装流程语言
# ============================
# UI_LANG 控制安装提示/菜单的语言。首次运行时检测到
# （或由用户选择），默认为自动检测。 “zh”或“en”。
UI_LANG=""

# 我们可以读取的终端。当脚本通过 `curl | bash` 运行时，stdin 是
# 脚本管道（读取时的 EOF），因此交互式提示必须从 tty 读取。
TTY_DEV="/dev/tty"
HAS_TTY=false
if [ -r /dev/tty ] && [ -w /dev/tty ]; then
    HAS_TTY=true
fi

# 从环境中检测默认 UI 语言（尽力而为，镜像 common/i18n）。
detect_ui_lang() {
    local loc=""
    # macOS：更喜欢AppleLocale，它反映了真实的UI语言
    if [ "$(uname)" = "Darwin" ] && command -v defaults &> /dev/null; then
        loc=$(defaults read -g AppleLocale 2>/dev/null || true)
    fi
    [ -z "$loc" ] && loc="${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}"
    case "$loc" in
        zh* | *zh_* | *_CN* | *_TW* | *_HK* | *Hans* | *Hant*) echo "zh" ;;
        *) echo "en" ;;
    esac
}

# 翻译助手：t <zh_text> <en_text>
t() {
    if [ "$UI_LANG" = "en" ]; then
        printf '%s' "$2"
    else
        printf '%s' "$1"
    fi
}

# 从控制终端读取一行（在 `curl | bash` 下工作）。
# 用法：tty_read VAR“提示”
tty_read() {
    local __var=$1 __prompt=$2 __input=""
    if [ "$HAS_TTY" = true ]; then
        # 确保 tty 处于正常线路模式。前面的箭头键菜单
        # 可能已将其置于 cbreak/-echo 模式；如果没有这个，`read` 可以
        # 立即返回或不回显键入的字符。
        stty sane < "$TTY_DEV" 2>/dev/null || true
        # 显式打印提示符（不是通过 read -p，其提示符可以是
        # 在箭头键菜单后立即吞下）并从 tty 读取。
        # `|| true` 因此非零读取 (EOF) 不会跳闸 `set -e`。
        printf '%s' "$__prompt" > /dev/tty
        read -r __input < "$TTY_DEV" || true
    else
        read -r -p "$__prompt" __input || true
    fi
    printf -v "$__var" '%s' "$__input"
}

# 带数字回退的箭头键可选择菜单。
# 用法： select_menu OUT_VAR "标题" "opt1" "opt2" ...
# 结果：OUT_VAR 设置为所选索引（从 1 开始）。
select_menu() {
    # 交互功能：绝不让非零命令（读EOF、算术
    # 评估为 0 等）在 `set -e` 下中止调用者。
    set +e
    local __out=$1; shift
    local title=$1; shift
    local options=("$@")
    local count=${#options[@]}
    # 初始突出显示：MENU_DEFAULT（基于 1）如果设置，则为第一个选项。
    local cur=0
    if [[ "${MENU_DEFAULT:-}" =~ ^[0-9]+$ ]] && (( MENU_DEFAULT >= 1 && MENU_DEFAULT <= count )); then
        cur=$((MENU_DEFAULT - 1))
    fi
    MENU_DEFAULT=""

    # 当没有可用的交互式终端时，回退到编号输入
    # （例如 CI、非 tty 管道）。箭头键渲染需要一个真正的 tty。
    if [ "$HAS_TTY" != true ] || [ ! -t 1 ]; then
        local def=$((cur + 1))
        echo -e "${CYAN}${BOLD}${title}${NC}"
        local i=1
        for opt in "${options[@]}"; do
            echo -e "  ${YELLOW}${i})${NC} ${opt}"
            i=$((i + 1))
        done
        local choice=""
        while true; do
            tty_read choice "$(t "请输入序号" "Enter number") [1-${count}, $(t "默认" "default") ${def}]: "
            choice=${choice:-$def}
            if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= count )); then
                break
            fi
            echo -e "${RED}$(t "无效选择，请输入" "Invalid choice, enter") 1-${count}${NC}"
        done
        printf -v "$__out" '%s' "$choice"
        return
    fi

    # 交互式箭头键菜单。
    # 使用文字转义字符（通过 $'...'）和 printf 而不是
    # `echo -e`，因为 `echo` 的反斜杠处理不可移植并且
    # 在某些 shell/终端上泄漏原始“\e[K”文本。
    local ESC=$'\033'
    local UP="${ESC}[A"          # 将光标向上移动一行
    local CLR="${ESC}[K"         # 清除到行尾

    # fd 3 是控制终端的长期（读取）句柄，已打开
    # 在安装流程之前通过 menu_session_begin() 执行一次。重用一个fd
    # 跨所有菜单避免了 bash 3.2 的 bug，其中重新打开 /dev/tty
    # menu 使第二个菜单读取 EOF 并自动选择默认值。
    # 使用 READ 重定向检测 fd 3 是否已打开（fd 3 已打开）
    # 只读；使用 `>&3` 进行测试会错误地将其报告为已关闭）。
    local _own_fd3=false
    if ! { : <&3; } 2>/dev/null; then
        exec 3<"$TTY_DEV"
        _own_fd3=true
    fi

    # 将终端置于 cbreak/raw 输入模式，以便单个按键到达
    # 立即并且没有回显。
    #   -echo ：不回显击键（否则箭头键会泄漏为 ^[[A）
    #   -icanon ：禁用行缓冲
    #   min 1 time 0 ：一旦有 1 个字节可用，读取就会返回
    local _restore="tput cnorm 2>/dev/null; stty echo icanon <${TTY_DEV} 2>/dev/null"
    trap "$_restore" EXIT INT TERM
    tput civis 2>/dev/null || true
    stty -echo -icanon min 1 time 0 <&3 2>/dev/null || true

    printf '%b\n' "${CYAN}${BOLD}${title}${NC}"
    printf '%b\n' "${CYAN}$(t "↑/↓ 选择，Enter 确认" "Use ↑/↓ to move, Enter to select")${NC}"

    local first_draw=true
    while true; do
        # 将光标向上移动到选项块的顶部以重新绘制它。
        if [ "$first_draw" = false ]; then
            local i=0
            while [ $i -lt $count ]; do
                printf '%s' "$UP"
                i=$((i + 1))
            done
        fi
        first_draw=false

        local idx=0
        for opt in "${options[@]}"; do
            if [ $idx -eq $cur ]; then
                printf '%s%b\n' "$CLR" "  ${GREEN}${BOLD}❯ ${opt}${NC}"
            else
                printf '%s%b\n' "$CLR" "    ${opt}"
            fi
            idx=$((idx + 1))
        done

        # 从共享终端 fd 3 读取一键。
        local key=""
        IFS= read -rsn1 key <&3
        local rc=$?
        if [ $rc -ne 0 ]; then
            # 没有可用的终端：恢复并回退到编号输入。
            eval "$_restore"; trap - EXIT INT TERM
            [ "${_own_fd3:-}" = true ] && exec 3<&- 2>/dev/null
            local choice=""
            while true; do
                tty_read choice "$(t "请输入序号" "Enter number") [1-${count}]: "
                choice=${choice:-$((cur + 1))}
                if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= count )); then
                    break
                fi
            done
            printf -v "$__out" '%s' "$choice"
            return
        fi

        # 空键表示 Enter/Return（读取 -n1 会去除换行符）。
        if [ -z "$key" ]; then
            break
        fi

        case "$key" in
            "$ESC")
                # 箭头键：ESC [ A/B（或 ESC O A/B）。读取后面的两个
                # 一次一个字节，没有超时（bash 3.2 没有小数
                # 读-t；在 cbreak 模式下，字节已被缓冲）。
                local b2="" b3=""
                IFS= read -rsn1 b2 <&3 2>/dev/null || b2=""
                IFS= read -rsn1 b3 <&3 2>/dev/null || b3=""
                case "${b2}${b3}" in
                    "[A" | "OA") cur=$(( (cur - 1 + count) % count )) ;;  # 向上
                    "[B" | "OB") cur=$(( (cur + 1) % count )) ;;          # 向下
                esac
                ;;
            $'\n' | $'\r')
                break
                ;;
            [0-9])
                if (( key >= 1 && key <= count )); then
                    cur=$((key - 1))
                    break
                fi
                ;;
            $'\003')
                # Ctrl-C：恢复和中止。
                eval "$_restore"; trap - EXIT INT TERM
                [ "${_own_fd3:-}" = true ] && exec 3<&- 2>/dev/null
                printf '\n%b\n' "${RED}$(t "已取消安装" "Installation cancelled")${NC}"
                exit 130
                ;;
        esac
    done

    eval "$_restore"
    trap - EXIT INT TERM
    [ "${_own_fd3:-}" = true ] && exec 3<&- 2>/dev/null
    printf -v "$__out" '%s' "$((cur + 1))"
}

# 打开/关闭由所有菜单共享的长期终端句柄（fd 3）
# 安装/配置会话。打开 fd 3 一次可以避免每个菜单重新打开问题
# bash 3.2（第二个菜单显示 EOF）。当没有 tty 时安全无操作。
menu_session_begin() {
    [ "$HAS_TTY" = true ] || return 0
    exec 3<"$TTY_DEV" 2>/dev/null || true
}
menu_session_end() {
    exec 3<&- 2>/dev/null || true
}

# 要求用户选择安装/UI 语言（安装的第一步）。
select_language() {
    # 顺序是固定的（英语第一，中文第二）。默认高亮显示
    # 遵循检测，但保守：只有一个置信的“zh”信号
    # (macOS AppleLocale / Linux zh_* locale) 预选中文；一切
    # else（英语、空/C/POSIX 语言环境、服务器映像）默认为英语。
    local detected
    detected=$(detect_ui_lang)
    if [ "$detected" = "zh" ]; then
        MENU_DEFAULT=2
        UI_LANG="zh"
    else
        MENU_DEFAULT=1
        UI_LANG="en"
    fi

    local lang_choice
    select_menu lang_choice "Select Language / 选择语言" "English" "中文 (Chinese)"
    case "$lang_choice" in
        1) UI_LANG="en" ;;
        2) UI_LANG="zh" ;;
        *) UI_LANG="en" ;;
    esac
    # 请记住流程的其余部分（配置写入稍后发生）
    INSTALL_LANG="$UI_LANG"
}

# 跨平台超时：更喜欢 GNU timeout/gtimeout，回退到纯 bash 实现
# 它使用后台进程+睡眠来强制执行硬时间限制。
if command -v timeout &> /dev/null; then
    _timeout() { timeout "$@"; }
elif command -v gtimeout &> /dev/null; then
    _timeout() { gtimeout "$@"; }
else
    _timeout() {
        local secs=$1; shift
        "$@" &
        local cmd_pid=$!
        ( sleep "$secs"; kill $cmd_pid 2>/dev/null ) &
        local watcher_pid=$!
        wait $cmd_pid 2>/dev/null
        local exit_code=$?
        kill $watcher_pid 2>/dev/null
        wait $watcher_pid 2>/dev/null
        return $exit_code
    }
fi

# 获取当前脚本目录。
# 当通过进程替换 (`bash <(curl ...)`) 或管道启动时，
# $0 指向 /dev/fd/* 或“bash”，因此 dirname 没有意义。回落至
# 在这种情况下当前工作目录（远程安装将 cd 到
# 克隆的项目目录并随后重置 BASE_DIR）。
_script_src="$0"
case "$_script_src" in
    /dev/fd/* | /proc/self/fd/* | bash | sh | -* | "")
        export BASE_DIR="$(pwd)"
        ;;
    *)
        export BASE_DIR=$(cd "$(dirname "$_script_src")" 2>/dev/null && pwd || pwd)
        ;;
esac

# 检测是否在项目目录中
IS_PROJECT_DIR=false
if [ -f "${BASE_DIR}/config-template.json" ] && [ -f "${BASE_DIR}/app.py" ]; then
    IS_PROJECT_DIR=true
fi

# 检查并安装工具
check_and_install_tool() {
    local tool_name=$1
    if ! command -v "$tool_name" &> /dev/null; then
        echo -e "${YELLOW}⚙️  $tool_name not found, installing...${NC}"
        if command -v yum &> /dev/null; then
            sudo yum install "$tool_name" -y
        elif command -v apt-get &> /dev/null; then
            sudo apt-get update && sudo apt-get install "$tool_name" -y
        elif command -v brew &> /dev/null; then
            brew install "$tool_name"
        else
            echo -e "${RED}❌ Unsupported package manager. Please install $tool_name manually.${NC}"
            return 1
        fi

        if ! command -v "$tool_name" &> /dev/null; then
            echo -e "${RED}❌ Failed to install $tool_name.${NC}"
            return 1
        else
            echo -e "${GREEN}✅ $tool_name installed successfully.${NC}"
            return 0
        fi
    else
        echo -e "${GREEN}✅ $tool_name is already installed.${NC}"
        return 0
    fi
}

# 检测并设置Python命令
detect_python_command() {
    FOUND_NEWER_VERSION=""
    
    # 尝试按优先顺序查找 Python 命令
    for cmd in python3 python python3.12 python3.11 python3.10 python3.9 python3.8 python3.7 python3.13; do
        if command -v $cmd &> /dev/null; then
            # 检查Python版本
            major_version=$($cmd -c 'import sys; print(sys.version_info[0])' 2>/dev/null)
            minor_version=$($cmd -c 'import sys; print(sys.version_info[1])' 2>/dev/null)
            
            if [[ "$major_version" == "3" ]]; then
                # 支持的范围是 3.7+。在 3.13+ 上，web.py 是从
                # 固定的 GitHub 提交（请参阅requirements.txt），这需要 git。
                if (( minor_version >= 7 )); then
                    PYTHON_CMD=$cmd
                    PYTHON_VERSION="${major_version}.${minor_version}"
                    break
                fi
            fi
        fi
    done
    
    if [ -z "$PYTHON_CMD" ]; then
        echo -e "${YELLOW}Tried: python3, python, python3.12, python3.11, python3.10, python3.9, python3.8, python3.7, python3.13${NC}"
        echo -e "${RED}❌ No suitable Python found. Please install Python 3.7 or newer${NC}"
        exit 1
    fi

    # 在 3.13+ 上，web.py 是通过 pip 从 GitHub 拉取的，这需要 git。
    if [[ "$major_version" == "3" ]] && (( minor_version >= 13 )); then
        if ! command -v git &> /dev/null; then
            echo -e "${YELLOW}⚠️  Python $PYTHON_VERSION detected. Installing web.py from GitHub requires git, which was not found.${NC}"
            echo -e "${YELLOW}    Please install git, or use Python 3.12 where web.py installs directly from PyPI.${NC}"
        fi
    fi
    
    # 出口供全球使用
    export PYTHON_CMD
    export PYTHON_VERSION
    
    echo -e "${GREEN}✅ Found Python: $PYTHON_CMD (version $PYTHON_VERSION)${NC}"
}

# 检查Python版本（> = 3.7）
check_python_version() {
    detect_python_command
    
    # 验证 pip 是否可用
    if ! $PYTHON_CMD -m pip --version &> /dev/null; then
        echo -e "${RED}❌ pip not found for $PYTHON_CMD. Please install pip.${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✅ pip is available for $PYTHON_CMD${NC}"
}

# 克隆项目
clone_project() {
    echo -e "${GREEN}🔍 Cloning CowAgent project...${NC}"

    if [ -d "CowAgent" ]; then
        # 现有目录会自动备份（无提示），因此
        # 安装人员保持一次性/放手。
        local backup_dir="CowAgent_backup_$(date +%s)"
        echo -e "${YELLOW}⚠️  $(t "目录 'CowAgent' 已存在，自动备份到" "Directory 'CowAgent' exists, backing up to") '$backup_dir'...${NC}"
        mv CowAgent "$backup_dir"
    fi

    check_and_install_tool git

    if ! command -v git &> /dev/null; then
        echo -e "${YELLOW}⚠️  Git not available. Trying wget/curl...${NC}"
        local zip_url="https://gitee.com/zhayujie/CowAgent/repository/archive/master.zip"
        if command -v wget &> /dev/null; then
            wget "$zip_url" -O CowAgent.zip
        elif command -v curl &> /dev/null; then
            curl -L "$zip_url" -o CowAgent.zip
        else
            echo -e "${RED}❌ Cannot download project. Please install Git, wget, or curl.${NC}"
            exit 1
        fi
        # 解压缩：首选 `unzip`，否则回退到 Python 的 zip 文件（无
        # 额外的依赖），因此无需解压的最小环境仍然可以工作。
        if command -v unzip &> /dev/null; then
            unzip CowAgent.zip
        elif command -v python3 &> /dev/null; then
            python3 -m zipfile -e CowAgent.zip .
        elif command -v python &> /dev/null; then
            python -m zipfile -e CowAgent.zip .
        else
            echo -e "${RED}❌ Cannot extract archive. Please install 'unzip' or Python.${NC}"
            exit 1
        fi
        # 存档顶级目录名称可能会有所不同（CowAgent-master 等）；检测它。
        local _extracted="CowAgent-master"
        if [ ! -d "$_extracted" ]; then
            _extracted=$(ls -d CowAgent-*/ 2>/dev/null | head -1 | sed 's:/*$::')
        fi
        [ -n "$_extracted" ] && [ -d "$_extracted" ] && mv "$_extracted" CowAgent
        rm -f CowAgent.zip
    else
        local clone_ok=false
        # 检测并暂时禁用无效的 git 代理设置
        local _git_proxy_unset=false
        local _http_proxy=$(git config --global http.proxy 2>/dev/null)
        local _https_proxy=$(git config --global https.proxy 2>/dev/null)
        if [ -n "$_http_proxy" ] && ! curl -s --connect-timeout 3 --max-time 5 --proxy "$_http_proxy" https://github.com > /dev/null 2>&1; then
            echo -e "${YELLOW}⚠️  Invalid git proxy detected: $_http_proxy, temporarily disabling...${NC}"
            git config --global --unset http.proxy
            [ -n "$_https_proxy" ] && git config --global --unset https.proxy
            _git_proxy_unset=true
        fi
        # 在尝试克隆之前测试 GitHub 连接
        if curl -sI --connect-timeout 5 --max-time 10 https://github.com > /dev/null 2>&1; then
            echo -e "${YELLOW}🌐 GitHub is reachable, cloning from GitHub...${NC}"
            _timeout 60 git clone --depth 10 --progress https://github.com/zhayujie/CowAgent.git && clone_ok=true
        fi
        if [ "$clone_ok" = false ]; then
            echo -e "${YELLOW}⚠️  GitHub clone failed or timed out, switching to Gitee mirror...${NC}"
            _timeout 30 git clone --depth 10 --progress https://gitee.com/zhayujie/CowAgent.git && clone_ok=true
        fi
        if [ "$clone_ok" = false ]; then
            echo -e "${RED}❌ Project clone failed. Please check network connection.${NC}"
            if git config --global http.proxy &> /dev/null || git config --global https.proxy &> /dev/null || [ -n "$http_proxy" ] || [ -n "$https_proxy" ] || [ -n "$HTTP_PROXY" ] || [ -n "$HTTPS_PROXY" ]; then
                echo -e "${YELLOW}💡 Detected proxy settings. If proxy is misconfigured, try removing it with:${NC}"
                echo -e "${YELLOW}   git config --global --unset http.proxy${NC}"
                echo -e "${YELLOW}   git config --global --unset https.proxy${NC}"
                echo -e "${YELLOW}   unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY${NC}"
            fi
            exit 1
        fi
    fi

    cd CowAgent || { echo -e "${RED}❌ Failed to enter project directory.${NC}"; exit 1; }
    export BASE_DIR=$(pwd)
    echo -e "${GREEN}✅ Project cloned successfully: $BASE_DIR${NC}"
    
    # 给管理脚本添加执行权限
    if [ -f "${BASE_DIR}/run.sh" ]; then
        chmod +x "${BASE_DIR}/run.sh" 2>/dev/null || true
        echo -e "${GREEN}✅ Execute permission added to run.sh${NC}"
    fi
    
    sleep 1
}

# 安装依赖项
install_dependencies() {
    echo -e "${GREEN}📦 Installing dependencies...${NC}"
    # 按安装语言选择 pip 索引，然后回退到另一个（如果
    # 首选之一无法访问：
    #   - zh用户：清华镜像第一（在中国速度快），官方PyPI后备
    #   - 其他：官方PyPI优先，清华镜像后备
    local PIP_MIRROR=""
    local _tuna="https://pypi.tuna.tsinghua.edu.cn/simple"
    local _pypi="https://pypi.org/simple"
    if [ "$UI_LANG" = "zh" ]; then
        # 优先选择清华；如果出现故障，则回退到官方 PyPI（默认 pip）。
        if curl -s --connect-timeout 5 "${_tuna}/" > /dev/null 2>&1; then
            PIP_MIRROR="-i $_tuna"
        fi
    else
        # 更喜欢官方PyPI；仅当 PyPI 无法访问时才使用清华。
        if ! curl -s --connect-timeout 5 "${_pypi}/" > /dev/null 2>&1 \
           && curl -s --connect-timeout 5 "${_tuna}/" > /dev/null 2>&1; then
            PIP_MIRROR="-i $_tuna"
        fi
    fi
    if [ -n "$PIP_MIRROR" ]; then
        echo -e "${YELLOW}Using pip mirror: ${_tuna}${NC}"
    fi

    # 仅当此点确实支持时才传递 --break-system-packages
    # （点 >= 23.x）。较旧的 pip 版本会出错并显示“没有这样的选项”，
    # 之前它转储了令人困惑的使用消息并导致安装失败。
    PIP_EXTRA_ARGS=""
    if $PYTHON_CMD -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null \
       && $PYTHON_CMD -m pip install --help 2>/dev/null | grep -q -- "--break-system-packages"; then
        PIP_EXTRA_ARGS="--break-system-packages"
        echo -e "${YELLOW}Python 3.11+ with break-system-packages support detected${NC}"
    fi

    echo -e "${YELLOW}Upgrading pip and basic tools...${NC}"
    set +e
    $PYTHON_CMD -m pip install --upgrade pip setuptools wheel importlib_metadata --ignore-installed $PIP_EXTRA_ARGS $PIP_MIRROR > /tmp/pip_upgrade.log 2>&1
    [ $? -ne 0 ] && echo -e "${YELLOW}⚠️  Some tools failed to upgrade, but continuing...${NC}"
    set -e
    rm -f /tmp/pip_upgrade.log

    echo -e "${YELLOW}Installing project dependencies...${NC}"
    set +e
    $PYTHON_CMD -m pip install -r requirements.txt $PIP_EXTRA_ARGS $PIP_MIRROR > /tmp/pip_install.log 2>&1
    local exit_code=$?
    set -e
    cat /tmp/pip_install.log

    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}✅ Dependencies installed successfully.${NC}"
    elif grep -qE "distutils installed project|uninstall-no-record-file|installed by debian" /tmp/pip_install.log; then
        echo -e "${YELLOW}⚠️  Detected system package conflict, retrying with workaround...${NC}"
        local IGNORE_PACKAGES=""
        for pkg in PyYAML setuptools wheel certifi charset-normalizer; do
            IGNORE_PACKAGES="$IGNORE_PACKAGES --ignore-installed $pkg"
        done
        set +e
        $PYTHON_CMD -m pip install -r requirements.txt $IGNORE_PACKAGES $PIP_EXTRA_ARGS $PIP_MIRROR \
            && echo -e "${GREEN}✅ Dependencies installed successfully (workaround applied).${NC}" \
            || echo -e "${YELLOW}⚠️  Some dependencies may have issues, but continuing...${NC}"
        set -e
    elif grep -q "externally-managed-environment" /tmp/pip_install.log; then
        echo -e "${YELLOW}⚠️  Detected externally-managed environment, retrying with --break-system-packages...${NC}"
        set +e
        $PYTHON_CMD -m pip install -r requirements.txt --break-system-packages $PIP_MIRROR \
            && echo -e "${GREEN}✅ Dependencies installed successfully (system packages override applied).${NC}" \
            || echo -e "${YELLOW}⚠️  Some dependencies may have issues, but continuing...${NC}"
        set -e
    else
        echo -e "${YELLOW}⚠️  Installation had errors, but continuing...${NC}"
    fi

    rm -f /tmp/pip_install.log

    # 通过可编辑安装注册 `cow` CLI 命令
    echo -e "${YELLOW}Registering cow CLI...${NC}"
    set +e
    $PYTHON_CMD -m pip install -e . $PIP_EXTRA_ARGS $PIP_MIRROR > /dev/null 2>&1
    if command -v cow &> /dev/null; then
        echo -e "${GREEN}✅ cow CLI registered.${NC}"
    else
        echo -e "${YELLOW}⚠️  cow CLI not in PATH, you can still use: $PYTHON_CMD -m cli.cli${NC}"
    fi
    set -e
}

# 选择型号
select_model() {
    echo ""
    local title sel
    title="$(t "选择 AI 模型" "Select AI Model")"
    # 第 12 个选项是“跳过”-> 稍后在 Web 控制台中配置。
    select_menu sel "$title" \
        "DeepSeek (deepseek-v4-flash, deepseek-v4-pro, etc.)" \
        "Claude (claude-opus-5, claude-sonnet-5, etc.)" \
        "OpenAI (gpt-5.6-luna, etc.)" \
        "Gemini (gemini-3.7-flash, gemini-3.6-flash, etc.)" \
        "MiniMax (MiniMax-M3, etc.)" \
        "GLM (glm-5.3-flash, glm-5.3, etc.)" \
        "Qwen (qwen3.8-flash, qwen3.8-max, etc.)" \
        "Kimi (kimi-k3, etc.)" \
        "Doubao (doubao-seed-2.1, etc.)" \
        "MiMo (mimo-v2.5-pro, etc.)" \
        "LinkAI ($(t "一个 Key 接入所有模型" "access all models via one API"))" \
        "$(t "⏭  跳过（稍后在 Web 控制台配置）" "⏭  Skip (configure later in the web console)")"
    model_choice="$sel"
}

# 读取模型配置：provider、default_model、key_variable_name
read_model_config() {
    local provider=$1 default_model=$2 key_var=$3
    echo -e "${GREEN}$(t "正在配置" "Configuring") ${provider}...${NC}"
    # 仅在此处询问 API 密钥；模型名称和 API 库默认为
    # 合理的值，并且可以稍后在 Web 控制台中更改。
    local _api_key
    tty_read _api_key "$(t "请输入" "Enter") ${provider} API Key ($(t "回车跳过，稍后在 Web 控制台填写" "press Enter to skip, set later in web console")): "
    MODEL_NAME="$default_model"
    # printf -v （不是 eval）因此包含引号/反引号/$() 的键是安全的。
    printf -v "${key_var}" '%s' "$_api_key"
}

# 配置模型。 “跳过”选项将模型留空，以便用户可以
# 首次启动后在Web控制台中完成配置。
configure_model() {
    case "$model_choice" in
        1) read_model_config "DeepSeek" "deepseek-v4-flash" "DEEPSEEK_KEY" ;;
        2) read_model_config "Claude" "claude-opus-5" "CLAUDE_KEY" ;;
        3) read_model_config "OpenAI" "gpt-5.6-luna" "OPENAI_KEY" ;;
        4) read_model_config "Gemini" "gemini-3.7-flash" "GEMINI_KEY" ;;
        5) read_model_config "MiniMax" "MiniMax-M3" "MINIMAX_KEY" ;;
        6) read_model_config "GLM" "glm-5.3-flash" "ZHIPU_KEY" ;;
        7) read_model_config "Qwen (DashScope)" "qwen3.8-flash" "DASHSCOPE_KEY" ;;
        8) read_model_config "Kimi (Moonshot)" "kimi-k3" "MOONSHOT_KEY" ;;
        9) read_model_config "Doubao (Volcengine Ark)" "doubao-seed-2-1-pro-260628" "ARK_KEY" ;;
        10) read_model_config "MiMo" "mimo-v2.5-pro" "MIMO_KEY" ;;
        11)
            # 显示获取 LinkAI 密钥的位置（zh 用户 -> 控制台页面）。
            echo -e "${CYAN}$(t "获取 LinkAI Key" "Get your LinkAI Key"): https://link-ai.tech/console/interface${NC}"
            read_model_config "LinkAI" "deepseek-v4-flash" "LINKAI_KEY"
            USE_LINKAI="true"
            ;;
        12)
            # 跳过：保留模型未设置，将在 Web 控制台中配置
            MODEL_SKIPPED="true"
            MODEL_NAME=""
            echo -e "${YELLOW}$(t "已跳过模型配置，稍后可在 Web 控制台填写" "Model configuration skipped, you can set it later in the web console")${NC}"
            ;;
    esac
}

# 通过稳定键进行通道标签（与菜单顺序无关）。
channel_label() {
    case "$1" in
        web)           t "Web 网页控制台（推荐，开箱即用）" "Web Console (recommended, ready to use)" ;;
        weixin)        t "微信" "Wechat" ;;
        feishu)        t "飞书" "Feishu" ;;
        dingtalk)      t "钉钉" "DingTalk" ;;
        wecom_bot)     t "企微智能机器人" "WeCom Bot" ;;
        qq)            printf '%s' "QQ" ;;
        wechatcom_app) t "企微自建应用" "WeCom App" ;;
        telegram)      printf '%s' "Telegram" ;;
        slack)         printf '%s' "Slack" ;;
        discord)       printf '%s' "Discord" ;;
        skip)          t "⏭  跳过（稍后在 Web 控制台配置）" "⏭  Skip (configure later in the web console)" ;;
    esac
}

# 选择频道。显示顺序取决于安装语言：
#   - 英语：首先是网络，然后是全球 IM 渠道（Telegram/Discord/Slack），
#     然后是针对中国的渠道。
#   - 中国：首先是网络，然后是针对中国的渠道，然后是全球渠道。
# 稳定的按键列表 (CHANNEL_KEYS) 将菜单顺序与配置分离
# 逻辑，因此重新排序菜单永远不会破坏configure_channel()。
select_channel() {
    echo ""
    local title sel
    title="$(t "选择接入渠道" "Select Communication Channel")"
    if [ "$UI_LANG" = "en" ]; then
        CHANNEL_KEYS=(web telegram discord slack weixin feishu dingtalk wecom_bot qq wechatcom_app skip)
    else
        CHANNEL_KEYS=(web weixin feishu dingtalk wecom_bot qq wechatcom_app telegram slack discord skip)
    fi
    local labels=() k
    for k in "${CHANNEL_KEYS[@]}"; do
        labels+=("$(channel_label "$k")")
    done
    select_menu sel "$title" "${labels[@]}"
    # 将基于 1 的菜单位置映射回稳定通道键。
    channel_choice="${CHANNEL_KEYS[$((sel - 1))]}"
}

# 配置频道，通过稳定频道键（非菜单位置）调度。
configure_channel() {
    case "$channel_choice" in
        web|skip)
            # Web（也是跳过时的默认设置）。使用默认端口
            # 没有提示；稍后可以在 Web 控制台/配置中更改它。
            CHANNEL_TYPE="web"
            WEB_PORT="9899"
            ACCESS_INFO="$(t "Web 控制台地址" "Web console") : http://localhost:9899/chat"
            ;;
        weixin)
            # 微信
            CHANNEL_TYPE="weixin"
            ACCESS_INFO="$(t "微信渠道已配置，请在终端或 Web 控制台扫码登录" "Weixin channel configured. Scan QR code in terminal or web console to login.")"
            ;;
        feishu)
            # 飞书（WebSocket模式）
            CHANNEL_TYPE="feishu"
            echo -e "${GREEN}$(t "配置飞书（WebSocket 模式）" "Configure Feishu (WebSocket mode)")...${NC}"
            local fs_app_id fs_app_secret
            tty_read fs_app_id "$(t "请输入飞书 App ID" "Enter Feishu App ID"): "
            tty_read fs_app_secret "$(t "请输入飞书 App Secret" "Enter Feishu App Secret"): "
            FEISHU_APP_ID="$fs_app_id"
            FEISHU_APP_SECRET="$fs_app_secret"
            FEISHU_EVENT_MODE="websocket"
            ACCESS_INFO="$(t "飞书渠道已配置（WebSocket 模式）" "Feishu channel configured (WebSocket mode)")"
            ;;
        dingtalk)
            # 钉钉
            CHANNEL_TYPE="dingtalk"
            echo -e "${GREEN}$(t "配置钉钉" "Configure DingTalk")...${NC}"
            local dt_client_id dt_client_secret
            tty_read dt_client_id "$(t "请输入钉钉 Client ID" "Enter DingTalk Client ID"): "
            tty_read dt_client_secret "$(t "请输入钉钉 Client Secret" "Enter DingTalk Client Secret"): "
            DT_CLIENT_ID="$dt_client_id"
            DT_CLIENT_SECRET="$dt_client_secret"
            ACCESS_INFO="$(t "钉钉渠道已配置" "DingTalk channel configured")"
            ;;
        wecom_bot)
            # 微康机器人
            CHANNEL_TYPE="wecom_bot"
            echo -e "${GREEN}$(t "配置企微智能机器人" "Configure WeCom Bot")...${NC}"
            local wecom_bot_id wecom_bot_secret
            tty_read wecom_bot_id "$(t "请输入 WeCom Bot ID" "Enter WeCom Bot ID"): "
            tty_read wecom_bot_secret "$(t "请输入 WeCom Bot Secret" "Enter WeCom Bot Secret"): "
            WECOM_BOT_ID="$wecom_bot_id"
            WECOM_BOT_SECRET="$wecom_bot_secret"
            ACCESS_INFO="$(t "企微智能机器人渠道已配置" "WeCom Bot channel configured")"
            ;;
        qq)
            # QQ
            CHANNEL_TYPE="qq"
            echo -e "${GREEN}$(t "配置 QQ 机器人" "Configure QQ Bot")...${NC}"
            local qq_app_id qq_app_secret
            tty_read qq_app_id "$(t "请输入 QQ App ID" "Enter QQ App ID"): "
            tty_read qq_app_secret "$(t "请输入 QQ App Secret" "Enter QQ App Secret"): "
            QQ_APP_ID="$qq_app_id"
            QQ_APP_SECRET="$qq_app_secret"
            ACCESS_INFO="$(t "QQ 机器人渠道已配置" "QQ Bot channel configured")"
            ;;
        wechatcom_app)
            # 微康App
            CHANNEL_TYPE="wechatcom_app"
            echo -e "${GREEN}$(t "配置企微自建应用" "Configure WeCom App")...${NC}"
            local corp_id com_token com_secret com_agent_id com_aes_key com_port
            tty_read corp_id "$(t "请输入企业 Corp ID" "Enter WeChat Corp ID"): "
            tty_read com_token "$(t "请输入应用 Token" "Enter WeChat Com App Token"): "
            tty_read com_secret "$(t "请输入应用 Secret" "Enter WeChat Com App Secret"): "
            tty_read com_agent_id "$(t "请输入应用 Agent ID" "Enter WeChat Com App Agent ID"): "
            tty_read com_aes_key "$(t "请输入应用 AES Key" "Enter WeChat Com App AES Key"): "
            tty_read com_port "$(t "请输入应用端口" "Enter WeChat Com App Port") [$(t "默认" "default"): 9898]: "
            com_port=${com_port:-9898}
            WECHATCOM_CORP_ID="$corp_id"
            WECHATCOM_TOKEN="$com_token"
            WECHATCOM_SECRET="$com_secret"
            WECHATCOM_AGENT_ID="$com_agent_id"
            WECHATCOM_AES_KEY="$com_aes_key"
            WECHATCOM_PORT="$com_port"
            ACCESS_INFO="$(t "企微自建应用渠道已配置，端口" "WeCom App channel configured on port") ${com_port}"
            ;;
        telegram)
            # 电报
            CHANNEL_TYPE="telegram"
            echo -e "${GREEN}$(t "配置 Telegram" "Configure Telegram")...${NC}"
            local tg_token
            tty_read tg_token "$(t "请输入 Telegram Bot Token" "Enter Telegram Bot Token"): "
            TELEGRAM_TOKEN="$tg_token"
            ACCESS_INFO="$(t "Telegram 渠道已配置" "Telegram channel configured")"
            ;;
        slack)
            # 松弛
            CHANNEL_TYPE="slack"
            echo -e "${GREEN}$(t "配置 Slack" "Configure Slack")...${NC}"
            local slack_bot slack_app
            tty_read slack_bot "$(t "请输入 Slack Bot Token" "Enter Slack Bot Token") (xoxb-...): "
            tty_read slack_app "$(t "请输入 Slack App Token" "Enter Slack App Token") (xapp-...): "
            SLACK_BOT_TOKEN="$slack_bot"
            SLACK_APP_TOKEN="$slack_app"
            ACCESS_INFO="$(t "Slack 渠道已配置" "Slack channel configured")"
            ;;
        discord)
            # 不和谐
            CHANNEL_TYPE="discord"
            echo -e "${GREEN}$(t "配置 Discord" "Configure Discord")...${NC}"
            local discord_token
            tty_read discord_token "$(t "请输入 Discord Bot Token" "Enter Discord Bot Token"): "
            DISCORD_TOKEN="$discord_token"
            ACCESS_INFO="$(t "Discord 渠道已配置" "Discord channel configured")"
            ;;
    esac
}

# 生成配置文件
create_config_file() {
    echo -e "${GREEN}📝 $(t "正在生成 config.json" "Generating config.json")...${NC}"

    CHANNEL_TYPE="$CHANNEL_TYPE" \
    MODEL_NAME="$MODEL_NAME" \
    OPENAI_KEY="${OPENAI_KEY:-}" \
    OPENAI_BASE="${OPENAI_BASE:-https://api.openai.com/v1}" \
    CLAUDE_KEY="${CLAUDE_KEY:-}" \
    CLAUDE_BASE="${CLAUDE_BASE:-https://api.anthropic.com/v1}" \
    GEMINI_KEY="${GEMINI_KEY:-}" \
    GEMINI_BASE="${GEMINI_BASE:-https://generativelanguage.googleapis.com}" \
    ZHIPU_KEY="${ZHIPU_KEY:-}" \
    MOONSHOT_KEY="${MOONSHOT_KEY:-}" \
    ARK_KEY="${ARK_KEY:-}" \
    DASHSCOPE_KEY="${DASHSCOPE_KEY:-}" \
    MINIMAX_KEY="${MINIMAX_KEY:-}" \
    MIMO_KEY="${MIMO_KEY:-}" \
    DEEPSEEK_KEY="${DEEPSEEK_KEY:-}" \
    DEEPSEEK_BASE="${DEEPSEEK_BASE:-https://api.deepseek.com/v1}" \
    USE_LINKAI="${USE_LINKAI:-false}" \
    LINKAI_KEY="${LINKAI_KEY:-}" \
    FEISHU_APP_ID="${FEISHU_APP_ID:-}" \
    FEISHU_APP_SECRET="${FEISHU_APP_SECRET:-}" \
    WEB_PORT="${WEB_PORT:-}" \
    DT_CLIENT_ID="${DT_CLIENT_ID:-}" \
    DT_CLIENT_SECRET="${DT_CLIENT_SECRET:-}" \
    WECOM_BOT_ID="${WECOM_BOT_ID:-}" \
    WECOM_BOT_SECRET="${WECOM_BOT_SECRET:-}" \
    QQ_APP_ID="${QQ_APP_ID:-}" \
    QQ_APP_SECRET="${QQ_APP_SECRET:-}" \
    WECHATCOM_CORP_ID="${WECHATCOM_CORP_ID:-}" \
    WECHATCOM_TOKEN="${WECHATCOM_TOKEN:-}" \
    WECHATCOM_SECRET="${WECHATCOM_SECRET:-}" \
    WECHATCOM_AGENT_ID="${WECHATCOM_AGENT_ID:-}" \
    WECHATCOM_AES_KEY="${WECHATCOM_AES_KEY:-}" \
    WECHATCOM_PORT="${WECHATCOM_PORT:-}" \
    TELEGRAM_TOKEN="${TELEGRAM_TOKEN:-}" \
    SLACK_BOT_TOKEN="${SLACK_BOT_TOKEN:-}" \
    SLACK_APP_TOKEN="${SLACK_APP_TOKEN:-}" \
    DISCORD_TOKEN="${DISCORD_TOKEN:-}" \
    COW_LANG="${INSTALL_LANG:-auto}" \
    $PYTHON_CMD -c "
import json, os
e = os.environ.get
base = {
    'channel_type': e('CHANNEL_TYPE') or 'web',
    'model': e('MODEL_NAME') or '',
    'cow_lang': e('COW_LANG', 'auto'),
    'open_ai_api_key': e('OPENAI_KEY', ''),
    'open_ai_api_base': e('OPENAI_BASE'),
    'claude_api_key': e('CLAUDE_KEY', ''),
    'claude_api_base': e('CLAUDE_BASE'),
    'gemini_api_key': e('GEMINI_KEY', ''),
    'gemini_api_base': e('GEMINI_BASE'),
    'zhipu_ai_api_key': e('ZHIPU_KEY', ''),
    'moonshot_api_key': e('MOONSHOT_KEY', ''),
    'ark_api_key': e('ARK_KEY', ''),
    'dashscope_api_key': e('DASHSCOPE_KEY', ''),
    'minimax_api_key': e('MINIMAX_KEY', ''),
    'mimo_api_key': e('MIMO_KEY', ''),
    'deepseek_api_key': e('DEEPSEEK_KEY', ''),
    'deepseek_api_base': e('DEEPSEEK_BASE'),
    # 将 ASR/TTS 提供商留空，以便 Web 控制台自动推荐实际已配置 API Key 的厂商
    # （例如 LinkAI），而不是始终使用 OpenAI。
    'voice_to_text': '',
    'text_to_voice': '',
    'voice_reply_voice': False,
    'speech_recognition': True,
    'group_speech_recognition': False,
    'use_linkai': e('USE_LINKAI') == 'true',
    'linkai_api_key': e('LINKAI_KEY', ''),
    'linkai_app_code': '',
    'agent': True,
    'agent_max_context_tokens': 50000,
    'agent_max_context_turns': 20,
    'agent_max_steps': 20,
    # 新安装默认开启自进化；老用户（无 key）保持代码默认值（关闭），
    # 从而确保升级不会静默改变其既有行为。
    'self_evolution_enabled': True,
}
channel_map = {
    'feishu': {'feishu_app_id': 'FEISHU_APP_ID', 'feishu_app_secret': 'FEISHU_APP_SECRET'},
    'web': {'web_port': ('WEB_PORT', int)},
    'dingtalk': {'dingtalk_client_id': 'DT_CLIENT_ID', 'dingtalk_client_secret': 'DT_CLIENT_SECRET'},
    'wecom_bot': {'wecom_bot_id': 'WECOM_BOT_ID', 'wecom_bot_secret': 'WECOM_BOT_SECRET'},
    'qq': {'qq_app_id': 'QQ_APP_ID', 'qq_app_secret': 'QQ_APP_SECRET'},
    'wechatcom_app': {'wechatcom_corp_id': 'WECHATCOM_CORP_ID', 'wechatcomapp_token': 'WECHATCOM_TOKEN', 'wechatcomapp_secret': 'WECHATCOM_SECRET', 'wechatcomapp_agent_id': 'WECHATCOM_AGENT_ID', 'wechatcomapp_aes_key': 'WECHATCOM_AES_KEY', 'wechatcomapp_port': ('WECHATCOM_PORT', int)},
    'telegram': {'telegram_token': 'TELEGRAM_TOKEN'},
    'slack': {'slack_bot_token': 'SLACK_BOT_TOKEN', 'slack_app_token': 'SLACK_APP_TOKEN'},
    'discord': {'discord_token': 'DISCORD_TOKEN'},
}
def _to_int(val, default):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default
ch = e('CHANNEL_TYPE') or 'web'
for key, spec in channel_map.get(ch, {}).items():
    if isinstance(spec, tuple):
        env_name, conv = spec
        # 用 int() 防御非数字输入；失败时回退到合理的端口号。
        base[key] = _to_int(e(env_name), 9899 if key == 'web_port' else 9898) if conv is int else conv(e(env_name))
    else:
        base[key] = e(spec, '')
with open('config.json', 'w') as f:
    json.dump(base, f, indent=2, ensure_ascii=False)
"

    echo -e "${GREEN}✅ $(t "配置文件创建成功" "Configuration file created successfully").${NC}"
}

# 启动项目
start_project() {
    echo ""
    echo -e "${GREEN}${EMOJI_ROCKET} Starting CowAgent...${NC}"
    sleep 1

    local USE_COW=false
    if command -v cow &> /dev/null; then
        USE_COW=true
    fi

    if $USE_COW; then
        cd "${BASE_DIR}"
        cow start --no-logs
    else
        if [ ! -f "${BASE_DIR}/nohup.out" ]; then
            touch "${BASE_DIR}/nohup.out"
        fi

        OS_TYPE=$(uname)

        if [[ "$OS_TYPE" == "Linux" ]]; then
            nohup setsid $PYTHON_CMD "${BASE_DIR}/app.py" > "${BASE_DIR}/nohup.out" 2>&1 &
            echo -e "${GREEN}${EMOJI_COW} CowAgent started on Linux (using $PYTHON_CMD)${NC}"
        elif [[ "$OS_TYPE" == "Darwin" ]]; then
            nohup $PYTHON_CMD "${BASE_DIR}/app.py" > "${BASE_DIR}/nohup.out" 2>&1 &
            echo -e "${GREEN}${EMOJI_COW} CowAgent started on macOS (using $PYTHON_CMD)${NC}"
        else
            echo -e "${RED}❌ Unsupported OS: ${OS_TYPE}${NC}"
            exit 1
        fi
    fi

    sleep 2
    echo ""
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo -e "${GREEN}${EMOJI_CHECK} $(t "CowAgent 已在后台运行" "CowAgent is now running in background")!${NC}"
    echo -e "${GREEN}${EMOJI_CHECK} $(t "关闭终端后进程仍会继续运行" "Process will continue after closing terminal").${NC}"
    echo -e "${CYAN}$ACCESS_INFO${NC}"

    # 如果跳过模型，请引导用户在 Web 控制台中完成设置。
    if [ "${MODEL_SKIPPED:-}" = "true" ]; then
        local _port="${WEB_PORT:-9899}"
        echo ""
        echo -e "${YELLOW}${EMOJI_WARN} $(t "尚未配置模型，请在 Web 控制台完成配置" "Model not configured yet, please finish setup in the web console"):${NC}"
        echo -e "${CYAN}   http://localhost:${_port}/chat${NC}"
    fi
    echo ""
    echo -e "${CYAN}${BOLD}$(t "管理命令" "Management Commands"):${NC}"
    if $USE_COW; then
        echo -e "  ${GREEN}cow stop${NC}       $(t "停止服务" "Stop the service")"
        echo -e "  ${GREEN}cow restart${NC}    $(t "重启服务" "Restart the service")"
        echo -e "  ${GREEN}cow status${NC}     $(t "查看状态" "Check status")"
        echo -e "  ${GREEN}cow logs${NC}       $(t "查看日志" "View logs")"
        echo -e "  ${GREEN}cow update${NC}     $(t "更新并重启" "Update and restart")"
        echo -e "  ${GREEN}cow install-browser${NC}  $(t "安装浏览器工具" "Install browser tool")"
    else
        echo -e "  ${GREEN}./run.sh stop${NC}       $(t "停止服务" "Stop the service")"
        echo -e "  ${GREEN}./run.sh restart${NC}    $(t "重启服务" "Restart the service")"
        echo -e "  ${GREEN}./run.sh status${NC}     $(t "查看状态" "Check status")"
        echo -e "  ${GREEN}./run.sh logs${NC}       $(t "查看日志" "View logs")"
        echo -e "  ${GREEN}./run.sh update${NC}     $(t "更新并重启" "Update and restart")"
        echo -e "  ${GREEN}cow install-browser${NC}  $(t "安装浏览器工具" "Install browser tool")"
    fi
    echo ""
    echo -e "${YELLOW}$(t "提示：需要让 Agent 浏览网页时，运行 cow install-browser 安装浏览器工具" "Tip: to let the Agent browse the web, run 'cow install-browser' to install the browser tool")${NC}"
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo ""

    echo -e "${YELLOW}$(t "显示最近日志（Ctrl+C 退出，Agent 继续运行）" "Showing recent logs (Ctrl+C to exit, agent keeps running)"):${NC}"
    sleep 2
    tail -n 30 -f "${BASE_DIR}/nohup.out"
}

# 显示用法
show_usage() {
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo -e "${CYAN}${BOLD}   ${EMOJI_COW} CowAgent Management Script${NC}"
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo ""
    echo -e "${YELLOW}$(t "用法" "Usage"):${NC}"
    echo -e "  ${GREEN}./run.sh${NC}               ${CYAN}# $(t "安装/配置项目" "Install/Configure project")${NC}"
    echo -e "  ${GREEN}./run.sh <command>${NC}     ${CYAN}# $(t "执行管理命令" "Execute management command")${NC}"
    echo ""
    echo -e "${YELLOW}$(t "命令" "Commands"):${NC}"
    echo -e "  ${GREEN}start${NC}      $(t "启动服务" "Start the service")"
    echo -e "  ${GREEN}stop${NC}       $(t "停止服务" "Stop the service")"
    echo -e "  ${GREEN}restart${NC}    $(t "重启服务" "Restart the service")"
    echo -e "  ${GREEN}status${NC}     $(t "查看服务状态" "Check service status")"
    echo -e "  ${GREEN}logs${NC}       $(t "查看日志 (tail -f)" "View logs (tail -f)")"
    echo -e "  ${GREEN}config${NC}     $(t "重新配置项目" "Reconfigure project")"
    echo -e "  ${GREEN}update${NC}     $(t "更新并重启" "Update and restart")"
    echo ""
    echo -e "${YELLOW}$(t "示例" "Examples"):${NC}"
    echo -e "  ${GREEN}./run.sh start${NC}"
    echo -e "  ${GREEN}./run.sh logs${NC}"
    echo -e "  ${GREEN}./run.sh status${NC}"
    echo -e "${CYAN}${BOLD}=========================================${NC}"
}

# 确保 PYTHON_CMD 已设置
ensure_python_cmd() {
    if [ -z "$PYTHON_CMD" ]; then
        detect_python_command > /dev/null 2>&1 || PYTHON_CMD="python3"
    fi
}

# 获取服务 PID（如果未运行则为空字符串）
get_pid() {
    ensure_python_cmd > /dev/null 2>&1
    ps ax | grep -i app.py | grep "${BASE_DIR}" | grep "$PYTHON_CMD" | grep -v grep | awk '{print $1}' | grep -E '^[0-9]+$' | head -1
}

# 检查服务是否正在运行
is_running() {
    [ -n "$(get_pid)" ]
}

# 检查cow CLI是否可用
has_cow() {
    command -v cow &> /dev/null
}

# 启动服务
cmd_start() {
    if [ ! -f "${BASE_DIR}/config.json" ]; then
        echo -e "${RED}${EMOJI_CROSS} $(t "未找到 config.json" "config.json not found")${NC}"
        echo -e "${YELLOW}$(t "请先运行 './run.sh' 进行配置" "Please run './run.sh' to configure first")${NC}"
        exit 1
    fi

    if has_cow; then
        cd "${BASE_DIR}"
        cow start
    else
        if is_running; then
            echo -e "${YELLOW}${EMOJI_WARN} $(t "CowAgent 已在运行中" "CowAgent is already running") (PID: $(get_pid))${NC}"
            echo -e "${YELLOW}$(t "使用 './run.sh restart' 重启" "Use './run.sh restart' to restart")${NC}"
            return
        fi
        check_python_version
        start_project
    fi
}

# 停止服务
cmd_stop() {
    # 不要让终止/返回非零（例如进程已经消失）中止
    # `set -e` 下的调用者 (cmd_restart)。
    set +e
    if has_cow; then
        cd "${BASE_DIR}"
        cow stop
    else
        echo -e "${GREEN}${EMOJI_STOP} $(t "正在停止 CowAgent" "Stopping CowAgent")...${NC}"

        if ! is_running; then
            echo -e "${YELLOW}${EMOJI_WARN} $(t "CowAgent 未在运行" "CowAgent is not running")${NC}"
            return 0
        fi

        pid=$(get_pid)
        if [ -z "$pid" ] || ! echo "$pid" | grep -qE '^[0-9]+$'; then
            echo -e "${RED}❌ $(t "获取有效 PID 失败" "Failed to get valid PID") (${pid})${NC}"
            return 0
        fi

        echo -e "${GREEN}$(t "找到运行中的进程" "Found running process") (PID: ${pid})${NC}"

        kill ${pid} 2>/dev/null || true
        sleep 3

        if ps -p ${pid} > /dev/null 2>&1; then
            echo -e "${YELLOW}⚠️  $(t "进程未停止，强制终止" "Process not stopped, forcing termination")...${NC}"
            kill -9 ${pid} 2>/dev/null || true
        fi

        echo -e "${GREEN}${EMOJI_CHECK} $(t "CowAgent 已停止" "CowAgent stopped")${NC}"
    fi
}

# 重启服务
cmd_restart() {
    if has_cow; then
        cd "${BASE_DIR}"
        cow restart
    else
        cmd_stop
        sleep 1
        cmd_start
    fi
}

# 检查状态
cmd_status() {
    if has_cow; then
        cd "${BASE_DIR}"
        cow status
    else
        echo -e "${CYAN}${BOLD}=========================================${NC}"
        echo -e "${CYAN}${BOLD}   ${EMOJI_COW} CowAgent Status${NC}"
        echo -e "${CYAN}${BOLD}=========================================${NC}"

        if is_running; then
            pid=$(get_pid)
            echo -e "${GREEN}$(t "状态" "Status"):${NC} ✅ $(t "运行中" "Running")"
            echo -e "${GREEN}PID:${NC}    ${pid}"
            if [ -f "${BASE_DIR}/nohup.out" ]; then
                echo -e "${GREEN}$(t "日志" "Logs"):${NC}   ${BASE_DIR}/nohup.out"
            fi
        else
            echo -e "${YELLOW}$(t "状态" "Status"):${NC} ⭐ $(t "已停止" "Stopped")"
        fi

        if [ -f "${BASE_DIR}/config.json" ]; then
            # `|| true`：当密钥不存在时（set -e safe），grep 返回 1。
            model=$(grep -o '"model"[[:space:]]*:[[:space:]]*"[^"]*"' "${BASE_DIR}/config.json" 2>/dev/null | cut -d'"' -f4 || true)
            channel=$(grep -o '"channel_type"[[:space:]]*:[[:space:]]*"[^"]*"' "${BASE_DIR}/config.json" 2>/dev/null | cut -d'"' -f4 || true)
            echo -e "${GREEN}$(t "模型" "Model"):${NC}  ${model:-$(t "（未配置）" "(not set)")}"
            echo -e "${GREEN}$(t "渠道" "Channel"):${NC} ${channel:-$(t "（未配置）" "(not set)")}"
        fi

        echo -e "${CYAN}${BOLD}=========================================${NC}"
    fi
}

# 查看日志
cmd_logs() {
    if has_cow; then
        cd "${BASE_DIR}"
        cow logs -f
    else
        if [ -f "${BASE_DIR}/nohup.out" ]; then
            echo -e "${YELLOW}$(t "查看日志（Ctrl+C 退出）" "Viewing logs (Ctrl+C to exit)"):${NC}"
            tail -f "${BASE_DIR}/nohup.out"
        else
            echo -e "${RED}❌ $(t "日志文件未找到" "Log file not found"): ${BASE_DIR}/nohup.out${NC}"
        fi
    fi
}

# 重新配置
cmd_config() {
    # 交互流程：禁用 `set -e`（请参阅 install_mode 了解基本原理）。
    set +e
    # 此会话中所有菜单的一个共享终端句柄。
    menu_session_begin

    # 首先选择语言，以便流程的其余部分本地化。
    select_language
    echo ""
    echo -e "${YELLOW}${EMOJI_WRENCH} $(t "正在重新配置 CowAgent" "Reconfiguring CowAgent")...${NC}"
    
    if [ -f "${BASE_DIR}/config.json" ]; then
        backup_file="${BASE_DIR}/config.json.backup.$(date +%s)"
        cp "${BASE_DIR}/config.json" "${backup_file}"
        echo -e "${GREEN}✅ $(t "已备份配置到" "Backed up config to"): ${backup_file}${NC}"
    fi
    
    check_python_version
    install_dependencies
    select_model
    configure_model
    select_channel
    configure_channel
    menu_session_end
    create_config_file
    
    echo ""
    local restart_now
    tty_read restart_now "$(t "现在重启服务" "Restart service now")? [Y/n]: "
    if [[ ! $restart_now == [Nn]* ]]; then
        cmd_restart
    fi
}

# 更新项目
cmd_update() {
    echo -e "${GREEN}${EMOJI_WRENCH} $(t "正在更新 CowAgent" "Updating CowAgent")...${NC}"
    cd "${BASE_DIR}"
    
    # 首先拉取最新代码（服务仍在运行）
    local pull_ok=false
    if [ -d .git ]; then
        echo -e "${GREEN}🔄 $(t "正在拉取最新代码" "Pulling latest code")...${NC}"
        if git pull; then
            pull_ok=true
        else
            echo -e "${YELLOW}⚠️  $(t "git pull 失败，尝试 Gitee 镜像" "git pull failed, trying Gitee mirror")...${NC}"
            git remote set-url origin https://gitee.com/zhayujie/CowAgent.git
            if git pull; then
                pull_ok=true
            else
                echo -e "${RED}❌ $(t "拉取代码失败，更新已中止" "Failed to pull code. Update aborted").${NC}"
                exit 1
            fi
        fi
    else
        echo -e "${YELLOW}⚠️  $(t "非 git 仓库，跳过代码更新" "Not a git repository, skipping code update")${NC}"
    fi
    
    # 使用更新后的 run.sh 重新执行以获取新逻辑
    exec "$0" _post_update
}

# 更新后：在 git pull 之后由 cmd_update 调用以使用新代码运行
cmd_post_update() {
    cd "${BASE_DIR}"

    # 停止服务
    if is_running; then
        cmd_stop
    fi

    # 重新安装依赖项
    check_python_version
    install_dependencies

    # 重启服务
    cmd_start
}

# 安装方式
install_mode() {
    # 交互流程：禁用 `set -e`，以便单个非零命令（例如
    # 算术 `(( ))` 计算结果为 0，`read` 命中 EOF，或可选
    # 步骤失败）不会默默地中止整个安装程序。
    set +e
    clear
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo -e "${CYAN}${BOLD}   ${EMOJI_COW} CowAgent Installation${NC}"
    echo -e "${CYAN}${BOLD}=========================================${NC}"
    echo ""

    # 为该会话中的所有菜单打开一个共享终端句柄（语言、
    # 型号、渠道）。一个长寿命的 fd 3 可避免每个菜单重新打开问题
    # bash 3.2。在提前返回和配置生成之前关闭。
    menu_session_begin

    # 第 0 步：选择安装/UI 语言。此后的所有内容均已本地化。
    select_language
    echo ""
    sleep 1

    if [ "$IS_PROJECT_DIR" = true ]; then
        echo -e "${GREEN}✅ $(t "检测到已有项目目录" "Detected existing project directory").${NC}"
        
        if [ -f "${BASE_DIR}/config.json" ]; then
            menu_session_end
            echo -e "${GREEN}✅ $(t "项目已配置" "Project already configured")${NC}"
            echo ""
            show_usage
            return
        fi
        
        echo -e "${YELLOW}📝 $(t "未找到 config.json，开始配置项目" "No config.json found. Let's configure your project")!${NC}"
        echo ""
        
        # 项目目录已存在，跳过克隆
        check_python_version
    else
        # 远程安装方式，需要克隆项目
        check_python_version
        clone_project
    fi
    
    # 安装依赖并配置
    install_dependencies
    select_model
    configure_model
    select_channel
    configure_channel
    menu_session_end
    create_config_file
    
    # 配置后自动启动，以获得真正的开箱即用体验。
    echo ""
    start_project
}

# 需要在项目目录内运行
require_project_dir() {
    if [ "$IS_PROJECT_DIR" = false ]; then
        echo -e "${RED}${EMOJI_CROSS} $(t "必须在项目目录下运行" "Must run in project directory")${NC}"
        exit 1
    fi
}

# 为管理命令初始化 UI_LANG：从现有的中选择cow_lang
# config.json，否则回退到环境检测。安装流程
# 稍后通过 select_language() 覆盖它。
init_ui_lang() {
    [ -n "$UI_LANG" ] && return
    local cfg_lang=""
    if [ -f "${BASE_DIR}/config.json" ]; then
        # `|| true`：当cow_lang不存在时，grep返回1，这将中止
        # 第一个管理命令下的 `set -e` 下的整个脚本。
        cfg_lang=$(grep -o '"cow_lang"[[:space:]]*:[[:space:]]*"[^"]*"' "${BASE_DIR}/config.json" 2>/dev/null | cut -d'"' -f4 || true)
    fi
    case "$cfg_lang" in
        zh) UI_LANG="zh" ;;
        en) UI_LANG="en" ;;
        *) UI_LANG=$(detect_ui_lang) ;;
    esac
}

# 主要功能
main() {
    init_ui_lang

    case "$1" in
        start|stop|restart|status|logs|config|update|_post_update)
            require_project_dir
            ;;
    esac

    case "$1" in
        start)   cmd_start ;;
        stop)    cmd_stop ;;
        restart) cmd_restart ;;
        status)  cmd_status ;;
        logs)    cmd_logs ;;
        config)  cmd_config ;;
        update)  cmd_update ;;
        _post_update) cmd_post_update ;;
        help|--help|-h)
            show_usage
            ;;
        "")
            install_mode
            ;;
        *)
            echo -e "${RED}${EMOJI_CROSS} $(t "未知命令" "Unknown command"): $1${NC}"
            echo ""
            show_usage
            exit 1
            ;;
    esac
}

# 执行主函数
main "$@"
