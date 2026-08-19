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
- Python 3 with [Textual](https://github.com/Textualize/textual)

The plugin will try to install Textual automatically on `herdr plugin install`.
If that fails (e.g. pip is not available), install it manually:

```sh
# macOS / most Linux
pip3 install textual

# Ubuntu / Debian / WSL (if pip is not installed)
sudo apt install python3-pip
pip3 install textual

# Ubuntu 24+ / externally-managed Python (PEP 668)
pip3 install textual --break-system-packages
```

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

### Privacy and data flow

The plugin does not call an external API or upload the captured response by
itself. It reads local session data or the local Herdr pane, displays a frozen
snapshot, and sends the resulting comment prompt back through Herdr to the
agent pane. The agent or tools configured by the user may have their own
network access; that behavior is outside this plugin.

The plugin may read:

- Claude Code session files under `~/.claude/projects/`;
- the local OpenCode database under `~/.local/share/opencode/`;
- the current Herdr pane output.

Do not use it on a session containing information you are not allowed to expose
to the configured agent.

## Status and limitations

This is an early open-source plugin for Herdr. The core prompt-building path
has a basic unit test, but the Textual UI and integrations with Claude Code,
OpenCode, and Herdr still require manual validation in a real session.

Known limitations:

- snapshot extraction depends on the output formats of the supported agents;
- the fallback for unknown agents is limited to the last 80 pane lines;
- Python 3, Textual, Herdr, and `jq` must be available in the runtime
  environment;
- dependency installation may require a user-managed Python environment on
  systems that enforce PEP 668.

## Supported agents

| Agent | Snapshot source |
|-------|----------------|
| Claude Code | JSONL session log (no scroll side-effect) |
| OpenCode | `herdr pane read` + TUI pattern extraction |
| Others | `herdr pane read` + last 80 lines fallback |
