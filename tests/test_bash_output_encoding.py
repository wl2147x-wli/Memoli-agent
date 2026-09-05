# 编码：utf-8
"""
Regression test for the Bash tool spilling large output to a temp file.

When a command's output exceeds DEFAULT_MAX_BYTES the full output is written to
a temp file. That file must be opened with encoding='utf-8'; otherwise it falls
back to the platform locale encoding (e.g. cp936/GBK on Chinese Windows), which
raises UnicodeEncodeError for output containing emoji or other characters not
representable in that codepage. The exception previously propagated out and
turned an otherwise-successful command (exit code 0) into a tool error, losing
all of its output.
"""
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.bash.bash import Bash


def test_large_non_locale_output_is_saved_as_utf8(tmp_path):
    tool = Bash({"cwd": str(tmp_path), "safety_mode": False})

    # 发出 ~80KB (> 50KB DEFAULT_MAX_BYTES) 的表情符号，以便该工具溢出
    # 完整输出到临时文件。原始 UTF-8 字节是从子进程写入的，因此
    # 命令行保持纯 ASCII，孩子自己的标准输出编码是
    # 无关紧要。
    code = "import sys; sys.stdout.buffer.write((chr(0x1F389) * 20000).encode('utf-8'))"
    command = f'"{sys.executable}" -c "{code}"'

    real_named_temp_file = tempfile.NamedTemporaryFile
    captured = {}

    def spy(*args, **kwargs):
        captured.update(kwargs)
        return real_named_temp_file(*args, **kwargs)

    temp_file_path = None
    try:
        with patch(
            "agent.tools.bash.bash.tempfile.NamedTemporaryFile", side_effect=spy
        ):
            result = tool.execute({"command": command, "timeout": 60})

        # 命令成功，因此该工具不得报告错误。
        assert result.status == "success", result.result

        # 临时文件必须以 UTF-8 格式打开（实际修复）。
        assert captured.get("encoding") == "utf-8"

        # 并且表情符号必须在保存的文件中往返。
        temp_file_path = result.result["details"]["full_output_path"]
        with open(temp_file_path, encoding="utf-8") as f:
            assert "\U0001f389" in f.read()
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
