#!/usr/bin/env python3
"""Output Comment Composer — Textual TUI rewrite."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Optional

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.color import Color
from textual.containers import Horizontal, Vertical
from textual.events import Key, MouseDown, MouseEvent, MouseMove, MouseUp
from textual.geometry import Region, Size
from textual.message import Message
from textual.screen import ModalScreen
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Button, Footer, Label, TextArea
from textual import work


_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_CODEX_STATUS_RE = re.compile(r"\bcontext\s+\d+%\s+used\b", re.IGNORECASE)
_CODEX_LIMIT_RE = re.compile(r"\b(?:weekly|(?:\d+h))\s+\d+%\s+left\b", re.IGNORECASE)
_CLAUDE_MODE_RE = re.compile(
    r"\b(?:bypass permissions|accept edits|plan mode)\s+on\b.*\bshift\+tab\b",
    re.IGNORECASE,
)
_CLAUDE_COMPOSER_STATUS_RE = re.compile(
    r"\b(?:auto|manual|normal|plan|accept edits|bypass permissions)\s+mode\s+on\b.*\bfor agents\b",
    re.IGNORECASE,
)
_CLAUDE_CONTEXT_STATUS_RE = re.compile(
    r"\borchestrator\b.*\bcont\b.*\d+%.*\b5h\b.*\d+%",
    re.IGNORECASE,
)
_CODEX_PROMPT_RE = re.compile(r"^[›❯>]\s*ask codex to do anything\s*$", re.IGNORECASE)
_CLAUDE_PROMPT_RE = re.compile(r"^[›❯>](?:\s.*)?$")
_CLAUDE_UPDATE_RE = re.compile(r"\bupdate installed\b.*\brestart to update\b", re.IGNORECASE)


def _is_horizontal_separator(line: str) -> bool:
    """Return whether a line is a terminal composer horizontal boundary."""
    plain = _ANSI_ESCAPE_RE.sub("", line).strip().replace(" ", "")
    return len(plain) >= 10 and all(char in "─━—-_═" for char in plain)


def _is_agent_status_line(line: str) -> bool:
    """Return whether a terminal line is a known Codex/Claude status footer."""
    plain = _ANSI_ESCAPE_RE.sub("", line).strip()
    return bool(
        (_CODEX_STATUS_RE.search(plain) and _CODEX_LIMIT_RE.search(plain))
        or _CLAUDE_MODE_RE.search(plain)
    )


def clean_snapshot_lines(lines: list[str]) -> list[str]:
    """Remove agent UI prompt/status footers from the end of a pane snapshot."""
    cleaned = list(lines)

    while True:
        while cleaned and not cleaned[-1].strip():
            cleaned.pop()

        if cleaned and _is_agent_status_line(cleaned[-1]):
            cleaned.pop()
            continue

        plain = _ANSI_ESCAPE_RE.sub("", cleaned[-1]).strip() if cleaned else ""
        if cleaned and (
            _CLAUDE_COMPOSER_STATUS_RE.search(plain)
            or _CLAUDE_CONTEXT_STATUS_RE.search(plain)
        ):
            # Locate the start of either Claude composer layout. Limit the
            # search so response text containing these tokens remains safe.
            footer_start = None
            for index in range(len(cleaned) - 1, max(-1, len(cleaned) - 12), -1):
                candidate = _ANSI_ESCAPE_RE.sub("", cleaned[index]).strip()
                if re.search(r"(?:^|\s)/effort(?:\s|$)", candidate, re.IGNORECASE):
                    footer_start = index
                    break
                if not _is_horizontal_separator(cleaned[index]):
                    continue
                for upper in range(index - 1, max(-1, index - 5), -1):
                    if not _is_horizontal_separator(cleaned[upper]):
                        continue
                    between = [
                        _ANSI_ESCAPE_RE.sub("", line).strip()
                        for line in cleaned[upper + 1 : index]
                    ]
                    if any(_CLAUDE_PROMPT_RE.match(line) for line in between):
                        # The paired rules define the composer even when its
                        # prompt is empty or preceded by an orchestrator label.
                        footer_start = upper
                        if footer_start > 0 and re.search(
                            r"(?:^|\s)/effort(?:\s|$)",
                            _ANSI_ESCAPE_RE.sub("", cleaned[footer_start - 1]),
                            re.IGNORECASE,
                        ):
                            footer_start -= 1
                        if footer_start > 0 and _CLAUDE_UPDATE_RE.search(
                            _ANSI_ESCAPE_RE.sub("", cleaned[footer_start - 1])
                        ):
                            footer_start -= 1
                        break
                if footer_start is not None:
                    break
            if footer_start is None:
                cleaned.pop()
            else:
                del cleaned[footer_start:]
            continue

        if cleaned and _CODEX_PROMPT_RE.match(plain):
            cleaned.pop()
            # Codex draws blank/decorative separator rows above its prompt.
            while cleaned:
                plain = _ANSI_ESCAPE_RE.sub("", cleaned[-1]).strip()
                if plain and re.search(r"\w", plain, re.UNICODE):
                    break
                cleaned.pop()
            continue

        break

    return cleaned


_MARKDOWN_BLOCK_RE = re.compile(r"^(?:[-*+]\s|\d+[.)]\s|>|#{1,6}\s|```|~~~)")
_SENTENCE_END_RE = re.compile(r"[.!?;:]\s*$")


def reflow_wrapped_prose(lines: list[str]) -> list[str]:
    """Join terminal hard-wrap continuations while preserving Markdown blocks."""
    reflowed: list[str] = []
    in_fence = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            reflowed.append(line)
            continue

        previous = reflowed[-1] if reflowed else ""
        should_join = bool(
            not in_fence
            and line[:1].isspace()
            and stripped
            and previous.strip()
            and len(previous.rstrip()) >= 40
            and not _SENTENCE_END_RE.search(previous)
            and not _MARKDOWN_BLOCK_RE.match(stripped)
        )
        if should_join:
            reflowed[-1] = f"{previous.rstrip()} {stripped}"
        else:
            reflowed.append(line)

    return reflowed


# ---------------------------------------------------------------------------
# Metadata loading
# ---------------------------------------------------------------------------


def load_meta_values() -> dict[str, str]:
    """Return the KEY=value pairs written by herdr/pane.sh."""
    values: dict[str, str] = {}
    meta = os.environ.get("OUTPUT_COMMENT_COMPOSER_META", "")
    if meta and os.path.isfile(meta):
        with open(meta, encoding="utf-8", errors="replace") as f:
            for line in f:
                key, sep, value = line.rstrip("\n").partition("=")
                if sep:
                    values[key] = value
    return values


def load_meta() -> str:
    """Return source_pane."""
    source_pane = os.environ.get("HERDR_PANE_ID", "unknown")
    return load_meta_values().get("SOURCE_PANE_ID") or source_pane


# ---------------------------------------------------------------------------
# Claude transcript loading
# ---------------------------------------------------------------------------

_TRANSCRIPT_MAX_LINES = 2000
_SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def find_claude_transcript(session_id: str) -> Optional[str]:
    """Return the JSONL transcript path for a Claude session, if it exists."""
    if not session_id or not _SESSION_ID_RE.match(session_id):
        return None
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    projects = os.path.join(config_dir, "projects")
    try:
        project_dirs = os.listdir(projects)
    except OSError:
        return None
    for project in project_dirs:
        path = os.path.join(projects, project, f"{session_id}.jsonl")
        if os.path.isfile(path):
            return path
    return None


def _user_prompt_text(content: object) -> str:
    """Return the visible text of a user prompt, or "" for tool results/commands."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return ""
        text = "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    else:
        return ""
    text = _SYSTEM_REMINDER_RE.sub("", text).strip()
    if text.startswith(("<command-", "<local-command", "<task-notification")):
        return ""
    return text


