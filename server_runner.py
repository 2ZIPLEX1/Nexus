#!/usr/bin/env python3
"""
server_runner.py — Headless-оркестратор для работы бота 24/7 на сервере (без окна GUI).

Один event loop держит весь async-стек (это убирает баг «loop is not the running loop»,
который в GUI возникал из-за run_async_in_gui со своими отдельными циклами):
  • buy-цикл  — TradingBot.run_cycle() каждые N минут (Step 0..2: sync/создание/проверка);
  • продажи   — TmSalesService: ping-онлайн, выставление после холда, подтверждение трейдов
                через maFile, детект проданного, откат отменённых, репрайс до топ-1;
  • сканер    — AutoScanner в отдельном потоке (свои клиенты) каждые N минут;
  • балансы + уведомления в Telegram.

Переиспользует боевые сервисы из flet_gui/, только без UI.

Использование:
  python server_runner.py                       # 24/7: buy + sell + scan
  python server_runner.py --once                # один buy-цикл и выход
  python server_runner.py --dry-run             # НИЧЕГО не покупает/не продаёт: только проверка
                                                #   логина, API, балансов, sell-статуса (безопасно)
  python server_runner.py --no-sell --no-scan   # отключить подсистемы
  python server_runner.py --cycle-min 30 --scan-min 30
"""

import argparse
import asyncio
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

# --- UTF-8 вывод: чинит краш логов с эмодзи на Windows-консоли (cp1251) ---
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Пути: корень проекта на sys.path (flet_gui + src резолвятся отсюда)
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# DNS-совместимость (ThreadedResolver) — ДО создания любых aiohttp-сессий
from src.dns_compat import apply_dns_compat  # noqa: E402
apply_dns_compat()

from src.logger import get_logger  # noqa: E402
from src.trading_bot import TradingBot  # noqa: E402
from flet_gui.state.app_state import AppState  # noqa: E402
from flet_gui.services.config_service import ConfigService  # noqa: E402
from flet_gui.services.database_service import DatabaseService  # noqa: E402
from flet_gui.services.account_service import AccountService  # noqa: E402
from flet_gui.services.scanner_service import ScannerService  # noqa: E402
from flet_gui.services.auto_buy_service import AutoBuyService  # noqa: E402
from flet_gui.services.proxy_service import ProxyService  # noqa: E402
from flet_gui.services.tm_sales_service import TmSalesService  # noqa: E402

logger = get_logger("server_runner")


