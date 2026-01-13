# Steam Trading Bot

Автоматический торговый бот для арбитража между Steam Marketplace и market.csgo.com.

## Принцип работы

```
Steam Marketplace (покупка по ордеру)
    → 7 дней холд
    → market.csgo.com (продажа)
    → Профит!
```

1. **Анализ цен**: Бот читает базу данных bottm с рекомендованными ценами
2. **Покупка**: Выставляет ордера на покупку в Steam по рекомендованной цене (20-й перцентиль)
3. **Ожидание**: Отслеживает 7-дневный холд после покупки
4. **Продажа**: Выставляет предметы на market.csgo.com по актуальной цене
5. **Учёт**: Ведёт статистику прибыли и всех операций

## Установка

```bash
# Клонируйте репозиторий
git clone <repo-url>
cd tm-steambot

# Создайте виртуальное окружение
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate     # Windows

# Установите зависимости
pip install -r requirements.txt

# Скопируйте и заполните конфигурацию
cp .env.example .env
nano .env
```

## Конфигурация

Отредактируйте файл `.env`:

```ini
# Steam аккаунт
STEAM_USERNAME=your_username
STEAM_PASSWORD=your_password
STEAM_API_KEY=your_api_key

# Steam Guard секреты (из SDA или maFile)
STEAM_SHARED_SECRET=your_shared_secret
STEAM_IDENTITY_SECRET=your_identity_secret

# market.csgo.com API
CSGOTM_API_KEY=your_api_key

# Telegram бот (опционально)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Пути к базам данных
BOTTM_DB_PATH=./data/main.db
TRADES_DB_PATH=./data/my_trades.db

# Настройки торговли
MIN_PROFIT_PERCENT=15      # Минимальный профит для покупки
MAX_ITEM_PRICE=50.0        # Максимальная цена предмета
MIN_ITEM_PRICE=0.5         # Минимальная цена предмета
ORDER_LIMIT_MULTIPLIER=5   # Множитель лимита ордеров (x5 от баланса)
```

## Получение секретов Steam Guard

### Из Steam Desktop Authenticator (SDA):
1. Откройте папку `maFiles`
2. Найдите файл `<steamid>.maFile`
3. Скопируйте значения `shared_secret` и `identity_secret`

### Из maFile:
```json
{
    "shared_secret": "XXXXX=",
    "identity_secret": "YYYYY="
}
```

## Настройка прокси для аккаунтов

Каждый аккаунт может использовать свой прокси для всех запросов (Steam Market, CSGO.TM).

### Конфигурация прокси в accounts.json:

```json
[
  {
    "name": "account1",
    "enabled": true,
    "currency": "RUB",
    "steam": {
      "username": "your_username",
      "password": "your_password",
      "api_key": "your_api_key",
      "shared_secret": "your_shared_secret",
      "identity_secret": "your_identity_secret"
    },
    "csgotm": {
      "api_key": "your_csgotm_api_key"
    },
    "proxy": "socks5://username:password@host:port",
    "limits": {
      "max_items": 10,
      "max_price_per_item": 1000.0,
      "total_budget": 5000.0
    }
  }
]
```

### Форматы прокси:
- **SOCKS5**: `socks5://username:password@host:port`
- **HTTP**: `http://username:password@host:port`
- **Без авторизации**: `socks5://host:port`
- **Отключить прокси**: `"proxy": null`

### Преимущества:
- ✅ Каждый аккаунт использует свой прокси
- ✅ Прокси применяется ко всем запросам (Steam Market, CSGO.TM)
- ✅ Снижается риск блокировки при работе с несколькими аккаунтами
- ✅ Можно работать из регионов с ограничениями

## Использование

```bash
# Запуск бота с Telegram
python main.py

# Запуск без Telegram
python main.py --no-telegram

# Проверка подключений
python main.py --test

# Показать статус
python main.py --status
```

## Telegram команды

- `/start` - Приветствие
- `/status` - Текущий статус торговли
- `/balance` - Баланс кошелька
- `/orders` - Активные ордера
- `/holdings` - Предметы на холде
- `/profit` - Статистика прибыли
- `/help` - Помощь

## Структура проекта

```
tm-steambot/
├── .env.example          # Пример конфигурации
├── config/
│   └── settings.py       # Загрузка настроек
├── src/
│   ├── bot.py            # Главный оркестратор
│   ├── steam_client.py   # Клиент Steam API
│   ├── csgotm_client.py  # Клиент market.csgo.com API
│   ├── database.py       # База данных сделок
│   ├── bottm_parser.py   # Парсер базы bottm
│   ├── trade_logic.py    # Торговая логика
│   ├── confirmations.py  # Авто-подтверждения
│   ├── telegram_bot.py   # Telegram уведомления
│   └── logger.py         # Логирование
├── data/
│   ├── main.db           # База bottm (внешняя)
│   └── my_trades.db      # База сделок (создаётся автоматически)
├── logs/                 # Логи
├── main.py               # Точка входа
└── requirements.txt
```

## База данных bottm

Бот использует внешнюю базу данных bottm (`main.db`) для получения рекомендованных цен:

```sql
-- Таблица items
market_hash_name        -- Название предмета
recommended_buy_order   -- Рекомендованная цена ордера (20-й перцентиль)
csgo_price             -- Цена продажи на market.csgo.com
recommended_wait_pct    -- Ожидаемый профит %
```

## Лимиты и ограничения

- **Лимит ордеров**: Сумма активных ордеров ≤ баланс × 5 (Steam позволяет до x10)
- **Комиссия market.csgo.com**: 10% от суммы продажи
- **Холд**: 7 дней после покупки
- **Rate limiting**: 3 секунды между запросами к Steam

## Логика торговли

### Покупка
1. Получить список прибыльных предметов из bottm
2. Отфильтровать уже купленные и на холде
3. Проверить доступный бюджет
4. Выставить ордера по `recommended_buy_order`
5. Записать в базу данных

### Мониторинг ордеров
- Проверка исполненных ордеров
- Отмена ордеров при изменении цены > 10%

### Продажа
1. Найти предметы с истёкшим холдом
2. Получить актуальную цену из bottm
3. Найти предмет в инвентаре Steam
4. Выставить на market.csgo.com
5. Подтвердить трейд через Steam Guard

### Подтверждения
Автоматически подтверждает:
- Трейд-офферы от бота market.csgo.com
- Листинги на маркете

## Безопасность

- Никогда не коммитьте `.env` файл!
- Храните секреты Steam Guard в безопасности
- Используйте отдельный аккаунт для торговли
- Регулярно проверяйте логи на подозрительную активность

## Лицензия

MIT
