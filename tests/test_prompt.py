import unittest

from output_comment_composer import ComposerApp


class BuildPromptTests(unittest.TestCase):
    def test_build_prompt_includes_selected_lines_and_comments(self):
        app = ComposerApp.__new__(ComposerApp)
        app.snap_lines = ["first line", "", "third line"]
        app.comments = [(0, 2, "Please clarify this")]

        prompt = app._build_prompt()

        self.assertIn("> first line\n>\n> third line", prompt)
        self.assertIn("Comment:\nPlease clarify this", prompt)


if __name__ == "__main__":
    unittest.main()
