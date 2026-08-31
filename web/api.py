"""
web/api.py — FastAPI-бэкенд поверх ServerOrchestrator («вязка» бота с сайтом).

Один процесс: FastAPI + оркестратор в одном event loop. Общий AppState → REST + WebSocket.

ВНИМАНИЕ: при старте включается автономный режим — закупка, продажи и сканер
запускаются САМИ и торгуют реальными деньгами. Это осознанное поведение сервера
(бот работает 24/7). Отключается через WEB_AUTOSTART=0.

Запуск (по умолчанию слушает только 127.0.0.1, наружу — через nginx с TLS):
    uvicorn web.api:app --host 127.0.0.1 --port 8000
    (или python -m web.api)

Авторизация — сессии с истечением:
  1. POST /api/login  {"password": "..."} → {"token": "...", "expires_in": 43200}
  2. Дальше заголовок `Authorization: Bearer <token>` на все /api/* и /api/ws-ticket.
  3. Для WebSocket: POST /api/ws-ticket → одноразовый тикет на 30 с → /ws?ticket=...

Переменные окружения:
  WEB_API_PASSWORD_HASH — ОБЯЗАТЕЛЬНА. Хеш пароля, `python -m web.hashpw`.
                          Без неё процесс не стартует (пароля по умолчанию нет).
  WEB_SESSION_TTL       — время жизни сессии в секундах (по умолчанию 12 ч).
  WEB_BIND_PUBLIC=1     — слушать 0.0.0.0 вместо 127.0.0.1 (не рекомендуется).
  WEB_TRUST_PROXY=1     — доверять X-Forwarded-For (включать за nginx из deploy/).
  WEB_CORS_ORIGINS      — список origin через запятую.
  WEB_ENABLE_DOCS=1     — открыть /docs и /openapi.json (по умолчанию закрыты).
  WEB_AUTOSTART=0       — не запускать торговлю автоматически при старте.
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import (
    Depends, FastAPI, Header, HTTPException, Query, Request,
    WebSocket, WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.logger import get_logger  # noqa: E402
from server_runner import ServerOrchestrator  # noqa: E402
from web.auth import (  # noqa: E402
    api_limiter, bearer_token, client_key, load_password_hash,
    login_limiter, sessions, tickets, verify_password,
)

logger = get_logger("web.api")

# --- Windows: политика event loop -------------------------------------------
# ВАЖНО: делаем это на уровне модуля, а не только в __main__. При запуске через
# `python -m uvicorn web.api:app` блок __main__ не выполняется, остаётся Proactor,
# и при обрыве соединения клиентом asyncio засыпает лог сотнями
# "socket.send() raised exception". Selector-цикл этой проблемы не имеет.
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass


class _DropDeadSocketNoise(logging.Filter):
    """Глушит безобидный шум asyncio при обрыве соединения клиентом."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "socket.send() raised exception" not in msg


logging.getLogger("asyncio").addFilter(_DropDeadSocketNoise())

# --- Авторизация -----------------------------------------------------------
# Пароля по умолчанию НЕТ: без WEB_API_PASSWORD_HASH процесс не поднимется.
# Раньше здесь лежал захардкоженный токен "professor" — кто угодно, увидев
# исходник, получал полный контроль над торговлей на любом инстансе.
PASSWORD_HASH = load_password_hash()

MAX_BODY_BYTES = 256 * 1024
MAX_COMMAND_LENGTH = 512

# --- Единый буфер логов для веб-экрана «Логи» ------------------------------
LOG_BUFFER: deque = deque(maxlen=3000)


class WebLogHandler(logging.Handler):
    """Складывает записи логирования бота в LOG_BUFFER и пушит в WebSocket.

    ВАЖНО: исключаем uvicorn/watchfiles — иначе access-лог от GET /api/logs
    порождает новую запись → WS «logs» → фронт снова тянет /api/logs → шторм.
    WS-уведомления троттлятся (не чаще ~раз в секунду).
    """

    _NOISY = ("uvicorn", "watchfiles", "websockets")
    _last_notify = 0.0

    def emit(self, record: logging.LogRecord):
        try:
            if record.name.startswith(self._NOISY):
                return
            ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
            line = f"{ts} [{record.levelname}] {record.name}: {record.getMessage()}"
            LOG_BUFFER.append(line)
            now = time.monotonic()
            if ctx.ws_manager and (now - WebLogHandler._last_notify) > 1.0:
                WebLogHandler._last_notify = now
                ctx.ws_manager.notify("logs")
        except Exception:
            pass


