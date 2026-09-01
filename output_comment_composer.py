#!/usr/bin/env python3
"""Output Comment Composer — Textual TUI rewrite."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
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


_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_CODEX_STATUS_RE = re.compile(r"\bcontext\s+\d+%\s+used\b", re.IGNORECASE)
_CODEX_LIMIT_RE = re.compile(r"\b(?:weekly|(?:\d+h))\s+\d+%\s+left\b", re.IGNORECASE)
_CLAUDE_MODE_RE = re.compile(
    r"\b(?:bypass permissions|accept edits|plan mode)\s+on\b.*\bshift\+tab\b",
    re.IGNORECASE,
)
_CLAUDE_COMPOSER_STATUS_RE = re.compile(
    r"\b(?:manual|normal|plan|accept edits|bypass permissions)\s+mode\s+on\b.*\bfor agents\b",
    re.IGNORECASE,
)
_CODEX_PROMPT_RE = re.compile(r"^[›❯>]\s*ask codex to do anything\s*$", re.IGNORECASE)


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
        if cleaned and _CLAUDE_COMPOSER_STATUS_RE.search(plain):
            # The Claude composer starts at its /effort selector. Limit the
            # backward search so response text containing /effort is safe.
            footer_start = None
            for index in range(len(cleaned) - 1, max(-1, len(cleaned) - 12), -1):
                candidate = _ANSI_ESCAPE_RE.sub("", cleaned[index]).strip()
                if re.search(r"(?:^|\s)/effort(?:\s|$)", candidate, re.IGNORECASE):
                    footer_start = index
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


# ---------------------------------------------------------------------------
# Metadata loading
# ---------------------------------------------------------------------------


def load_meta() -> str:
    """Return source_pane."""
    source_pane = os.environ.get("HERDR_PANE_ID", "unknown")
    meta = os.environ.get("OUTPUT_COMMENT_COMPOSER_META", "")
    if meta and os.path.isfile(meta):
        with open(meta, encoding="utf-8", errors="replace") as f:
            for line in f:
                key, sep, value = line.rstrip("\n").partition("=")
                if not sep:
                    continue
                if key == "SOURCE_PANE_ID":
                    source_pane = value or source_pane
    return source_pane


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
        Binding("down", "scroll_down_line", "Down", show=False),
        Binding("up", "scroll_up_line", "Up", show=False),
    ]

    def __init__(self, lines: list[str], comments_ref: list[tuple[int, int, str]] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.snap_lines = lines
        self.comments_ref = comments_ref if comments_ref is not None else []
        self.sel_start: Optional[int] = None
        self.sel_end: Optional[int] = None
        self._drag_anchor: Optional[int] = None
        self._dragging = False
        self._row_map: list[tuple[str, tuple]] = []
        self._wrap_width: int = 0
        self._refresh_row_map()

    def _refresh_row_map(self, wrap_width: int = 0) -> None:
        """Build row map with word-wrap support.

        Each row is one of:
          ('line_chunk', (line_idx, chunk_idx, chunk_text))
          ('annotation', (text,))
        """
        self._wrap_width = wrap_width
        lineno_width = max(3, len(str(max(len(self.snap_lines), 1))))
        sep_width = 3  # " │ "
        avail = wrap_width - lineno_width - sep_width if wrap_width > lineno_width + sep_width + 12 else 0

        after: dict[int, str] = {}
        for s, e, text in self.comments_ref:
            after[e] = text

        rows: list[tuple[str, tuple]] = []
        for i in range(len(self.snap_lines)):
            content = self.snap_lines[i].replace("\t", "    ")
            if avail > 0 and len(content) > avail:
                chunks = textwrap.wrap(content, avail) or [""]
            else:
                chunks = [content]
            for ci, chunk in enumerate(chunks):
                rows.append(("line_chunk", (i, ci, chunk)))
            if i in after:
                rows.append(("annotation", (after[i],)))
        self._row_map = rows
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

        if selected:
            segments = [
                Segment(lineno_str, lineno_style + _SELECTED_STYLE),
                Segment(sep, _SEP_STYLE + _SELECTED_STYLE),
                Segment(content, _SELECTED_STYLE),
            ]
            strip = Strip(segments).extend_cell_length(width, _SELECTED_STYLE)
        else:
            segments = [
                Segment(lineno_str, lineno_style),
                Segment(sep, _SEP_STYLE),
                Segment(content, _CONTENT_STYLE),
            ]
            strip = Strip(segments).extend_cell_length(width)

        return strip.crop(0, width)

    # ------------------------------------------------------------------
    # Mouse selection
    # ------------------------------------------------------------------

    def _y_to_line(self, y: int) -> Optional[int]:
        y = y - 1  # compensate for 1-cell top border
        row_idx = y + int(self.scroll_offset.y)
        if row_idx < 0 or row_idx >= len(self._row_map):
            return None
        kind, value = self._row_map[row_idx]
        if kind == "annotation":
            return None
        return value[0]  # line_idx

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
    border: solid #3f3f46;
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
"""


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
        def __init__(self, lines: list[str]) -> None:
            super().__init__()
            self.lines = lines

    def __init__(self):
        super().__init__()
        self.source_pane = load_meta()
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
        return self._fetch_pane_read()

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
        return clean_snapshot_lines(result.stdout.splitlines())

    def on_composer_app_snapshot_ready(self, message: SnapshotReady) -> None:
        self.snap_lines = message.lines
        viewer = self.query_one("#viewer", SnapshotViewer)
        viewer.snap_lines = self.snap_lines
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

            viewer = self.query_one("#viewer", SnapshotViewer)
            viewer.border_subtitle = f"@andpeicunha · {len(self.comments)} comment(s)"
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
        self._cleanup()
        self.exit()

    def on_unmount(self) -> None:
        self._cleanup()


if __name__ == "__main__":
    ComposerApp().run()
