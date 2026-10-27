"""The curses user interface of the Output Comment Composer."""
from __future__ import annotations

import curses
import os
import termios
import time
import traceback

from .editor import TextBuffer, needs_discard_confirmation
from .herdr_io import copy_text_to_clipboard, fetch_snapshot, send_comments
from .layout import (
    COMMENT_PREFIX,
    build_display_rows,
    content_rows_available,
    editor_cursor_position,
    editor_visual_rows,
    page_target,
    scroll_position_label,
    scrollbar_thumb,
    selection_bounds,
)
from .markdown import (
    bold_segments,
    comment_preview,
    expand_transcript_blocks,
    format_markdown_lines,
    join_blocks,
    mark_inline_markup,
    split_code_fences,
)
from .transcript import fetch_transcript, load_meta


# Open comment box: top divider, three text rows, and the frame's bottom edge.
_COMMENT_BOX_HEIGHT = 5


def selected_color_pair(color_count: int) -> tuple[int, int]:
    """Use a quiet neutral background when the terminal supports 256 colors."""
    if color_count >= 256:
        return 250, 235
    return curses.COLOR_GREEN, -1


_EDITOR_KEYS = {
    "\n": TextBuffer.newline,
    "\r": TextBuffer.newline,
    curses.KEY_ENTER: TextBuffer.newline,
    "\b": TextBuffer.backspace,
    "\x7f": TextBuffer.backspace,
    curses.KEY_BACKSPACE: TextBuffer.backspace,
    curses.KEY_LEFT: TextBuffer.move_left,
    curses.KEY_RIGHT: TextBuffer.move_right,
    curses.KEY_UP: TextBuffer.move_up,
    curses.KEY_DOWN: TextBuffer.move_down,
}


def _draw_heavy_box(window: curses.window, attr: int = 0) -> None:
    height, width = window.getmaxyx()
    if height < 2 or width < 2:
        return
    horizontal = "━" * (width - 2)
    _safe_addnstr(window, 0, 0, f"┏{horizontal}┓", width, attr)
    for y in range(1, height - 1):
        _safe_addnstr(window, y, 0, "┃", 1, attr)
        _safe_addnstr(window, y, width - 1, "┃", 1, attr)
    _safe_addnstr(window, height - 1, 0, f"┗{horizontal}┛", width, attr)


def _safe_addnstr(
    screen: curses.window, y: int, x: int, text: str, width: int, attr: int = 0
) -> None:
    if width <= 0:
        return
    try:
        screen.addnstr(y, x, text, width, attr)
    except curses.error:
        pass


