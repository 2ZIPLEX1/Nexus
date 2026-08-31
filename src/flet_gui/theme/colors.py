"""
Color palette for the Steam Trading Bot GUI.

Cyberpunk Professional theme - dark, sleek, high contrast.
"""

# Main color palette
COLORS = {
    # Backgrounds
    "bg_primary": "#0f0f12",      # Deep dark background
    "bg_surface": "#1e1e24",      # Card/surface background
    "bg_elevated": "#2a2a32",     # Elevated elements (hover, selected)
    "bg_input": "#16161a",        # Input field background

    # Accents
    "accent_purple": "#8b5cf6",   # Primary accent (buttons, highlights)
    "accent_purple_hover": "#7c3aed",  # Purple hover state
    "accent_lime": "#d4f658",     # Success/highlights/profit
    "accent_lime_dark": "#a3b53a",  # Lime text on dark
    "accent_red": "#ef4444",      # Error/stop/loss
    "accent_red_hover": "#dc2626",  # Red hover state
    "accent_blue": "#3b82f6",     # Info/links
    "accent_blue_hover": "#2563eb",  # Blue hover state
    "accent_yellow": "#f59e0b",   # Warning/pending
    "accent_cyan": "#06b6d4",     # Secondary accent

    # Text
    "text_primary": "#ffffff",    # Main text
    "text_secondary": "#9ca3af",  # Muted text
    "text_tertiary": "#6b7280",   # Very muted text
    "text_disabled": "#4b5563",   # Disabled text

    # Borders
    "border": "#3f3f46",          # Default border
    "border_light": "#52525b",    # Lighter border
    "border_focus": "#8b5cf6",    # Focus state border

    # Status colors
    "status_online": "#10b981",   # Online/connected
    "status_offline": "#6b7280",  # Offline/disconnected
    "status_busy": "#f59e0b",     # Busy/processing

    # Profit/Loss
    "profit_positive": "#10b981", # Green for profit
    "profit_negative": "#ef4444", # Red for loss
    "profit_neutral": "#9ca3af",  # Gray for neutral
}

# Gradient definitions
GRADIENTS = {
    "purple_glow": "linear-gradient(135deg, #8b5cf6 0%, #6366f1 100%)",
    "success_glow": "linear-gradient(135deg, #10b981 0%, #059669 100%)",
    "danger_glow": "linear-gradient(135deg, #ef4444 0%, #dc2626 100%)",
}

# Shadow definitions
SHADOWS = {
    "sm": "0 1px 2px 0 rgba(0, 0, 0, 0.05)",
    "md": "0 4px 6px -1px rgba(0, 0, 0, 0.1)",
    "lg": "0 10px 15px -3px rgba(0, 0, 0, 0.1)",
    "glow_purple": "0 0 20px rgba(139, 92, 246, 0.3)",
    "glow_lime": "0 0 20px rgba(212, 246, 88, 0.3)",
}

# Typography
FONTS = {
    "family": "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif",
    "mono": "JetBrains Mono, Fira Code, Consolas, monospace",
}

FONT_SIZES = {
    "xs": 11,
    "sm": 13,
    "base": 14,
    "lg": 16,
    "xl": 18,
    "2xl": 22,
    "3xl": 28,
    "4xl": 36,
}

# Spacing
SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "2xl": 32,
}

# Border radius
RADIUS = {
    "sm": 4,
    "md": 8,
    "lg": 12,
    "xl": 16,
    "full": 9999,
}
