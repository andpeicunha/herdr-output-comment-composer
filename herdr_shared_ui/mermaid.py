"""Offline Mermaid previews for the shared Herdr terminal viewers."""
from __future__ import annotations

import curses
import hashlib
import io
from functools import lru_cache
import os
import platform
import re
import subprocess
import tarfile
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import draw_heavy_frame, draw_title_bar, safe_addnstr
from .layout import wrap_physical_line

MERMAID_ASCII_VERSION = "1.6.1"
_ASSET_DIGESTS = {
    "darwin-arm64": "9b7f7788bd2596437d92856e9a60b7b05ecb5f6f786c8c0b1cb369f742bf8063",
    "darwin-x86_64": "a0fc7b8dc4f01d0ad0afff16590d63b8a85d157cc957b2a659ffeca617360bdc",
    "linux-arm64": "b166e0b4a0c34e31068c7629333e887742af714bb42966db08adf861eb352139",
    "linux-x86_64": "9c2844824635415982a8d34be301a0abb1f64599f019892f7d844c4620ce8d41",
}
_FENCE_LANGUAGE = re.compile(r"^[ \t]*(?:```|~~~)[ \t]*([A-Za-z0-9_-]+)?")
_MAX_SOURCE_BYTES = 32 * 1024
_MAX_OUTPUT_BYTES = 1024 * 1024
_MAX_OUTPUT_LINES = 5000


@dataclass(frozen=True)
class MermaidRenderResult:
    lines: tuple[str, ...]
    rendered: bool
    reason: str = ""


@lru_cache(maxsize=128)
def _cached_auto_render(source: str, width: int) -> MermaidRenderResult:
    """Avoid launching the renderer again on each curses redraw."""
    return render_mermaid_ascii(source, width)


def extract_mermaid_source(blocks: list[str], roles: list[str], index: int) -> str | None:
    """Return the Mermaid body when ``index`` points inside its fenced block."""
    if len(blocks) != len(roles) or not 0 <= index < len(blocks):
        return None
    if roles[index] not in ("fence", "code", "code_gap"):
        return None
    opening = next((i for i in range(index, -1, -1) if roles[i] == "fence"), None)
    if opening is None:
        return None
    match = _FENCE_LANGUAGE.match(blocks[opening])
    if not match or (match.group(1) or "").casefold() not in ("mermaid", "mmd"):
        return None
    end = next((i for i in range(opening + 1, len(blocks)) if roles[i] == "fence"), len(blocks))
    if index >= end:
        return None
    return "\n".join(blocks[opening + 1 : end]).strip("\n")


def prepare_mermaid_blocks(
    blocks: list[str], roles: list[str], width: int
) -> tuple[list[str], list[str], set[int], list[int]]:
    """Render compatible Mermaid fences in place while preserving source block indexes.

    Returns display text, display roles, hidden source indexes, and a cursor mapping.
    Incompatible diagrams stay as their original fenced code.
    """
    if len(blocks) != len(roles):
        return list(blocks), list(roles), set(), list(range(len(blocks)))
    display = list(blocks)
    display_roles = list(roles)
    hidden: set[int] = set()
    cursor_targets = list(range(len(blocks)))
    index = 0
    while index < len(blocks):
        if roles[index] != "fence":
            index += 1
            continue
        source = extract_mermaid_source(blocks, roles, index)
        if source is None:
            index += 1
            continue
        end = next((i for i in range(index + 1, len(roles)) if roles[i] == "fence"), len(roles))
        result = _cached_auto_render(source, width)
        body_indexes = list(range(index + 1, end))
        if not result.rendered or not body_indexes:
            index = end + 1
            continue

        display[index] = "Mermaid preview"
        display_roles[index] = "mermaid_label"
        rendered_lines = list(result.lines)
        visible_indexes: list[int] = []
        for offset, block_index in enumerate(body_indexes):
            start = offset * len(rendered_lines) // len(body_indexes)
            stop = (offset + 1) * len(rendered_lines) // len(body_indexes)
            chunk = rendered_lines[start:stop]
            if chunk:
                display[block_index] = "\n".join(chunk)
                display_roles[block_index] = "mermaid_render"
                visible_indexes.append(block_index)
            else:
                display[block_index] = ""
                display_roles[block_index] = "mermaid_hidden"
                hidden.add(block_index)
        if end < len(blocks):
            display[end] = ""
            display_roles[end] = "mermaid_tail"
            hidden.add(end)
        for block_index in range(index + 1, min(end + 1, len(blocks))):
            target = min(visible_indexes, key=lambda item: abs(item - block_index))
            cursor_targets[block_index] = target
        index = end + 1
    return display, display_roles, hidden, cursor_targets


