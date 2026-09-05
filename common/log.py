import logging
import os
import sys
import io


def _log_path():
    # 镜像 config.get_data_root() 而不导入配置（避免循环
    # 导入，因为 config 导入此模块）。桌面构建集
    # COW_DATA_DIR（例如~/.cow）；源部署回退到 CWD。
    data_dir = os.environ.get("COW_DATA_DIR")
    if data_dir:
        data_dir = os.path.expanduser(data_dir)
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "run.log")
    return "run.log"


def _reset_logger(log):
    for handler in log.handlers:
        handler.close()
        log.removeHandler(handler)
        del handler
    log.handlers.clear()
    log.propagate = False
    stdout = sys.stdout
    if hasattr(stdout, "buffer"):
        stdout = io.TextIOWrapper(stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    console_handle = logging.StreamHandler(stdout)
    console_handle.setFormatter(
        logging.Formatter(
            "[%(levelname)s][%(asctime)s][%(filename)s:%(lineno)d] - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    log.addHandler(console_handle)
    # 文件日志记录是尽力而为：如果日志路径不可写（例如
    # 打包的应用程序安装在由非管理员用户运行的程序文件下，其中
    # 不可写的 CWD），回退到仅控制台而不是崩溃
    # 导入时的整个过程。
    try:
        file_handle = logging.FileHandler(_log_path(), encoding="utf-8")
        file_handle.setFormatter(
            logging.Formatter(
                "[%(levelname)s][%(asctime)s][%(filename)s:%(lineno)d] - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        log.addHandler(file_handle)
    except OSError:
        console_handle.handle(
            logging.LogRecord(
                "log", logging.WARNING, __file__, 0,
                "[log] file logging disabled (log path not writable): %s",
                (_log_path(),), None,
            )
        )


def _get_logger():
    log = logging.getLogger("log")
    _reset_logger(log)
    log.setLevel(logging.INFO)
    return log


# 日志句柄
logger = _get_logger()
