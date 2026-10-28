"""The comment editor's text model."""
from __future__ import annotations


class TextBuffer:
    """Multi-line text with a cursor; the comment editor's pure editing model."""

    def __init__(self, text: str = "") -> None:
        self.lines = text.splitlines() or [""]
        self.row = len(self.lines) - 1
        self.col = len(self.lines[self.row])

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def insert(self, text: str) -> None:
        line = self.lines[self.row]
        self.lines[self.row] = line[: self.col] + text + line[self.col :]
        self.col += len(text)

    def newline(self) -> None:
        line = self.lines[self.row]
        self.lines[self.row] = line[: self.col]
        self.lines.insert(self.row + 1, line[self.col :])
        self.row += 1
        self.col = 0

    def backspace(self) -> None:
        if self.col > 0:
            line = self.lines[self.row]
            self.lines[self.row] = line[: self.col - 1] + line[self.col :]
            self.col -= 1
        elif self.row > 0:
            previous_length = len(self.lines[self.row - 1])
            self.lines[self.row - 1] += self.lines.pop(self.row)
            self.row -= 1
            self.col = previous_length

    def clear_line(self) -> None:
        """Erase the whole current line (Ctrl+U)."""
        self.lines[self.row] = ""
        self.col = 0

    def move_left(self) -> None:
        if self.col > 0:
            self.col -= 1
        elif self.row > 0:
            self.row -= 1
            self.col = len(self.lines[self.row])

    def move_right(self) -> None:
        if self.col < len(self.lines[self.row]):
            self.col += 1
        elif self.row + 1 < len(self.lines):
            self.row += 1
            self.col = 0

    def move_up(self) -> None:
        if self.row > 0:
            self.row -= 1
            self.col = min(self.col, len(self.lines[self.row]))

    def move_down(self) -> None:
        if self.row + 1 < len(self.lines):
            self.row += 1
            self.col = min(self.col, len(self.lines[self.row]))


def needs_discard_confirmation(original: str, current: str) -> bool:
    return original.strip() != current.strip()
