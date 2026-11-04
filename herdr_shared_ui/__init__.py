"""Shared terminal UI primitives for Herdr Python curses plugins."""

from __future__ import annotations

import curses
from typing import Mapping

VERSION = "1.0.0"

_SHARED_COLOR_PAIRS_256 = {
    "selected": (250, 24),
    "active_cursor": (255, 25),
    "pane_border": (39, -1),
    "pane_title": (255, 24),
    "comment": (curses.COLOR_YELLOW, -1),
    "muted": (curses.COLOR_BLUE, -1),
    "footer": (curses.COLOR_WHITE, curses.COLOR_BLUE),
    "success": (curses.COLOR_GREEN, -1),
    "error": (curses.COLOR_RED, -1),
    "heading": (curses.COLOR_CYAN, -1),
    "code": (252, 236),
    "code_comment": (245, 236),
    "code_frame": (245, -1),
    "quote": (curses.COLOR_MAGENTA, -1),
    "rule": (curses.COLOR_BLUE, -1),
    "bullet": (curses.COLOR_WHITE, -1),
    "table": (curses.COLOR_WHITE, -1),
    "record": (curses.COLOR_WHITE, -1),
    "marker": (curses.COLOR_GREEN, -1),
}

_SHARED_COLOR_PAIRS_BASIC = {
    "selected": (curses.COLOR_WHITE, curses.COLOR_BLUE),
    "active_cursor": (curses.COLOR_BLACK, curses.COLOR_WHITE),
    "pane_border": (curses.COLOR_CYAN, -1),
    "pane_title": (curses.COLOR_WHITE, curses.COLOR_BLUE),
    "comment": (curses.COLOR_YELLOW, -1),
    "muted": (curses.COLOR_BLUE, -1),
    "footer": (curses.COLOR_WHITE, curses.COLOR_BLUE),
    "success": (curses.COLOR_GREEN, -1),
    "error": (curses.COLOR_RED, -1),
    "heading": (curses.COLOR_CYAN, -1),
    "code": (curses.COLOR_WHITE, curses.COLOR_BLACK),
    "code_comment": (curses.COLOR_CYAN, curses.COLOR_BLACK),
    "code_frame": (curses.COLOR_BLUE, -1),
    "quote": (curses.COLOR_MAGENTA, -1),
    "rule": (curses.COLOR_BLUE, -1),
    "bullet": (curses.COLOR_WHITE, -1),
    "table": (curses.COLOR_WHITE, -1),
    "record": (curses.COLOR_WHITE, -1),
    "marker": (curses.COLOR_GREEN, -1),
}


def initialize_colors(
    curses_module=curses,
    extra_pairs: Mapping[str, tuple[int, int]] | None = None,
) -> dict[str, int]:
    """Initialize the shared semantic palette and optional plugin-specific pairs."""
    if not curses_module.has_colors():
        return {}

    curses_module.start_color()
    try:
        curses_module.use_default_colors()
    except curses_module.error:
        pass

    color_count = getattr(curses_module, "COLORS", 0)
    pairs = dict(_SHARED_COLOR_PAIRS_256 if color_count >= 256 else _SHARED_COLOR_PAIRS_BASIC)
    pairs.update(extra_pairs or {})

    styles: dict[str, int] = {}
    for number, (name, colors) in enumerate(pairs.items(), 1):
        try:
            curses_module.init_pair(number, *colors)
            styles[name] = curses_module.color_pair(number)
        except curses_module.error:
            continue
    return styles


def safe_addnstr(screen, y: int, x: int, text: str, width: int, attr: int = 0) -> None:
    """Write text while safely containing curses edge-cell errors."""
    if width <= 0:
        return
    try:
        screen.addnstr(y, x, text, width, attr)
    except curses.error:
        pass


def draw_heavy_frame(screen, attr: int = 0) -> None:
    """Draw the shared heavy terminal border."""
    height, width = screen.getmaxyx()
    if height < 2 or width < 2:
        return
    horizontal = "━" * (width - 2)
    safe_addnstr(screen, 0, 0, f"┏{horizontal}┓", width, attr)
    for y in range(1, height - 1):
        safe_addnstr(screen, y, 0, "┃", 1, attr)
        safe_addnstr(screen, y, width - 1, "┃", 1, attr)
    safe_addnstr(screen, height - 1, 0, f"┗{horizontal}┛", width, attr)


def fill_row(screen, y: int, x: int, width: int, attr: int) -> None:
    """Fill a row region, including cells where no text is present."""
    if width > 0:
        safe_addnstr(screen, y, x, " " * width, width, attr)


def draw_title_bar(
    screen,
    left_text: str,
    attr: int,
    right_text: str = "",
) -> None:
    """Draw a filled title bar with a left title and optional right label."""
    _height, width = screen.getmaxyx()
    inner_width = max(0, width - 2)
    fill_row(screen, 0, 1, inner_width, attr)
    left_room = inner_width
    if right_text:
        right_width = len(right_text)
        left_room = max(0, inner_width - right_width - 2)
    safe_addnstr(screen, 0, 2, left_text, max(0, left_room - 2), attr)
    if right_text and inner_width >= len(right_text) + 8:
        safe_addnstr(screen, 0, width - len(right_text) - 2, right_text, len(right_text), attr)


def __getattr__(name: str):
    """Keep the package version available to simple plugin-side pin checks."""
    if name == "__version__":
        return VERSION
    raise AttributeError(name)
