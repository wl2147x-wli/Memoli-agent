# -*- coding: utf-8 -*-

import logging
import os
import signal
import sys
import time

from channel import channel_factory
from common import const
from common.log import logger
from common.ssl_certs import ensure_ca_bundle
from config import load_config, conf
from plugins import *
import threading


_channel_mgr = None

# 桌面模式开关：由 Electron 客户端通过环境变量 COW_DESKTOP=1 开启。
# 该模式下差异有三处：插件在后台线程加载（cow_cli/godcmd 等命令
# 插件依然可用，又不拖慢启动）、跳过 MCP 预热（桌面环境没有
# npx/uvx 运行时）、调度器预热让位给 Web API 就绪。
DESKTOP_MODE = os.environ.get("COW_DESKTOP") == "1"


# ---------------------------------------------------------------------------
# 返回全局通道管理器单例。
# 返回值：ChannelManager 实例；run() 尚未执行到初始化处时为 None。
# ---------------------------------------------------------------------------
def get_channel_manager():
    return _channel_mgr


# ---------------------------------------------------------------------------
# 把 channel_type 配置值解析为通道名列表。
# 支持三种写法：单个字符串 "feishu"、逗号分隔字符串 "feishu, dingtalk"、
# 列表 ["feishu", "dingtalk"]；其余类型（含 None）一律返回空列表。
# ---------------------------------------------------------------------------
def _parse_channel_type(raw) -> list:
    """
    把 channel_type 配置值解析为通道名列表。
    支持三种写法：
      - 单个字符串："feishu"
      - 逗号分隔字符串："feishu, dingtalk"
      - 列表：["feishu", "dingtalk"]
    """
    if isinstance(raw, list):
        return [ch.strip() for ch in raw if ch.strip()]
    if isinstance(raw, str):
        return [ch.strip() for ch in raw.split(",") if ch.strip()]
    return []


# ---------------------------------------------------------------------------
# 判断启动列表中是否已包含 Web 控制台。
# 列表元素可能是旧版通道名字符串，也可能是 ChannelInstance 实例，
# 两种形态都要检查，避免误判导致 Web 控制台被重复启动。
# ---------------------------------------------------------------------------
def _has_web_entry(channel_names: list) -> bool:
    """启动列表中已包含 Web 控制台时返回 True（元素为字符串或 ChannelInstance 均可）。"""
    from channel.channel_instances import ChannelInstance
    for entry in channel_names:
        if isinstance(entry, ChannelInstance):
            if entry.channel_type == "web":
                return True
        elif entry == "web":
            return True
    return False


# ---------------------------------------------------------------------------
# 计算本次启动要拉起的通道列表 = config.json 的 channel_type
# + team.json 的 channel_instances，并按通道类型去重。
# 规则：config.json 配置的通道照常启动；已被 channel_instances 接管的
# 多实例类型（如 feishu）从扁平条目中剔除，避免同一机器人被启动两次；
# 旧版安装（无 team.json）则原样返回 _parse_channel_type 的结果。
# 返回值：通道名字符串与 ChannelInstance 混合的列表；全空时兜底 ["web"]。
# ---------------------------------------------------------------------------
def _resolve_startup_channels(raw_channel):
    """启动通道列表 = config.json 的通道配置 + team.json 的实例记录，
    并对支持多实例的通道类型按“类型”去重。

    config.json 所配置的内容仍以它为事实来源：其中的 ``channel_type``
    列表（dingtalk、wecom 等）总是照常启动，与旧版安装的行为完全一致。
    team.json 的 ``channel_instances`` 承载显式配置的多实例机器人
    （目前是 feishu），每个实例都有自己的凭证和代理绑定。

    微妙之处在 feishu：config.json 的扁平 ``feishu`` 条目与
    ``channel_instances`` 里的 feishu 记录是*同一种连接*。一旦 team.json
    接管 feishu（存在至少一个 feishu 实例），feishu 的事实来源就只有
    ``channel_instances``——扁平配置条目会被丢弃，以免同一个机器人在
    同一条 websocket 上被启动两次。无论实例绑定到哪个代理，这条规则
    都成立：把所有 feishu 实例重新绑定到非默认代理时，也绝不能让
    config.json 的 feishu 以“游离的默认绑定机器人”身份复活。
    非多实例类型永远不会被实例接管，config.json 继续照常启动它们。

    旧版单代理安装没有 team.json / channel_instances，此时本函数
    的返回值与以前的 ``_parse_channel_type(raw_channel)`` 完全一致。
    """
    from channel.channel_instances import MULTI_INSTANCE_READY, _normalize_type

    names = _parse_channel_type(raw_channel)

    instances = []
    try:
        from agent import team
        from channel.channel_instances import resolve_channel_instances

        settings = team.resolve(conf())
        raw_instances = settings.get("channel_instances")
        if isinstance(raw_instances, list) and raw_instances:
            instances = resolve_channel_instances(settings)
    except Exception as e:
        logger.warning(
            f"[App] Failed to resolve channel_instances, using config.json "
            f"channel_type only: {e}"
        )
        instances = []

    # 这些通道类型现在由 channel_instances（feishu 等）接管。
    # 从 config.json 的扁平条目中剔除它们，让实例记录成为唯一事实来源。
    managed_types = {
        inst.channel_type
        for inst in instances
        if inst.channel_type in MULTI_INSTANCE_READY
    }

    entries = []
    for name in names:
        if _normalize_type(name) in managed_types:
            logger.info(
                f"[App] channel_type '{name}' is managed by channel_instances; "
                f"skipping the flat config.json entry to avoid a duplicate bot"
            )
            continue
        entries.append(name)

    if instances:
        logger.info(
            f"[App] Starting channel_instances: "
            f"{[(i.instance_id, i.channel_type, i.agent_id) for i in instances]}"
        )
        entries.extend(instances)

    if not entries:
        entries = ["web"]
    return entries


