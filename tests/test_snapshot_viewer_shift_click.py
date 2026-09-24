"""Test shift+click selection workaround for SnapshotViewer.

This test suite validates the shift+click selection feature, which provides
an alternative to drag-based selection for environments where continuous
MouseMove events are unreliable (e.g., Windows+WSL2).

The shift+click workaround allows users to:
1. Shift+click to set an anchor point
2. Shift+click again to extend selection from anchor to new line
3. Release to confirm selection

This is separate from (but coexists with) drag-based selection.
"""
import unittest
from unittest.mock import Mock, patch
from textual.events import MouseDown, MouseUp

from output_comment_composer import SnapshotViewer


class SnapshotViewerShiftClickTests(unittest.TestCase):
    """Test shift+click selection as alternative to drag."""

    def setUp(self):
        """Create a viewer with test lines."""
        self.lines = ["line 0", "line 1", "line 2", "line 3", "line 4"]
        self.viewer = SnapshotViewer(self.lines, [])

    def _create_mouse_event(self, event_class, shift: bool = False):
        """Create a MouseDown/MouseUp event with mocked stop() method."""
        event = event_class(
            widget=None,
            x=10,
            y=0,
            delta_x=0,
            delta_y=0,
            button=1,
            shift=shift,
            meta=False,
            ctrl=False,
            screen_x=10,
            screen_y=0,
        )
        # Mock stop() method
        event.stop = Mock()
        return event

    def test_first_shift_click_sets_anchor(self):
        """First shift+click (no anchor yet) should set anchor and single-line selection."""
        event = self._create_mouse_event(MouseDown, shift=True)
        
        # Mock _y_to_line to return line 1
        with patch.object(self.viewer, "_y_to_line", return_value=1):
            self.viewer.on_mouse_down(event)
        
        # Should have set anchor and sel_start/end to same line
        self.assertEqual(self.viewer._click_anchor, 1)
        self.assertEqual(self.viewer.sel_start, 1)
        self.assertEqual(self.viewer.sel_end, 1)
        event.stop.assert_called_once()

    def test_second_shift_click_extends_selection(self):
        """Second shift+click should extend selection from anchor to clicked line."""
        # Set anchor via first shift+click
        event1 = self._create_mouse_event(MouseDown, shift=True)
        with patch.object(self.viewer, "_y_to_line", return_value=1):
            self.viewer.on_mouse_down(event1)
        self.assertEqual(self.viewer._click_anchor, 1)
        
        # Second shift+click on line 3 should extend
        event2 = self._create_mouse_event(MouseDown, shift=True)
        with patch.object(self.viewer, "_y_to_line", return_value=3):
            self.viewer.on_mouse_down(event2)
        
        # Should extend from anchor (1) to clicked line (3)
        self.assertEqual(self.viewer._click_anchor, 1)  # Anchor unchanged
        self.assertEqual(self.viewer.sel_start, 1)
        self.assertEqual(self.viewer.sel_end, 3)
        self.assertFalse(self.viewer._dragging)  # shift+click should not trigger drag

    def test_shift_click_then_mouse_up_requests_comment(self):
        """Mouse up after shift+click should request comment editor."""
        # First shift+click
        event_down = self._create_mouse_event(MouseDown, shift=True)
        with patch.object(self.viewer, "_y_to_line", return_value=2):
            self.viewer.on_mouse_down(event_down)
        
        # Mouse up with shift
        event_up = self._create_mouse_event(MouseUp, shift=True)
        with patch.object(self.viewer, "_request_comment_for_selection") as mock_request:
            self.viewer.on_mouse_up(event_up)
            mock_request.assert_called_once()

    def test_non_shift_click_resets_anchor(self):
        """Regular click (no shift) should reset anchor and start drag."""
        # Set anchor via shift+click
        event_shift = self._create_mouse_event(MouseDown, shift=True)
        with patch.object(self.viewer, "_y_to_line", return_value=1):
            self.viewer.on_mouse_down(event_shift)
        self.assertEqual(self.viewer._click_anchor, 1)
        
        # Regular click on line 2 - mock capture_mouse to avoid app requirement
        event_regular = self._create_mouse_event(MouseDown, shift=False)
        with patch.object(self.viewer, "_y_to_line", return_value=2):
            with patch.object(self.viewer, "capture_mouse"):
                self.viewer.on_mouse_down(event_regular)
        
        # Anchor should be reset to new click position, drag should start
        self.assertEqual(self.viewer._click_anchor, 2)
        self.assertEqual(self.viewer._drag_anchor, 2)
        self.assertTrue(self.viewer._dragging)

    def test_shift_click_backward_extends_upward(self):
        """shift+click from anchor=3 to line=1 should select lines 1-3."""
        # Set anchor at line 3
        event1 = self._create_mouse_event(MouseDown, shift=True)
        with patch.object(self.viewer, "_y_to_line", return_value=3):
            self.viewer.on_mouse_down(event1)
        
        # Click at line 1 (above anchor) with shift
        event2 = self._create_mouse_event(MouseDown, shift=True)
        with patch.object(self.viewer, "_y_to_line", return_value=1):
            self.viewer.on_mouse_down(event2)
        
        # Should select 1-3 (sorted)
        self.assertEqual(self.viewer.sel_start, 1)
        self.assertEqual(self.viewer.sel_end, 3)

    def test_shift_click_with_no_drag_anchor_set(self):
        """Shift+click should NOT set _drag_anchor (unlike regular click)."""
        event = self._create_mouse_event(MouseDown, shift=True)
        with patch.object(self.viewer, "_y_to_line", return_value=2):
            self.viewer.on_mouse_down(event)
        
        # After shift+click, _drag_anchor should remain None
        self.assertIsNone(self.viewer._drag_anchor)
        self.assertIsNotNone(self.viewer._click_anchor)

    def test_shift_click_on_none_line_does_nothing(self):
        """Shift+click on non-content (e.g., annotation) should be ignored."""
        event = self._create_mouse_event(MouseDown, shift=True)
        
        # Mock _y_to_line to return None (e.g., clicked on annotation)
        with patch.object(self.viewer, "_y_to_line", return_value=None):
            self.viewer.on_mouse_down(event)
        
        # Nothing should happen
        self.assertIsNone(self.viewer._click_anchor)
        self.assertIsNone(self.viewer.sel_start)


if __name__ == "__main__":
    unittest.main()
