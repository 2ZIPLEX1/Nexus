# Деплой бота на VPS (24/7, «поставил и забыл»)

Серверный энтрипоинт — [`server_runner.py`](../server_runner.py): один процесс держит buy-цикл,
продажи (CSGO.TM: ping-онлайн, листинг после холда, подтверждение трейдов через maFile,
детект проданного, репрайс), сканер и уведомления в Telegram. GUI/окно не нужны.

Ниже — Linux (systemd). Для Windows-сервера см. раздел в конце.

---

## 1. Подготовка

```bash
# Пользователь без root-прав под бота
sudo useradd -m -s /bin/bash botuser

# Код в /opt/tm-steambot (скопируй репозиторий сюда)
sudo mkdir -p /opt/tm-steambot
sudo chown -R botuser:botuser /opt/tm-steambot
# ... скопировать файлы проекта в /opt/tm-steambot ...

sudo -u botuser bash
cd /opt/tm-steambot

# venv + зависимости
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

> Нужен Python 3.11+. На 3.14 DNS-фикс (`src/dns_compat.py`) обязателен — он уже применяется автоматически.

## 2. Конфигурация

Проверь, что на месте и заполнены:

- **`accounts.json`** — аккаунты (`steam.username/password/api_key/shared_secret/identity_secret/steamid`,
  `csgotm.api_key`, `limits`, `proxy`). `enabled: true` только у боевых.
- **`.env`** — `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (для уведомlений и heartbeat), лимиты.
- **`bot_config.json`** — пороги профита/цены, интервалы (`cycle_interval_minutes`, `scan_interval_minutes`).
- **`proxies.txt`** — прокси для сканера (по одному в строке).

⚠️ **Config-гэп продажи:** в CSGO.TM-аккаунте должен быть задан **Steam Web API key**
(в dry-run видно как `steam_web_api_key: False`). Без него верификация трейдов при продаже может не работать.
Задать в настройках маркета для каждого аккаунта.

### 2.1 Права на файлы с секретами — обязательно

`accounts.json`, `.env`, `proxies.txt` и `*.maFile` содержат пароли Steam, семена
Steam Guard и ключи API **открытым текстом**. После `chown` из шага 1 они всё ещё
имеют режим 644 — то есть их читает любой пользователь сервера. Исправьте:

```bash
cd /opt/tm-steambot
chmod 600 .env accounts.json proxies.txt 2>/dev/null
chmod 600 *.maFile 2>/dev/null
chmod 700 data logs
chown -R botuser:botuser /opt/tm-steambot

# Проверка: во втором столбце должно быть -rw------- у всех файлов
ls -l .env accounts.json proxies.txt *.maFile 2>/dev/null
```

> **Перед первым запуском на сервере пройдите
> [ROTATION.md](ROTATION.md).** Часть ключей уже могла утечь (пароли прокси
> лежали в `logs/bot.log`, а `build_exe.py` зашивал `.env` в дистрибутив),
> и правки в коде их не отзывают.

### 2.2 Веб-панель

Если поднимаете сайт, а не только headless-бота, см.
[../web/README.md](../web/README.md) и юнит
[tm-steambot-web.service](tm-steambot-web.service). Ключевое: панели нужен
`WEB_API_PASSWORD_HASH` (`python -m web.hashpw`), она слушает `127.0.0.1`, а
наружу выставляется только через nginx с TLS
([nginx-tm-steambot.conf](nginx-tm-steambot.conf)).

## 3. Проверка ДО запуска службы (без сделок)

```bash
cd /opt/tm-steambot
.venv/bin/python server_runner.py --dry-run
```

Ожидаем: логин всех аккаунтов, балансы Steam+CSGO.TM, активные ордера, `access_token: OK`,
`sell-статус: OK`. Если что-то падает — чинить до включения службы.

Опционально — один реальный buy-цикл вручную (создаёт реальные ордера!):
```bash
.venv/bin/python server_runner.py --once
```

## 4. systemd-служба (авто-рестарт)

```bash
# Отредактируй User / WorkingDirectory / ExecStart под свои пути
sudo cp /opt/tm-steambot/deploy/tm-steambot.service /etc/systemd/system/
sudo nano /etc/systemd/system/tm-steambot.service

sudo systemctl daemon-reload
sudo systemctl enable --now tm-steambot

# Статус и логи
systemctl status tm-steambot
journalctl -u tm-steambot -f
```

Служба перезапускается сама при падении (`Restart=always`, пауза 15с; не более 5 рестартов за 5 мин).
Мягкая остановка `systemctl stop tm-steambot` шлёт SIGTERM → бот корректно закрывает сессии.

### Флаги (правь `ExecStart`)
```
server_runner.py                       # 24/7: buy + sell + scan
server_runner.py --cycle-min 30 --scan-min 30
server_runner.py --no-scan             # без сканера (если нет прокси)
server_runner.py --heartbeat-hours 12  # сводка в Telegram раз в 12ч (0 = выкл)
```

## 5. Ротация логов

`server_runner` пишет в `logs/bot.log` (+ journald). Чтобы файл не рос бесконечно:

```bash
# Подставь свой путь внутри файла, затем:
sudo cp /opt/tm-steambot/deploy/logrotate-tm-steambot /etc/logrotate.d/tm-steambot
sudo logrotate --debug /etc/logrotate.d/tm-steambot   # проверка конфига
```

Используется `copytruncate` — служба не требует перезапуска при ротации.

## 6. Проверка живучести

- Останови и подними: `sudo systemctl restart tm-steambot` — в Telegram придёт «запущен».
- Heartbeat: раз в `--heartbeat-hours` в Telegram приходит сводка (балансы, кол-во циклов, продажи).
- Фатальный сбой шлёт `💥 server_runner упал: ...` перед рестартом.

---

## Windows-сервер (альтернатива)

systemd нет. Варианты:
- **NSSM** (Non-Sucking Service Manager): `nssm install tm-steambot` → Application = `python.exe`,
  Arguments = `server_runner.py`, Startup dir = папка проекта. NSSM сам рестартит при падении.
- **Планировщик задач**: триггер «При входе/запуске», действие `pythonw server_runner.py`,
  «Перезапускать при сбое».

Ротацию логов на Windows делает сам бот только частично — чисти `logs/bot.log` по расписанию
или ограничь `bot_config.json`/внешним скриптом.