def remap_mermaid_comments(comments: dict[int, str], cursor_targets: list[int]) -> dict[int, str]:
    """Draw comments on the visible preview line that represents their source block."""
    remapped: dict[int, str] = {}
    for index, text in comments.items():
        target = cursor_targets[index] if 0 <= index < len(cursor_targets) else index
        remapped[target] = f"{remapped[target]}\n{text}" if target in remapped else text
    return remapped


def _target() -> str | None:
    system = platform.system().casefold()
    machine = platform.machine().casefold()
    os_name = {"darwin": "darwin", "linux": "linux"}.get(system)
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64", "amd64": "x86_64"}.get(machine)
    target = f"{os_name}-{arch}" if os_name and arch else None
    return target if target in _ASSET_DIGESTS else None


def bundled_mermaid_binary(*, asset_dir: str | Path | None = None, cache_dir: str | Path | None = None) -> Path | None:
    """Verify and cache the platform binary included with the plugin package."""
    target = _target()
    if not target:
        return None
    assets = Path(asset_dir) if asset_dir else Path(__file__).parent / "assets" / "mermaid-ascii"
    archive = assets / f"{target}.tar.gz"
    try:
        data = archive.read_bytes()
        if hashlib.sha256(data).hexdigest() != _ASSET_DIGESTS[target]:
            return None
        cache = Path(cache_dir) if cache_dir else _default_cache_dir()
        output_dir = cache / MERMAID_ASCII_VERSION / target
        binary = output_dir / "mermaid-ascii"
        if binary.is_file() and os.access(binary, os.X_OK):
            return binary
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as bundle:
            member = next((item for item in bundle.getmembers() if item.name == "mermaid-ascii"), None)
            if member is None or not member.isfile() or member.size > 64 * 1024 * 1024:
                return None
            stream = bundle.extractfile(member)
            if stream is None:
                return None
            content = stream.read(64 * 1024 * 1024 + 1)
            if len(content) != member.size:
                return None
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            if cache_dir is not None:
                return None
            output_dir = Path(tempfile.gettempdir()) / "herdr" / "mermaid-ascii" / MERMAID_ASCII_VERSION / target
            binary = output_dir / "mermaid-ascii"
            output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output_dir, prefix=".mermaid-ascii-", delete=False) as temp:
            temp.write(content)
            temp_path = Path(temp.name)
        try:
            temp_path.chmod(0o755)
            os.replace(temp_path, binary)
        finally:
            temp_path.unlink(missing_ok=True)
        return binary
    except (OSError, tarfile.TarError, ValueError):
        return None


def _default_cache_dir() -> Path:
    if os.environ.get("HERDR_PLUGIN_STATE_DIR"):
        return Path(os.environ["HERDR_PLUGIN_STATE_DIR"]) / "cache" / "mermaid-ascii"
    if os.environ.get("XDG_CACHE_HOME"):
        return Path(os.environ["XDG_CACHE_HOME"]) / "herdr" / "mermaid-ascii"
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Caches" / "herdr" / "mermaid-ascii"
    return Path.home() / ".cache" / "herdr" / "mermaid-ascii"


def _display_width(text: str) -> int:
    return sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in text)


