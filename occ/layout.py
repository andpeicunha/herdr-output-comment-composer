"""Pure layout math: display rows, selection, paging, and the scrollbar."""
from __future__ import annotations

import re
import textwrap


# Start of a wrapped list item or quote; wrapped rows are indented under its text.
_HANGING_RE = re.compile(r"^\s*(?:[•◦│]|\d+[.)])\s+")
COMMENT_PREFIX = "  ╰─ comment: "


def build_display_rows(
    lines: list[str],
    comments: dict[int, str],
    width: int = 0,
    spacing: bool = False,
    compact_after: set[int] | None = None,
    no_wrap: set[int] | None = None,
    preserve_space: set[int] | None = None,
) -> list[tuple[str, int, str]]:
    """Wrap blocks into display rows.

    Blocks in ``no_wrap`` (tables) are cut instead of wrapped. Blocks in
    ``preserve_space`` (code) keep their whitespace; for the others, whitespace at a
    break is dropped and wrapped list items get a hanging indent.
    """
    rows: list[tuple[str, int, str]] = []
    for index, line in enumerate(lines):
        first_row = True
        physical_lines = line.splitlines() or [""]
        for physical_line in physical_lines:
            if width <= 0:
                wrapped = [physical_line]
            elif index in (no_wrap or set()):
                wrapped = [physical_line[:width]]
            else:
                keep = index in (preserve_space or set())
                hanging = None if keep else _HANGING_RE.match(physical_line)
                wrapped = textwrap.wrap(
                    physical_line,
                    width=max(1, width),
                    replace_whitespace=False,
                    drop_whitespace=not keep,
                    subsequent_indent=" " * min(len(hanging.group()), width // 2) if hanging else "",
                )
            for wrapped_line in wrapped or [""]:
                kind = "line" if first_row else "continuation"
                rows.append((kind, index, wrapped_line.rstrip()))
                first_row = False
        if index in comments:
            comment_lines = comments[index].splitlines() or [""]
            comment_width = max(1, width - len(COMMENT_PREFIX))
            first_comment_row = True
            for comment_line in comment_lines:
                wrapped = textwrap.wrap(comment_line, width=comment_width) if width > 0 else [comment_line]
                for wrapped_line in wrapped or [""]:
                    kind = "comment" if first_comment_row else "comment_continuation"
                    rows.append((kind, index, wrapped_line))
                    first_comment_row = False
        if spacing and index + 1 < len(lines) and index not in (compact_after or set()):
            rows.append(("spacer", index, ""))
    return rows


def selection_bounds(
    cursor: int, anchor: int | None, selected: tuple[int, int] | None
) -> tuple[int, int]:
    if anchor is not None:
        return tuple(sorted((anchor, cursor)))
    if selected is not None:
        return selected
    return cursor, cursor


def content_rows_available(total_height: int, reserved_bottom: int = 0) -> int:
    """Return viewer rows after frame, headers, status, footer, and editor space.

    The editor box replaces the frame's bottom edge while it is open.
    """
    frame_bottom = 0 if reserved_bottom else 1
    return max(1, total_height - reserved_bottom - frame_bottom - 6)


def editor_visual_rows(
    buffer: list[str], width: int
) -> list[tuple[int, int, str]]:
    """Soft-wrap editor lines while keeping logical row and column offsets."""
    width = max(1, width)
    rows: list[tuple[int, int, str]] = []
    for logical_row, line in enumerate(buffer):
        if not line:
            rows.append((logical_row, 0, ""))
            continue
        for start in range(0, len(line), width):
            rows.append((logical_row, start, line[start : start + width]))
        if len(line) % width == 0:
            rows.append((logical_row, len(line), ""))
    return rows


def editor_cursor_position(
    visual_rows: list[tuple[int, int, str]], logical_row: int, column: int
) -> tuple[int, int]:
    matches = [
        (index, start, text)
        for index, (row, start, text) in enumerate(visual_rows)
        if row == logical_row and start <= column <= start + len(text)
    ]
    if not matches:
        return 0, 0
    index, start, _text = matches[-1]
    return index, column - start


def page_target(rows: list[tuple[str, int, str]], cursor: int, delta_rows: int) -> int:
    """Return the block about ``delta_rows`` display rows away from ``cursor``.

    Always moves at least one block, so a block taller than the page is not a dead end.
    """
    if not rows:
        return cursor
    start = next(
        (index for index, (kind, line_index, _) in enumerate(rows)
         if kind == "line" and line_index == cursor),
        0,
    )
    target_row = min(max(0, start + delta_rows), len(rows) - 1)
    target = rows[target_row][1]
    last_block = rows[-1][1]
    if delta_rows > 0 and target <= cursor:
        target = min(cursor + 1, last_block)
    elif delta_rows < 0 and target >= cursor:
        target = max(cursor - 1, 0)
    return target


def scrollbar_thumb(total_rows: int, visible_rows: int, top: int) -> tuple[int, int] | None:
    """Return the thumb's (start, size) in the track, or None when nothing scrolls."""
    if visible_rows <= 0 or total_rows <= visible_rows:
        return None
    size = min(visible_rows, max(1, round(visible_rows * visible_rows / total_rows)))
    max_top = total_rows - visible_rows
    start = round(min(max(0, top), max_top) / max_top * (visible_rows - size))
    return start, size


def scroll_position_label(total_rows: int, visible_rows: int, top: int) -> str:
    """Return "top", "end", or a percentage; empty when everything fits."""
    if total_rows <= visible_rows:
        return ""
    max_top = total_rows - visible_rows
    if top <= 0:
        return "top"
    if top >= max_top:
        return "end"
    return f"{round(top / max_top * 100)}%"
