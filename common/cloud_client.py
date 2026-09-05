"""
Cloud management client for connecting to a remote control console.

Handles remote configuration sync, message push, and skill management over
the console's socket protocol.

DEFAULT IS LOCAL-ONLY. Out of the box no cloud config is enabled: the
application runs entirely on this machine and uploads nothing to any remote
service. The cloud client is only activated when BOTH of these hold:

  1. ``use_linkai`` is True in config (checked in app.py before this module
     is imported).
  2. ``cloud_deployment_id`` (or env CLOUD_DEPLOYMENT_ID) is non-empty
     (checked in app.py and again in the ``start()`` function below).

If either is missing this module is never loaded and the program continues
as a purely local application.
"""

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from linkai import LinkAIClient, PushMsg
from config import conf, pconf, plugin_config, available_setting, write_plugin_config, get_root, get_weixin_credentials_path
from plugins import PluginManager
from contextlib import contextmanager
from contextvars import ContextVar
import threading
import time
import json
import os


chat_client: LinkAIClient


CHANNEL_ACTIONS = {"channel_create", "channel_update", "channel_delete"}


# ChannelType -> 应用程序凭据的配置键映射。
# 对于单令牌通道（例如电报/不和谐），secret_key 可以是“”。
# 对于slack来说，appId携带bot_token，appSecret携带app_token。
CREDENTIAL_MAP = {
    "feishu":            ("feishu_app_id",          "feishu_app_secret"),
    "dingtalk":          ("dingtalk_client_id",      "dingtalk_client_secret"),
    "wecom_bot":         ("wecom_bot_id",            "wecom_bot_secret"),
    "qq":                ("qq_app_id",               "qq_app_secret"),
    "wechatmp":          ("wechatmp_app_id",         "wechatmp_app_secret"),
    "wechatmp_service":  ("wechatmp_app_id",         "wechatmp_app_secret"),
    "wechatcom_app":     ("wechatcomapp_agent_id",   "wechatcomapp_secret"),
    "telegram":          ("telegram_token",          ""),
    "slack":             ("slack_bot_token",         "slack_app_token"),
    "discord":           ("discord_token",           ""),
}


# 控制台用户驱动当前线程处理的请求。保存在一个
# ContextVar，以便出站调用可以读取它，而无需将其传递给每个
# 呼叫签名；后台线程开始为空。
_console_user: ContextVar = ContextVar("console_user", default=None)


def current_user_id():
    """Console user for the request being handled, or None."""
    return _console_user.get()


@contextmanager
def _acting_user(user_id):
    value = str(user_id).strip() if user_id is not None and str(user_id).strip() else None
    token = _console_user.set(value)
    try:
        yield
    finally:
        _console_user.reset(token)