def require_auth(authorization: Optional[str] = Header(None)) -> str:
    """Пускает только по живому токену сессии. Возвращает сам токен (для logout)."""
    token = bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    if not sessions.validate(token):
        # Один и тот же ответ на «протух» и «неверный» — не подсказываем атакующему.
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return token


# --- Оркестратор (без авто-старта подсистем) -------------------------------
def _default_args():
    return argparse.Namespace(
        once=False, dry_run=False, no_buy=True, no_sell=True, no_scan=True,
        cycle_min=0, scan_min=0, heartbeat_hours=12,
    )


class AppCtx:
    orch: Optional[ServerOrchestrator] = None
    ready: bool = False
    ws_manager = None


ctx = AppCtx()


# --- WebSocket: мост AppState → клиенты ------------------------------------
class WSManager:
    """Пушит изменения AppState всем подключённым клиентам (thread-safe из потока сканера)."""

    KEYS = ["logs", "stats", "accounts", "active_orders", "bot_state", "scanner_state"]

    def __init__(self, state, loop):
        self.state = state
        self.loop = loop
        self.clients: set[asyncio.Queue] = set()
        for key in self.KEYS:
            state.subscribe(key, self._make_cb(key))

    def _make_cb(self, key):
        def _cb():
            self.notify(key)
        return _cb

    def notify(self, key):
        """Broadcast изменения ключа всем клиентам (потокобезопасно)."""
        try:
            self.loop.call_soon_threadsafe(self._broadcast, key)
        except RuntimeError:
            pass

    def _broadcast(self, key):
        for q in list(self.clients):
            try:
                q.put_nowait({"type": key})
            except Exception:
                pass

    async def connect(self, ws: WebSocket) -> asyncio.Queue:
        await ws.accept()
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.clients.add(q)
        return q

    def disconnect(self, q: asyncio.Queue):
        self.clients.discard(q)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Токен НЕ логируем: этот же лог отдаётся по /api/logs и уходит в journald.
    logger.info("Web API старт. Вход по паролю (POST /api/login), сессия %d ч.",
                sessions.ttl // 3600)
    orch = ServerOrchestrator(_default_args())
    ctx.orch = orch
    ctx.ws_manager = WSManager(orch.state, asyncio.get_running_loop())

    # Перехват ВСЕХ логов (включая Steam Guard) в веб-экран «Логи»
    from src.logger import add_global_handler
    add_global_handler(WebLogHandler())

    async def _prepare():
        try:
            await orch.prepare()
            ctx.ready = True
            logger.info("Аккаунты залогинены, данные загружены — API готов")

            # Автономный режим: продажи + buy-цикл + сканер стартуют сами,
            # watchdog поднимает упавшее и шлёт уведомления в Telegram.
            # Отключается через WEB_AUTOSTART=0.
            if os.environ.get("WEB_AUTOSTART", "1") != "0":
                await orch.start_autonomous()
        except Exception as e:
            logger.error(f"prepare() failed: {e}")
            try:
                await orch._notify(f"❌ <b>Ошибка запуска сервера</b>\n{e}")
            except Exception:
                pass

    async def _sweep_limiters():
        """Чистка корзин rate-limiter'а.

        Словарь ключуется по IP, поэтому без уборки поток запросов с разных
        адресов медленно съедал бы память процесса.
        """
        while True:
            await asyncio.sleep(300)
            login_limiter.sweep()
            api_limiter.sweep()

    task = asyncio.create_task(_prepare())
    sweeper = asyncio.create_task(_sweep_limiters())
    try:
        yield
    finally:
        sweeper.cancel()
        task.cancel()
        try:
            await orch.stop_buy_loop()
        except Exception:
            pass
        try:
            await orch.stop_sales()
        except Exception:
            pass
        try:
            orch.stop_scanner()
        except Exception:
            pass
        await orch.close_clients()


# /docs, /redoc и /openapi.json закрыты: они бесплатно отдают атакующему полную
# карту роутов, включая те, что тратят деньги. Открыть — WEB_ENABLE_DOCS=1.
_DOCS_ON = os.environ.get("WEB_ENABLE_DOCS") == "1"

app = FastAPI(
    title="TM Steam Bot API",
    version="1.0",
    lifespan=lifespan,
    docs_url="/docs" if _DOCS_ON else None,
    redoc_url="/redoc" if _DOCS_ON else None,
    openapi_url="/openapi.json" if _DOCS_ON else None,
)


def _cors_origins() -> list[str]:
    raw = os.environ.get(
        "WEB_CORS_ORIGINS",
        "http://localhost:3002,http://localhost:3001,http://localhost:3000",
    )
    # .strip() обязателен: "http://a, http://b" иначе давал origin " http://b",
    # который не совпадёт ни с чем и молча ломал вход с этого адреса.
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if "*" in origins:
        raise SystemExit(
            "[БЕЗОПАСНОСТЬ] WEB_CORS_ORIGINS='*' недопустим: любой сайт сможет "
            "дёргать API из браузера жертвы. Перечислите origin'ы явно."
        )
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    # Авторизация у нас по заголовку Bearer, а не по cookie, поэтому credentials
    # не нужны — а именно этот флаг превращает ошибку в конфиге в полноценное
    # межсайтовое чтение данных.
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """Лимит размера тела, общий rate limit и security-заголовки."""
    # 1. Размер тела: без этого POST /api/config буферизует в память что угодно.
    if request.method in ("POST", "PUT", "PATCH"):
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)

    # 2. Общий потолок запросов (логин лимитируется отдельно и жёстче).
    path = request.url.path
    if path.startswith("/api/") and path != "/api/login":
        if not api_limiter.allow(client_key(request)):
            return JSONResponse(
                {"detail": "Too many requests"},
                status_code=429,
                headers={"Retry-After": str(api_limiter.retry_after(client_key(request)))},
            )

    response = await call_next(request)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if path.startswith("/api/"):
        # Балансы, ордера и логи не должны оседать в кешах и history.
        response.headers["Cache-Control"] = "no-store"
    return response


