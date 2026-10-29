"""Group text into selectable Markdown blocks and format them for the terminal."""
from __future__ import annotations

import re
import textwrap


_BLOCK_START_RE = re.compile(r"^(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|>|```|~~~|[❯●]\s)")
# Markdown horizontal rule: ---, ***, or ___ (optionally spaced).
# A list item; non-blank lines right after it continue the item (Markdown lazy continuation).
_LIST_ITEM_RE = re.compile(r"^(?:[-*+]\s|\d+[.)]\s)")
_RULE_RE = re.compile(r"^(?:-[ \t]*){3,}$|^(?:\*[ \t]*){3,}$|^(?:_[ \t]*){3,}$")

# Markdown pipe rows, or tables already drawn with box characters by the agent UI.
_TABLE_ROW_PREFIXES = ("|", "│", "┌", "├", "└", "┏", "┣", "┗", "╭", "╰")

_TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")
# A border line of a table drawn with box characters (no text).
_BOX_BORDER_RE = re.compile(r"^[\s─━═┌┐└┘├┤┬┴┼╭╮╰╯┏┓┗┛┣┫┳┻╋┃│║]+$")
_CODE_ROLES = ("fence", "code", "code_gap")
_CODE_COMMENT_RE = re.compile(r"(^|\s)(//|#(?=\s|$))")

# Invisible markers around bold spans in rendered text; drawn with A_BOLD.
BOLD_ON = "\x01"

BOLD_OFF = "\x02"

_CODE_SPAN_RE = re.compile(r"`([^`]+)`")
_BOLD_DELIMITER_RE = re.compile(r"\*\*|__")


def group_logical_blocks(lines: list[str]) -> list[str]:
    """Group physical terminal lines into selectable logical blocks."""
    blocks: list[str] = []
    paragraph: list[str] = []
    code: list[str] = []
    table: list[str] = []
    in_code = False
    list_item_open = False

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(" ".join(part.strip() for part in paragraph if part.strip()))
            paragraph.clear()

    def flush_table() -> None:
        if table:
            blocks.append("\n".join(table))
            table.clear()

    for line in lines:
        stripped = line.strip()
        if not in_code and stripped.startswith(_TABLE_ROW_PREFIXES):
            flush_paragraph()
            table.append(stripped)
            list_item_open = False
            continue
        flush_table()
        if stripped.startswith(("```", "~~~")):
            flush_paragraph()
            list_item_open = False
            code.append(line)
            in_code = not in_code
            if not in_code:
                blocks.append("\n".join(code))
                code.clear()
            continue
        if in_code:
            code.append(line)
            continue
        if not stripped:
            flush_paragraph()
            list_item_open = False
            continue
        if _BLOCK_START_RE.match(stripped) or _RULE_RE.match(stripped):
            flush_paragraph()
            is_item = bool(_LIST_ITEM_RE.match(stripped)) and not _RULE_RE.match(stripped)
            # List items keep their indentation, which is their nesting level.
            blocks.append(line.expandtabs(4).rstrip() if is_item else stripped)
            list_item_open = is_item
            continue
        if list_item_open:
            blocks[-1] += " " + stripped
            continue
        paragraph.append(line)

    flush_paragraph()
    flush_table()
    if code:
        blocks.append("\n".join(code))
    return blocks


def split_code_fences(blocks: list[str]) -> list[tuple[str, str]]:
    """Split fenced code and tables into one selectable block per code line or table row.

    Returns (text, role) pairs. The role is "" for normal blocks, "fence" for the opening
    fence line, "code" for a line that directly follows the previous one, "code_gap" for
    a line that follows one or more blank lines, "thead" and "trow" for the header (with
    its separator line) and the rows of a Markdown table, and "tline" for the lines of a
    table drawn with box characters.
    """
    expanded: list[tuple[str, str]] = []
    for block in blocks:
        if not block.lstrip().startswith(("```", "~~~")):
            if is_markdown_table(block):
                expanded.extend(split_pipe_table(block))
            elif block.lstrip().startswith(_TABLE_ROW_PREFIXES[1:]):
                expanded.extend(split_box_table(block))
            else:
                expanded.append((block, ""))
            continue
        opening, *body = block.split("\n")
        if body and body[-1].strip().startswith(("```", "~~~")):
            body = body[:-1]
        expanded.append((opening.strip(), "fence"))
        gap = False
        for line in body:
            if not line.strip():
                gap = True
                continue
            expanded.append((line.rstrip(), "code_gap" if gap else "code"))
            gap = False
    return expanded