class CloudClient(LinkAIClient):
    def __init__(self, api_key: str, channel, host: str = "", port=None):
        super().__init__(api_key, host, port=port)
        self.channel = channel
        self.client_type = channel.channel_type
        self.channel_mgr = None
        self._skill_service = None
        self._memory_service = None
        self._knowledge_service = None
        self._chat_service = None
        self._session_service = None
        self._workspace_service = None

    @property
    def skill_service(self):
        """Lazy-init SkillService so it is available once SkillManager exists."""
        if self._skill_service is None:
            try:
                from agent.skills.manager import SkillManager
                from agent.skills.service import SkillService
                from common.state_dir import skills_dir
                manager = SkillManager(custom_dir=str(skills_dir()))
                self._skill_service = SkillService(manager)
                logger.debug("[CloudClient] SkillService initialised")
            except Exception as e:
                logger.error(f"[CloudClient] Failed to init SkillService: {e}")
        return self._skill_service

    @property
    def memory_service(self):
        """Lazy-init MemoryService."""
        if self._memory_service is None:
            try:
                from agent.memory.service import MemoryService
                from common.state_dir import state_root_str
                self._memory_service = MemoryService(state_root_str())
                logger.debug("[CloudClient] MemoryService initialised")
            except Exception as e:
                logger.error(f"[CloudClient] Failed to init MemoryService: {e}")
        return self._memory_service

    @property
    def knowledge_service(self):
        """Lazy-init KnowledgeService."""
        if self._knowledge_service is None:
            try:
                from agent.knowledge.service import KnowledgeService
                from common.state_dir import state_root_str
                self._knowledge_service = KnowledgeService(state_root_str())
                logger.debug("[CloudClient] KnowledgeService initialised")
            except Exception as e:
                logger.error(f"[CloudClient] Failed to init KnowledgeService: {e}")
        return self._knowledge_service

    @property
    def workspace_service(self):
        """Lazy-init WorkspaceService."""
        if self._workspace_service is None:
            try:
                from agent.workspace.service import WorkspaceService
                from common.state_dir import state_root_str
                self._workspace_service = WorkspaceService(state_root_str())
                logger.debug("[CloudClient] WorkspaceService initialised")
            except Exception as e:
                logger.error(f"[CloudClient] Failed to init WorkspaceService: {e}")
        return self._workspace_service

    @property
    def chat_service(self):
        """Lazy-init ChatService (requires AgentBridge via Bridge singleton)."""
        if self._chat_service is None:
            try:
                from agent.chat.service import ChatService
                from bridge.bridge import Bridge
                agent_bridge = Bridge().get_agent_bridge()
                self._chat_service = ChatService(agent_bridge)
                logger.debug("[CloudClient] ChatService initialised")
            except Exception as e:
                logger.error(f"[CloudClient] Failed to init ChatService: {e}")
        return self._chat_service

    @property
    def session_service(self):
        """Lazy-init SessionService."""
        if self._session_service is None:
            try:
                from agent.chat.session_service import SessionService
                self._session_service = SessionService()
                logger.debug("[CloudClient] SessionService initialised")
            except Exception as e:
                logger.error(f"[CloudClient] Failed to init SessionService: {e}")
        return self._session_service

    # ------------------------------------------------------------------
    # 消息推送回调
    # ------------------------------------------------------------------
    def on_message(self, push_msg: PushMsg):
        session_id = push_msg.session_id
        msg_content = push_msg.msg_content
        logger.info(f"receive msg push, session_id={session_id}, msg_content={msg_content}")
        context = Context()
        context.type = ContextType.TEXT
        context["receiver"] = session_id
        context["isgroup"] = push_msg.is_group
        self.channel.send(Reply(ReplyType.TEXT, content=msg_content), context)

    # ------------------------------------------------------------------
    # 配置回调
    # ------------------------------------------------------------------
    def on_config(self, config: dict):
        if not self.client_id:
            return
        logger.info(f"[CloudClient] Loading remote config: {config}")

        action = config.get("action")
        if action in CHANNEL_ACTIONS:
            self._dispatch_channel_action(action, config.get("data", {}))
            return

        if config.get("enabled") != "Y":
            return

        local_config = conf()
        need_restart_channel = False

        for key in config.keys():
            if key in available_setting and config.get(key) is not None:
                local_config[key] = config.get(key)

        # 自进化开关：标准化远程值（bool /“Y”/“N”/“true”）
        # 为一个真正的布尔值，以便进化配置解析器正确读取它。
        if config.get("self_evolution_enabled") is not None:
            local_config["self_evolution_enabled"] = self._to_bool(config.get("self_evolution_enabled"))

        # 语音设置
        reply_voice_mode = config.get("reply_voice_mode")
        if reply_voice_mode:
            if reply_voice_mode == "voice_reply_voice":
                local_config["voice_reply_voice"] = True
                local_config["always_reply_voice"] = False
            elif reply_voice_mode == "always_reply_voice":
                local_config["always_reply_voice"] = True
                local_config["voice_reply_voice"] = True
            elif reply_voice_mode == "no_reply_voice":
                local_config["always_reply_voice"] = False
                local_config["voice_reply_voice"] = False

        # 型号配置
        if config.get("model"):
            local_config["model"] = config.get("model")

        # 通道配置（传统单通道路径）
        if config.get("channelType"):
            if local_config.get("channel_type") != config.get("channelType"):
                local_config["channel_type"] = config.get("channelType")
                need_restart_channel = True

        # 特定于渠道的应用程序凭据（旧版单渠道路径）
        current_channel_type = local_config.get("channel_type", "")
        if self._set_channel_credentials(local_config, current_channel_type,
                                         config.get("app_id"), config.get("app_secret")):
            need_restart_channel = True

        if config.get("admin_password"):
            if not pconf("Godcmd"):
                write_plugin_config({"Godcmd": {"password": config.get("admin_password"), "admin_users": []}})
            else:
                pconf("Godcmd")["password"] = config.get("admin_password")
            PluginManager().instances["GODCMD"].reload()

        if config.get("group_app_map") and pconf("linkai"):
            local_group_map = {}
            for mapping in config.get("group_app_map"):
                local_group_map[mapping.get("group_name")] = mapping.get("app_code")
            pconf("linkai")["group_app_map"] = local_group_map
            PluginManager().instances["LINKAI"].reload()

        if config.get("text_to_image") and config.get("text_to_image") == "midjourney" and pconf("linkai"):
            if pconf("linkai")["midjourney"]:
                pconf("linkai")["midjourney"]["enabled"] = True
                pconf("linkai")["midjourney"]["use_image_create_prefix"] = True
        elif config.get("text_to_image") and config.get("text_to_image") in ["dall-e-2", "dall-e-3"]:
            if pconf("linkai")["midjourney"]:
                pconf("linkai")["midjourney"]["use_image_create_prefix"] = False

        self._save_config_to_file(local_config)

        if need_restart_channel:
            self._restart_channel(local_config.get("channel_type", ""))

    # ------------------------------------------------------------------
    # 通道增删改查操作
    # ------------------------------------------------------------------
    def _dispatch_channel_action(self, action: str, data: dict):
        channel_type = data.get("channelType")
        if not channel_type:
            logger.warning(f"[CloudClient] Channel action '{action}' missing channelType, data={data}")
            return

        # 每个连接 ID 选择此通道进入多实例路径：
        # 它的身份、绑定和凭证都存储在每个实例中
        # 名册文件而不是作为 config.json 中的一个平面集，所以有几个
        # 一种类型的连接可以共存。缺席的话，下面的都是
        # 原始单连接路径，逐字节。
        instance_id = str(data.get("channelId") or "").strip()
        if instance_id:
            logger.info(
                f"[CloudClient] Channel action: {action}, "
                f"channelType={channel_type}, id={instance_id}"
            )
            if action == "channel_create":
                self._handle_instance_create(instance_id, channel_type, data)
            elif action == "channel_update":
                self._handle_instance_update(instance_id, channel_type, data)
            elif action == "channel_delete":
                self._handle_instance_delete(instance_id, channel_type, data)
            return

        logger.info(f"[CloudClient] Channel action: {action}, channelType={channel_type}")

        if action == "channel_create":
            self._handle_channel_create(channel_type, data)
        elif action == "channel_update":
            self._handle_channel_update(channel_type, data)
        elif action == "channel_delete":
            self._handle_channel_delete(channel_type, data)

    # ------------------------------------------------------------------
    # 每个实例通道操作（多实例路径）
    # ------------------------------------------------------------------
    @staticmethod
    def _instance_credentials_from(channel_type: str, data: dict) -> dict:
        """Map the remote appId/appSecret onto this type's credential keys."""
        cred = CREDENTIAL_MAP.get(channel_type)
        if not cred:
            return {}
        id_key, secret_key = cred
        out = {}
        if data.get("appId") is not None:
            out[id_key] = data.get("appId")
        if secret_key and data.get("appSecret") is not None:
            out[secret_key] = data.get("appSecret")
        return out

    @staticmethod
    def _instance_agent_id(data: dict):
        """The bound Agent id if the remote supplied one, else None.

        Accepts a few plausible field names so the binding is honored whichever
        the control plane uses; None means "leave the current binding as-is".
        """
        for key in ("agentId", "agent_id", "boundAgentId"):
            value = data.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    def _handle_instance_create(self, instance_id: str, channel_type: str, data: dict):
        from channel.channel_instances import upsert_instance
        inst = upsert_instance(
            conf(),
            channel_type=channel_type,
            instance_id=instance_id,
            agent_id=self._instance_agent_id(data),
            credentials=self._instance_credentials_from(channel_type, data),
        )
        if not self.channel_mgr:
            return
        threading.Thread(
            target=self._do_add_instance, args=(inst,), daemon=True
        ).start()

    def _handle_instance_update(self, instance_id: str, channel_type: str, data: dict):
        from channel.channel_instances import upsert_instance, remove_instance
        enabled = data.get("enabled", "Y")
        if enabled == "N":
            remove_instance(conf(), instance_id)
            if self.channel_mgr:
                threading.Thread(
                    target=self._do_remove_channel, args=(instance_id,), daemon=True
                ).start()
            return
        inst = upsert_instance(
            conf(),
            channel_type=channel_type,
            instance_id=instance_id,
            agent_id=self._instance_agent_id(data),
            credentials=self._instance_credentials_from(channel_type, data),
        )
        if not self.channel_mgr:
            return
        threading.Thread(
            target=self._do_add_instance, args=(inst,), daemon=True
        ).start()

    def _handle_instance_delete(self, instance_id: str, channel_type: str, data: dict):
        from channel.channel_instances import remove_instance
        remove_instance(conf(), instance_id)
        if self.channel_mgr:
            threading.Thread(
                target=self._do_remove_channel, args=(instance_id,), daemon=True
            ).start()

    def _do_add_instance(self, inst):
        """Start (or restart) one instance and report its type-level status.

        Status is reported at the channel-type level (not the instance id) so it
        stays compatible with the existing status protocol; instance-level status
        can be layered on once the control plane tracks it.
        """
        try:
            self.channel_mgr.add_channel(inst)
            logger.info(f"[CloudClient] Channel instance '{inst.instance_id}' added successfully")
        except Exception as e:
            logger.error(
                f"[CloudClient] Failed to add channel instance '{inst.instance_id}': {e}",
                exc_info=True,
            )
            self.send_channel_status(inst.channel_type, "error", str(e))
            return
        ch = self.channel_mgr.get_channel(inst.instance_id)
        if not ch:
            self.send_channel_status(inst.channel_type, "error", "channel instance not found")
            return
        success, error = ch.wait_startup(timeout=3)
        if success:
            logger.info(
                f"[CloudClient] Channel instance '{inst.instance_id}' connected, reporting status"
            )
            self.send_channel_status(inst.channel_type, "connected")
        else:
            logger.warning(
                f"[CloudClient] Channel instance '{inst.instance_id}' startup failed: {error}"
            )
            self.send_channel_status(inst.channel_type, "error", error)

    def _handle_channel_create(self, channel_type: str, data: dict):
        local_config = conf()
        cred_changed = self._set_channel_credentials(
            local_config, channel_type, data.get("appId"), data.get("appSecret"))
        self._add_channel_type(local_config, channel_type)
        self._save_config_to_file(local_config)

        if not self.channel_mgr:
            return

        existing_ch = self.channel_mgr.get_channel(channel_type)
        skip_restart = existing_ch and not cred_changed
        if skip_restart and channel_type in ("weixin", "wx"):
            login_status = getattr(existing_ch, "login_status", "")
            if login_status != "logged_in":
                skip_restart = False
                logger.info(f"[CloudClient] Channel '{channel_type}' not logged in "
                            f"(status={login_status}), forcing restart")
        if skip_restart:
            logger.info(f"[CloudClient] Channel '{channel_type}' already running with same config, "
                        "skip restart, reporting status only")
            threading.Thread(
                target=self._report_channel_startup, args=(channel_type,), daemon=True
            ).start()
            return

        threading.Thread(
            target=self._do_add_channel, args=(channel_type,), daemon=True
        ).start()

    def _handle_channel_update(self, channel_type: str, data: dict):
        local_config = conf()
        enabled = data.get("enabled", "Y")

        cred_changed = self._set_channel_credentials(
            local_config, channel_type, data.get("appId"), data.get("appSecret"))
        if enabled == "N":
            self._remove_channel_type(local_config, channel_type)
        else:
            self._add_channel_type(local_config, channel_type)
        self._save_config_to_file(local_config)

        if not self.channel_mgr:
            return

        if enabled == "N":
            threading.Thread(
                target=self._do_remove_channel, args=(channel_type,), daemon=True
            ).start()
        else:
            existing_ch = self.channel_mgr.get_channel(channel_type)
            needs_restart = cred_changed or not existing_ch
            if not needs_restart and channel_type in ("weixin", "wx"):
                login_status = getattr(existing_ch, "login_status", "")
                if login_status != "logged_in":
                    needs_restart = True
                    logger.info(f"[CloudClient] Channel '{channel_type}' not logged in "
                                f"(status={login_status}), forcing restart")
            if existing_ch and not needs_restart:
                logger.info(f"[CloudClient] Channel '{channel_type}' already running with same config, "
                            "skip restart, reporting status only")
                threading.Thread(
                    target=self._report_channel_startup, args=(channel_type,), daemon=True
                ).start()
            else:
                threading.Thread(
                    target=self._do_restart_channel, args=(self.channel_mgr, channel_type), daemon=True
                ).start()

    def _handle_channel_delete(self, channel_type: str, data: dict):
        local_config = conf()
        self._clear_channel_credentials(local_config, channel_type)
        self._remove_channel_type(local_config, channel_type)
        self._save_config_to_file(local_config)

        if channel_type in ("weixin", "wx"):
            self._remove_weixin_credentials()

        if self.channel_mgr:
            threading.Thread(
                target=self._do_remove_channel, args=(channel_type,), daemon=True
            ).start()

    @staticmethod
    def _remove_weixin_credentials():
        """Remove the weixin token credentials file so next connect triggers QR login."""
        cred_path = get_weixin_credentials_path()
        try:
            if os.path.exists(cred_path):
                os.remove(cred_path)
                logger.info(f"[CloudClient] Removed weixin credentials: {cred_path}")
        except Exception as e:
            logger.warning(f"[CloudClient] Failed to remove weixin credentials: {e}")

    # ------------------------------------------------------------------
    # 价值帮手
    # ------------------------------------------------------------------
    @staticmethod
    def _to_bool(value) -> bool:
        """Normalize a remote config value to bool (bool / "Y"/"N" / "true"/"1")."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in ("y", "yes", "true", "1", "on")
        return False

    # ------------------------------------------------------------------
    # 通道凭证助手
    # ------------------------------------------------------------------
    @staticmethod
    def _set_channel_credentials(local_config: dict, channel_type: str,
                                 app_id, app_secret) -> bool:
        """
        Write app_id / app_secret into the correct config keys for *channel_type*.
        Also syncs the values to environment variables (upper-cased key) so that
        skills that rely on env-based checks (e.g. has_env_var) work immediately.
        Returns True if any value actually changed.
        """
        cred = CREDENTIAL_MAP.get(channel_type)
        if not cred:
            return False
        id_key, secret_key = cred
        changed = False
        if app_id is not None and local_config.get(id_key) != app_id:
            local_config[id_key] = app_id
            os.environ[id_key.upper()] = str(app_id)
            changed = True
        # 对于单令牌通道，secret_key 可能为空（例如 telegram/discord）
        if secret_key and app_secret is not None and local_config.get(secret_key) != app_secret:
            local_config[secret_key] = app_secret
            os.environ[secret_key.upper()] = str(app_secret)
            changed = True
        if changed:
            logger.info(f"[CloudClient] Synced {channel_type} credentials to conf and env")
        return changed

    @staticmethod
    def _clear_channel_credentials(local_config: dict, channel_type: str):
        cred = CREDENTIAL_MAP.get(channel_type)
        if not cred:
            return
        id_key, secret_key = cred
        local_config.pop(id_key, None)
        os.environ.pop(id_key.upper(), None)
        if secret_key:
            local_config.pop(secret_key, None)
            os.environ.pop(secret_key.upper(), None)

    # ------------------------------------------------------------------
    # Channel_type 列表助手
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_channel_types(local_config: dict) -> list:
        raw = local_config.get("channel_type", "")
        if isinstance(raw, list):
            return [ch.strip() for ch in raw if ch.strip()]
        if isinstance(raw, str):
            return [ch.strip() for ch in raw.split(",") if ch.strip()]
        return []

    @staticmethod
    def _add_channel_type(local_config: dict, channel_type: str):
        types = CloudClient._parse_channel_types(local_config)
        if channel_type not in types:
            types.append(channel_type)
            local_config["channel_type"] = ", ".join(types)

    @staticmethod
    def _remove_channel_type(local_config: dict, channel_type: str):
        types = CloudClient._parse_channel_types(local_config)
        if channel_type in types:
            types.remove(channel_type)
            local_config["channel_type"] = ", ".join(types)

    # ------------------------------------------------------------------
    # 通道管理器线程助手
    # ------------------------------------------------------------------
    def _do_add_channel(self, channel_type: str):
        try:
            self.channel_mgr.add_channel(channel_type)
            logger.info(f"[CloudClient] Channel '{channel_type}' added successfully")
        except Exception as e:
            logger.error(f"[CloudClient] Failed to add channel '{channel_type}': {e}", exc_info=True)
            self.send_channel_status(channel_type, "error", str(e))
            return
        self._report_channel_startup(channel_type)

    def _do_remove_channel(self, channel_type: str):
        try:
            self.channel_mgr.remove_channel(channel_type)
            logger.info(f"[CloudClient] Channel '{channel_type}' removed successfully")
        except Exception as e:
            logger.error(f"[CloudClient] Failed to remove channel '{channel_type}': {e}")

    def send_channel_qrcode(self, channel_type: str, qrcode_url: str):
        """Report QR code URL for a channel that requires scan-to-login."""
        if self.client_id:
            from linkai.api.client.client import ClientMsgType
            msg = self._build_package(ClientMsgType.CHANNEL_STATUS)
            msg["data"]["channelType"] = channel_type
            msg["data"]["status"] = "qrcode"
            msg["data"]["qrcodeUrl"] = qrcode_url
            self._send_package(msg)
            logger.info(f"[CloudClient] Sent QR code status for '{channel_type}'")

    def _report_channel_startup(self, channel_type: str):
        """Wait for channel startup result and report to cloud."""
        ch = self.channel_mgr.get_channel(channel_type)
        if not ch:
            self.send_channel_status(channel_type, "error", "channel instance not found")
            return

        if channel_type in ("weixin", "wx") and hasattr(ch, "login_status"):
            login_status = getattr(ch, "login_status", "")
            if login_status in ("waiting_scan", "scanned", "idle"):
                logger.info(f"[CloudClient] Channel '{channel_type}' is waiting for QR login, "
                            "skip reporting connected")
                return

        success, error = ch.wait_startup(timeout=3)
        if success:
            logger.info(f"[CloudClient] Channel '{channel_type}' connected, reporting status")
            self.send_channel_status(channel_type, "connected")
        else:
            logger.warning(f"[CloudClient] Channel '{channel_type}' startup failed: {error}")
            self.send_channel_status(channel_type, "error", error)

    # ------------------------------------------------------------------
    # 技能回调
    # ------------------------------------------------------------------
    def on_skill(self, data: dict) -> dict:
        """
        Handle SKILL messages from the cloud console.
        Delegates to SkillService.dispatch for the actual operations.

        :param data: message data with 'action', 'clientId', 'payload'
        :return: response dict
        """
        action = data.get("action", "")
        payload = data.get("payload")
        logger.info(f"[CloudClient] on_skill: action={action}")

        svc = self.skill_service
        if svc is None:
            return {"action": action, "code": 500, "message": "SkillService not available", "payload": None}

        return svc.dispatch(action, payload)

    # ------------------------------------------------------------------
    # 内存回调
    # ------------------------------------------------------------------
    def on_memory(self, data: dict) -> dict:
        """
        Handle MEMORY messages from the cloud console.
        Delegates to MemoryService.dispatch for the actual operations.

        :param data: message data with 'action', 'clientId', 'payload'
        :return: response dict
        """
        action = data.get("action", "")
        payload = data.get("payload")
        logger.info(f"[CloudClient] on_memory: action={action}")

        svc = self.memory_service
        if svc is None:
            return {"action": action, "code": 500, "message": "MemoryService not available", "payload": None}

        return svc.dispatch(action, payload)

    # ------------------------------------------------------------------
    # 知识回调
    # ------------------------------------------------------------------
    def on_knowledge(self, data: dict) -> dict:
        """
        Handle KNOWLEDGE messages from the cloud console.
        Delegates to KnowledgeService.dispatch for the actual operations.

        :param data: message data with 'action', 'clientId', 'payload'
        :return: response dict
        """
        action = data.get("action", "")
        payload = data.get("payload")
        logger.info(f"[CloudClient] on_knowledge: action={action}")

        svc = self.knowledge_service
        if svc is None:
            return {"action": action, "code": 500, "message": "KnowledgeService not available", "payload": None}

        return svc.dispatch(action, payload)

    # ------------------------------------------------------------------
    # 工作区回调
    # ------------------------------------------------------------------
    def on_workspace(self, data: dict) -> dict:
        """
        Handle WORKSPACE messages from the cloud console.

        Read-only browsing of the agent workspace. WorkspaceService keeps every
        path inside the workspace root and caps response sizes.

        :param data: message data with 'action', 'clientId', 'payload'
        :return: response dict
        """
        action = data.get("action", "")
        payload = data.get("payload") or {}

        logger.info(f"[CloudClient] on_workspace: action={action}, path={payload.get('path', '')}")

        svc = self.workspace_service
        if svc is None:
            return {"action": action, "code": 500, "message": "WorkspaceService not available", "payload": None}

        return svc.dispatch(action, payload)

    # ------------------------------------------------------------------
    # 聊天回调
    # ------------------------------------------------------------------
    def on_chat(self, data: dict, send_chunk_fn):
        """
        Handle CHAT messages from the cloud console.
        Runs the agent in streaming mode and sends chunks back via send_chunk_fn.

        :param data: message data with 'action' and 'payload' (query, session_id)
        :param send_chunk_fn: callable(chunk_data: dict) to send one streaming chunk
        """
        payload = data.get("payload", {})
        query = payload.get("query", "")
        session_id = payload.get("session_id", "cloud_console")
        channel_type = payload.get("channel_type", "")
        # 代表其运行的控制台用户；使用归因于他们
        # 而不是注册此部署所用的帐户。
        user_id = payload.get("user_id") or data.get("user_id")
        if not session_id.startswith("session_"):
            session_id = f"session_{session_id}"
        logger.info(f"[CloudClient] on_chat: session={session_id}, channel={channel_type}, "
                    f"user_id={user_id}, query={query[:80]}")

        # 取消/转向快速路径。这些并不是新的特工回合——他们会继续行动
        # 本次会议的跑步活动已经开始。网络渠道拦截
        # 它们在其 HTTP 处理程序中；云/套接字路径（此方法）是什么
        # 像 linkai-admin 驱动器这样的平台，所以它也必须在这里尊重它们。
        # 两者都到达正在轮询的相同进程内注册表。
        stripped = (query or "").strip()
        steer_flag = bool(payload.get("steer"))
        if stripped == "/cancel":
            handled = self._handle_cancel(session_id, send_chunk_fn)
            if handled:
                return
        elif steer_flag or stripped.startswith("/steer"):
            instruction = (
                stripped[len("/steer"):].strip()
                if stripped.startswith("/steer")
                else stripped
            )
            self._handle_steer(session_id, instruction, send_chunk_fn)
            return

        with _acting_user(user_id):
            # 在代理运行之前拦截cow/slash命令
            try:
                from plugins import PluginManager
                mgr = PluginManager()
                instance = mgr.instances.get("COW_CLI")
                if instance and hasattr(instance, "execute"):
                    result = instance.execute(query, session_id=session_id)
                    if result is not None:
                        send_chunk_fn({"chunk_type": "content", "delta": result, "segment_id": 0})
                        return
            except Exception as e:
                logger.warning(f"[CloudClient] cow_cli intercept failed: {e}")

            svc = self.chat_service
            if svc is None:
                raise RuntimeError("ChatService not available")

            svc.run(query=query, session_id=session_id, channel_type=channel_type,
                    send_chunk_fn=send_chunk_fn)

    def _agent_bridge(self):
        try:
            from bridge.bridge import Bridge
            return Bridge().get_agent_bridge()
        except Exception as e:
            logger.warning(f"[CloudClient] agent_bridge unavailable: {e}")
            return None

    def _handle_cancel(self, session_id: str, send_chunk_fn) -> bool:
        """Abort the in-flight run for this session. Returns True if it was our
        command to handle (always True once matched), regardless of whether a
        run was actually running."""
        bridge = self._agent_bridge()
        cancelled = 0
        if bridge is not None:
            try:
                from agent.protocol import get_cancel_registry
                key = bridge.scoped_session_key(session_id)
                cancelled = get_cancel_registry().cancel_session(key)
            except Exception as e:
                logger.warning(f"[CloudClient] cancel failed: {e}")
        logger.info(f"[CloudClient] /cancel: session={session_id}, cancelled={cancelled}")
        msg = "已中止当前执行。" if cancelled > 0 else "当前没有正在执行的任务。"
        send_chunk_fn({"chunk_type": "content", "delta": msg, "segment_id": 0})
        return True

    def _handle_steer(self, session_id: str, instruction: str, send_chunk_fn) -> None:
        """Inject a mid-run instruction into this session's active run."""
        if not instruction:
            send_chunk_fn({"chunk_type": "content",
                           "delta": "用法：/steer <要补充的指令>", "segment_id": 0})
            return
        bridge = self._agent_bridge()
        status_val = None
        if bridge is not None:
            try:
                result = bridge.steer_session(session_id, instruction)
                status_val = getattr(getattr(result, "status", None), "value", None) or str(result)
            except Exception as e:
                logger.warning(f"[CloudClient] steer failed: {e}")
        logger.info(f"[CloudClient] /steer: session={session_id}, status={status_val}")
        msg = ("已把补充要求插入当前执行，员工会在下一步纳入。"
               if status_val in ("accepted", "ACCEPTED", "queued")
               else "当前没有正在执行的任务可插话，请直接发送新的要求。")
        send_chunk_fn({"chunk_type": "content", "delta": msg, "segment_id": 0})

    # ------------------------------------------------------------------
    # 历史回调
    # ------------------------------------------------------------------
    # 通过 HISTORY 通道处理的会话相关操作
    _SESSION_ACTIONS = {
        "list_sessions", "delete_session", "rename_session",
        "clear_context", "generate_title",
    }

    def on_history(self, data: dict) -> dict:
        """
        Handle HISTORY messages from the cloud console.

        Supports both history query and session management actions
        through a unified HISTORY message channel:
          - query: paginated conversation history
          - list_sessions / delete_session / rename_session /
            clear_context / generate_title: session lifecycle

        :param data: message data with 'action' and 'payload'
        :return: response dict
        """
        action = data.get("action", "query")
        payload = data.get("payload", {})
        logger.info(f"[CloudClient] on_history: action={action}")

        if action == "query":
            return self._query_history(payload)

        if action in self._SESSION_ACTIONS:
            # 某些操作（例如generate_title）调用模型，因此属性
            # 就像聊天请求一样将它们发送给控制台用户。
            with _acting_user(payload.get("user_id")):
                return self._dispatch_session(action, payload)

        return {"action": action, "code": 404, "message": f"unknown action: {action}", "payload": None}

    def _dispatch_session(self, action: str, payload: dict) -> dict:
        """Delegate session actions to SessionService."""
        svc = self.session_service
        if svc is None:
            return {"action": action, "code": 500,
                    "message": "SessionService not available", "payload": None}
        return svc.dispatch(action, payload)

    def _query_history(self, payload: dict) -> dict:
        """Query paginated conversation history using ConversationStore."""
        session_id = payload.get("session_id", "")
        page = int(payload.get("page", 1))
        page_size = int(payload.get("page_size", 20))

        if not session_id:
            return {
                "action": "query",
                "payload": {"status": "error", "message": "session_id required"},
            }

        # Web 渠道存储带有“session_”前缀的会话
        if not session_id.startswith("session_"):
            session_id = f"session_{session_id}"
        logger.info(f"[CloudClient] history query: session={session_id}, page={page}, page_size={page_size}")

        try:
            from agent.memory.conversation_store import get_conversation_store
            store = get_conversation_store()
            result = store.load_history_page(
                session_id=session_id,
                page=page,
                page_size=page_size,
            )
            return {
                "action": "query",
                "payload": {"status": "success", **result},
            }
        except Exception as e:
            logger.error(f"[CloudClient] History query error: {e}")
            return {
                "action": "query",
                "payload": {"status": "error", "message": str(e)},
            }

    # ------------------------------------------------------------------
    # 频道重启助手
    # ------------------------------------------------------------------
    def _restart_channel(self, new_channel_type: str):
        """
        Restart the channel via ChannelManager when channel type changes.
        """
        if self.channel_mgr:
            logger.info(f"[CloudClient] Restarting channel to '{new_channel_type}'...")
            threading.Thread(target=self._do_restart_channel, args=(self.channel_mgr, new_channel_type), daemon=True).start()
        else:
            logger.warning("[CloudClient] ChannelManager not available, please restart the application manually")

    def _do_restart_channel(self, mgr, new_channel_type: str):
        """
        Perform the channel restart in a separate thread to avoid blocking the config callback.
        """
        try:
            mgr.restart(new_channel_type)
            if mgr.channel:
                self.channel = mgr.channel
                self.client_type = mgr.channel.channel_type
                logger.info(f"[CloudClient] Channel reference updated to '{new_channel_type}'")
        except Exception as e:
            logger.error(f"[CloudClient] Channel restart failed: {e}")
            self.send_channel_status(new_channel_type, "error", str(e))
            return
        self._report_channel_startup(new_channel_type)

    # ------------------------------------------------------------------
    # 配置持久化
    # ------------------------------------------------------------------
    def _save_config_to_file(self, local_config: dict):
        """
        Save configuration to config.json file.
        """
        try:
            config_path = os.path.join(get_root(), "config.json")
            if not os.path.exists(config_path):
                logger.warning(f"[CloudClient] config.json not found at {config_path}, skip saving")
                return

            with open(config_path, "r", encoding="utf-8") as f:
                file_config = json.load(f)

            file_config.update(dict(local_config))

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(file_config, f, indent=4, ensure_ascii=False)

            logger.info("[CloudClient] Configuration saved to config.json successfully")
        except Exception as e:
            logger.error(f"[CloudClient] Failed to save configuration to config.json: {e}")


