import curses
import hashlib
from pathlib import Path
import unittest
from unittest.mock import Mock

import herdr_shared_ui as ui
from occ.ui import Composer


class Screen:
    def __init__(self, height=10, width=40):
        self.height, self.width = height, width
        self.calls = []

    def getmaxyx(self):
        return self.height, self.width

    def addnstr(self, y, x, text, width, attr):
        self.calls.append((y, x, text[:width], attr))


class SharedUITests(unittest.TestCase):
    def test_pinned_source_digest(self):
        package = Path(ui.__file__).parent
        self.assertEqual(ui.VERSION, '1.0.0')
        self.assertEqual((package / 'VERSION').read_text().strip(), '1.0.0')
        digest = hashlib.sha256((package / '__init__.py').read_bytes()).hexdigest()
        self.assertEqual(digest, '4fe30c2666126511667900a2af8844c6ec626b048594514f581020b11fac5111')
        pin = (package / 'PIN').read_text()
        self.assertTrue(pin.endswith('\n'))
        self.assertNotIn('\\n', pin)
        self.assertEqual(pin.strip(), f'1.0.0 sha256:{digest}')

    def test_palette_in_both_color_modes_and_without_colors(self):
        for count, expected in [(256, (250, 24)), (8, (curses.COLOR_WHITE, curses.COLOR_BLUE))]:
            fake = Mock(COLORS=count, error=curses.error)
            fake.has_colors.return_value = True
            fake.color_pair.side_effect = lambda number: number
            styles = ui.initialize_colors(fake)
            fake.init_pair.assert_any_call(styles['selected'], *expected)
            self.assertIn('active_cursor', styles)
        fake = Mock(error=curses.error)
        fake.has_colors.return_value = False
        self.assertEqual(ui.initialize_colors(fake), {})
        fake.start_color.assert_not_called()

    def test_palette_continues_after_color_pair_failure(self):
        fake = Mock(COLORS=256, error=curses.error)
        fake.has_colors.return_value = True
        fake.init_pair.side_effect = [None, curses.error] + [None] * 20
        fake.color_pair.side_effect = lambda number: number

        styles = ui.initialize_colors(fake)

        self.assertNotIn('active_cursor', styles)
        self.assertIn('pane_border', styles)
        composer = Composer('pane')
        composer.colors = styles
        self.assertEqual(composer.style('active_cursor', curses.A_REVERSE), curses.A_REVERSE)

    def test_composer_frame_title_and_divider(self):
        screen = Screen()
        composer = Composer('pane')
        composer.colors = {'pane_title': 4, 'muted': 8}
        composer.draw_frame(screen, 2)
        self.assertIn((0, 0, '┏' + '━' * 38 + '┓', 2), screen.calls)
        self.assertIn((0, 1, ' ' * 38, 4 | curses.A_BOLD), screen.calls)
        self.assertIn((2, 1, '─' * 38, 8), screen.calls)

    def test_selected_wrapped_and_code_rows_fill_full_width(self):
        screen = Screen()
        composer = Composer('pane')
        composer.lines = ['wrapped', 'code']
        composer.block_kinds = ['assistant', 'assistant']
        composer.block_starts = [True, True]
        composer.cursor = 1
        composer.selection_anchor = 0
        composer.colors = {'selected': 16, 'active_cursor': 32}
        rows = [('line', 0, 'first'), ('continuation', 0, 'second'), ('line', 1, 'code')]
        composer.draw_rows(screen, [('wrapped', 'paragraph'), ('code', 'code')], rows, 0, 3, 38)
        self.assertIn((3, 1, ' ' * 38, 16), screen.calls)
        self.assertIn((4, 1, ' ' * 38, 16), screen.calls)
        self.assertIn((5, 1, ' ' * 38, 32 | curses.A_BOLD), screen.calls)


if __name__ == '__main__':
    unittest.main()