def split_pipe_table(block: str) -> list[tuple[str, str]]:
    """One block per row of a Markdown table; the separator line stays with the header."""
    groups: list[list[str]] = []
    for row in (line.strip() for line in block.split("\n")):
        cells = _split_cells(row)
        if groups and all(_TABLE_SEPARATOR_CELL_RE.match(cell) for cell in cells):
            groups[-1].append(row)
        else:
            groups.append([row])
    return [("\n".join(rows), "thead" if index == 0 else "trow") for index, rows in enumerate(groups)]


def split_box_table(block: str) -> list[tuple[str, str]]:
    """One block per content line of a table drawn with box characters.

    Border lines (``┌───┐``, ``├───┤``) stay with the content line next to them.
    """
    groups: list[list[str]] = []
    pending: list[str] = []
    for line in block.split("\n"):
        if _BOX_BORDER_RE.match(line):
            (groups[-1] if groups else pending).append(line)
        else:
            groups.append(pending + [line])
            pending = []
    if pending:
        groups.append(pending)
    return [("\n".join(lines), "tline") for lines in groups]


def continues_run(previous_role: str, role: str) -> bool:
    """True when a block continues the previous one (code lines, table rows) with no gap."""
    return role in ("code", "trow") or (role == "tline" and previous_role == "tline")


def split_markdown_blocks(text: str) -> list[tuple[str, str]]:
    """Split one transcript message into selectable (text, code role) blocks."""
    expanded: list[tuple[str, str]] = []
    for block, code in split_code_fences(group_logical_blocks(text.splitlines())):
        if not code and re.search(r"(?:^|\s)•\s+", block) and block.count("•") > 1:
            expanded.extend(
                (f"• {item.strip()}", "")
                for item in re.split(r"\s*•\s+", block)
                if item.strip()
            )
        else:
            expanded.append((block, code))
    return expanded


def expand_transcript_blocks(
    blocks: list[tuple[str, str]],
) -> list[tuple[str, str, bool, str]]:
    """Preserve roles while splitting messages into semantic Markdown blocks.

    Returns (kind, text, is_message_start, code role) tuples.
    """
    expanded: list[tuple[str, str, bool, str]] = []
    for kind, text in blocks:
        message_blocks = [(text, "")] if kind == "tool" else split_markdown_blocks(text)
        for index, (block, code) in enumerate(message_blocks):
            expanded.append((kind, block, index == 0, code))
    return expanded


def join_blocks(lines: list[str], code: list[str], start: int, end: int) -> str:
    """Join a selected range for copying; code lines and table rows keep single newlines."""
    text = lines[start]
    for index in range(start + 1, end + 1):
        text += ("\n" if continues_run(code[index - 1], code[index]) else "\n\n") + lines[index]
    return text


def mark_inline_markup(text: str) -> str:
    """Replace **bold**/__bold__ with BOLD_ON/BOLD_OFF markers and unwrap `code`.

    Code spans stay literal (`__init__` is not bold, `**` inside code is text), but a
    bold phrase may contain code spans: **the `userId` field** is one bold span.
    Markers that never find a partner stay as literal text.
    """
    spans = list(_CODE_SPAN_RE.finditer(text))
    # Same length as ``text`` with code spans blanked out, so only real markup is found.
    flat = text
    for span in reversed(spans):
        flat = flat[: span.start()] + "\x00" * (span.end() - span.start()) + flat[span.end() :]

    edits: list[tuple[int, int, str]] = [(s.start(), s.end(), s.group(1)) for s in spans]
    open_at: dict[str, int] = {}
    for match in _BOLD_DELIMITER_RE.finditer(flat):
        kind, start, end = match.group(), match.start(), match.end()
        before = flat[start - 1] if start else " "
        after = flat[end] if end < len(flat) else " "
        if kind == "__":
            can_open = not (before.isalnum() or before == "_") and not after.isspace()
            can_close = not (after.isalnum() or after == "_") and not before.isspace()
        else:
            can_open = not after.isspace()
            can_close = not before.isspace()
        if kind in open_at and can_close and start > open_at[kind] + 2:
            opener = open_at.pop(kind)
            edits += [(opener, opener + 2, BOLD_ON), (start, end, BOLD_OFF)]
        elif can_open and kind not in open_at:
            open_at[kind] = start

    pieces, position = [], 0
    for start, end, replacement in sorted(edits):
        pieces += [text[position:start], replacement]
        position = end
    pieces.append(text[position:])
    return "".join(pieces)


def _strip_inline_markup(text: str) -> str:
    return mark_inline_markup(text).replace(BOLD_ON, "").replace(BOLD_OFF, "")