def get_root_domain(host: str = "") -> str:
    """Extract root domain from a hostname.

    If *host* is empty, reads CLOUD_HOST env var / cloud_host config.
    """
    if not host:
        host = os.environ.get("CLOUD_HOST") or conf().get("cloud_host", "")
    if not host:
        return ""
    host = host.strip().rstrip("/")
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split(":")[0]
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def get_deployment_id() -> str:
    """Return cloud deployment id from env var or config."""
    return os.environ.get("CLOUD_DEPLOYMENT_ID") or conf().get("cloud_deployment_id", "")


def get_website_base_url() -> str:
    """Return the URL prefix that maps to the workspace websites/ dir.

    Do nothing when in local env.
    """
    deployment_id = get_deployment_id()
    if not deployment_id:
        return ""

    websites_domain = os.environ.get("CLOUD_WEBSITES_DOMAIN") or conf().get("cloud_websites_domain", "")
    if websites_domain:
        websites_domain = websites_domain.strip().rstrip("/")
        if websites_domain.startswith(("http://", "https://")):
            return f"{websites_domain}/{deployment_id}"
        return f"https://{websites_domain}/{deployment_id}"

    domain = get_root_domain()
    if not domain:
        return ""
    return f"https://app.{domain}/{deployment_id}"


# 发送工具使用的网站/下的子目录
COW_SEND_WEB_SUBDIR = "cow-send"