# --- Схемы -----------------------------------------------------------------
class LoginReq(BaseModel):
    password: str = Field(min_length=1, max_length=256)


# Ключи, которые НИКОГДА не принимаются от клиента.
# Пути — потому что `proxy_file`/`bottm_db_path` читаются как файлы
# (flet_gui/services/scanner_service.py), и запись туда произвольного пути
# превращает настройки в примитив чтения файлов.
# Секреты — потому что их незачем править из браузера.
CONFIG_FORBIDDEN_KEYS = frozenset({
    "proxy_file", "bottm_db_path", "db_path", "log_file",
    "steam_api_key", "csgotm_api_key", "notification_webhook",
})


class ConfigValues(BaseModel):
    """Белый список настроек, которые можно менять через API.

    Раньше здесь был голый `dict`: любой запрос клал в bot_config.json что
    угодно — торговлю в убыток, произвольные пути к файлам — и `save_config`
    перезаписывал файл ЦЕЛИКОМ, молча теряя все неперечисленные ключи.

    `extra="ignore"` намеренно: экран настроек грузит весь конфиг через
    GET /api/config и отправляет его обратно целиком. Неизвестные и запрещённые
    ключи просто отбрасываются, а не роняют сохранение в 422.

    Границы профита допускают отрицательные значения: в рабочем конфиге сейчас
    min_profit_pct = -5.5, это осознанная настройка, а не ошибка. Но -100%
    (слить баланс) уже за пределами.
    """

    model_config = {"extra": "ignore"}

    # Профит (может быть отрицательным — см. выше)
    min_profit_pct: Optional[float] = Field(default=None, ge=-50, le=1000)
    min_profit_percent: Optional[float] = Field(default=None, ge=-50, le=1000)
    scanner_min_profit: Optional[float] = Field(default=None, ge=-50, le=1000)
    check_orders_min_profit: Optional[float] = Field(default=None, ge=-50, le=1000)

    # Ценовые лимиты
    trade_min_price: Optional[float] = Field(default=None, ge=0, le=10_000_000)
    trade_max_price: Optional[float] = Field(default=None, ge=0, le=10_000_000)
    scanner_min_price: Optional[float] = Field(default=None, ge=0, le=10_000_000)
    scanner_max_price: Optional[float] = Field(default=None, ge=0, le=10_000_000)
    max_price_rub: Optional[float] = Field(default=None, ge=0, le=10_000_000)
    csgotm_min_balance: Optional[float] = Field(default=None, ge=0, le=10_000_000)
    csgo_commission: Optional[float] = Field(default=None, ge=0, le=100)
    price_check_threshold_percent: Optional[float] = Field(default=None, ge=0, le=1000)

    # Объёмы и интервалы
    cycle_interval_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    scan_interval_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    auto_scan_interval: Optional[int] = Field(default=None, ge=1, le=1440)
    auto_rescan_interval: Optional[int] = Field(default=None, ge=1, le=1440)
    proxy_rotation_interval_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    max_items_per_cycle: Optional[int] = Field(default=None, ge=1, le=10_000)
    scan_max_items: Optional[int] = Field(default=None, ge=1, le=10_000)
    scanner_max_items: Optional[int] = Field(default=None, ge=1, le=10_000)
    auto_scan_new_items: Optional[int] = Field(default=None, ge=1, le=10_000)
    max_daily_trades: Optional[int] = Field(default=None, ge=0, le=100_000)
    max_hold_time_hours: Optional[int] = Field(default=None, ge=1, le=8760)
    trade_hold_days: Optional[int] = Field(default=None, ge=0, le=365)
    min_sales_7d: Optional[int] = Field(default=None, ge=0, le=1_000_000)

    # Сканер и прокси
    scanner_delay: Optional[float] = Field(default=None, ge=0, le=600)
    scanner_workers: Optional[int] = Field(default=None, ge=1, le=64)
    requests_per_proxy: Optional[int] = Field(default=None, ge=1, le=10_000)
    proxy_max_requests: Optional[int] = Field(default=None, ge=1, le=10_000)
    proxy_cooldown: Optional[int] = Field(default=None, ge=0, le=86_400)
    proxy_blacklist_duration: Optional[int] = Field(default=None, ge=0, le=86_400)
    order_rate_limit_cooldown: Optional[int] = Field(default=None, ge=0, le=86_400)

    # Флаги
    auto_refresh: Optional[bool] = None
    debug_mode: Optional[bool] = None
    auto_scan_enabled: Optional[bool] = None
    auto_update_prices: Optional[bool] = None
    price_update_to_top1: Optional[bool] = None
    use_proxy: Optional[bool] = None
    proxy_rotation_enabled: Optional[bool] = None
    enable_notifications: Optional[bool] = None
    log_to_file: Optional[bool] = None


