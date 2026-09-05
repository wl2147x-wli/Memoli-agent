"""
Slack channel via Bolt for Python (Socket Mode).

Features:
- Direct message & channel chat (text / image / file)
- Channel trigger: @mention or reply in a thread the bot is in (configurable)
- /cancel fast-path matches Web channel behaviour
- Socket Mode: no public IP / callback URL required, works behind NAT

Implementation note:
    slack_bolt's SocketModeHandler is blocking and runs its own background
    threads. We start it in a dedicated thread so the rest of cow (sync) stays
    untouched. Inbound events are dispatched onto cow's existing sync
    ChatChannel.produce() pipeline; outbound send() calls the Slack Web API
    client directly (it is sync-safe).
"""

import os
import re
import threading

import requests

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel, check_prefix
from channel.slack.slack_message import SlackMessage
from common.expired_dict import ExpiredDict
from common.log import logger
from common.singleton import singleton
from config import conf


@singleton
class SlackChannel(ChatChannel):
    NOT_SUPPORT_REPLYTYPE = []

    def __init__(self):
        super().__init__()
        self.bot_token = ""
        self.app_token = ""
        self.bot_user_id = ""  # 用于删除@提及并忽略自我消息
        self._app = None
        self._handler = None
        self._client = None
        self._loop_thread = None
        # 幂等重复数据删除； Slack 在慢速确认时重试事件传递
        self._received_msgs = ExpiredDict(60 * 60 * 1)

        # 禁用组白名单/前缀检查（我们自己处理触发
        # 在_should_reply_in_channel中），与telegram / feishu频道对齐。
        conf()["group_name_white_list"] = ["ALL_GROUP"]
        conf()["single_chat_prefix"] = [""]

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def startup(self):
        self.bot_token = self.cfg("slack_bot_token", "")
        self.app_token = self.cfg("slack_app_token", "")
        if not self.bot_token or not self.app_token:
            err = "[Slack] slack_bot_token and slack_app_token are both required"
            logger.error(err)
            self.report_startup_error(err)
            return

        # 谨防交换两个代币的常见错误：
        # 机器人令牌必须以 xoxb- 开头，应用程序级令牌必须以 xapp- 开头。
        if not self.bot_token.startswith("xoxb-") or not self.app_token.startswith("xapp-"):
            err = (
                "[Slack] token type mismatch: slack_bot_token must start with 'xoxb-' "
                "and slack_app_token must start with 'xapp-' (they look swapped)"
            )
            logger.error(err)
            self.report_startup_error(err)
            return

        try:
            from slack_bolt import App
            from slack_bolt.adapter.socket_mode import SocketModeHandler
        except ImportError:
            err = (
                "[Slack] slack_bolt is not installed. "
                "Run: pip install slack_bolt"
            )
            logger.error(err)
            self.report_startup_error(err)
            return

        try:
            self._app = App(token=self.bot_token)
            self._client = self._app.client

            # 解析我们自己的机器人用户 ID（@mention strip / self-ignore 需要）
            auth = self._client.auth_test()
            self.bot_user_id = auth.get("user_id", "")
            self.name = self.bot_user_id  # ChatChannel 使用 self.name 去除 @-mention
            logger.info(f"[Slack] Bot logged in as user_id={self.bot_user_id}, team={auth.get('team')}")
        except Exception as e:
            err = f"[Slack] auth_test failed: {e}"
            logger.error(err)
            self.report_startup_error(err)
            return

        self._register_handlers()

        self._handler = SocketModeHandler(self._app, self.app_token)

        def _run():
            try:
                logger.info("[Slack] Starting Socket Mode connection...")
                self.report_startup_success()
                logger.info("[Slack] ✅ Slack bot ready, listening for events")
                self._handler.start()
            except Exception as e:
                logger.error(f"[Slack] socket mode crashed: {e}", exc_info=True)
                self.report_startup_error(str(e))
            finally:
                logger.info("[Slack] socket mode exited")

        self._loop_thread = threading.Thread(target=_run, daemon=True, name="slack-socket")
        self._loop_thread.start()
        # 阻止startup()，直到处理程序线程退出，与其他通道匹配
        # 行为（启动是一个阻塞调用）。
        self._loop_thread.join()

    def _register_handlers(self):
        app = self._app

        # app_mention：机器人在频道中被@提及
        @app.event("app_mention")
        def _on_app_mention(event, ack):
            ack()
            self._handle_event(event, is_group=True)

        # 消息：DM 和频道消息（包括话题回复）
        @app.event("message")
        def _on_message(event, ack):
            ack()
            self._handle_message_event(event)

    def stop(self):
        logger.info("[Slack] stop() called")
        try:
            if self._handler is not None:
                self._handler.close()
        except Exception as e:
            logger.warning(f"[Slack] handler close error: {e}")
        if self._loop_thread and self._loop_thread.is_alive():
            try:
                self._loop_thread.join(timeout=10)
            except Exception:
                pass
        logger.info("[Slack] stop() completed")

    # ------------------------------------------------------------------
    # 入站：slack 事件 -> ChatMessage -> ChatChannel.product
    # ------------------------------------------------------------------

    def _handle_message_event(self, event: dict):
        """Route a raw `message` event: skip bot/system noise, decide grouping."""
        try:
            logger.debug(
                f"[Slack] message event: channel_type={event.get('channel_type')}, "
                f"subtype={event.get('subtype')}, user={event.get('user')}, "
                f"ts={event.get('ts')}, thread_ts={event.get('thread_ts')}"
            )
            # 忽略机器人消息（包括我们自己的消息）和消息编辑/删除
            if event.get("bot_id") or event.get("subtype") in ("bot_message", "message_changed", "message_deleted"):
                return
            if event.get("user") == self.bot_user_id:
                return

            channel_type = event.get("channel_type", "")
            # DM (im) 是单聊；频道/群组是群聊。应用提及
            # 已经涵盖了频道 @-提及，因此对于普通频道消息，我们
            # 仅在配置/线程跟踪时做出反应。
            is_group = channel_type in ("channel", "group", "mpim")
            if is_group:
                # app_mention 处理程序涵盖显式@bot；这里我们只处理
                # 机器人参与的线程中的后续回复。
                if not self._should_reply_in_channel(event):
                    return
            self._handle_event(event, is_group=is_group)
        except Exception as e:
            logger.error(f"[Slack] _handle_message_event error: {e}", exc_info=True)

    def _handle_event(self, event: dict, is_group: bool):
        """Parse event -> build SlackMessage -> produce()."""
        try:
            channel_id = event.get("channel", "")
            ts = event.get("ts", "")
            if not channel_id:
                return

            # 幂等重复数据删除
            msg_uid = f"{channel_id}:{ts}"
            if self._received_msgs.get(msg_uid):
                return
            self._received_msgs[msg_uid] = True

            # 如果需要，解析类型+下载媒体。
            ctype, content, caption = self._parse_event(event)
            if ctype is None:
                logger.debug(f"[Slack] unsupported message type, skip. event={event}")
                return

            # 从频道文本中删除 <@bot_user_id> 提及
            if is_group and self.bot_user_id:
                if ctype == ContextType.TEXT and content:
                    content = self._strip_at_mention(content)
                if caption:
                    caption = self._strip_at_mention(caption)

            slack_msg = SlackMessage(
                event,
                is_group=is_group,
                bot_user_id=self.bot_user_id,
                ctype=ctype,
                content=content,
            )
            slack_msg.is_at = is_group  # 如果我们在频道中到达这里，就会提到/线程化机器人

            from channel.file_cache import get_file_cache
            file_cache = get_file_cache()
            session_id = self._compute_session_id(event, is_group)

            # 媒体+标题一起：视为完整查询并绕过缓存
            if ctype in (ContextType.IMAGE, ContextType.FILE) and caption:
                tag = "image" if ctype == ContextType.IMAGE else "file"
                merged_text = f"{caption}\n[{tag}: {content}]"
                slack_msg.ctype = ContextType.TEXT
                slack_msg.content = merged_text
                ctype = ContextType.TEXT
                logger.info(f"[Slack] Media+caption merged for session {session_id}")
                # 跳转到下面的 TEXT 分支

            elif ctype == ContextType.IMAGE:
                file_cache.add(session_id, content, file_type="image")
                logger.info(f"[Slack] Image cached for session {session_id}, waiting for query...")
                return
            elif ctype == ContextType.FILE:
                file_cache.add(session_id, content, file_type="file")
                logger.info(f"[Slack] File cached for session {session_id}: {content}")
                return

            if ctype == ContextType.TEXT:
                # 快速路径：/cancel 镜像 Web 渠道行为
                if (content or "").strip().lower() in ("/cancel", "cancel"):
                    self._do_cancel(session_id, channel_id, event)
                    return

                cached_files = file_cache.get(session_id)
                if cached_files:
                    refs = []
                    for fi in cached_files:
                        ftype = fi["type"]
                        tag = ftype if ftype in ("image", "video") else "file"
                        refs.append(f"[{tag}: {fi['path']}]")
                    slack_msg.content = (slack_msg.content or "") + "\n" + "\n".join(refs)
                    file_cache.clear(session_id)
                    logger.info(f"[Slack] Attached {len(cached_files)} cached file(s) to query")

            # 如果存在，请在原始线程中回复，否则在此消息上启动一个
            thread_ts = event.get("thread_ts") or ts

            context = self._compose_context(
                slack_msg.ctype,
                slack_msg.content,
                isgroup=is_group,
                msg=slack_msg,
                # 回复返回线程，无需手动@提及
                no_need_at=True,
            )
            if context:
                context["session_id"] = session_id
                context["receiver"] = channel_id
                context["slack_channel"] = channel_id
                context["slack_thread_ts"] = thread_ts if is_group else None
                from agent.team_addressing import stamp_speaker_from_channel
                stamp_speaker_from_channel(self, context, slack_msg.content)
                self.produce(context)
            logger.debug(f"[Slack] received: type={ctype}, content={str(slack_msg.content)[:80]}")
        except Exception as e:
            logger.error(f"[Slack] _handle_event error: {e}", exc_info=True)

    def _do_cancel(self, session_id: str, channel_id: str, event: dict):
        """Fast-path: /cancel calls cancel_session directly without going through agent."""
        try:
            from agent.protocol import get_cancel_registry
            from bridge.bridge import Bridge
            agent_bridge = Bridge().get_agent_bridge()
            agent_id = agent_bridge.agent_router.resolve(
                explicit_agent_id=getattr(self, "bound_agent_id", "") or None,
            )
            scoped_session_id = agent_bridge._cancel_key(
                agent_id, session_id, agent_bridge.agent_registry.default_agent_id
            )
            cancelled = get_cancel_registry().cancel_session(scoped_session_id)
            text = "Current task cancelled." if cancelled else "No running task to cancel."
            thread_ts = event.get("thread_ts") or event.get("ts")
            self._client.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts)
            logger.info(f"[Slack] /cancel session={session_id}, cancelled={cancelled}")
        except Exception as e:
            logger.error(f"[Slack] /cancel error: {e}", exc_info=True)

    def _parse_event(self, event: dict):
        """Parse a slack event and return (ctype, content, caption).

        - content is text for ContextType.TEXT, otherwise the local file path
        - caption is the optional text accompanying a file; empty for plain text
        """
        text = (event.get("text") or "").strip()
        files = event.get("files") or []

        if files:
            # 处理第一个附件；标题是附带的消息文本
            f = files[0]
            mimetype = (f.get("mimetype") or "").lower()
            url = f.get("url_private_download") or f.get("url_private")
            name = f.get("name") or f.get("id") or "file"
            if not url:
                return (None, None, "")
            path = self._download_file(url, name)
            if not path:
                return (None, None, "")
            if mimetype.startswith("image/"):
                return (ContextType.IMAGE, path, text)
            return (ContextType.FILE, path, text)

        if text:
            return (ContextType.TEXT, text, "")

        return (None, None, "")

    def _download_file(self, url: str, name: str):
        """Download a Slack private file (requires bot token auth) to local tmp dir."""
        try:
            headers = {"Authorization": f"Bearer {self.bot_token}"}
            resp = requests.get(url, headers=headers, timeout=60, stream=True)
            resp.raise_for_status()
            tmp_dir = SlackMessage.get_tmp_dir()
            # 通过 url 尾部清理名称并保持其唯一性
            safe_name = re.sub(r"[^\w.\-]", "_", name)
            local_path = os.path.join(tmp_dir, safe_name)
            with open(local_path, "wb") as fp:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        fp.write(chunk)
            logger.debug(f"[Slack] downloaded {name} -> {local_path}")
            return local_path
        except Exception as e:
            logger.error(f"[Slack] download_file failed ({name}): {e}")
            return None

    # ------------------------------------------------------------------
    # 通道触发逻辑
    # ------------------------------------------------------------------

    def _should_reply_in_channel(self, event: dict) -> bool:
        """Decide whether to reply to a plain channel message (no @mention).

        app_mention already handles explicit @bot, so here we only deal with
        follow-up messages. `all` replies to every message; `mention_or_reply`
        replies inside threads the bot already participates in.
        """
        mode = conf().get("slack_group_trigger", "mention_or_reply")
        if mode == "all":
            return True
        if mode == "mention_only":
            return False
        # 提及或回复：仅在现有线程内跟进
        return bool(event.get("thread_ts"))

    def _strip_at_mention(self, content: str) -> str:
        """Strip <@BOT_USER_ID> from channel text."""
        if not content or not self.bot_user_id:
            return content
        pattern = re.compile(r"<@" + re.escape(self.bot_user_id) + r">", re.IGNORECASE)
        return pattern.sub("", content).strip()

    @staticmethod
    def _compute_session_id(event: dict, is_group: bool) -> str:
        channel_id = event.get("channel", "")
        user_id = event.get("user", "")
        if is_group:
            if conf().get("group_shared_session", True):
                return f"slack_channel_{channel_id}"
            return f"slack_channel_{channel_id}_{user_id}"
        return f"slack_user_{user_id}"

    # ------------------------------------------------------------------
    # 覆盖 _compose_context：跳过父组白名单/at 检查
    # （已通过 _should_reply_in_channel 处理）。与电报相同的想法。
    # ------------------------------------------------------------------

    def _compose_context(self, ctype: ContextType, content, **kwargs):
        context = Context(ctype, content)
        context.kwargs = kwargs
        if "channel_type" not in context:
            context["channel_type"] = self.channel_type
        self.stamp_instance_context(context)
        if "origin_ctype" not in context:
            context["origin_ctype"] = ctype

        cmsg = context["msg"]
        if cmsg.is_group:
            if conf().get("group_shared_session", True):
                context["session_id"] = cmsg.other_user_id
            else:
                context["session_id"] = f"{cmsg.from_user_id}:{cmsg.other_user_id}"
        else:
            context["session_id"] = cmsg.from_user_id
        context["receiver"] = cmsg.other_user_id

        if ctype == ContextType.TEXT:
            img_match_prefix = check_prefix(content, conf().get("image_create_prefix"))
            if img_match_prefix:
                content = content.replace(img_match_prefix, "", 1)
                context.type = ContextType.IMAGE_CREATE
            else:
                context.type = ContextType.TEXT
            context.content = (content or "").strip()
            if "desire_rtype" not in context and conf().get("always_reply_voice"):
                context["desire_rtype"] = ReplyType.VOICE
        elif ctype == ContextType.VOICE:
            if "desire_rtype" not in context and (
                conf().get("voice_reply_voice") or conf().get("always_reply_voice")
            ):
                context["desire_rtype"] = ReplyType.VOICE

        return context

    # ------------------------------------------------------------------
    # 出站：ChatChannel.send -> Slack Web API
    # ------------------------------------------------------------------

    def send(self, reply: Reply, context: Context):
        """Called from cow's sync main thread; Slack Web client is sync-safe."""
        if self._client is None:
            logger.warning("[Slack] client not ready, drop reply")
            return

        channel_id = context.get("slack_channel")
        thread_ts = context.get("slack_thread_ts")
        if not channel_id:
            logger.warning("[Slack] no slack_channel in context, drop reply")
            return

        try:
            self._do_send(reply, channel_id, thread_ts)
            logger.info(f"[Slack] sent reply (type={reply.type}, channel={channel_id})")
        except Exception as e:
            logger.error(f"[Slack] send failed: {e}", exc_info=True)

    def _do_send(self, reply: Reply, channel_id: str, thread_ts):
        rtype = reply.type
        content = reply.content

        if rtype in (ReplyType.TEXT, ReplyType.INFO, ReplyType.ERROR):
            text = str(content) if content is not None else ""
            if not text:
                return
            # Slack 将一条消息的长度限制在 4 万个字符左右；保守地分裂
            for chunk in _split_text(text, 3500):
                self._client.chat_postMessage(channel=channel_id, text=chunk, thread_ts=thread_ts)

        elif rtype == ReplyType.IMAGE:
            # 已经是本地 BytesIO；直接上传
            content.seek(0)
            self._client.files_upload_v2(
                channel=channel_id, file=content, filename="image.png", thread_ts=thread_ts,
            )

        elif rtype == ReplyType.IMAGE_URL:
            url = str(content)
            if url.startswith("file://"):
                local = url[7:]
                self._client.files_upload_v2(
                    channel=channel_id, file=local, thread_ts=thread_ts,
                )
            else:
                # 以文本形式发布 URL； Slack 会将其展开为图像预览
                self._client.chat_postMessage(channel=channel_id, text=url, thread_ts=thread_ts)

        elif rtype in (ReplyType.VOICE, ReplyType.FILE):
            local = content[7:] if isinstance(content, str) and content.startswith("file://") else content
            caption = getattr(reply, "text_content", None) or None
            self._client.files_upload_v2(
                channel=channel_id, file=local, initial_comment=caption, thread_ts=thread_ts,
            )

        else:
            # 后备：以纯文本形式发送
            self._client.chat_postMessage(channel=channel_id, text=str(content), thread_ts=thread_ts)


def _split_text(text: str, limit: int):
    """Split long text preferring line breaks to keep markdown structure intact."""
    if len(text) <= limit:
        yield text
        return
    buf = []
    size = 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > limit and buf:
            yield "".join(buf)
            buf, size = [], 0
        # 硬分割超出限制的单线
        while len(line) > limit:
            yield line[:limit]
            line = line[limit:]
        buf.append(line)
        size += len(line)
    if buf:
        yield "".join(buf)
