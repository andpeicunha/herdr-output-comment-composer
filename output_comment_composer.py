#!/usr/bin/env python3
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import termios
import textwrap
import tty


HEADER_LINES = 4


def load_meta():
    source_pane = os.environ.get("HERDR_PANE_ID", "unknown")
    snapshot_file = ""
    meta = os.environ.get("OUTPUT_COMMENT_COMPOSER_META", "")
    if meta and os.path.isfile(meta):
        with open(meta, encoding="utf-8", errors="replace") as f:
            for line in f:
                key, sep, value = line.rstrip("\n").partition("=")
                if not sep:
                    continue
                if key == "SOURCE_PANE_ID":
                    source_pane = value or source_pane
                elif key == "SNAPSHOT_FILE":
                    snapshot_file = value
    return source_pane, snapshot_file


class Composer:
    def __init__(self):
        self.source_pane, self.snapshot_file = load_meta()
        self.lines = self.load_snapshot()
        self.comments = []
        self.selection = None
        self.drag_anchor = None
        self.status = "Drag to select │ j/k=scroll  d/u=half-page  g/G=top/bottom  s=send  q/Esc=close"
        self.old_term = None
        self.visual_to_line = {}
        self.running = True
        self.scroll_offset = 0

    def load_snapshot(self):
        if self.snapshot_file and os.path.isfile(self.snapshot_file):
            with open(self.snapshot_file, encoding="utf-8", errors="replace") as f:
                return f.read().splitlines()
        return ["No snapshot available."]

    def wrap_lines(self, cols):
        """Return list of (logical_idx, visual_text) with word-wrap applied."""
        line_no_width = max(3, len(str(len(self.lines))))
        prefix_width = line_no_width + 3  # " N │ "
        wrap_width = max(20, cols - prefix_width)
        result = []
        for idx, line in enumerate(self.lines):
            text = line.replace("\t", "    ")
            if not text:
                result.append((idx, ""))
                continue
            wrapped = textwrap.wrap(text, width=wrap_width) or [""]
            for i, part in enumerate(wrapped):
                result.append((idx, part if i == 0 else "  " + part))
        return result

    def cleanup(self):
        # Disable mouse, restore cursor, leave alternate screen
        sys.stdout.write("\033[?1006l\033[?1002l\033[?1000l\033[?25h\033[0m\033[?1049l")
        sys.stdout.flush()
        if self.old_term is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.old_term)
        if self.snapshot_file and os.path.isfile(self.snapshot_file):
            try:
                os.unlink(self.snapshot_file)
                os.rmdir(os.path.dirname(self.snapshot_file))
            except OSError:
                pass

    def line_for_y(self, y):
        return self.visual_to_line.get(y)

    def set_selection(self, a, b):
        if a is None or b is None:
            return
        start, end = sorted((a, b))
        self.selection = (start, end)
        self.status = f"Selected {start + 1}-{end + 1} │ c/Enter=comment  s=send  q/Esc=close"

    def selected(self, idx):
        return self.selection and self.selection[0] <= idx <= self.selection[1]

    def fmt_status(self, text):
        """Bold+yellow the shortcut keys (patterns like j/k=scroll or c/Enter=comentar)."""
        return re.sub(
            r'([A-Za-z][A-Za-z0-9/]*)(\=[^\s│]+)',
            lambda m: f"\033[1;33m{m.group(1)}\033[0m{m.group(2)}",
            text,
        )

    def clamp_scroll_visual(self, total_visual, rows):
        content_rows = rows - HEADER_LINES
        max_offset = max(0, total_visual - content_rows)
        self.scroll_offset = max(0, min(self.scroll_offset, max_offset))

    def render(self):
        cols, rows = shutil.get_terminal_size((100, 30))
        line_no_width = max(3, len(str(len(self.lines))))
        prefix_width = line_no_width + 3
        visual_lines = self.wrap_lines(cols)
        total_visual = len(visual_lines)
        self.clamp_scroll_visual(total_visual, rows)
        self.visual_to_line = {}
        content_rows = rows - HEADER_LINES
        pct = f" [{self.scroll_offset + 1}-{min(self.scroll_offset + content_rows, total_visual)}/{total_visual}]" if total_visual else ""
        out = ["\033[3J\033[2J\033[H\033[?25l"]
        out.append(f"Output Comment Composer — frozen snapshot{pct}\r\n")
        out.append(f"Source pane: {self.source_pane}\r\n")
        out.append(self.fmt_status(self.status) + "\033[0m\r\n")
        out.append(("─" * max(1, cols)) + "\r\n")
        y = HEADER_LINES + 1
        comment_by_end = {}
        for start, end, text in self.comments:
            comment_by_end.setdefault(end, []).append((start, text))
        prev_idx = None
        for vi in range(self.scroll_offset, total_visual):
            if y > rows:
                break
            idx, part = visual_lines[vi]
            self.visual_to_line[y] = idx
            if idx != prev_idx:
                prefix = f"{idx + 1:>{line_no_width}} │ "
                prev_idx = idx
            else:
                prefix = " " * prefix_width
            text = (prefix + part)[:cols]
            if self.selected(idx):
                out.append("\033[7m" + text.ljust(cols) + "\033[0m\r\n")
            else:
                out.append(text + "\r\n")
            y += 1
            # Show inline comments after last visual row of this logical line
            next_idx = visual_lines[vi + 1][0] if vi + 1 < total_visual else -1
            if next_idx != idx:
                for start, comment in comment_by_end.get(idx, []):
                    if y > rows:
                        break
                    label = f"      ↳ comment on {start + 1}-{idx + 1}: "
                    out.append((label + comment)[:cols] + "\r\n")
                    y += 1
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def prompt_comment(self):
        if not self.selection:
            self.status = "Select one or more snapshot lines first."
            return
        start, end = self.selection
        sys.stdout.write("\033[?25h\033[0m\r\nComment: ")
        sys.stdout.flush()
        chars = []
        text = ""
        cancelled = False
        def read_char():
            """Read one Unicode character from stdin, handling multi-byte UTF-8."""
            first = os.read(sys.stdin.fileno(), 1)
            if not first:
                return ""
            b = first[0]
            if b < 0x80:
                n = 0
            elif b < 0xE0:
                n = 1
            elif b < 0xF0:
                n = 2
            else:
                n = 3
            rest = b"" if n == 0 else os.read(sys.stdin.fileno(), n)
            return (first + rest).decode("utf-8", "replace")

        while True:
            ch = read_char()
            if ch in ("\r", "\n"):
                text = "".join(chars)
                break
            if ch == "\x1b":
                cancelled = True
                break
            if ch in ("\x7f", "\b"):
                if chars:
                    chars.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if ch >= " ":
                chars.append(ch)
                sys.stdout.write(ch)
                sys.stdout.flush()
        sys.stdout.write("\033[?25l")
        if text:
            self.comments.append((start, end, text))
            self.status = f"Stored temporary comment on lines {start + 1}-{end + 1}."
        else:
            self.status = "Comment cancelled." if cancelled else "Empty comment cancelled."

    def build_prompt(self):
        parts = ["Please address these comments on your previous output:"]
        for i, (start, end, comment) in enumerate(self.comments, 1):
            quote = "\n".join(f"> {line}" for line in self.lines[start : end + 1])
            parts.append(
                f"Comment {i} on lines {start + 1}-{end + 1}:\n"
                f"{quote}\n\n"
                f"Comment:\n{comment}"
            )
        return "\n\n".join(parts) + "\n"

    def send_comments(self):
        if not self.comments:
            self.status = "No temporary comments to send. Add a comment first."
            return
        if not self.source_pane or self.source_pane == "unknown":
            self.status = "Cannot send: original source pane is unknown."
            return

        prompt = self.build_prompt()
        herdr = os.environ.get("HERDR_BIN_PATH", "herdr")
        agent_result = subprocess.run(
            [herdr, "agent", "prompt", self.source_pane, prompt],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if agent_result.returncode != 0:
            text_result = subprocess.run(
                [herdr, "pane", "send-text", self.source_pane, prompt],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            keys_result = None
            if text_result.returncode == 0:
                keys_result = subprocess.run(
                    [herdr, "agent", "send-keys", self.source_pane, "Enter"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            if text_result.returncode != 0 or not keys_result or keys_result.returncode != 0:
                err = (agent_result.stderr or text_result.stderr or (keys_result.stderr if keys_result else "")).strip()
                self.status = f"Send failed{': ' + err[:80] if err else '.'}"
                return

        self.status = f"Sent {len(self.comments)} comment(s) to source pane; closing."
        self.running = False

    def handle_mouse(self, seq):
        m = re.match(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])", seq)
        if not m:
            return
        button, _x, y, kind = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
        # Mouse wheel: button 64 = scroll up, 65 = scroll down
        if button == 64:
            self.scroll_offset -= 3
            return
        if button == 65:
            self.scroll_offset += 3
            return
        line = self.line_for_y(y)
        if line is None:
            return
        if kind == "M" and button == 0:
            self.drag_anchor = line
            self.set_selection(line, line)
        elif kind == "M" and button & 32 and self.drag_anchor is not None:
            self.set_selection(self.drag_anchor, line)
        elif kind == "m" and self.drag_anchor is not None:
            self.set_selection(self.drag_anchor, line)
            self.drag_anchor = None

    def read_key(self):
        if not select.select([sys.stdin], [], [], 0.1)[0]:
            return ""
        ch = os.read(sys.stdin.fileno(), 1).decode("utf-8", "replace")
        if ch != "\x1b":
            return ch
        while select.select([sys.stdin], [], [], 0.01)[0]:
            ch += os.read(sys.stdin.fileno(), 1).decode("utf-8", "replace")
            if re.match(r"\x1b\[<\d+;\d+;\d+[Mm]$", ch):
                break
        return ch

    def run(self):
        self.old_term = termios.tcgetattr(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())
        # Enter alternate screen + enable mouse; alternate screen prevents
        # scrollback pollution (same as ratatui/crossterm behaviour)
        sys.stdout.write("\033[?1049h\033[?1000h\033[?1002h\033[?1006h")
        sys.stdout.flush()
        signal.signal(signal.SIGWINCH, lambda *_: self.render())
        try:
            self.render()
            while self.running:
                key = self.read_key()
                if not key:
                    continue
                if key in ("q", "\x1b"):
                    break
                if key in ("c", "\r", "\n"):
                    self.prompt_comment()
                elif key == "s":
                    self.send_comments()
                elif key in ("j", "\x1b[B"):   # j or down arrow
                    self.scroll_offset += 1
                elif key in ("k", "\x1b[A"):   # k or up arrow
                    self.scroll_offset -= 1
                elif key in ("d",):             # half-page down
                    _, rows = shutil.get_terminal_size((100, 30))
                    self.scroll_offset += max(1, (rows - HEADER_LINES) // 2)
                elif key in ("u",):             # half-page up
                    _, rows = shutil.get_terminal_size((100, 30))
                    self.scroll_offset -= max(1, (rows - HEADER_LINES) // 2)
                elif key in ("g",):             # top
                    self.scroll_offset = 0
                elif key in ("G",):             # bottom
                    self.scroll_offset = len(self.lines)
                elif key.startswith("\x1b[<"):
                    self.handle_mouse(key)
                self.render()
        finally:
            self.cleanup()


if __name__ == "__main__":
    Composer().run()
