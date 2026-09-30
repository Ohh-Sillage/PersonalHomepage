"""统一日志配置：控制台 + 按天轮转的文件日志，自动清理过期文件。

日志文件（项目根目录 logs/）：
- app.log      应用与访问日志（INFO+），保留最近 14 天
- security.log 安全事件（4xx/5xx、可疑扫描、限流拦截），保留最近 14 天

服务器上位于 /opt/homepage/logs/，可用 python sync.py logs 拉取到本地排查。
"""

import logging
import logging.handlers
import sys

from app.config import BASE_DIR

LOG_DIR = BASE_DIR / "logs"
KEEP_DAYS = 14  # 日志保留天数：更早的轮转文件由 handler 自动删除

_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _formatter() -> logging.Formatter:
    return logging.Formatter(_FORMAT, _DATE_FORMAT)


def _make_file_handler(filename: str, level: int) -> logging.Handler | None:
    """创建按天轮转、自动清理的文件 handler；目录不可写时返回 None（降级为仅控制台）。"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.TimedRotatingFileHandler(
            LOG_DIR / filename,
            when="midnight",
            interval=1,
            backupCount=KEEP_DAYS,
            encoding="utf-8",
        )
        handler.setLevel(level)
        handler.setFormatter(_formatter())
        return handler
    except OSError:
        return None


def setup_logging() -> None:
    """初始化根日志：文件（app.log）+ 控制台（systemd journal 中同样可见）。"""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    file_handler = _make_file_handler("app.log", logging.INFO)
    if file_handler:
        root.addHandler(file_handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(_formatter())
    root.addHandler(console)

    # uvicorn 自身日志并入统一输出；访问日志由自定义中间件记录，关掉默认的避免重复
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # 第三方库降噪（httpx 每次请求都会打 INFO 日志，太吵）
    for name in ("httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取应用日志器（写入 app.log + 控制台）。"""
    return logging.getLogger(name)


def security_logger() -> logging.Logger:
    """安全事件日志器：额外写入 logs/security.log（同时保留在 app.log 完整时间线中）。"""
    logger = logging.getLogger("security")
    if not logger.handlers:
        handler = _make_file_handler("security.log", logging.WARNING)
        if handler:
            logger.addHandler(handler)
    return logger
