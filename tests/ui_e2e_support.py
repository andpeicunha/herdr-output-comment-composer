"""Small PTY/pyte harness for exercising the real curses screen in tests."""
from __future__ import annotations

import fcntl
import os
import pty
import select
import struct
import subprocess
import termios
import time
from pathlib import Path

try:
    import pyte
except ImportError:  # UI-only test dependency; the plugin has no runtime dependency.
    pyte = None


class CursesSession:
    def __init__(self, command: list[str], env: dict[str, str], *, cols: int = 80, rows: int = 24):
        if pyte is None:
            raise RuntimeError("pyte is required; run via uv --with pyte")
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.ByteStream(self.screen)
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        attrs = termios.tcgetattr(slave)
        attrs[0] &= ~(termios.IXON | termios.IXOFF)
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        self.process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True)
        os.close(slave)
        self.pump(1.0)

    def pump(self, duration: float = 0.25) -> None:
        end = time.monotonic() + duration
        while time.monotonic() < end:
            ready, _, _ = select.select([self.master], [], [], 0.05)
            if ready:
                try:
                    data = os.read(self.master, 65536)
                except OSError:
                    return
                if not data:
                    return
                self.stream.feed(data)

    def send(self, keys: str) -> None:
        try:
            os.write(self.master, keys.encode())
        except OSError:
            return
        self.pump()

    def wait_for(self, text: str, timeout: float = 3.0) -> str:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            current = self.text()
            if text in current:
                return current
            if self.process.poll() is not None:
                break
            self.pump(0.05)
        raise AssertionError(f"Timed out waiting for {text!r}; screen was:\n{self.text()}")

    def text(self) -> str:
        return "\n".join("".join(self.screen.buffer[y][x].data for x in range(self.screen.columns)).rstrip()
                         for y in range(self.screen.lines))

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        os.close(self.master)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]
