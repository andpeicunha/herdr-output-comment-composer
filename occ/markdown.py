"""Group text into selectable Markdown blocks and format them for the terminal."""
from __future__ import annotations

import re


_BLOCK_START_RE = re.compile(r"^(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|>|```|~~~|[❯●]\s)")
# Markdown horizontal rule: ---, ***, or ___ (optionally spaced).
# A list item; non-blank lines right after it continue the item (Markdown lazy continuation).
_LIST_ITEM_RE = re.compile(r"^(?:[-*+]\s|\d+[.)]\s)")
_RULE_RE = re.compile(r"^(?:-[ \t]*){3,}$|^(?:\*[ \t]*){3,}$|^(?:_[ \t]*){3,}$")

# Markdown pipe rows, or tables already drawn with box characters by the agent UI.
_TABLE_ROW_PREFIXES = ("|", "│", "┌", "├", "└", "┏", "┣", "┗", "╭", "╰")

_TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")

# Invisible markers around bold spans in rendered text; drawn with A_BOLD.
BOLD_ON = "\x01"

BOLD_OFF = "\x02"

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|(?<!\w)__(.+?)__(?!\w)")


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
            blocks.append(stripped)
            list_item_open = bool(_LIST_ITEM_RE.match(stripped)) and not _RULE_RE.match(stripped)
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
    """Split fenced code blocks into one selectable block per code line.

    Returns (text, code role) pairs. The role is "" for normal blocks, "fence" for the
    opening fence line, "code" for a line that directly follows the previous one, and
    "code_gap" for a line that follows one or more blank lines.
    """
    expanded: list[tuple[str, str]] = []
    for block in blocks:
        if not block.lstrip().startswith(("```", "~~~")):
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
    """Join a selected range for copying; consecutive code lines keep single newlines."""
    text = lines[start]
    for index in range(start + 1, end + 1):
        text += ("\n" if code[index] == "code" else "\n\n") + lines[index]
    return text


def mark_inline_markup(text: str) -> str:
    """Replace **bold**/__bold__ with BOLD_ON/BOLD_OFF markers and unwrap `code`.

    Code spans are kept literal, so `__init__` is not mistaken for bold.
    """
    parts = re.split(r"`([^`]+)`", text)
    for index in range(0, len(parts), 2):
        parts[index] = _BOLD_RE.sub(
            lambda m: f"{BOLD_ON}{m.group(1) or m.group(2)}{BOLD_OFF}", parts[index]
        )
    return "".join(parts)


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


def render_markdown_table(block: str, width: int = 0) -> str:
    """Align pipe-table columns, truncating the widest ones to fit ``width``."""
    rows: list[list[str] | None] = []
    for raw in block.splitlines():
        cells = [cell.strip() for cell in raw.strip().strip("|").split("|")]
        if all(_TABLE_SEPARATOR_CELL_RE.match(cell) for cell in cells):
            rows.append(None)
        else:
            rows.append([_strip_inline_markup(cell) for cell in cells])
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


def format_markdown_lines(
    lines: list[str], width: int = 0, code: list[str] | None = None
) -> list[tuple[str, str]]:
    """Return simplified terminal text and a whole-line Markdown style name.

    ``code`` holds each block's code role from ``split_code_fences``; code lines are
    shown as-is, never parsed as Markdown.
    """
    formatted: list[tuple[str, str]] = []
    in_code = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        role = code[index] if code else ""
        if role == "fence":
            language = stripped.lstrip("`~").strip()
            label = f"─ code · {language} " if language else "─ code "
            formatted.append((label + "─" * 8, "code"))
            continue
        if role:
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
            formatted.append(("  • " + mark_inline_markup(bullet.group(1)), "bullet"))
            continue
        numbered = re.match(r"^\s*(\d+[.)])\s+(.*)$", line)
        if numbered:
            formatted.append((f"  {numbered.group(1)} {mark_inline_markup(numbered.group(2))}", "bullet"))
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
