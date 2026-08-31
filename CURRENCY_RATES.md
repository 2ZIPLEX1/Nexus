# Модуль курсов валют

Автоматическое получение и кеширование актуальных курсов валют для мультивалютных аккаунтов Steam.

## Возможности

- ✅ **Автоматическое обновление** курсов раз в 24 часа
- ✅ **Несколько источников** с fallback:
  - exchangerate-api.com (основной)
  - ЦБ РФ API (резервный)
  - Статические курсы (fallback)
- ✅ **Двухуровневое кеширование**:
  - В памяти (мгновенный доступ)
  - В файле `data/currency_rates_cache.json` (персистентность)
- ✅ **Поддержка всех валют Steam**:
  - USD (код 1)
  - EUR (код 3)
  - RUB (код 5)
  - UAH (код 18)
  - TRY (код 19)
  - BRL (код 23)
  - CNY (код 25)

## Использование

### Получение актуальных курсов

```python
from src.currency_rates import get_currency_provider

provider = get_currency_provider()
rates = provider.get_rates()

print(rates)
# {'USD': 1.0, 'EUR': 0.86, 'RUB': 77.93, 'UAH': 43.41, ...}
```

### Конвертация рублей в валюту Steam

```python
from src.currency_rates import convert_rub_to_currency

# Конвертировать 850 RUB в USD (код валюты 1)
price_usd = convert_rub_to_currency(850, 1)  # ~10.91 USD

# Конвертировать 850 RUB в EUR (код валюты 3)
price_eur = convert_rub_to_currency(850, 3)  # ~9.40 EUR

# Конвертировать 850 RUB в RUB (код валюты 5)
price_rub = convert_rub_to_currency(850, 5)  # 850 RUB (без конвертации)
```

### Интеграция с созданием ордеров

Модуль автоматически используется в `steam_client_aiosteampy.py`:

```python
# В create_buy_order():
if wallet_currency != 5:  # Если НЕ RUB
    from src.currency_rates import convert_rub_to_currency
    price_in_wallet_currency = convert_rub_to_currency(price, wallet_currency)
```

## Работа с мультивалютными аккаунтами

### Пример: EUR аккаунт

1. **Получение цен**: Всегда в рублях (для сравнения с CSGO.TM)
   ```
   Steam Market: 850 RUB
   CSGO.TM:      1000 RUB
   Профит:       +17.6%
   ```

2. **Создание ордера**: Автоматическая конвертация
   ```
   850 RUB → 9.40 EUR (по актуальному курсу)
   Ордер создается на €9.40
   ```

3. **В Steam Community**: Отображается в EUR
   ```
   Your buy order: €9.40
   ```

## Кеширование

### Время жизни кеша
- **24 часа** - курсы обновляются раз в сутки
- Автоматическое обновление при истечении

### Местоположение кеша
```
data/currency_rates_cache.json
```

### Формат кеша
```json
{
  "timestamp": 1768832675.84,
  "rates": {
    "USD": 1.0,
    "EUR": 0.861402,
    "RUB": 77.931466,
    "UAH": 43.410176
  }
}
```

### Очистка кеша
Для принудительного обновления курсов удалите файл кеша:
```bash
rm data/currency_rates_cache.json
```

## Источники курсов

### 1. exchangerate-api.com (основной)
- **URL**: https://open.er-api.com/v6/latest/USD
- **Бесплатный**, без регистрации
- Обновление: раз в 24 часа
- Покрытие: все основные валюты

### 2. ЦБ РФ API (резервный)
- **URL**: https://www.cbr-xml-daily.ru/daily_json.js
- Официальный API Центрального Банка России
- Обновление: ежедневно
- Покрытие: RUB, EUR, USD

### 3. Статические курсы (fallback)
Используются если все API недоступны:
```python
{
    'USD': 1.0,
    'EUR': 0.92,
    'RUB': 95.0,
    'UAH': 41.0,
    'TRY': 34.0,
    'BRL': 5.0,
    'CNY': 7.2,
}
```

## Логирование

Модуль логирует все операции:

```
[INFO] Fetching fresh currency rates...
[INFO] Fetched rates from exchangerate-api: {'RUB': 77.93, ...}
[INFO] Currency rates updated
[DEBUG] Converted 850.00 RUB -> 9.40 EUR (via USD, rates: RUB=77.93, EUR=0.86)
```

## Производительность

- **Первый запрос**: ~500-1000ms (загрузка из API)
- **Кеш в файле**: ~5-10ms (чтение JSON)
- **Кеш в памяти**: <1ms (мгновенный доступ)

## Коды валют Steam

| Код | Валюта | Название |
|-----|--------|----------|
| 1   | USD    | US Dollar |
| 3   | EUR    | Euro |
| 5   | RUB    | Russian Ruble |
| 18  | UAH    | Ukrainian Hryvnia |
| 19  | TRY    | Turkish Lira |
| 23  | BRL    | Brazilian Real |
| 25  | CNY    | Chinese Yuan |

## Troubleshooting

### Курсы не обновляются
1. Проверьте доступность API:
   ```bash
   curl https://open.er-api.com/v6/latest/USD
   ```
2. Проверьте права доступа к `data/` директории
3. Очистите кеш вручную

### Неточные курсы
- Курсы обновляются раз в 24 часа
- Для крипто-скинов можно увеличить частоту обновления (изменить `CACHE_TTL`)
- Рекомендуется использовать margin для профита (5-10%)

### API недоступен
- Модуль автоматически переключится на резервный источник
- В крайнем случае используются статические курсы
- Проверьте подключение к интернету

## TODO

- [ ] Добавить больше источников курсов (backup)
- [ ] Поддержка других криптовалют
- [ ] WebSocket для real-time обновлений
- [ ] Настраиваемый TTL кеша через config