class ChannelManager:
    """
    管理多个并发运行通道的生命周期。
    每个通道的 startup() 都在自己的守护线程中运行。
    除非显式禁用，Web 控制台会作为默认控制台自动启动。
    """

    # -----------------------------------------------------------------------
    # 构造函数：只初始化空的注册表与锁，不启动任何通道。
    # _channels/_threads 以通道名（普通类型）或 instance_id（多实例）为键。
    # -----------------------------------------------------------------------
    def __init__(self):
        # 两个注册表都以通道名（普通类型）或 instance_id（多实例类型）为键
        self._channels = {}        # 通道名/实例 id -> 通道实例
        self._threads = {}         # 通道名/实例 id -> 对应启动线程
        self._primary_channel = None
        self._lock = threading.Lock()
        self.cloud_mode = False    # 云客户端（LinkAI 云部署）接管时置 True，并透传给各通道

    # -----------------------------------------------------------------------
    # 兼容旧代码的只读属性：返回主通道（第一个启动的非 web 通道）。
    # -----------------------------------------------------------------------
    @property
    def channel(self):
        """兼容旧代码：返回主通道（第一个启动的非 web 通道）。"""
        return self._primary_channel

    # -----------------------------------------------------------------------
    # 按名称（或实例 id）查询已注册的通道实例；未找到返回 None。
    # -----------------------------------------------------------------------
    def get_channel(self, channel_name: str):
        return self._channels.get(channel_name)

    # -----------------------------------------------------------------------
    # 把启动列表条目统一成 (名称, 通道类型, 工厂参数) 三元组。
    # 字符串条目按旧版行为处理：名称即类型、无额外参数；
    # ChannelInstance 条目以 instance_id 为注册表键，并把该实例自己的
    # 凭证与代理绑定传给工厂，使同一类型的多实例可以共存。
    # -----------------------------------------------------------------------
    @staticmethod
    def _normalize_entry(entry):
        """同时接受旧版通道类型字符串和 ChannelInstance 两种条目。

        返回 (name, channel_type, factory_kwargs)。对普通字符串，行为与
        旧版完全一致：name 即 channel_type，且没有实例级覆盖参数。对
        ChannelInstance，注册表键为 instance_id，工厂会收到该实例的
        凭证与绑定信息，从而让同一类型的多个实例可以共存。
        """
        from channel.channel_instances import ChannelInstance

        if isinstance(entry, ChannelInstance):
            return (
                entry.instance_id,
                entry.channel_type,
                {
                    "instance_id": entry.instance_id,
                    "bound_agent_id": entry.agent_id,
                    "credentials": entry.credentials or None,
                    "members": entry.members or None,
                },
            )
        return (entry, entry, {})

    # -----------------------------------------------------------------------
    # 创建并以子线程方式启动一批通道。
    # 流程：规范化条目 -> 停掉同名旧通道 -> 逐个实例化（实例化失败的
    # 跳过，不拖垮其它通道）-> 首次启动时装载插件、按需拉起云客户端
    # -> Web 控制台最先启动，其余通道错开 0.1 秒逐个起线程。
    # 参数：channel_names 为通道名字符串或 ChannelInstance 的列表；
    #       first_start=True 时执行仅进程启动阶段需要的一次性初始化
    #       （插件装载、云客户端），热重启/动态添加时传 False。
    # -----------------------------------------------------------------------
    def start(self, channel_names: list, first_start: bool = False):
        """
        在子线程中创建并启动一个或多个通道。
        first_start 为 True 时，插件与 LinkAI 云客户端也会一并初始化。

        每个条目可以是旧版通道类型字符串，也可以是 ChannelInstance。
        """
        entries = [self._normalize_entry(e) for e in channel_names]

        # 并发路径可能已经启动了同名通道（例如保存配置触发了重启，
        # 由它自行拉起）。直接覆盖注册表条目会把旧实例变成孤儿：
        # 没有任何东西再持有它，它会保持连接、持续消耗事件，导致
        # 每条入站消息被处理两次。因此先显式 stop 旧实例再注册。
        for name, _ctype, _kw in entries:
            if self._channels.get(name) is not None:
                logger.warning(f"[ChannelManager] Channel '{name}' is already running, stopping it first")
                self.stop(name)

        with self._lock:
            channels = []
            for name, channel_type, factory_kwargs in entries:
                # 配置错误的通道（例如 wechatcom_app 缺少
                # corp_id/token/aes_key）绝不能拖垮整个启动流程：
                # 实例化时可能因解析配置而抛异常。尤其是 Web 控制台
                # 必须能起来，桌面外壳才有地方展示错误、让用户修复
                # 配置。因此跳过损坏的通道，保住其余部分。
                try:
                    ch = channel_factory.create_channel(channel_type, **factory_kwargs)
                except Exception as e:
                    logger.error(f"[ChannelManager] Failed to create channel '{name}', skipping it: {e}")
                    logger.exception(e)
                    continue
                ch.cloud_mode = self.cloud_mode
                self._channels[name] = ch
                channels.append((name, ch))
                if self._primary_channel is None and name != "web":
                    self._primary_channel = ch

            if self._primary_channel is None and channels:
                self._primary_channel = channels[0][1]

            if first_start:
                if DESKTOP_MODE:
                    # 在后台线程加载插件，让命令插件（cow_cli / godcmd，
                    # 如 /status、#help）在桌面客户端里照常可用，
                    # 又不阻塞 Web 服务就绪。
                    threading.Thread(
                        target=PluginManager().load_plugins, daemon=True
                    ).start()
                else:
                    PluginManager().load_plugins()

                # 云客户端是可选的。它仅在以下情况下启动
                # use_linkai=True 且 cloud_deployment_id 已设置。
                # 默认情况下，两者均未配置，因此应用程序运行
                # 完全在本地，无需任何远程连接。
                if conf().get("use_linkai") and (
                    os.environ.get("CLOUD_DEPLOYMENT_ID") or conf().get("cloud_deployment_id")
                ):
                    try:
                        from common import cloud_client
                        threading.Thread(
                            target=cloud_client.start,
                            args=(self._primary_channel, self),
                            daemon=True,
                        ).start()
                    except Exception:
                        pass

            # Web 控制台排在最前启动，让它尽早完成绑定（桌面模式下的
            # 看门狗正在等它就绪）；其余通道之间错开 0.1 秒，避免
            # 同时抢初始化资源。
            web_entry = None
            other_entries = []
            for entry in channels:
                if entry[0] == "web":
                    web_entry = entry
                else:
                    other_entries.append(entry)

            ordered = ([web_entry] if web_entry else []) + other_entries
            for i, (name, ch) in enumerate(ordered):
                if i > 0 and name != "web":
                    time.sleep(0.1)
                t = threading.Thread(target=self._run_channel, args=(name, ch), daemon=True)
                self._threads[name] = t
                t.start()
                logger.debug(f"[ChannelManager] Channel '{name}' started in sub-thread")

    # -----------------------------------------------------------------------
    # 通道线程的入口：调用 channel.startup() 并捕获一切异常。
    # 桌面模式下 Web 通道启动失败属于致命错误：直接以非零码退出，
    # 让 Electron 外壳立即显示真实错误，而不是等健康检查超时。
    # -----------------------------------------------------------------------
    def _run_channel(self, name: str, channel):
        try:
            channel.startup()
        except Exception as e:
            logger.error(f"[ChannelManager] Channel '{name}' startup error: {e}")
            logger.exception(e)
            # 桌面客户端就是 Web 通道：没有它，Electron 外壳会一直
            # 轮询一个永远不会应答的健康检查端点，90 秒后才把原因
            # 归咎于笼统的“初始化失败”。以非零码退出，让外壳立即
            # 显示真正的错误。服务器部署保留旧行为——其余通道可能
            # 仍在正常服务，因此单个通道损坏不应中断整个进程。
            if DESKTOP_MODE and name == "web":
                logging.shutdown()
                os._exit(1)

    # -----------------------------------------------------------------------
    # 停止指定通道（channel_name 为空时停止全部）并清理注册表。
    # 顺序：锁内弹出注册表条目 -> 锁外依次尝试 ch.stop() 优雅停止
    # -> 等线程 5 秒；仍未退出的，优雅停止过就放任守护线程自行收尾，
    # 否则注入异常强制中断。
    # -----------------------------------------------------------------------
    def stop(self, channel_name: str = None):
        """
        停止通道。给出 channel_name 时只停止该通道；
        否则停止全部通道。
        """
        # 先在锁内把注册表条目弹出，再到锁外执行实际停止：
        # channel.stop()/线程 join 可能耗时甚至回调回本管理器，
        # 若持锁执行会死锁。
        with self._lock:
            names = [channel_name] if channel_name else list(self._channels.keys())
            to_stop = []
            for name in names:
                ch = self._channels.pop(name, None)
                th = self._threads.pop(name, None)
                to_stop.append((name, ch, th))
            if channel_name and self._primary_channel is self._channels.get(channel_name):
                self._primary_channel = None

        for name, ch, th in to_stop:
            if ch is None:
                logger.warning(f"[ChannelManager] Channel '{name}' not found in managed channels")
                if th and th.is_alive():
                    self._interrupt_thread(th, name)
                continue
            logger.info(f"[ChannelManager] Stopping channel '{name}'...")
            graceful = False
            if hasattr(ch, 'stop'):
                try:
                    ch.stop()
                    graceful = True
                except Exception as e:
                    logger.warning(f"[ChannelManager] Error during channel '{name}' stop: {e}")
            if th and th.is_alive():
                th.join(timeout=5)
                if th.is_alive():
                    if graceful:
                        logger.info(f"[ChannelManager] Channel '{name}' thread still alive after stop(), "
                                    "leaving daemon thread to finish on its own")
                    else:
                        logger.warning(f"[ChannelManager] Channel '{name}' thread did not exit in 5s, forcing interrupt")
                        self._interrupt_thread(th, name)

    # -----------------------------------------------------------------------
    # 向目标线程注入 SystemExit 异常，打破 start_forever 之类的阻塞循环。
    # 仅在优雅停止失效时使用；注入失败会回滚并记录警告，
    # 绝不让清理流程本身抛异常。
    # -----------------------------------------------------------------------
    @staticmethod
    def _interrupt_thread(th: threading.Thread, name: str):
        """向目标线程注入 SystemExit，打破 start_forever 之类的阻塞循环。"""
        import ctypes
        try:
            tid = th.ident
            if tid is None:
                return
            res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
                ctypes.c_ulong(tid), ctypes.py_object(SystemExit)
            )
            if res == 1:
                logger.info(f"[ChannelManager] Interrupted thread for channel '{name}'")
            elif res > 1:
                ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), None)
                logger.warning(f"[ChannelManager] Failed to interrupt thread for channel '{name}'")
        except Exception as e:
            logger.warning(f"[ChannelManager] Thread interrupt error for '{name}': {e}")

    # -----------------------------------------------------------------------
    # 重启单个通道：stop -> 清空单例缓存 -> 等待 1 秒释放端口/资源
    # -> 重新 start。可从任意线程调用（如远程配置保存后的回调）。
    # 传入裸通道名时，先尝试从名册文件找回对应的 ChannelInstance
    # 记录，使重启保留该实例原有的绑定与凭证，而不是退回全局配置。
    # -----------------------------------------------------------------------
    def restart(self, new_channel):
        """
        重启单个通道。
        可从任意线程调用（例如远程配置保存后的回调）。

        接受通道类型字符串或 ChannelInstance。当裸字符串对应某个
        已登记的显式实例时，会查回其记录（绑定 + 凭证），使重启
        保留原有身份，而不是退回旧版的全局配置路径。
        """
        from channel.channel_instances import ChannelInstance

        entry = new_channel
        if not isinstance(entry, ChannelInstance):
            entry = self._resolve_instance_entry(new_channel) or new_channel
        name = entry.instance_id if isinstance(entry, ChannelInstance) else entry
        logger.info(f"[ChannelManager] Restarting channel '{name}'...")
        self.stop(name)
        _clear_singleton_cache(name)
        time.sleep(1)
        self.start([entry], first_start=False)
        logger.info(f"[ChannelManager] Channel '{name}' restarted successfully")

    # -----------------------------------------------------------------------
    # 按名称查找已登记的 ChannelInstance 记录；不存在返回 None。
    # 用于让“以裸 id 触发的重启/添加”能恢复该实例的代理绑定与凭证；
    # 名册缺失（旧版安装）时返回 None，调用方退回旧版全局配置路径。
    # 任何异常都吞掉并返回 None，绝不影响重启主流程。
    # -----------------------------------------------------------------------
    @staticmethod
    def _resolve_instance_entry(name: str):
        """返回为 *name* 登记的 ChannelInstance 记录，没有则返回 None。

        让以裸 id 触发的重启/添加能从名册文件恢复该实例的绑定与
        凭证。名册缺失（旧版安装）时返回 None，调用方保持原来的
        纯字符串行为。
        """
        try:
            from config import conf
            from channel.channel_instances import get_instance
            return get_instance(conf(), name)
        except Exception:
            return None

    # -----------------------------------------------------------------------
    # 动态添加并启动一个新通道；同名通道已在运行时改为重启。
    # channel 可以是旧版通道名字符串（凭证取自全局配置），也可以是
    # 自带 id/绑定/凭证的 ChannelInstance（同类型多实例之一）。
    # -----------------------------------------------------------------------
    def add_channel(self, channel):
        """
        动态添加并启动一个新通道；若通道已在运行，则改为重启。

        ``channel`` 可以是旧版通道类型字符串（单实例，凭证读自全局
        配置），也可以是自带 id、绑定与凭证的 ChannelInstance
        （同一类型多个实例之一）。
        """
        from channel.channel_instances import ChannelInstance

        channel_name = (
            channel.instance_id if isinstance(channel, ChannelInstance) else channel
        )
        with self._lock:
            if channel_name in self._channels:
                logger.info(f"[ChannelManager] Channel '{channel_name}' already exists, restarting")
        if self._channels.get(channel_name):
            self.restart(channel_name)
            return
        logger.info(f"[ChannelManager] Adding channel '{channel_name}'...")
        _clear_singleton_cache(channel_name)
        self.start([channel], first_start=False)
        logger.info(f"[ChannelManager] Channel '{channel_name}' added successfully")

    # -----------------------------------------------------------------------
    # 动态停止并移除一个运行中的通道；通道不存在时只告警、不做任何事。
    # -----------------------------------------------------------------------
    def remove_channel(self, channel_name: str):
        """
        动态停止并移除一个运行中的通道。
        """
        with self._lock:
            if channel_name not in self._channels:
                logger.warning(f"[ChannelManager] Channel '{channel_name}' not found, nothing to remove")
                return
        logger.info(f"[ChannelManager] Removing channel '{channel_name}'...")
        self.stop(channel_name)
        logger.info(f"[ChannelManager] Channel '{channel_name}' removed successfully")


