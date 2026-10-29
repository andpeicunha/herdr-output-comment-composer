"""Key reading that also understands Alt+arrows.

curses has no constant for Alt+Up/Down. Depending on the terminal they arrive as
a named key (terminfo kUP3/kDN3), as ESC followed by the arrow, or as the raw
sequence ESC [ 1 ; 3 A. read_key turns all of them into the ALT_* codes below.
"""

import curses

ALT_UP = 0x10001
ALT_DOWN = 0x10002

_NAMED = {
    b"kUP3": ALT_UP,
    b"kDN3": ALT_DOWN,
    b"kUP2": curses.KEY_SR,
    b"kDN2": curses.KEY_SF,
}
_SEQUENCES = {
    "[1;3A": ALT_UP,
    "[1;3B": ALT_DOWN,
    "[1;2A": curses.KEY_SR,
    "[1;2B": curses.KEY_SF,
}


def decode_escape(rest: list[int]) -> int:
    """Map the keys that followed an ESC to one key code; plain ESC (27) if unknown."""
    if rest == [curses.KEY_UP]:
        return ALT_UP
    if rest == [curses.KEY_DOWN]:
        return ALT_DOWN
    text = "".join(chr(code) for code in rest if 0 <= code < 256)
    return _SEQUENCES.get(text, 27)


def read_key(screen: curses.window, wait_ms: int = -1) -> int:
    """Read one key; wait_ms is the usual curses timeout (-1 blocks)."""
    screen.timeout(wait_ms)
    key = screen.getch()
    if key > 255:
        try:
            name = curses.keyname(key)
        except (curses.error, ValueError):
            name = b""
        return _NAMED.get(name, key)
    if key != 27:
        return key
    rest: list[int] = []
    screen.timeout(40)
    while len(rest) < 8:
        extra = screen.getch()
        if extra == -1:
            break
        rest.append(extra)
    screen.timeout(wait_ms)
    return decode_escape(rest)
