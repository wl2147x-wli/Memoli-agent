# -*- coding=utf-8 -*-
"""
Adapter that turns a single `sync_msg` item from WeCom customer-service
into a CoW `ChatMessage` object.
"""
import os
import re

from wechatpy.enterprise import WeChatClient

from bridge.context import ContextType
from channel.chat_message import ChatMessage
from common.log import logger
from common import state_dir


def _get_tmp_dir() -> str:
    """Save under agent_workspace/tmp/ so agent tools (e.g. `read`) can
    resolve a relative path like `tmp/xxx.pdf` against their own
    workspace root. Mirrors the convention used by weixin / wecom_bot.
    """
    return str(state_dir.tmp_dir())


def _extract_filename(content_disposition: str) -> str:
    """Best-effort parse of `filename` / `filename*` from a Content-Disposition
    header. Returns '' when nothing usable is found."""
    if not content_disposition:
        return ""
    # RFC 5987 形式：文件名*=UTF-8''xxx
    m = re.search(r"filename\*=(?:[^'\"]*'[^']*'\s*)?([^;]+)", content_disposition)
    if m:
        try:
            from urllib.parse import unquote
            return unquote(m.group(1).strip().strip('"'))
        except Exception:
            return m.group(1).strip().strip('"')
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', content_disposition)
    return m.group(1).strip() if m else ""


class WechatKfMessage(ChatMessage):
    """
    msg structure (from cgi-bin/kf/sync_msg):
        {
          "msgid": "...",
          "send_time": 1700000000,
          "origin": 3,
          "msgtype": "text" | "image" | "voice" | ...,
          "open_kfid": "wkxxxx",
          "external_userid": "wmxxxx",
          "text": {"content": "..."},
          "image": {"media_id": "..."},
          "voice": {"media_id": "..."},
          ...
        }
    """

    def __init__(self, msg: dict, client: WeChatClient = None, is_group: bool = False):
        # 注意：跳过父构造函数，因为它需要解析 wechatpy
        # 消息对象，而在这里我们从sync_msg接收到一个原始字典。
        super().__init__(msg)
        self.is_group = is_group
        self.msg_id = msg.get("msgid")
        self.create_time = msg.get("send_time")
        self.origin = msg.get("origin")
        self.msgtype = msg.get("msgtype")
        self.open_kfid = msg.get("open_kfid")
        self.external_userid = msg.get("external_userid")

        if self.msgtype == "text":
            self.ctype = ContextType.TEXT
            self.content = msg.get("text", {}).get("content", "")
        elif self.msgtype == "image":
            self.ctype = ContextType.IMAGE
            media_id = msg.get("image", {}).get("media_id", "")
            self.content = os.path.join(_get_tmp_dir(), media_id + ".jpg")

            def download_image():
                response = client.media.download(media_id)
                if response.status_code == 200:
                    with open(self.content, "wb") as f:
                        f.write(response.content)
                else:
                    logger.info(f"[wechat_kf] Failed to download image, {response.content}")

            self._prepare_fn = download_image
        elif self.msgtype == "voice":
            self.ctype = ContextType.VOICE
            media_id = msg.get("voice", {}).get("media_id", "")
            # WeCom默认返回amr；下游语音管道将进行转换。
            self.content = os.path.join(_get_tmp_dir(), media_id + ".amr")

            def download_voice():
                response = client.media.download(media_id)
                if response.status_code == 200:
                    with open(self.content, "wb") as f:
                        f.write(response.content)
                else:
                    logger.info(f"[wechat_kf] Failed to download voice, {response.content}")

            self._prepare_fn = download_voice
        elif self.msgtype == "file":
            self.ctype = ContextType.FILE
            media_id = msg.get("file", {}).get("media_id", "")
            # 临时路径；一旦我们有，就在 download_file() 中重写
            # Content-Disposition 中的原始文件名。
            self.content = os.path.join(_get_tmp_dir(), media_id)

            def download_file():
                response = client.media.download(media_id)
                if response.status_code == 200:
                    filename = _extract_filename(
                        response.headers.get("Content-Disposition", "")
                    ) or media_id
                    self.content = os.path.join(_get_tmp_dir(), filename)
                    with open(self.content, "wb") as f:
                        f.write(response.content)
                else:
                    logger.info(f"[wechat_kf] Failed to download file, {response.content}")

            self._prepare_fn = download_file
        else:
            raise NotImplementedError(
                f"[wechat_kf] Unsupported message type: {self.msgtype}"
            )

        self.from_user_id = self.external_userid
        self.to_user_id = self.open_kfid
        self.other_user_id = self.external_userid