class ConfigUpdate(BaseModel):
    # На верхнем уровне оставляем dict: значения чистим до валидации, потому что
    # экран настроек шлёт пустые строки для незаполненных полей.
    config: dict


class CommandReq(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_COMMAND_LENGTH)


# --- Публичные -------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "ready": ctx.ready}


@app.post("/api/login")
def login(req: LoginReq, request: Request):
    """Пароль → сессионный токен с TTL.

    Лимит 5 попыток / 15 мин на IP: перебор пароля становится бессмысленным.
    """
    key = client_key(request)
    if not login_limiter.allow(key):
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts",
            headers={"Retry-After": str(login_limiter.retry_after(key))},
        )
    if not verify_password(req.password, PASSWORD_HASH):
        logger.warning("Неудачная попытка входа в панель с %s", key)
        raise HTTPException(status_code=401, detail="Wrong password")

    login_limiter.reset(key)  # успешный вход снимает счётчик
    token, ttl = sessions.create()
    logger.info("Успешный вход в панель с %s", key)
    return {"token": token, "expires_in": ttl}


# --- Сессия (auth) ---------------------------------------------------------
@app.post("/api/logout")
def logout(token: str = Depends(require_auth)):
    sessions.revoke(token)
    return {"ok": True}


@app.post("/api/ws-ticket")
def ws_ticket(_: str = Depends(require_auth)):
    """Одноразовый тикет на 30 с для WebSocket.

    Долгоживущий токен в query-строке оседал бы в access-логах nginx, в истории
    браузера и в Referer. Тикет гасится при первом использовании.
    """
    ticket, ttl = tickets.issue()
    return {"ticket": ticket, "expires_in": ttl}


# --- Чтение (auth) ---------------------------------------------------------
def _state():
    if not ctx.orch:
        raise HTTPException(status_code=503, detail="Orchestrator not ready")
    return ctx.orch.state


