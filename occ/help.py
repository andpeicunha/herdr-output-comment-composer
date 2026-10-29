"""Keyboard shortcuts of the composer and the pure layout of the help modal."""
from __future__ import annotations

import textwrap

# (section title, [(keys, what they do)])
Section = tuple[str, list[tuple[str, str]]]

COMPOSER_HELP: list[Section] = [
    (
        "Move",
        [
            ("↑ ↓ / k j", "previous / next block"),
            ("⇧↑ ⇧↓", "page up / down"),
            ("u d / PgUp PgDn", "half a page up / down"),
            ("g G", "first / last block"),
        ],
    ),
    (
        "Select and copy",
        [
            ("Space", "start / finish a selection of several blocks"),
            ("y", "copy the selection (or the block) and end the selection"),
        ],
    ),
    (
        "Comments",
        [
            ("c", "write or edit the comment on this block"),
            ("s", "send all comments to the agent"),
        ],
    ),
    (
        "While writing a comment",
        [
            ("Ctrl+S", "save and close the box"),
            ("Tab / Shift+Tab", "save and go to the next / previous block"),
            ("Enter", "new line"),
            ("Ctrl+U", "clear the current line"),
            ("Esc", "cancel (asks first when you changed it)"),
        ],
    ),
    (
        "Other",
        [
            ("q", "close (asks first when comments are not sent)"),
            ("Esc", "end the selection; with none, close"),
            ("?", "show this list"),
        ],
    ),
]


def help_layout(sections: list[Section], width: int) -> tuple[list[tuple[str, str, str]], int]:
    """Rows of the help modal and the text indent, for a modal ``width`` columns wide.

    Each row is ``(kind, keys, text)``: kind is "section", "key", or "blank". Keys and
    their text share a row when the keys fit in half of the width; otherwise the text
    goes on the rows below the keys, so no key is ever cut.
    """
    width = max(10, width)
    longest = max((len(keys) for _title, items in sections for keys, _text in items), default=0)
    stacked = longest > width // 2
    indent = 2 if stacked else longest + 2
    text_width = max(1, width - indent - (2 if stacked else 0))
    rows: list[tuple[str, str, str]] = []
    for index, (title, items) in enumerate(sections):
        if index:
            rows.append(("blank", "", ""))
        rows.append(("section", title, ""))
        for keys, text in items:
            lines = textwrap.wrap(text, text_width) or [""]
            if stacked:
                rows.append(("key", keys, ""))
                rows.extend(("key", "", line) for line in lines)
            else:
                rows.append(("key", keys, lines[0]))
                rows.extend(("key", "", line) for line in lines[1:])
    return rows, indent


def clamp_scroll(offset: int, total: int, visible: int) -> int:
    """Keep a scroll offset inside the rows that exist."""
    return max(0, min(offset, total - visible))
