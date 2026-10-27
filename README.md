# output-comment-composer

A keyboard-first [Herdr](https://herdr.io) plugin for reviewing agent output,
adding inline comments, and sending structured feedback without leaving the
terminal.

## Features

- Reads up to 500 recent lines from Codex or Claude JSONL transcripts
  (set `OCC_MAX_LINES` to change the limit).
- Falls back to `herdr pane read` for other agents.
- Organizes prompts, assistant output, tools, paragraphs, lists, quotes,
  headings, tables, and code into selectable blocks.
- Renders Markdown tables with aligned columns, truncating wide cells.
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
| `Shift+↑` / `Shift+↓` | Move a full page up / down |
| `u` / `Page Up` | Move half a page up |
| `d` / `Page Down` | Move half a page down |
| `g` / `G` | First / last block |
| `c` | Open the comment box for the current block |
| `Enter` | Add a line inside the comment editor |
| `Tab` / `Shift+Tab` | Save and keep typing on the next / previous block |
| `Ctrl+S` | Save the comment and close the box |
| `Esc` | Cancel editing; confirm before discarding changes |
| `Space` | Start or finish a multi-block selection |
| `y` | Copy selected blocks through OSC 52 |
| `s` | Send all comments to the source agent |
| `q` | Close the composer |

Use your terminal's paste shortcut, usually `Ctrl+Shift+V`, inside the comment
editor.

### Environment variables

Set these in the environment Herdr runs in; the launcher forwards them to the
composer pane.

| Variable | Default | Effect |
| --- | --- | --- |
| `OCC_MAX_LINES` | `500` | Transcript lines to load |
| `OCC_SIGNATURE` | unset | Signature line appended to the sent prompt, e.g. `@your-handle` |

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
