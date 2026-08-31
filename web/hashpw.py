"""
web/hashpw.py — генератор WEB_API_PASSWORD_HASH для веб-панели.

    python -m web.hashpw

Пароль вводится скрыто (getpass) и НЕ печатается на экран и НЕ попадает в
историю оболочки — поэтому не передавайте его аргументом командной строки.
"""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from web.auth import hash_password  # noqa: E402

MIN_LENGTH = 12


def main() -> int:
    print("Генерация хеша пароля для веб-панели.\n")
    try:
        password = getpass.getpass("Пароль: ")
        confirm = getpass.getpass("Ещё раз: ")
    except (KeyboardInterrupt, EOFError):
        print("\nОтменено.")
        return 1

    if password != confirm:
        print("Пароли не совпадают.", file=sys.stderr)
        return 1
    if len(password) < MIN_LENGTH:
        print(
            f"Пароль короче {MIN_LENGTH} символов. Панель управляет реальными "
            "деньгами и доступна из интернета — возьмите длиннее.",
            file=sys.stderr,
        )
        return 1

    digest = hash_password(password)
    print("\nГотово. Добавьте в окружение сервиса:\n")
    print(f"WEB_API_PASSWORD_HASH={digest}\n")
    print("Например, в /etc/tm-steambot/web.env (chmod 600, владелец botuser).")
    print("Сам пароль нигде не сохраняется — запомните его.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
