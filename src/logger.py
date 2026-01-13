"""
Logging configuration for Steam Trading Bot.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

import colorlog


def get_logger(name: str, log_file: Optional[Path] = None) -> logging.Logger:
    """
    Get a configured logger instance.

    Args:
        name: Logger name (usually __name__)
        log_file: Optional path to log file

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    # Try to get log level from settings, default to INFO
    try:
        from config import settings
        log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
        log_file = log_file or settings.log_file
    except Exception:
        log_level = logging.INFO
        log_file = log_file or Path("./logs/bot.log")

    logger.setLevel(log_level)

    # Console handler with colors
    console_handler = colorlog.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_format = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s]%(reset)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(log_level)
        file_format = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    return logger


def get_trade_logger() -> logging.Logger:
    """Get a dedicated logger for trade operations."""
    return get_logger("trades", Path("./logs/trades.log"))


def get_error_logger() -> logging.Logger:
    """Get a dedicated logger for errors."""
    return get_logger("errors", Path("./logs/errors.log"))