@app.get("/api/status")
def status(_=Depends(require_auth)):
    if not ctx.orch:
        raise HTTPException(status_code=503, detail="Orchestrator not ready")
    return {"ready": ctx.ready, **ctx.orch.status_snapshot(), "stats": _state().stats}


@app.get("/api/accounts")
def accounts(_=Depends(require_auth)):
    return [
        {
            "name": a.name, "enabled": a.enabled, "logged_in": a.logged_in,
            "currency": a.currency, "steam_balance": a.steam_balance,
            "csgotm_balance": a.csgotm_balance, "csgotm_settlement": a.csgotm_settlement,
        }
        for a in _state().accounts
    ]


@app.get("/api/orders")
def orders(_=Depends(require_auth)):
    return _state().active_orders


@app.get("/api/inventory")
def inventory(_=Depends(require_auth)):
    return _state().items_on_hold


@app.get("/api/profitable")
def profitable(_=Depends(require_auth)):
    return _state().profitable_items


@app.get("/api/sales")
def sales(_=Depends(require_auth)):
    return _state().recent_sales


@app.get("/api/history")
def history(_=Depends(require_auth)):
    return _state().history


@app.get("/api/logs")
def logs(limit: int = Query(400, ge=1, le=3000), _=Depends(require_auth)):
    # Единый буфер: все python-логи (steam_client, trading_bot, csgotm, guard…) + state.add_log
    # Границы у limit обязательны: без ge=1 значение 0 или -1 инвертировало срез
    # и отдавало весь буфер целиком вместо запрошенного хвоста.
    return list(LOG_BUFFER)[-limit:]


@app.get("/api/config")
def get_config(_=Depends(require_auth)):
    # Ключи с секретами наружу не отдаём: панель их всё равно не редактирует,
    # а в ответе они утекли бы в кеш браузера и в devtools.
    return {k: v for k, v in _state().config.items() if k not in CONFIG_FORBIDDEN_KEYS}


# --- Управление (auth) -----------------------------------------------------
@app.post("/api/config")
def set_config(body: ConfigUpdate, _=Depends(require_auth)):
    """Обновление настроек: только белый список, только слиянием.

    Раньше тело запроса ложилось в bot_config.json как есть — вместе с путями к
    файлам и с потерей всех ключей, которых не было в запросе.
    """
    # Пустые строки от незаполненных полей формы — это «не менять», а не 422.
    incoming = {
        k: v for k, v in body.config.items()
        if k not in CONFIG_FORBIDDEN_KEYS and v != ""
    }
    allowed = ConfigValues.model_validate(incoming).model_dump(exclude_none=True)

    merged = dict(_state().config)
    merged.update(allowed)

    ctx.orch.config_service.save_config(merged)

    ok, problems = ctx.orch.config_service.validate_config()
    if not ok:
        logger.warning("Конфиг сохранён, но не прошёл валидацию: %s", "; ".join(problems))
    return {"ok": True, "applied": sorted(allowed), "warnings": [] if ok else problems}


@app.post("/api/bot/start")
async def bot_start(_=Depends(require_auth)):
    ok = await ctx.orch.start_buy_loop()
    return {"ok": ok}


@app.post("/api/bot/stop")
async def bot_stop(_=Depends(require_auth)):
    await ctx.orch.stop_buy_loop()
    return {"ok": True}


@app.post("/api/sales/start")
async def sales_start(_=Depends(require_auth)):
    ok = await ctx.orch.start_sales()
    return {"ok": ok}


@app.post("/api/sales/stop")
async def sales_stop(_=Depends(require_auth)):
    await ctx.orch.stop_sales()
    return {"ok": True}


@app.post("/api/scanner/start")
def scanner_start(_=Depends(require_auth)):
    return {"ok": ctx.orch.start_scanner()}


@app.post("/api/scanner/stop")
def scanner_stop(_=Depends(require_auth)):
    ctx.orch.stop_scanner()
    return {"ok": True}


@app.post("/api/scan/run")
async def scan_run(max_items: int = Query(10, ge=1, le=200), _=Depends(require_auth)):
    # Потолок в 200: каждый предмет — живой запрос к Steam/CSGO.TM через прокси,
    # без границы max_items=10000000 клал бы и бота, и лимиты аккаунтов.
    items = await ctx.orch.scanner_service.run_single_scan_async(max_items=max_items)
    return {"ok": True, "found": len(items)}


