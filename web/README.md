# Веб-версия бота (сайт)

Два компонента:

- **Бэкенд** `web/api.py` — FastAPI поверх `ServerOrchestrator`. Один процесс держит
  бота (buy/sell/scan) и API (REST + WebSocket). Общий `AppState`.
- **Фронтенд** `web/frontend/` — Next.js (дизайн в стиле uxera), зеркало GUI.

## Запуск бэкенда

```bash
# из корня проекта, в venv с requirements.txt

# 1. Один раз: придумать пароль и получить его хеш
python -m web.hashpw
# → WEB_API_PASSWORD_HASH=scrypt$32768$8$1$...

# 2. Запуск
export WEB_API_PASSWORD_HASH='scrypt$32768$8$1$...'   # ОБЯЗАТЕЛЬНО
export WEB_CORS_ORIGINS=http://localhost:3002
python -m web.api                            # http://127.0.0.1:8000
```

Без `WEB_API_PASSWORD_HASH` процесс **не стартует** — пароля по умолчанию нет
(раньше здесь был захардкоженный токен `professor`, и любой, кто видел исходник,
получал полный доступ к торговле).

Слушает только `127.0.0.1`. Наружу — через nginx с TLS, см.
[deploy/nginx-tm-steambot.conf](../deploy/nginx-tm-steambot.conf).

> **Торговля стартует автоматически.** При старте поднимается автономный режим:
> закупка, продажи и сканер работают реальными деньгами. Отключить —
> `WEB_AUTOSTART=0`, тогда подсистемы запускаются только кнопками на сайте.

**Авторизация — сессии с истечением:**

1. `POST /api/login` `{"password": "..."}` → `{"token": "...", "expires_in": 43200}`
2. Дальше — заголовок `Authorization: Bearer <token>`
3. Для WebSocket: `POST /api/ws-ticket` → одноразовый тикет на 30 с → `WS /ws?ticket=...`

Лимит на подбор пароля: 5 попыток за 15 минут с одного IP.

Эндпоинты: `GET /api/{status,accounts,orders,inventory,profitable,sales,history,logs,config}`,
`POST /api/{bot,sales,scanner}/{start,stop}`, `POST /api/scan/run`, `POST /api/config`,
`POST /api/{login,logout,ws-ticket}`, `WS /ws?ticket=...`.

`/docs` и `/openapi.json` закрыты (открыть — `WEB_ENABLE_DOCS=1`).

### Переменные окружения

| Переменная | Назначение |
|---|---|
| `WEB_API_PASSWORD_HASH` | **обязательна**, хеш пароля из `python -m web.hashpw` |
| `WEB_SESSION_TTL` | время жизни сессии, сек (по умолчанию 43200 = 12 ч) |
| `WEB_AUTOSTART` | `0` — не запускать торговлю при старте |
| `WEB_TRUST_PROXY` | `1` за nginx, иначе rate limit увидит один IP |
| `WEB_BIND_PUBLIC` | `1` — слушать `0.0.0.0` (без TLS не рекомендуется) |
| `WEB_CORS_ORIGINS` | список origin через запятую; `*` запрещён |
| `WEB_ENABLE_DOCS` | `1` — открыть `/docs` |
| `WEB_PORT` | порт (по умолчанию 8000) |

## Запуск фронтенда

```bash
cd web/frontend
cp .env.local.example .env.local     # при необходимости поправь NEXT_PUBLIC_API_BASE
npm install
npm run dev                          # http://localhost:3002
```

При первом входе фронт спросит **пароль** (тот, из которого сделан `WEB_API_PASSWORD_HASH`).
Пароль обменивается на сессионный токен и нигде не сохраняется; сам токен живёт в
`sessionStorage` — то есть пропадает при закрытии вкладки и не переживает перезагрузку,
в отличие от прежнего вечного токена в `localStorage`.

## Экраны (паритет с GUI)

Готовы и подключены к API: Дашборд (стат-карты + старт/стоп подсистем), Аккаунты, Ордера,
Инвентарь/холд, Сканер (+ ручной скан), Продажи, История, Статистика, Настройки, Логи (live).
Авто-покупка — заглушка (нужны CRUD-эндпоинты списка, следующая итерация).

## Прод

Готовые конфиги лежат в [deploy/](../deploy/):

| Файл | Назначение |
|---|---|
| [tm-steambot-web.service](../deploy/tm-steambot-web.service) | systemd-юнит панели (с изоляцией) |
| [nginx-tm-steambot.conf](../deploy/nginx-tm-steambot.conf) | TLS-терминация + reverse-proxy |
| [ROTATION.md](../deploy/ROTATION.md) | **чеклист ротации ключей — выполнить до выкладки** |

Схема: интернет → nginx (443, TLS) → uvicorn на `127.0.0.1:8000`. Фронт —
`npm run build && npm start` на `127.0.0.1:3000`, наружу тоже через nginx.

```bash
sudo cp deploy/tm-steambot-web.service /etc/systemd/system/
sudo mkdir -p /etc/tm-steambot
python -m web.hashpw    # результат → /etc/tm-steambot/web.env
sudo chmod 600 /etc/tm-steambot/web.env
sudo chown botuser /etc/tm-steambot/web.env
sudo systemctl daemon-reload && sudo systemctl enable --now tm-steambot-web
```

Проверить, что наружу ничего лишнего не смотрит:

```bash
ss -tlnp | grep -E '8000|3000'      # должен быть только 127.0.0.1
```

Панель управляет реальными деньгами — не выставляйте её в интернет без TLS и
без ротации ключей из `ROTATION.md`.