def bold_segments(text: str, bold: bool = False) -> tuple[list[tuple[str, bool]], bool]:
    """Split marked text into (segment, is_bold) pairs; return the trailing bold state.

    The state carries across wrapped rows of the same block.
    """
    segments: list[tuple[str, bool]] = []
    current = ""
    for char in text:
        if char in (BOLD_ON, BOLD_OFF):
            if current:
                segments.append((current, bold))
                current = ""
            bold = char == BOLD_ON
        else:
            current += char
    if current:
        segments.append((current, bold))
    return segments, bold


def is_markdown_table(block: str) -> bool:
    rows = block.splitlines()
    return bool(rows) and all(row.strip().startswith("|") for row in rows)


def _split_cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _table_rows(block: str, convert) -> list[list[str] | None]:
    """Cells of every line (None for a separator line), each cell passed through ``convert``."""
    rows: list[list[str] | None] = []
    for raw in block.splitlines():
        cells = _split_cells(raw)
        if all(_TABLE_SEPARATOR_CELL_RE.match(cell) for cell in cells):
            rows.append(None)
        else:
            rows.append([convert(cell) for cell in cells])
    return rows


def render_markdown_table(block: str, width: int = 0) -> str:
    """Align pipe-table columns, truncating the widest ones to fit ``width``."""
    rows = _table_rows(block, _strip_inline_markup)
    data = [row for row in rows if row is not None]
    if not data:
        return block
    columns = max(len(row) for row in data)
    for row in data:
        row.extend([""] * (columns - len(row)))
    widths = [max(len(row[column]) for row in data) for column in range(columns)]
    total = sum(widths) + 3 * (columns - 1)
    while width > 0 and total > width and max(widths) > 1:
        widest = widths.index(max(widths))
        widths[widest] -= 1
        total -= 1

    def fit(cell: str, size: int) -> str:
        if len(cell) > size:
            cell = cell[: max(0, size - 1)] + "…"
        return cell.ljust(size)

    rendered = []
    for row in rows:
        if row is None:
            rendered.append("─┼─".join("─" * size for size in widths))
        else:
            rendered.append(" │ ".join(fit(cell, size) for cell, size in zip(row, widths)).rstrip())
    return "\n".join(rendered)


