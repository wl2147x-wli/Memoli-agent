#!/usr/bin/env bash
#
# 通过 PyInstaller 将桌面后端构建为独立的 onedir 包。
# 从任何地方逃跑；路径是相对于存储库根解析的。
#
# 用途：
#   bash 桌面/build/build-backend.sh # 构建
#   PYTHON=python3.11 bashdesktop/build/build-backend.sh # 选择解释器
#
# 输出：desktop/build/dist/cowagent-backend/（包含可执行文件的文件夹）
set -euo pipefail

# ---解析路径--------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUILD_DIR="$SCRIPT_DIR"
VENV_DIR="$BUILD_DIR/.venv-build"

# 首选 Python 3.11（如果可用）：在 3.13+ 上，web.py 必须从
# GitHub git 源（PyPI 构建失败），在某些网络上不稳定。
# 3.11 直接从 PyPI 安装 web.py 并拥有最好的 PyInstaller 支持。
if [ -z "${PYTHON:-}" ]; then
  for cand in \
    "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11" \
    "python3.11" \
    "python3.12" \
    "python3"; do
    if command -v "$cand" >/dev/null 2>&1; then
      PYTHON="$cand"
      break
    fi
  done
fi
# 更喜欢 Python 3.11：它从 PyPI 安装 web.py（无 GitHub 克隆）并避免
# 3.13 删除了 cgi 兼容性垫片。如果需要，用 PYTHON=... 覆盖。
pick_python() {
  if [ -n "${PYTHON:-}" ]; then echo "$PYTHON"; return; fi
  for c in python3.11 python3.12 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1; then echo "$c"; return; fi
  done
  echo python3
}
PYTHON="$(pick_python)"

echo "==> Repo root: $ROOT"
echo "==> Using Python: $($PYTHON --version 2>&1) ($PYTHON)"

# --- 隔离构建 venv --------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
  echo "==> Creating build venv at $VENV_DIR"
  "$PYTHON" -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "==> Installing build dependencies"
pip install -q --upgrade pip
# 如果 deps 失败（例如片状网络），不要留下一半填充的 venv：
# 否则下一次运行将重用损坏的 venv。
if ! pip install -q -r "$BUILD_DIR/requirements-desktop.txt"; then
  echo "!! Dependency install failed. Removing the build venv so a retry starts clean." >&2
  deactivate || true
  rm -rf "$VENV_DIR"
  exit 1
fi
pip install -q pyinstaller

# --- 从存储库根目录运行 pyinstaller 以便相关数据解析 -------------
cd "$ROOT"
echo "==> Running PyInstaller (onedir)"
pyinstaller "$BUILD_DIR/cowagent-backend.spec" \
  --noconfirm \
  --distpath "$BUILD_DIR/dist" \
  --workpath "$BUILD_DIR/build-work"

echo ""
echo "==> Done. Bundle at: $BUILD_DIR/dist/cowagent-backend/"
du -sh "$BUILD_DIR/dist/cowagent-backend/" 2>/dev/null || true
echo "==> Smoke test: COW_DESKTOP=1 \"$BUILD_DIR/dist/cowagent-backend/cowagent-backend\""
