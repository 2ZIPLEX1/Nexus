# Layout Fixes - 21.01.2026

## Исправленные проблемы

### 1. ✅ Dashboard - карточки не помещаются
**Было:** Карточки в одну строку с `wrap=True` - выходили за границы
**Стало:** 2 ряда по 3 карточки в `Column` с `Row` внутри

```python
ft.Column([
    ft.Row([card1, card2, card3], spacing=12),
    ft.Row([card4, card5, card6], spacing=12),
], spacing=12)
```

### 2. ✅ TM Parser - таблица не на всю высоту
**Было:** Контейнер таблицы без `expand=True`
**Стало:** Добавлен `expand=True` к контейнеру

```python
ft.Container(
    content=ft.Column([table], scroll=ft.ScrollMode.AUTO),
    expand=True,  # ← ключевое исправление
)
```

### 3. ✅ Logs - терминал не на всю высоту
**Было:** Контейнер логов без `expand=True`
**Стало:** Добавлен `expand=True` к контейнеру

```python
ft.Container(
    content=ft.Column(log_entries, scroll=ft.ScrollMode.AUTO),
    expand=True,  # ← ключевое исправление
)
```

## Общий паттерн для full-height views

Для любого view, который должен занимать всю доступную высоту:

```python
ft.Container(
    content=ft.Column(
        [
            # Header (фиксированный)
            ft.Row([title, buttons]),
            
            # Content (растягивается)
            ft.Container(
                content=ft.Column([...], scroll=ft.ScrollMode.AUTO),
                expand=True,  # ← главное!
            ),
        ],
        spacing=12,
        expand=True,  # ← и здесь
    ),
    padding=20,
    expand=True,  # ← и здесь
)
```

## Тестирование

Запустите GUI и проверьте:
```bash
python -m flet_gui.main
```

1. Dashboard - все 6 карточек видны в 2 ряда
2. TM Parser - таблица занимает всю высоту окна
3. Logs - терминал занимает всю высоту окна

## Размеры текста

Уменьшены для компактности:
- Dashboard cards: размер текста → 11-13px
- TM Parser table: размер текста → 11px  
- Logs: размер текста → 11px

Всё теперь умещается и скроллится правильно! ✅
