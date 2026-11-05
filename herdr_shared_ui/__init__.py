"""Composable terminal UI primitives for Python curses plugins."""
from __future__ import annotations

import curses

from .themes import DEFAULT_THEME, THEME_IDS, initialize_colors, normalize_theme

VERSION = "1.1.2"

def safe_addnstr(screen, y: int, x: int, text: str, width: int, attr: int = 0) -> None:
    """Write text while containing curses edge-cell errors."""
    if width <= 0:
        return
    try:
        screen.addnstr(y, x, text, width, attr)
    except curses.error:
        pass

def draw_heavy_frame(screen, attr: int = 0) -> None:
    """Draw a heavy terminal border."""
    height, width = screen.getmaxyx()
    if height < 2 or width < 2:
        return
    safe_addnstr(screen, 0, 0, f"┏{'━' * (width - 2)}┓", width, attr)
    for y in range(1, height - 1):
        safe_addnstr(screen, y, 0, "┃", 1, attr)
        safe_addnstr(screen, y, width - 1, "┃", 1, attr)
    safe_addnstr(screen, height - 1, 0, f"┗{'━' * (width - 2)}┛", width, attr)

def fill_row(screen, y: int, x: int, width: int, attr: int) -> None:
    """Fill a row region, including blank cells."""
    if width > 0:
        safe_addnstr(screen, y, x, " " * width, width, attr)

def draw_title_bar(screen, left_text: str, attr: int, right_text: str = "") -> None:
    """Draw a filled title bar with an optional right label."""
    _height, width = screen.getmaxyx()
    inner_width = max(0, width - 2)
    fill_row(screen, 0, 1, inner_width, attr)
    left_room = max(0, inner_width - len(right_text) - 2) if right_text else inner_width
    safe_addnstr(screen, 0, 2, left_text, max(0, left_room - 2), attr)
    if right_text and inner_width >= len(right_text) + 8:
        safe_addnstr(screen, 0, width - len(right_text) - 2, right_text, len(right_text), attr)

def __getattr__(name: str):
    if name == "__version__":
        return VERSION
    raise AttributeError(name)
