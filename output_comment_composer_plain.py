#!/usr/bin/env python3
"""Minimal curses UI used to isolate Textual rendering problems."""
from __future__ import annotations

import base64
import curses
import json
import os
import re
import subprocess
import termios
import textwrap
import time
import traceback


_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_BLOCK_START_RE = re.compile(r"^(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|>|```|~~~|[❯●]\s)")
_TRANSCRIPT_MAX_LINES = 800
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_COMMENT_PREFIX = "  ╰─ comment: "


def load_meta() -> dict[str, str]:
    values: dict[str, str] = {}
    path = os.environ.get("OUTPUT_COMMENT_COMPOSER_META", "")
    if not path:
        return values
    try:
        with open(path, encoding="utf-8") as meta:
            for raw in meta:
                key, separator, value = raw.rstrip("\n").partition("=")
                if separator:
                    values[key] = value
    except OSError:
        pass
    return values


def _read_jsonl(path: str) -> list[dict]:
    entries: list[dict] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as source:
            for raw in source:
                try:
                    value = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(value, dict):
                    entries.append(value)
    except OSError:
        pass
    return entries


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict)
        and block.get("type") in ("text", "input_text", "output_text")
    ).strip()


def codex_transcript_blocks(entries: list[dict]) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for entry in entries:
        if entry.get("type") != "response_item":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        kind = payload.get("type")
        if kind == "message" and payload.get("role") in ("user", "assistant"):
            text = _message_text(payload.get("content"))
            if not text or text.startswith(("<", "# AGENTS.md")):
                continue
            role = "user" if payload.get("role") == "user" else "assistant"
            blocks.append((role, text))
        elif kind in ("function_call", "custom_tool_call", "local_shell_call"):
            name = str(payload.get("name") or "shell")
            blocks.append(("tool", name))
    return blocks


def claude_transcript_blocks(entries: list[dict]) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for entry in entries:
        if entry.get("isSidechain") or entry.get("isMeta"):
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if entry.get("type") == "user":
            text = _message_text(content)
            if text and not text.startswith(("<command-", "<local-command", "<task-notification")):
                blocks.append(("user", text))
        elif entry.get("type") == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and str(block.get("text", "")).strip():
                    blocks.append(("assistant", str(block["text"]).strip()))
                elif block.get("type") == "tool_use":
                    blocks.append(("tool", str(block.get("name") or "tool")))
    return blocks


def limit_transcript_blocks(
    blocks: list[tuple[str, str]], max_lines: int = _TRANSCRIPT_MAX_LINES
) -> list[tuple[str, str]]:
    kept: list[tuple[str, str]] = []
    used = 0
    for block in reversed(blocks):
        block_lines = max(1, len(block[1].splitlines()))
        if kept and used + block_lines > max_lines:
            break
        kept.append(block)
        used += block_lines
    return list(reversed(kept))


def _find_codex_transcript(session_id: str) -> str | None:
    if not session_id or not _SESSION_ID_RE.match(session_id):
        return None
    suffix = f"-{session_id}.jsonl"
    root_dir = os.path.expanduser(os.path.join(os.environ.get("CODEX_HOME", "~/.codex"), "sessions"))
    newest: str | None = None
    for root, _dirs, files in os.walk(root_dir):
        for name in files:
            if name.startswith("rollout-") and name.endswith(suffix):
                path = os.path.join(root, name)
                if newest is None or path > newest:
                    newest = path
    return newest


