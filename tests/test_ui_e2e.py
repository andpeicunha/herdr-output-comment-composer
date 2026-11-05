from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from tests.ui_e2e_support import CursesSession, pyte


@unittest.skipIf(pyte is None, "install pyte to run virtual-terminal E2E tests")
class ComposerTerminalE2ETests(unittest.TestCase):
    def start_ui(self, config: str, scenario: str = "") -> CursesSession:
        root = Path(__file__).resolve().parents[1]
        env = {
            **os.environ, "TERM": "xterm-256color", "LINES": "24", "COLUMNS": "80",
            "HERDR_PLUGIN_CONFIG_DIR": config,
            "HERDR_PLUGIN_STATE_DIR": str(Path(config) / "state"),
            "HERDR_PLUGIN_ROOT": str(root),
            "PYTHONPATH": str(root) + os.pathsep + os.environ.get("PYTHONPATH", ""),
            "OCC_E2E_SCENARIO": scenario,
            "OCC_E2E_PROMPT": str(Path(config) / "prompt.txt"),
        }
        env.pop("OCC_THEME", None)
        return CursesSession([sys.executable, str(root / "tests/ui_e2e_driver.py")], env)

    def test_theme_help_and_keyboard_confirmation_through_real_curses_ui(self):
        with tempfile.TemporaryDirectory() as config, self.start_ui(config, "theme") as ui:
            ui.wait_for("COMMENTS")
            selected_row = next(
                row for row in ui.screen.buffer.values()
                if "second item" in "".join(cell.data for cell in row.values())
            )
            self.assertIn("005f87", {cell.bg for cell in selected_row.values()})
            for theme in ("midnight", "paper", "terminal"):
                ui.send("t")
                ui.wait_for(f"Theme: {theme}")
            saved = (Path(config) / "config.env").read_text(encoding="utf-8")
            self.assertIn("OCC_THEME=terminal", saved)
            ui.send("?")
            ui.send("j" * 20)
            ui.wait_for("cycle and save the viewer theme")
            ui.send("q")
            ui.send("q")
            ui.wait_for("Close without sending?")
            ui.send("\t\n")
            self.assertEqual(ui.process.wait(timeout=3), 0)

    def test_navigation_shift_selection_and_comment_save_and_send_prompt(self):
        with tempfile.TemporaryDirectory() as config, self.start_ui(config, "edit-send") as ui:
            ui.wait_for("COMMENTS")
            ui.send("g")
            ui.send("\x1b[1;2B")
            ui.wait_for("Selected 2 block(s)")
            ui.send("c")
            ui.wait_for("Ctrl+S save")
            ui.send("Please revise")
            ui.send("\x13")
            ui.wait_for("Comment saved on blocks")
            ui.send("s")
            ui.wait_for("Sent 1 comment(s)")
            prompt = (Path(config) / "prompt.txt").read_text(encoding="utf-8")
            self.assertIn("Comment 1 on blocks 1-2:", prompt)
            self.assertIn("Comment:\nPlease revise", prompt)
            self.assertIn("> # UI preview", prompt)

    def test_cancel_unchanged_edit_and_confirm_discard_changed_edit(self):
        with tempfile.TemporaryDirectory() as config, self.start_ui(config, "edit-cancel") as ui:
            ui.wait_for("COMMENTS")
            ui.send("g")
            ui.send("c")
            ui.send("\x1b")
            ui.wait_for("Comment edit cancelled")
            ui.send("c")
            ui.send("draft")
            ui.send("\x1b")
            ui.wait_for("Discard the changes to this comment?")
            ui.send("y")
            ui.wait_for("Comment edit cancelled")
            ui.send("q")
            self.assertEqual(ui.process.wait(timeout=3), 0)

    def test_no_keeps_composer_open_and_yes_closes_with_unsent_comments(self):
        for answer, stays_open in (("n", True), ("y", False)):
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as config, self.start_ui(config, "close-" + ("no" if answer == "n" else "yes")) as ui:
                ui.wait_for("COMMENTS")
                ui.send("q")
                ui.wait_for("Close without sending?")
                ui.send(answer)
                if stays_open:
                    ui.wait_for("COMMENTS")
                    self.assertIsNone(ui.process.poll())
                    ui.send("q")
                    ui.send("y")
                self.assertEqual(ui.process.wait(timeout=3), 0)


if __name__ == "__main__":
    unittest.main()
