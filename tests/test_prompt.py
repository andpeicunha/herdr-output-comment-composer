import unittest

from output_comment_composer import ComposerApp, clean_snapshot_lines


class CleanSnapshotLinesTests(unittest.TestCase):
    def test_removes_trailing_codex_status_line(self):
        lines = [
            "Nenhum arquivo foi alterado.",
            "",
            "gpt-5.6-sol low · ~/Apps/ahkta-core · Context 13% used · 5h 98% left · weekly 98% left · 0.152.0",
        ]

        self.assertEqual(clean_snapshot_lines(lines), ["Nenhum arquivo foi alterado."])

    def test_removes_trailing_claude_mode_status_line(self):
        lines = ["Resposta final", "⏵⏵ bypass permissions on (shift+tab to cycle)"]

        self.assertEqual(clean_snapshot_lines(lines), ["Resposta final"])

    def test_preserves_similar_content_inside_response(self):
        lines = [
            "Context 13% used · weekly 98% left",
            "Esta linha faz parte da resposta.",
        ]

        self.assertEqual(clean_snapshot_lines(lines), lines)


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