def _tool_use_label(block: dict) -> str:
    tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
    detail = (
        tool_input.get("description")
        or tool_input.get("file_path")
        or tool_input.get("pattern")
        or tool_input.get("command")
        or ""
    )
    detail = str(detail).splitlines()[0] if detail else ""
    return f"● {block.get('name', 'tool')}({detail})"


def transcript_lines(entries: list[dict]) -> list[str]:
    """Render Claude transcript entries as plain text lines for the viewer."""
    lines: list[str] = []

    def add_block(marker: str, text: str) -> None:
        if lines:
            lines.append("")
        for index, line in enumerate(text.splitlines() or [""]):
            lines.append(f"{marker} {line}" if index == 0 else f"  {line}")

    for entry in entries:
        if entry.get("isSidechain") or entry.get("isMeta"):
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if entry.get("type") == "user":
            text = _user_prompt_text(content)
            if text:
                add_block("❯", text)
        elif entry.get("type") == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text", "").strip():
                    add_block("●", block["text"].strip())
                elif block.get("type") == "tool_use":
                    if lines:
                        lines.append("")
                    lines.append(_tool_use_label(block))

    return lines[-_TRANSCRIPT_MAX_LINES:]


def _read_jsonl(path: str) -> list[dict]:
    """Read JSONL objects, skipping lines that fail to parse."""
    entries: list[dict] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
    return entries


def read_claude_transcript(path: str) -> list[str]:
    """Read a Claude JSONL transcript as viewer lines."""
    return transcript_lines(_read_jsonl(path))


# ---------------------------------------------------------------------------
# Codex transcript loading
# ---------------------------------------------------------------------------


def find_codex_transcript(session_id: str) -> Optional[str]:
    """Return the rollout JSONL path for a Codex thread, if it exists.

    Codex stores threads as ``sessions/YYYY/MM/DD/rollout-<ts>-<thread_id>.jsonl``.
    """
    if not session_id or not _SESSION_ID_RE.match(session_id):
        return None
    codex_home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    suffix = f"-{session_id}.jsonl"
    newest: Optional[str] = None
    for root, _dirs, files in os.walk(os.path.join(codex_home, "sessions")):
        for name in files:
            if name.startswith("rollout-") and name.endswith(suffix):
                path = os.path.join(root, name)
                if newest is None or path > newest:
                    newest = path
    return newest


def _codex_message_text(payload: dict) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        return ""
    return "\n".join(
        b.get("text", "")
        for b in content
        if isinstance(b, dict) and b.get("type") in ("input_text", "output_text")
    ).strip()


def _codex_tool_detail(payload: dict) -> str:
    """Best-effort one-line summary of a Codex tool call's arguments."""
    raw = payload.get("arguments", payload.get("input", ""))
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            pass
    if isinstance(raw, dict):
        raw = raw.get("description") or raw.get("cmd") or raw.get("command") or raw.get("path") or ""
    if isinstance(raw, list):
        raw = " ".join(str(part) for part in raw)
    lines = str(raw).strip().splitlines()
    return lines[0] if lines else ""


