"""Semantic color themes for curses based plugins."""
from __future__ import annotations

import curses
from collections.abc import Mapping

THEME_IDS = ("terminal", "herdr-dark", "midnight", "paper")
DEFAULT_THEME = "terminal"

_ROLES = (
    "selected", "active_cursor", "pane_border", "pane_title", "comment", "muted",
    "footer", "success", "error", "heading", "code", "code_comment", "code_frame",
    "quote", "rule", "bullet", "table", "record", "marker",
)

def normalize_theme(theme: str | None) -> str:
    """Return a supported theme ID, using terminal defaults for unknown values."""
    return theme if theme in THEME_IDS else DEFAULT_THEME

def _palette(curses_module, theme: str, color_count: int) -> dict[str, tuple[int, int]]:
    c = curses_module
    if theme == "terminal":
        return {role: (-1, -1) for role in _ROLES}
    if color_count < 8:
        fg, bg = c.COLOR_WHITE, -1
        values = {role: (fg, bg) for role in _ROLES}
        values.update(selected=(c.COLOR_WHITE, c.COLOR_BLUE), footer=(c.COLOR_WHITE, c.COLOR_BLUE),
                      heading=(c.COLOR_CYAN, -1), error=(c.COLOR_RED, -1), success=(c.COLOR_GREEN, -1))
        return values
    if color_count >= 256:
        values = {
            "selected": (250, 24), "active_cursor": (255, 25), "pane_border": (39, -1),
            "pane_title": (255, 24), "comment": (c.COLOR_YELLOW, -1), "muted": (c.COLOR_BLUE, -1),
            "footer": (c.COLOR_WHITE, c.COLOR_BLUE), "success": (c.COLOR_GREEN, -1),
            "error": (c.COLOR_RED, -1), "heading": (c.COLOR_CYAN, -1), "code": (252, 236),
            "code_comment": (245, 236), "code_frame": (245, -1), "quote": (c.COLOR_MAGENTA, -1),
            "rule": (c.COLOR_BLUE, -1), "bullet": (c.COLOR_WHITE, -1), "table": (c.COLOR_WHITE, -1),
            "record": (c.COLOR_WHITE, -1), "marker": (c.COLOR_GREEN, -1),
        }
    else:
        values = {
            "selected": (c.COLOR_WHITE, c.COLOR_BLUE), "active_cursor": (c.COLOR_BLACK, c.COLOR_WHITE),
            "pane_border": (c.COLOR_CYAN, -1), "pane_title": (c.COLOR_WHITE, c.COLOR_BLUE),
            "comment": (c.COLOR_YELLOW, -1), "muted": (c.COLOR_BLUE, -1),
            "footer": (c.COLOR_WHITE, c.COLOR_BLUE), "success": (c.COLOR_GREEN, -1),
            "error": (c.COLOR_RED, -1), "heading": (c.COLOR_CYAN, -1),
            "code": (c.COLOR_WHITE, c.COLOR_BLACK), "code_comment": (c.COLOR_CYAN, c.COLOR_BLACK),
            "code_frame": (c.COLOR_BLUE, -1), "quote": (c.COLOR_MAGENTA, -1), "rule": (c.COLOR_BLUE, -1),
            "bullet": (c.COLOR_WHITE, -1), "table": (c.COLOR_WHITE, -1), "record": (c.COLOR_WHITE, -1),
            "marker": (c.COLOR_GREEN, -1),
        }
    if theme == "midnight":
        values.update(selected=(c.COLOR_WHITE, c.COLOR_MAGENTA), pane_border=(c.COLOR_MAGENTA, -1),
                      pane_title=(c.COLOR_WHITE, c.COLOR_MAGENTA), heading=(c.COLOR_MAGENTA, -1), footer=(c.COLOR_WHITE, c.COLOR_MAGENTA))
    elif theme == "paper":
        values.update(selected=(c.COLOR_BLACK, c.COLOR_CYAN), pane_border=(c.COLOR_BLUE, -1),
                      pane_title=(c.COLOR_BLACK, c.COLOR_CYAN), muted=(c.COLOR_BLACK, -1),
                      code=(c.COLOR_BLACK, c.COLOR_WHITE), code_comment=(c.COLOR_BLUE, c.COLOR_WHITE),
                      footer=(c.COLOR_BLACK, c.COLOR_CYAN))
    return values

def initialize_colors(curses_module=curses, extra_pairs: Mapping[str, tuple[int, int]] | None = None,
                      theme: str | None = "herdr-dark") -> dict[str, int]:
    """Initialize semantic styles for a supported named theme and local roles."""
    if not curses_module.has_colors():
        return {}
    curses_module.start_color()
    try:
        curses_module.use_default_colors()
    except curses_module.error:
        pass
    theme = normalize_theme(theme)
    pairs = _palette(curses_module, theme, getattr(curses_module, "COLORS", 0))
    pairs.update(extra_pairs or {})
    styles: dict[str, int] = {}
    for number, (name, colors) in enumerate(pairs.items(), 1):
        try:
            curses_module.init_pair(number, *colors)
            styles[name] = curses_module.color_pair(number)
        except curses_module.error:
            continue
    return styles