class ServerOrchestrator:
    """Собирает и гоняет весь стек в одном event loop."""

    WATCHDOG_INTERVAL_SEC = 300  # Как часто watchdog проверяет живость сервисов (5 мин)
    ORDER_RECHECK_INTERVAL_SEC = 6 * 3600  # Перепроверка профита активных ордеров (6 часов)

    def __init__(self, args):
        self.args = args
        self.state = AppState()
        self._stopping = False

        # Мост логов: всё, что сервисы пишут через state.add_log(), уходит в серверный лог.
        self._last_log_index = 0
        self.state.subscribe("logs", self._forward_logs)

        # Боевые сервисы (без UI)
        self.config_service = ConfigService(self.state)          # грузит bot_config.json → state.config
        self.db_service = DatabaseService(self.state)
        self.account_service = AccountService(self.state)         # грузит accounts.json → state.accounts
        self.proxy_service = ProxyService(self.state)
        self.auto_buy_service = AutoBuyService(self.state, self.account_service, self.proxy_service)
        self.scanner_service = ScannerService(self.state, self.auto_buy_service)

        # Telegram (опционально)
        self.telegram_bot = None
        try:
            from src.telegram_bot import TelegramNotifier
            tg = TelegramNotifier()
            self.telegram_bot = tg if tg.is_configured else None
            if self.telegram_bot:
                logger.info("Telegram notifier configured")
            else:
                logger.info("Telegram not configured (token/chat_id пустые) — уведомления off")
        except Exception as e:
            logger.warning(f"Telegram init failed: {e}")

        self.sales_service = TmSalesService(
            self.state, self.account_service, self.db_service, self.telegram_bot
        )

        # Обратная связь: без неё _handle_price_update_callback в боте видит _sales_service=None
        # и кнопки из уведомлений («Выставить топ-1» и пр.) отвечают «Сервис продаж не запущен».
        if self.telegram_bot:
            self.telegram_bot.set_sales_service(self.sales_service)

        self.bots: dict[str, TradingBot] = {}
        self._accounts: list = []

        # Heartbeat: периодическая сводка в Telegram (чтобы «поставил и забыл»)
        self.heartbeat_hours = args.heartbeat_hours
        self._last_heartbeat = 0.0

        # Управляемая buy-задача (для API-режима start/stop)
        self._buy_task = None
        self._buy_stop = None

        # Фоновая задача Telegram-polling (приём нажатий inline-кнопок)
        self._tg_task = None

        # Watchdog автономного режима (следит, что продажи/buy/сканер живы)
        self._watchdog_task = None

        # Периодическая перепроверка профита активных ордеров (раз в 6 часов)
        self._order_recheck_task = None

        # Аккаунты, о простое которых уже уведомили (чтобы не повторять каждые 5 мин)
        self._offline_notified: set = set()

        # Интервалы (минуты): CLI > config > дефолт 30
        cfg = self.state.config or {}
        self.cycle_min = args.cycle_min or int(cfg.get("cycle_interval_minutes", 30) or 30)
        self.scan_min = args.scan_min or int(cfg.get("scan_interval_minutes", cfg.get("auto_scan_interval", 30)) or 30)

    # ------------------------------------------------------------------ logs
    def _forward_logs(self):
        """Пробрасывает новые строки state.logs в python-логгер (файл/stdout)."""
        logs = self.state.logs
        new = logs[self._last_log_index:]
        self._last_log_index = len(logs)
        for line in new:
            logger.info(line)

    async def _notify(self, text: str):
        if self.telegram_bot:
            try:
                await self.telegram_bot.send_message(text)
            except Exception as e:
                logger.warning(f"Telegram send failed: {e}")

    def _wire_telegram_prompts(self, acc):
        """Подключить Telegram как источник Steam Guard кода и ручных подтверждений.

        Нужно для аккаунтов БЕЗ maFile (нет shared_secret/identity_secret): раньше они
        спрашивали код и подтверждение через консольный input(), что на сервере
        не работает — процесс просто вис. Теперь код приходит сообщением в чат,
        а подтверждение — нажатием кнопки.
        """
        client = getattr(acc, "steam_client", None)
        if not client or not self.telegram_bot:
            return

        try:
            async def _code_provider(account_name: str):
                return await self.telegram_bot.ask_steam_guard_code(account_name)

            client.set_code_provider(_code_provider)

            async def _confirm_callback(confirmation_id: int):
                await self.telegram_bot.ask_manual_confirmation(
                    acc.name,
                    action="Ордер выставлен — подтвердите его в Steam Mobile Guard, "
                           "затем нажмите кнопку ниже.",
                )

            client.set_confirmation_callback(_confirm_callback)
        except Exception as e:
            logger.debug(f"[{acc.name}] Не удалось подключить Telegram-подсказки: {e}")

    # --------------------------------------------------------------- login
    async def login_all(self) -> list:
        """Логинит все enabled-аккаунты в ТЕКУЩЕМ loop. Возвращает список Account'ов."""
        am = self.account_service.account_manager
        if not am:
            logger.error("AccountManager не инициализирован (accounts.json?)")
            return []

        enabled = am.get_enabled_accounts()
        logger.info(f"Логиним {len(enabled)} аккаунт(ов)...")

        async def _login(acc):
            try:
                acc.reinitialize_steam_client()  # привязать aiohttp-сессию к этому loop
                # ВАЖНО: провайдеры ставим ДО логина — Steam Guard код может
                # понадобиться прямо во время него (аккаунты без maFile).
                self._wire_telegram_prompts(acc)
                ok = await acc.login_async()
                # Повторно: set_confirmation_callback срабатывает только когда
                # внутренний aiosteampy-клиент уже создан (т.е. после логина).
                if ok:
                    self._wire_telegram_prompts(acc)
                return acc, ok
            except Exception as e:
                logger.error(f"[{acc.name}] login error: {e}")
                return acc, False

        results = await asyncio.gather(*[_login(a) for a in enabled])
        logged = [acc for acc, ok in results if ok]

        for acc, ok in results:
            for info in self.state.accounts:
                if info.name == acc.name:
                    info.logged_in = ok
                    break

        logger.info(f"Залогинено {len(logged)}/{len(enabled)}")
        self._accounts = logged

        # Уведомляем ТОЛЬКО о реально неудавшихся аккаунтах (ретраи уже отработали
        # внутри login_async) — чтобы не слать «фейковые» тревоги, когда со второй
        # попытки всё получилось.
        failed = [acc.name for acc, ok in results if not ok]
        if failed:
            await self._notify(
                "❌ <b>Не удалось авторизовать аккаунты</b>\n"
                + "\n".join(f"• {n}" for n in failed)
                + f"\n\nУспешно: {len(logged)}/{len(enabled)}"
            )

        return logged

    async def close_clients(self):
        """Аккуратно закрыть aiohttp-сессии Steam-клиентов (в этом же loop)."""
        for acc in self._accounts:
            try:
                if acc.steam_client:
                    await acc.steam_client.logout()
            except Exception as e:
                logger.debug(f"[{acc.name}] close error: {e}")

    async def refresh_balances(self, accounts) -> str:
        """Тянет Steam + CSGO.TM балансы, обновляет state, возвращает текст-сводку."""
        lines = []
        for acc in accounts:
            steam_bal = 0.0
            csgo_bal = 0.0
            try:
                wallet = await acc.steam_client.get_wallet_balance()
                if wallet:
                    steam_bal = wallet.balance
                    acc._last_wallet_balance = steam_bal
            except Exception as e:
                logger.warning(f"[{acc.name}] steam balance error: {e}")
            try:
                money = await asyncio.to_thread(acc.get_csgotm_money)
                csgo_bal = money.get("money", 0.0)
            except Exception as e:
                logger.warning(f"[{acc.name}] csgotm balance error: {e}")

            for info in self.state.accounts:
                if info.name == acc.name:
                    info.steam_balance = steam_bal
                    info.csgotm_balance = csgo_bal
                    break
            lines.append(f"[{acc.name}] Steam: {steam_bal:.2f} {acc.config.currency} | CSGO.TM: {csgo_bal:.2f} ₽")

        summary = "\n".join(lines)
        logger.info("Балансы:\n" + summary)
        return summary

    # ------------------------------------------------------------- buy cycle
    async def run_buy_cycle(self):
        """Один buy-цикл по всем ботам."""
        if not self.bots:
            return
        logger.info("===== BUY CYCLE =====")
        for name, bot in self.bots.items():
            try:
                stats = await bot.run_cycle()
                logger.info(f"[{name}] cycle: {stats}")
            except Exception as e:
                logger.error(f"[{name}] buy cycle error: {e}")
                import traceback
                logger.debug(traceback.format_exc())

    async def maybe_heartbeat(self, accounts, cycle_num: int, force: bool = False):
        """Раз в heartbeat_hours шлёт сводку (балансы + статистика продаж) в Telegram."""
        if self.heartbeat_hours <= 0 or not self.telegram_bot:
            return
        now = time.time()
        if not force and (now - self._last_heartbeat) < self.heartbeat_hours * 3600:
            return
        self._last_heartbeat = now

        bal_lines = []
        for info in self.state.accounts:
            if info.logged_in:
                bal_lines.append(f"• {info.name}: Steam {info.steam_balance:.0f} {info.currency} | TM {info.csgotm_balance:.0f} ₽")

        sold = listed = 0
        try:
            for st in self.sales_service._account_states.values():
                sold += st.stats.items_sold
                listed += st.stats.items_listed
        except Exception:
            pass

        text = (
            f"💓 <b>server_runner жив</b> {datetime.now():%Y-%m-%d %H:%M}\n"
            f"Циклов: {cycle_num}\n"
            + ("\n".join(bal_lines) if bal_lines else "нет залогиненных аккаунтов")
            + f"\n📦 За сессию: выставлено {listed}, продано {sold}"
        )
        await self._notify(text)

    # ------------------------------------------------------------- dry run
    async def dry_run(self, accounts):
        """
        Безопасная проверка всего стека БЕЗ сделок: логин, балансы, активные ордера,
        профитные предметы, access token и sell-статус CSGO.TM (проверка пути подтверждений).
        """
        logger.info("=========== DRY-RUN (без сделок) ===========")
        await self.refresh_balances(accounts)

        for acc in accounts:
            # Активные buy-ордера в Steam
            try:
                orders = await acc.steam_client.get_active_buy_orders()
                logger.info(f"[{acc.name}] активных buy-ордеров в Steam: {len(orders)}")
            except Exception as e:
                logger.error(f"[{acc.name}] get_active_buy_orders FAILED: {e}")

            # Профитные предметы из БД (что бот попытался бы купить)
            try:
                bot = TradingBot(acc)
                items = bot.get_profitable_items(limit=5)
                logger.info(f"[{acc.name}] профитных предметов доступно: {len(items)}")
            except Exception as e:
                logger.error(f"[{acc.name}] get_profitable_items FAILED: {e}")

            # Access token + sell-статус (проверка пути продажи/подтверждений)
            try:
                token = await acc.steam_client.get_access_token()
                logger.info(f"[{acc.name}] access_token: {'OK (' + str(len(token)) + ' симв.)' if token else 'НЕТ'}")
            except Exception as e:
                logger.error(f"[{acc.name}] get_access_token FAILED: {e}")

            try:
                if acc.csgotm_client:
                    status = await asyncio.to_thread(acc.csgotm_client.test_sell_status)
                    issues = []
                    if not status.get("user_token"):
                        issues.append("trade link не задан")
                    if not status.get("trade_check"):
                        issues.append("trade check не прошёл")
                    if not status.get("steam_web_api_key"):
                        issues.append("Steam API key не задан")
                    if status.get("site_notmpban") is False:
                        issues.append("ВРЕМЕННЫЙ БАН за невыдачу предметов")
                    logger.info(f"[{acc.name}] sell-статус: {'OK' if not issues else ', '.join(issues)}")
            except Exception as e:
                logger.error(f"[{acc.name}] test_sell_status FAILED: {e}")

        logger.info("=========== DRY-RUN завершён ===========")

    # ------------------------------------------ управляемые методы (CLI + API)
    async def prepare(self) -> list:
        """Логин аккаунтов + балансы + загрузка данных из БД в state. Для API-режима.

        БД грузится ВСЕГДА (логина Steam не требует) — сайт показывает ордера/холд/статистику
        даже если Steam временно отклонил вход. Балансы обновляются только при успешном логине.
        """
        # БД — независимо от Steam
        try:
            self.db_service.load_all_data()
        except Exception as e:
            logger.warning(f"db load error: {e}")

        accounts = await self.login_all()
        if accounts:
            try:
                await self.refresh_balances(accounts)
            except Exception as e:
                logger.warning(f"balance refresh error: {e}")
            # перезагрузим данные (после логина могли синхронизироваться)
            try:
                self.db_service.load_all_data()
            except Exception:
                pass

        # Polling Telegram — без него callback'и от inline-кнопок не приходят вообще
        # (в GUI это делает flet_gui/main.py, в headless-режиме раньше не запускалось).
        self.start_telegram_polling()
        return accounts

    def start_telegram_polling(self):
        """Запустить приём Telegram-обновлений (нужно для inline-кнопок в уведомлениях).

        start_polling() внутри держит себя живым через asyncio.Event().wait() и никогда
        не возвращается, поэтому запускаем ЗАДАЧЕЙ, иначе повесим весь старт сервера.
        """
        if not self.telegram_bot:
            return
        if self._tg_task and not self._tg_task.done():
            return
        try:
            self._tg_task = asyncio.create_task(self.telegram_bot.start_polling())
            logger.info("Telegram polling запущен — кнопки в уведомлениях активны")
        except Exception as e:
            logger.warning(f"Telegram polling не запустился: {e}")

    # --------------------------------------------------- автономный режим
    async def start_autonomous(self):
        """Поднять всё разом: продажи + buy-цикл + сканер, и включить watchdog.

        Используется в headless/API-режиме, чтобы бот работал «поставил и забыл».
        """
        started = []
        try:
            if await self.start_sales():
                started.append("sales")
        except Exception as e:
            logger.error(f"autostart sales failed: {e}")
            await self._notify(f"⚠️ Не удалось запустить продажи: {e}")

        try:
            if await self.start_buy_loop():
                started.append(f"buy/{self.cycle_min}м")
        except Exception as e:
            logger.error(f"autostart buy failed: {e}")
            await self._notify(f"⚠️ Не удалось запустить buy-цикл: {e}")

        try:
            if self.start_scanner():
                started.append(f"scan/{self.scan_min}м")
        except Exception as e:
            logger.error(f"autostart scanner failed: {e}")
            await self._notify(f"⚠️ Не удалось запустить сканер: {e}")

        logger.info(f"Автономный режим: запущено {', '.join(started) or 'ничего'}")

        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())

        if self._order_recheck_task is None or self._order_recheck_task.done():
            self._order_recheck_task = asyncio.create_task(self._order_recheck_loop())

        await self._notify(
            "🤖 <b>Автономный режим включён</b>\n"
            f"Продажи: {'✅' if 'sales' in started else '❌'}\n"
            f"Buy-цикл: каждые {self.cycle_min} мин\n"
            f"Сканер: каждые {self.scan_min} мин"
        )
        return started

    async def _watchdog_loop(self):
        """Следит, что продажи/buy/сканер живы и поднимает упавшее.

        Уведомления шлём ТОЛЬКО когда восстановить не удалось. Успешный авто-рестарт —
        это самоизлечившийся сбой, о нём достаточно записи в логе: иначе в чат сыплются
        «фейковые» тревоги про проблемы, которых по факту уже нет.
        """
        while True:
            try:
                await asyncio.sleep(self.WATCHDOG_INTERVAL_SEC)

                # Продажи должны работать ВСЕГДА
                sales_alive = False
                try:
                    sales_alive = bool(getattr(self.sales_service, "_running", False))
                except Exception:
                    pass
                if not sales_alive and self._accounts:
                    logger.warning("Watchdog: сервис продаж упал — перезапускаю")
                    try:
                        await self.start_sales()
                        logger.info("Watchdog: продажи восстановлены")
                    except Exception as e:
                        await self._notify(f"❌ <b>Продажи упали</b> и не восстановились: {e}")

                # Buy-цикл
                if self._buy_task is None or self._buy_task.done():
                    logger.warning("Watchdog: buy-цикл не активен — перезапускаю")
                    try:
                        await self.start_buy_loop()
                        logger.info("Watchdog: buy-цикл восстановлен")
                    except Exception as e:
                        await self._notify(f"❌ <b>Buy-цикл упал</b> и не восстановился: {e}")

                # Сканер
                try:
                    if not self.state.scanner_state.running:
                        logger.warning("Watchdog: сканер не активен — перезапускаю")
                        self.start_scanner()
                        logger.info("Watchdog: сканер восстановлен")
                except Exception as e:
                    await self._notify(f"❌ <b>Сканер упал</b> и не восстановился: {e}")

                # Аккаунты разлогинились — без них не работает ничего.
                # Шлём один раз на «эпизод»: пока состояние не изменилось, не повторяем.
                try:
                    offline = {a.name for a in self._accounts if not await self._is_logged_in(a)}
                    if offline and offline != self._offline_notified:
                        await self._notify(
                            "⚠️ <b>Аккаунты не в сети</b>: " + ", ".join(sorted(offline))
                        )
                    elif not offline and self._offline_notified:
                        await self._notify(
                            "✅ Аккаунты снова в сети: " + ", ".join(sorted(self._offline_notified))
                        )
                    self._offline_notified = offline
                except Exception:
                    pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Watchdog error: {e}")

    async def _order_recheck_loop(self):
        """Раз в 6 часов пересчитывает профит по активным ордерам и отменяет невыгодные.

        В buy-цикле этого нет: sync_order_statuses() сверяет только НАЛИЧИЕ ордера в Steam
        (есть/нет → filled/cancelled), но не пересчитывает профит. Готовый метод
        check_and_cancel_unprofitable_orders() раньше вызывался только из GUI по кнопке,
        поэтому в headless-режиме ордера по профиту не перепроверялись вообще.
        """
        while True:
            try:
                await asyncio.sleep(self.ORDER_RECHECK_INTERVAL_SEC)
                await self.recheck_orders_profit()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Order recheck loop error: {e}")

    async def recheck_orders_profit(self) -> dict:
        """Один прогон перепроверки профита активных ордеров (можно дёрнуть вручную)."""
        if not self.account_service or not self.db_service:
            return {}

        cfg = self.state.config or {}
        min_profit = float(cfg.get("check_orders_min_profit", 5.0))

        # Предметы под управлением авто-байера не трогаем (как в GUI)
        excluded = set()
        try:
            excluded = {i.name for i in self.auto_buy_service.items}
        except Exception:
            pass

        logger.info(f"Перепроверка ордеров: мин. профит {min_profit}%")
        try:
            results = await self.account_service.check_and_cancel_unprofitable_orders(
                self.db_service,
                min_profit_percent=min_profit,
                check_realtime=True,
                excluded_items=excluded,
            )
        except Exception as e:
            logger.error(f"Перепроверка ордеров упала: {e}")
            await self._notify(f"⚠️ Перепроверка ордеров не выполнена: {e}")
            return {}

        try:
            self.db_service.load_all_data()
        except Exception:
            pass

        checked = results.get("checked", 0)
        cancelled = results.get("cancelled", 0)
        skipped = results.get("skipped", 0)
        logger.info(f"Перепроверка ордеров: проверено {checked}, отменено {cancelled}, пропущено {skipped}")

        # В Telegram пишем только если реально что-то отменили — иначе лишний шум
        if cancelled:
            await self._notify(
                "🧹 <b>Перепроверка ордеров</b>\n"
                f"Отменено невыгодных: <b>{cancelled}</b>\n"
                f"Проверено: {checked} | Пропущено: {skipped}\n"
                f"Порог профита: {min_profit}%"
            )
        return results

    async def _is_logged_in(self, acc) -> bool:
        """Мягкая проверка залогиненности аккаунта (без запросов к Steam)."""
        try:
            client = getattr(acc, "steam_client", None)
            return bool(client and getattr(client, "_logged_in", False))
        except Exception:
            return True  # не смогли проверить — не поднимаем ложную тревогу

    async def start_sales(self):
        if not self._accounts:
            return False
        await self.sales_service.start([a.name for a in self._accounts])
        for acc in self._accounts:
            self.bots.setdefault(acc.name, TradingBot(acc))
        return True

    async def stop_sales(self):
        await self.sales_service.stop()

    def start_scanner(self):
        self.state.config["scan_interval_minutes"] = self.scan_min
        return self.scanner_service.start_scanner()

    def stop_scanner(self):
        self.scanner_service.stop_scanner()

    async def start_buy_loop(self):
        """Запустить периодический buy-цикл как фоновую задачу (для API)."""
        if self._buy_task and not self._buy_task.done():
            return False
        for acc in self._accounts:
            self.bots.setdefault(acc.name, TradingBot(acc))
        self._buy_stop = asyncio.Event()
        self._buy_task = asyncio.create_task(self._buy_loop_body(self._buy_stop))
        self.state.update_bot_status(True, "Running")
        return True

    async def stop_buy_loop(self):
        if self._buy_stop:
            self._buy_stop.set()
        if self._buy_task:
            try:
                await asyncio.wait_for(self._buy_task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._buy_task.cancel()
        self.state.update_bot_status(False, "Stopped")

    async def _buy_loop_body(self, stop_event):
        cycle_sec = self.cycle_min * 60
        self._last_heartbeat = time.time()
        cycle_num = 0
        while not stop_event.is_set():
            cycle_num += 1
            logger.info(f"\n######## CYCLE #{cycle_num} ########")
            await self.run_buy_cycle()
            try:
                await self.refresh_balances(self._accounts)
            except Exception as e:
                logger.warning(f"balance refresh error: {e}")
            try:
                await self.maybe_heartbeat(self._accounts, cycle_num)
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=cycle_sec)
            except asyncio.TimeoutError:
                pass

    def status_snapshot(self) -> dict:
        """Снимок состояния подсистем для API /status."""
        try:
            sales_running = getattr(self.sales_service, "_running", False)
        except Exception:
            sales_running = False
        return {
            "accounts_logged_in": sum(1 for a in self.state.accounts if a.logged_in),
            "accounts_total": len(self.state.accounts),
            "buy_running": bool(self._buy_task and not self._buy_task.done()),
            "sales_running": sales_running,
            "scanner_running": self.state.scanner_state.running,
            "cycle_min": self.cycle_min,
            "scan_min": self.scan_min,
        }

    # ------------------------------------------------------------- lifecycle
    async def run(self):
        accounts = await self.login_all()
        if not accounts:
            logger.error("Ни один аккаунт не залогинен — выход")
            return

        if self.args.dry_run:
            await self.dry_run(accounts)
            await self.close_clients()
            return

        await self.refresh_balances(accounts)
        await self._notify(
            f"🤖 server_runner запущен\nАккаунтов: {len(accounts)}\n"
            f"buy: {'off' if self.args.no_buy else str(self.cycle_min)+' мин'} | "
            f"sell: {'off' if self.args.no_sell else 'on'} | "
            f"scan: {'off' if self.args.no_scan else str(self.scan_min)+' мин'}"
        )

        # Продажи (создаёт свои задачи в этом loop; переинициализирует steam-клиенты in-loop)
        if not self.args.no_sell:
            try:
                await self.sales_service.start([a.name for a in accounts])
                logger.info("TmSalesService запущен")
            except Exception as e:
                logger.error(f"TmSalesService start failed: {e}")

        # Боты для buy-цикла (после sales.start — используют in-loop клиенты)
        if not self.args.no_buy:
            for acc in accounts:
                self.bots[acc.name] = TradingBot(acc)

        # Сканер (в отдельном потоке, свои клиенты)
        if not self.args.no_scan:
            try:
                self.state.config["scan_interval_minutes"] = self.scan_min
                self.scanner_service.start_scanner()
            except Exception as e:
                logger.error(f"Scanner start failed: {e}")

        if self.args.once:
            await self.run_buy_cycle()
            await self.shutdown()
            return

        # Основной цикл
        cycle_sec = self.cycle_min * 60
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _request_stop():
            logger.info("Получен сигнал остановки")
            stop_event.set()

        try:
            loop.add_signal_handler(signal.SIGINT, _request_stop)
            loop.add_signal_handler(signal.SIGTERM, _request_stop)
        except (NotImplementedError, RuntimeError):
            # Windows ProactorEventLoop не всегда поддерживает add_signal_handler
            pass

        logger.info(f"Основной цикл: buy каждые {self.cycle_min} мин. Ctrl+C для остановки.")
        self._last_heartbeat = time.time()
        cycle_num = 0
        while not stop_event.is_set():
            cycle_num += 1
            logger.info(f"\n######## CYCLE #{cycle_num} ########")
            if not self.args.no_buy:
                await self.run_buy_cycle()
                try:
                    await self.refresh_balances(accounts)
                except Exception as e:
                    logger.warning(f"balance refresh error: {e}")
            try:
                await self.maybe_heartbeat(accounts, cycle_num)
            except Exception as e:
                logger.debug(f"heartbeat error: {e}")
            # Ждём следующего цикла или сигнала остановки
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=cycle_sec)
            except asyncio.TimeoutError:
                pass

        await self.shutdown()

    async def shutdown(self):
        if self._stopping:
            return
        self._stopping = True
        logger.info("Останавливаемся...")
        if not self.args.no_sell:
            try:
                await self.sales_service.stop()
            except Exception as e:
                logger.warning(f"sales stop error: {e}")
        if not self.args.no_scan:
            try:
                self.scanner_service.stop_scanner()
            except Exception as e:
                logger.warning(f"scanner stop error: {e}")
        await self._notify("🛑 server_runner остановлен")
        await self.close_clients()
        logger.info("Готово.")


