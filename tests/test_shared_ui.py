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
        digest = hashlib.sha256()
        for path in sorted(p for p in package.rglob('*') if p.is_file() and p.name != 'PIN' and '__pycache__' not in p.parts):
            relative = path.relative_to(package).as_posix().encode()
            data = path.read_bytes()
            digest.update(len(relative).to_bytes(4, 'big'))
            digest.update(relative)
            digest.update(len(data).to_bytes(8, 'big'))
            digest.update(data)
        pin = (package / 'PIN').read_text(encoding='utf-8').split()
        self.assertEqual(ui.VERSION, '1.1.0')
        self.assertEqual((package / 'VERSION').read_text().strip(), '1.1.0')
        self.assertEqual(pin, ['1.1.0', f'sha256:{digest.hexdigest()}'])

    def test_shared_controls_dispatch_plugin_actions_from_keyboard(self):
        from herdr_shared_ui.controls import Button, ButtonBar, Modal

        bar = ButtonBar([Button("Back", "back"), Button("Confirm", "confirm")])
        self.assertIsNone(bar.handle_key("\t"))
        self.assertEqual(bar.handle_key("\n"), "confirm")
        modal = Modal([Button("Confirm", "confirm")], {"confirm": lambda: True})
        self.assertTrue(modal.handle_key("\n"))

    def test_palette_in_both_color_modes_and_without_colors(self):
        for count, expected in [(256, (250, 24)), (8, (curses.COLOR_WHITE, curses.COLOR_BLUE))]:
            fake = Mock(
                COLORS=count,
                error=curses.error,
                COLOR_BLACK=curses.COLOR_BLACK,
                COLOR_BLUE=curses.COLOR_BLUE,
                COLOR_CYAN=curses.COLOR_CYAN,
                COLOR_GREEN=curses.COLOR_GREEN,
                COLOR_MAGENTA=curses.COLOR_MAGENTA,
                COLOR_RED=curses.COLOR_RED,
                COLOR_WHITE=curses.COLOR_WHITE,
                COLOR_YELLOW=curses.COLOR_YELLOW,
            )
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
