import unittest
from unittest.mock import patch

from output_comment_composer import ComposerApp, SnapshotViewer, clean_snapshot_lines


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

    def test_removes_claude_empty_prompt_with_context_meter(self):
        lines = [
            "Quer que eu rode os testes e suba a PR?",
            "────────────────────────────────────────────────────────",
            "orchestrator —",
            "❯",
            "────────────────────────────────────────────────────────",
            "orchestrator·Sonnet 5 | Cont 30% | 5h 48% | 7d 12%",
        ]

        self.assertEqual(
            clean_snapshot_lines(lines),
            ["Quer que eu rode os testes e suba a PR?"],
        )

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


class SnapshotViewerFocusTests(unittest.TestCase):
    def test_targets_saved_annotation_after_selected_line(self):
        comments = [(1, 1, "Revise este ponto")]
        viewer = SnapshotViewer(["primeira", "segunda", "terceira"], comments)
        viewer.sel_start = 1
        viewer.sel_end = 1

        target = viewer._selection_target_row()

        self.assertIsNotNone(target)
        self.assertEqual(viewer._row_map[target][0], "annotation")

    def test_targets_selected_text_when_comment_was_deleted(self):
        viewer = SnapshotViewer(["primeira", "segunda", "terceira"], [])
        viewer.sel_start = 1
        viewer.sel_end = 1

        target = viewer._selection_target_row()

        self.assertIsNotNone(target)
        self.assertEqual(viewer._row_map[target][0], "line_chunk")
        self.assertEqual(viewer._row_map[target][1][0], 1)

    def test_centers_saved_annotation_region(self):
        comments = [(1, 1, "Revise este ponto")]
        viewer = SnapshotViewer(["primeira", "segunda", "terceira"], comments)
        viewer.sel_start = 1
        viewer.sel_end = 1
        viewer.scroll_to_region = unittest.mock.Mock()

        viewer.scroll_selection_into_view()

        viewer.scroll_to_region.assert_called_once()
        self.assertTrue(viewer.scroll_to_region.call_args.kwargs["center"])
        self.assertFalse(viewer.scroll_to_region.call_args.kwargs["x_axis"])


if __name__ == "__main__":
    unittest.main()
