"""
Telegram channel via Bot API (long polling mode).

Features:
- Single chat & group chat (text / photo / voice / video / document)
- Group trigger: @mention or reply-to-bot (configurable)
- /cancel fast-path matches Web channel behaviour
- Auto-register bot commands menu on startup (mirrors Web slash menu)
- Optional HTTP/SOCKS5 proxy support for restricted networks

Implementation note:
    python-telegram-bot is async-first. We run the bot inside a dedicated
    thread with its own asyncio loop so the rest of cow (which is sync)
    stays untouched. Inbound updates are dispatched onto cow's existing
    sync ChatChannel.produce() pipeline; outbound send() schedules
    coroutines back onto that loop via asyncio.run_coroutine_threadsafe.
"""

import asyncio
import os
import re
import threading

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel, check_prefix
from channel.telegram.telegram_markdown import CAPTION_LIMIT, to_telegram_html
from channel.telegram.telegram_message import TelegramMessage
from common.expired_dict import ExpiredDict
from common.log import logger
from common.singleton import singleton
from config import conf

# 机器人命令菜单，与 Web 斜线命令对齐。
# 仅限顶级命令；子命令用空格输入（例如“/技能列表”）。
TELEGRAM_BOT_COMMANDS = [
    ("help", "Show command help"),
    ("status", "Show running status"),
    ("context", "View/clear conversation context (sub: clear)"),
    ("tasks", "List scheduled tasks for this chat"),
    ("skill", "Manage skills (list/search/install/...)"),
    ("memory", "Manage memory (sub: dream)"),
    ("knowledge", "Manage knowledge base (list/on/off)"),
    ("config", "Show current config"),
    ("cancel", "Cancel running agent task"),
    ("steer", "Guide the running agent task"),
    ("logs", "Show recent logs"),
    ("version", "Show version"),
]


