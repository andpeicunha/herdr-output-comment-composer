import unittest
from unittest.mock import patch

from output_comment_composer import (
    ComposerApp,
    SnapshotViewer,
    clean_snapshot_lines,
    reflow_wrapped_prose,
)


class SnapshotViewerWrapTests(unittest.TestCase):
    def test_does_not_wrap_table_lines_with_box_drawing_chars(self):
        """Lines with box-drawing characters should not be wrapped."""
        # Create a long line with box-drawing chars (simulating an ASCII table)
        long_table_line = "│ Header 1     │ Header 2     │ Header 3     │ ... more content that exceeds available width significantly"
        viewer = SnapshotViewer([long_table_line], comments_ref=[])

        # Simulate a narrow viewport that would normally trigger wrapping
        viewer._refresh_row_map(wrap_width=80)

        # Find all chunks for this line (line 0)
        chunks_for_line = [
            value for kind, value in viewer._row_map
            if kind == "line_chunk" and value[0] == 0
        ]

        # Should have exactly 1 chunk (no wrapping)
        self.assertEqual(len(chunks_for_line), 1)
        self.assertIn("│", chunks_for_line[0][2])

    def test_wraps_normal_text_lines_longer_than_available_width(self):
        """Normal text lines should still be wrapped when they exceed available width."""
        long_text = "Este é um texto muito longo sem nenhum caractere especial de caixa que deveria ser quebrado em múltiplas linhas quando a largura disponível for limitada"
        viewer = SnapshotViewer([long_text], comments_ref=[])

        # Simulate a narrow viewport
        viewer._refresh_row_map(wrap_width=80)

        # Find all chunks for this line (line 0)
        chunks_for_line = [
            value for kind, value in viewer._row_map
            if kind == "line_chunk" and value[0] == 0
        ]

        # Should have multiple chunks (wrapping occurred)
        self.assertGreater(len(chunks_for_line), 1)


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

    def test_removes_claude_footer_without_separators_new_format(self):
        """Remove new Claude footer format without horizontal separators."""
        lines = [
            "Próximo passo: você confirmar se quer que eu limpe comentários extras nos YAMLs do pip-core/pip-ops-checklist-aluno também.",
            "",
            "✓ Update installed · Restart to update",
            "",
            "orchestrator –",
            "❯",
            "",
            "@andrecunha",
        ]

        # Should remove everything from the update banner onwards, keeping only response
        self.assertEqual(
            clean_snapshot_lines(lines),
            ["Próximo passo: você confirmar se quer que eu limpe comentários extras nos YAMLs do pip-core/pip-ops-checklist-aluno também."],
        )

    def test_removes_claude_footer_without_separators_without_update_banner(self):
        """Remove new Claude footer format when there's no update banner."""
        lines = [
            "Análise concluída.",
            "",
            "orchestrator —",
            "❯",
            "",
            "@andrecunha",
        ]

        # Should remove footer even without update banner
        self.assertEqual(
            clean_snapshot_lines(lines),
            ["Análise concluída."],
        )

    def test_removes_claude_footer_with_dashes_before_orchestrator_label(self):
        """Remove footer when horizontal dashes precede 'orchestrator' on the same line."""
        lines = [
            "Análise completa com resultado.",
            "",
            "──────────────────────────── orchestrator",
            "❯",
            "",
            "@andpeicunha",
        ]

        # Should remove everything from the dashes+orchestrator line onwards
        self.assertEqual(
            clean_snapshot_lines(lines),
            ["Análise completa com resultado."],
        )

    def test_preserves_legitimate_orchestrator_word_without_prompt_below(self):
        """Preserve lines containing 'orchestrator' when not followed by a prompt."""
        lines = [
            "Este texto menciona que o orchestrator processou a requisição.",
            "A análise está completa.",
        ]

        # Should NOT remove this content since there's no prompt line below "orchestrator"
        self.assertEqual(
            clean_snapshot_lines(lines),
            [
                "Este texto menciona que o orchestrator processou a requisição.",
                "A análise está completa.",
            ],
        )


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


class ReflowWrappedProseTests(unittest.TestCase):
    def test_joins_indented_hard_wraps_in_same_paragraph(self):
        lines = [
            "A maior decisão de produto é se a aula cancelada deve desaparecer ou está sendo",
            "    chamada de Excluir, preservando internamente a ocorrência cancelada para",
            "    histórico e futuras reservas.",
        ]

        self.assertEqual(
            reflow_wrapped_prose(lines),
            [
                "A maior decisão de produto é se a aula cancelada deve desaparecer ou está sendo "
                "chamada de Excluir, preservando internamente a ocorrência cancelada para histórico "
                "e futuras reservas."
            ],
        )

    def test_preserves_lists_paragraphs_and_fenced_code(self):
        lines = [
            "Uma introdução suficientemente longa que termina sem pontuação para continuar",
            "  - item separado",
            "",
            "```python",
            "    print('não juntar')",
            "```",
        ]

        self.assertEqual(reflow_wrapped_prose(lines), lines)


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

    def test_mouse_selection_requests_comment_editor(self):
        viewer = SnapshotViewer(["primeira", "segunda"], [])
        viewer.sel_start = 0
        viewer.sel_end = 1
        viewer.post_message = unittest.mock.Mock()

        viewer._request_comment_for_selection()

        message = viewer.post_message.call_args.args[0]
        self.assertIsInstance(message, SnapshotViewer.SelectionCompleted)


if __name__ == "__main__":
    unittest.main()
