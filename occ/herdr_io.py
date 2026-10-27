"""Talk to Herdr and the terminal: read the source pane, copy, and send feedback."""
from __future__ import annotations

import base64
import os
import re
import subprocess

from .markdown import group_logical_blocks


_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


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


def copy_blocks_to_clipboard(blocks: list[str], start: int, end: int) -> None:
    text = "\n\n".join(blocks[start : end + 1])
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    os.write(1, f"\x1b]52;c;{encoded}\a".encode("ascii"))


def build_prompt(lines: list[str], comments: dict[int, str], signature: str = "") -> str:
    parts = ["Please address these comments on your previous output:"]
    for number, block_index in enumerate(sorted(comments), 1):
        quoted = "\n".join(
            f"> {line}".rstrip() for line in lines[block_index].splitlines() or [""]
        )
        parts.append(
            f"Comment {number} on block {block_index + 1}:\n\n"
            f"{quoted}\n\n"
            f"Comment:\n{comments[block_index]}"
        )
    if signature:
        parts.append(f"— {signature}")
    return "\n\n".join(parts) + "\n"


def send_comments(
    source_pane: str, lines: list[str], comments: dict[int, str]
) -> tuple[bool, str]:
    herdr = os.environ.get("HERDR_BIN_PATH", "herdr")
    prompt = build_prompt(lines, comments, os.environ.get("OCC_SIGNATURE", "").strip())
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