# ---------------------------------------------------------------------------
# 清空指定通道类的单例缓存，使下次创建实例时按最新配置重建。
# 通道类大多是“工厂闭包 + 单例字典”的写法：这里通过遍历闭包单元格
# 找到那个字典并清空。未登记的通道名直接跳过；任何失败只告警，
# 不影响重启流程本身。
# ---------------------------------------------------------------------------
def _clear_singleton_cache(channel_name: str):
    """
    清空通道类的单例缓存，以便按更新后的配置创建新实例。
    """
    cls_map = {
        "web": "channel.web.web_channel.WebChannel",
        "wechatmp": "channel.wechatmp.wechatmp_channel.WechatMPChannel",
        "wechatmp_service": "channel.wechatmp.wechatmp_channel.WechatMPChannel",
        "wechatcom_app": "channel.wechatcom.wechatcomapp_channel.WechatComAppChannel",
        const.WECHAT_KF: "channel.wechat_kf.wechat_kf_channel.WechatKfChannel",
        const.FEISHU: "channel.feishu.feishu_channel.FeiShuChanel",
        const.DINGTALK: "channel.dingtalk.dingtalk_channel.DingTalkChanel",
        const.WECOM_BOT: "channel.wecom_bot.wecom_bot_channel.WecomBotChannel",
        const.QQ: "channel.qq.qq_channel.QQChannel",
        const.TELEGRAM: "channel.telegram.telegram_channel.TelegramChannel",
        const.SLACK: "channel.slack.slack_channel.SlackChannel",
        const.DISCORD: "channel.discord.discord_channel.DiscordChannel",
        const.WEIXIN: "channel.weixin.weixin_channel.WeixinChannel",
        "wx": "channel.weixin.weixin_channel.WeixinChannel",
    }
    module_path = cls_map.get(channel_name)
    if not module_path:
        return
    try:
        parts = module_path.rsplit(".", 1)
        module_name, class_name = parts[0], parts[1]
        import importlib
        module = importlib.import_module(module_name)
        wrapper = getattr(module, class_name, None)
        if wrapper and hasattr(wrapper, '__closure__') and wrapper.__closure__:
            for cell in wrapper.__closure__:
                try:
                    cell_contents = cell.cell_contents
                    if isinstance(cell_contents, dict):
                        cell_contents.clear()
                        logger.debug(f"[ChannelManager] Cleared singleton cache for {class_name}")
                        break
                except ValueError:
                    pass
    except Exception as e:
        logger.warning(f"[ChannelManager] Failed to clear singleton cache: {e}")


