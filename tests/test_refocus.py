import json
import os
import tempfile
import unittest

from occ import refocus


class FakeHerdr:
    """Answers the herdr CLI calls the handler makes and records the mutating ones."""

    def __init__(self, layouts, workspaces=None):
        self.layouts = layouts  # pane_id -> layout dict
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


class RefocusTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.env = {"HERDR_PLUGIN_STATE_DIR": self.dir.name}
        self.kills = []
        refocus.register_pane("w1:p9", os.getpid(), self.env)

    def event(self, name, **data):
        env = dict(self.env)
        env["HERDR_PLUGIN_EVENT"] = name
        env["HERDR_PLUGIN_EVENT_JSON"] = json.dumps({"event": name.replace(".", "_"), "data": data})
        return env

    def run_event(self, herdr, name, **data):
        return refocus.handle_event(
            self.event(name, **data), run=herdr, kill=lambda pid, sig: self.kills.append((pid, sig))
        )

    @staticmethod
    def layout(focused, zoomed=True, tab="w1:t1"):
        return {"tab_id": tab, "focused_pane_id": focused, "zoomed": zoomed}

    def test_tab_switch_back_refocuses_zooms_and_requests_redraw(self):
        herdr = FakeHerdr({"w1:p9": self.layout("w1:p1")})
        self.run_event(herdr, "tab.focused", tab_id="w1:t2", workspace_id="w1")
        self.assertEqual(self.run_event(herdr, "tab.focused", tab_id="w1:t1", workspace_id="w1"), ["w1:p9"])
        self.assertIn(["plugin", "pane", "focus", "w1:p9"], herdr.calls)
        self.assertIn(["pane", "zoom", "w1:p9", "--on"], herdr.calls)
        self.assertEqual(self.kills, [(os.getpid(), refocus.REDRAW_SIGNAL)])

    def test_already_focused_and_zoomed_only_requests_redraw(self):
        herdr = FakeHerdr({"w1:p9": self.layout("w1:p9")})
        self.run_event(herdr, "tab.focused", tab_id="w1:t2", workspace_id="w1")
        self.run_event(herdr, "tab.focused", tab_id="w1:t1", workspace_id="w1")
        self.assertEqual(herdr.mutations(), [])
        self.assertEqual(len(self.kills), 1)

    def test_focus_moving_inside_the_active_tab_is_ignored(self):
        herdr = FakeHerdr({"w1:p9": self.layout("w1:p1")})
        self.run_event(herdr, "tab.focused", tab_id="w1:t1", workspace_id="w1")  # becomes active
        herdr.calls.clear()
        self.kills.clear()
        # Herdr 0.9.5 re-emits tab/workspace focused for in-tab pane moves.
        self.assertEqual(self.run_event(herdr, "tab.focused", tab_id="w1:t1", workspace_id="w1"), [])
        self.assertEqual(self.run_event(herdr, "workspace.focused", workspace_id="w1"), [])
        self.assertEqual(herdr.mutations(), [])
        self.assertEqual(self.kills, [])

    def test_workspace_switch_uses_the_active_tab_of_that_workspace(self):
        herdr = FakeHerdr(
            {"w1:p9": self.layout("w1:p1")},
            workspaces=[{"workspace_id": "w1", "active_tab_id": "w1:t1"}],
        )
        refocus.swap_active_tab("w2:t1", self.env)
        self.assertEqual(self.run_event(herdr, "workspace.focused", workspace_id="w1"), ["w1:p9"])
        self.assertIn(["pane", "zoom", "w1:p9", "--on"], herdr.calls)

    def test_pane_focused_is_never_handled(self):
        herdr = FakeHerdr({"w1:p9": self.layout("w1:p1")})
        self.assertEqual(self.run_event(herdr, "pane.focused", pane_id="w1:p1", tab_id="w1:t1"), [])
        self.assertEqual(herdr.calls, [])

    def test_plugin_pane_in_another_tab_is_left_alone(self):
        herdr = FakeHerdr({"w1:p9": self.layout("w1:p1", tab="w1:t1")})
        self.assertEqual(self.run_event(herdr, "tab.focused", tab_id="w1:t2", workspace_id="w1"), [])
        self.assertEqual(herdr.mutations(), [])

    def test_stale_registration_is_dropped(self):
        refocus.register_pane("w1:p7", 2**22 + 12345, self.env)
        self.assertEqual(refocus.registered_panes(self.env), {"w1:p9": os.getpid()})
        refocus.unregister_pane("w1:p9", self.env)
        self.assertEqual(refocus.registered_panes(self.env), {})

    def test_redraw_signal_flag_is_consumed_once(self):
        refocus.consume_redraw()
        refocus._on_redraw_signal(None, None)
        self.assertTrue(refocus.consume_redraw())
        self.assertFalse(refocus.consume_redraw())


if __name__ == "__main__":
    unittest.main()
