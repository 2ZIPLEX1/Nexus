"""
Скрипт для очистки дублированных записей в sold_items.

Удаляет дубликаты продаж, оставляя только самую новую запись для каждого предмета.
"""

import sqlite3
from pathlib import Path

def cleanup_duplicate_sales():
    """Удалить дубликаты из таблицы sold_items."""

    # Путь к базе данных
    db_path = Path("data/my_trades.db")

    if not db_path.exists():
        print(f"База данных не найдена: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Находим дубликаты (одинаковые предметы, независимо от даты)
        cursor.execute("""
            SELECT
                account_name,
                item_name,
                COUNT(*) as count
            FROM sold_items
            GROUP BY account_name, item_name
            HAVING count > 1
        """)

        duplicates = cursor.fetchall()

        if not duplicates:
            print("✅ Дубликаты не найдены!")
            return

        print(f"⚠️  Найдено {len(duplicates)} предметов с дубликатами:")

        total_deleted = 0

        for account_name, item_name, count in duplicates:
            print(f"\n📦 {item_name[:50]}")
            print(f"   Аккаунт: {account_name}")
            print(f"   Всего записей: {count}")

            # Получаем все записи этого предмета, сортируем по дате (новые первые)
            cursor.execute("""
                SELECT id, purchase_price, sale_price, profit, sale_date
                FROM sold_items
                WHERE account_name = ? AND item_name = ?
                ORDER BY sale_date DESC, id DESC
            """, (account_name, item_name))

            items = cursor.fetchall()

            # Оставляем первую запись (самую новую), удаляем остальные
            keep_id = items[0][0]
            keep_date = items[0][4]
            ids_to_delete = [item[0] for item in items[1:]]

            print(f"   ✅ Оставляем: ID {keep_id}, дата {keep_date}, profit: {items[0][3]:.2f}₽")
            print(f"   ❌ Удаляем: {len(ids_to_delete)} записей")

            for idx, item in enumerate(items[1:], 1):
                print(f"      {idx}. ID {item[0]}, дата {item[4]}, profit: {item[3]:.2f}₽")

            # Удаляем дубликаты
            for item_id in ids_to_delete:
                cursor.execute("DELETE FROM sold_items WHERE id = ?", (item_id,))
                total_deleted += 1

        conn.commit()

        print(f"\n✅ Очистка завершена!")
        print(f"   Удалено записей: {total_deleted}")

        # Показываем статистику после очистки
        cursor.execute("SELECT COUNT(*) FROM sold_items")
        total_sales = cursor.fetchone()[0]
        print(f"   Осталось записей: {total_sales}")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        conn.rollback()

    finally:
        conn.close()


if __name__ == "__main__":
    print("🧹 Очистка дубликатов продаж...\n")
    cleanup_duplicate_sales()
