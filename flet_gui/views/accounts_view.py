"""
Accounts view showing all trading accounts.

Optimized version:
- Removed duplicate handler functions (100+ lines saved)
- All blocking operations run via page.run_task() to prevent GUI freezing
- Handlers moved to module level for reusability
"""

import flet as ft
import asyncio

from flet_gui.theme.colors import COLORS, FONT_SIZES, RADIUS
from flet_gui.state.app_state import AppState


# ============================================================================
# HANDLER FACTORIES (module-level to avoid duplication)
# ============================================================================

def create_toggle_handler(account_service, state, acc_name, page=None):
    """Create toggle handler for specific account."""
    async def handler(e):
        try:
            new_value = e.control.value
            # Update account enabled status
            for acc in state.accounts:
                if acc.name == acc_name:
                    acc.enabled = new_value
                    break

            state.add_log(f"[INFO] Account {acc_name} {'enabled' if new_value else 'disabled'}")

            # Save to account service (run in thread pool to avoid blocking)
            if account_service:
                success = await asyncio.to_thread(
                    account_service.set_account_enabled, acc_name, new_value
                )
                if success:
                    state.add_log(f"[SUCCESS] Account state saved to accounts.json")
                else:
                    state.add_log(f"[ERROR] Failed to save account state")

            if page:
                page.update()

        except Exception as ex:
            state.add_log(f"[ERROR] Failed to toggle account: {str(ex)}")
    return handler


def create_login_handler(account_service, state, acc_name, refresh_callback, page=None):
    """Create async login handler for specific account."""
    async def handler(e):
        if not account_service:
            state.add_log("[ERROR] Account service not available")
            return

        state.add_log(f"[INFO] Logging in {acc_name}...")

        # Disable button to show loading state
        if hasattr(e, 'control') and e.control:
            e.control.disabled = True
            e.control.text = "Logging in..."
            if page:
                page.update()

        try:
            # Use async login method to avoid blocking GUI
            success = await account_service.login_account_async(acc_name)
            if success:
                refresh_callback()
            if page:
                page.update()
        except Exception as ex:
            state.add_log(f"[ERROR] Login failed: {str(ex)}")
        finally:
            # Re-enable button
            if hasattr(e, 'control') and e.control:
                e.control.disabled = False
                e.control.text = "Login"
                if page:
                    page.update()
    return handler


def create_logout_handler(account_service, state, acc_name, refresh_callback, page=None):
    """Create async logout handler for specific account."""
    async def handler(e):
        if not account_service:
            state.add_log("[ERROR] Account service not available")
            return

        state.add_log(f"[INFO] Logging out {acc_name}...")
        try:
            # Logout is usually fast, but run in thread to be safe
            await asyncio.to_thread(account_service.logout_account, acc_name)
            refresh_callback()
            if page:
                page.update()
        except Exception as ex:
            state.add_log(f"[ERROR] Logout failed: {str(ex)}")
    return handler


def create_detect_currency_handler(account_service, state, acc_name, refresh_callback, page=None):
    """Create async detect currency handler for specific account."""
    async def handler(e):
        if not account_service:
            state.add_log("[ERROR] Account service not available")
            return

        state.add_log(f"[INFO] Detecting currency for {acc_name}...")

        # Disable button to show loading
        if hasattr(e, 'control') and e.control:
            e.control.disabled = True
            if page:
                page.update()

        try:
            # Run blocking operation in thread pool
            currency = await asyncio.to_thread(
                account_service.detect_currency, acc_name
            )

            if currency:
                state.add_log(f"[SUCCESS] Detected currency for {acc_name}: {currency}")
                refresh_callback()
            else:
                state.add_log(f"[WARNING] Could not detect currency for {acc_name}")

        except Exception as ex:
            state.add_log(f"[ERROR] Currency detection failed: {str(ex)}")
        finally:
            if hasattr(e, 'control') and e.control:
                e.control.disabled = False
                if page:
                    page.update()
    return handler


# ============================================================================
# ACCOUNT CARD BUILDER
# ============================================================================

