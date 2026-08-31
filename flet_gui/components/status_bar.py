"""
Bottom status bar component.
"""

import flet as ft
from datetime import datetime

from flet_gui.theme.colors import COLORS, FONT_SIZES
from flet_gui.state.app_state import AppState


def create_status_bar() -> ft.Container:
    """
    Create bottom status bar showing:
    - Version info
    - Connected accounts count
    - Current time
    """
    state = AppState()
    logged_in = sum(1 for acc in state.accounts if acc.logged_in)
    total = len(state.accounts)

    return ft.Container(
        content=ft.Row(
            [
                # Left: Version
                ft.Text(
                    "v1.0.0",
                    size=FONT_SIZES["xs"],
                    color=COLORS["text_tertiary"],
                ),

                # Center: Connection status
                ft.Row(
                    [
                        ft.Icon(
                            ft.Icons.CIRCLE,
                            size=8,
                            color=COLORS["status_online"] if logged_in > 0 else COLORS["status_offline"],
                        ),
                        ft.Text(
                            f"Accounts: {logged_in}/{total} online",
                            size=FONT_SIZES["xs"],
                            color=COLORS["text_secondary"],
                        ),
                    ],
                    spacing=6,
                ),

                # Right: Current time
                ft.Text(
                    datetime.now().strftime("%H:%M:%S"),
                    size=FONT_SIZES["xs"],
                    color=COLORS["text_tertiary"],
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        padding=ft.padding.symmetric(horizontal=24, vertical=8),
        bgcolor=COLORS["bg_surface"],
        border=ft.border.only(top=ft.BorderSide(1, COLORS["border"])),
    )


# Alias for backward compatibility
StatusBar = create_status_bar
