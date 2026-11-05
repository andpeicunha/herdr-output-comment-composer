from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from occ.settings import next_theme, save_theme, selected_theme


class ComposerThemeSettingsTests(unittest.TestCase):
    def test_invalid_or_missing_theme_falls_back_to_terminal(self):
        with tempfile.TemporaryDirectory() as config:
            with patch.dict(os.environ, {"HERDR_PLUGIN_CONFIG_DIR": config}, clear=True):
                self.assertEqual(selected_theme(), "terminal")
                with open(os.path.join(config, "config.env"), "w", encoding="utf-8") as target:
                    target.write("OCC_THEME=unsupported\n")
                self.assertEqual(selected_theme(), "terminal")

    def test_theme_cycle_persists_and_preserves_other_settings(self):
        with tempfile.TemporaryDirectory() as config:
            path = os.path.join(config, "config.env")
            with open(path, "w", encoding="utf-8") as target:
                target.write("OCC_SIGNATURE=@me\nOCC_THEME=terminal\n")
            with patch.dict(os.environ, {"HERDR_PLUGIN_CONFIG_DIR": config}, clear=True):
                theme = next_theme(selected_theme())
                self.assertEqual(theme, "herdr-dark")
                self.assertTrue(save_theme(theme))
                with open(path, encoding="utf-8") as source:
                    contents = source.read()
                self.assertIn("OCC_SIGNATURE=@me", contents)
                self.assertIn("OCC_THEME=herdr-dark", contents)
                self.assertEqual(selected_theme(), "herdr-dark")


if __name__ == "__main__":
    unittest.main()