@singleton
class TelegramChannel(ChatChannel):
    NOT_SUPPORT_REPLYTYPE = []

    def __init__(self):
        super().__init__()
        self.bot_token = ""
        self.bot_username = ""  # 用于@提及匹配
        self._bot = None
        self._application = None
        self._loop = None
        self._loop_thread = None
        self._stop_event = threading.Event()
        # 幂等重复数据删除； TG 偶尔会在不稳定的网络上重新提供相同的更新
        self._received_msgs = ExpiredDict(60 * 60 * 1)

        # 禁用组白名单/前缀检查（我们自己处理触发
        # in _should_reply_in_group)，与 feishu / wecom_bot 渠道对齐。
        conf()["group_name_white_list"] = ["ALL_GROUP"]
        conf()["single_chat_prefix"] = [""]

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def startup(self):
        self.bot_token = self.cfg("telegram_token", "")
        if not self.bot_token:
            err = "[Telegram] telegram_token is required"
            logger.error(err)
            self.report_startup_error(err)
            return

        try:
            from telegram.ext import (
                Application,
                MessageHandler,
                CommandHandler,
                filters,
            )
        except ImportError:
            err = (
                "[Telegram] python-telegram-bot is not installed. "
                "Run: pip install python-telegram-bot"
            )
            logger.error(err)
            self.report_startup_error(err)
            return

        # 在专用线程中运行异步事件循环，以便同步牛体
        # 未受影响。
        self._loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._async_main(Application, MessageHandler, CommandHandler, filters))
            except Exception as e:
                logger.error(f"[Telegram] event loop crashed: {e}", exc_info=True)
                self.report_startup_error(str(e))
            finally:
                try:
                    self._loop.close()
                except Exception:
                    pass
                logger.info("[Telegram] event loop exited")

        self._loop_thread = threading.Thread(target=_run_loop, daemon=True, name="telegram-loop")
        self._loop_thread.start()
        # 阻止startup()直到循环线程退出，匹配其他通道'
        # 行为（启动是一个阻塞调用）。
        self._loop_thread.join()

    async def _async_main(self, Application, MessageHandler, CommandHandler, filters):
        """Build Application, register handlers, and run polling."""
        builder = Application.builder().token(self.bot_token)

        # 代理：更喜欢 telegram_proxy 配置，回退到 HTTPS_PROXY env var
        proxy_url = conf().get("telegram_proxy", "") or os.environ.get("HTTPS_PROXY", "")
        if proxy_url:
            try:
                builder = builder.proxy(proxy_url).get_updates_proxy(proxy_url)
                logger.info(f"[Telegram] using proxy: {proxy_url}")
            except Exception as e:
                logger.warning(f"[Telegram] proxy config failed, fallback to direct: {e}")

        # 通过代理上传媒体（照片/语音/视频/文档）可能会很慢，
        # 增加读/写/连接/池超时。
        builder = (
            builder
            .read_timeout(60)
            .write_timeout(120)
            .connect_timeout(30)
            .pool_timeout(30)
        )

        application = builder.build()
        self._application = application
        self._bot = application.bot

        # 获取我们自己的用户名（需要在组中进行@提及匹配）
        try:
            me = await self._bot.get_me()
            self.bot_username = me.username or ""
            self.name = self.bot_username  # ChatChannel 使用 self.name 去除 @-mention
            logger.info(f"[Telegram] Bot logged in as @{self.bot_username} (id={me.id})")
        except Exception as e:
            err = f"[Telegram] get_me failed: {e}"
            logger.error(err)
            self.report_startup_error(err)
            return

        # 注册命令菜单（失败非致命）
        if conf().get("telegram_register_commands", True):
            try:
                from telegram import BotCommand
                cmds = [BotCommand(name, desc) for name, desc in TELEGRAM_BOT_COMMANDS]
                await self._bot.set_my_commands(cmds)
                logger.info(f"[Telegram] Registered {len(cmds)} bot commands")
            except Exception as e:
                logger.warning(f"[Telegram] set_my_commands failed: {e}")

        # 处理程序：
        # 1) /cancel 使用快速路径
        application.add_handler(CommandHandler("cancel", self._on_cancel))
        # 2）普通消息（文字+媒体）
        application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, self._on_message))
        # 3) 其他斜杠命令以纯文本形式转发给代理处理
        application.add_handler(MessageHandler(filters.COMMAND, self._on_command_passthrough))

        # 开始投票。 drop_pending_updates 避免重启后重播积压。
        # get_updates 期间出现短暂的“服务器已断开连接”/RemoteProtocolError
        # 在代理/片状网络上很常见； PTB的网络环路自动重试，
        # 所以我们只需要降低噪音（参见_quiet_polling_network_errors）。
        self._quiet_polling_network_errors()
        logger.info("[Telegram] Starting long polling...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling(
            drop_pending_updates=True,
            # 服务器端的长轮询保持时间；较小的值 = 重新连接更多
            # 经常发生，但每个挂起的连接失败的速度更快。
            timeout=30,
            # 在出现短暂的 get_updates 网络错误时永远重试而不是放弃。
            bootstrap_retries=-1,
        )
        self.report_startup_success()
        logger.info("[Telegram] ✅ Telegram bot ready, polling for updates")

        # 阻塞直到 stop()
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(0.5)
        finally:
            try:
                await application.updater.stop()
                await application.stop()
                await application.shutdown()
            except Exception as e:
                logger.warning(f"[Telegram] shutdown error: {e}")

    @staticmethod
    def _quiet_polling_network_errors():
        """Downgrade PTB's noisy 'Exception happened while polling for updates' logs.

        These transient get_updates errors (RemoteProtocolError / NetworkError /
        TimedOut, typically over a proxy) are auto-retried by PTB's network loop,
        so logging the full traceback at ERROR is just noise. We attach a filter
        that drops these specific records while leaving real errors untouched.
        """
        import logging

        class _PollingNoiseFilter(logging.Filter):
            _NEEDLES = (
                "Exception happened while polling for updates",
                "Server disconnected without sending a response",
            )

            def filter(self, record: logging.LogRecord) -> bool:
                try:
                    msg = record.getMessage()
                except Exception:
                    return True
                if any(n in msg for n in self._NEEDLES):
                    # 在 DEBUG 处保留单行面包屑，删除回溯。
                    logger.debug(f"[Telegram] transient polling network error (auto-retrying): {msg.splitlines()[0]}")
                    return False
                return True

        noise_filter = _PollingNoiseFilter()
        for name in ("telegram.ext.Updater", "telegram.ext._updater", "telegram.ext"):
            logging.getLogger(name).addFilter(noise_filter)

    def stop(self):
        logger.info("[Telegram] stop() called")
        self._stop_event.set()
        if self._loop_thread and self._loop_thread.is_alive():
            try:
                self._loop_thread.join(timeout=10)
            except Exception:
                pass
        logger.info("[Telegram] stop() completed")

    # ------------------------------------------------------------------
    # 入站：电报更新 -> ChatMessage -> ChatChannel.product
    # ------------------------------------------------------------------

    async def _on_cancel(self, update, _context):
        """Fast-path: /cancel calls cancel_session directly without going through agent."""
        try:
            from agent.protocol import get_cancel_registry
            session_id = self._compute_session_id(update)
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
            await update.effective_message.reply_text(text)
            logger.info(f"[Telegram] /cancel session={session_id}, cancelled={cancelled}")
        except Exception as e:
            logger.error(f"[Telegram] /cancel error: {e}", exc_info=True)
            try:
                await update.effective_message.reply_text(f"⚠️ /cancel failed: {e}")
            except Exception:
                pass

    async def _on_command_passthrough(self, update, _context):
        """All non-/cancel commands fall through to plain message handling."""
        await self._on_message(update, _context)

    async def _on_message(self, update, _context):
        """Telegram update entry: parse message -> build ChatMessage -> produce()."""
        try:
            message = update.effective_message
            chat = update.effective_chat
            if not message or not chat:
                return

            # 幂等重复数据删除
            msg_uid = f"{chat.id}:{message.message_id}"
            if self._received_msgs.get(msg_uid):
                return
            self._received_msgs[msg_uid] = True

            is_group = chat.type in ("group", "supergroup")

            # 调试日志：当组消息被悄悄删除时很有用
            if is_group:
                logger.debug(
                    f"[Telegram] group update received: chat_id={chat.id}, "
                    f"text={(message.text or message.caption or '')[:40]!r}, "
                    f"reply_to_bot={bool(message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.username == self.bot_username)}"
                )

            # 群组触发门（如果没有触发则默默下降）
            if is_group and not self._should_reply_in_group(update):
                logger.debug(f"[Telegram] group message not triggered (need @{self.bot_username} or reply), skip")
                return

            # 如果需要，解析消息类型+下载媒体。
            # 带标题的媒体消息返回本地路径和标题文本。
            ctype, content, caption = await self._parse_message(message)
            if ctype is None:
                logger.debug(f"[Telegram] unsupported message type, skip. msg={message}")
                return

            # 删除组文本/标题的 @bot 提及
            if is_group and self.bot_username:
                if ctype == ContextType.TEXT and content:
                    content = self._strip_at_mention(content)
                if caption:
                    caption = self._strip_at_mention(caption)

            tg_msg = TelegramMessage(
                update,
                is_group=is_group,
                bot_username=self.bot_username,
                ctype=ctype,
                content=content,
            )
            tg_msg.is_at = is_group  # 如果我们以小组形式来到这里，则会提到/回复机器人

            # 文件缓存：独立媒体进入缓存，下一个文本查询附加它们
            from channel.file_cache import get_file_cache
            file_cache = get_file_cache()
            session_id = self._compute_session_id(update)

            # 媒体+标题一起：视为完整查询并绕过缓存
            if ctype in (ContextType.IMAGE, ContextType.FILE) and caption:
                tag = "image" if ctype == ContextType.IMAGE else "file"
                merged_text = f"{caption}\n[{tag}: {content}]"
                tg_msg.ctype = ContextType.TEXT
                tg_msg.content = merged_text
                ctype = ContextType.TEXT
                logger.info(f"[Telegram] Media+caption merged for session {session_id}")
                # 跳转到下面的 TEXT 分支

            elif ctype == ContextType.IMAGE:
                file_cache.add(session_id, content, file_type="image")
                logger.info(f"[Telegram] Image cached for session {session_id}, waiting for query...")
                return
            elif ctype == ContextType.FILE:
                file_cache.add(session_id, content, file_type="file")
                logger.info(f"[Telegram] File cached for session {session_id}: {content}")
                return

            if ctype == ContextType.TEXT:
                cached_files = file_cache.get(session_id)
                if cached_files:
                    refs = []
                    for fi in cached_files:
                        ftype = fi["type"]
                        tag = ftype if ftype in ("image", "video") else "file"
                        refs.append(f"[{tag}: {fi['path']}]")
                    tg_msg.content = (tg_msg.content or "") + "\n" + "\n".join(refs)
                    file_cache.clear(session_id)
                    logger.info(f"[Telegram] Attached {len(cached_files)} cached file(s) to query")

            # 调度到cow主管道（重用ChatChannel._compose_context路由）
            context = self._compose_context(
                tg_msg.ctype,
                tg_msg.content,
                isgroup=is_group,
                msg=tg_msg,
            )
            if context:
                context["session_id"] = session_id
                context["receiver"] = str(chat.id)
                context["telegram_chat_id"] = chat.id
                context["telegram_reply_to_msg_id"] = message.message_id if is_group else None
                from agent.team_addressing import stamp_speaker_from_channel
                stamp_speaker_from_channel(self, context, tg_msg.content)
                self.produce(context)
            logger.debug(f"[Telegram] received: type={ctype}, content={str(tg_msg.content)[:80]}")

        except Exception as e:
            logger.error(f"[Telegram] _on_message error: {e}", exc_info=True)

    async def _parse_message(self, message):
        """Parse a telegram message and return (ctype, content, caption).

        - content is text for ContextType.TEXT, otherwise the local file path
        - caption is the optional text accompanying a media message; empty for plain text
        """
        caption = (message.caption or "").strip()

        if message.photo:
            largest = message.photo[-1]
            path = await self._download_file(largest.file_id, suffix=".jpg")
            return (ContextType.IMAGE, path, caption) if path else (None, None, "")

        if message.voice or message.audio:
            audio_obj = message.voice or message.audio
            suffix = ".ogg" if message.voice else (
                "." + (audio_obj.mime_type.split("/")[-1] if getattr(audio_obj, "mime_type", "") else "mp3")
            )
            path = await self._download_file(audio_obj.file_id, suffix=suffix)
            return (ContextType.VOICE, path, caption) if path else (None, None, "")

        if message.video or message.video_note:
            video_obj = message.video or message.video_note
            path = await self._download_file(video_obj.file_id, suffix=".mp4")
            return (ContextType.FILE, path, caption) if path else (None, None, "")

        if message.document:
            doc = message.document
            ext = ""
            if doc.file_name and "." in doc.file_name:
                ext = "." + doc.file_name.rsplit(".", 1)[-1]
            path = await self._download_file(doc.file_id, suffix=ext, original_name=doc.file_name)
            if not path:
                return (None, None, "")
            # 图像类型文档（用户选择“作为文件发送”）被视为图像
            mime = (doc.mime_type or "").lower()
            if mime.startswith("image/"):
                return (ContextType.IMAGE, path, caption)
            return (ContextType.FILE, path, caption)

        if message.text:
            return (ContextType.TEXT, message.text.strip(), "")

        return (None, None, "")

    async def _download_file(self, file_id: str, suffix: str = "", original_name: str = ""):
        """Download via bot.get_file into the local tmp dir; return path or None on failure."""
        try:
            f = await self._bot.get_file(file_id)
            tmp_dir = TelegramMessage.get_tmp_dir()
            base = original_name or f"{file_id}{suffix or ''}"
            # 使用 file_id 前缀以避免名称冲突/奇怪的字符
            safe_name = f"{file_id}_{base}" if original_name else base
            local_path = os.path.join(tmp_dir, safe_name)
            await f.download_to_drive(custom_path=local_path)
            logger.debug(f"[Telegram] downloaded file_id={file_id} -> {local_path}")
            return local_path
        except Exception as e:
            logger.error(f"[Telegram] download_file failed (file_id={file_id}): {e}")
            return None

    # ------------------------------------------------------------------
    # 组触发逻辑
    # ------------------------------------------------------------------

    def _should_reply_in_group(self, update) -> bool:
        """Decide whether to reply to a group message based on configuration."""
        mode = conf().get("telegram_group_trigger", "mention_or_reply")
        if mode == "all":
            return True

        message = update.effective_message
        if not message:
            return False

        # 1) 提到
        if self.bot_username and self._is_mentioned(message, self.bot_username):
            return True

        # 2）回复机器人消息
        if mode == "mention_or_reply":
            reply = message.reply_to_message
            if reply and reply.from_user and reply.from_user.username == self.bot_username:
                return True

        return False

    @staticmethod
    def _is_mentioned(message, bot_username: str) -> bool:
        """Check whether entities/caption_entities contain a @mention of the bot."""
        bot_at = "@" + bot_username.lower()
        text = (message.text or message.caption or "").lower()
        if bot_at in text:
            return True
        # 还要严格检查实体以支持text_mention（无用户名@）
        for ent in (message.entities or []) + (message.caption_entities or []):
            if ent.type == "mention":
                src = message.text or message.caption or ""
                if src[ent.offset: ent.offset + ent.length].lower() == bot_at:
                    return True
        return False

    def _strip_at_mention(self, content: str) -> str:
        """Strip @bot_username from group text (case-insensitive)."""
        if not content or not self.bot_username:
            return content
        pattern = re.compile(r"@" + re.escape(self.bot_username), re.IGNORECASE)
        return pattern.sub("", content).strip()

    @staticmethod
    def _compute_session_id(update) -> str:
        chat = update.effective_chat
        user = update.effective_user
        is_group = chat.type in ("group", "supergroup")
        if is_group:
            if conf().get("group_shared_session", True):
                return f"tg_group_{chat.id}"
            return f"tg_group_{chat.id}_{user.id}"
        return f"tg_user_{user.id}"

    # ------------------------------------------------------------------
    # 覆盖 _compose_context：跳过父组白名单/at 检查
    # （已通过 _should_reply_in_group 在 _on_message 中处理）。同样的想法
    # 作为飞书频道。
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
    # 出站：ChatChannel.send -> Telegram API
    # ------------------------------------------------------------------

    def send(self, reply: Reply, context: Context):
        """Called from cow's sync main thread; we marshal the coroutine onto the loop thread."""
        if self._loop is None or self._bot is None:
            logger.warning("[Telegram] bot not ready, drop reply")
            return

        chat_id = context.get("telegram_chat_id")
        reply_to = context.get("telegram_reply_to_msg_id")
        if chat_id is None:
            logger.warning("[Telegram] no telegram_chat_id in context, drop reply")
            return

        coro = self._async_send(reply, chat_id, reply_to)
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            # 通过代理上传媒体可能会很慢；让PTB自己的暂停获胜
            future.result(timeout=180)
        except Exception as e:
            logger.error(f"[Telegram] send failed: {e}")

    # 暂时性网络错误（代理打嗝等）的重试次数
    _SEND_RETRIES = 2
    _SEND_RETRY_BACKOFF = 2.0  # 秒

    async def _send_with_retry(self, send_fn, *, label: str):
        """Run a single Telegram API call with retries for transient network errors."""
        from telegram.error import BadRequest, NetworkError, TimedOut
        last_err = None
        for attempt in range(self._SEND_RETRIES + 1):
            try:
                return await send_fn()
            except BadRequest:
                # PTB 中 NetworkError 的子类，但请求本身是
                # 格式错误：重试只会延迟失败。
                raise
            except (NetworkError, TimedOut) as e:
                last_err = e
                if attempt >= self._SEND_RETRIES:
                    break
                wait = self._SEND_RETRY_BACKOFF * (attempt + 1)
                logger.warning(
                    f"[Telegram] {label} transient error (attempt {attempt + 1}/"
                    f"{self._SEND_RETRIES + 1}): {e}; retry in {wait}s"
                )
                await asyncio.sleep(wait)
        raise last_err

    async def _send_text(self, text: str, chat_id, reply_to_msg_id):
        """Send markdown as Telegram HTML, splitting on the 4096-char cap.

        One malformed entity makes Telegram reject the whole message, so a
        rejected chunk is resent verbatim rather than dropped.
        """
        from telegram.constants import ParseMode
        from telegram.error import BadRequest

        for chunk in _split_text(text, 4000):
            rendered = to_telegram_html(chunk)
            if not rendered:
                continue
            try:
                await self._send_with_retry(
                    lambda c=rendered: self._bot.send_message(
                        chat_id=chat_id,
                        text=c,
                        parse_mode=ParseMode.HTML,
                        reply_to_message_id=reply_to_msg_id,
                        # 如果删除了reply_to，避免整个发送失败
                        allow_sending_without_reply=True,
                    ),
                    label="send_message",
                )
            except BadRequest as e:
                logger.warning(f"[Telegram] HTML rejected ({e}); resending as plain text")
                await self._send_with_retry(
                    lambda c=chunk: self._bot.send_message(
                        chat_id=chat_id,
                        text=c,
                        reply_to_message_id=reply_to_msg_id,
                        allow_sending_without_reply=True,
                    ),
                    label="send_message(plain)",
                )

    async def _async_send(self, reply: Reply, chat_id, reply_to_msg_id):
        try:
            rtype = reply.type
            content = reply.content

            if rtype == ReplyType.TEXT or rtype == ReplyType.INFO or rtype == ReplyType.ERROR:
                text = str(content) if content is not None else ""
                if not text:
                    return
                await self._send_text(text, chat_id, reply_to_msg_id)

            elif rtype == ReplyType.IMAGE:
                # 已经是本地 BytesIO；直接发送
                content.seek(0)
                await self._send_with_retry(
                    lambda: self._bot.send_photo(
                        chat_id=chat_id,
                        photo=content,
                        reply_to_message_id=reply_to_msg_id,
                        allow_sending_without_reply=True,
                    ),
                    label="send_photo",
                )

            elif rtype == ReplyType.IMAGE_URL:
                url = str(content)
                if url.startswith("file://"):
                    local = url[7:]
                    # 在 lambda 内部打开，以便每次重试都会获得新的流
                    async def _send_local_photo():
                        with open(local, "rb") as f:
                            return await self._bot.send_photo(
                                chat_id=chat_id, photo=f,
                                reply_to_message_id=reply_to_msg_id,
                                allow_sending_without_reply=True,
                            )
                    await self._send_with_retry(_send_local_photo, label="send_photo(file)")
                else:
                    await self._send_with_retry(
                        lambda: self._bot.send_photo(
                            chat_id=chat_id, photo=url,
                            reply_to_message_id=reply_to_msg_id,
                            allow_sending_without_reply=True,
                        ),
                        label="send_photo(url)",
                    )

            elif rtype == ReplyType.VOICE:
                local = content[7:] if isinstance(content, str) and content.startswith("file://") else content
                async def _send_voice():
                    with open(local, "rb") as f:
                        return await self._bot.send_voice(
                            chat_id=chat_id, voice=f,
                            reply_to_message_id=reply_to_msg_id,
                            allow_sending_without_reply=True,
                        )
                await self._send_with_retry(_send_voice, label="send_voice")

            elif rtype == ReplyType.FILE:
                # 视频通过 send_video，其他所有内容通过 send_document
                local = content[7:] if isinstance(content, str) and content.startswith("file://") else content
                # 文件回复可能带有随附的文本标题
                caption = getattr(reply, "text_content", None) or None
                is_video = isinstance(local, str) and local.lower().endswith(
                    (".mp4", ".mov", ".avi", ".mkv", ".webm")
                )

                # 标题的上限远远低于消息，并且标题过大
                # 上传本身失败。任何太长的内容都会单独出现。
                overflow = None
                if caption and len(caption) > CAPTION_LIMIT:
                    caption, overflow = None, caption

                from telegram.constants import ParseMode
                from telegram.error import BadRequest

                async def _send_file(cap, mode):
                    with open(local, "rb") as f:
                        if is_video:
                            return await self._bot.send_video(
                                chat_id=chat_id, video=f, caption=cap, parse_mode=mode,
                                reply_to_message_id=reply_to_msg_id,
                                allow_sending_without_reply=True,
                            )
                        return await self._bot.send_document(
                            chat_id=chat_id, document=f, caption=cap, parse_mode=mode,
                            reply_to_message_id=reply_to_msg_id,
                            allow_sending_without_reply=True,
                        )

                label = "send_video" if is_video else "send_document"
                try:
                    await self._send_with_retry(
                        lambda: _send_file(to_telegram_html(caption) if caption else None, ParseMode.HTML),
                        label=label,
                    )
                except BadRequest as e:
                    logger.warning(f"[Telegram] caption rejected ({e}); resending file without markup")
                    await self._send_with_retry(lambda: _send_file(caption, None), label=f"{label}(plain)")

                if overflow:
                    await self._send_text(overflow, chat_id, reply_to_msg_id)

            else:
                # 后备：以纯文本形式发送
                await self._send_with_retry(
                    lambda: self._bot.send_message(
                        chat_id=chat_id, text=str(content),
                        reply_to_message_id=reply_to_msg_id,
                        allow_sending_without_reply=True,
                    ),
                    label="send_message(fallback)",
                )

            logger.info(f"[Telegram] sent reply (type={rtype}, chat_id={chat_id})")

        except Exception as e:
            logger.error(f"[Telegram] _async_send error: {e}", exc_info=True)


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
