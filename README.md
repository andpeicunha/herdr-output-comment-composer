# output-comment-composer

A [Herdr](https://herdr.io) plugin for annotating your AI agent's output inline.

Opens a frozen snapshot of the agent's last response in a zoomed TUI pane. Select lines, add comments, and send them back as a structured prompt — without losing context or scrolling your session.

## Features

- Captures the last assistant response via Claude Code JSONL session logs (no terminal scroll)
- Falls back to `herdr pane read` for OpenCode, Cursor, Codex, or any other agent
- Word-wrapped preview with internal scroll
- Mouse drag to select lines; keyboard shortcuts for everything
- UTF-8 / accented character support in comment input

## Requirements

- [Herdr](https://herdr.io) ≥ 0.7.5
- Python 3 (standard library only)

## Installation

```sh
herdr plugin install andpeicunha/herdr-output-comment-composer
```

## Usage

Bind the `toggle` action to a key in your Herdr config, then press it from any agent pane.

```toml
# herdr config (config.toml)
[[keybindings]]
key = "c"
modifiers = ["super", "shift"]
action = { plugin = "andpeicunha.output-comment-composer", action_id = "toggle" }
```

### Keys

| Key | Action |
|-----|--------|
| Drag / click | Select lines |
| `c` / `Enter` | Add comment to selection |
| `s` | Send all comments to the agent |
| `j` / `↓` | Scroll down |
| `k` / `↑` | Scroll up |
| `d` / `u` | Half-page down / up |
| `g` / `G` | Top / bottom |
| Mouse wheel | Scroll |
| `q` / `Esc` | Close |

## How it works

1. On toggle, the plugin reads the agent's last response (Claude Code: from `~/.claude/projects/<session>.jsonl`; others: via `herdr pane read`)
2. Opens a zoomed pane with a frozen snapshot of that response
3. You select lines and type comments
4. On `s`, the plugin sends a structured prompt back to the original agent pane

## Supported agents

| Agent | Snapshot source |
|-------|----------------|
| Claude Code | JSONL session log (no scroll side-effect) |
| OpenCode | `herdr pane read` + TUI pattern extraction |
| Others | `herdr pane read` + last 80 lines fallback |