def copy_send_file(src_path: str, workspace_root: str) -> str:
    """Copy *src_path* into ``websites/cow-send/`` and return its URL.

    Returns empty string in local env.
    """
    import shutil
    import uuid

    from common.utils import expand_path

    base = get_website_base_url()
    if not base or not src_path or not os.path.isfile(src_path):
        return ""
    ws = os.path.abspath(expand_path(workspace_root))
    send_dir = os.path.join(ws, "websites", COW_SEND_WEB_SUBDIR)
    try:
        os.makedirs(send_dir, exist_ok=True)
    except OSError:
        return ""
    ext = os.path.splitext(src_path)[1].lower()
    if len(ext) > 12 or not ext.replace(".", "").isalnum():
        ext = ""
    dest_name = f"{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(send_dir, dest_name)
    try:
        shutil.copy2(src_path, dest_path)
    except OSError as e:
        logger.warning(f"[cloud] copy_send_file: copy failed: {e}")
        return ""
    return f"{base}/{COW_SEND_WEB_SUBDIR}/{dest_name}"


def build_website_prompt(workspace_dir: str) -> list:
    """Build system prompt lines for cloud website/file sharing rules.

    Returns an empty list when cloud deployment is not configured,
    so callers can safely do ``lines.extend(build_website_prompt(...))``.
    """
    base_url = get_website_base_url()
    if not base_url:
        return []

    return [
        "**文件分享与网页生成规则** (非常重要 — 当前为云部署模式):",
        "",
        f"云端已为工作空间的 `websites/` 目录配置好公网路由映射，访问地址前缀为: `{base_url}`",
        "",
        "1. **网页/网站**: 编写网页、H5页面等前端代码时，**必须**将文件放到 `websites/` 目录中",
        f"   - 例如: `websites/index.html` → `{base_url}/index.html`",
        f"   - 例如: `websites/my-app/index.html` → `{base_url}/my-app/index.html`",
        "",
        "2. **生成文件分享** (PPT、PDF、图片、音视频等): 当你为用户生成了需要下载或查看的文件时，**可以**将文件保存到 `websites/` 目录中",
        f"  - 例如: 生成的PPT保存到 `websites/files/report.pptx` → 下载链接为 `{base_url}/files/report.pptx`",
        "   - 你仍然可以同时使用 `send` 工具发送文件（在微信、飞书、钉钉、web等渠道中有效），但**必须同时在回复文本中提供下载链接**作为兜底，因为部分渠道无法通过 send 接收本地文件",
        "",
        "3. **必须发送链接**: 无论是网页还是文件，生成后**必须将完整的访问/下载链接直接写在回复文本中发送给用户**",
        "",
        "4. **文件名和路径尽量使用英文/拼音/数字等**，不要使用中文，避免链接无法访问",
        "",
        "5. 建议为每个独立项目在 `websites/` 下创建子目录，保持结构清晰",
        "",
    ]

