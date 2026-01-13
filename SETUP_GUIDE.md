# 🚀 Руководство по настройке и запуску бота

## 📋 Предварительные требования

1. Python 3.10+ установлен
2. База данных `profitable_items.db` от bottm
3. Аккаунты Steam с 2FA
4. API ключи CSGO.TM

## 🔧 Установка

### 1. Установить зависимости

```bash
pip install -r requirements.txt
```

### 2. Создать файл `.env`

Скопируйте `.env.example` в `.env` и заполните:

```bash
cp .env.example .env
nano .env
```

### 3. Настроить аккаунты

Создайте `accounts.json` на основе `accounts.example.json`:

```bash
cp accounts.example.json accounts.json
nano accounts.json
```

Пример для одного аккаунта:

```json
[
  {
    "name": "main_account",
    "enabled": true,
    "steam": {
      "username": "your_username",
      "password": "your_password",
      "api_key": "your_steam_api_key",
      "shared_secret": "base64_shared_secret",
      "identity_secret": "base64_identity_secret"
    },
    "csgotm": {
      "api_key": "your_csgotm_api_key"
    },
    "proxy": null,
    "limits": {
      "max_items": 10,
      "max_price_per_item": 1000.0,
      "total_budget": 5000.0
    }
  }
]
```

### 4. Получить cookies из браузера

**Для каждого аккаунта:**

1. Откройте https://store.steampowered.com (залогинившись)
2. Нажмите **F12** → **Application** → **Cookies** → **https://store.steampowered.com**
3. Скопируйте cookies:
   - `sessionid`
   - `steamLoginSecure`
   - `steamCountry`
   - `timezoneOffset`

4. Создайте файл `steam_cookies_<account_name>.txt`:

```
sessionid=your_sessionid
steamLoginSecure=your_steamLoginSecure
steamCountry=RU%7C...
timezoneOffset=10800,0
```

Например, для аккаунта `main_account` → `steam_cookies_main_account.txt`

## ✅ Проверка установки

Запустите тест:

```bash
python main.py --test
```

Должно показать:
- ✅ Steam подключение
- ✅ CSGO.TM подключение
- ✅ Баланс кошелька

## 🤖 Запуск бота

### Режим 1: Один цикл (тест)

```bash
python bot_runner.py --once
```

Выполнит:
1. Создание бай-ордеров
2. Проверку исполненных ордеров
3. Продажу предметов после холда

### Режим 2: Тестовый режим (без реальных сделок)

```bash
python bot_runner.py --once --test
```

Только читает profitable_items, НЕ создает ордера.

### Режим 3: Непрерывный цикл (24/7)

```bash
python bot_runner.py --loop
```

Бесконечный цикл каждые 5 минут.

**Остановка:** Ctrl+C

## 📊 Мониторинг

### Статистика БД

```python
from src.database import trades_db

stats = trades_db.get_stats()
print(f"Active orders: {stats['active_orders']}")
print(f"Items on hold: {stats['items_on_hold']}")
print(f"Total profit: ${stats['total_profit']:.2f}")
```

### Логи

Все операции логируются в консоль с префиксом `[account_name]`.

## 🔄 Workflow бота

```
1. Чтение profitable_items.db
   ↓
2. Фильтрация (профит > 5%, цена < лимита)
   ↓
3. Создание бай-ордеров на Steam Market
   ↓
4. Проверка исполненных ордеров (каждый цикл)
   ↓
5. Добавление в purchased_items (7-дневный холд)
   ↓
6. Проверка unlock_date
   ↓
7. Продажа на CSGO.TM (после холда)
   ↓
8. Запись в sold_items
```

## ⚙️ Настройки

### Лимиты (в accounts.json)

- `max_items` - макс. предметов одновременно (10)
- `max_price_per_item` - макс. цена за предмет (1000.0 RUB)
- `total_budget` - общий бюджет (5000.0 RUB)

### Минимальный профит (в trading_bot.py)

```python
MIN_PROFIT_PCT = 5.0  # 5%
```

### Интервал цикла (в bot_runner.py)

```python
CYCLE_INTERVAL = 300  # 5 минут
```

## 🐛 Troubleshooting

### Проблема: "Login failed: captcha"

**Решение:** Используйте cookies из браузера (см. шаг 4 установки)

### Проблема: "No profitable items"

**Решение:**
1. Проверьте путь к `profitable_items.db` в `.env`
2. Убедитесь, что в БД есть предметы
3. Понизьте `MIN_PROFIT_PCT` в `trading_bot.py`

### Проблема: "Insufficient balance"

**Решение:** Пополните баланс Steam кошелька

### Проблема: "Proxy connection failed"

**Решение:** Проверьте формат прокси в `accounts.json`:
- HTTP: `http://user:pass@ip:port`
- SOCKS5: `socks5://user:pass@ip:port`

## 📝 TODO

- [ ] Реализовать проверку статуса ордеров через Steam API
- [ ] Реализовать продажу на CSGO.TM через bot trade
- [ ] Добавить Telegram уведомления
- [ ] Добавить веб-интерфейс для мониторинга

## 📞 Поддержка

При возникновении проблем проверьте:
1. Логи в консоли
2. Файл `data/my_trades.db` (SQLite браузером)
3. Cookies актуальные (не истекли)

---

**Успешной торговли! 🎯💰**