# ---------------------------------------------------------------------------
# 注册信号处理器：收到 SIGINT/SIGTERM 时先保存用户数据，再退出进程。
# 若此前已注册过同号信号处理器，则先链式调用旧处理器、保留其原有
# 行为；没有旧处理器时直接 sys.exit(0)。
# ---------------------------------------------------------------------------
def sigterm_handler_wrap(_signo):
    old_handler = signal.getsignal(_signo)

    # 内层：真正的信号处理体；参数为信号处理器标准签名（信号号, 栈帧）。
    def func(_signo, _stack_frame):
        logger.info("signal {} received, exiting...".format(_signo))
        conf().save_user_datas()
        if callable(old_handler):  # 若此前已注册过处理器，则链式调用，不抢占原有行为
            return old_handler(_signo, _stack_frame)
        sys.exit(0)

    signal.signal(_signo, func)


# ---------------------------------------------------------------------------
# 进程启动阶段后台预热所有已启用代理的 MCP 工具，让 npx/uvx 等子进程
# 在第一条用户消息到来之前完成初始化。本函数立即返回，实际加载发生在
# ToolManager 内部的线程里；MCP 未配置时调用同样安全。
# 必须逐代理（带 identity_scope 身份作用域）预热：否则只有默认代理的
# 服务器会就绪，其余代理要等到各自的第一条消息才开始启动。
# ---------------------------------------------------------------------------
def _warmup_mcp_tools():
    """
    在进程启动时就启动 MCP 服务器加载，让子进程（npx / uvx 等）
    在第一条用户消息到达之前完成初始化。本函数立即返回——实际工作
    由 ToolManager 内部的守护线程完成。MCP 未配置时调用同样安全。

    会为每个已启用的代理预热：本函数在任何路由发生之前运行，
    若不做这个循环，就只有默认代理的服务器会就绪，其余代理只能
    等到各自的第一条消息才开始启动。
    """
    try:
        from agent.registry import get_agent_registry
        from agent.tools import ToolManager
        from common.runtime_identity import identity_scope

        profiles = get_agent_registry().list(include_disabled=False)
    except Exception as e:
        logger.warning(f"[App] MCP warmup failed (non-fatal): {e}")
        return

    for profile in profiles:
        # 在每个代理的身份作用域内分别预热，让 ToolManager 读取到
        # 各自的 mcp.json；单个代理的配置损坏只影响它自己，
        # 不会妨碍其余代理的预热。
        try:
            with identity_scope(agent_id=profile.id):
                ToolManager()._load_mcp_tools()
        except Exception as e:
            logger.warning(f"[App] MCP warmup failed for '{profile.id}' (non-fatal): {e}")