@app.post("/api/command")
async def command(body: CommandReq, _=Depends(require_auth)):
    """Команды из веб-экрана «Логи»: login / scan [N] / balances / guard <код>."""
    text = (body.text or "").strip()
    if not text:
        return {"ok": False, "reply": "пустая команда"}
    parts = text.split()
    cmd = parts[0].lower()
    # Эхо команды в лог — с вырезанным аргументом `guard`, иначе одноразовый
    # Steam Guard попадал бы в /api/logs целиком ещё до обработки.
    logger.info("[CMD] %s", cmd if cmd == "guard" else text)
    orch = ctx.orch

    if cmd in ("login", "relogin"):
        async def _relogin():
            accs = await orch.login_all()
            if accs:
                await orch.refresh_balances(accs)
        asyncio.create_task(_relogin())
        return {"ok": True, "reply": "Повторный логин запущен — смотри логи"}

    if cmd == "scan":
        n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 15
        asyncio.create_task(orch.scanner_service.run_single_scan_async(max_items=n))
        return {"ok": True, "reply": f"Скан {n} предметов запущен"}

    if cmd in ("balances", "balance"):
        asyncio.create_task(orch.refresh_balances(orch._accounts))
        return {"ok": True, "reply": "Обновление балансов запущено"}

    if cmd == "guard":
        code = parts[1] if len(parts) > 1 else ""
        # Аккаунты с identity_secret подтверждают автоматически; ручной код —
        # для аккаунтов без maFile (если появится ожидающий запрос).
        waiter = getattr(orch, "_guard_waiter", None)
        if waiter and code:
            try:
                waiter(code)
                # Сам код НЕ логируем: этот лог отдаётся по GET /api/logs и
                # уходит в journald — одноразовый Steam Guard оседал бы в обоих.
                logger.info(f"[CMD] Guard-код принят (длина {len(code)})")
                return {"ok": True, "reply": "Guard-код передан"}
            except Exception as e:
                return {"ok": False, "reply": f"Ошибка Guard: {e}"}
        logger.warning("[CMD] Нет ожидающего запроса Steam Guard (аккаунты на maFile подтверждают автоматически)")
        return {"ok": True, "reply": "Нет ожидающего запроса Guard"}

    logger.warning(f"[CMD] Неизвестная команда: {cmd}. Доступно: login, scan [N], balances, guard <код>")
    return {"ok": True, "reply": f"Неизвестная команда: {cmd}"}


# --- WebSocket live-state --------------------------------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, ticket: str = ""):
    """Live-состояние. Пускает только по одноразовому тикету из /api/ws-ticket.

    Раньше сюда передавался постоянный токен доступа в query-строке — он оседал
    в access-логах прокси и в истории браузера. Тикет живёт 30 секунд и гасится
    при первом использовании, поэтому его утечка из логов бесполезна.
    """
    if not tickets.consume(ticket):
        await ws.close(code=1008)
        return
    q = await ctx.ws_manager.connect(ws)
    try:
        # начальный снапшот
        await ws.send_json({"type": "status", "data": ctx.orch.status_snapshot()})
        while True:
            msg = await q.get()
            await ws.send_json(msg)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"ws error: {e}")
    finally:
        ctx.ws_manager.disconnect(q)


if __name__ == "__main__":
    import uvicorn
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # По умолчанию слушаем ТОЛЬКО localhost. Наружу — через nginx с TLS
    # (deploy/nginx-tm-steambot.conf). Публичный бинд — осознанный opt-in.
    if os.environ.get("WEB_BIND_PUBLIC") == "1":
        host = "0.0.0.0"
        logger.warning(
            "WEB_BIND_PUBLIC=1 — API слушает все интерфейсы БЕЗ TLS. "
            "Пароли и данные пойдут открытым текстом. Используйте nginx из deploy/."
        )
    else:
        host = "127.0.0.1"

    uvicorn.run(
        "web.api:app",
        host=host,
        port=int(os.environ.get("WEB_PORT", 8000)),
        reload=False,
        access_log=False,  # без per-request access-лога (шум + был цикл с /api/logs)
        server_header=False,  # не выдавать версию uvicorn
        proxy_headers=os.environ.get("WEB_TRUST_PROXY") == "1",
        forwarded_allow_ips="127.0.0.1",
    )
