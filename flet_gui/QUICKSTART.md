# 🚀 Quick Start - Flet GUI

## Запуск GUI

```bash
cd "c:\git projects\tm-steambot"
python -m flet_gui.main
```

Или используйте упрощённую версию (если есть проблемы):

```bash
python -m flet_gui.main_simple
```

## ✅ Что увидите

1. **Окно приложения** откроется автоматически
2. **Боковая навигация** слева с 8 иконками:
   - 📊 Dashboard
   - 👤 Accounts
   - 📋 Orders
   - 📦 Inventory
   - 🔍 TM Parser
   - 📜 History
   - ⚙️ Settings
   - 📝 Logs

3. **Dashboard** с 6 карточками статистики (mock данные):
   - Steam Balance: 12,586 RUB
   - CSGO.TM Balance: 10,400 RUB
   - Active Orders: 47
   - Items on Hold: 12
   - Total Profit: 15,420 RUB
   - Sold Items: 156

4. **Цветовая схема**:
   - Фиолетовый (#8b5cf6) - основной акцент
   - Лаймовый (#d4f658) - успех/прибыль
   - Тёмный фон (#0f0f12)

## 🎮 Что можно делать

- ✅ Переключаться между вкладками (клик по иконкам слева)
- ✅ Смотреть Dashboard со статистикой
- ✅ Смотреть Accounts (3 mock аккаунта)
- ✅ Смотреть TM Parser (10 прибыльных предметов)
- ✅ Смотреть Logs (цветные логи)
- ✅ Кнопки Start/Stop (пока симуляция)
- ✅ Кнопка Refresh (обновить данные)

## 📝 Mock данные

GUI работает с тестовыми данными:
- 3 аккаунта (MainAccount, SecondAccount, TestAccount)
- 50 активных ордеров
- 15 предметов на удержании
- 10 прибыльных предметов
- 10 недавних продаж
- Логи

## ⚠️ Известные предупреждения

При запуске может показать:
```
DeprecationWarning: app() is deprecated since version 0.70.0
```

Это нормально, GUI всё равно работает. Это просто предупреждение о том, что метод `app()` устарел в новой версии Flet.

## 🐛 Если не запускается

1. Проверьте, что Flet установлен:
   ```bash
   pip install flet
   ```

2. Используйте упрощённую версию:
   ```bash
   python -m flet_gui.main_simple
   ```

3. Проверьте версию Python (нужен 3.10+):
   ```bash
   python --version
   ```

## 📚 Дополнительно

- [README.md](README.md) - полная документация
- [main.py](main.py) - основной файл
- [main_simple.py](main_simple.py) - упрощённая версия

---

**Совет**: Запустите и просто покликайте по иконкам слева - увидите все views! 🎨