# ---------------------------------------------------------------------------
# 在主线程上预解析调度器的依赖导入图，规避多线程导入死锁。
# 原因：Python 按模块加锁导入，两个线程以相反顺序遍历重叠的依赖图
# 会直接死锁——调度器预热走 agent.tools -> requests -> urllib3，
# 通道创建走 web_channel -> web -> http.client -> email，两图相交。
# 桌面模式在后台线程预热，因此相关模块必须在该线程创建之前
# 就已进入 sys.modules，之后它只构建对象、不再触发导入。
# ---------------------------------------------------------------------------
def _preload_heavy_imports():
    """在主线程上预解析调度器的导入依赖图。

    Python 对模块导入按模块加锁，两个线程以相反顺序遍历重叠的
    依赖图会直接死锁：调度器预热拉取 agent.tools -> requests ->
    urllib3，而通道创建拉取 web_channel -> web -> http.client ->
    email，两条链路恰好相交。桌面模式的预热在后台线程进行，
    因此相关模块必须在该线程创建之前就已在 sys.modules 中——
    之后它只构建对象、不再触发导入。
    """
    try:
        from bridge.bridge import Bridge  # noqa: F401
    except Exception as e:
        logger.warning(f"[App] Import preload failed (non-fatal): {e}")


WEB_STARTUP_TIMEOUT = 25


