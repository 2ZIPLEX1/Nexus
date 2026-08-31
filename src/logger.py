"""
Logging configuration for Steam Trading Bot.

Здесь же — централизованная РЕДАКЦИЯ СЕКРЕТОВ в логах (SecretRedactingFilter).
Это важно: логи бота уходят сразу в три места — файл logs/bot.log, journald и
веб-буфер, который отдаётся наружу по HTTP (GET /api/logs). Утечка в лог = утечка
в веб-панель. До появления фильтра в logs/bot.log лежало 155 строк с паролями
SOCKS5-прокси открытым текстом.

Фильтр — страховка «на всех», а не замена аккуратному логированию: маскировать
секрет в месте вызова всё равно правильнее.
"""

import logging
import re
import sys
from pathlib import Path
from typing import Optional

import colorlog

# На Windows консоль часто в cp1251 — эмодзи в логах (💰📊 и т.п.) роняют StreamHandler
# с UnicodeEncodeError. Переводим stdout/stderr в UTF-8 один раз при импорте логгера,
# ДО создания любых обработчиков. Идемпотентно и безопасно на всех платформах.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


# --- Редакция секретов ------------------------------------------------------
_MASK = "***"

# Порядок важен: сначала узкие правила (URL с кредами), потом общие (key=value).
_REDACTIONS: list[tuple[re.Pattern, str]] = [
    # socks5://user:pass@host:port и http(s)://user:pass@host — пароли прокси.
    (re.compile(r"\b(socks5h?|socks4a?|https?)://[^\s:/@]+:[^\s@]+@", re.I),
     r"\1://" + _MASK + ":" + _MASK + "@"),

    # otpauth://totp/...?secret=BASE32 — семя Steam Guard целиком.
    (re.compile(r"(otpauth://[^\s?]*\?[^\s]*secret=)[A-Za-z0-9=]+", re.I),
     r"\1" + _MASK),

    # key=value / "key": "value" для любого чувствительного имени.
    (re.compile(
        r"(?i)\b(api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|"
        r"shared[_-]?secret|identity[_-]?secret|revocation[_-]?code|"
        r"password|passwd|pwd|secret|token|steamLoginSecure|sessionid|"
        r"steamRefresh_steam|WEB_API_PASSWORD_HASH)"
        r"(\"?\s*[:=]\s*\"?)"
        r"([^\s,;&\"'}\])]{4,})"),
     r"\1\2" + _MASK),

    # Authorization: Bearer <...> / Basic <...>
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/=]{8,}"),
     r"\1 " + _MASK),

    # Одиночные длинные hex-строки — это Steam API key (32 hex) и подобное.
    (re.compile(r"\b[0-9A-Fa-f]{32,}\b"), _MASK),
]


def redact_text(text: str) -> str:
    """Маскирует секреты в произвольной строке.

    Пригодно и вне логирования — например, для текста исключения от
    aiohttp-socks, который часто содержит полный URL прокси с паролем.
    """
    if not text:
        return text
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class SecretRedactingFilter(logging.Filter):
    """Вычищает секреты из записи ДО того, как она уйдёт в любой обработчик.

    Навешивается на каждый обработчик (а не на root): get_logger выставляет
    logger.propagate = False, поэтому до root записи попросту не доходят.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            original = record.getMessage()
            cleaned = redact_text(original)
            if cleaned != original:
                # Аргументы уже подставлены в cleaned — обнуляем, иначе logging
                # попытается форматировать строку повторно.
                record.msg = cleaned
                record.args = ()
            # Трейсбеки тоже носят секреты (например, repr настроек в кадре).
            if record.exc_text:
                record.exc_text = redact_text(record.exc_text)
        except Exception:
            # Логирование не должно падать из-за фильтра.
            pass
        return True


_REDACTING_FILTER = SecretRedactingFilter()


def _protect(handler: logging.Handler) -> logging.Handler:
    """Вешает фильтр редакции на обработчик (идемпотентно)."""
    if _REDACTING_FILTER not in handler.filters:
        handler.addFilter(_REDACTING_FILTER)
    return handler


# Глобальные доп. обработчики (например, веб-буфер логов). Добавляются ко ВСЕМ
# логгерам — уже созданным и будущим — чтобы весь вывод (в т.ч. Steam Guard) уходил
# не только в консоль, но и в подписанные приёмники (веб-экран Логи).
_GLOBAL_HANDLERS: list[logging.Handler] = []


def add_global_handler(handler: logging.Handler) -> None:
    """Добавить обработчик ко всем существующим и будущим логгерам."""
    if handler in _GLOBAL_HANDLERS:
        return
    _protect(handler)  # веб-буфер отдаётся наружу — редакция обязательна
    _GLOBAL_HANDLERS.append(handler)
    # ретроактивно — на root и все уже созданные логгеры
    logging.getLogger().addHandler(handler)
    for name in list(logging.Logger.manager.loggerDict.keys()):
        lg = logging.getLogger(name)
        if isinstance(lg, logging.Logger) and handler not in lg.handlers:
            lg.addHandler(handler)


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

    # Disable propagation to root logger to avoid duplicate logs
    logger.propagate = False

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
    logger.addHandler(_protect(console_handler))

    # Глобальные обработчики (веб-буфер и т.п.)
    for h in _GLOBAL_HANDLERS:
        if h not in logger.handlers:
            logger.addHandler(h)

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
        logger.addHandler(_protect(file_handler))

    return logger


def get_trade_logger() -> logging.Logger:
    """Get a dedicated logger for trade operations."""
    return get_logger("trades", Path("./logs/trades.log"))


def get_error_logger() -> logging.Logger:
    """Get a dedicated logger for errors."""
    return get_logger("errors", Path("./logs/errors.log"))