def _find_claude_transcript(session_id: str) -> str | None:
    if not session_id or not _SESSION_ID_RE.match(session_id):
        return None
    projects = os.path.expanduser(
        os.path.join(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude"), "projects")
    )
    try:
        project_dirs = os.listdir(projects)
    except OSError:
        return None
    for project in project_dirs:
        path = os.path.join(projects, project, f"{session_id}.jsonl")
        if os.path.isfile(path):
            return path
    return None


def fetch_transcript(meta: dict[str, str]) -> list[tuple[str, str]]:
    session_id = meta.get("SESSION_ID", "")
    agent = meta.get("AGENT", "")
    if agent == "codex":
        path = _find_codex_transcript(session_id)
        blocks = codex_transcript_blocks(_read_jsonl(path)) if path else []
    elif agent == "claude":
        path = _find_claude_transcript(session_id)
        blocks = claude_transcript_blocks(_read_jsonl(path)) if path else []
    else:
        blocks = []
    return limit_transcript_blocks(blocks)


def fetch_snapshot(source_pane: str) -> list[str]:
    herdr = os.environ.get("HERDR_BIN_PATH", "herdr")
    result = subprocess.run(
        [
            herdr,
            "pane",
            "read",
            source_pane,
            "--source",
            "recent-unwrapped",
            "--lines",
            "200",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ["Failed to read source pane."]
    lines = [_ANSI_RE.sub("", line) for line in result.stdout.splitlines()]
    return group_logical_blocks(lines) or ["Source pane is empty."]


def group_logical_blocks(lines: list[str]) -> list[str]:
    """Group physical terminal lines into selectable logical blocks."""
    blocks: list[str] = []
    paragraph: list[str] = []
    code: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(" ".join(part.strip() for part in paragraph if part.strip()))
            paragraph.clear()

    for line in lines:
        stripped = line.strip()
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


def build_display_rows(
    lines: list[str],
    comments: dict[int, str],
    width: int = 0,
    spacing: bool = False,
    compact_after: set[int] | None = None,
) -> list[tuple[str, int, str]]:
    rows: list[tuple[str, int, str]] = []
    for index, line in enumerate(lines):
        first_row = True
        physical_lines = line.splitlines() or [""]
        for physical_line in physical_lines:
            wrapped = (
                textwrap.wrap(
                    physical_line,
                    width=max(1, width),
                    replace_whitespace=False,
                    drop_whitespace=False,
                )
                if width > 0
                else [physical_line]
            )
            for wrapped_line in wrapped or [""]:
                kind = "line" if first_row else "continuation"
                rows.append((kind, index, wrapped_line.rstrip()))
                first_row = False
        if index in comments:
            comment_lines = comments[index].splitlines() or [""]
            comment_width = max(1, width - len(_COMMENT_PREFIX))
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


def copy_blocks_to_clipboard(blocks: list[str], start: int, end: int) -> None:
    text = "\n\n".join(blocks[start : end + 1])
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    os.write(1, f"\x1b]52;c;{encoded}\a".encode("ascii"))


def format_markdown_lines(lines: list[str]) -> list[tuple[str, str]]:
    """Return simplified terminal text and a whole-line Markdown style name."""
    formatted: list[tuple[str, str]] = []
    in_code = False
    for line in lines:
        stripped = line.strip()
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
            formatted.append((heading.group(2), "heading"))
            continue
        quote = re.match(r"^>\s?(.*)$", stripped)
        if quote:
            formatted.append(("│ " + quote.group(1), "quote"))
            continue
        bullet = re.match(r"^\s*[-*+]\s+(.*)$", line)
        if bullet:
            formatted.append(("  • " + bullet.group(1), "bullet"))
            continue
        numbered = re.match(r"^\s*(\d+[.)])\s+(.*)$", line)
        if numbered:
            formatted.append((f"  {numbered.group(1)} {numbered.group(2)}", "bullet"))
            continue
        if re.search(r"(?:^|\s)•\s+", line):
            items = [item.strip() for item in re.split(r"\s*•\s+", line) if item.strip()]
            formatted.append(("\n".join(f"  • {item}" for item in items), "bullet"))
            continue
        clean = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), line)
        clean = re.sub(r"`([^`]+)`", r"\1", clean)
        formatted.append((clean, "normal"))
    return formatted


def needs_discard_confirmation(original: str, current: str) -> bool:
    return original.strip() != current.strip()


def content_rows_available(total_height: int, reserved_bottom: int = 0) -> int:
    """Return viewer rows after frame, headers, status, footer, and editor space.

    The editor box replaces the frame's bottom edge while it is open.
    """
    frame_bottom = 0 if reserved_bottom else 1
    return max(1, total_height - reserved_bottom - frame_bottom - 6)


def selected_color_pair(color_count: int) -> tuple[int, int]:
    """Use a quiet neutral background when the terminal supports 256 colors."""
    if color_count >= 256:
        return 250, 235
    return curses.COLOR_GREEN, -1


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


def build_prompt(lines: list[str], comments: dict[int, str]) -> str:
    parts = ["Please address these comments on your previous output:"]
    for number, line_index in enumerate(sorted(comments), 1):
        parts.append(
            f"Comment {number} on lines {line_index + 1}–{line_index + 1}:\n\n"
            f"> {lines[line_index]}\n\n"
            f"Comment:\n{comments[line_index]}"
        )
    return "\n\n".join(parts) + "\n\n— @andpeicunha\n"


def send_comments(
    source_pane: str, lines: list[str], comments: dict[int, str]
) -> tuple[bool, str]:
    herdr = os.environ.get("HERDR_BIN_PATH", "herdr")
    prompt = build_prompt(lines, comments)
    result = subprocess.run(
        [herdr, "agent", "prompt", source_pane, prompt],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode == 0:
        return True, ""

    fallback = subprocess.run(
        [herdr, "pane", "send-text", source_pane, prompt],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if fallback.returncode != 0:
        return False, (result.stderr or fallback.stderr or "Send failed").strip()

    enter = subprocess.run(
        [herdr, "agent", "send-keys", source_pane, "Enter"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if enter.returncode != 0:
        return False, (enter.stderr or "Could not submit prompt").strip()
    return True, ""


def comment_preview(block: str, limit: int = 40) -> str:
    """Return a one-line, truncated preview of the commented block."""
    text = " ".join(block.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _draw_rounded_box(window: curses.window, attr: int = 0) -> None:
    height, width = window.getmaxyx()
    if height < 2 or width < 2:
        return
    horizontal = "─" * (width - 2)
    _safe_addnstr(window, 0, 0, f"╭{horizontal}╮", width, attr)
    for y in range(1, height - 1):
        _safe_addnstr(window, y, 0, "│", 1, attr)
        _safe_addnstr(window, y, width - 1, "│", 1, attr)
    _safe_addnstr(window, height - 1, 0, f"╰{horizontal}╯", width, attr)


def _safe_addnstr(
    screen: curses.window, y: int, x: int, text: str, width: int, attr: int = 0
) -> None:
    if width <= 0:
        return
    try:
        screen.addnstr(y, x, text, width, attr)
    except curses.error:
        pass


class PlainComposer:
    def __init__(self, source_pane: str, meta: dict[str, str] | None = None):
        self.lines = ["Loading snapshot…"]
        self.block_kinds = ["assistant"]
        self.block_starts = [True]
        self.source_pane = source_pane
        self.meta = meta or {}
        self.cursor = 0
        self.comments: dict[int, str] = {}
        self.selection_anchor: int | None = None
        self.selected_range: tuple[int, int] | None = None
        self.status = ""
        self.sent = False
        self.colors: dict[str, int] = {}

    def run(self, screen: curses.window) -> None:
        curses.curs_set(0)
        screen.keypad(True)
        self.setup_colors()
        self.draw_loading(screen)
        started = time.perf_counter()
        transcript = fetch_transcript(self.meta)
        if transcript:
            expanded = expand_transcript_blocks(transcript)
            self.block_kinds = [kind for kind, _text, _start in expanded]
            self.lines = [text for _kind, text, _start in expanded]
            self.block_starts = [start for _kind, _text, start in expanded]
            source = "transcript"
        else:
            self.lines = fetch_snapshot(self.source_pane)
            self.block_kinds = ["assistant"] * len(self.lines)
            self.block_starts = [index == 0 for index in range(len(self.lines))]
            source = "pane fallback"
        self.cursor = max(0, len(self.lines) - 1)
        self.status = (
            f"Loaded {len(self.lines)} blocks from {source} "
            f"in {time.perf_counter() - started:.2f}s"
        )
        while True:
            self.draw(screen)
            key = screen.getch()
            if key in (ord("q"), 27):
                return
            if key in (curses.KEY_UP, ord("k")):
                self.cursor = max(0, self.cursor - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                self.cursor = min(len(self.lines) - 1, self.cursor + 1)
            elif key in (curses.KEY_PPAGE, ord("u")):
                self.cursor = max(0, self.cursor - max(1, screen.getmaxyx()[0] // 2))
            elif key in (curses.KEY_NPAGE, ord("d")):
                self.cursor = min(
                    len(self.lines) - 1,
                    self.cursor + max(1, screen.getmaxyx()[0] // 2),
                )
            elif key == ord("g"):
                self.cursor = 0
            elif key == ord("G"):
                self.cursor = len(self.lines) - 1
            elif key == ord("c"):
                self.edit_comment(screen)
            elif key == ord(" "):
                self.toggle_selection()
            elif key == ord("y"):
                start, end = self.current_selection()
                copy_blocks_to_clipboard(self.lines, start, end)
                count = end - start + 1
                self.status = f"Copied {count} block(s)"
            elif key == ord("s"):
                if self.submit(screen):
                    return

    def current_selection(self) -> tuple[int, int]:
        return selection_bounds(
            self.cursor, self.selection_anchor, self.selected_range
        )

    def toggle_selection(self) -> None:
        if self.selection_anchor is not None:
            self.selected_range = tuple(sorted((self.selection_anchor, self.cursor)))
            self.selection_anchor = None
            start, end = self.selected_range
            self.status = f"Selected blocks {start + 1}–{end + 1}"
        elif self.selected_range is not None:
            self.selected_range = None
            self.status = "Selection cleared"
        else:
            self.selection_anchor = self.cursor
            self.status = "Selection started · move and press Space again"

    def setup_colors(self) -> None:
        if not curses.has_colors():
            return
        curses.start_color()
        curses.use_default_colors()
        color_count = getattr(curses, "COLORS", 0)
        pairs = {
            "selected": selected_color_pair(color_count),
            "comment": (curses.COLOR_YELLOW, -1),
            "comment_badge": (curses.COLOR_BLACK, curses.COLOR_YELLOW),
            "muted": (curses.COLOR_BLUE, -1),
            "footer": (curses.COLOR_WHITE, curses.COLOR_BLUE),
            "success": (curses.COLOR_GREEN, -1),
            "error": (curses.COLOR_RED, -1),
            "heading": (curses.COLOR_CYAN, -1),
            "code": (curses.COLOR_GREEN, -1),
            "quote": (curses.COLOR_MAGENTA, -1),
            "bullet": (curses.COLOR_WHITE, -1),
            "gutter": (245 if color_count >= 256 else curses.COLOR_BLUE, -1),
            "marker": (curses.COLOR_GREEN, -1),
            "prompt": (curses.COLOR_WHITE, -1),
            "tool": (245 if color_count >= 256 else curses.COLOR_BLUE, -1),
        }
        for number, (name, colors) in enumerate(pairs.items(), 1):
            try:
                curses.init_pair(number, *colors)
                self.colors[name] = curses.color_pair(number)
            except curses.error:
                pass

    def style(self, name: str, fallback: int = 0) -> int:
        return self.colors.get(name, fallback)

    def draw_loading(self, screen: curses.window) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        title = " Output Comment Composer · plain mode "
        _safe_addnstr(screen, 0, 0, title.ljust(max(0, width - 1)), width - 1, curses.A_REVERSE)
        message = "Loading snapshot…"
        x = max(0, (width - len(message)) // 2)
        _safe_addnstr(screen, max(1, height // 2), x, message, width - x - 1, curses.A_BOLD)
        screen.refresh()

    def draw(self, screen: curses.window, reserved_bottom: int = 0) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        viewer_height = height - reserved_bottom
        if viewer_height < 8 or width < 30:
            _safe_addnstr(screen, 0, 0, "Pane too small", width - 1, curses.A_BOLD)
            screen.refresh()
            return

        # The open editor box draws its own top edge, which closes the frame.
        inner_bottom = viewer_height - 1 if reserved_bottom else height - 2
        inner_width = width - 2
        border_attr = self.style("comment", curses.A_BOLD) | curses.A_BOLD
        _draw_rounded_box(screen, border_attr)
        badge = " ✎ COMMENTS "
        _safe_addnstr(
            screen,
            0,
            2,
            badge,
            width - 4,
            self.style("comment_badge", curses.A_REVERSE) | curses.A_BOLD,
        )
        _safe_addnstr(
            screen,
            0,
            2 + len(badge),
            " Output Comment Composer ",
            width - len(badge) - 4,
            border_attr,
        )
        position = f"block {self.cursor + 1}/{len(self.lines)}"
        meta = f" source {self.source_pane}  ·  {len(self.comments)} comment(s)  ·  {position} "
        _safe_addnstr(screen, 1, 1, meta, inner_width, self.style("muted"))
        _safe_addnstr(screen, 2, 1, "─" * inner_width, inner_width, self.style("muted"))

        markdown = format_markdown_lines(self.lines)
        rendered_blocks = [
            text if self.block_kinds[index] == "assistant" else self.lines[index]
            for index, (text, _kind) in enumerate(markdown)
        ]
        compact_after = {
            index
            for index in range(len(markdown) - 1)
            if markdown[index][1] == "bullet"
            and markdown[index + 1][1] == "bullet"
            and not self.block_starts[index + 1]
        }
        rows = build_display_rows(
            rendered_blocks,
            self.comments,
            width=max(1, width - 6),
            spacing=True,
            compact_after=compact_after,
        )
        selected_start, selected_end = self.current_selection()
        selected_row = next(
            index
            for index, (kind, line_index, _) in enumerate(rows)
            if kind == "line" and line_index == self.cursor
        )
        available = content_rows_available(height, reserved_bottom)
        top = max(0, selected_row - available // 2)
        top = min(top, max(0, len(rows) - available))

        for y, (kind, line_index, text) in enumerate(rows[top : top + available], 3):
            if kind == "spacer":
                continue
            if kind in ("comment", "comment_continuation"):
                prefix = _COMMENT_PREFIX if kind == "comment" else " " * len(_COMMENT_PREFIX)
                _safe_addnstr(
                    screen,
                    y,
                    1,
                    prefix + text,
                    inner_width,
                    self.style("comment", curses.A_BOLD) | curses.A_BOLD,
                )
                continue
            block_kind = self.block_kinds[line_index]
            if kind == "line":
                if self.block_starts[line_index]:
                    prefix = {"user": "❯ ", "assistant": "● ", "tool": "  "}.get(
                        block_kind, "● "
                    )
                else:
                    prefix = "  "
            else:
                prefix = "  "
            _rendered, markdown_kind = markdown[line_index]
            if selected_start <= line_index <= selected_end:
                content_attr = self.style("selected", curses.A_REVERSE)
                gutter_attr = content_attr
            else:
                if block_kind == "user":
                    content_attr = self.style("prompt", curses.A_BOLD)
                elif block_kind == "tool":
                    content_attr = self.style("tool")
                else:
                    fallback = curses.A_BOLD if markdown_kind == "heading" else 0
                    content_attr = self.style(markdown_kind, fallback)
                gutter_attr = self.style("marker" if block_kind != "tool" else "tool")
            _safe_addnstr(screen, y, 1, prefix, len(prefix), gutter_attr)
            _safe_addnstr(
                screen,
                y,
                1 + len(prefix),
                text,
                inner_width - len(prefix),
                content_attr,
            )

        _safe_addnstr(
            screen,
            inner_bottom - 2,
            1,
            "─" * inner_width,
            inner_width,
            self.style("muted"),
        )
        status_attr = self.style("error") if self.status.startswith("Error") else self.style("success")
        _safe_addnstr(screen, inner_bottom - 1, 2, self.status, inner_width - 1, status_attr)
        footer = " ↑/↓ move · Space select · y copy · c comment · s send · q close "
        _safe_addnstr(
            screen,
            inner_bottom,
            1,
            footer.ljust(inner_width),
            inner_width,
            self.style("footer", curses.A_REVERSE),
        )
        screen.refresh()

    def edit_comment(self, screen: curses.window) -> None:
        height, width = screen.getmaxyx()
        box_width = width
        box_height = 8
        box_x = 0
        box_y = max(0, height - box_height)
        border_attr = self.style("comment", curses.A_BOLD) | curses.A_BOLD
        badge = " ✎ COMMENT "
        preview = comment_preview(self.lines[self.cursor])
        self.draw(screen, reserved_bottom=box_height)
        editor = curses.newwin(box_height, box_width, box_y, box_x)
        editor.keypad(True)
        original = self.comments.get(self.cursor, "")
        buffer = original.splitlines() or [""]
        row = len(buffer) - 1
        col = len(buffer[row])
        visual_top = 0
        saved = False
        curses.curs_set(1)
        try:
            while True:
                editor.erase()
                _draw_rounded_box(editor, border_attr)
                # Join the editor's top edge to the pane frame above it.
                _safe_addnstr(editor, 0, 0, "├", 1, border_attr)
                _safe_addnstr(editor, 0, box_width - 1, "┤", 1, border_attr)
                _safe_addnstr(
                    editor,
                    0,
                    2,
                    badge,
                    box_width - 4,
                    self.style("comment_badge", curses.A_REVERSE) | curses.A_BOLD,
                )
                label_x = 2 + len(badge)
                _safe_addnstr(
                    editor,
                    0,
                    label_x,
                    f" {preview} ",
                    box_width - label_x - 2,
                    border_attr,
                )
                inner_height = box_height - 3
                inner_width = box_width - 4
                visual_rows = editor_visual_rows(buffer, inner_width)
                cursor_visual_row, cursor_visual_col = editor_cursor_position(
                    visual_rows, row, col
                )
                if cursor_visual_row < visual_top:
                    visual_top = cursor_visual_row
                elif cursor_visual_row >= visual_top + inner_height:
                    visual_top = cursor_visual_row - inner_height + 1
                for screen_row, (_logical, _start, text_line) in enumerate(
                    visual_rows[visual_top : visual_top + inner_height], 1
                ):
                    _safe_addnstr(editor, screen_row, 2, text_line, box_width - 4)
                help_text = " Ctrl+S save · Enter new line · Esc cancel "
                _safe_addnstr(
                    editor,
                    box_height - 1,
                    2,
                    help_text,
                    box_width - 4,
                    self.style("muted"),
                )
                cursor_y = 1 + cursor_visual_row - visual_top
                cursor_x = 2 + min(cursor_visual_col, box_width - 5)
                try:
                    editor.move(cursor_y, cursor_x)
                except curses.error:
                    pass
                editor.refresh()
                key = editor.get_wch()
                if key == "\x13":
                    saved = True
                    break
                if key == "\x1b":
                    current = "\n".join(buffer)
                    if not needs_discard_confirmation(original, current):
                        break
                    curses.curs_set(0)
                    if self.confirm_discard(screen):
                        break
                    curses.curs_set(1)
                    continue
                if key in ("\n", "\r", curses.KEY_ENTER):
                    remainder = buffer[row][col:]
                    buffer[row] = buffer[row][:col]
                    buffer.insert(row + 1, remainder)
                    row += 1
                    col = 0
                elif key in (curses.KEY_BACKSPACE, "\b", "\x7f"):
                    if col > 0:
                        buffer[row] = buffer[row][: col - 1] + buffer[row][col:]
                        col -= 1
                    elif row > 0:
                        previous_length = len(buffer[row - 1])
                        buffer[row - 1] += buffer.pop(row)
                        row -= 1
                        col = previous_length
                elif key == curses.KEY_LEFT:
                    if col > 0:
                        col -= 1
                    elif row > 0:
                        row -= 1
                        col = len(buffer[row])
                elif key == curses.KEY_RIGHT:
                    if col < len(buffer[row]):
                        col += 1
                    elif row + 1 < len(buffer):
                        row += 1
                        col = 0
                elif key == curses.KEY_UP and row > 0:
                    row -= 1
                    col = min(col, len(buffer[row]))
                elif key == curses.KEY_DOWN and row + 1 < len(buffer):
                    row += 1
                    col = min(col, len(buffer[row]))
                elif isinstance(key, str) and key.isprintable():
                    buffer[row] = buffer[row][:col] + key + buffer[row][col:]
                    col += len(key)
        finally:
            curses.curs_set(0)
        if not saved:
            self.status = "Comment edit cancelled"
            return
        text = "\n".join(buffer).strip()
        if text:
            self.comments[self.cursor] = text
            self.status = f"Comment saved on line {self.cursor + 1}"
        else:
            self.comments.pop(self.cursor, None)
            self.status = f"Comment removed from line {self.cursor + 1}"

    def confirm_discard(self, screen: curses.window) -> bool:
        """Return True only when the user explicitly confirms discard."""
        height, width = screen.getmaxyx()
        modal_width = max(38, min(width - 4, 64))
        modal_height = 7
        modal_y = max(0, (height - modal_height) // 2)
        modal_x = max(0, (width - modal_width) // 2)
        modal = curses.newwin(modal_height, modal_width, modal_y, modal_x)
        modal.keypad(True)
        while True:
            modal.erase()
            modal.box()
            _safe_addnstr(
                modal,
                0,
                2,
                " Unsaved comment ",
                modal_width - 4,
                self.style("error", curses.A_BOLD) | curses.A_BOLD,
            )
            _safe_addnstr(
                modal,
                2,
                3,
                "Discard the changes to this comment?",
                modal_width - 6,
            )
            buttons = "[ Enter / n: go back ]    [ y: discard ]"
            _safe_addnstr(
                modal,
                4,
                max(2, (modal_width - len(buttons)) // 2),
                buttons,
                modal_width - 4,
                self.style("comment", curses.A_BOLD),
            )
            _safe_addnstr(
                modal,
                5,
                3,
                "Esc also goes back",
                modal_width - 6,
                self.style("muted"),
            )
            modal.refresh()
            key = modal.get_wch()
            if key in ("y", "Y"):
                return True
            if key in ("n", "N", "\n", "\r", "\x1b", curses.KEY_ENTER):
                return False

    def submit(self, screen: curses.window) -> bool:
        if not self.comments:
            self.status = "Error: add at least one comment before sending"
            curses.beep()
            return False
        self.status = f"Sending {len(self.comments)} comment(s)…"
        self.draw(screen)
        success, error = send_comments(
            self.source_pane, self.lines, self.comments
        )
        if not success:
            self.status = f"Error: {error[:120]}"
            curses.beep()
            return False
        self.status = f"Sent {len(self.comments)} comment(s)"
        self.draw(screen)
        curses.napms(350)
        self.sent = True
        return True


def main() -> None:
    meta = load_meta()
    source_pane = meta.get("SOURCE_PANE_ID") or os.environ.get("HERDR_PANE_ID", "unknown")
    original_termios = None
    if os.isatty(0):
        try:
            original_termios = termios.tcgetattr(0)
            attrs = termios.tcgetattr(0)
            attrs[0] &= ~(termios.IXON | termios.IXOFF)
            termios.tcsetattr(0, termios.TCSANOW, attrs)
        except termios.error:
            original_termios = None
    try:
        curses.set_escdelay(25)
        curses.wrapper(PlainComposer(source_pane, meta).run)
    finally:
        if original_termios is not None:
            try:
                termios.tcsetattr(0, termios.TCSANOW, original_termios)
            except termios.error:
                pass


def log_crash() -> None:
    debug_dir = os.environ.get("OCC_DEBUG_DIR", "/tmp/output-comment-composer-debug")
    try:
        os.makedirs(debug_dir, exist_ok=True)
        with open(os.path.join(debug_dir, "plain-crash.log"), "a", encoding="utf-8") as log:
            log.write(
                f"pid={os.getpid()} TERM={os.environ.get('TERM', '')!r} "
                f"tty_in={os.isatty(0)} tty_out={os.isatty(1)}\n"
            )
            log.write(traceback.format_exc())
            log.write("\n")
    except OSError:
        pass


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        log_crash()
        raise