def build_account_card(account, account_service, state, refresh_callback, page=None):
    """Build a single account card with all controls."""
    status_color = COLORS["status_online"] if account.logged_in else COLORS["status_offline"]
    status_text = "Online" if account.logged_in else "Offline"

    # Create handlers using factory functions
    toggle_handler = create_toggle_handler(account_service, state, account.name, page)
    login_handler = create_login_handler(account_service, state, account.name, refresh_callback, page)
    logout_handler = create_logout_handler(account_service, state, account.name, refresh_callback, page)
    currency_handler = create_detect_currency_handler(account_service, state, account.name, refresh_callback, page)

    return ft.Container(
        content=ft.Column(
            [
                # Header row with name and status
                ft.Row(
                    [
                        ft.Text(
                            account.name,
                            size=FONT_SIZES["lg"],
                            weight=ft.FontWeight.BOLD,
                            color=COLORS["text_primary"],
                        ),
                        ft.Container(
                            content=ft.Text(
                                status_text,
                                size=FONT_SIZES["xs"],
                                color=status_color,
                            ),
                            bgcolor=f"{status_color}20",
                            border_radius=12,
                            padding=ft.padding.symmetric(horizontal=8, vertical=4),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                # Balance info row
                ft.Row(
                    [
                        ft.Text(
                            f"Currency: {account.currency}",
                            size=FONT_SIZES["sm"],
                            color=COLORS["text_secondary"]
                        ),
                        ft.Text(
                            f"Steam: {account.steam_balance:,.2f} {account.currency}",
                            size=FONT_SIZES["sm"],
                            color=COLORS["accent_blue"]
                        ),
                        ft.Text(
                            f"TM: {account.csgotm_balance:,.2f} RUB",
                            size=FONT_SIZES["sm"],
                            color=COLORS["accent_purple"]
                        ),
                        ft.Text(
                            f"Hold: {account.csgotm_settlement:,.2f} RUB",
                            size=FONT_SIZES["sm"],
                            color=COLORS["accent_yellow"]
                        ),
                    ],
                    spacing=16,
                    wrap=True,
                ),
                # Enable/disable switch
                ft.Row([
                    ft.Switch(
                        value=account.enabled,
                        active_color=COLORS["accent_purple"],
                        on_change=toggle_handler,
                    ),
                    ft.Text(
                        "Enabled" if account.enabled else "Disabled",
                        size=FONT_SIZES["sm"],
                        color=COLORS["text_primary"],
                    ),
                ], spacing=8),
                # Action buttons
                ft.Row(
                    [
                        ft.FilledButton(
                            "Login" if not account.logged_in else "Logout",
                            icon=ft.Icons.LOGIN if not account.logged_in else ft.Icons.LOGOUT,
                            on_click=login_handler if not account.logged_in else logout_handler,
                            style=ft.ButtonStyle(
                                bgcolor=COLORS["accent_purple"] if not account.logged_in else COLORS["accent_red"],
                                color=COLORS["text_primary"],
                            ),
                        ),
                        ft.FilledButton(
                            "Detect Currency",
                            icon=ft.Icons.CURRENCY_EXCHANGE,
                            on_click=currency_handler,
                            style=ft.ButtonStyle(
                                bgcolor=COLORS["accent_blue"],
                                color=COLORS["text_primary"],
                            ),
                            disabled=not account.logged_in,
                        ),
                    ],
                    spacing=12,
                ),
            ],
            spacing=12,
        ),
        bgcolor=COLORS["bg_surface"],
        border=ft.border.all(1, COLORS["border"]),
        border_radius=RADIUS["lg"],
        padding=16,
    )


# ============================================================================
# MAIN VIEW
# ============================================================================

def create_accounts_view(account_service=None, page=None) -> ft.Container:
    """
    Create accounts view showing:
    - List of accounts with status
    - Balance information
    - Currency detection
    - Enable/disable toggles

    All blocking operations run asynchronously to prevent GUI freezing.
    """
    state = AppState()

    # Refs for dynamic updates
    accounts_column_ref = ft.Ref[ft.Column]()

    def refresh_accounts():
        """Refresh account cards display."""
        account_cards = [
            build_account_card(account, account_service, state, refresh_accounts, page)
            for account in state.accounts
        ]

        # Update accounts column
        if accounts_column_ref.current:
            accounts_column_ref.current.controls = account_cards

        if page:
            page.update()

    async def login_all_handler(e):
        """Login all enabled accounts in parallel (non-blocking)."""
        if not account_service:
            state.add_log("[ERROR] Account service not available")
            return

        # Disable button to show loading
        if hasattr(e, 'control') and e.control:
            e.control.disabled = True
            e.control.text = "Logging in..."
            if page:
                page.update()

        state.add_log("[INFO] Logging in all enabled accounts in parallel...")
        try:
            # Run blocking operation in thread pool
            results = await asyncio.to_thread(account_service.login_all_accounts)

            # Refresh the view to show updated status
            refresh_accounts()

            if page:
                page.update()

        except Exception as ex:
            state.add_log(f"[ERROR] Login all failed: {str(ex)}")
        finally:
            if hasattr(e, 'control') and e.control:
                e.control.disabled = False
                e.control.text = "Login All"
                if page:
                    page.update()

    # Initial account cards
    account_cards = [
        build_account_card(account, account_service, state, refresh_accounts, page)
        for account in state.accounts
    ]

    return ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(
                            "Accounts",
                            size=FONT_SIZES["2xl"],
                            weight=ft.FontWeight.BOLD,
                            color=COLORS["text_primary"],
                        ),
                        ft.Row([
                            ft.FilledButton(
                                "Login All",
                                icon=ft.Icons.LOGIN,
                                on_click=login_all_handler,
                                style=ft.ButtonStyle(
                                    bgcolor=COLORS["accent_blue"],
                                    color=COLORS["text_primary"],
                                ),
                                disabled=not account_service,
                            ),
                            ft.FilledButton(
                                "Add Account",
                                icon=ft.Icons.ADD,
                                style=ft.ButtonStyle(
                                    bgcolor=COLORS["accent_purple"],
                                    color=COLORS["text_primary"],
                                ),
                                disabled=True,  # Not implemented yet
                            ),
                        ], spacing=12),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Column(
                    ref=accounts_column_ref,
                    controls=account_cards,
                    spacing=16,
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                ),
            ],
            spacing=16,
            expand=True,
        ),
        padding=24,
        expand=True,
    )


AccountsView = create_accounts_view
