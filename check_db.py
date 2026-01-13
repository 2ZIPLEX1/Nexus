"""
Проверка базы данных bottm.db и отображение статистики.
"""

from pathlib import Path
from src.bottm_parser import bottm_parser
from src.logger import get_logger

logger = get_logger(__name__)

def check_database():
    """Проверить базу данных bottm.db и показать статистику."""

    print("\n" + "="*60)
    print("🔍 Проверка базы данных bottm.db")
    print("="*60 + "\n")

    # Проверяем существование файла
    db_path = Path("data/main.db")

    if not db_path.exists():
        print(f"❌ Файл не найден: {db_path.absolute()}")
        print("\n📝 Что нужно сделать:")
        print("1. Скопируйте вашу базу bottm.db в папку data:")
        print("   copy C:\\путь\\к\\bottm.db data\\main.db")
        print("\n2. Или укажите правильный путь в настройках GUI")
        return

    print(f"✅ Файл найден: {db_path.absolute()}")
    print(f"📦 Размер: {db_path.stat().st_size / 1024:.2f} KB\n")

    # Читаем предметы
    try:
        items = bottm_parser.get_all_items()

        if not items:
            print("⚠️ База данных пуста или таблица 'profitable_items' не существует")
            print("\n📝 Убедитесь что:")
            print("1. Это правильная база данных bottm")
            print("2. В базе есть таблица 'profitable_items'")
            print("3. База актуальна и содержит данные")
            return

        print(f"📊 Всего предметов в базе: {len(items)}")

        # Статистика по профиту
        profit_ranges = {
            "> 20%": 0,
            "10-20%": 0,
            "5-10%": 0,
            "0-5%": 0,
            "< 0%": 0
        }

        total_steam_price = 0
        total_csgo_price = 0

        for item in items:
            # Получаем профит
            profit = item.net_profit_pct

            if profit > 20:
                profit_ranges["> 20%"] += 1
            elif profit > 10:
                profit_ranges["10-20%"] += 1
            elif profit > 5:
                profit_ranges["5-10%"] += 1
            elif profit > 0:
                profit_ranges["0-5%"] += 1
            else:
                profit_ranges["< 0%"] += 1

            if item.recommended_buy_order:
                total_steam_price += item.recommended_buy_order
            if item.csgo_price:
                total_csgo_price += item.csgo_price

        print("\n📈 Распределение по профиту:")
        for range_name, count in profit_ranges.items():
            percentage = (count / len(items) * 100) if items else 0
            bar = "█" * int(percentage / 2)
            print(f"  {range_name:>8}: {count:>5} ({percentage:>5.1f}%) {bar}")

        print(f"\n💰 Средняя цена Steam: {total_steam_price / len(items):.2f} RUB")
        print(f"💎 Средняя цена CSGO.TM: {total_csgo_price / len(items):.2f} RUB")

        # Примеры топовых предметов
        print("\n🔝 Топ 10 самых прибыльных предметов:")
        sorted_items = sorted(items, key=lambda x: x.net_profit_pct, reverse=True)[:10]

        for i, item in enumerate(sorted_items, 1):
            print(f"  {i:2}. {item.market_hash_name[:50]:50} | "
                  f"Steam: {item.recommended_buy_order:>7.2f} | "
                  f"CSGO: {item.csgo_price:>7.2f} | "
                  f"Profit: {item.net_profit_pct:>6.1f}%")

        # Проверяем фильтры
        print("\n🔍 Проверка фильтров бота:")

        # Загружаем настройки
        import json
        config_path = Path("bot_config.json")
        if config_path.exists():
            with open(config_path) as f:
                bot_config = json.load(f)
                min_profit = bot_config.get('min_profit_pct', 5.0)
        else:
            min_profit = 5.0

        print(f"  Минимальный профит: {min_profit}%")

        # Фильтруем по профиту
        filtered = [item for item in items if item.is_profitable(min_profit_pct=min_profit)]
        print(f"  Предметов после фильтра по профиту: {len(filtered)}")

        if len(filtered) == 0:
            print("\n⚠️ ВНИМАНИЕ: После применения фильтров не осталось предметов!")
            print(f"  Попробуйте снизить минимальный профит (сейчас {min_profit}%)")
            print(f"  Или проверьте что база данных содержит актуальные данные")

        print("\n" + "="*60)
        print("✅ Проверка завершена")
        print("="*60 + "\n")

    except Exception as e:
        print(f"\n❌ Ошибка при чтении базы данных: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_database()
