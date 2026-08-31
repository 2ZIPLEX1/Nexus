# План фиксов: Steam headers + подтверждения (maFile)

Дата: 2026-07-12. Контекст: Steam ужесточил проверку и часть запросов начала отличаться
по headers от реального браузера; отдельно — на аккаунтах с maFile не ставятся buy-ордера
(подтверждение через identity_secret падает), а на аккаунтах без maFile ставятся (ручное
подтверждение с телефона).

---

## Проблема 1. Header-фингерпринт Steam (orderbook и др.)

**Что было не так**
- `src/bottm/api/steam_market.py`, `_get_session()`: User-Agent был **обрезан** —
  `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36` без хвоста
  `(KHTML, like Gecko) Chrome/xxx Safari/537.36`. Такого UA у реального браузера не бывает.
- Запрос `GET /market/orderbook` (`_get_buy_orders_from_orderbook`) не слал `Sec-Fetch-*`,
  которые реальный fetch со страницы листинга всегда отправляет.
- `X-Valve-Request-Type: queryAction` и `Referer` уже были корректны.

**Что сделано** ✅
- Добавлены модульные константы `CHROME_VERSION`, `BROWSER_USER_AGENT`, `BROWSER_CLIENT_HINTS`.
- `_get_session()` теперь ставит полный UA + client hints (`sec-ch-ua*`).
- В orderbook-заголовки добавлены `Sec-Fetch-Site: same-origin`, `Sec-Fetch-Mode: cors`,
  `Sec-Fetch-Dest: empty`; `Accept` приведён к браузерному `*/*`.
- Версия Chrome в UA и в `sec-ch-ua` синхронизированы (обе `149`) — менять только вместе.

**Осталось / проверить**
- Прогнать реальный orderbook-запрос и убедиться, что 200, а не 429/403.
- При желании — согласовать те же UA/client-hints в «ручных» Steam-запросах
  (`get_histogram` через priceoverview, `get_access_token` через pointssummary в
  `src/steam_client_aiosteampy.py`), которые переиспользуют сессию aiosteampy.

---

## Проблема 2. maFile-подтверждения: ордера не ставятся на аккаунтах с maFile

**Диагноз (по коду + поведению)**
- Клиент выбирается по `shared_secret`:
  - без maFile → `ManualTwoFactorSteamClient` → подтверждение вручную с телефона (работает);
  - c maFile → `AioSteamClient` → авто-подтверждение через `mobileconf`, требует `identity_secret`.
- В `place_buy_order` (aiosteampy) при `need_confirmation` вызывается `confirm_market_purchase`,
  которая при пустом/некорректном `identity_secret` или сбое `mobileconf` **бросает исключение**,
  `place_buy_order` пробрасывает его → `create_buy_order` возвращал generic-ошибку → ордер не ставится.
- Ошибка **проглатывалась** и выглядела как обычный сбой создания ордера — в логах не видно причины.
- Логи в репозитории (январь) на ~6 мес старше проблемы (июль) и показывают старое успешное
  поведение — для текущей диагностики бесполезны.

**Что сделано** ✅
- `src/steam_client_aiosteampy.py`, `_create_client()`:
  - `identity_secret` нормализуется: пустая строка → `None` (чтобы `@identity_secret_required`
    отрабатывал корректно);
  - если у аккаунта есть `shared_secret`, но нет `identity_secret` — пишется явный `ERROR`
    «авто-подтверждение работать не будет».
- `create_buy_order()`: ошибки подтверждения теперь выделяются отдельно и логируются понятно:
  - `CONFIRMATION_NO_IDENTITY_SECRET` — нет identity_secret;
  - `CONFIRMATION_FAILED: ...` — подтверждение через mobileconf упало (виден текст ошибки Steam).
- `src/trading_bot.py`: убран **фейковый** блок `sleep(5); confirmed_count += 1`. Теперь
  `confirmed_count` инкрементится только когда ордер реально создан+подтверждён (success=True
  при наличии identity_secret), с честным логом. Провал подтверждения уходит в ветку «Order failed».

**Осталось / проверить (нужен свежий прогон)**
- Запустить бота на maFile-аккаунте и снять НОВЫЙ лог. Теперь причина будет видна:
  - `CONFIRMATION_NO_IDENTITY_SECRET` → identity_secret не долетает из конфига/maFile → чинить загрузку;
  - `CONFIRMATION_FAILED: <текст Steam>` → если это про headers/сессию — добавить нужные
    заголовки на `mobileconf`-запросы (аналогично orderbook) либо проверить mobile-scope сессии;
  - `Unable to find confirmation` → рассинхрон id подтверждения (тайминг/фильтр aiosteampy).

---

## Проблема 3. Сломанный модуль подтверждений (`src/confirmations.py`)

**Что было не так**
- `ConfirmationHandler` был написан под другую библиотеку (steampy/python-steam):
  вызывал `get_confirmations(identity_secret, steamid)`, `confirm_market_transaction`,
  `confirm_all_market_transactions`, `.steamid`, `.identity_secret`, `ensure_logged_in()` —
  ничего из этого нет у aiosteampy-обёртки. Все вызовы → `AttributeError` → глотались
  широким `except` → возвращали 0. Модуль молча ничего не делал.
- Был синхронным, хотя клиент полностью async (в `auto_buyer.py` висел TODO про это).