def start(channel, channel_mgr=None):
    if not get_deployment_id():
        return

    global chat_client
    chat_client = CloudClient(api_key=conf().get("linkai_api_key"), host=conf().get("cloud_host", ""), port=conf().get("cloud_port"), channel=channel)
    chat_client.channel_mgr = channel_mgr
    chat_client.config = _build_config()
    chat_client.start()
    time.sleep(1.5)
    if chat_client.client_id:
        logger.info("[CloudClient] Console: https://link-ai.tech/console/clients")
        if channel_mgr:
            channel_mgr.cloud_mode = True
            threading.Thread(target=_report_existing_channels, args=(chat_client, channel_mgr), daemon=True).start()


def _report_existing_channels(client: CloudClient, mgr):
    """Report status for all channels that were started before cloud client connected."""
    try:
        for name, ch in list(mgr._channels.items()):
            if name == "web":
                continue
            ch.cloud_mode = True
            client._report_channel_startup(name)
    except Exception as e:
        logger.warning(f"[CloudClient] Failed to report existing channel status: {e}")


def _build_config():
    local_conf = conf()
    config = {
        "linkai_app_code": local_conf.get("linkai_app_code"),
        "single_chat_prefix": local_conf.get("single_chat_prefix"),
        "single_chat_reply_prefix": local_conf.get("single_chat_reply_prefix"),
        "single_chat_reply_suffix": local_conf.get("single_chat_reply_suffix"),
        "group_chat_prefix": local_conf.get("group_chat_prefix"),
        "group_chat_reply_prefix": local_conf.get("group_chat_reply_prefix"),
        "group_chat_reply_suffix": local_conf.get("group_chat_reply_suffix"),
        "group_name_white_list": local_conf.get("group_name_white_list"),
        "nick_name_black_list": local_conf.get("nick_name_black_list"),
        "speech_recognition": "Y" if local_conf.get("speech_recognition") else "N",
        "text_to_image": local_conf.get("text_to_image"),
        "image_create_prefix": local_conf.get("image_create_prefix"),
        "model": local_conf.get("model"),
        "agent_max_context_turns": local_conf.get("agent_max_context_turns"),
        "agent_max_context_tokens": local_conf.get("agent_max_context_tokens"),
        "agent_max_steps": local_conf.get("agent_max_steps"),
        # 报告自我演化开关，以便控制台可以反映状态
        "self_evolution_enabled": "Y" if local_conf.get("self_evolution_enabled") else "N",
        "self_evolution_idle_minutes": local_conf.get("self_evolution_idle_minutes"),
        "self_evolution_min_turns": local_conf.get("self_evolution_min_turns"),
        "channelType": local_conf.get("channel_type"),
    }

    if local_conf.get("always_reply_voice"):
        config["reply_voice_mode"] = "always_reply_voice"
    elif local_conf.get("voice_reply_voice"):
        config["reply_voice_mode"] = "voice_reply_voice"

    if pconf("linkai"):
        config["group_app_map"] = pconf("linkai").get("group_app_map")

    if plugin_config.get("Godcmd"):
        config["admin_password"] = plugin_config.get("Godcmd").get("password")

    # 根据 CREDENTIAL_MAP 添加特定于渠道的应用程序凭据。
    # 对于多通道channel_type（逗号分隔），第一个匹配的类型获胜。
    current_channel_type = local_conf.get("channel_type", "")
    for ch_type in CloudClient._parse_channel_types({"channel_type": current_channel_type}):
        cred = CREDENTIAL_MAP.get(ch_type)
        if not cred:
            continue
        id_key, secret_key = cred
        config["app_id"] = local_conf.get(id_key)
        config["app_secret"] = local_conf.get(secret_key) if secret_key else ""
        break

    return config
