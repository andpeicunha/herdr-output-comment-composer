#!/usr/bin/env bash
set -uo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

mode="${1:-toggle}"
H="${HERDR_BIN_PATH:-herdr}"
plugin_id="${HERDR_PLUGIN_ID:-andpeicunha.output-comment-composer}"
ws="${HERDR_WORKSPACE_ID:-}"
source_pane="${HERDR_PANE_ID:-}"
cwd=""

if [ -n "${HERDR_PLUGIN_CONTEXT_JSON:-}" ]; then
  cwd=$(printf '%s' "$HERDR_PLUGIN_CONTEXT_JSON" | jq -r '.focused_pane_cwd // .workspace_cwd // empty' 2>/dev/null)
fi

_early_log="${TMPDIR:-/tmp}/output-comment-composer-debug"
mkdir -p "$_early_log"
echo "start mode=$mode ws=${HERDR_WORKSPACE_ID:-} pane=${HERDR_PANE_ID:-}" >> "$_early_log/bash.log"

refuse() {
  echo "refuse: $1" >> "$_early_log/bash.log"
  printf 'output-comment-composer: %s\n' "$1" >&2
  exit 1
}

[ -n "$ws" ] || refuse "no workspace context (invoke from inside herdr)"
[ -n "$source_pane" ] || refuse "no source pane context"

panes_json=$("$H" pane list --workspace "$ws" 2>/dev/null) && [ -n "$panes_json" ] || refuse "herdr pane list failed for $ws"

