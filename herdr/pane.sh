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

# Runtime state lives in the plugin state dir (see herdr plugin docs); stderr
# goes to the plugin command log (herdr plugin log list --plugin <id>).
state_dir="${HERDR_PLUGIN_STATE_DIR:-${TMPDIR:-/tmp}/output-comment-composer}"

refuse() {
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

mkdir -p "$state_dir" || refuse "cannot create state dir $state_dir"
# One metadata file per workspace, replaced on every open.
meta_file="$state_dir/meta-${ws//[^A-Za-z0-9_.-]/_}.env"

# Session id and agent type of the source pane (best-effort).
session_id=$(printf '%s' "$panes_json" \
  | jq -r --arg p "$source_pane" \
      '.result.panes[] | select(.pane_id == $p) | .agent_session.value // empty' \
  2>/dev/null || true)
agent=$(printf '%s' "$panes_json" \
  | jq -r --arg p "$source_pane" \
      '.result.panes[] | select(.pane_id == $p) | .agent_session.agent // empty' \
  2>/dev/null || true)

cat >"$meta_file" <<EOF
SOURCE_PANE_ID=$source_pane
SESSION_ID=$session_id
SOURCE_CWD=$cwd
AGENT=$agent
EOF

open_args=(
  plugin pane open
  --plugin "$plugin_id"
  --entrypoint pane
  --placement zoomed
  --target-pane "$source_pane"
  --env "OUTPUT_COMMENT_COMPOSER_META=$meta_file"
  --focus
)

if [ -n "$cwd" ]; then
  open_args+=(--cwd "$cwd")
fi

if [ -n "${OCC_MAX_LINES:-}" ]; then
  open_args+=(--env "OCC_MAX_LINES=$OCC_MAX_LINES")
fi

if [ -n "${OCC_SIGNATURE:-}" ]; then
  open_args+=(--env "OCC_SIGNATURE=$OCC_SIGNATURE")
fi

open_json=$("$H" "${open_args[@]}" 2>/dev/null)

new=$(printf '%s' "$open_json" | jq -r '.result.plugin_pane.pane.pane_id // empty' 2>/dev/null)
[ -n "$new" ] || refuse "herdr plugin pane open failed"
printf 'opened %s (zoomed) in %s\n' "$new" "$ws"
