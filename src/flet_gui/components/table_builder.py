"""
TableBuilder - unified table component for consistent UI across views.

This component reduces code duplication in:
- history_view.py
- orders_view.py
- inventory_view.py
- tm_parser_view.py
"""

import flet as ft
from typing import List, Dict, Any, Callable, Optional
from dataclasses import dataclass

from flet_gui.theme.colors import COLORS, FONT_SIZES


@dataclass
class TableColumn:
    """Definition of a table column."""
    key: str                    # Key in data dict
    header: str                 # Header text
    width: int = 150            # Column width
    align: str = "left"         # left, center, right
    format_fn: Optional[Callable] = None  # Custom formatter
    color_fn: Optional[Callable] = None   # Dynamic color based on value


class TableBuilder:
    """
    Unified table builder for consistent data tables across views.

    Usage:
        columns = [
            TableColumn("name", "Item Name", width=200),
            TableColumn("price", "Price", width=100, format_fn=lambda x: f"{x:.2f}₽"),
            TableColumn("profit", "Profit", width=80, color_fn=lambda x: "green" if x > 0 else "red"),
        ]

        table = TableBuilder(columns)
        header = table.build_header()
        rows = table.build_rows(data_list)
    """

    def __init__(self, columns: List[TableColumn]):
        """Initialize table builder with column definitions."""
        self.columns = columns

    def build_header(self) -> ft.Container:
        """Build table header row."""
        header_controls = []

        for col in self.columns:
            alignment = ft.MainAxisAlignment.START
            if col.align == "center":
                alignment = ft.MainAxisAlignment.CENTER
            elif col.align == "right":
                alignment = ft.MainAxisAlignment.END

            header_controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text(
                                col.header,
                                size=FONT_SIZES.get("sm", 13),
                                weight=ft.FontWeight.BOLD,
                                color=COLORS.get("text_secondary", "#888888"),
                            )
                        ],
                        alignment=alignment,
                    ),
                    width=col.width,
                    padding=ft.padding.symmetric(horizontal=8),
                )
            )

        return ft.Container(
            content=ft.Row(
                controls=header_controls,
                spacing=0,
            ),
            padding=ft.padding.symmetric(horizontal=16, vertical=12),
            bgcolor=COLORS.get("bg_elevated", "#1a1a2e"),
            border=ft.border.only(bottom=ft.BorderSide(2, COLORS.get("border", "#333355"))),
        )

    def build_row(self, data: Dict[str, Any], index: int = 0, on_click: Callable = None) -> ft.Container:
        """Build a single table row."""
        row_controls = []

        for col in self.columns:
            value = data.get(col.key, "")

            # Apply formatter if provided
            if col.format_fn and value is not None:
                try:
                    display_value = col.format_fn(value)
                except:
                    display_value = str(value)
            else:
                display_value = str(value) if value is not None else ""

            # Determine text color
            text_color = COLORS.get("text_primary", "#ffffff")
            if col.color_fn and value is not None:
                try:
                    text_color = col.color_fn(value)
                except:
                    pass

            alignment = ft.MainAxisAlignment.START
            if col.align == "center":
                alignment = ft.MainAxisAlignment.CENTER
            elif col.align == "right":
                alignment = ft.MainAxisAlignment.END

            row_controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text(
                                display_value,
                                size=FONT_SIZES.get("sm", 13),
                                color=text_color,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            )
                        ],
                        alignment=alignment,
                    ),
                    width=col.width,
                    padding=ft.padding.symmetric(horizontal=8),
                )
            )

        # Alternate row background
        bg_color = COLORS.get("bg_surface", "#16162a") if index % 2 == 0 else COLORS.get("bg_elevated", "#1a1a2e")

        return ft.Container(
            content=ft.Row(
                controls=row_controls,
                spacing=0,
            ),
            padding=ft.padding.symmetric(horizontal=16, vertical=10),
            bgcolor=bg_color,
            border=ft.border.only(bottom=ft.BorderSide(1, COLORS.get("border", "#333355"))),
            on_click=on_click,
            ink=True if on_click else False,
        )

    def build_rows(self, data_list: List[Dict[str, Any]], on_row_click: Callable = None) -> List[ft.Container]:
        """Build all table rows from data list."""
        rows = []
        for i, data in enumerate(data_list):
            click_handler = None
            if on_row_click:
                # Create closure to capture current data
                click_handler = lambda e, d=data: on_row_click(d)

            rows.append(self.build_row(data, index=i, on_click=click_handler))
        return rows

    def build_empty_state(self, message: str = "No data") -> ft.Container:
        """Build empty state placeholder."""
        return ft.Container(
            content=ft.Column(
                [
                    ft.Icon(
                        ft.Icons.INBOX_OUTLINED,
                        size=48,
                        color=COLORS.get("text_tertiary", "#555555"),
                    ),
                    ft.Text(
                        message,
                        size=FONT_SIZES.get("md", 14),
                        color=COLORS.get("text_tertiary", "#555555"),
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=12,
            ),
            padding=40,
            alignment=ft.alignment.center,
        )


# ============================================================================
# COMMON FORMATTERS
# ============================================================================

def format_price(value, currency: str = "₽") -> str:
    """Format price with currency."""
    if value is None:
        return "-"
    try:
        return f"{float(value):,.2f}{currency}"
    except:
        return str(value)


def format_percent(value) -> str:
    """Format percentage value."""
    if value is None:
        return "-"
    try:
        return f"{float(value):+.1f}%"
    except:
        return str(value)


def format_date(value) -> str:
    """Format datetime value."""
    if value is None:
        return "-"
    try:
        if isinstance(value, str):
            from datetime import datetime
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.strftime("%d.%m.%Y %H:%M")
        return str(value)
    except:
        return str(value)


def format_hours(value) -> str:
    """Format hours remaining."""
    if value is None:
        return "-"
    try:
        hours = int(value)
        if hours <= 0:
            return "Ready"
        elif hours < 24:
            return f"{hours}h"
        else:
            days = hours // 24
            remaining_hours = hours % 24
            return f"{days}d {remaining_hours}h"
    except:
        return str(value)


# ============================================================================
# COLOR FUNCTIONS
# ============================================================================

def color_profit(value) -> str:
    """Color based on profit value (positive=green, negative=red)."""
    try:
        if float(value) > 0:
            return COLORS.get("accent_green", "#4ade80")
        elif float(value) < 0:
            return COLORS.get("accent_red", "#f87171")
        else:
            return COLORS.get("text_primary", "#ffffff")
    except:
        return COLORS.get("text_primary", "#ffffff")


def color_status(value) -> str:
    """Color based on status value."""
    status_colors = {
        "active": COLORS.get("accent_green", "#4ade80"),
        "pending": COLORS.get("accent_yellow", "#fbbf24"),
        "cancelled": COLORS.get("accent_red", "#f87171"),
        "filled": COLORS.get("accent_blue", "#60a5fa"),
        "sold": COLORS.get("accent_purple", "#a78bfa"),
        "holding": COLORS.get("accent_yellow", "#fbbf24"),
        "listed": COLORS.get("accent_blue", "#60a5fa"),
    }
    return status_colors.get(str(value).lower(), COLORS.get("text_primary", "#ffffff"))