is_composer_pane() {
  info=$("$H" pane process-info --pane "$1" 2>/dev/null) || return 1
  printf '%s' "$info" | jq -e '
    [.result.process_info.foreground_processes[]?
      | select((((.argv0 // "") | split("/") | last) == "output-comment-composer")
          or ((((.argv // [])[0] // "") | split("/") | last) == "output-comment-composer"))]
    | length > 0' >/dev/null 2>&1
}

existing=""
while IFS= read -r pane; do
  [ -n "$pane" ] || continue
  if is_composer_pane "$pane"; then
    existing="$existing$pane"$'\n'
  fi
done <<EOF
$(printf '%s' "$panes_json" | jq -r '.result.panes[].pane_id // empty' 2>/dev/null)
EOF

close_all() {
  while IFS= read -r pane; do
    [ -n "$pane" ] || continue
    "$H" pane close "$pane" >/dev/null 2>&1 || :
  done <<EOF
$existing
EOF
  printf 'closed output-comment-composer in %s\n' "$ws"
}

case "$mode" in
close)
  [ -n "$existing" ] && close_all || printf 'close: nothing open in %s\n' "$ws"
  exit 0
  ;;
toggle)
  if [ -n "$existing" ]; then
    close_all
    exit 0
  fi
  ;;
open)
  if [ -n "$existing" ]; then
    printf 'open: already open in %s\n' "$ws"
    exit 0
  fi
  ;;
*)
  refuse "unknown mode '$mode' (toggle | open | close)"
  ;;
esac

tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/output-comment-composer.XXXXXX") || refuse "cannot create temp dir"
raw_snapshot_file="$tmp_dir/raw-snapshot.txt"
snapshot_file="$tmp_dir/snapshot.txt"
meta_file="$tmp_dir/meta.env"
# Debug: keep last invocation raw/snapshot in a stable path for inspection
debug_dir="${TMPDIR:-/tmp}/output-comment-composer-debug"
mkdir -p "$debug_dir"
echo "bash:start source=$source_pane ws=$ws" >> "$debug_dir/bash.log"

# ---------------------------------------------------------------------------
# Snapshot strategy (in priority order):
#
#   1. Claude Code JSONL session log  — full history, no terminal scroll
#      Path: ~/.claude/projects/<encoded-cwd>/<session-id>.jsonl
#      Requires: source pane is a claude agent with a known session_id
#
#   2. herdr pane read (fallback)  — terminal buffer, may scroll source pane
#      Used for: opencode, cursor, codex, or any non-claude agent
#
# To add a new agent's log format: add a branch in the Python block below
# that reads from that agent's log file and writes plain text to out_path.
# ---------------------------------------------------------------------------

# Attempt strategy 1: Claude Code JSONL
session_id=$("$H" pane list --workspace "$ws" 2>/dev/null \
  | jq -r --arg p "$source_pane" \
      '.result.panes[] | select(.pane_id == $p) | .agent_session.value // empty' \
  2>/dev/null || true)

snapshot_source="pane-read"
if [ -n "$session_id" ]; then
  # Encode cwd to the same format Claude Code uses: replace / with -
  # Claude Code path: ~/.claude/projects/<path-with-dashes>/<session>.jsonl
  encoded_cwd=$(printf '%s' "${cwd:-$HOME}" | sed 's|/|-|g')
  jsonl_file="$HOME/.claude/projects/${encoded_cwd}/${session_id}.jsonl"
  if [ -f "$jsonl_file" ]; then
    echo "bash:using-jsonl $jsonl_file" >> "$debug_dir/bash.log"
    python3 - "$jsonl_file" "$raw_snapshot_file" <<'PYJSONL'
import json, sys

jsonl_path, out_path = sys.argv[1], sys.argv[2]
lines = open(jsonl_path, encoding="utf-8", errors="replace").readlines()

# Collect all assistant text blocks in order
blocks = []
for line in lines:
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

# Write the last assistant block
last = blocks[-1] if blocks else ""
with open(out_path, "w", encoding="utf-8") as f:
    f.write(last)
    if last:
        f.write("\n")
PYJSONL
    if [ -s "$raw_snapshot_file" ]; then
      snapshot_source="jsonl"
    fi
  fi
fi

# Attempt strategy 1b: OpenCode SQLite
if [ "$snapshot_source" != "jsonl" ] && [ -n "$session_id" ]; then
  opencode_db="$HOME/.local/share/opencode/opencode.db"
  if [ -f "$opencode_db" ] && command -v sqlite3 >/dev/null 2>&1; then
    echo "bash:trying-opencode-sqlite session=$session_id" >> "$debug_dir/bash.log"
    python3 - "$opencode_db" "$session_id" "$raw_snapshot_file" <<'PYOPENCODE'
import json, subprocess, sys

db_path, session_id, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

query = """
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
"""

try:
    import sqlite3
    conn = sqlite3.connect(db_path)
    rows = conn.execute(query, (session_id, session_id)).fetchall()
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
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
        if text:
            f.write("\n")
except Exception as e:
    import sys
    print(f"opencode-sqlite error: {e}", file=sys.stderr)
    sys.exit(1)
PYOPENCODE
    if [ -s "$raw_snapshot_file" ]; then
      snapshot_source="jsonl"
      echo "bash:opencode-sqlite-ok" >> "$debug_dir/bash.log"
    fi
  fi
fi

# Fallback: herdr pane read (may scroll source pane)
if [ "$snapshot_source" != "jsonl" ]; then
  if ! "$H" pane read "$source_pane" --lines 400 >"$raw_snapshot_file" 2>"$tmp_dir/read.err"; then
    read_err=$(cat "$tmp_dir/read.err" 2>/dev/null || true)
    echo "bash:pane-read-failed $read_err" >> "$debug_dir/bash.log"
    rm -rf "$tmp_dir"
    refuse "failed to read source pane ${source_pane}${read_err:+: $read_err}"
  fi
  echo "bash:pane-read-ok lines=$(wc -l < "$raw_snapshot_file")" >> "$debug_dir/bash.log"
fi
echo "bash:snapshot-source=$snapshot_source" >> "$debug_dir/bash.log"
cp "$raw_snapshot_file" "$debug_dir/raw-snapshot.txt"

python3 - "$raw_snapshot_file" "$snapshot_file" "$snapshot_source" <<'PY'
import re
import sys

# ---------------------------------------------------------------------------
# Agent TUI pattern registry
#
# Each entry describes how to detect block boundaries in the raw pane output
# of a specific agent TUI. Add a new entry when supporting a new agent.
#
# Fields:
#   status_re   – regex matching the TUI's *status/footer* line (used to find
#                 the end of the last response block; strip trailing status bar)
#   block_end_re – (optional) alternative end-of-block marker if status_re is
#                 not reliable (e.g. a separator line above the prompt)
#   block_start_prefixes – plain-string prefixes that mark the *start* of the
#                 previous turn (iteration stops when one of these is found
#                 while scanning backwards)
#   block_start_re – (optional) additional regex for start-of-previous-turn
#
# Known agents:
#
#   opencode
#     Status line:   "▣  <title> ·"
#     Prev-turn markers: "┃", "$", "+ Thought:", "Orchestrator ·"
#     Prev-turn regex:   ^[╹▀⬝]+
#
#   claude-code  (Claude Code CLI)
#     Status line:   "  <model> <repo>/<branch> | ..."  (fixed bottom bar)
#     Separator:     "─" * terminal_width  (horizontal rule between turns)
#     Prompt line:   "❯"  (immediately after separator = start of user turn)
#     Prev-turn markers: separator line itself; stop on "❯" or "─"*cols
#
#   cursor  (TODO – fill in when tested)
#   codex   (TODO – fill in when tested)
# ---------------------------------------------------------------------------

raw_path, out_path = sys.argv[1], sys.argv[2]
snapshot_source = sys.argv[3] if len(sys.argv) > 3 else "pane-read"

lines = open(raw_path, encoding="utf-8", errors="replace").read().splitlines()

# JSONL source: content is already the final assistant block — write as-is
if snapshot_source == "jsonl":
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        if lines:
            f.write("\n")
    sys.exit(0)

# ---------------------------------------------------------------------------
# Per-agent extractors
# ---------------------------------------------------------------------------

def detect_agent(lines):
    for line in lines:
        if re.match(r"^\s*▣\s+.+·", line):
            return "opencode"
        # Status bar: "  Sonnet 4.6 dotfiles/main | ..."  (model name + version + repo/branch + |)
        if re.match(r"^\s*(Sonnet|Opus|Haiku)\s+[\d.]+\s+\S+/\S+\s+\|", line):
            return "claude-code"
        # TODO: cursor  – add detection when tested
        # TODO: codex   – add detection when tested
    return None


def extract_opencode(lines):
    """
    OpenCode TUI
    - Status/footer line: "▣  <title> ·"
    - Prev-turn markers:  lines starting with ┃  $  + Thought:  Orchestrator ·
    - Prev-turn regex:    ^[╹▀⬝]+
    """
    status_indexes = [i for i, l in enumerate(lines) if re.match(r"^\s*▣\s+.+·", l)]
    end = status_indexes[-1] if status_indexes else len(lines)

    block = []
    for line in reversed(lines[:end]):
        stripped = line.strip()
        if stripped.startswith(("┃", "$", "+ Thought:", "Orchestrator ·")):
            break
        if re.match(r"^[╹▀⬝]+", stripped):
            break
        block.append(line)

    block.reverse()
    return block


def extract_claude_code(lines):
    """
    Claude Code CLI TUI
    - Status bar (2 lines at bottom):
        "  Sonnet 4.6 repo/branch | ..."
        "  ⏵⏵ accept edits on ..."
    - Turn separator: a line of ─ chars (≥10), full terminal width
    - Structure (bottom to top):
        <status bar lines>
        ──────...──────   ← last separator (below empty prompt)
        ❯                 ← empty prompt (awaiting input)
        ──────...──────   ← separator after last response
        <Claude response> ← what we want
        ❯ <user message>  ← previous user turn
        ──────...──────   ← separator before user turn
    Strategy: find all separator lines, take content between last two.
    """
    sep_re = re.compile(r"^─{10,}")
    status_re = re.compile(r"^\s*(Sonnet|Opus|Haiku)\s+[\d.]+\s+\S+/\S+\s+\|")

    # Find top of status bar (first status line from the bottom)
    end = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if status_re.match(lines[i]):
            end = i
            break

    # Find all separator indexes before the status bar
    seps = [i for i in range(end) if sep_re.match(lines[i].strip())]

    if len(seps) < 2:
        return []

    # Walk backwards through separator pairs, skipping empty/prompt-only blocks
    # (e.g. the idle "❯" prompt at the bottom)
    for idx in range(len(seps) - 1, 0, -1):
        start = seps[idx - 1] + 1
        finish = seps[idx]
        block = [l for l in lines[start:finish] if l.strip() and l.strip() != "❯"]
        if block:
            # Return the full slice (with blank lines), just confirmed non-empty
            return lines[start:finish]

    return []


EXTRACTORS = {
    "opencode": extract_opencode,
    "claude-code": extract_claude_code,
    # "cursor": extract_cursor,  # TODO
    # "codex": extract_codex,    # TODO
}

agent_key = detect_agent(lines)
extractor = EXTRACTORS.get(agent_key)

if extractor:
    block = extractor(lines)
else:
    block = []

# Fallback: last 80 lines before end-of-buffer
if not block:
    block = lines[max(0, len(lines) - 80):len(lines)]

import os, shutil
_debug = "/tmp/output-comment-composer-debug"
os.makedirs(_debug, exist_ok=True)
try:
    shutil.copy(raw_path, os.path.join(_debug, "raw-snapshot.txt"))
    _seps_info = ""
    with open(os.path.join(_debug, "debug.txt"), "w") as dbg:
        dbg.write(f"agent={agent_key}\nblock_lines={len(block)}\n")
except Exception:
    pass

with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(block))
    if block:
        f.write("\n")
PY

cat >"$meta_file" <<EOF
SOURCE_PANE_ID=$source_pane
SNAPSHOT_FILE=$snapshot_file
EOF

open_args=(
  plugin pane open
  --plugin "$plugin_id"
  --entrypoint pane
  --placement zoomed
  --target-pane "$source_pane"
  --env "OUTPUT_COMMENT_COMPOSER_META=$meta_file"
  --env "OCC_DEBUG_DIR=$debug_dir"
  --focus
)

if [ -n "$cwd" ]; then
  open_args+=(--cwd "$cwd")
fi

open_json=$("$H" "${open_args[@]}" 2>/dev/null)

new=$(printf '%s' "$open_json" | jq -r '.result.plugin_pane.pane.pane_id // empty' 2>/dev/null)
[ -n "$new" ] || refuse "herdr plugin pane open failed"
printf 'opened %s (overlay) in %s\n' "$new" "$ws"