# ---------------------------------------------------------------------------
# 启动 Web 启动看门狗：SERVING 事件在 timeout 秒内未被置位，就转储
# 全部线程堆栈并以非零码退出。
# 为什么需要它：通道启动“崩溃”已有兜底，但“卡死”过去会让进程永远
# 存活——Electron 外壳等完自己的超时、报一个笼统的“初始化失败”，
# 而僵死的后端一直驻留，每次启动尝试都会多攒一个。转储堆栈让这类
# 卡死能直接从日志定位，而不是靠猜。
# ---------------------------------------------------------------------------
def _start_web_watchdog(timeout: int = WEB_STARTUP_TIMEOUT):
    """Web 控制台在 ``timeout`` 秒内未完成端口绑定则退出进程。

    通道启动“崩溃”已有退出兜底，但“卡死”过去会让进程永远存活：
    Electron 外壳等完自己的超时、把原因归咎于笼统的“初始化失败”，
    而僵死的后端一直驻留——每尝试启动一次就多攒一个。转储全部
    线程堆栈，让这类卡死下次能从日志直接定位，而不是靠猜。
    """
    # 在这里、也就是主线程上导入：后台线程绝不能承担
    # 首次导入这些模块的开销（参见 _preload_heavy_imports）。
    import faulthandler
    from channel.web.web_channel import SERVING

    # 内层：看门狗线程体。SERVING 就绪则静默返回；超时则记日志、
    # 转储所有线程堆栈并强制退出进程（os._exit 绕过一切清理钩子）。
    def _watch():
        if SERVING.wait(timeout):
            return
        logger.error(
            f"[App] Web console did not start within {timeout}s, exiting. "
            "Thread stacks follow:"
        )
        try:
            faulthandler.dump_traceback()
        except Exception:
            pass
        logging.shutdown()
        os._exit(1)

    threading.Thread(target=_watch, daemon=True).start()


# ---------------------------------------------------------------------------
# 急切初始化 AgentBridge，让调度器线程随进程启动而就绪，
# 而不是等到第一条用户消息到来才启动（届时 cron 任务会白白延迟）。
# ---------------------------------------------------------------------------
def _warmup_scheduler():
    """急切初始化 AgentBridge，让调度器线程随进程启动而就绪，
    而不是等到第一条用户消息到来才启动。"""
    try:
        from bridge.bridge import Bridge
        Bridge().get_agent_bridge()
    except Exception as e:
        logger.warning(f"[App] Scheduler warmup failed: {e}")


