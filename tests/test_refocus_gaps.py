import curses
import json
import os
import signal
import tempfile
import unittest

from occ import keys, refocus


class FakeHerdr:
    """Copy of the herdr CLI boundary fake from tests/test_refocus.py."""

    def __init__(self, layouts, workspaces=None):
        self.layouts = layouts
        self.workspaces = workspaces or []
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["pane", "layout"]:
            layout = self.layouts.get(args[3])
            return {"result": {"layout": layout}} if layout else None
        if args[:2] == ["workspace", "list"]:
            return {"result": {"workspaces": self.workspaces}}
        return {"result": {}}

    def mutations(self):
        return [c for c in self.calls if c[0] in ("plugin", "pane") and c[1] in ("focus", "zoom")]


class GapTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.env = {"HERDR_PLUGIN_STATE_DIR": self.dir.name}
        self.kills = []
        refocus.register_pane("w1:p9", os.getpid(), self.env)

    def run_event(self, herdr, name, **data):
        env = dict(self.env)
        env["HERDR_PLUGIN_EVENT"] = name
        env["HERDR_PLUGIN_EVENT_JSON"] = json.dumps({"data": data})
        return refocus.handle_event(env, run=herdr, kill=lambda pid, sig: self.kills.append((pid, sig)))

    @staticmethod
    def layout(focused, zoomed=True, tab="w1:t1"):
        return {"tab_id": tab, "focused_pane_id": focused, "zoomed": zoomed}

    def test_no_registered_plugin_pane_does_nothing(self):
        refocus.unregister_pane("w1:p9", self.env)
        herdr = FakeHerdr({"w1:p9": self.layout("w1:p1")})
        self.assertEqual(self.run_event(herdr, "tab.focused", tab_id="w1:t1", workspace_id="w1"), [])
        self.assertEqual(herdr.mutations(), [])
        self.assertEqual(self.kills, [])

    def test_unzoomed_plugin_pane_already_focused_is_zoomed_without_refocus(self):
        herdr = FakeHerdr({"w1:p9": self.layout("w1:p9", zoomed=False)})
        self.run_event(herdr, "tab.focused", tab_id="w1:t2", workspace_id="w1")
        self.run_event(herdr, "tab.focused", tab_id="w1:t1", workspace_id="w1")
        self.assertIn(["pane", "zoom", "w1:p9", "--on"], herdr.calls)
        self.assertNotIn(["plugin", "pane", "focus", "w1:p9"], herdr.calls)


class _FakeScreen:
    def __init__(self, keys_to_return):
        self.pending = list(keys_to_return)
        self.cleared = 0

    def timeout(self, _ms):
        pass

    def getch(self):
        return self.pending.pop(0) if self.pending else -1

    def clearok(self, flag):
        if flag:
            self.cleared += 1


class ReadKeyRedrawTests(unittest.TestCase):
    def setUp(self):
        refocus.consume_redraw()
        self.addCleanup(refocus.consume_redraw)

    def test_redraw_request_clears_screen_and_returns_resize_when_idle(self):
        refocus._on_redraw_signal(None, None)
        screen = _FakeScreen([-1])
        self.assertEqual(keys.read_key(screen, 1000), curses.KEY_RESIZE)
        self.assertEqual(screen.cleared, 1)

    def test_redraw_request_keeps_a_real_key_pressed_meanwhile(self):
        refocus._on_redraw_signal(None, None)
        screen = _FakeScreen([ord("a")])
        self.assertEqual(keys.read_key(screen, 1000), ord("a"))
        self.assertEqual(screen.cleared, 1)

    def test_no_redraw_request_leaves_read_key_untouched(self):
        screen = _FakeScreen([-1])
        self.assertEqual(keys.read_key(screen, 1000), -1)
        self.assertEqual(screen.cleared, 0)

    def test_event_signal_reaches_the_ui_read_key_as_a_redraw(self):
        previous = signal.getsignal(refocus.REDRAW_SIGNAL)
        self.addCleanup(signal.signal, refocus.REDRAW_SIGNAL, previous)
        refocus.install_redraw_handler()
        dir_ = tempfile.TemporaryDirectory()
        self.addCleanup(dir_.cleanup)
        env = {"HERDR_PLUGIN_STATE_DIR": dir_.name}
        refocus.register_pane("w1:p9", os.getpid(), env)
        herdr = FakeHerdr({"w1:p9": {"tab_id": "w1:t1", "focused_pane_id": "w1:p9", "zoomed": True}})
        env.update(
            HERDR_PLUGIN_EVENT="tab.focused",
            HERDR_PLUGIN_EVENT_JSON=json.dumps({"data": {"tab_id": "w1:t1", "workspace_id": "w1"}}),
        )
        refocus.swap_active_tab("w1:t2", env)
        self.assertEqual(refocus.handle_event(env, run=herdr), ["w1:p9"])
        screen = _FakeScreen([-1])
        self.assertEqual(keys.read_key(screen, 1000), curses.KEY_RESIZE)
        self.assertEqual(screen.cleared, 1)


if __name__ == "__main__":
    unittest.main()
