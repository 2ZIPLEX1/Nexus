Полное объяснение логики парсера и план исправлений
ОБЗОР СИСТЕМЫ
Бот реализует торговую стратегию: Купить на Steam через buy order → Продать на market.csgo.com

1. ПОЛНЫЙ ПРОЦЕСС ПАРСЕРА (ОТ НАЧАЛА ДО КОНЦА)
1.1 Точка входа - scanner_process.py:118-189
Процесс запуска:

Загрузка конфигурации из JSON (min_price, max_price, min_profit, min_sales_7d)
Загрузка и тестирование прокси
Создание ItemScanner с фильтрами
Запуск scanner.load_data() для загрузки данных с маркетов
1.2 Загрузка данных - scanner.py:127-135
Источник 1: market.csgo.com

Эндпоинт: /api/v2/prices/class_instance/{currency}.json
Возвращает для каждого предмета:
price - минимальная цена ПРОДАЖИ на CSGO.TM
buy_order - максимальная заявка на ПОКУПКУ на CSGO.TM
popularity_7d - количество продаж за 7 дней
Источник 2: Steam Market

Получается позже для каждого отфильтрованного кандидата
1.3 Фильтрация кандидатов - scanner.py:137-176
Быстрая предварительная фильтрация:

Тип предмета: только weapon_skin и agent
Диапазон цен: min_price ≤ price ≤ max_price
Минимум продаж: popularity_7d ≥ min_sales_7d
Наличие buy_order на CSGO.TM (> 0)
Результат: Отсортированный список кандидатов (по популярности)

1.4 Анализ каждого кандидата - scanner.py:178-418
Для каждого кандидата выполняется:

Шаг 1: Получение данных Steam

priceoverview/ эндпоинт:

lowest_price - минимальная цена продажи
median_price - медианная цена
volume - объем за 24ч
itemordershistogram эндпоинт:

highest_buy_order - максимальная заявка на покупку (КЛЮЧЕВОЕ ЗНАЧЕНИЕ)
lowest_sell_order - минимальная цена продажи
buy_order_graph - график всех заявок
Шаг 2: Проверка на фейк профит (scanner.py:237-246)


if steam_buy_order >= steam_lowest_sell:
    return None  # ❌ ФЕЙК ПРОФИТ - невозможная ситуация!
Шаг 3: Получение истории цен

CSGO.TM: sales_7d, sales_30d, average_7d, average_30d
Steam: история за 7 дней с расчетом percentile_10 и percentile_25
2. КЛЮЧЕВЫЕ ПОНЯТИЯ
2.1 Steam Buy Order (steam_buy_order)
Что это: Текущая максимальная заявка на ПОКУПКУ на Steam Market
Откуда: itemordershistogram эндпоинт, поле highest_buy_order
Использование: База для расчета текущего профита
Пример: Если steam_buy_order = 1000 RUB, кто-то сейчас готов купить предмет за 1000 RUB
2.2 Рекомендуемая цена (recommended_buy_order)
Что это: Рекомендуемая цена для выставления своей заявки на покупку
Откуда: 10-й процентиль истории Steam за 7 дней
Формула: recommended_buy_order = percentile_10 × (steam_buy_order / steam_history.avg_price)
Смысл: Цена, ниже которой произошло 10% всех продаж за неделю
Выгода:
Дешевле чем текущая заявка (экономия денег)
Вероятность заполнения ~90%
Больший профит
Пример:


steam_buy_order = 1000 RUB (текущая лучшая заявка)
recommended_buy_order = 920 RUB (10-й процентиль)
Экономия: 80 RUB (8%)
2.3 Разница между ценами
Цена	Описание	Использование
steam_buy_order	Текущая макс заявка на Steam	Расчет текущего профита
suggested_buy_order	steam_buy_order × 1.01	Переторг текущей заявки
recommended_buy_order	10-й процентиль истории	РЕКОМЕНДУЕТСЯ для большего профита
steam_lowest_sell	Минимальная цена продажи на Steam	Проверка на фейк профит
2.4 Какую цену использовать для выставления ордера?
Приоритет:

✅ Если есть recommended_buy_order → используй её (больший профит)
⚠️ Если нет рекомендации → используй steam_buy_order или suggested_buy_order
❌ НИКОГДА не ставь выше steam_lowest_sell → потеряешь деньги
3. РАСЧЕТ ПРОФИТА
3.1 Константа комиссии

CSGO_MARKET_FEE_PCT = 7.0  # Комиссия market.csgo.com
3.2 Формулы профита
Мгновенная продажа (instant) - продать по buy_order на CSGO.TM:


csgo_instant_net = csgo_buy_order × 0.93
instant_profit = csgo_instant_net - steam_buy_order
instant_profit_pct = (instant_profit / steam_buy_order) × 100
Ждущая продажа (wait) - продать по price на CSGO.TM:


csgo_wait_net = csgo_price × 0.93
wait_profit = csgo_wait_net - steam_buy_order
wait_profit_pct = (wait_profit / steam_buy_order) × 100
С рекомендуемой ценой:


recommended_instant_profit = csgo_instant_net - recommended_buy_order
recommended_instant_profit_pct = (recommended_instant_profit / recommended_buy_order) × 100
3.3 Пример расчета

Предмет: AK-47 | Redline (Field-Tested)

CSGO.TM:
  - csgo_price = 1200 RUB (минимальная цена продажи)
  - csgo_buy_order = 1100 RUB (макс заявка на покупку)

Steam:
  - steam_buy_order = 950 RUB (макс заявка на покупку)
  - steam_lowest_sell = 1050 RUB (минимальная цена продажи)
  - recommended_buy_order = 900 RUB (10-й процентиль)

РАСЧЕТ ПРОФИТА:

1. При steam_buy_order (950 RUB):
   instant_profit = (1100 × 0.93) - 950 = 1023 - 950 = 73 RUB
   instant_profit_pct = (73 / 950) × 100 = 7.7%

   wait_profit = (1200 × 0.93) - 950 = 1116 - 950 = 166 RUB
   wait_profit_pct = (166 / 950) × 100 = 17.5%

2. При recommended_buy_order (900 RUB):
   recommended_instant_profit = 1023 - 900 = 123 RUB
   recommended_instant_profit_pct = (123 / 900) × 100 = 13.7%

   recommended_wait_profit = 1116 - 900 = 216 RUB
   recommended_wait_profit_pct = (216 / 900) × 100 = 24.0%

ВЫВОД: Использование recommended_buy_order дает +6% профита!
4. ПРОБЛЕМЫ С ФЕЙК ПРОФИТОМ (КРИТИЧЕСКИЕ НАХОДКИ)
4.1 Отсутствие валидации None значений
Проблема: scanner.py:237-246


if steam_lowest_sell and steam_buy_order:
    if steam_buy_order >= steam_lowest_sell:
        return None  # фейк профит
Баг: Если steam_lowest_sell = None, проверка не выполняется и функция продолжает работу с неполными данными!

Исправление: Добавить обязательную проверку наличия всех критических данных

4.2 Некорректная конвертация валют
Проблема: scanner.py:279-289


usd_to_currency = steam_buy_order / steam_history.avg_price
steam_history_p10 = steam_history.percentile_10 * usd_to_currency
Баг: Нет проверки на разумность коэффициента конвертации! Если steam_history.avg_price аномальный, результат будет фейковым.

Исправление: Добавить sanity-check на коэффициент (должен быть в разумных пределах 0.5-2.0)

4.3 Устаревшие данные из кэша
Проблема: csgo_market.py:208-222


if self._prices_cache and not force_reload:
    return self._prices_cache
Баг: Кэш может быть устаревшим (часами старым), нет timestamp!

Исправление: Добавить автоматическое обновление кэша каждые N минут

4.4 Деление на ноль или близкие к нулю значения
Проблема: Несколько мест в scanner.py


steam_spread_pct = (steam_spread / steam_lowest_sell) * 100  # линия 255
instant_profit_pct = (instant_profit / steam_buy_order) * 100  # линия 316
Баг: Нет проверки на деление на ноль

Исправление: Добавить проверку > 0 перед делением

4.5 Отсутствие комплексной валидации
Проблема: Нет единой функции валидации данных

Исправление: Создать функцию validate_item_data() которая проверит:

Все критические поля != None
Все цены > 0
steam_buy_order < steam_lowest_sell
Разумность соотношений цен (не отличаются в 100 раз)
5. ОТОБРАЖЕНИЕ В GUI
5.1 Таблица выгодных предметов (gui.py:1973-2204)
Колонки:

Предмет - название (market_hash_name)
Steam Buy - текущая заявка на покупку на Steam (steam_buy_order)
CSGO Sell - цена на CSGO.TM (csgo_buy_order)
Профит % - лучший из instant/wait профита
Рек. цена - рекомендуемая цена покупки (recommended_buy_order)
Обновлено - timestamp последнего обновления
Действия - кнопки обновить/удалить
5.2 Текущие обработчики кликов
Клик на	Действие	Код
Название предмета	Открытие Steam страницы	gui.py:2087-2102
CSGO Sell	Открытие CSGO.TM страницы	gui.py:2113-2126
Профит % заголовок	Сортировка по профиту	gui.py:2043-2054
Кнопка 🔄	Обновление данных предмета	gui.py:2159-2172
Кнопка ❌	Удаление предмета	gui.py:2175-2180
ПРОБЛЕМА: Клик на название открывает Steam, но лучше перенести на клик по "Steam Buy"