# ---------------------------------------------------------------------------
# 把仍存在 config.json 里的团队名册迁移到独立的 team 文件。
# 之所以放在启动入口而不是控制台下次编辑时：这里是全进程唯一
# 单线程、且任何代码尚未读取注册表的位置；迁移完成之前，名册
# 随时可能被某个整体重写 config.json 的调用方覆盖掉。
# ---------------------------------------------------------------------------
def _migrate_team_roster():
    """把仍保存在 config.json 中的团队名册迁移到独立的 team 文件。

    之所以放在这里而不是等控制台下次编辑时执行：网关启动是唯一
    单线程运行、且任何代码尚未读取注册表的时机；在迁移完成之前，
    名册随时可能被某个整体重写 config.json 的调用方覆盖掉。
    """
    try:
        import os

        from agent import team
        from config import conf, get_data_root

        team.migrate(conf(), os.path.join(get_data_root(), "config.json"))
    except Exception as e:
        # 迁移失败不阻断启动：team.resolve 读取名册时仍会回退到 config.json。
        logger.warning(f"[App] Could not move the roster into its own file: {e}")


# ---------------------------------------------------------------------------
# 检查旧版默认工作区 ~/cow 是否残留数据；与当前配置的 agent_workspace
# 不一致时在日志中告警（例如用户改了 agent_workspace 却没有搬走旧
# 目录的内容）。否则新工作区看起来像空目录，用户却无从知道原因。
# 只提示、不自动迁移——数据是否保留由用户手工决定。
# ---------------------------------------------------------------------------
def _warn_if_legacy_workspace_data_exists():
    """
    当硬编码的 ~/cow 默认目录中存在 agent_workspace 没有的数据时
    发出告警——例如修改了 agent_workspace 却没有搬走旧目录的内容。
    否则新工作区会看起来像空目录，而用户无从知道原因。
    """
    try:
        from common.state_dir import state_root_str
        from common.utils import expand_path
        workspace_root = state_root_str()
        legacy_root = expand_path("~/cow")
        # samefile 比较的是文件系统身份，因此能正确处理大小写
        # 不敏感的文件系统（Windows 与 macOS 的默认情况）——
        # 但仅靠 os.path.normcase 不够，它只能折叠 Windows 的
        # 大小写。任一路径尚不存在时走兜底（samefile 要求两者都存在）。
        try:
            same = os.path.samefile(legacy_root, workspace_root)
        except OSError:
            same = os.path.normcase(os.path.realpath(legacy_root)) == os.path.normcase(os.path.realpath(workspace_root))
        if same:
            return
        # 任何可见条目都算数——会话/技能/记忆等都在此列。隐藏条目
        # 一律忽略，这样 .DS_Store 之类的系统噪音不会每次启动都触发警告。
        leftovers = os.listdir(legacy_root) if os.path.isdir(legacy_root) else []
        if any(not name.startswith(".") for name in leftovers):
            logger.warning(
                f"[App] Found existing data at the default workspace ({legacy_root}) "
                f"that doesn't match your configured agent_workspace ({workspace_root}). "
                f"It is not migrated automatically - if it has session history, memory, "
                f"or skills you want to keep, move it into {workspace_root} manually."
            )
    except Exception as e:
        logger.warning(f"[App] Legacy workspace check failed: {e}")


# ---------------------------------------------------------------------------
# 把项目 skills/ 目录下的内置技能同步到每个已启用代理的工作区，
# 避免新配置的代理“天生”没有技能可用。
# 同步策略：目标已存在则先删后拷，以内置版本为准（每次启动对齐）。
# ---------------------------------------------------------------------------
def _sync_builtin_skills():
    """把项目 skills/ 中的内置技能同步到每个已启用代理的工作区，
    避免新配置的代理一出生就没有技能可用。"""
    import shutil
    try:
        from agent.registry import get_agent_registry
        from common.runtime_identity import RuntimeIdentity
        from common.state_dir import skills_dir

        project_root = os.path.dirname(os.path.abspath(__file__))
        builtin_dir = os.path.join(project_root, "skills")
        if not os.path.isdir(builtin_dir):
            return

        for profile in get_agent_registry().list(include_disabled=False):
            custom_dir = str(
                skills_dir(RuntimeIdentity(agent_id=profile.id), ensure=True)
            )
            synced = 0
            for name in os.listdir(builtin_dir):
                src = os.path.join(builtin_dir, name)
                if not os.path.isdir(src) or not os.path.isfile(os.path.join(src, "SKILL.md")):
                    continue
                dst = os.path.join(custom_dir, name)
                try:
                    if os.path.isdir(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                    synced += 1
                except Exception as e:
                    logger.warning(f"[App] Failed to sync builtin skill '{name}': {e}")
            if synced:
                logger.info(
                    f"[App] Synced {synced} builtin skill(s) to workspace of "
                    f"agent '{profile.id}'"
                )
    except Exception as e:
        logger.warning(f"[App] Builtin skills sync failed: {e}")


# ---------------------------------------------------------------------------
# 为每个已启用代理铺设 subagents/ 目录的指南与示例类型，
# 让用户创建子代理时有可参照的模板。
# 与内置技能不同：这里只在目标文件缺失时写入一次、不做覆盖同步，
# 用户对模板的修改或删除都会被保留。子代理功能未启用时不建目录。
# ---------------------------------------------------------------------------
def _scaffold_subagent_assets():
    """在每个已启用代理的 subagents/ 目录中铺设指南和示例类型，
    让用户创建子代理时有可以照抄的模板。

    仅在功能启用时执行：从不启用子代理的安装不应凭空长出目录。
    文件采用“缺失才写入”而非像技能那样同步覆盖，因此用户对模板
    的修改或删除都会被保留。
    """
    import shutil
    try:
        from agent.registry import get_agent_registry
        from agent.subagent import SubagentSettings
        from common.runtime_identity import RuntimeIdentity
        from common.state_dir import subagents_dir

        if not SubagentSettings.from_config().enabled:
            return

        asset_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "agent", "subagent", "assets"
        )
        if not os.path.isdir(asset_dir):
            return

        for profile in get_agent_registry().list(include_disabled=False):
            target_dir = subagents_dir(RuntimeIdentity(agent_id=profile.id), ensure=True)
            written = 0
            for name in sorted(os.listdir(asset_dir)):
                src = os.path.join(asset_dir, name)
                target = target_dir / name
                if not os.path.isfile(src) or target.exists():
                    continue
                try:
                    shutil.copyfile(src, target)
                    written += 1
                except Exception as e:
                    logger.warning(f"[App] Failed to write sub agent asset '{name}': {e}")
            if written:
                logger.info(
                    f"[App] Seeded {written} sub agent file(s) in workspace of "
                    f"agent '{profile.id}'"
                )
    except Exception as e:
        logger.warning(f"[App] Sub agent scaffold failed: {e}")


