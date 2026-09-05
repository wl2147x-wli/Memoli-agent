"""
pytts voice service (offline)
"""

import os
import sys
import time

import pyttsx3

from bridge.reply import Reply, ReplyType
from common.log import logger
from common.tmp_dir import TmpDir
from voice.voice import Voice


class PyttsVoice(Voice):
    engine = pyttsx3.init()

    def __init__(self):
        # 语速
        self.engine.setProperty("rate", 125)
        # 音量
        self.engine.setProperty("volume", 1.0)
        if sys.platform == "win32":
            for voice in self.engine.getProperty("voices"):
                if "Chinese" in voice.name:
                    self.engine.setProperty("voice", voice.id)
        else:
            self.engine.setProperty("voice", "zh")
            # 如果espeak的问题解决了，使用runAndWait()并删除这个startLoop()
            # TODO：检查这是否适用于 win32
            self.engine.startLoop(useDriverLoop=False)

    def textToVoice(self, text):
        try:
            # 多线程下避免同名文件
            wavFileName = "reply-" + str(int(time.time())) + "-" + str(hash(text) & 0x7FFFFFFF) + ".wav"
            wavFile = TmpDir().path() + wavFileName
            logger.info("[Pytts] textToVoice text={} voice file name={}".format(text, wavFile))

            self.engine.save_to_file(text, wavFile)

            if sys.platform == "win32":
                self.engine.runAndWait()
            else:
                # 在 ubuntu 中，runAndWait 并不真正等到文件创建。
                # 一旦任务队列为空就会返回，但任务仍在协程中运行。
                # 如果你调用 runAndWait() 和 time.sleep() 两次，它会卡住，所以不要使用这个。
                # 如果要解决此问题，请在 espeak.py 的第 127 行（函数 save_to_file 的开头）添加 self._proxy.setBusy(True)。
                # self.engine.runAndWait()

                # 在espeak解决这个问题之前，我们迭代生成器并自行控制等待。
                # 但这不是使用它的规范方法，例如，如果文件已经存在，它也不能等待。
                self.engine.iterate()
                while self.engine.isBusy() or wavFileName not in os.listdir(TmpDir().path()):
                    time.sleep(0.1)

            reply = Reply(ReplyType.VOICE, wavFile)

        except Exception as e:
            reply = Reply(ReplyType.ERROR, str(e))
        finally:
            return reply