def codex_transcript_lines(entries: list[dict]) -> list[str]:
    """Render Codex rollout entries in the same line format as Claude's."""
    blocks: list[dict] = []
    for entry in entries:
        if entry.get("type") != "response_item":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        kind = payload.get("type")
        if kind == "message" and payload.get("role") == "user":
            text = _codex_message_text(payload)
            # Codex injects AGENTS.md / environment context as user messages.
            if text and not text.startswith(("<", "# AGENTS.md")):
                blocks.append(_user(text))
        elif kind == "message" and payload.get("role") == "assistant":
            text = _codex_message_text(payload)
            if text:
                blocks.append(_assistant_block({"type": "text", "text": text}))
        elif kind in ("function_call", "custom_tool_call", "local_shell_call"):
            name = payload.get("name") or "shell"
            blocks.append(
                _assistant_block(
                    {"type": "tool_use", "name": name, "input": {"description": _codex_tool_detail(payload)}}
                )
            )
    return transcript_lines(blocks)


def _user(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _assistant_block(block: dict) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": [block]}}


def read_codex_transcript(path: str) -> list[str]:
    """Read a Codex rollout JSONL as viewer lines."""
    return codex_transcript_lines(_read_jsonl(path))


# ---------------------------------------------------------------------------
# Markdown display styling (transcript snapshots only)
# ---------------------------------------------------------------------------

_PROMPT_STYLE = Style(color="#a5b4fc")
_MARKER_STYLE = Style(color="white", bold=True)
_TOOL_MARKER_STYLE = Style(color="green", bold=True)
_TOOL_NAME_STYLE = Style(bold=True)
_TOOL_DETAIL_STYLE = Style(color="grey62")
_HEADING_STYLE = Style(color="#c4b5fd", bold=True)
_CODE_STYLE = Style(color="#fbbf24")
_FENCE_STYLE = Style(color="grey42")
_QUOTE_STYLE = Style(color="grey62", italic=True)
_BOLD_STYLE = Style(bold=True)
_ITALIC_STYLE = Style(italic=True)

_TOOL_LINE_RE = re.compile(r"^● ([A-Za-z0-9_.:-]+)\((.*)\)$")
_HEADING_RE = re.compile(r"^(\s*)#{1,6}\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+")
_RULE_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_INLINE_RE = re.compile(r"`([^`]+)`|\*\*(.+?)\*\*|__(.+?)__|(?<![\w*])\*(?!\s)([^*]+?)(?<!\s)\*(?![\w*])")


def _append_inline_markdown(text: Text, body: str) -> None:
    """Append ``body`` to ``text`` with inline code/bold/italic markers styled."""
    position = 0
    for match in _INLINE_RE.finditer(body):
        text.append(body[position : match.start()])
        code, bold, bold_alt, italic = match.groups()
        if code is not None:
            text.append(code, _CODE_STYLE)
        elif italic is not None:
            text.append(italic, _ITALIC_STYLE)
        else:
            text.append(bold if bold is not None else bold_alt, _BOLD_STYLE)
        position = match.end()
    text.append(body[position:])


def style_transcript_lines(lines: list[str]) -> list[Text]:
    """Return display text for transcript lines, rendering basic Markdown.

    Lines come from ``transcript_lines``: a block starts with ``❯ `` (user
    prompt) or ``● `` (agent text/tool) and continues with a two-space indent.
    User prompts are shown verbatim; agent text gets inline and block Markdown.
    """
    styled: list[Text] = []
    block = ""
    in_fence = False

    for line in lines:
        if line.startswith("❯ "):
            block, in_fence = "user", False
            text = Text("❯ ", _MARKER_STYLE)
            text.append(line[2:], _PROMPT_STYLE)
            styled.append(text)
            continue

        tool = _TOOL_LINE_RE.match(line)
        if tool:
            block, in_fence = "tool", False
            text = Text("● ", _TOOL_MARKER_STYLE)
            text.append(tool.group(1), _TOOL_NAME_STYLE)
            text.append(f"({tool.group(2)})", _TOOL_DETAIL_STYLE)
            styled.append(text)
            continue

        if line.startswith("● "):
            block, in_fence = "agent", False
            text = Text("● ", _MARKER_STYLE)
            body = line[2:]
        elif line.startswith("  "):
            text = Text("  ")
            body = line[2:]
        else:
            styled.append(Text(line))
            continue

        if block == "user":
            text.append(body, _PROMPT_STYLE)
        elif body.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            text.append(body, _FENCE_STYLE)
        elif in_fence:
            text.append(body, _CODE_STYLE)
        elif _RULE_RE.match(body):
            text.append(body, _FENCE_STYLE)
        elif heading := _HEADING_RE.match(body):
            text.append(heading.group(1))
            text.append(heading.group(2), _HEADING_STYLE)
        elif body.lstrip().startswith(">"):
            text.append(body, _QUOTE_STYLE)
        else:
            bullet = _BULLET_RE.match(body)
            if bullet:
                text.append(f"{bullet.group(1)}• ")
                body = body[bullet.end() :]
            _append_inline_markdown(text, body)
        styled.append(text)

    return styled


def wrap_offsets(plain: str, width: int) -> list[int]:
    """Return cut offsets that word-wrap ``plain`` to ``width`` cells."""
    offsets: list[int] = []
    start = 0
    while len(plain) - start > width:
        cut = plain.rfind(" ", start, start + width + 1)
        cut = cut + 1 if cut > start else start + width
        offsets.append(cut)
        start = cut
    return offsets


# ---------------------------------------------------------------------------
# Snapshot viewer widget
# ---------------------------------------------------------------------------

_LINENO_STYLE = Style(color="grey50")
_SEP_STYLE = Style(color="grey35")
_CONTENT_STYLE = Style()
_SELECTED_BG = Color.parse("#1a3a1a")  # dark green tint
_SELECTED_STYLE = Style(bgcolor=_SELECTED_BG.rich_color)


class SnapshotViewer(ScrollView):
    """Scrollable line viewer with mouse-drag selection."""

    class SelectionCompleted(Message):
        """Posted when a mouse selection is ready to be annotated."""

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("shift+down", "extend_down", "Extend", show=False),
        Binding("shift+up", "extend_up", "Extend", show=False),
    ]

    def __init__(self, lines: list[str], comments_ref: list[tuple[int, int, str]] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.snap_lines = lines
        # True when snap_lines come from an agent transcript (Markdown source).
        self.markdown = False
        self.comments_ref = comments_ref if comments_ref is not None else []
        self.sel_start: Optional[int] = None
        self.sel_end: Optional[int] = None
        self._drag_anchor: Optional[int] = None
        self._dragging = False
        self._row_map: list[tuple[str, tuple]] = []
        self._wrap_width: int = 0
        self._kb_cursor: int = 0
        self._kb_anchor: Optional[int] = None
        self._refresh_row_map()

    def _refresh_row_map(self, wrap_width: int = 0) -> None:
        """Build row map with word-wrap support.

        Each row is one of:
          ('line_chunk', (line_idx, chunk_idx, chunk_text: Text))
          ('annotation', (text,))
        """
        self._wrap_width = wrap_width
        lineno_width = max(3, len(str(max(len(self.snap_lines), 1))))
        sep_width = 3  # " │ "
        avail = wrap_width - lineno_width - sep_width if wrap_width > lineno_width + sep_width + 12 else 0

        after: dict[int, str] = {}
        for s, e, text in self.comments_ref:
            after[e] = text

        expanded = [line.replace("\t", "    ") for line in self.snap_lines]
        if self.markdown:
            display = style_transcript_lines(expanded)
        else:
            display = [Text(line) for line in expanded]

        rows: list[tuple[str, tuple]] = []
        for i, content in enumerate(display):
            if avail > 0 and content.cell_len > avail:
                chunks = list(content.divide(wrap_offsets(content.plain, avail))) or [Text()]
            else:
                chunks = [content]
            for ci, chunk in enumerate(chunks):
                rows.append(("line_chunk", (i, ci, chunk)))
            if i in after:
                rows.append(("annotation", (after[i],)))
        self._row_map = rows
        if self.snap_lines:
            self._kb_cursor = max(0, min(self._kb_cursor, len(self.snap_lines) - 1))
        else:
            self._kb_cursor = 0
        if self.is_mounted:
            w = wrap_width or self.size.width
            self.virtual_size = Size(w, len(self._row_map))

    def on_resize(self) -> None:
        self._refresh_row_map(self.size.width)
        self.refresh(layout=True)

    # ------------------------------------------------------------------
    # ScrollView protocol
    # ------------------------------------------------------------------

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        if width != self._wrap_width:
            self._refresh_row_map(width)
        return len(self._row_map)

    def render_line(self, y: int) -> Strip:
        row_idx = y + int(self.scroll_offset.y)
        if row_idx < 0 or row_idx >= len(self._row_map):
            return Strip.blank(self.size.width)

        kind, value = self._row_map[row_idx]
        width = self.size.width
        lineno_width = max(3, len(str(max(len(self.snap_lines), 1))))

        if kind == "annotation":
            prefix = " " * lineno_width + "   ╰─ "
            avail = max(1, width - len(prefix) - 1)
            text = str(value[0]).replace("\n", " ")
            if len(text) > avail:
                text = text[:avail - 1] + "…"
            annotation_style = Style(color="yellow", italic=True)
            seg = Segment(prefix + text, annotation_style)
            strip = Strip([seg]).extend_cell_length(width, annotation_style)
            return strip.crop(0, width)

        # kind == "line_chunk"
        line_idx, chunk_idx, content = value
        if line_idx < 0 or line_idx >= len(self.snap_lines):
            return Strip.blank(width)

        selected = (
            self.sel_start is not None
            and self.sel_end is not None
            and self.sel_start <= line_idx <= self.sel_end
        )

        has_comment = any(s <= line_idx <= e for s, e, _ in self.comments_ref)

        if chunk_idx == 0:
            if has_comment:
                lineno_str = f"●{line_idx + 1:>{lineno_width - 1}}"
                lineno_style = Style(color="yellow")
            else:
                lineno_str = f"{line_idx + 1:>{lineno_width}}"
                lineno_style = _LINENO_STYLE
        else:
            # Continuation line: blank lineno + wrap indicator
            lineno_str = " " * (lineno_width - 1) + "↳"
            lineno_style = _LINENO_STYLE

        sep = " │ "
        content_segments = list(content.render(self.app.console))

        if selected:
            segments = [
                Segment(lineno_str, lineno_style + _SELECTED_STYLE),
                Segment(sep, _SEP_STYLE + _SELECTED_STYLE),
                *Segment.apply_style(content_segments, post_style=_SELECTED_STYLE),
            ]
            strip = Strip(segments).extend_cell_length(width, _SELECTED_STYLE)
        else:
            segments = [
                Segment(lineno_str, lineno_style),
                Segment(sep, _SEP_STYLE),
                *Segment.apply_style(content_segments, _CONTENT_STYLE),
            ]
            strip = Strip(segments).extend_cell_length(width)

        return strip.crop(0, width)

    # ------------------------------------------------------------------
    # Mouse selection
    # ------------------------------------------------------------------

    def _debug_mouse_event(self, event: MouseEvent, line: Optional[int]) -> None:
        """Write raw mouse geometry when debug logging is enabled."""
        debug_dir = os.environ.get("OCC_DEBUG_DIR", "")
        if not debug_dir:
            return
        try:
            os.makedirs(debug_dir, exist_ok=True)
            with open(os.path.join(debug_dir, "mouse.log"), "a", encoding="utf-8") as log:
                log.write(
                    f"{type(event).__name__} x={event.x} y={event.y} "
                    f"screen=({event.screen_x},{event.screen_y}) "
                    f"region={self.region} content={self.content_region} "
                    f"scroll={self.scroll_offset} line={line}\n"
                )
        except OSError:
            pass

    def _y_to_line(self, event: MouseEvent) -> Optional[int]:
        """Map a mouse event to a logical snapshot line.

        ``event.y`` is relative to the widget that forwarded the event.  That
        coordinate became unreliable for plugin panes/zoomed overlays (it can
        remain at the top of the viewport), so use the screen coordinate and
        Textual's actual content region instead.  The content-region origin
        already accounts for the border; add the ScrollView offset exactly
        once to get the virtual row.
        """
        content_offset = event.get_content_offset_capture(self)
        row_idx = content_offset.y + int(self.scroll_offset.y)
        if row_idx < 0 or row_idx >= len(self._row_map):
            return None
        kind, value = self._row_map[row_idx]
        if kind == "annotation":
            return None
        return value[0]  # line_idx

    def on_mouse_down(self, event: MouseDown) -> None:
        if event.button != 1:
            return
        line = self._y_to_line(event)
        self._debug_mouse_event(event, line)
        if line is None:
            return
        self._drag_anchor = line
        self._dragging = True
        # Keep receiving move/up events while the pointer leaves the exact
        # cell where the drag started. This is required by overlay/plugin
        # panes, where the parent screen otherwise retargets the event.
        self.capture_mouse()
        self.sel_start = line
        self.sel_end = line
        self.refresh()
        event.stop()

    def on_mouse_move(self, event: MouseMove) -> None:
        if not self._dragging or self._drag_anchor is None:
            return
        line = self._y_to_line(event)
        self._debug_mouse_event(event, line)
        if line is None:
            return
        a, b = sorted((self._drag_anchor, line))
        self.sel_start = a
        self.sel_end = b
        self.refresh()
        event.stop()

    def on_mouse_up(self, event: MouseUp) -> None:
        if not self._dragging:
            return
        line = self._y_to_line(event)
        self._debug_mouse_event(event, line)
        if line is not None and self._drag_anchor is not None:
            a, b = sorted((self._drag_anchor, line))
            self.sel_start = a
            self.sel_end = b
        self._dragging = False
        self._drag_anchor = None
        self.release_mouse()
        self.refresh()
        event.stop()
        self._request_comment_for_selection()

    def _request_comment_for_selection(self) -> None:
        if self.has_selection():
            self.post_message(self.SelectionCompleted())

    # ------------------------------------------------------------------
    # Keyboard scroll helpers
    # ------------------------------------------------------------------

    def _clamp_cursor(self, line_idx: int) -> int:
        if not self.snap_lines:
            return 0
        return max(0, min(line_idx, len(self.snap_lines) - 1))

    def action_cursor_down(self) -> None:
        self._kb_anchor = None
        self._kb_cursor = self._clamp_cursor(self._kb_cursor + 1)
        self.sel_start = self.sel_end = self._kb_cursor
        self.refresh()
        self._scroll_kb_cursor_into_view()

    def action_cursor_up(self) -> None:
        self._kb_anchor = None
        self._kb_cursor = self._clamp_cursor(self._kb_cursor - 1)
        self.sel_start = self.sel_end = self._kb_cursor
        self.refresh()
        self._scroll_kb_cursor_into_view()

    def action_extend_down(self) -> None:
        if self._kb_anchor is None:
            self._kb_anchor = self._kb_cursor
        self._kb_cursor = self._clamp_cursor(self._kb_cursor + 1)
        self.sel_start, self.sel_end = sorted((self._kb_anchor, self._kb_cursor))
        self.refresh()
        self._scroll_kb_cursor_into_view()

    def action_extend_up(self) -> None:
        if self._kb_anchor is None:
            self._kb_anchor = self._kb_cursor
        self._kb_cursor = self._clamp_cursor(self._kb_cursor - 1)
        self.sel_start, self.sel_end = sorted((self._kb_anchor, self._kb_cursor))
        self.refresh()
        self._scroll_kb_cursor_into_view()

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def has_selection(self) -> bool:
        return self.sel_start is not None and self.sel_end is not None

    def _line_to_row(self, line_idx: int) -> Optional[int]:
        """Return the row in ``_row_map`` for ``line_idx`` (annotation row if present)."""
        line_rows = [
            index
            for index, (kind, value) in enumerate(self._row_map)
            if kind == "line_chunk" and value[0] == line_idx
        ]
        if not line_rows:
            return None
        last_line_row = line_rows[-1]
        annotation_row = last_line_row + 1
        if (
            annotation_row < len(self._row_map)
            and self._row_map[annotation_row][0] == "annotation"
        ):
            return annotation_row
        return last_line_row

    def _selection_target_row(self) -> Optional[int]:
        """Return the row containing the selected line's annotation or text."""
        if self.sel_end is None:
            return None
        return self._line_to_row(self.sel_end)

    def scroll_selection_into_view(self) -> None:
        """Center the selected line/comment after the editor closes."""
        target_row = self._selection_target_row()
        if target_row is None:
            return
        self.scroll_to_region(
            Region(0, target_row, max(1, self.size.width), 1),
            center=True,
            animate=False,
            force=True,
            immediate=True,
            x_axis=False,
        )

    def reveal_selection_for_editing(self) -> None:
        """Keep the selected lines readable while the comment editor is open.

        Center the selection when it fits the viewport; otherwise align its
        first line to the top so the user can read it from the start.
        """
        if self.sel_start is None or self.sel_end is None:
            return
        first_rows = [
            index
            for index, (kind, value) in enumerate(self._row_map)
            if kind == "line_chunk" and value[0] == self.sel_start
        ]
        last_row = self._line_to_row(self.sel_end)
        if not first_rows or last_row is None:
            return
        first_row = first_rows[0]
        height = last_row - first_row + 1
        if height <= self.scrollable_content_region.height:
            region = Region(0, first_row, max(1, self.size.width), height)
            self.scroll_to_region(
                region, center=True, animate=False, force=True, immediate=True, x_axis=False
            )
        else:
            self.scroll_to(y=first_row, animate=False, force=True, immediate=True)

    def _scroll_kb_cursor_into_view(self) -> None:
        """Keep the keyboard cursor line visible in the viewport."""
        target_row = self._line_to_row(self._kb_cursor)
        if target_row is None:
            return
        self.scroll_to_region(
            Region(0, target_row, max(1, self.size.width), 1),
            animate=False,
            force=False,
            immediate=True,
            x_axis=False,
        )

    def selection_label(self) -> str:
        if not self.has_selection():
            return ""
        assert self.sel_start is not None and self.sel_end is not None
        if self.sel_start == self.sel_end:
            return f"line {self.sel_start + 1}"
        return f"lines {self.sel_start + 1}–{self.sel_end + 1}"


# ---------------------------------------------------------------------------
# Comment input widget
# ---------------------------------------------------------------------------


class CommentInput(TextArea):
    """Multi-line TextArea with ctrl+s=save, escape=cancel."""

    BINDINGS = [
        Binding("ctrl+s", "save_comment", "Save", show=False),
        Binding("escape", "cancel_comment", "Cancel", show=False),
    ]

    def action_save_comment(self) -> None:
        self.app.save_comment()  # type: ignore[attr-defined]

    def action_cancel_comment(self) -> None:
        self.app.cancel_comment()  # type: ignore[attr-defined]

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            self.insert("\n")
            event.stop()
            event.prevent_default()


class ConfirmScreen(ModalScreen[bool]):
    """Yes/no modal used before discarding comments.

    "Voltar" is focused first so a stray Enter never discards anything.
    """

    BINDINGS = [
        Binding("y", "answer(True)", "yes", show=False),
        Binding("n", "answer(False)", "no", show=False),
        Binding("escape", "answer(False)", "no", show=False),
        Binding("left", "focus_previous", "previous", show=False),
        Binding("right", "focus_next", "next", show=False),
    ]

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
        background: $background 60%;
    }

    #confirm-box {
        width: 60;
        height: auto;
        border: heavy $warning;
        background: $panel;
        padding: 1 2;
    }

    #confirm-question {
        width: 100%;
        margin-bottom: 1;
    }

    #confirm-buttons {
        width: 100%;
        height: auto;
        align-horizontal: center;
    }

    #confirm-buttons Button {
        margin: 0 2;
    }
    """

    def __init__(self, question: str, confirm_label: str = "Sair e descartar") -> None:
        super().__init__()
        self.question = question
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(self.question, id="confirm-question")
            with Horizontal(id="confirm-buttons"):
                yield Button(" Voltar (n) ", id="confirm-no", variant="primary", compact=True)
                yield Button(f" {self.confirm_label} (y) ", id="confirm-yes", variant="error", compact=True)

    def on_mount(self) -> None:
        self.query_one("#confirm-no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "confirm-yes")

    def action_answer(self, answer: bool) -> None:
        self.dismiss(answer)

    def action_focus_previous(self) -> None:
        self.focus_previous()

    def action_focus_next(self) -> None:
        self.focus_next()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def _register_round_dashed_border() -> str:
    """Register a light dashed border with rounded corners; return its name.

    Textual has no public API for custom borders, so this extends its
    internal tables (verified on Textual 8.2). If they change, fall back to
    the built-in heavy ``dashed`` border so the pane still opens.
    """
    try:
        from textual import _border
        from textual.css import constants

        _border.BORDER_CHARS["round-dashed"] = (
            ("╭", "╌", "╮"),
            ("╎", " ", "╎"),
            ("╰", "╌", "╯"),
        )
        _border.BORDER_LOCATIONS["round-dashed"] = _border.BORDER_LOCATIONS["round"]
        _border.BORDER_LABEL_LOCATIONS["round-dashed"] = _border.BORDER_LABEL_LOCATIONS["round"]
        constants.VALID_BORDER.add("round-dashed")
        return "round-dashed"
    except Exception:
        return "dashed"


_VIEWER_BORDER = _register_round_dashed_border()

_APP_CSS = """
Screen {
    background: transparent;
    layers: base overlay;
}