# ---------------------------------------------------------------------------
# 进程主入口：按依赖顺序完成启动，然后无限循环保活。
# 顺序刻意安排如下：CA 证书（先于一切 TLS 连接）-> 加载配置 ->
# 迁移团队名册 -> 检查旧工作区残留 -> 注册信号处理 -> 解析启动通道
# （含多实例展开与 Web 控制台补齐）-> 同步内置技能/子代理模板 ->
# 预热 MCP 与调度器 -> 启动全部通道。
# 桌面模式下任何未捕获的启动异常都以非零码退出，让外壳显示真实
# 错误并停止重试；Ctrl+C 静默退出。
# ---------------------------------------------------------------------------
def run():
    global _channel_mgr
    try:
        # 必须在任何 TLS 连接建立之前执行：PyInstaller 打包版没有
        # 系统 OpenSSL CA 存储，需要改用 certifi 的证书包。
        bundle = ensure_ca_bundle()
        if bundle:
            logger.debug(f"[App] using certifi CA bundle: {bundle}")
        # 加载 config.json 等配置，后续所有 conf() 调用都依赖它
        load_config()
        _migrate_team_roster()
        _warn_if_legacy_workspace_data_exists()
        # Ctrl+C（SIGINT）：走包装过的处理器，退出前先保存用户数据
        sigterm_handler_wrap(signal.SIGINT)
        # SIGTERM（kill/服务停止）：与 SIGINT 同样处理
        sigterm_handler_wrap(signal.SIGTERM)

        # 读取原始 channel_type 配置；解析成启动列表的工作
        # 由 _resolve_startup_channels 完成
        raw_channel = conf().get("channel_type", "web")

        if "--cmd" in sys.argv:
            channel_names = ["terminal"]
        else:
            # 多实例选择加入：当 team.json 定义channel_instances时，
            # 启动这些（每个都有自己的凭据+代理绑定）。
            # 否则，回退到旧版的channel_type 列表而不受影响。
            channel_names = _resolve_startup_channels(raw_channel)

        # 除非明确禁用 web_console，否则自动补上 Web 控制台。
        # web 始终以旧版字符串形式启动，不进实例注册表；
        # 多实例机制只作用于 IM 通道。
        web_console_enabled = conf().get("web_console", True)
        if web_console_enabled and not _has_web_entry(channel_names):
            channel_names.append("web")

        # 在任何通道启动之前，把内置技能同步、子代理模板铺设到
        # 各代理的工作区，保证首批消息到来时即可用
        _sync_builtin_skills()
        _scaffold_subagent_assets()

        # 后台预热 MCP 服务器：让 npx/uvx 子进程在第一条用户消息
        # 到来之前完成初始化，首条消息的延迟不再受包下载影响。
        # 桌面模式跳过——它依赖的外部 npx/uvx 运行时未随应用打包。
        if not DESKTOP_MODE:
            _warmup_mcp_tools()

        if DESKTOP_MODE:
            # 把 AgentBridge/调度器预热推迟到后台线程，
            # 让 Web API 几秒内就绪；调度器照常启动，
            # 只是不阻塞 UI 准备完成。
            _preload_heavy_imports()
            _start_web_watchdog()
            threading.Thread(target=_warmup_scheduler, daemon=True).start()
        else:
            _warmup_scheduler()

        logger.info(f"[App] Starting channels: {channel_names}")

        _channel_mgr = ChannelManager()
        _channel_mgr.start(channel_names, first_start=True)

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error("App startup failed!")
        logger.exception(e)
        # 桌面外壳会把退出码 0 视为正常关闭，随后不断重试“连接”
        # 直到超时。以非零码退出，让外壳展示真实错误并立即停止重试。
        if DESKTOP_MODE:
            logging.shutdown()
            os._exit(1)


if __name__ == "__main__":
    run()
