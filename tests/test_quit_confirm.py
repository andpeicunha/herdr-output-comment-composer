import asyncio
import unittest
from unittest.mock import patch

from output_comment_composer import ComposerApp, ConfirmScreen, SnapshotViewer


class _App(ComposerApp):
    def _do_fetch(self):
        return [f"line {i}" for i in range(20)], False


def _run(scenario):
    async def main():
        app = _App()
        exits = []
        with patch.object(ComposerApp, "exit", lambda self, *a, **k: exits.append(True)):
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause(0.2)
                await scenario(app, pilot)
                await pilot.pause(0.1)
                screen = app.screen
        return exits, screen

    return asyncio.run(main())


class QuitConfirmTests(unittest.TestCase):
    def test_escape_without_comments_exits_immediately(self):
        async def scenario(app, pilot):
            await pilot.press("escape")

        exits, screen = _run(scenario)

        self.assertEqual(exits, [True])
        self.assertNotIsInstance(screen, ConfirmScreen)

    def test_escape_with_comments_asks_and_n_keeps_the_pane(self):
        async def scenario(app, pilot):
            app.comments.append((0, 0, "keep me"))
            await pilot.press("escape")
            await pilot.pause(0.1)
            self.assertIsInstance(app.screen, ConfirmScreen)
            await pilot.press("n")

        exits, screen = _run(scenario)

        self.assertEqual(exits, [])
        self.assertNotIsInstance(screen, ConfirmScreen)

    def test_escape_inside_confirm_keeps_the_pane(self):
        async def scenario(app, pilot):
            app.comments.append((0, 0, "keep me"))
            await pilot.press("q")
            await pilot.pause(0.1)
            await pilot.press("escape")

        exits, _screen = _run(scenario)

        self.assertEqual(exits, [])

    def test_y_confirms_exit(self):
        async def scenario(app, pilot):
            app.comments.append((0, 0, "bye"))
            await pilot.press("q")
            await pilot.pause(0.1)
            await pilot.press("y")

        exits, _screen = _run(scenario)

        self.assertEqual(exits, [True])

    def test_escape_on_typed_draft_asks_before_discarding(self):
        async def scenario(app, pilot):
            viewer = app.query_one("#viewer", SnapshotViewer)
            viewer.sel_start = viewer.sel_end = 3
            app.action_open_comment()
            await pilot.pause(0.1)
            await pilot.press("o", "i")
            await pilot.press("escape")
            await pilot.pause(0.1)
            self.assertIsInstance(app.screen, ConfirmScreen)
            await pilot.press("n")
            await pilot.pause(0.1)
            self.assertEqual(app.query_one("#comment-input").text, "oi")
            await pilot.press("escape")
            await pilot.pause(0.1)
            await pilot.press("y")
            await pilot.pause(0.1)
            self.assertNotIn("visible", app.query_one("#comment-panel").classes)

        exits, _screen = _run(scenario)

        self.assertEqual(exits, [])

    def test_escape_on_empty_draft_closes_without_asking(self):
        async def scenario(app, pilot):
            viewer = app.query_one("#viewer", SnapshotViewer)
            viewer.sel_start = viewer.sel_end = 3
            app.action_open_comment()
            await pilot.pause(0.1)
            await pilot.press("escape")
            await pilot.pause(0.1)
            self.assertNotIsInstance(app.screen, ConfirmScreen)
            self.assertNotIn("visible", app.query_one("#comment-panel").classes)

        exits, _screen = _run(scenario)

        self.assertEqual(exits, [])


if __name__ == "__main__":
    unittest.main()
