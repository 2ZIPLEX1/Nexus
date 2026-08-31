"""
Application header component with title and control buttons.
"""

import flet as ft
from typing import Callable

from flet_gui.theme.colors import COLORS, FONT_SIZES
from flet_gui.state.app_state import AppState


def create_header(
    on_start: Callable[[], None],
    on_stop: Callable[[], None],
    on_refresh: Callable[[], None],
    on_sync: Callable[[], None] = None,
    page=None,
) -> ft.Container:
    """
    Create top header bar with:
    - Application title and logo
    - Bot status indicator
    - Start/Stop/Refresh/Sync buttons

    Args:
        on_start: Callback when Start button clicked
        on_stop: Callback when Stop button clicked
        on_refresh: Callback when Refresh button clicked
        on_sync: Callback when Sync button clicked
        page: Flet page for updates
    """
    state = AppState()

    # Refs for dynamic updates
    status_row_ref = ft.Ref[ft.Row]()
    start_button_ref = ft.Ref[ft.FilledButton]()
    stop_button_ref = ft.Ref[ft.FilledButton]()

    def update_status():
        """Update status indicator and buttons based on bot state."""
        is_running = state.bot_state.running

        # Update status row with new icon and text
        if status_row_ref.current:
            status_row_ref.current.controls = [
                ft.Icon(
                    ft.Icons.PLAY_CIRCLE_FILLED if is_running else ft.Icons.PAUSE_CIRCLE_FILLED,
                    color=COLORS["accent_lime"] if is_running else COLORS["text_secondary"],
                    size=18,
                ),
                ft.Text(
                    "Running" if is_running else "Stopped",
                    size=FONT_SIZES["sm"],
                    color=COLORS["accent_lime"] if is_running else COLORS["text_secondary"],
                ),
            ]

        if start_button_ref.current:
            start_button_ref.current.disabled = is_running

        if stop_button_ref.current:
            stop_button_ref.current.disabled = not is_running

        if page:
            page.update()

    def handle_start():
        on_start()
        update_status()

    def handle_stop():
        on_stop()
        update_status()

    is_running = state.bot_state.running

    return ft.Container(
        content=ft.Row(
            [
                # Left side: Logo and title
                ft.Row(
                    [
                        ft.Icon(
                            ft.Icons.SMART_TOY,
                            color=COLORS["accent_purple"],
                            size=28,
                        ),
                        ft.Text(
                            "Steamify",
                            size=FONT_SIZES["xl"],
                            weight=ft.FontWeight.BOLD,
                            color=COLORS["text_primary"],
                        ),
                    ],
                    spacing=12,
                ),

                # Center: Status indicator
                ft.Row(
                    ref=status_row_ref,
                    controls=[
                        ft.Icon(
                            ft.Icons.PLAY_CIRCLE_FILLED if is_running else ft.Icons.PAUSE_CIRCLE_FILLED,
                            color=COLORS["accent_lime"] if is_running else COLORS["text_secondary"],
                            size=18,
                        ),
                        ft.Text(
                            "Running" if is_running else "Stopped",
                            size=FONT_SIZES["sm"],
                            color=COLORS["accent_lime"] if is_running else COLORS["text_secondary"],
                        ),
                    ],
                    spacing=6,
                ),

                # Right side: Control buttons
                ft.Row(
                    [
                        ft.FilledButton(
                            "Start",
                            ref=start_button_ref,
                            icon=ft.Icons.PLAY_ARROW,
                            disabled=is_running,
                            on_click=lambda _: handle_start(),
                        ),
                        ft.FilledButton(
                            "Stop",
                            ref=stop_button_ref,
                            icon=ft.Icons.STOP,
                            disabled=not is_running,
                            on_click=lambda _: handle_stop(),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.SYNC,
                            icon_color=COLORS["accent_cyan"],
                            tooltip="Sync orders from Steam",
                            on_click=lambda _: on_sync() if on_sync else None,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.REFRESH,
                            icon_color=COLORS["accent_blue"],
                            tooltip="Refresh data",
                            on_click=lambda _: on_refresh(),
                        ),
                    ],
                    spacing=8,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        padding=ft.padding.symmetric(horizontal=24, vertical=16),
        bgcolor=COLORS["bg_surface"],
        border=ft.border.only(bottom=ft.BorderSide(1, COLORS["border"])),
    )


# Alias for backward compatibility
AppHeader = create_header