ПЛАН ИСПРАВЛЕНИЙ
Задача 1: Исправление проблем с фейк профитом
1.1 Добавить комплексную валидацию данных
Файл: src/bottm/analysis/scanner.py
Добавить новую функцию после линии 90:


def validate_item_data(
    steam_buy_order: Optional[float],
    steam_lowest_sell: Optional[float],
    csgo_price: float,
    csgo_buy_order: float,
    steam_history_avg: Optional[float]
) -> tuple[bool, str]:
    """
    Валидация данных предмета на корректность.
    Возвращает (is_valid, error_message).
    """
    # Проверка 1: Все критические поля должны быть заполнены
    if steam_buy_order is None:
        return False, "Missing steam_buy_order"
    if steam_lowest_sell is None:
        return False, "Missing steam_lowest_sell"

    # Проверка 2: Все цены должны быть > 0
    if steam_buy_order <= 0:
        return False, f"Invalid steam_buy_order: {steam_buy_order}"
    if steam_lowest_sell <= 0:
        return False, f"Invalid steam_lowest_sell: {steam_lowest_sell}"
    if csgo_price <= 0:
        return False, f"Invalid csgo_price: {csgo_price}"
    if csgo_buy_order <= 0:
        return False, f"Invalid csgo_buy_order: {csgo_buy_order}"

    # Проверка 3: buy_order ДОЛЖЕН быть меньше lowest_sell (иначе фейк профит)
    if steam_buy_order >= steam_lowest_sell:
        return False, f"Fake profit: buy_order ({steam_buy_order:.0f}) >= lowest_sell ({steam_lowest_sell:.0f})"

    # Проверка 4: Цены должны быть в разумных пределах (не отличаются в 100 раз)
    if steam_buy_order / steam_lowest_sell < 0.01 or steam_buy_order / steam_lowest_sell > 0.99:
        return False, f"Unrealistic spread: {steam_buy_order:.0f} vs {steam_lowest_sell:.0f}"

    # Проверка 5: Валидация конвертации валют (если есть история)
    if steam_history_avg and steam_history_avg > 0:
        usd_to_currency = steam_buy_order / steam_history_avg
        if usd_to_currency < 0.5 or usd_to_currency > 2.0:
            return False, f"Unrealistic currency conversion: {usd_to_currency:.2f}"

    return True, ""
1.2 Использовать валидацию в analyze_item()
Файл: src/bottm/analysis/scanner.py
После получения всех данных Steam (после линии 232), добавить:


# Комплексная валидация данных
is_valid, error_msg = validate_item_data(
    steam_buy_order=steam_buy_order,
    steam_lowest_sell=steam_lowest_sell,
    csgo_price=price_data.price,
    csgo_buy_order=price_data.buy_order,
    steam_history_avg=steam_history.avg_price if steam_history else None
)

if not is_valid:
    logger.warning(f"  ❌ Invalid data: {error_msg}")
    return None
1.3 Удалить старую проверку на фейк профит (линии 237-246)
Причина: Новая валидация уже включает эту проверку

1.4 Добавить проверку перед делением
Файл: src/bottm/analysis/scanner.py
Линия 255 заменить:


# Старый код:
steam_spread_pct = (steam_spread / steam_lowest_sell) * 100

# Новый код:
steam_spread_pct = None
if steam_lowest_sell and steam_lowest_sell > 0:
    steam_spread_pct = (steam_spread / steam_lowest_sell) * 100
1.5 Добавить timestamp кэша
Файл: src/bottm/api/csgo_market.py
Добавить поле в класс CSGOMarketAPI (после линии 98):


self._prices_cache_timestamp: Optional[float] = None
self.CACHE_TTL_SECONDS = 600  # 10 минут
Обновить load_prices_with_buy_orders() (после линии 208):


# Проверка кэша с учетом времени
import time
current_time = time.time()

if self._prices_cache and not force_reload:
    if self._prices_cache_timestamp:
        cache_age = current_time - self._prices_cache_timestamp
        if cache_age < self.CACHE_TTL_SECONDS:
            logger.info(f"Using cached prices (age: {cache_age:.0f}s)")
            return self._prices_cache
        else:
            logger.info(f"Cache expired (age: {cache_age:.0f}s), reloading...")

# После загрузки данных, обновить timestamp
self._prices_cache_timestamp = current_time
Задача 2: Перенести открытие Steam страницы с клика на предмет на клик по "Steam Buy"
2.1 Изменить обработчик клика на название предмета
Файл: gui.py
Линия 2093-2102 заменить:


# Старый код (открывает Steam):
item_btn = ctk.CTkButton(
    row,
    text=market_hash_name[:50] + "..." if len(market_hash_name) > 50 else market_hash_name,
    command=open_steam,  # ← было открытие Steam
    fg_color="transparent",
    hover_color=("gray70", "gray30"),
    anchor="w",
    font=ctk.CTkFont(size=13)
)