def parse_args():
    p = argparse.ArgumentParser(description="Headless server orchestrator для торгового бота")
    p.add_argument("--once", action="store_true", help="Один buy-цикл и выход")
    p.add_argument("--dry-run", action="store_true", help="Проверка без сделок (логин/API/балансы/sell-статус)")
    p.add_argument("--no-buy", action="store_true", help="Не запускать buy-цикл")
    p.add_argument("--no-sell", action="store_true", help="Не запускать продажи")
    p.add_argument("--no-scan", action="store_true", help="Не запускать сканер")
    p.add_argument("--cycle-min", type=int, default=0, help="Интервал buy-цикла, мин (по умолчанию из config/30)")
    p.add_argument("--scan-min", type=int, default=0, help="Интервал сканера, мин (по умолчанию из config/30)")
    p.add_argument("--heartbeat-hours", type=int, default=12, help="Период сводки в Telegram, ч (0 = выкл)")
    return p.parse_args()


async def _amain():
    args = parse_args()
    orch = ServerOrchestrator(args)
    try:
        await orch.run()
    except Exception as e:
        import traceback
        logger.error(f"ФАТАЛЬНЫЙ СБОЙ: {e}")
        logger.error(traceback.format_exc())
        try:
            await orch._notify(f"💥 server_runner упал: {e}\n(systemd перезапустит, если настроен)")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        logger.info("Прервано пользователем")
