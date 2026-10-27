"""Group text into selectable Markdown blocks and format them for the terminal."""
from __future__ import annotations

import re


_BLOCK_START_RE = re.compile(r"^(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|>|```|~~~|[❯●]\s)")

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
            continue
        flush_table()
        if stripped.startswith(("```", "~~~")):
            flush_paragraph()
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
            continue
        if _BLOCK_START_RE.match(stripped):
            flush_paragraph()
            blocks.append(stripped)
            continue
        paragraph.append(line)

    flush_paragraph()
    flush_table()
    if code:
        blocks.append("\n".join(code))
    return blocks


def split_markdown_blocks(text: str) -> list[str]:
    """Split one transcript message into independently selectable blocks."""
    blocks = group_logical_blocks(text.splitlines())
    expanded: list[str] = []
    for block in blocks:
        if re.search(r"(?:^|\s)•\s+", block) and block.count("•") > 1:
            expanded.extend(
                f"• {item.strip()}"
                for item in re.split(r"\s*•\s+", block)
                if item.strip()
            )
        else:
            expanded.append(block)
    return expanded


def expand_transcript_blocks(
    blocks: list[tuple[str, str]],
) -> list[tuple[str, str, bool]]:
    """Preserve roles while splitting messages into semantic Markdown blocks."""
    expanded: list[tuple[str, str, bool]] = []
    for kind, text in blocks:
        message_blocks = [text] if kind == "tool" else split_markdown_blocks(text)
        for index, block in enumerate(message_blocks):
            expanded.append((kind, block, index == 0))
    return expanded


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


def format_markdown_lines(lines: list[str], width: int = 0) -> list[tuple[str, str]]:
    """Return simplified terminal text and a whole-line Markdown style name."""
    formatted: list[tuple[str, str]] = []
    in_code = False
    for line in lines:
        stripped = line.strip()
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
