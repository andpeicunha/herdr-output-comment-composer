"""Small keyboard-first curses controls with plugin-owned actions."""
from __future__ import annotations

import curses
from dataclasses import dataclass
from collections.abc import Callable, Sequence

@dataclass(frozen=True)
class Button:
    label: str
    action: str

class ButtonBar:
    """Focusable button list; callers own the meaning of returned actions."""
    def __init__(self, buttons: Sequence[Button], focused: int = 0):
        self.buttons = tuple(buttons)
        self.focused = max(0, min(focused, len(self.buttons) - 1)) if self.buttons else 0

    def handle_key(self, key) -> str | None:
        if not self.buttons:
            return None
        if key in ("\t", curses.KEY_RIGHT, curses.KEY_DOWN):
            self.focused = (self.focused + 1) % len(self.buttons)
        elif key in (curses.KEY_LEFT, curses.KEY_UP):
            self.focused = (self.focused - 1) % len(self.buttons)
        elif key in ("\n", "\r", " ", curses.KEY_ENTER):
            return self.buttons[self.focused].action
        return None

    def draw(self, window, y: int, x: int, attr: int = 0, focused_attr: int = 0) -> None:
        from . import safe_addnstr
        cursor = x
        for index, button in enumerate(self.buttons):
            label = f"[ {button.label} ]"
            safe_addnstr(window, y, cursor, label, len(label), focused_attr if index == self.focused else attr)
            cursor += len(label) + 2

class Modal:
    """Generic modal action dispatcher; policy and confirmation stay with caller."""
    def __init__(self, buttons: Sequence[Button], handlers: dict[str, Callable[[], object]]):
        self.buttons = ButtonBar(buttons)
        self.handlers = handlers

    def handle_key(self, key):
        action = self.buttons.handle_key(key)
        return self.handlers[action]() if action is not None and action in self.handlers else None

    def draw_buttons(self, window, y: int, x: int, attr: int = 0, focused_attr: int = 0) -> None:
        self.buttons.draw(window, y, x, attr, focused_attr)
