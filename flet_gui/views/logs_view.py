"""
Logs view - properly fixed with full height terminal.
"""

import flet as ft
from flet_gui.theme.colors import COLORS, FONT_SIZES, RADIUS
from flet_gui.state.app_state import AppState


def create_logs_view(page=None) -> ft.Container:
    """Logs view with full-height terminal."""
    state = AppState()

    # Refs for dynamic updates
    log_column_ref = ft.Ref[ft.Column]()
    log_count_ref = ft.Ref[ft.Text]()

    # Track auto-scroll state - by default auto-scroll is ON
    auto_scroll_enabled = [True]  # Use list to avoid closure issues
    last_log_count = [0]  # Track if logs changed

    def on_scroll(e):
        """Disable auto-scroll when user manually scrolls."""
        # When user scrolls manually, disable auto-scroll
        # This prevents forcing user to bottom when they're reading old logs
        auto_scroll_enabled[0] = False

    def refresh_logs():
        """Refresh log display."""
        logs = state.logs
        current_count = len(logs)

        # Update log count
        if log_count_ref.current:
            log_count_ref.current.value = f"{current_count} lines (max 1000)"

        # Combine all logs into one selectable text
        if logs:
            logs_text = "\n".join(logs)
        else:
            logs_text = "No logs yet"

        # Update log column with single text element
        if log_column_ref.current:
            log_column_ref.current.controls = [
                ft.Text(
                    logs_text,
                    size=11,
                    color=COLORS["text_secondary"],
                    font_family="monospace",
                    selectable=True,
                    no_wrap=False,
                )
            ]

            # Auto-scroll only if:
            # 1. Auto-scroll is enabled (user hasn't manually scrolled)
            # 2. Logs have been updated (new logs added)
            if auto_scroll_enabled[0] and current_count > last_log_count[0]:
                log_column_ref.current.auto_scroll = True
            else:
                log_column_ref.current.auto_scroll = False

            # Update last log count
            last_log_count[0] = current_count

        if page:
            page.update()

    def on_clear_logs(e):
        """Handle clear logs button click."""
        state.clear_logs()
        refresh_logs()

    def on_scroll_to_bottom(e):
        """Re-enable auto-scroll and scroll to bottom."""
        auto_scroll_enabled[0] = True
        if log_column_ref.current:
            log_column_ref.current.auto_scroll = True
        if page:
            page.update()


    # Subscribe to state changes for auto-refresh
    state.subscribe('logs', refresh_logs)

    logs = state.logs

    # Combine all logs into one selectable text
    if logs:
        logs_text = "\n".join(logs)
    else:
        logs_text = "No logs yet"

    # Create single text element for all logs
    log_entries = [
        ft.Text(
            logs_text,
            size=11,
            color=COLORS["text_secondary"],
            font_family="monospace",
            selectable=True,
            no_wrap=False,
        )
    ]

    # Terminal container with full width
    terminal = ft.Container(
        content=ft.Column(
            ref=log_column_ref,
            controls=log_entries,
            spacing=1,
            scroll=ft.ScrollMode.ALWAYS,
            auto_scroll=True,
            horizontal_alignment=ft.CrossAxisAlignment.START,
            expand=True,
            on_scroll=on_scroll,  # Detect user scroll
        ),
        bgcolor=COLORS["bg_primary"],
        border=ft.border.all(1, COLORS["border"]),
        border_radius=8,
        padding=12,
        expand=True,
        width=float("inf"),  # Force full width
    )

    return ft.Container(
        content=ft.Column(
            controls=[
                # Header
                ft.Row(
                    controls=[
                        ft.Text("Logs", size=24, weight=ft.FontWeight.BOLD),
                        ft.Row([
                            ft.FilledButton(
                                "Scroll to Bottom",
                                icon=ft.Icons.ARROW_DOWNWARD,
                                on_click=on_scroll_to_bottom,
                            ),
                            ft.FilledButton(
                                "Clear",
                                icon=ft.Icons.DELETE_OUTLINE,
                                on_click=on_clear_logs,
                            ),
                        ], spacing=8),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                # Log count
                ft.Text(
                    ref=log_count_ref,
                    value=f"{len(logs)} lines (max 1000)",
                    size=12,
                    color=COLORS["text_tertiary"],
                ),
                # Terminal (fills remaining space)
                terminal,
            ],
            spacing=12,
            expand=True,  # KEY: column expands
        ),
        padding=20,
        expand=True,  # KEY: container expands
    )


LogsView = create_logs_view
