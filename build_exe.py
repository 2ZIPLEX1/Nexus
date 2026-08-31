"""
Build standalone .exe for Steamify GUI.

Usage:
    1. Install PyInstaller: pip install pyinstaller
    2. Run this script: python build_exe.py
    3. Find the .exe in dist/Steamify/
"""
import os
import subprocess
import sys
import glob
from pathlib import Path

def build_exe():
    """Build the executable using PyInstaller."""

    print("Building Steamify GUI executable...")
    print("=" * 60)

    # Check if PyInstaller is installed
    try:
        import PyInstaller
        print(f"OK PyInstaller {PyInstaller.__version__} found")
    except ImportError:
        print("X PyInstaller not found!")
        print("\nInstalling PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("OK PyInstaller installed")

    project_root = Path(__file__).parent

    # Проверяем наличие иконки
    icon_path = project_root / "icon.ico"
    icon_arg = f"--icon={icon_path}" if icon_path.exists() else None
    if icon_arg:
        print(f"OK Icon found: {icon_path}")
    else:
        print("i No icon.ico found (optional)")

    # PyInstaller command
    # ВНИМАНИЕ: в сборку НЕ кладём ни .env, ни data/ (там cookies сессий Steam),
    # ни accounts.json, ни proxies.txt. PyInstaller не шифрует --add-data:
    # содержимое достаётся из готового билда обычным распаковщиком или `strings`,
    # то есть любой, кому отдали .exe, получал пароли Steam, оба Guard-секрета,
    # ключи API и доступ к прокси. Секреты оператор кладёт рядом с бинарником сам.
    cmd = [
        "pyinstaller",
        "--name=Steamify",
        "--onedir",
        "--windowed",
        "--noconfirm",
        f"--add-data={project_root / 'flet_gui'};flet_gui",
    ]

    # Только шаблон без реальных значений
    env_example = project_root / ".env.example"
    if env_example.exists():
        cmd.append(f"--add-data={env_example};.")
        print(f"OK .env.example file found: {env_example}")

    # Добавляем иконку если есть
    if icon_arg:
        cmd.append(icon_arg)

    # Добавляем icon.ico для runtime (для окна приложения)
    icon_ico = project_root / "icon.ico"
    if icon_ico.exists():
        cmd.append(f"--add-data={icon_ico};.")
        print(f"OK Runtime icon (ICO) found: {icon_ico}")

    # Добавляем icon.png для runtime (на всякий случай)
    icon_png = project_root / "icon.png"
    if icon_png.exists():
        cmd.append(f"--add-data={icon_png};.")
        print(f"OK Runtime icon (PNG) found: {icon_png}")

    # Hidden imports
    cmd.append("--hidden-import=flet")
    cmd.append("--hidden-import=aiosteampy")
    cmd.append("--hidden-import=aiohttp")
    cmd.append("--hidden-import=sqlite3")

    # Entry point
    cmd.append(str(project_root / "flet_gui" / "main.py"))

    print("\nRunning PyInstaller...")
    print(" ".join(cmd))
    print()

    try:
        subprocess.check_call(cmd, cwd=project_root)

        # Копируем дополнительные файлы конфигурации
        import shutil
        dist_dir = project_root / 'dist' / 'Steamify'

        print("\n" + "=" * 60)
        print("Copying configuration files...")

        # accounts.json, proxies.txt, .env и базы из data/ НЕ копируем:
        # это живые учётные данные, и раньше они уезжали вместе с дистрибутивом.
        # Оператор кладёт их рядом с .exe сам, на своей машине.
        example = project_root / ".env.example"
        if example.exists():
            shutil.copy2(example, dist_dir / ".env.example")
            print("OK Copied .env.example (шаблон без секретов)")

        readme = dist_dir / "ПРОЧТИ_МЕНЯ.txt"
        readme.write_text(
            "Перед первым запуском положите рядом с Steamify.exe свои файлы:\n"
            "  .env           — скопируйте из .env.example и заполните\n"
            "  accounts.json  — учётные записи Steam\n"
            "  proxies.txt    — список прокси\n"
            "\n"
            "Эти файлы НЕ входят в сборку намеренно: внутри .exe они не шифруются\n"
            "и извлекаются любым распаковщиком. Никому не передавайте их вместе\n"
            "с программой.\n",
            encoding="utf-8",
        )
        print("OK Created ПРОЧТИ_МЕНЯ.txt")

        print("\n" + "=" * 60)
        print("OK Build completed successfully!")
        print(f"\nExecutable location: {project_root / 'dist' / 'Steamify' / 'Steamify.exe'}")
        print("\nYou can now:")
        print("1. Run the .exe directly")
        print("2. Create a desktop shortcut")
        print("3. Distribute the entire 'dist/Steamify' folder")
    except subprocess.CalledProcessError as e:
        print(f"\nX Build failed: {e}")
        return False

    return True

if __name__ == "__main__":
    build_exe()
