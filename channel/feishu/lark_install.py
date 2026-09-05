"""
On-demand provisioning of the ``lark_oapi`` SDK (Feishu channel).

Why this exists
---------------
The desktop client (PyInstaller build) intentionally does **not** bundle
``lark_oapi``: the published SDK is ~122MB unpacked because it ships models for
all 59 Feishu open-platform domains, which is why the channel was dropped from
the desktop build (see zhayujie/CowAgent#2987 — "客户端没有飞书通道").

Instead the first time a user enables Feishu in desktop mode we fetch a trimmed,
pure-Python bundle (~1MB) built by ``desktop/build/build-feishu-vendor.py``,
unpack it into a writable per-user directory and put that on ``sys.path``. The
bundle is published once per SDK version and mirrored (see ``VENDOR_URLS``).

Running ``pip`` at this point is not an option: the frozen app has no real
Python interpreter — ``sys.executable`` is the bundled backend itself — so
``sys.executable -m pip`` does not behave like pip. Unpacking a prebuilt archive
needs nothing but the import machinery, which works normally in a frozen build.

For source / non-desktop installs ``lark_oapi`` comes from ``requirements.txt``
and this module simply confirms it is importable.
"""
import hashlib
import importlib
import importlib.util
import io
import logging
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile

try:
    from common.log import logger
except Exception:  # pragma: no cover - common may be unavailable in isolation
    logger = logging.getLogger("feishu_lark_install")

LARK_PKG = "lark-oapi"
LARK_MIN = "1.5.5"

# 每当发布新捆绑包时都会发生碰撞：“<lark version>-<bundle revision>”。
VENDOR_VERSION = "1.7.1-1"

# 已发布存档的 sha256。构建器为 a 发出一个字节相同的 zip
# 给定的版本，所以这个引脚是稳定的；这就是使下载安全的原因
# 信任。仅针对本地实验留空（然后跳过验证
# 并带有警告）。
VENDOR_SHA256 = "a96de70291e43b4829a5f717035806835f116bf4dc1d0a2d2ed551908a825381"

# 按顺序尝试；桌面安装程序使用相同的镜像。飞书是一个
# 仅限中国产品，因此国内CDN优先。任何镜子都是安全的
# 因为有效负载是根据 VENDOR_SHA256 检查的。
VENDOR_URLS = (
    "https://cdn.link-ai.tech/desktop/vendor/feishu-vendor-{version}.zip",
    "https://cdn.cowagent.ai/desktop/vendor/feishu-vendor-{version}.zip",
)

DOWNLOAD_TIMEOUT = 120

# 每用户、可写、持久位置。镜像浏览器工具的 ~/.cow
# 这样 CowAgent 拥有的所有东西都集中在一个屋檐下。
_VENDOR_SUBDIR = os.path.join(".cow", "feishu_vendor")


def _install_error(reason: str = "") -> ImportError:
    detail = f" ({reason})" if reason else ""
    return ImportError(
        f"lark_oapi is required for the Feishu channel but is not available{detail}. "
        f"Install it with: pip install -U '{LARK_PKG}>={LARK_MIN}'"
    )


def vendor_dir() -> str:
    """Return the directory the trimmed SDK is unpacked into.

    Versioned so a newer bundle never has to overwrite a directory that a
    running process may still be importing from.
    """
    base = os.environ.get("COW_DATA_DIR") or os.path.expanduser("~")
    return os.path.join(base, _VENDOR_SUBDIR, VENDOR_VERSION)


def vendor_urls() -> list:
    """Candidate download URLs, most preferred first."""
    override = os.environ.get("COW_FEISHU_VENDOR_URL")
    if override:
        return [override]
    return [url.format(version=VENDOR_VERSION) for url in VENDOR_URLS]


def is_available() -> bool:
    """True if lark_oapi can be imported right now."""
    return importlib.util.find_spec("lark_oapi") is not None


