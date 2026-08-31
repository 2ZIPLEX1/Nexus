"""
Stat card component for dashboard metrics.
"""

import flet as ft
from typing import Callable, Optional

from flet_gui.theme.colors import COLORS, FONT_SIZES, RADIUS


def create_stat_card(
    title: str,
    value: str,
    icon: str,
    icon_color: str = None,
    subtitle: str = None,
    subtitle_color: str = None,
    on_click: Callable[[], None] = None,
) -> ft.Container:
    """
    Create a card displaying a single statistic with:
    - Icon
    - Title (label)
    - Value (main number)
    - Optional subtitle/change indicator

    Args:
        title: Label text (e.g., "Steam Balance")
        value: Main value text (e.g., "12,500 RUB")
        icon: Flet icon name
        icon_color: Icon color (defaults to accent_purple)
        subtitle: Optional subtitle text
        subtitle_color: Subtitle color (for profit/loss indication)
        on_click: Optional click handler
    """
    icon_col = icon_color or COLORS["accent_purple"]
    sub_col = subtitle_color or COLORS["text_secondary"]

    content = ft.Column(
        [
            # Icon and title row
            ft.Row(
                [
                    ft.Container(
                        content=ft.Icon(
                            icon,
                            color=icon_col,
                            size=20,
                        ),
                        bgcolor=f"{icon_col}20",  # 20% opacity
                        border_radius=8,
                        padding=8,
                    ),
                    ft.Text(
                        title,
                        size=FONT_SIZES["sm"],
                        color=COLORS["text_secondary"],
                    ),
                ],
                spacing=10,
            ),

            # Value
            ft.Text(
                value,
                size=FONT_SIZES["2xl"],
                weight=ft.FontWeight.BOLD,
                color=COLORS["text_primary"],
            ),

            # Subtitle (optional)
            ft.Text(
                subtitle or "",
                size=FONT_SIZES["xs"],
                color=sub_col,
                visible=bool(subtitle),
            ),
        ],
        spacing=8,
    )

    return ft.Container(
        content=content,
        padding=16,
        border_radius=RADIUS["lg"],
        bgcolor=COLORS["bg_surface"],
        border=ft.border.all(1, COLORS["border"]),
        on_click=lambda _: on_click() if on_click else None,
        ink=True if on_click else False,
    )


# Alias for backward compatibility
StatCard = create_stat_card
