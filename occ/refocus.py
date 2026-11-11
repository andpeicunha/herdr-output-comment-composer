"""Bring the plugin pane back when its tab or workspace becomes active again.

In Herdr 0.9.5 zoom belongs to the tab and follows the focused pane, so after the user
focuses another pane of the same tab and leaves, the zoomed plugin pane comes back
covered or stale. A ``tab.focused`` / ``workspace.focused`` event hook runs
``handle_event`` which focuses the live plugin pane of the activated tab, zooms it again
and asks its UI process to repaint (SIGUSR1). It never reacts to ``pane.focused``.

Herdr 0.9.5 also emits ``tab.focused`` / ``workspace.focused`` (same payload) when focus
only moves between panes inside the already active tab, so the handler remembers the last
active tab and ignores events that do not change it; otherwise it would steal focus.

The UI process registers itself with ``register_pane`` (one file per pane in the plugin
state dir); the handler only trusts entries whose pid is alive and whose pane still exists.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
from typing import Callable, Mapping

HANDLED_EVENTS = ("tab.focused", "workspace.focused")
REDRAW_SIGNAL = signal.SIGUSR1

Runner = Callable[[list[str]], "dict | None"]


def _state_dir(env: Mapping[str, str] = os.environ) -> str:
    return os.path.join(env.get("HERDR_PLUGIN_STATE_DIR") or os.path.join(
        env.get("TMPDIR", "/tmp"), "herdr-plugin-panes"), "panes")


def _last_tab_path(env: Mapping[str, str] = os.environ) -> str:
    return os.path.join(os.path.dirname(_state_dir(env)), "active_tab")


def swap_active_tab(tab_id: str, env: Mapping[str, str] = os.environ) -> str:
    """Store ``tab_id`` as the active tab and return the previous one ("" if unknown)."""
    path = _last_tab_path(env)
    try:
        with open(path, encoding="utf-8") as source:
            previous = source.read().strip()
    except OSError:
        previous = ""
    if previous != tab_id:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as out:
                out.write(tab_id)
        except OSError:
            pass
    return previous


def _entry_path(pane_id: str, env: Mapping[str, str] = os.environ) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in pane_id)
    return os.path.join(_state_dir(env), safe)


def register_pane(pane_id: str, pid: int | None = None, env: Mapping[str, str] = os.environ) -> None:
    """Record that ``pane_id`` hosts this UI process (best effort)."""
    if not pane_id:
        return
    try:
        os.makedirs(_state_dir(env), exist_ok=True)
        with open(_entry_path(pane_id, env), "w", encoding="utf-8") as out:
            json.dump({"pane_id": pane_id, "pid": pid or os.getpid()}, out)
    except OSError:
        pass


def unregister_pane(pane_id: str, env: Mapping[str, str] = os.environ) -> None:
    if not pane_id:
        return
    try:
        os.unlink(_entry_path(pane_id, env))
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def registered_panes(env: Mapping[str, str] = os.environ) -> dict[str, int]:
    """Live registered plugin panes as ``{pane_id: pid}``; stale entries are removed."""
    found: dict[str, int] = {}
    directory = _state_dir(env)
    try:
        names = os.listdir(directory)
    except OSError:
        return found
    for name in names:
        path = os.path.join(directory, name)
        try:
            with open(path, encoding="utf-8") as source:
                data = json.load(source)
            pane_id, pid = str(data["pane_id"]), int(data["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if _pid_alive(pid):
            found[pane_id] = pid
        else:
            try:
                os.unlink(path)
            except OSError:
                pass
    return found


def _herdr_runner(env: Mapping[str, str] = os.environ) -> Runner:
    binary = env.get("HERDR_BIN_PATH", "herdr")

    def run(args: list[str]) -> dict | None:
        try:
            result = subprocess.run([binary, *args], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return None
            return json.loads(result.stdout or "{}")
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None

    return run


def _target_tab(event_name: str, event: dict, run: Runner) -> tuple[str, str]:
    """(workspace_id, tab_id) that just became active; "" for unknown parts."""
    payload = event.get("data", event) if isinstance(event, dict) else {}
    tab_id = payload.get("tab_id") or (payload.get("tab") or {}).get("tab_id") or ""
    workspace_id = payload.get("workspace_id") or (payload.get("workspace") or {}).get("workspace_id") or ""
    if event_name == "workspace.focused" or not tab_id:
        listing = run(["workspace", "list"]) or {}
        for workspace in (listing.get("result") or {}).get("workspaces", []):
            if workspace.get("workspace_id") == workspace_id:
                return workspace_id, workspace.get("active_tab_id") or ""
    return workspace_id, tab_id


def handle_event(
    env: Mapping[str, str] = os.environ,
    run: Runner | None = None,
    kill: Callable[[int, int], None] = os.kill,
) -> list[str]:
    """Refocus + rezoom the plugin pane(s) of the activated tab; returns the pane ids touched."""
    event_name = env.get("HERDR_PLUGIN_EVENT", "")
    if event_name not in HANDLED_EVENTS:  # never pane.focused: must not steal focus
        return []
    try:
        event = json.loads(env.get("HERDR_PLUGIN_EVENT_JSON") or "{}")
    except ValueError:
        event = {}
    run = run or _herdr_runner(env)
    _workspace, tab_id = _target_tab(event_name, event, run)
    if not tab_id:
        return []
    if swap_active_tab(tab_id, env) == tab_id:  # focus moved inside the active tab
        return []
    panes = registered_panes(env)
    if not panes:
        return []
    handled: list[str] = []
    for pane_id, pid in panes.items():
        layout = ((run(["pane", "layout", "--pane", pane_id]) or {}).get("result") or {}).get("layout")
        if not layout or layout.get("tab_id") != tab_id:
            continue
        if layout.get("focused_pane_id") != pane_id:
            run(["plugin", "pane", "focus", pane_id])
        if not layout.get("zoomed") or layout.get("focused_pane_id") != pane_id:
            run(["pane", "zoom", pane_id, "--on"])
        try:
            kill(pid, REDRAW_SIGNAL)
        except OSError:
            pass
        handled.append(pane_id)
    return handled


_redraw_requested = False


def _on_redraw_signal(_signum, _frame) -> None:
    global _redraw_requested
    _redraw_requested = True


def install_redraw_handler() -> None:
    """Let the handler ask this UI process to repaint (SIGUSR1)."""
    try:
        signal.signal(REDRAW_SIGNAL, _on_redraw_signal)
    except (ValueError, OSError):
        pass


def consume_redraw() -> bool:
    """True once per redraw request."""
    global _redraw_requested
    requested, _redraw_requested = _redraw_requested, False
    return requested


def main() -> int:
    handle_event()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