def needs_download() -> bool:
    """True if enabling Feishu would have to fetch the bundle first.

    Lets the UI warn about the one-time wait before it happens; ``ensure``
    re-checks anyway, so a stale answer only costs a misplaced hint.
    """
    return not is_available() and not os.path.isdir(vendor_dir())


def _activate(path: str) -> bool:
    """Put an unpacked bundle on sys.path and report whether it took effect."""
    if not os.path.isdir(path):
        return False
    if path not in sys.path:
        sys.path.insert(0, path)
        # find_spec 查阅缓存的查找器，这些查找器在
        # 目录已存在。
        importlib.invalidate_caches()
    return is_available()


def _fetch(url: str) -> bytes:
    logger.info("[FeiShu] downloading Feishu SDK bundle from %s", url)
    # 海外镜像位于 CDN 后面，该 CDN 对 urllib 的默认响应 403
    # User-Agent，因此未命名的请求只会到达中国镜像。
    req = urllib.request.Request(url, headers={"User-Agent": "CowAgent"})
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
        return resp.read()


def _verify(payload: bytes) -> None:
    if not VENDOR_SHA256:
        logger.warning("[FeiShu] VENDOR_SHA256 is unset; skipping integrity check")
        return
    digest = hashlib.sha256(payload).hexdigest()
    if digest != VENDOR_SHA256:
        raise ValueError(f"checksum mismatch: expected {VENDOR_SHA256}, got {digest}")


def _safe_extract(payload: bytes, dest: str) -> None:
    """Unpack the archive, refusing entries that escape ``dest``."""
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for name in zf.namelist():
            target = os.path.realpath(os.path.join(dest, name))
            if not target.startswith(os.path.realpath(dest) + os.sep):
                raise ValueError(f"refusing to extract outside the vendor dir: {name}")
        zf.extractall(dest)


def _download() -> bytes:
    """Fetch the bundle, falling back through the mirrors on failure."""
    last = None
    for url in vendor_urls():
        try:
            payload = _fetch(url)
            _verify(payload)
            return payload
        except Exception as exc:
            last = exc
            logger.warning("[FeiShu] could not fetch the bundle from %s: %s", url, exc)
    raise last


def _provision(target: str) -> None:
    """Download and unpack the bundle into ``target`` atomically."""
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    payload = _download()

    staging = tempfile.mkdtemp(prefix=".incomplete-", dir=parent)
    try:
        _safe_extract(payload, staging)
        try:
            os.rename(staging, target)
        except OSError:
            # 另一个进程赢得了比赛，或者平台拒绝重命名
            # 到现有目录；它的副本是等效的。
            if not os.path.isdir(target):
                raise
            shutil.rmtree(staging, ignore_errors=True)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def ensure(allow_install: bool = True) -> None:
    """Make ``lark_oapi`` importable, fetching the bundle if needed.

    - Already importable (source install, or a previous download): return.
    - Desktop mode with ``allow_install``: download the trimmed bundle and add
      it to ``sys.path``.
    - Otherwise: raise ``ImportError`` with actionable guidance.
    """
    if is_available():
        return

    target = vendor_dir()
    # 之前的运行可能已经将其解压。
    if _activate(target):
        return

    if not allow_install:
        raise _install_error()

    # 源/非桌面安装从requirements.txt获取它。
    if os.environ.get("COW_DESKTOP") != "1":
        raise _install_error()

    logger.warning(
        "[FeiShu] Feishu SDK not present; fetching the bundle into %s. "
        "This happens once and needs a network connection.", target,
    )
    try:
        _provision(target)
    except Exception as exc:
        logger.error("[FeiShu] failed to provision the Feishu SDK bundle: %s", exc)
        raise _install_error(str(exc)) from exc

    if not _activate(target):
        raise _install_error("bundle unpacked but lark_oapi is still not importable")
    logger.info("[FeiShu] Feishu SDK bundle ready at %s", target)
