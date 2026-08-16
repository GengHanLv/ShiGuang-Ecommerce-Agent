"""
作用：记录每次请求的耗时、意图、工具调用结果，用于监控与排错。
"""
import sys
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time}</green> | {level} | {message}")
logger.add("logs/agent.log", rotation="10 MB", retention="7 days", level="INFO")