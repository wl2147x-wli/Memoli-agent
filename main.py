"""旧脚本兼容入口；推荐安装后直接执行 ``memoli``。"""

from __future__ import annotations

import sys

from memoli_agent.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["chat", *sys.argv[1:]]))
