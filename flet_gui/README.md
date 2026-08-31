# Steam Trading Bot - Flet GUI

Современный GUI для Steam Trading Bot, построенный на Flet (Flutter for Python).

## 🎨 Дизайн

- **Стиль**: Cyberpunk Professional - тёмный, элегантный, с высоким контрастом
- **Цветовая палитра**:
  - Фон: Deep Dark (#0f0f12)
  - Поверхности/Карточки: Lighter Dark (#1e1e24)
  - Акценты: Purple (#8b5cf6) для основных действий, Lime (#d4f658) для успеха
  - Текст: Чистая иерархия белый/серый

## ⚡ Преимущества

### Производительность
- ✅ **Нет уничтожения виджетов** - обновление через прямые свойства вместо destroy/recreate
- ✅ **Неблокирующий UI** - все тяжёлые операции через `page.run_task()`
- ✅ **Реактивное состояние** - Observer pattern для автоматических обновлений UI
- ✅ **Готово к виртуализации** - архитектура поддерживает ленивый рендеринг для списков 1000+ элементов

### Архитектура
- ✅ **Чистое разделение** - UI не запрашивает данные синхронно, только наблюдает за изменениями
- ✅ **Централизованное состояние** - Singleton `AppState` с observer pattern
- ✅ **Event Bus** - Для межкомпонентной коммуникации
- ✅ **Сервисный слой** - Чистая граница между UI и бизнес-логикой

## 📁 Структура проекта

```
flet_gui/
├── main.py                 # Точка входа
├── state/
│   ├── app_state.py        # Централизованное состояние (Singleton + Observer)
│   └── events.py           # Event bus для событий
├── views/
│   ├── dashboard_view.py   # Карточки статистики, недавние сделки
│   ├── accounts_view.py    # Карточки аккаунтов с балансом
│   ├── orders_view.py      # Таблица ордеров
│   ├── inventory_view.py   # Предметы на удержании
│   ├── tm_parser_view.py   # Прибыльные предметы, контроллы сканирования
│   ├── history_view.py     # История транзакций
│   ├── settings_view.py    # Настройки бота
│   └── logs_view.py        # Терминал логов (макс 1000 строк)
├── components/
│   ├── navigation.py       # NavigationRail боковая панель
│   ├── header.py           # Хедер с Start/Stop/Refresh
│   ├── status_bar.py       # Нижняя статус-панель
│   └── stat_card.py        # Карточка статистики
├── services/
│   └── mocks.py            # Mock сервисы для тестирования UI
└── theme/
    └── colors.py           # Цветовая палитра и стили
```

## 🚀 Установка и запуск

### 1. Установите Flet

```bash
pip install flet
```

### 2. Запустите GUI

```bash
python -m flet_gui.main
```

Или из корня проекта:

```bash
cd "c:\git projects\tm-steambot"
python -m flet_gui.main
```

## 🎯 Текущий статус (Phase 1 - Foundation)

### ✅ Реализовано
- [x] Структура проекта
- [x] Цветовая тема (Cyberpunk Professional)
- [x] Централизованное состояние (AppState с Observer pattern)
- [x] Event Bus
- [x] Компоненты навигации, хедера, статус-бара
- [x] Dashboard view с mock данными
- [x] Все 8 placeholder views (Accounts, Orders, Inventory, TM Parser, History, Settings, Logs)
- [x] Mock сервисы для тестирования

### 🔜 Следующие шаги (Phase 2-7)

#### Phase 2: Простые views
- [ ] Settings view с формой для bot_config.json
- [ ] Logs view с reactive обновлениями
- [ ] Улучшить Accounts view

#### Phase 3: Таблицы с данными
- [ ] Виртуализированный DataTable компонент
- [ ] Orders view с сортировкой/фильтрацией
- [ ] Inventory view с отслеживанием цен
- [ ] History view с фильтрами

#### Phase 4: Интеграция с backend
- [ ] Database service (обёртка для trades_db)
- [ ] Account service (обёртка для AccountManager)
- [ ] Trading service (обёртка для TradingBot)
- [ ] Scanner service (обёртка для AutoScanner)
- [ ] Замена mock данных на реальные

#### Phase 5: Расширенная функциональность
- [ ] Start/Stop бота (реальная интеграция)
- [ ] Auto-scanner интеграция
- [ ] Уведомления и toast сообщения
- [ ] Экспорт данных

## 🧪 Тестирование

GUI работает с mock данными для быстрого тестирования визуальной части и производительности без необходимости настройки Steam/CSGO.TM API.

### Mock данные включают:
- 3 аккаунта (2 онлайн, 1 оффлайн)
- 50 активных ордеров
- 15 предметов на удержании
- 10 прибыльных предметов из сканера
- 10 недавних продаж
- 50 записей истории
- Примеры логов

Для подключения реального backend смотрите раздел "Phase 4: Интеграция с backend".

## 💡 Ключевые паттерны

### 1. Reactive State Updates
```python
# UI подписывается на изменения
state = AppState()
state.subscribe('active_orders', lambda: update_ui())

# Обновление данных автоматически триггерит UI
state.active_orders = new_orders  # UI обновится
```

### 2. Функциональные компоненты
```python
def create_stat_card(title, value, icon) -> ft.Container:
    # Создаёт компонент без классов и состояния
    return ft.Container(...)

# Использование
card = create_stat_card("Balance", "12,500 RUB", ft.Icons.WALLET)
```

### 3. Неблокирующие операции
```python
async def heavy_operation():
    # Тяжёлая работа не блокирует UI
    data = await fetch_from_api()
    state.data = data

# Запуск в фоне
page.run_task(heavy_operation)
```

## 📝 Сравнение с старым GUI

| Аспект | Старый (CustomTkinter) | Новый (Flet) |
|--------|------------------------|--------------|
| **Обновление списков** | Destroy + recreate виджетов | Обновление свойств |
| **Производительность** | Лаги при 100+ элементах | Плавно с 1000+ элементами |
| **Архитектура** | Монолитная, UI + логика | MVC, чистое разделение |
| **Состояние** | Распределённое по классам | Централизованное (Singleton) |
| **Async** | Threads с блокировками | Native async/await |
| **Стиль** | Стандартный тёмный | Cyberpunk Professional |

## 🎨 Цвета и стили

Все цвета и стили определены в `theme/colors.py`:

```python
COLORS = {
    "bg_primary": "#0f0f12",      # Основной фон
    "bg_surface": "#1e1e24",      # Карточки
    "accent_purple": "#8b5cf6",   # Основной акцент
    "accent_lime": "#d4f658",     # Успех/прибыль
    "text_primary": "#ffffff",    # Основной текст
    # ... и другие
}
```

## 🐛 Известные ограничения

1. **Reactive updates**: Пока views не обновляются автоматически при изменении state. Нужно использовать кнопку Refresh.
2. **Mock данные**: Симулированный bot cycle не обновляет реальные данные.
3. **Виртуализация**: Пока не реализована для больших списков (будет в Phase 3).

## 📚 Дополнительные ресурсы

- [Flet Documentation](https://flet.dev/)
- [Design Plan](C:\Users\marv1n\.claude\plans\greedy-wandering-sonnet.md)
- [Original GUI](../gui.py) - 4023 строки CustomTkinter кода для миграции

---

**Примечание**: Это начальная версия (Phase 1). Большая часть функциональности будет добавлена в следующих фазах по мере интеграции с реальным backend.