#viewer {
    height: 1fr;
    border: __VIEWER_BORDER__ #22c55e;
    overflow-x: hidden;
    scrollbar-size-vertical: 1;
}

#comment-panel {
    height: auto;
    max-height: 14;
    border: solid $success;
    display: none;
    padding: 0 1;
}

#comment-panel.visible {
    display: block;
}

#comment-label {
    color: $success;
    height: 1;
    padding: 0 0;
}

#comment-input {
    height: auto;
    min-height: 3;
    max-height: 10;
    background: $panel;
    border: none;
    color: $text;
}

#comment-hint {
    color: $text-muted;
    height: 1;
    text-align: right;
}

Footer {
    background: #1a1730;
    color: #a5b4fc;
}

FooterKey {
    background: #312e81;
    color: #c7d2fe;
}
""".replace("__VIEWER_BORDER__", _VIEWER_BORDER)


class ComposerApp(App[None]):
    CSS = _APP_CSS
    TITLE = "output-comment-composer"

    BINDINGS = [
        Binding("c", "open_comment", "comment", show=True),
        Binding("s", "send_comments", "send", show=True),
        Binding("q", "quit", "quit", show=True),
        Binding("escape", "quit", "quit", show=False),
    ]

    class SnapshotReady(Message):
        def __init__(self, lines: list[str], markdown: bool = False) -> None:
            super().__init__()
            self.lines = lines
            self.markdown = markdown

    def __init__(self):
        super().__init__()
        self.source_pane = load_meta()
        self.snap_lines: list[str] = []
        self.comments: list[tuple[int, int, str]] = []
        self._editing_comment_idx: Optional[int] = None
        self._draft_original: str = ""
        self._meta_dir: str = ""
        meta = os.environ.get("OUTPUT_COMMENT_COMPOSER_META", "")
        if meta:
            self._meta_dir = os.path.dirname(meta)

    # ------------------------------------------------------------------
    # Async snapshot fetch
    # ------------------------------------------------------------------

    @work
    async def _fetch_snapshot(self) -> None:
        import asyncio
        try:
            lines, markdown = await asyncio.to_thread(self._do_fetch)
        except Exception as e:
            debug_dir = os.environ.get("OCC_DEBUG_DIR", "")
            if debug_dir:
                with open(os.path.join(debug_dir, "bash.log"), "a") as f:
                    f.write(f"py:fetch-exception {e}\n")
            lines, markdown = [f"Error loading snapshot: {e}"], False
        self.post_message(self.SnapshotReady(lines, markdown))

    def _do_fetch(self) -> tuple[list[str], bool]:
        """Return (lines, is_markdown_transcript)."""
        # herdr only keeps the visible screen for fullscreen (alt-screen)
        # agents, so prefer the full agent transcript when there is one.
        lines = self._fetch_transcript()
        if lines:
            return lines, True
        return self._fetch_pane_read(), False

    def _fetch_transcript(self) -> list[str]:
        meta = load_meta_values()
        session_id = meta.get("SESSION_ID", "")
        agent = meta.get("AGENT", "")
        if agent in ("", "claude"):
            find, read = find_claude_transcript, read_claude_transcript
        elif agent == "codex":
            find, read = find_codex_transcript, read_codex_transcript
        else:
            return []
        path = find(session_id)
        if not path:
            return []
        try:
            return read(path)
        except OSError:
            return []

    def _fetch_pane_read(self) -> list[str]:
        herdr = os.environ.get("HERDR_BIN_PATH", "herdr")
        result = subprocess.run(
            [
                herdr,
                "pane",
                "read",
                self.source_pane,
                "--source",
                "recent-unwrapped",
                "--lines",
                "500",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return ["Failed to read pane."]
        lines = clean_snapshot_lines(result.stdout.splitlines())
        return reflow_wrapped_prose(lines)

    def on_composer_app_snapshot_ready(self, message: SnapshotReady) -> None:
        self.snap_lines = message.lines
        viewer = self.query_one("#viewer", SnapshotViewer)
        viewer.snap_lines = self.snap_lines
        viewer.markdown = message.markdown
        viewer._kb_cursor = len(viewer.snap_lines) - 1 if viewer.snap_lines else 0
        viewer._refresh_row_map(viewer.size.width)
        self.screen.refresh(layout=True)
        viewer.scroll_end(animate=False)
        viewer.focus()
        viewer = self.query_one("#viewer", SnapshotViewer)
        viewer.border_subtitle = "@andpeicunha"

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield SnapshotViewer(["Loading…"], comments_ref=self.comments, id="viewer")
        with Vertical(id="comment-panel"):
            yield Label("comment", id="comment-label")
            yield CommentInput("", language=None, id="comment-input", soft_wrap=True)
            yield Label("ctrl+s save · esc cancel", id="comment-hint")
        yield Footer()

    # ------------------------------------------------------------------
    # Subtitle / title update
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        viewer = self.query_one("#viewer", SnapshotViewer)
        viewer.border_title = f"source: {self.source_pane}"
        viewer.border_subtitle = "@andpeicunha · loading…"
        self._fetch_snapshot()

    # ------------------------------------------------------------------
    # Comment panel open/close
    # ------------------------------------------------------------------

    def action_open_comment(self) -> None:
        viewer = self.query_one("#viewer", SnapshotViewer)
        if not viewer.has_selection():
            self.notify("Select lines first (mouse drag)", severity="warning")
            return

        # Find existing comment for this selection
        self._editing_comment_idx = None
        existing_text = ""
        for i, (s, e, text) in enumerate(self.comments):
            if s == viewer.sel_start and e == viewer.sel_end:
                self._editing_comment_idx = i
                existing_text = text
                break

        panel = self.query_one("#comment-panel")
        label = self.query_one("#comment-label", Label)
        mode = "edit comment" if self._editing_comment_idx is not None else "comment"
        label.update(f"{mode} · {viewer.selection_label()}")
        panel.add_class("visible")
        inp = self.query_one("#comment-input", CommentInput)
        inp.clear()
        if existing_text:
            inp.insert(existing_text)
        self._draft_original = existing_text
        inp.focus()
        # Opening the panel shrinks the viewer, which can hide the selection
        # behind it. Re-reveal the selection once the new layout is in place.
        self.call_after_refresh(self._reveal_selection_after_open, viewer)

    def _reveal_selection_after_open(self, viewer: SnapshotViewer) -> None:
        viewer._refresh_row_map(viewer.size.width)
        viewer.refresh(layout=True)
        self.call_after_refresh(viewer.reveal_selection_for_editing)

    def on_snapshot_viewer_selection_completed(
        self, _message: SnapshotViewer.SelectionCompleted
    ) -> None:
        """Open the editor immediately after a mouse selection."""
        self.action_open_comment()

    def save_comment(self) -> None:
        viewer = self.query_one("#viewer", SnapshotViewer)
        inp = self.query_one("#comment-input", CommentInput)
        text = inp.text.strip()
        panel = self.query_one("#comment-panel")

        if viewer.has_selection():
            assert viewer.sel_start is not None and viewer.sel_end is not None
            if self._editing_comment_idx is not None:
                if text:
                    # Replace existing
                    self.comments[self._editing_comment_idx] = (viewer.sel_start, viewer.sel_end, text)
                    self.notify(
                        f"Comment updated ({viewer.selection_label()})",
                        severity="information",
                    )
                else:
                    # Empty text = delete
                    del self.comments[self._editing_comment_idx]
                    self.notify(
                        f"Comment removed ({viewer.selection_label()})",
                        severity="warning",
                    )
                self._editing_comment_idx = None
            elif text:
                self.comments.append((viewer.sel_start, viewer.sel_end, text))
                self.notify(
                    f"Comment stored ({viewer.selection_label()})",
                    severity="information",
                )

            viewer = self.query_one("#viewer", SnapshotViewer)
            viewer.border_subtitle = f"@andpeicunha · {len(self.comments)} comment(s)"
            viewer._refresh_row_map(viewer.size.width)
            viewer.refresh(layout=True)

        panel.remove_class("visible")
        inp.clear()
        viewer.focus()
        # Closing the panel resizes the viewer asynchronously. Wait for that
        # layout pass, rebuild against the final dimensions, then scroll on a
        # second refresh so the resize cannot overwrite the target offset.
        self.call_after_refresh(self._restore_saved_comment_position, viewer)

    def _restore_saved_comment_position(self, viewer: SnapshotViewer) -> None:
        viewer._refresh_row_map(viewer.size.width)
        viewer.refresh(layout=True)
        self.call_after_refresh(viewer.scroll_selection_into_view)

    def cancel_comment(self) -> None:
        draft = self.query_one("#comment-input", CommentInput).text.strip()
        if draft and draft != self._draft_original.strip():
            self.push_screen(
                ConfirmScreen("Descartar o texto deste comentário?", "Descartar"),
                lambda discard: self._discard_comment() if discard else None,
            )
            return
        self._discard_comment()

    def _discard_comment(self) -> None:
        panel = self.query_one("#comment-panel")
        panel.remove_class("visible")
        inp = self.query_one("#comment-input", CommentInput)
        inp.clear()
        self.query_one("#viewer", SnapshotViewer).focus()

    # ------------------------------------------------------------------
    # Send logic (identical to original)
    # ------------------------------------------------------------------

    def _build_prompt(self) -> str:
        parts = ["Please address these comments on your previous output:"]
        for i, (s, e, comment) in enumerate(self.comments, 1):
            raw_lines = self.snap_lines[s : e + 1]
            if raw_lines:
                quote = "\n".join(f"> {line}" if line.strip() else ">" for line in raw_lines)
            else:
                quote = f"> [linha {s + 1}" + (f"–{e + 1}" if e != s else "") + ": fora do snapshot]"
            parts.append(
                f"Comment {i} on lines {s + 1}–{e + 1}:\n\n"
                f"{quote}\n\n"
                f"Comment:\n{comment}"
            )
        return "\n\n".join(parts) + "\n\n— @andpeicunha\n"

    def action_send_comments(self) -> None:
        if not self.comments:
            self.notify("No comments yet — add one with c", severity="warning")
            return
        if not self.source_pane or self.source_pane == "unknown":
            self.notify("Cannot send: source pane unknown", severity="error")
            return
        prompt = self._build_prompt()
        herdr = os.environ.get("HERDR_BIN_PATH", "herdr")
        result = subprocess.run(
            [herdr, "agent", "prompt", self.source_pane, prompt],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            r2 = subprocess.run(
                [herdr, "pane", "send-text", self.source_pane, prompt],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            if r2.returncode == 0:
                subprocess.run(
                    [herdr, "agent", "send-keys", self.source_pane, "Enter"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            else:
                err = (result.stderr or r2.stderr or "").strip()
                self.notify(
                    f"Send failed: {err[:120]}" if err else "Send failed",
                    severity="error",
                    timeout=6,
                )
                return
        self.notify(f"Sent {len(self.comments)} comment(s)", severity="information")
        self._cleanup()
        self.exit()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup(self) -> None:
        if self._meta_dir and os.path.isdir(self._meta_dir):
            try:
                shutil.rmtree(self._meta_dir)
            except OSError:
                pass

    def action_quit(self) -> None:
        # Only quit when comment panel is hidden; otherwise let escape cancel comment
        panel = self.query_one("#comment-panel")
        if "visible" in panel.classes:
            return
        if self.comments:
            count = len(self.comments)
            noun = "comentário" if count == 1 else "comentários"
            self.push_screen(
                ConfirmScreen(f"Você tem {count} {noun} não enviado(s). Sair e perder?"),
                lambda leave: self._exit_now() if leave else None,
            )
            return
        self._exit_now()

    def _exit_now(self) -> None:
        self._cleanup()
        self.exit()

    def on_unmount(self) -> None:
        self._cleanup()


if __name__ == "__main__":
    ComposerApp().run()
