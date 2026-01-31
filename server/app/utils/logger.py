"""
日志工具模块

结构化日志格式化和应用级日志配置
"""

import json
import logging
import sys
from datetime import datetime
from typing import Optional


class StructuredFormatter(logging.Formatter):
    """JSON 结构化日志格式化器"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id

        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(
    level: str = "INFO",
    structured: bool = False,
) -> None:
    """
    配置应用级日志

    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        structured: 是否使用 JSON 结构化格式
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 清除已有的处理器
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    if structured:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))

    root_logger.addHandler(handler)

    # 降低第三方库的日志级别
    for name in ("uvicorn.access", "sqlalchemy.engine", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    获取命名日志器

    Args:
        name: 日志器名称

    Returns:
        配置好的 Logger 实例
    """
    return logging.getLogger(name)
