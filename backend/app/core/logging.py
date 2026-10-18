"""在应用启动时统一配置标准日志，覆盖各业务模块。"""

import logging
from logging.handlers import RotatingFileHandler
from backend.app.core.config import ROOT_DIR


def configure_logging():
    directory = ROOT_DIR / "logs"
    directory.mkdir(exist_ok=True)
    handler = RotatingFileHandler(
        directory / "agent.log", maxBytes=10 * 1024 * 1024, backupCount=7, encoding="utf-8"
    )
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    handler.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[console, handler], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
