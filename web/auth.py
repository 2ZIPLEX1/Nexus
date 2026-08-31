"""
web/auth.py — аутентификация веб-панели: хеш пароля, сессии, WS-тикеты, rate limit.

Почему так, а не иначе:

* **Никаких новых зависимостей.** Хеширование на `hashlib.scrypt` из стандартной
  библиотеки. Бот управляет реальными деньгами, и каждый лишний пакет в
  requirements — это ещё один вектор supply-chain. scrypt memory-hard, для
  защиты пароля панели этого более чем достаточно.

* **Fail-closed.** Раньше токен доступа имел значение по умолчанию (`professor`),
  захардкоженное в исходнике. Теперь без `WEB_API_PASSWORD_HASH` процесс просто
  не поднимается: лучше упасть при старте, чем молча слушать порт с угадываемым
  паролем.

* **Сессии, а не вечный токен.** Пароль обменивается на случайный токен с TTL.
  Утёкший токен протухает сам и отзывается через /api/logout, тогда как утёкший
  статический токен жил до перезапуска процесса.

* **Тикеты для WebSocket.** Браузерный WebSocket не умеет слать заголовки, а
  токен в query-строке оседает в access-логах nginx, в истории браузера и в
  Referer. Поэтому /ws принимает не сессию, а одноразовый тикет на 30 секунд.

Хранилище сессий — в памяти процесса. Рестарт разлогинивает всех; для одного
инстанса панели это приемлемо и заметно безопаснее файла на диске.

Настройка::

    python -m web.hashpw            # спросит пароль, напечатает строку хеша
    export WEB_API_PASSWORD_HASH='scrypt$32768$8$1$...$...'
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple

# --- Параметры KDF ----------------------------------------------------------
# n=2**15, r=8, p=1 → ~33 МБ памяти и ~100 мс на проверку. Для формы логина это
# незаметно, а перебор делает дорогим. maxmem задаём явно: дефолт OpenSSL (32 МБ)
# для этих параметров слишком мал и scrypt упадёт с ValueError.
_SCRYPT_N = 2 ** 15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_MAXMEM = 128 * _SCRYPT_N * _SCRYPT_R * 2  # с двукратным запасом

SESSION_TTL_SECONDS = int(os.environ.get("WEB_SESSION_TTL", 12 * 3600))
TICKET_TTL_SECONDS = 30


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# --- Пароль -----------------------------------------------------------------
def hash_password(password: str) -> str:
    """Возвращает строку вида `scrypt$n$r$p$salt$hash` для WEB_API_PASSWORD_HASH."""
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN, maxmem=_SCRYPT_MAXMEM,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64e(salt)}${_b64e(dk)}"


def verify_password(password: str, stored: str) -> bool:
    """Проверка пароля против сохранённого хеша. Никогда не бросает исключений.

    Важно: пароль кодируется в bytes до сравнения. Прежний код звал
    `secrets.compare_digest` на двух `str`, и любой не-ASCII пароль (а именно
    такой рекомендовал README) валил эндпоинт в 500 через TypeError вместо 401.
    """
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt = _b64d(salt_b64)
        expected = _b64d(hash_b64)
        dk = hashlib.scrypt(
            password.encode("utf-8"), salt=salt,
            n=int(n), r=int(r), p=int(p),
            dklen=len(expected), maxmem=_SCRYPT_MAXMEM,
        )
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def load_password_hash() -> str:
    """Читает WEB_API_PASSWORD_HASH или падает с инструкцией (fail-closed)."""
    value = (os.environ.get("WEB_API_PASSWORD_HASH") or "").strip()
    if not value:
        raise SystemExit(
            "\n[БЕЗОПАСНОСТЬ] Не задан WEB_API_PASSWORD_HASH — запуск отменён.\n"
            "\n"
            "Панель управляет реальными деньгами, поэтому пароля по умолчанию у неё нет.\n"
            "Сгенерируйте хеш и положите его в окружение:\n"
            "\n"
            "    python -m web.hashpw\n"
            "    export WEB_API_PASSWORD_HASH='scrypt$...'\n"
            "\n"
            "На сервере — через EnvironmentFile=/etc/tm-steambot/web.env (chmod 600),\n"
            "см. deploy/tm-steambot-web.service.\n"
        )
    if not value.startswith("scrypt$"):
        raise SystemExit(
            "[БЕЗОПАСНОСТЬ] WEB_API_PASSWORD_HASH должен быть хешем вида 'scrypt$...', "
            "а не паролем открытым текстом. Сгенерируйте: python -m web.hashpw"
        )
    return value


# --- Сессии -----------------------------------------------------------------
class SessionStore:
    """Токены сессий с истечением. Потокобезопасно."""

    def __init__(self, ttl: int = SESSION_TTL_SECONDS):
        self.ttl = ttl
        self._sessions: Dict[str, float] = {}
        self._lock = threading.Lock()

    def create(self) -> Tuple[str, int]:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._prune_locked()
            self._sessions[token] = time.time() + self.ttl
        return token, self.ttl

    def validate(self, token: str) -> bool:
        if not token:
            return False
        now = time.time()
        with self._lock:
            # Перебор всех сессий со сравнением за постоянное время: словарный
            # доступ по секрету теоретически подвержен тайминг-атаке.
            for known, expires in list(self._sessions.items()):
                if hmac.compare_digest(known, token):
                    if expires < now:
                        self._sessions.pop(known, None)
                        return False
                    return True
        return False

    def revoke(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    def revoke_all(self) -> None:
        with self._lock:
            self._sessions.clear()

    def _prune_locked(self) -> None:
        now = time.time()
        for token, expires in list(self._sessions.items()):
            if expires < now:
                self._sessions.pop(token, None)

    @property
    def active_count(self) -> int:
        with self._lock:
            self._prune_locked()
            return len(self._sessions)


# --- Одноразовые тикеты для WebSocket ---------------------------------------
class TicketStore:
    """Короткоживущие одноразовые тикеты: секрет не попадает в долгие логи."""

    def __init__(self, ttl: int = TICKET_TTL_SECONDS):
        self.ttl = ttl
        self._tickets: Dict[str, float] = {}
        self._lock = threading.Lock()

    def issue(self) -> Tuple[str, int]:
        ticket = secrets.token_urlsafe(24)
        with self._lock:
            self._prune_locked()
            self._tickets[ticket] = time.time() + self.ttl
        return ticket, self.ttl

    def consume(self, ticket: str) -> bool:
        """Проверяет и сразу гасит тикет — повторное использование невозможно."""
        if not ticket:
            return False
        now = time.time()
        with self._lock:
            for known, expires in list(self._tickets.items()):
                if hmac.compare_digest(known, ticket):
                    self._tickets.pop(known, None)
                    return expires >= now
        return False

    def _prune_locked(self) -> None:
        now = time.time()
        for ticket, expires in list(self._tickets.items()):
            if expires < now:
                self._tickets.pop(ticket, None)


# --- Rate limiting ----------------------------------------------------------
class RateLimiter:
    """Скользящее окно per-key. Без внешних зависимостей (slowapi не нужен)."""

    def __init__(self, max_hits: int, window_seconds: int):
        self.max_hits = max_hits
        self.window = window_seconds
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_hits:
                return False
            bucket.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def retry_after(self, key: str) -> int:
        with self._lock:
            bucket = self._hits.get(key)
            if not bucket:
                return 0
            return max(1, int(self.window - (time.monotonic() - bucket[0])))

    def sweep(self) -> None:
        """Чистит пустые корзины, чтобы словарь не рос от разовых IP."""
        cutoff = time.monotonic() - self.window
        with self._lock:
            for key, bucket in list(self._hits.items()):
                while bucket and bucket[0] < cutoff:
                    bucket.popleft()
                if not bucket:
                    self._hits.pop(key, None)


def client_key(request) -> str:
    """IP клиента с учётом обратного прокси.

    X-Forwarded-For учитывается ТОЛЬКО если WEB_TRUST_PROXY=1. Иначе заголовок
    подделывается кем угодно и rate limit обходится одной строкой в запросе.
    За nginx из deploy/ переменную выставлять нужно.
    """
    if os.environ.get("WEB_TRUST_PROXY") == "1":
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return getattr(getattr(request, "client", None), "host", None) or "unknown"


# --- Общие экземпляры -------------------------------------------------------
sessions = SessionStore()
tickets = TicketStore()

# 5 попыток за 15 минут на IP: перебор пароля становится бессмысленным,
# а живой оператор с опечаткой не блокируется.
login_limiter = RateLimiter(max_hits=5, window_seconds=15 * 60)

# Общий потолок на API — предохранитель от потока запросов, а не основная
# защита (основная — логин-лимитер и nginx).
# Планка намеренно высокая: панель живёт на WebSocket-уведомлениях, каждое из
# которых заставляет открытый экран перезапросить свой REST-эндпоинт. При
# активном сканировании с несколькими вкладками легко набегает несколько
# запросов в секунду — лимит в 4/с блокировал бы обычную работу оператора.
api_limiter = RateLimiter(max_hits=1200, window_seconds=60)


def bearer_token(authorization: Optional[str]) -> str:
    """Достаёт токен из заголовка Authorization; "" если заголовка нет."""
    if not authorization:
        return ""
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1].strip()
