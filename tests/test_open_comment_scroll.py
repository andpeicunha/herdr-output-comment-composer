import asyncio
import unittest

from output_comment_composer import ComposerApp, SnapshotViewer


class _App(ComposerApp):
    def _do_fetch(self):
        return [f"line {i}" for i in range(200)], False


def _open_editor(sel_start, sel_end, scroll_y):
    async def main():
        app = _App()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(0.2)
            viewer = app.query_one("#viewer", SnapshotViewer)
            viewer.sel_start, viewer.sel_end = sel_start, sel_end
            viewer.scroll_to(y=scroll_y, animate=False, immediate=True)
            await pilot.pause(0.1)
            app.action_open_comment()
            await pilot.pause(0.2)
            top = int(viewer.scroll_offset.y)
            visible = viewer.scrollable_content_region.height
        return top, visible

    return asyncio.run(main())


class OpenCommentScrollTests(unittest.TestCase):
    def test_short_selection_at_bottom_stays_visible(self):
        # Line 90 sits on the last visible row before the panel opens.
        top, visible = _open_editor(90, 91, scroll_y=71)

        self.assertLessEqual(top, 90)
        self.assertLess(91, top + visible)

    def test_tall_selection_aligns_first_line_to_top(self):
        top, visible = _open_editor(50, 120, scroll_y=0)

        self.assertGreater(120 - 50 + 1, visible)
        self.assertEqual(top, 50)


if __name__ == "__main__":
    unittest.main()
