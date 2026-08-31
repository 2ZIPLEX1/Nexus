"""
Main navigation component - sidebar with NavigationRail.
"""

import flet as ft
from typing import Callable

from flet_gui.theme.colors import COLORS


def create_navigation(on_change: Callable[[int], None]) -> ft.Container:
    """
    Create sidebar navigation using NavigationRail.

    Provides navigation between the 10 main views:
    - Dashboard
    - Accounts
    - Orders
    - Inventory
    - TM Parser
    - TM Sales
    - History
    - Statistics
    - Settings
    - Logs

    Args:
        on_change: Callback when tab changes, receives tab index
    """

    def handle_change(e):
        """Handle navigation change."""
        on_change(e.control.selected_index)

    return ft.Container(
        content=ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=80,
            min_extended_width=180,
            bgcolor=COLORS["bg_surface"],
            indicator_color=COLORS["accent_purple"],
            destinations=[
                ft.NavigationRailDestination(
                    icon=ft.Icons.DASHBOARD_OUTLINED,
                    selected_icon=ft.Icons.DASHBOARD,
                    label="Dashboard",
                    padding=ft.padding.symmetric(vertical=2),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.PERSON_OUTLINE,
                    selected_icon=ft.Icons.PERSON,
                    label="Accounts",
                    padding=ft.padding.symmetric(vertical=2),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.LIST_ALT_OUTLINED,
                    selected_icon=ft.Icons.LIST_ALT,
                    label="Orders",
                    padding=ft.padding.symmetric(vertical=2),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.INVENTORY_2_OUTLINED,
                    selected_icon=ft.Icons.INVENTORY_2,
                    label="Inventory",
                    padding=ft.padding.symmetric(vertical=2),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.SEARCH_OUTLINED,
                    selected_icon=ft.Icons.SEARCH,
                    label="TM Parser",
                    padding=ft.padding.symmetric(vertical=2),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.SELL_OUTLINED,
                    selected_icon=ft.Icons.SELL,
                    label="TM Sales",
                    padding=ft.padding.symmetric(vertical=2),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.SHOPPING_BAG_OUTLINED,
                    selected_icon=ft.Icons.SHOPPING_BAG,
                    label="Auto Buy",
                    padding=ft.padding.symmetric(vertical=2),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.HISTORY_OUTLINED,
                    selected_icon=ft.Icons.HISTORY,
                    label="History",
                    padding=ft.padding.symmetric(vertical=2),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.BAR_CHART_OUTLINED,
                    selected_icon=ft.Icons.BAR_CHART,
                    label="Statistics",
                    padding=ft.padding.symmetric(vertical=2),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    selected_icon=ft.Icons.SETTINGS,
                    label="Settings",
                    padding=ft.padding.symmetric(vertical=2),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.TERMINAL_OUTLINED,
                    selected_icon=ft.Icons.TERMINAL,
                    label="Logs",
                    padding=ft.padding.symmetric(vertical=2),
                ),
            ],
            on_change=handle_change,
        ),
        border=ft.border.only(right=ft.BorderSide(1, COLORS["border"])),
    )


# Alias for backward compatibility
MainNavigation = create_navigation
