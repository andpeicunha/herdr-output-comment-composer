import unittest
from unittest.mock import Mock, PropertyMock, patch

from output_comment_composer import CommentInput, ComposerApp, SnapshotViewer


class CopySelectionTests(unittest.TestCase):
    def test_copy_selection_uses_raw_snapshot_lines(self):
        viewer = SnapshotViewer(["one", "two", "three"])
        viewer.sel_start, viewer.sel_end = 1, 2
        app = Mock()

        with patch.object(SnapshotViewer, "app", new_callable=PropertyMock, return_value=app):
            self.assertTrue(viewer.copy_selection())

        app.copy_to_clipboard.assert_called_once_with("two\nthree")
        app.notify.assert_called_once_with("Snapshot text copied", severity="information")

    def test_ctrl_c_copies_snapshot_when_comment_input_has_no_selection(self):
        comment_input = CommentInput("")
        viewer = Mock()
        viewer.copy_selection.return_value = True
        app = Mock()
        app.query_one.return_value = viewer
        event = Mock(key="ctrl+c")

        with patch.object(CommentInput, "app", new_callable=PropertyMock, return_value=app):
            comment_input.on_key(event)

        app.query_one.assert_called_once_with("#viewer", SnapshotViewer)
        event.stop.assert_called_once_with()
        event.prevent_default.assert_called_once_with()

    def test_ctrl_c_without_any_selection_is_stopped(self):
        comment_input = CommentInput("")
        viewer = Mock()
        viewer.copy_selection.return_value = False
        app = Mock()
        app.query_one.return_value = viewer
        event = Mock(key="ctrl+c")

        with patch.object(CommentInput, "app", new_callable=PropertyMock, return_value=app):
            comment_input.on_key(event)

        event.stop.assert_called_once_with()
        event.prevent_default.assert_called_once_with()

    def test_ctrl_s_save_path_stores_comment_and_closes_only_editor(self):
        app = Mock(spec=ComposerApp)
        app.comments = []
        app._editing_comment_idx = None
        viewer = Mock()
        viewer.has_selection.return_value = True
        viewer.sel_start = 2
        viewer.sel_end = 2
        viewer.selection_label.return_value = "line 3"
        inp = Mock()
        inp.text = "Please review this line"
        panel = Mock()
        app.query_one.side_effect = [viewer, inp, panel, viewer]

        ComposerApp.save_comment(app)

        self.assertEqual(app.comments, [(2, 2, "Please review this line")])
        panel.remove_class.assert_called_once_with("visible")
        inp.clear.assert_called_once_with()
        app.call_after_refresh.assert_called_once()
        app.exit.assert_not_called()

    def test_ctrl_s_action_saves_when_editor_is_open(self):
        app = Mock(spec=ComposerApp)
        panel = Mock()
        panel.classes = {"visible"}
        app.query_one.return_value = panel

        ComposerApp.action_save_comment_if_open(app)

        app.save_comment.assert_called_once_with()

    def test_ctrl_s_action_is_a_noop_after_editor_closes(self):
        app = Mock(spec=ComposerApp)
        panel = Mock()
        panel.classes = set()
        app.query_one.return_value = panel

        ComposerApp.action_save_comment_if_open(app)

        app.save_comment.assert_not_called()


if __name__ == "__main__":
    unittest.main()
