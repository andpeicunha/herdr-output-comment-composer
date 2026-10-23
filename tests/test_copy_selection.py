import unittest
from unittest.mock import Mock, PropertyMock, patch

from output_comment_composer import CommentInput, SnapshotViewer


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


if __name__ == "__main__":
    unittest.main()