# Новый код (без клика или с копированием названия):
item_label = ctk.CTkLabel(
    row,
    text=market_hash_name[:50] + "..." if len(market_hash_name) > 50 else market_hash_name,
    anchor="w",
    font=ctk.CTkFont(size=13)
)
item_label.grid(row=0, column=0, padx=8, pady=6, sticky="ew")
Альтернатива: Оставить кнопку, но изменить действие на копирование названия в буфер обмена

2.2 Добавить обработчик клика на "Steam Buy" колонку
Файл: gui.py
Линия 2105-2110 заменить:


# Старый код (без клика):
steam_label = ctk.CTkLabel(
    row,
    text=f"{item.get('steam_buy_order', 0):.2f} ₽",
    font=ctk.CTkFont(size=13)
)

# Новый код (с кликом на Steam):
def open_steam(name=market_hash_name):
    import webbrowser
    encoded_name = name.replace(' ', '%20').replace('|', '%7C')
    webbrowser.open(f"https://steamcommunity.com/market/listings/730/{encoded_name}")

steam_btn = ctk.CTkButton(
    row,
    text=f"{item.get('steam_buy_order', 0):.2f} ₽",
    command=open_steam,  # ← теперь Steam Buy открывает Steam
    fg_color="transparent",
    hover_color=("gray70", "gray30"),
    font=ctk.CTkFont(size=13)
)
steam_btn.grid(row=0, column=1, padx=8, pady=6, sticky="ew")
2.3 Обновить комментарии в коде
Добавить комментарии:


# Колонка 0: Название предмета (только отображение)
# Колонка 1: Steam Buy цена (клик открывает Steam Market)
# Колонка 2: CSGO Sell цена (клик открывает CSGO.TM)
КРИТИЧЕСКИЕ ФАЙЛЫ ДЛЯ МОДИФИКАЦИИ
src/bottm/analysis/scanner.py (основная логика анализа)

Добавить функцию validate_item_data()
Использовать валидацию в analyze_item()
Добавить проверки перед делением на ноль
src/bottm/api/csgo_market.py (CSGO.TM API)

Добавить timestamp кэша
Обновить логику проверки кэша
gui.py (интерфейс)

Изменить обработчик клика на название предмета
Добавить обработчик клика на "Steam Buy"
ВЕРИФИКАЦИЯ ИЗМЕНЕНИЙ
Тест 1: Проверка валидации на фейк профит

Входные данные:
  steam_buy_order = 1000
  steam_lowest_sell = 950

Ожидаемый результат:
  ❌ validate_item_data() должна вернуть (False, "Fake profit: ...")
  ❌ Предмет НЕ должен попасть в список выгодных
Тест 2: Проверка устаревшего кэша

Действия:
  1. Запустить сканер
  2. Подождать 11 минут (> CACHE_TTL_SECONDS)
  3. Запустить сканер снова

Ожидаемый результат:
  ✅ Данные должны перезагрузиться из API
  ✅ В логе: "Cache expired (age: 660s), reloading..."
Тест 3: Проверка клика на Steam Buy

Действия:
  1. Найти выгодный предмет в списке
  2. Кликнуть на "Steam Buy" колонку

Ожидаемый результат:
  ✅ Открывается браузер со страницей Steam Market предмета
Тест 4: Проверка клика на название предмета

Действия:
  1. Кликнуть на название предмета

Ожидаемый результат:
  ✅ Ничего не происходит (или копируется в буфер, если выбран этот вариант)
  ❌ НЕ открывается браузер
ДОПОЛНИТЕЛЬНЫЕ РЕКОМЕНДАЦИИ
Логирование аномалий: Добавить детальное логирование всех случаев отклонения предметов
Метрики: Считать статистику: сколько предметов отклонено по каждой причине
UI индикация: Показывать причину отклонения предмета в GUI (если пользователь хочет видеть)
Тестирование: Написать unit-тесты для validate_item_data() с граничными случаями
ИТОГО
Основные проблемы:

❌ Отсутствие комплексной валидации данных
❌ Устаревшие данные в кэше без timestamp
❌ Некорректная обработка None значений
❌ Отсутствие проверок перед делением на ноль
❌ Некорректная конвертация валют без sanity-check
Решения:

✅ Добавить функцию validate_item_data() с 5 проверками
✅ Добавить timestamp кэша с TTL 10 минут
✅ Добавить проверки на None перед использованием
✅ Добавить проверки > 0 перед делением
✅ Добавить sanity-check на коэффициент конвертации
UI изменения:

✅ Перенести открытие Steam с клика на название на клик по "Steam Buy"
✅ Название предмета остается только для отображения