def _wrap_field(name: str, value: str, width: int) -> list[str]:
    """``Name: value`` wrapped to ``width``, continuation lines indented under the value."""
    label = f"{name}: "
    indent = " " * min(len(label), max(0, width // 2))
    lines = textwrap.wrap(
        label + value,
        width=max(1, width),
        subsequent_indent=indent,
        replace_whitespace=False,
        break_long_words=True,
    ) or [label.rstrip()]
    if lines[0].startswith(f"{name}:"):
        lines[0] = f"{BOLD_ON}{name}:{BOLD_OFF}" + lines[0][len(name) + 1 :]
    return lines


def layout_table_blocks(blocks: list[str], width: int = 0) -> list[tuple[str, str]]:
    """Display text for the row blocks of one pipe table (header block first).

    The table shows with aligned columns when they fit ``width`` without cutting a cell.
    Otherwise each row becomes a record (``Name: value`` lines with the full text), like
    agent UIs do for a table that is too wide.
    """
    table = "\n".join(blocks)
    plain = [row for row in _table_rows(table, _strip_inline_markup) if row is not None]
    if not plain:
        return [(block, "table") for block in blocks]
    columns = max(len(row) for row in plain)
    natural = (
        sum(max((len(row[c]) for row in plain if c < len(row)), default=0) for c in range(columns))
        + 3 * (columns - 1)
    )
    if width <= 0 or natural <= width:
        rendered = render_markdown_table(table, width).split("\n")
        result: list[tuple[str, str]] = []
        position = 0
        for block in blocks:
            count = len(block.split("\n"))
            result.append(("\n".join(rendered[position : position + count]), "table"))
            position += count
        return result
    rich = [row for row in _table_rows(table, mark_inline_markup) if row is not None]
    names = [
        name or f"Column {number + 1}"
        for number, name in enumerate(plain[0] + [""] * (columns - len(plain[0])))
    ]
    columns_line = textwrap.wrap(
        "Columns: " + " · ".join(names),
        width=max(1, width),
        subsequent_indent=" " * min(9, max(0, width // 2)),
    )
    result = [("\n".join(columns_line), "record")]
    rule = "─" * min(width, 40)
    for row in rich[1:]:
        lines = [rule]
        for name, value in zip(names, row):
            if value:
                lines.extend(_wrap_field(name, value, width))
        result.append(("\n".join(lines), "record"))
    return result


def _layout_table_groups(
    lines: list[str], code: list[str], width: int
) -> dict[int, tuple[str, str]]:
    """Display text for every table block, laying out each table as a whole."""
    display: dict[int, tuple[str, str]] = {}
    index = 0
    while index < len(lines):
        role = code[index]
        if role == "thead":
            end = index + 1
            while end < len(lines) and code[end] == "trow":
                end += 1
            for position, shown in zip(range(index, end), layout_table_blocks(lines[index:end], width)):
                display[position] = shown
            index = end
            continue
        if role == "tline":
            display[index] = (lines[index], "table")
        index += 1
    return display


def format_markdown_lines(
    lines: list[str], width: int = 0, code: list[str] | None = None
) -> list[tuple[str, str]]:
    """Return simplified terminal text and a whole-line Markdown style name.

    ``code`` holds each block's code role from ``split_code_fences``; code lines are
    shown as-is, never parsed as Markdown.
    """
    formatted: list[tuple[str, str]] = []
    in_code = False
    indent_stack: list[int] = []
    tables = _layout_table_groups(lines, code, width) if code else {}

    def list_level(item: str) -> int:
        """Nesting level of a list item from its indentation (any step size)."""
        expanded = item.expandtabs(4)
        indent = len(expanded) - len(expanded.lstrip())
        while indent_stack and indent_stack[-1] > indent:
            indent_stack.pop()
        if not indent_stack or indent_stack[-1] < indent:
            indent_stack.append(indent)
        return len(indent_stack) - 1

    for index, line in enumerate(lines):
        stripped = line.strip()
        role = code[index] if code else ""
        if role or not _LIST_ITEM_RE.match(stripped):
            indent_stack.clear()
        if index in tables:
            formatted.append(tables[index])
            continue
        if role == "fence":
            language = stripped.lstrip("`~").strip()
            label = f"─ code · {language} " if language else "─ code "
            formatted.append((label + "─" * 8, "code"))
            continue
        if role in _CODE_ROLES:
            formatted.append(("  " + line, "code"))
            continue
        if not in_code and is_markdown_table(line):
            formatted.append((render_markdown_table(line, width), "table"))
            continue
        if not in_code and stripped.startswith(_TABLE_ROW_PREFIXES[1:]):
            formatted.append((line, "table"))
            continue
        if "\n" in line and stripped.startswith(("```", "~~~")):
            code_lines = line.splitlines()
            body = code_lines[1:-1] if len(code_lines) > 1 else []
            formatted.append(("\n".join("  " + item for item in body), "code"))
            continue
        if stripped.startswith(("```", "~~~")):
            in_code = not in_code
            formatted.append(("─ code " + "─" * 8, "code"))
            continue
        if in_code:
            formatted.append(("  " + line, "code"))
            continue
        if _RULE_RE.match(stripped):
            formatted.append(("─" * min(width or 40, 40), "rule"))
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            formatted.append((mark_inline_markup(heading.group(2)), "heading"))
            continue
        quote = re.match(r"^>\s?(.*)$", stripped)
        if quote:
            formatted.append(("│ " + mark_inline_markup(quote.group(1)), "quote"))
            continue
        bullet = re.match(r"^\s*[-*+]\s+(.*)$", line)
        if bullet:
            level = list_level(line)
            marker = "•" if level == 0 else "◦"
            formatted.append(
                ("  " * (level + 1) + f"{marker} " + mark_inline_markup(bullet.group(1)), "bullet")
            )
            continue
        numbered = re.match(r"^\s*(\d+[.)])\s+(.*)$", line)
        if numbered:
            indent = "  " * (list_level(line) + 1)
            formatted.append((f"{indent}{numbered.group(1)} {mark_inline_markup(numbered.group(2))}", "bullet"))
            continue
        if re.search(r"(?:^|\s)•\s+", line):
            items = [item.strip() for item in re.split(r"\s*•\s+", line) if item.strip()]
            formatted.append(("\n".join(f"  • {mark_inline_markup(item)}" for item in items), "bullet"))
            continue
        formatted.append((mark_inline_markup(line), "normal"))
    return formatted


def comment_preview(block: str, limit: int = 40) -> str:
    """Return a one-line, truncated preview of the commented block."""
    if is_markdown_table(block):
        header = block.splitlines()[0].strip().strip("|").split("|")
        block = " · ".join(_strip_inline_markup(cell.strip()) for cell in header)
    text = " ".join(_strip_inline_markup(block).split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def is_code_frame(text: str) -> bool:
    """True for the rule line that opens a code block ("─ code · ts ────")."""
    return text.lstrip().startswith(("─", "— code"))


def split_code_comment(text: str) -> tuple[str, str]:
    """Split a code line into (code, trailing comment) at a `//` or `#` comment marker.

    A marker only counts at the start of the line or after whitespace, so URLs such as
    "https://host" and "a#b" stay whole.
    """
    match = _CODE_COMMENT_RE.search(text)
    if not match:
        return text, ""
    cut = match.start(2)
    return text[:cut], text[cut:]