def render_mermaid_ascii(
    source: str,
    width: int,
    *,
    binary_path: str | Path | None = None,
    asset_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
) -> MermaidRenderResult:
    """Render a bounded diagram, returning a reason for source fallback on failure."""
    if not source.strip() or len(source.encode("utf-8")) > _MAX_SOURCE_BYTES:
        return MermaidRenderResult((), False, "empty or oversized Mermaid source")
    if width < 20:
        return MermaidRenderResult((), False, "pane is too narrow")
    binary = Path(binary_path) if binary_path else bundled_mermaid_binary(asset_dir=asset_dir, cache_dir=cache_dir)
    if not binary or not binary.is_file():
        return MermaidRenderResult((), False, "renderer is unavailable for this platform")
    try:
        process = subprocess.run(
            [str(binary), "--file", "-", "--max-width", str(width), "--paddingX", "1", "--paddingY", "1", "--borderPadding", "0"],
            input=source,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return MermaidRenderResult((), False, "renderer failed or timed out")
    if process.returncode != 0:
        return MermaidRenderResult((), False, "Mermaid syntax is unsupported or invalid")
    if "could not fit --max-width" in process.stderr:
        return MermaidRenderResult((), False, "diagram is wider than this pane")
    raw = process.stdout.splitlines()
    if not raw or len(raw) > _MAX_OUTPUT_LINES or len(process.stdout.encode("utf-8")) > _MAX_OUTPUT_BYTES:
        return MermaidRenderResult((), False, "renderer returned empty or oversized output")
    lines = tuple("".join(char for char in line if char in "\t" or unicodedata.category(char) != "Cc").rstrip() for line in raw)
    if any(_display_width(line) > width for line in lines):
        return MermaidRenderResult((), False, "diagram is wider than this pane")
    return MermaidRenderResult(lines, True)


def show_mermaid_viewer(
    screen,
    source: str,
    *,
    width: int,
    binary_path: str | Path | None = None,
    style: dict[str, int] | None = None,
) -> MermaidRenderResult:
    """Open a scrollable modal. Failed renders show the original Mermaid source."""
    result = render_mermaid_ascii(source, width, binary_path=binary_path)
    lines = result.lines if result.rendered else tuple(source.splitlines()) or ("",)
    title = " Mermaid preview " if result.rendered else f" Mermaid source · {result.reason} "
    palette = style or {}
    height, screen_width = screen.getmaxyx()
    if height < 5 or screen_width < 12:
        return result
    modal = curses.newwin(height, screen_width, 0, 0)
    modal.keypad(True)
    content_width = max(1, screen_width - 4)
    rows = [part for line in lines for part in wrap_physical_line(line, content_width, preserve_space=True)]
    visible = max(1, height - 3)
    offset = 0
    while True:
        modal.erase()
        draw_heavy_frame(modal, palette.get("border", 0))
        draw_title_bar(modal, title, palette.get("title", 0), " mermaid-ascii 1.6.1 ")
        for position, line in enumerate(rows[offset : offset + visible], 1):
            safe_addnstr(modal, position, 2, line, content_width, palette.get("content", 0))
        footer = " ↑/↓ scroll · PgUp/PgDn page · g/G top/end · q/Esc close "
        safe_addnstr(modal, height - 2, 2, footer, content_width, palette.get("muted", 0))
        modal.refresh()
        key = modal.get_wch()
        if key in ("q", "\x1b"):
            break
        if key in (curses.KEY_UP, "k"):
            offset = max(0, offset - 1)
        elif key in (curses.KEY_DOWN, "j"):
            offset = min(max(0, len(rows) - visible), offset + 1)
        elif key == curses.KEY_PPAGE:
            offset = max(0, offset - visible)
        elif key == curses.KEY_NPAGE:
            offset = min(max(0, len(rows) - visible), offset + visible)
        elif key == "g":
            offset = 0
        elif key == "G":
            offset = max(0, len(rows) - visible)
    del modal
    return result
