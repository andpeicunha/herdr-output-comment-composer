import unittest
from unittest.mock import patch

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

    def test_removes_trailing_claude_composer_block(self):
        lines = [
            "Resposta final do Claude.",
            "",
            "  · /effort                                      ○ low",
            "────────────────────────────────────────────────────────",
            "  ❯",
            "────────────────────────────────────────────────────────",
            "  Sonnet 5 dotfiles/main",
            "  ⏸ manual mode on · ← for agents",
        ]

        self.assertEqual(clean_snapshot_lines(lines), ["Resposta final do Claude."])

    def test_removes_trailing_claude_auto_mode_composer_block(self):
        lines = [
            "Próximo passo: perguntar ao time de plataforma.",
            "✓ Update installed · Restart to update",
            "────────────────────────────────────────────────────────",
            "› sim, monta a mensagem pro time de plataforma",
            "────────────────────────────────────────────────────────",
            "orchestrator·Sonnet 5 | Cont 28% | 5h 43% | 7d 12%",
            "  ⏵ auto mode on (shift+tab to cycle) · ← for agents",
        ]

        self.assertEqual(
            clean_snapshot_lines(lines),
            ["Próximo passo: perguntar ao time de plataforma."],
        )

    def test_detects_claude_composer_by_prompt_boundaries_without_update_banner(self):
        lines = [
            "Resposta válida.",
            "────────────────────────────────────────────────────────",
            "› próximo pedido do usuário",
            "────────────────────────────────────────────────────────",
            "orchestrator·Opus | Cont 31% | 5h 55%",
            "  ⏵ auto mode on (shift+tab to cycle) · ← for agents",
        ]

        self.assertEqual(clean_snapshot_lines(lines), ["Resposta válida."])

    def test_does_not_treat_an_unbounded_prompt_like_response_as_composer(self):
        lines = [
            "Resposta válida.",
            "› este exemplo pertence ao conteúdo",
            "  ⏵ auto mode on (shift+tab to cycle) · ← for agents",
        ]

        self.assertEqual(
            clean_snapshot_lines(lines),
            ["Resposta válida.", "› este exemplo pertence ao conteúdo"],
        )

    def test_removes_trailing_codex_prompt_block(self):
        lines = [
            "Depois, use prefix + r para recarregar o Herdr.",
            "",
            "────────────────────────────────────────────────────────",
            "  ↳  ───────",
            "",
            "› Ask Codex to do anything",
        ]

        self.assertEqual(
            clean_snapshot_lines(lines),
            ["Depois, use prefix + r para recarregar o Herdr."],
        )

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


class FetchPaneReadTests(unittest.TestCase):
    @patch("output_comment_composer.subprocess.run")
    def test_fetches_logical_unwrapped_lines(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = "Uma linha longa sem quebra física.\n"
        app = ComposerApp.__new__(ComposerApp)
        app.source_pane = "pane-123"

        lines = app._fetch_pane_read()

        self.assertEqual(lines, ["Uma linha longa sem quebra física."])
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--source") + 1], "recent-unwrapped")


if __name__ == "__main__":
    unittest.main()
