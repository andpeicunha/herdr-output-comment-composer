"""Stable wrapping primitives shared by terminal viewers."""
from __future__ import annotations

import textwrap
import re

_HANGING_RE = re.compile(
    r"^\s*(?:│\s+(?:(?:[-*+•◦]|\d+[.)])\s+)?|(?:[•◦]|\d+[.)])\s+)"
)

def wrap_physical_line(text: str, width: int, *, preserve_space: bool = False,
                       hanging_indent: int | None = None) -> list[str]:
    """Wrap one physical row with the common viewer whitespace policy."""
    if width <= 0:
        return [text]
    if hanging_indent is None and not preserve_space:
        match = _HANGING_RE.match(text)
        hanging_indent = len(match.group()) if match else 0
    return textwrap.wrap(
        text, width=max(1, width), replace_whitespace=False,
        drop_whitespace=not preserve_space,
        subsequent_indent=" " * min(max(0, hanging_indent or 0), width // 2),
    ) or [""]

def build_rows(lines: list[str], width: int, *, preserve_space: set[int] | None = None,
               no_wrap: set[int] | None = None, no_wrap_width: int | None = None) -> list[tuple[str, int, str]]:
    """Build common line and continuation rows; viewer annotations remain local."""
    rows = []
    cut_width = width if no_wrap_width is None else no_wrap_width
    for index, block in enumerate(lines):
        first = True
        for line in block.splitlines() or [""]:
            if index in (no_wrap or set()):
                wrapped = [line[:cut_width]]
            else:
                wrapped = wrap_physical_line(line, width, preserve_space=index in (preserve_space or set()))
            for part in wrapped:
                rows.append(("line" if first else "continuation", index, part.rstrip()))
                first = False
    return rows
