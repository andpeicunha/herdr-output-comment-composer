# output-comment-composer

A keyboard-first [Herdr](https://herdr.io) plugin for reviewing agent output,
adding inline comments, and sending structured feedback without leaving the
terminal.

## Features

- Reads up to 800 recent lines from Codex or Claude JSONL transcripts.
- Falls back to `herdr pane read` for other agents.
- Organizes prompts, assistant output, tools, paragraphs, lists, quotes,
  headings, and code into selectable blocks.
- Wraps long content and comments without hiding the cursor.
- Supports multiline comments, draft-discard confirmation, multi-block copy,
  and structured feedback submission.
- Uses Python's built-in `curses`; no Python package installation is needed.

## Requirements

- [Herdr](https://herdr.io) 0.7.5 or newer.
- Python 3 with `curses` support.
- `jq` for the Herdr pane launcher.

## Installation

```sh
herdr plugin install andpeicunha/herdr-output-comment-composer
```

## Usage

Bind the `toggle` action in your Herdr configuration:

```toml
[[keys.command]]
key = "prefix+c"
type = "plugin_action"
command = "andpeicunha.output-comment-composer.toggle"
description = "output-comment-composer: toggle"
```

### Keys

| Key | Action |
| --- | --- |
| `↑` / `k` | Previous semantic block |
| `↓` / `j` | Next semantic block |
| `u` / `Page Up` | Move half a page up |
| `d` / `Page Down` | Move half a page down |
| `g` / `G` | First / last block |
| `c` | Add or edit a comment |
| `Enter` | Add a line inside the comment editor |
| `Ctrl+S` | Save the open comment |
| `Esc` | Cancel editing; confirm before discarding changes |
| `Space` | Start or finish a multi-block selection |
| `y` | Copy selected blocks through OSC 52 |
| `s` | Send all comments to the source agent |
| `q` | Close the composer |

Use your terminal's paste shortcut, usually `Ctrl+Shift+V`, inside the comment
editor.

## How it works

1. The plugin reads the current agent session metadata from Herdr.
2. Codex and Claude sessions are loaded from their local JSONL transcripts.
3. Recent content is split into semantic Markdown blocks and shown in a zoomed
   `curses` pane.
4. Comments stay in memory until `s` sends a structured prompt through Herdr.

The plugin does not call an external API. The configured agent may have its own
network access after it receives the feedback prompt.

## Supported sources

| Agent | Source |
| --- | --- |
| Codex | `~/.codex/sessions/**/*.jsonl` |
| Claude Code | `~/.claude/projects/**/*.jsonl` |
| Other agents | `herdr pane read` fallback |

## Development

```sh
python3 -m unittest discover -s tests -v
```

For local testing:

```sh
herdr plugin link .
```