**Что сделано** ✅
- `confirmations.py` переписан как тонкая **async**-обёртка над нативным aiosteampy API:
  `get_confirmations()`, `allow_confirmation()`, `allow_all_confirmations()`.
  Методы: `get_confirmations()`, `allow(conf)`, `confirm_all()`,
  `confirm_all_market_listings()`, `confirm_all_trades()`. Типы подтверждений — по значениям
  `aiosteampy.constants.ConfirmationType` (TRADE=2, LISTING=3, PURCHASE=12).
- Понятная ошибка, если клиент не залогинен или нет identity_secret.
- `src/auto_buyer.py`: вызов `confirm_all_market_listings()` теперь `await`-ится.

**Примечание**
- В проде торговый цикл — `src/trading_bot.py` (Step 0–2). `ConfirmationHandler`/`auto_buyer`
  в активном пути не используются, но модуль приведён в рабочее состояние на будущее.

---

## Проблема 4. Без прокси: "Could not contact DNS servers" (aiodns на Windows)

**Диагноз (проверено репродукцией)**
- OS-резолвер работает: `socket.gethostbyname('steamcommunity.com')` → 104.83.34.182.
- Установлены `aiodns 4.0.0` + `pycares 5.0.1`; aiohttp 3.13 при наличии aiodns берёт
  `DefaultResolver = AsyncResolver` (c-ares). На этом Windows/Python 3.14 c-ares не может
  прочитать DNS-серверы → `Cannot connect to host steamcommunity.com:443 [Could not contact DNS servers]`.
- С socks5-прокси проблема не видна (хост резолвится удалённо на прокси). Ошибка на этапе
  резолва DNS, ДО HTTP — headers/запрос ни при чём.
- Тест: `AsyncResolver(aiodns)` → FAIL, `ThreadedResolver(OS)` → 200.

**Что сделано** ✅
- Новый модуль `src/dns_compat.py`: `apply_dns_compat()` переключает
  `aiohttp.resolver.DefaultResolver` и `aiohttp.connector.DefaultResolver` на `ThreadedResolver`
  (OS getaddrinfo). Применяется при импорте, идемпотентно, ДО создания любых ClientSession.
- Импортируется рано в: `src/steam_client_aiosteampy.py`, `src/bottm/api/steam_market.py`,
  `flet_gui/main.py`.

**Альтернатива без кода:** `pip uninstall aiodns` — тогда aiohttp сам использует ThreadedResolver.

**Проверка:** после импорта `DefaultResolver = ThreadedResolver`; дефолтная сессия к Steam → 200.

---

## Проблема 5. createbuyorder отклоняется («429» = анти-бот на кривой отпечаток)

**Сверка браузерного cURL `POST /market/createbuyorder/` с aiosteampy**
- Отсутствовали у нас: `Origin`, `Sec-Fetch-Site/Mode/Dest`, `sec-ch-ua*`, `Accept-Language`.
- User-Agent: браузер — Windows Chrome 149; у нас — случайный из fake_useragent
  (в логах ChromeOS/Mac!), что не совпадает с `sec-ch-ua-platform: Windows` и палит бота.
- `X-Requested-With` браузер тут НЕ шлёт (ранняя гипотеза снята).
- Тело: браузер — `multipart/form-data` + доп. поля (`billing_country=RU`, `tradefee_tax`,
  `save_my_address`, first/last name…); у нас — `x-www-form-urlencoded` без них. Оба формата
  валидны — вероятно НЕ блокер; блокер — отпечаток headers/UA.

**Что сделано** ✅ (в `src/steam_client_aiosteampy.py`)
- Константы `STEAM_CHROME_VERSION`/`STEAM_WINDOWS_UA` + `client_hints_for_ua()`.
- `_generate_user_agent()` и `get_or_create_user_agent()` теперь дают стабильный Windows Chrome UA;
  существующие не-Windows UA (ChromeOS/Mac) МИГРИРУЮТСЯ на Windows при следующем логине
  (старые cookies один раз инвалидируются — это норм).
- В `_create_client()` на сессию aiosteampy ставятся `Accept-Language` + `sec-ch-ua*`
  (согласованы с UA).
- В `create_buy_order()` в `place_buy_order(headers=...)` добавлены `Origin` + `Sec-Fetch-*`
  (Referer aiosteampy ставит сам).

**Осталось / если не хватит**
- Если Steam всё равно отклоняет — реплицировать тело браузера точно: `multipart/form-data`
  + поля `billing_country`, `tradefee_tax`, `save_my_address` и т.д. Это потребует обхода
  aiosteampy (свой POST), поэтому делаем только если header-фикс не помог.
- Те же per-request `Origin`/`Sec-Fetch` стоит добавить и в другие мутации
  (cancel_buy_order, mobileconf-подтверждения) для единообразия.

---

## Прочее (замечено в логах, НЕ входило в правки)
- `Failed to ... : Timeout context manager should be used inside a task` на
  `cancel_buy_order` / `get_inventory` / `get_active_buy_orders` — проблема обёртки asyncio/aiohttp
  timeout (event loop). Требует отдельного разбора.
- `get inventory: Cannot extend enumerations` — aiosteampy `App`-enum на неизвестном appid.
- Step 3 (продажа) в `trading_bot.py` закомментирован — предметы копятся «на удержании»,
  ничего не продаётся. Отдельная задача, если нужно включать продажу.

---

## Затронутые файлы
- `src/bottm/api/steam_market.py` — headers/UA/orderbook
- `src/steam_client_aiosteampy.py` — identity_secret guard + диагностика ошибок подтверждения
- `src/trading_bot.py` — честный учёт подтверждений
- `src/confirmations.py` — переписан под aiosteampy (async)
- `src/auto_buyer.py` — `await` для async-подтверждения
