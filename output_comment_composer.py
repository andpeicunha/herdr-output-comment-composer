#!/usr/bin/env python3
"""Output Comment Composer — Textual TUI rewrite."""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
from typing import Optional

from rich.segment import Segment
from rich.style import Style
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.color import Color
from textual.containers import Vertical
from textual.events import Key, MouseDown, MouseMove, MouseUp
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Footer, Label, TextArea
from textual import work


# ---------------------------------------------------------------------------
# Metadata loading
# ---------------------------------------------------------------------------


def load_meta() -> tuple[str, str, str, str]:
    """Return (source_pane, session_id, source_cwd, agent)."""
    source_pane = os.environ.get("HERDR_PANE_ID", "unknown")
    session_id = ""
    source_cwd = ""
    agent = ""
    meta = os.environ.get("OUTPUT_COMMENT_COMPOSER_META", "")
    if meta and os.path.isfile(meta):
        with open(meta, encoding="utf-8", errors="replace") as f:
            for line in f:
                key, sep, value = line.rstrip("\n").partition("=")
                if not sep:
                    continue
                if key == "SOURCE_PANE_ID":
                    source_pane = value or source_pane
                elif key == "SESSION_ID":
                    session_id = value
                elif key == "SOURCE_CWD":
                    source_cwd = value
                elif key == "AGENT":
                    agent = value
    return source_pane, session_id, source_cwd, agent


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

    BINDINGS = [
        Binding("j", "scroll_down_line", "Down", show=False),
        Binding("k", "scroll_up_line", "Up", show=False),
    ]

    def __init__(self, lines: list[str], comments_ref: list[tuple[int, int, str]] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.snap_lines = lines
        self.comments_ref = comments_ref if comments_ref is not None else []
        self.sel_start: Optional[int] = None
        self.sel_end: Optional[int] = None
        self._drag_anchor: Optional[int] = None
        self._dragging = False
        self._row_map: list[tuple[str, int | str]] = []
        self._refresh_row_map()

    def _refresh_row_map(self) -> None:
        """Build row map from comments_ref. Each row is ('line', line_idx) or ('annotation', text)."""
        # Map from line_idx -> comment text (last comment wins if overlapping)
        after: dict[int, str] = {}
        for s, e, text in self.comments_ref:
            after[e] = text
        rows: list[tuple[str, int | str]] = []
        for i in range(len(self.snap_lines)):
            rows.append(("line", i))
            if i in after:
                rows.append(("annotation", after[i]))
        self._row_map = rows

    # ------------------------------------------------------------------
    # ScrollView protocol
    # ------------------------------------------------------------------

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return len(self._row_map)

    def render_line(self, y: int) -> Strip:
        row_idx = y + int(self.scroll_offset.y)
        if row_idx < 0 or row_idx >= len(self._row_map):
            return Strip.blank(self.size.width)

        kind, value = self._row_map[row_idx]
        width = self.size.width
        lineno_width = max(3, len(str(len(self.snap_lines))))

        if kind == "annotation":
            # Render comment text line: "  ╰─ <truncated text>"
            prefix = " " * lineno_width + "   ╰─ "
            avail = width - len(prefix) - 1
            text = str(value).replace("\n", " ")
            if len(text) > avail:
                text = text[:avail - 1] + "…"
            annotation_style = Style(color="yellow", italic=True)
            seg = Segment(prefix + text, annotation_style)
            strip = Strip([seg]).extend_cell_length(width, annotation_style)
            return strip.crop(0, width)

        # kind == "line"
        line_idx = value
        assert isinstance(line_idx, int)
        if line_idx < 0 or line_idx >= len(self.snap_lines):
            return Strip.blank(width)

        content = self.snap_lines[line_idx].replace("\t", "    ")

        selected = (
            self.sel_start is not None
            and self.sel_end is not None
            and self.sel_start <= line_idx <= self.sel_end
        )

        has_comment = any(s <= line_idx <= e for s, e, _ in self.comments_ref)

        if has_comment:
            lineno_str = f"●{line_idx + 1:>{lineno_width - 1}}"
            lineno_style = Style(color="yellow")
        else:
            lineno_str = f"{line_idx + 1:>{lineno_width}}"
            lineno_style = _LINENO_STYLE

        sep = " │ "

        if selected:
            segments = [
                Segment(lineno_str, lineno_style + _SELECTED_STYLE),
                Segment(sep, _SEP_STYLE + _SELECTED_STYLE),
                Segment(content, _SELECTED_STYLE),
            ]
            strip = Strip(segments)
            strip = strip.extend_cell_length(width, _SELECTED_STYLE)
        else:
            segments = [
                Segment(lineno_str, lineno_style),
                Segment(sep, _SEP_STYLE),
                Segment(content, _CONTENT_STYLE),
            ]
            strip = Strip(segments)
            strip = strip.extend_cell_length(width)

        return strip.crop(0, width)

    # ------------------------------------------------------------------
    # Mouse selection
    # ------------------------------------------------------------------

    def _y_to_line(self, y: int) -> Optional[int]:
        row_idx = y + int(self.scroll_offset.y)
        if row_idx < 0 or row_idx >= len(self._row_map):
            return None
        kind, value = self._row_map[row_idx]
        if kind == "annotation":
            return None
        return value  # type: ignore[return-value]

    def on_mouse_down(self, event: MouseDown) -> None:
        if event.button != 1:
            return
        line = self._y_to_line(event.y)
        if line is None:
            return
        self._drag_anchor = line
        self._dragging = True
        self.sel_start = line
        self.sel_end = line
        self.refresh()
        event.stop()

    def on_mouse_move(self, event: MouseMove) -> None:
        if not self._dragging or self._drag_anchor is None:
            return
        line = self._y_to_line(event.y)
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
        line = self._y_to_line(event.y)
        if line is not None and self._drag_anchor is not None:
            a, b = sorted((self._drag_anchor, line))
            self.sel_start = a
            self.sel_end = b
        self._dragging = False
        self._drag_anchor = None
        self.refresh()
        event.stop()

    # ------------------------------------------------------------------
    # Keyboard scroll helpers
    # ------------------------------------------------------------------

    def action_scroll_down_line(self) -> None:
        self.scroll_relative(y=1)

    def action_scroll_up_line(self) -> None:
        self.scroll_relative(y=-1)

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def has_selection(self) -> bool:
        return self.sel_start is not None and self.sel_end is not None

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


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

_APP_CSS = """
Screen {
    background: transparent;
    layers: base overlay;
}

#viewer {
    height: 1fr;
    border: none;
    scrollbar-gutter: stable;
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
    background: $panel;
    color: $text-muted;
}
"""


class ComposerApp(App[None]):
    CSS = _APP_CSS
    TITLE = "Output Comment Composer"

    BINDINGS = [
        Binding("c", "open_comment", "comment", show=True),
        Binding("s", "send_comments", "send", show=True),
        Binding("q", "quit", "quit", show=True),
        Binding("escape", "quit", "quit", show=False),
    ]

    class SnapshotReady(Message):
        def __init__(self, lines: list[str]) -> None:
            super().__init__()
            self.lines = lines

    def __init__(self):
        super().__init__()
        self.source_pane, self.session_id, self.source_cwd, self.agent = load_meta()
        self.snap_lines: list[str] = []
        self.comments: list[tuple[int, int, str]] = []
        self._editing_comment_idx: Optional[int] = None
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
            lines = await asyncio.to_thread(self._do_fetch)
        except Exception as e:
            debug_dir = os.environ.get("OCC_DEBUG_DIR", "")
            if debug_dir:
                with open(os.path.join(debug_dir, "bash.log"), "a") as f:
                    f.write(f"py:fetch-exception {e}\n")
            lines = [f"Error loading snapshot: {e}"]
        self.post_message(self.SnapshotReady(lines))

    def _do_fetch(self) -> list[str]:
        debug_dir = os.environ.get("OCC_DEBUG_DIR", "")

        def _log(msg: str) -> None:
            if debug_dir:
                try:
                    with open(os.path.join(debug_dir, "bash.log"), "a") as f:
                        f.write(f"py:{msg}\n")
                except Exception:
                    pass

        # Strategy A: Claude Code JSONL
        if self.agent in ("claude", "claude-code", "") and self.session_id:
            lines = self._fetch_claude_jsonl()
            if lines:
                _log("strategy=claude-jsonl ok")
                return lines

        # Strategy B: OpenCode SQLite
        opencode_db = os.path.expanduser("~/.local/share/opencode/opencode.db")
        if os.path.isfile(opencode_db):
            if self.session_id or self.source_cwd:
                lines = self._fetch_opencode_sqlite(opencode_db)
                if lines:
                    _log("strategy=opencode-sqlite ok")
                    return lines

        # Strategy C: fallback pane read
        _log("strategy=pane-read")
        return self._fetch_pane_read()

    def _fetch_claude_jsonl(self) -> list[str]:
        encoded_cwd = (self.source_cwd or os.path.expanduser("~")).replace("/", "-")
        jsonl_path = os.path.expanduser(
            f"~/.claude/projects/{encoded_cwd}/{self.session_id}.jsonl"
        )
        if not os.path.isfile(jsonl_path):
            return []
        blocks = []
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if entry.get("type") != "assistant":
                    continue
                msg = entry.get("message", {})
                if msg.get("role") != "assistant":
                    continue
                for part in msg.get("content", []):
                    if isinstance(part, dict) and part.get("type") == "text":
                        text = part.get("text", "").strip()
                        if text:
                            blocks.append(text)
        last = blocks[-1] if blocks else ""
        return last.splitlines() if last else []

    def _fetch_opencode_sqlite(self, db_path: str) -> list[str]:
        try:
            conn = sqlite3.connect(db_path)
            session_id = self.session_id or None

            if not session_id and self.source_cwd:
                row = conn.execute("""
                    SELECT s.id FROM session s
                    JOIN message m ON m.session_id = s.id
                    JOIN part p ON p.message_id = m.id
                    WHERE s.directory = ?
                      AND json_extract(m.data, '$.role') = 'assistant'
                      AND json_extract(p.data, '$.type') = 'text'
                    ORDER BY s.time_updated DESC LIMIT 1
                """, (self.source_cwd,)).fetchone()
                if row:
                    session_id = row[0]

            if not session_id:
                conn.close()
                return []

            rows = conn.execute("""
                SELECT p.data
                FROM part p
                JOIN message m ON p.message_id = m.id
                WHERE m.session_id = ?
                  AND json_extract(m.data, '$.role') = 'assistant'
                  AND json_extract(p.data, '$.type') = 'text'
                  AND m.time_created = (
                    SELECT MAX(m2.time_created) FROM message m2
                    JOIN part p2 ON p2.message_id = m2.id
                    WHERE m2.session_id = ?
                      AND json_extract(m2.data, '$.role') = 'assistant'
                      AND json_extract(p2.data, '$.type') = 'text'
                  )
                ORDER BY p.time_created ASC
            """, (session_id, session_id)).fetchall()
            conn.close()

            parts = []
            for (data_json,) in rows:
                try:
                    d = json.loads(data_json)
                    if d.get("type") == "text" and d.get("text"):
                        parts.append(d["text"])
                except Exception:
                    pass
            text = "\n".join(parts)
            return text.splitlines() if text else []
        except Exception:
            return []

    def _fetch_pane_read(self) -> list[str]:
        herdr = os.environ.get("HERDR_BIN_PATH", "herdr")
        result = subprocess.run(
            [herdr, "pane", "read", self.source_pane, "--lines", "400"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return ["Failed to read pane."]
        raw_lines = result.stdout.splitlines()
        return self._extract_last_block(raw_lines)

    def _extract_last_block(self, lines: list[str]) -> list[str]:
        """Detect agent TUI and extract last assistant block; fallback to last 80 lines."""

        def detect_agent(ls: list[str]) -> Optional[str]:
            for line in ls:
                if re.match(r"^\s*▣\s+.+·", line):
                    return "opencode"
                if re.match(r"^\s*(Sonnet|Opus|Haiku)\s+[\d.]+\s+\S+/\S+\s+\|", line):
                    return "claude-code"
            return None

        def extract_opencode(ls: list[str]) -> list[str]:
            status_indexes = [i for i, l in enumerate(ls) if re.match(r"^\s*▣\s+.+·", l)]
            end = status_indexes[-1] if status_indexes else len(ls)
            block: list[str] = []
            for line in reversed(ls[:end]):
                stripped = line.strip()
                if stripped.startswith(("┃", "$", "+ Thought:", "Orchestrator ·")):
                    break
                if re.match(r"^[╹▀⬝]+", stripped):
                    break
                block.append(line)
            block.reverse()
            return block

        def extract_claude_code(ls: list[str]) -> list[str]:
            sep_re = re.compile(r"^─{10,}")
            status_re = re.compile(r"^\s*(Sonnet|Opus|Haiku)\s+[\d.]+\s+\S+/\S+\s+\|")
            end = len(ls)
            for i in range(len(ls) - 1, -1, -1):
                if status_re.match(ls[i]):
                    end = i
                    break
            seps = [i for i in range(end) if sep_re.match(ls[i].strip())]
            if len(seps) < 2:
                return []
            for idx in range(len(seps) - 1, 0, -1):
                start = seps[idx - 1] + 1
                finish = seps[idx]
                block = [l for l in ls[start:finish] if l.strip() and l.strip() != "❯"]
                if block:
                    return ls[start:finish]
            return []

        agent_key = detect_agent(lines)
        if agent_key == "opencode":
            block = extract_opencode(lines)
        elif agent_key == "claude-code":
            block = extract_claude_code(lines)
        else:
            block = []

        if not block:
            block = lines[max(0, len(lines) - 80):]
        return block

    def on_composer_app_snapshot_ready(self, message: SnapshotReady) -> None:
        viewer = self.query_one("#viewer", SnapshotViewer)
        viewer.snap_lines = message.lines
        viewer._refresh_row_map()
        viewer.refresh(layout=True)
        viewer.focus()
        self.sub_title = f"source: {self.source_pane}"

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
        self.sub_title = f"source: {self.source_pane} · loading…"
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
        inp.focus()

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

            self.sub_title = f"source: {self.source_pane} · {len(self.comments)} comment(s)"
            viewer._refresh_row_map()
            viewer.refresh()

        panel.remove_class("visible")
        inp.clear()
        viewer.focus()

    def cancel_comment(self) -> None:
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
            quote = "\n".join(f"> {line}" for line in self.snap_lines[s : e + 1])
            parts.append(
                f"Comment {i} on lines {s + 1}–{e + 1}:\n"
                f"{quote}\n\n"
                f"Comment:\n{comment}"
            )
        return "\n\n".join(parts) + "\n"

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
        self._cleanup()
        self.exit()

    def on_unmount(self) -> None:
        self._cleanup()


if __name__ == "__main__":
    ComposerApp().run()