class Composer:
    def __init__(self, source_pane: str, meta: dict[str, str] | None = None):
        self.lines = ["Loading snapshot…"]
        self.block_kinds = ["assistant"]
        self.block_starts = [True]
        # Code role per block ("", "fence", "code", "code_gap"); see split_code_fences.
        self.block_code = [""]
        self.source_pane = source_pane
        self.meta = meta or {}
        self.cursor = 0
        self.comments: dict[int, str] = {}
        self.selection_anchor: int | None = None
        self.selected_range: tuple[int, int] | None = None
        self.status = ""
        self.sent = False
        self.colors: dict[str, int] = {}
        # Typing state for the open comment box; None while it is closed.
        self.editor: TextBuffer | None = None
        self.edit_top = 0
        # Layout from the last draw, used to page by screen rows.
        self.display_rows: list[tuple[str, int, str]] = []
        self.visible_rows = 1

    def run(self, screen: curses.window) -> None:
        curses.curs_set(0)
        screen.keypad(True)
        self.setup_colors()
        self.draw_loading(screen)
        started = time.perf_counter()
        transcript = fetch_transcript(self.meta)
        if transcript:
            expanded = expand_transcript_blocks(transcript)
            self.block_kinds = [kind for kind, _text, _start, _code in expanded]
            self.lines = [text for _kind, text, _start, _code in expanded]
            self.block_starts = [start for _kind, _text, start, _code in expanded]
            self.block_code = [code for _kind, _text, _start, code in expanded]
            source = "transcript"
        else:
            snapshot = split_code_fences(fetch_snapshot(self.source_pane))
            self.lines = [text for text, _code in snapshot]
            self.block_code = [code for _text, code in snapshot]
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
            elif key in (
                curses.KEY_SR,
                curses.KEY_SF,
                curses.KEY_PPAGE,
                curses.KEY_NPAGE,
                ord("u"),
                ord("d"),
            ):
                # Shift+arrows page a full screen; u/d and PgUp/PgDn half a screen.
                if key in (curses.KEY_SR, curses.KEY_SF):
                    page = max(1, self.visible_rows - 2)
                else:
                    page = max(1, self.visible_rows // 2)
                if key in (curses.KEY_SR, curses.KEY_PPAGE, ord("u")):
                    page = -page
                self.cursor = page_target(self.display_rows, self.cursor, page)
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
                copy_text_to_clipboard(join_blocks(self.lines, self.block_code, start, end))
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
            "rule": (curses.COLOR_BLUE, -1),
            "bullet": (curses.COLOR_WHITE, -1),
            "table": (curses.COLOR_WHITE, -1),
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
        title = " Output Comment Composer "
        _safe_addnstr(screen, 0, 0, title.ljust(max(0, width - 1)), width - 1, curses.A_REVERSE)
        message = "Loading snapshot…"
        x = max(0, (width - len(message)) // 2)
        _safe_addnstr(screen, max(1, height // 2), x, message, width - x - 1, curses.A_BOLD)
        screen.refresh()

    def draw(self, screen: curses.window) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        box_height = _COMMENT_BOX_HEIGHT if self.editor is not None else 0
        viewer_height = height - box_height
        if viewer_height < 8 or width < 30:
            _safe_addnstr(screen, 0, 0, "Pane too small", width - 1, curses.A_BOLD)
            screen.refresh()
            return

        # While typing, the comment box's divider closes the viewer instead of the frame.
        inner_bottom = viewer_height - 1 if box_height else height - 2
        inner_width = width - 2
        border_attr = self.style("comment", curses.A_BOLD) | curses.A_BOLD
        self.draw_frame(screen, border_attr)

        markdown, rows = self.layout_rows(max(1, width - 6))
        selected_row = next(
            index
            for index, (kind, line_index, _) in enumerate(rows)
            if kind == "line" and line_index == self.cursor
        )
        available = content_rows_available(height, box_height)
        self.display_rows = rows
        self.visible_rows = available
        top = max(0, selected_row - available // 2)
        top = min(top, max(0, len(rows) - available))

        self.draw_header(screen, len(rows), available, top, inner_width)
        self.draw_scrollbar(screen, len(rows), available, top, border_attr)
        self.draw_rows(screen, markdown, rows, top, available, inner_width)
        self.draw_footer(screen, inner_bottom, inner_width)
        if box_height:
            self.draw_comment_box(screen, viewer_height, border_attr)
        screen.refresh()

    def draw_frame(self, screen: curses.window, border_attr: int) -> None:
        """Heavy frame with the COMMENTS banner and the header separator."""
        width = screen.getmaxyx()[1]
        _draw_heavy_box(screen, border_attr)
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
        _safe_addnstr(screen, 2, 1, "─" * (width - 2), width - 2, self.style("muted"))

    def layout_rows(
        self, content_width: int
    ) -> tuple[list[tuple[str, str]], list[tuple[str, int, str]]]:
        """Format every block and wrap it into display rows."""
        markdown = format_markdown_lines(self.lines, content_width, self.block_code)
        rendered_blocks = []
        for index, (text, _kind) in enumerate(markdown):
            block_kind = self.block_kinds[index]
            # Assistant blocks and code lines keep the formatted text.
            if block_kind == "tool":
                text = self.lines[index]
            elif block_kind == "user" and not self.block_code[index]:
                text = mark_inline_markup(self.lines[index])
            rendered_blocks.append(text)
        compact_after = {
            index
            for index in range(len(markdown) - 1)
            if (
                markdown[index][1] == "bullet"
                and markdown[index + 1][1] == "bullet"
                and not self.block_starts[index + 1]
            )
            or self.block_code[index + 1] == "code"
        }
        rows = build_display_rows(
            rendered_blocks,
            self.comments,
            width=content_width,
            spacing=True,
            compact_after=compact_after,
            no_wrap={
                index
                for index, (_text, kind) in enumerate(markdown)
                if kind == "table" and self.block_kinds[index] == "assistant"
            },
        )
        return markdown, rows

    def draw_header(
        self, screen: curses.window, total_rows: int, available: int, top: int, inner_width: int
    ) -> None:
        position = f"block {self.cursor + 1}/{len(self.lines)}"
        scroll_label = scroll_position_label(total_rows, available, top)
        if scroll_label:
            position += f" · {scroll_label}"
        meta = f" source {self.source_pane}  ·  {len(self.comments)} comment(s)  ·  {position} "
        _safe_addnstr(screen, 1, 1, meta, inner_width, self.style("muted"))

    def draw_scrollbar(
        self, screen: curses.window, total_rows: int, available: int, top: int, border_attr: int
    ) -> None:
        """Scrollbar in the free column just inside the right frame edge."""
        thumb = scrollbar_thumb(total_rows, available, top)
        if thumb is None:
            return
        x = screen.getmaxyx()[1] - 2
        thumb_start, thumb_size = thumb
        for offset in range(available):
            if thumb_start <= offset < thumb_start + thumb_size:
                _safe_addnstr(screen, 3 + offset, x, "┃", 1, border_attr)
            else:
                _safe_addnstr(screen, 3 + offset, x, "│", 1, self.style("muted"))

    def draw_rows(
        self,
        screen: curses.window,
        markdown: list[tuple[str, str]],
        rows: list[tuple[str, int, str]],
        top: int,
        available: int,
        inner_width: int,
    ) -> None:
        selected_start, selected_end = self.current_selection()
        # Bold state at the start of each row, so a bold span wrapped over rows stays bold.
        bold_at_row: list[bool] = []
        bold = False
        for kind, _line_index, text in rows:
            if kind == "line":
                bold = False
            bold_at_row.append(bold)
            if kind in ("line", "continuation"):
                _segments, bold = bold_segments(text, bold)

        for y, (kind, line_index, text) in enumerate(rows[top : top + available], 3):
            if kind == "spacer":
                continue
            if kind in ("comment", "comment_continuation"):
                prefix = COMMENT_PREFIX if kind == "comment" else " " * len(COMMENT_PREFIX)
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
            x = 1 + len(prefix)
            segments, _bold = bold_segments(text, bold_at_row[top + y - 3])
            for segment, is_bold in segments:
                room = inner_width - (x - 1)
                if room <= 0:
                    break
                attr = content_attr | curses.A_BOLD if is_bold else content_attr
                _safe_addnstr(screen, y, x, segment, room, attr)
                x += len(segment)

    def draw_footer(self, screen: curses.window, inner_bottom: int, inner_width: int) -> None:
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
        footer = " ↑/↓ move · ⇧↑/↓ page · Space select · y copy · c comment · s send · q close "
        _safe_addnstr(
            screen,
            inner_bottom,
            1,
            footer.ljust(inner_width),
            inner_width,
            self.style("footer", curses.A_REVERSE),
        )

    def draw_comment_box(self, screen: curses.window, top: int, border_attr: int) -> None:
        """Draw the open comment editor at the bottom of the frame."""
        height, width = screen.getmaxyx()
        inner_height = _COMMENT_BOX_HEIGHT - 2
        inner_width = width - 4
        # Divider joined to the pane frame; the frame supplies the sides and bottom.
        _safe_addnstr(screen, top, 0, "┣" + "━" * (width - 2) + "┫", width, border_attr)
        badge = " ✎ COMMENT "
        _safe_addnstr(
            screen,
            top,
            2,
            badge,
            width - 4,
            self.style("comment_badge", curses.A_REVERSE) | curses.A_BOLD,
        )
        label_x = 2 + len(badge)
        _safe_addnstr(
            screen,
            top,
            label_x,
            f" {comment_preview(self.lines[self.cursor])} ",
            width - label_x - 2,
            border_attr,
        )

        editor = self.editor or TextBuffer()
        visual_rows = editor_visual_rows(editor.lines, inner_width)
        cursor_row, cursor_col = editor_cursor_position(visual_rows, editor.row, editor.col)
        if cursor_row < self.edit_top:
            self.edit_top = cursor_row
        elif cursor_row >= self.edit_top + inner_height:
            self.edit_top = cursor_row - inner_height + 1
        for offset, (_logical, _start, text) in enumerate(
            visual_rows[self.edit_top : self.edit_top + inner_height], 1
        ):
            _safe_addnstr(screen, top + offset, 2, text, inner_width)
        help_text = " Ctrl+S save · Tab next · Shift+Tab prev · Enter new line · Esc cancel "
        _safe_addnstr(screen, height - 1, 2, help_text, width - 4, self.style("muted"))
        try:
            screen.move(top + 1 + cursor_row - self.edit_top, 2 + min(cursor_col, inner_width - 1))
        except curses.error:
            pass

    def open_editor(self) -> str:
        """Start typing on the current block; return its saved comment."""
        original = self.comments.get(self.cursor, "")
        self.editor = TextBuffer(original)
        self.edit_top = 0
        return original

    def save_editor(self) -> None:
        text = self.editor.text.strip() if self.editor else ""
        if text:
            self.comments[self.cursor] = text
            self.status = f"Comment saved on block {self.cursor + 1}"
        elif self.comments.pop(self.cursor, None) is not None:
            self.status = f"Comment removed from block {self.cursor + 1}"

    def edit_comment(self, screen: curses.window) -> None:
        original = self.open_editor()
        curses.curs_set(1)
        try:
            while True:
                self.draw(screen)
                key = screen.get_wch()
                editor = self.editor
                if key == "\x13":
                    self.save_editor()
                    return
                if key in ("\t", curses.KEY_BTAB):
                    # Save, then keep typing on the next/previous block.
                    self.save_editor()
                    step = 1 if key == "\t" else -1
                    self.cursor = min(max(0, self.cursor + step), len(self.lines) - 1)
                    original = self.open_editor()
                    continue
                if key == "\x1b":
                    if needs_discard_confirmation(original, editor.text):
                        curses.curs_set(0)
                        if not self.confirm_discard(screen):
                            curses.curs_set(1)
                            continue
                    self.status = "Comment edit cancelled"
                    return
                action = _EDITOR_KEYS.get(key)
                if action is not None:
                    action(editor)
                elif isinstance(key, str) and key.isprintable():
                    editor.insert(key)
        finally:
            self.editor = None
            curses.curs_set(0)

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
        curses.wrapper(Composer(source_pane, meta).run)
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
