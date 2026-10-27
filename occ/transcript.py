"""Load recent conversation blocks from Codex and Claude JSONL transcripts."""
from __future__ import annotations

import json
import os
import re


_TRANSCRIPT_MAX_LINES = 500

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def load_meta() -> dict[str, str]:
    values: dict[str, str] = {}
    path = os.environ.get("OUTPUT_COMMENT_COMPOSER_META", "")
    if not path:
        return values
    try:
        with open(path, encoding="utf-8") as meta:
            for raw in meta:
                key, separator, value = raw.rstrip("\n").partition("=")
                if separator:
                    values[key] = value
    except OSError:
        pass
    return values


def _read_jsonl(path: str) -> list[dict]:
    entries: list[dict] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as source:
            for raw in source:
                try:
                    value = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(value, dict):
                    entries.append(value)
    except OSError:
        pass
    return entries


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict)
        and block.get("type") in ("text", "input_text", "output_text")
    ).strip()


def codex_transcript_blocks(entries: list[dict]) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for entry in entries:
        if entry.get("type") != "response_item":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        kind = payload.get("type")
        if kind == "message" and payload.get("role") in ("user", "assistant"):
            text = _message_text(payload.get("content"))
            if not text or text.startswith(("<", "# AGENTS.md")):
                continue
            role = "user" if payload.get("role") == "user" else "assistant"
            blocks.append((role, text))
        elif kind in ("function_call", "custom_tool_call", "local_shell_call"):
            name = str(payload.get("name") or "shell")
            blocks.append(("tool", name))
    return blocks


def claude_transcript_blocks(entries: list[dict]) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for entry in entries:
        if entry.get("isSidechain") or entry.get("isMeta"):
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if entry.get("type") == "user":
            text = _message_text(content)
            if text and not text.startswith(("<command-", "<local-command", "<task-notification")):
                blocks.append(("user", text))
        elif entry.get("type") == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and str(block.get("text", "")).strip():
                    blocks.append(("assistant", str(block["text"]).strip()))
                elif block.get("type") == "tool_use":
                    blocks.append(("tool", str(block.get("name") or "tool")))
    return blocks


def limit_transcript_blocks(
    blocks: list[tuple[str, str]], max_lines: int = _TRANSCRIPT_MAX_LINES
) -> list[tuple[str, str]]:
    kept: list[tuple[str, str]] = []
    used = 0
    for block in reversed(blocks):
        block_lines = max(1, len(block[1].splitlines()))
        if kept and used + block_lines > max_lines:
            break
        kept.append(block)
        used += block_lines
    return list(reversed(kept))


def _find_codex_transcript(session_id: str) -> str | None:
    if not session_id or not _SESSION_ID_RE.match(session_id):
        return None
    suffix = f"-{session_id}.jsonl"
    root_dir = os.path.expanduser(os.path.join(os.environ.get("CODEX_HOME", "~/.codex"), "sessions"))
    newest: str | None = None
    for root, _dirs, files in os.walk(root_dir):
        for name in files:
            if name.startswith("rollout-") and name.endswith(suffix):
                path = os.path.join(root, name)
                if newest is None or path > newest:
                    newest = path
    return newest


def _find_claude_transcript(session_id: str) -> str | None:
    if not session_id or not _SESSION_ID_RE.match(session_id):
        return None
    projects = os.path.expanduser(
        os.path.join(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude"), "projects")
    )
    try:
        project_dirs = os.listdir(projects)
    except OSError:
        return None
    for project in project_dirs:
        path = os.path.join(projects, project, f"{session_id}.jsonl")
        if os.path.isfile(path):
            return path
    return None


def transcript_max_lines() -> int:
    """Return the transcript line budget, overridable with ``OCC_MAX_LINES``."""
    try:
        value = int(os.environ.get("OCC_MAX_LINES", ""))
    except ValueError:
        return _TRANSCRIPT_MAX_LINES
    return value if value > 0 else _TRANSCRIPT_MAX_LINES


def fetch_transcript(meta: dict[str, str]) -> list[tuple[str, str]]:
    session_id = meta.get("SESSION_ID", "")
    agent = meta.get("AGENT", "")
    if agent == "codex":
        path = _find_codex_transcript(session_id)
        blocks = codex_transcript_blocks(_read_jsonl(path)) if path else []
    elif agent == "claude":
        path = _find_claude_transcript(session_id)
        blocks = claude_transcript_blocks(_read_jsonl(path)) if path else []
    else:
        blocks = []
    return limit_transcript_blocks(blocks, transcript_max_lines())
