import os
import tempfile
import unittest

from unittest.mock import patch

from occ.editor import TextBuffer, needs_close_confirmation, needs_discard_confirmation
from occ.herdr_io import build_prompt, send_comments
from occ.layout import (
    build_display_rows,
    content_rows_available,
    editor_cursor_position,
    editor_visual_rows,
    page_target,
    scroll_position_label,
    scrollbar_thumb,
    selection_bounds,
)
from occ.markdown import (
    BOLD_OFF,
    BOLD_ON,
    bold_segments,
    comment_preview,
    expand_transcript_blocks,
    format_markdown_lines,
    group_logical_blocks,
    join_blocks,
    mark_inline_markup,
    render_markdown_table,
    split_code_fences,
    split_markdown_blocks,
)
from occ.settings import parse_config_env, setting
from occ.transcript import (
    codex_transcript_blocks,
    limit_transcript_blocks,
    transcript_max_lines,
)
from occ.ui import _EDITOR_KEYS, Composer, selected_color_pair


class ComposerTests(unittest.TestCase):
    def test_comment_is_rendered_after_its_source_line(self):
        rows = build_display_rows(["one", "two", "three"], {1: "teste"})

        self.assertEqual(
            rows,
            [
                ("line", 0, "one"),
                ("line", 1, "two"),
                ("comment", 1, "teste"),
                ("line", 2, "three"),
            ],
        )

    def test_build_prompt_orders_comments_by_line(self):
        prompt = build_prompt(["one", "two", "three"], {2: "last", 0: "first"})

        self.assertLess(prompt.index("first"), prompt.index("last"))
        self.assertIn("> one", prompt)
        self.assertIn("> three", prompt)

    def test_build_prompt_labels_blocks_and_quotes_every_line(self):
        prompt = build_prompt(["intro", "| a |\n| b |"], {1: "fix table"})

        self.assertIn("Comment 1 on block 2:", prompt)
        self.assertNotIn("lines", prompt)
        self.assertIn("> | a |\n> | b |", prompt)

    def test_build_prompt_signature_is_optional(self):
        self.assertNotIn("—", build_prompt(["one"], {0: "x"}))
        self.assertTrue(
            build_prompt(["one"], {0: "x"}, signature="@someone").endswith("\n\n— @someone\n")
        )

    def test_multiline_comment_gets_one_display_row_per_line(self):
        rows = build_display_rows(["one"], {0: "first\nsecond"})

        self.assertEqual(
            rows,
            [
                ("line", 0, "one"),
                ("comment", 0, "first"),
                ("comment_continuation", 0, "second"),
            ],
        )

    def test_formats_basic_markdown(self):
        formatted = format_markdown_lines(
            ["# Title", "- item", "> quote", "```python", "print('x')", "```"]
        )

        self.assertEqual(formatted[0], ("Title", "heading"))
        self.assertEqual(formatted[1], ("  • item", "bullet"))
        self.assertEqual(formatted[2], ("│ quote", "quote"))
        self.assertEqual(formatted[4], ("  print('x')", "code"))

    def test_discard_confirmation_only_for_changed_draft(self):
        self.assertFalse(needs_discard_confirmation("same", "same"))
        self.assertFalse(needs_discard_confirmation(" same ", "same"))
        self.assertTrue(needs_discard_confirmation("original", "changed"))
        self.assertTrue(needs_discard_confirmation("", "new draft"))

    def test_editor_space_is_removed_from_viewer_height(self):
        self.assertEqual(content_rows_available(40), 33)
        self.assertEqual(content_rows_available(40, reserved_bottom=12), 22)
        self.assertEqual(content_rows_available(8, reserved_bottom=8), 1)

    def test_groups_wrapped_prose_into_one_logical_block(self):
        blocks = group_logical_blocks(
            ["A long paragraph starts here", "and continues here.", "", "- item"]
        )

        self.assertEqual(
            blocks,
            ["A long paragraph starts here and continues here.", "- item"],
        )

    def test_wraps_one_logical_block_into_multiple_display_rows(self):
        rows = build_display_rows(["one two three four"], {}, width=8)

        self.assertGreater(len(rows), 1)
        self.assertTrue(all(row[1] == 0 for row in rows))

    def test_selection_uses_anchor_or_finished_range(self):
        self.assertEqual(selection_bounds(3, None, None), (3, 3))
        self.assertEqual(selection_bounds(3, 7, None), (3, 7))
        self.assertEqual(selection_bounds(3, None, (1, 4)), (1, 4))

    def test_selection_uses_soft_dark_green_when_supported(self):
        self.assertEqual(selected_color_pair(256), (250, 235))
        self.assertEqual(selected_color_pair(8), (2, -1))

    def test_inline_bullets_become_separate_markdown_rows(self):
        formatted = format_markdown_lines(["• first • second • third"])

        self.assertEqual(
            formatted,
            [("  • first\n  • second\n  • third", "bullet")],
        )

    def test_wrapped_rows_use_continuation_kind(self):
        rows = build_display_rows(["one two three four"], {}, width=8)

        self.assertEqual(rows[0][0], "line")
        self.assertTrue(all(row[0] == "continuation" for row in rows[1:]))

    def test_editor_soft_wrap_keeps_cursor_visible(self):
        visual = editor_visual_rows(["abcdefghij"], width=5)

        self.assertEqual(
            visual,
            [(0, 0, "abcde"), (0, 5, "fghij"), (0, 10, "")],
        )
        self.assertEqual(editor_cursor_position(visual, 0, 10), (2, 0))

    def test_codex_transcript_keeps_roles_and_tools(self):
        entries = [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "question"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "answer"}],
                },
            },
            {
                "type": "response_item",
                "payload": {"type": "function_call", "name": "shell"},
            },
        ]

        self.assertEqual(
            codex_transcript_blocks(entries),
            [("user", "question"), ("assistant", "answer"), ("tool", "shell")],
        )

    def test_transcript_limit_keeps_recent_complete_blocks(self):
        blocks = [("assistant", "one\ntwo"), ("user", "three"), ("assistant", "four\nfive")]

        self.assertEqual(
            limit_transcript_blocks(blocks, max_lines=3),
            [("user", "three"), ("assistant", "four\nfive")],
        )

    def test_display_spacing_adds_blank_row_between_blocks(self):
        rows = build_display_rows(["one", "two"], {}, spacing=True)

        self.assertEqual(rows, [("line", 0, "one"), ("spacer", 0, ""), ("line", 1, "two")])

    def test_compact_list_items_do_not_get_blank_rows(self):
        rows = build_display_rows(
            ["- one", "- two", "paragraph"],
            {},
            spacing=True,
            compact_after={0},
        )

        self.assertEqual(
            rows,
            [
                ("line", 0, "- one"),
                ("line", 1, "- two"),
                ("spacer", 1, ""),
                ("line", 2, "paragraph"),
            ],
        )

    def test_each_markdown_list_item_is_a_selectable_block(self):
        blocks = split_markdown_blocks(
            "Intro paragraph that wraps\nonto a second source line.\n\n- first\n- second"
        )

        self.assertEqual(
            blocks,
            [
                ("Intro paragraph that wraps onto a second source line.", ""),
                ("- first", ""),
                ("- second", ""),
            ],
        )

    def test_message_marker_only_belongs_to_first_semantic_block(self):
        expanded = expand_transcript_blocks(
            [("assistant", "Paragraph.\n\n- first\n- second")]
        )

        self.assertEqual(
            expanded,
            [
                ("assistant", "Paragraph.", True, ""),
                ("assistant", "- first", False, ""),
                ("assistant", "- second", False, ""),
            ],
        )

    @patch("occ.herdr_io.subprocess.run")
    def test_send_uses_agent_prompt(self, run):
        run.return_value.returncode = 0
        run.return_value.stderr = ""

        success, error = send_comments("pane-1", ["one"], {0: "review"})

        self.assertTrue(success)
        self.assertEqual(error, "")
        self.assertEqual(run.call_args.args[0][1:4], ["agent", "prompt", "pane-1"])

    def test_wrapped_comment_continues_without_prefix_row(self):
        rows = build_display_rows(["one"], {0: "alpha beta gamma"}, width=20)

        self.assertEqual(
            [kind for kind, _index, _text in rows],
            ["line", "comment", "comment_continuation", "comment_continuation"],
        )

    def test_markdown_table_rows_stay_in_one_block(self):
        blocks = split_markdown_blocks(
            "Intro.\n\n| Name | Value |\n|---|---|\n| alpha | 1 |\nAfter."
        )

        self.assertEqual(
            blocks,
            [
                ("Intro.", ""),
                ("| Name | Value |\n|---|---|\n| alpha | 1 |", ""),
                ("After.", ""),
            ],
        )

    def test_wrapped_list_items_stay_one_block(self):
        lines = [
            "- A receita lista os ingredientes na ordem em que entram. Primeiro o",
            "  tempero, depois o molho, sempre mexendo devagar.",
            "- Misture com cuidado (ex.: use uma colher de",
            "pau) para não quebrar.",
            "1. Separe os ingredientes na bancada",
            "   e meça cada quantidade.",
            "",
            "Parágrafo depois.",
        ]

        self.assertEqual(
            group_logical_blocks(lines),
            [
                "- A receita lista os ingredientes na ordem em que entram. Primeiro o tempero, depois o molho, sempre mexendo devagar.",
                "- Misture com cuidado (ex.: use uma colher de pau) para não quebrar.",
                "1. Separe os ingredientes na bancada e meça cada quantidade.",
                "Parágrafo depois.",
            ],
        )

    def test_blank_line_or_new_block_ends_a_list_item(self):
        self.assertEqual(
            group_logical_blocks(["- item", "", "paragraph", "- next", "## Heading", "text", "---", "after"]),
            ["- item", "paragraph", "- next", "## Heading", "text", "---", "after"],
        )

    def test_bold_can_contain_code_spans(self):
        text = "**Passo 3 — Use o campo `userId`, não o nome.** A lista já tem o `userId`."

        self.assertEqual(
            mark_inline_markup(text),
            f"{BOLD_ON}Passo 3 — Use o campo userId, não o nome.{BOLD_OFF} A lista já tem o userId.",
        )

    def test_bold_pairs_across_code_spans_without_leaking_to_later_bold(self):
        text = (
            "**Passo 4 — Serviço próprio: `example-service`.** (Neste exemplo) "
            "É um serviço **corporativo**, pensado para `a` e `b`."
        )

        self.assertEqual(
            mark_inline_markup(text),
            f"{BOLD_ON}Passo 4 — Serviço próprio: example-service.{BOLD_OFF} (Neste exemplo) "
            f"É um serviço {BOLD_ON}corporativo{BOLD_OFF}, pensado para a e b.",
        )
        self.assertEqual(
            mark_inline_markup("O nível é o **mesmo de `x-y`**, mas **no início**"),
            f"O nível é o {BOLD_ON}mesmo de x-y{BOLD_OFF}, mas {BOLD_ON}no início{BOLD_OFF}",
        )

    def test_unpaired_markers_and_markers_inside_code_stay_literal(self):
        self.assertEqual(mark_inline_markup("a ** b"), "a ** b")
        self.assertEqual(mark_inline_markup("2 ** 3 e 4**5"), "2 ** 3 e 4**5")
        self.assertEqual(mark_inline_markup("só `**x**` aqui"), "só **x** aqui")

    def test_list_items_keep_indentation_but_other_blocks_do_not(self):
        self.assertEqual(
            group_logical_blocks(["- a", "  - b", "    - c", "  ## Title", "  > quote"]),
            ["- a", "  - b", "    - c", "## Title", "> quote"],
        )

    def test_nested_bullets_use_an_inner_marker_per_level(self):
        blocks = ["- a", "  - b", "    - c", "  - d", "- e"]

        self.assertEqual(
            [text for text, _kind in format_markdown_lines(blocks)],
            ["  • a", "    ◦ b", "      ◦ c", "    ◦ d", "  • e"],
        )

    def test_nesting_works_with_four_space_steps_numbers_and_resets(self):
        self.assertEqual(
            [text for text, _kind in format_markdown_lines(["- a", "    - b"])],
            ["  • a", "    ◦ b"],
        )
        self.assertEqual(
            [text for text, _kind in format_markdown_lines(["1. a", "   - b", "2. c"])],
            ["  1. a", "    ◦ b", "  2. c"],
        )
        self.assertEqual(
            [text for text, _kind in format_markdown_lines(["- a", "  - b", "Text", "  - c"])],
            ["  • a", "    ◦ b", "Text", "  • c"],
        )

    def test_wrapped_list_items_get_a_hanging_indent(self):
        rows = build_display_rows(["    ◦ " + "palavra " * 8], {}, width=24)
        continuation = [text for kind, _index, text in rows if kind == "continuation"]

        self.assertTrue(rows[0][2].startswith("    ◦ palavra"))
        self.assertGreater(len(continuation), 1)
        self.assertTrue(all(t.startswith(" " * 6 + "palavra") for t in continuation))

    def test_wrapped_paragraphs_have_no_stray_leading_space(self):
        rows = build_display_rows(["uma frase que quebra em varias linhas curtas"], {}, width=12)

        self.assertGreater(len(rows), 2)
        self.assertFalse(any(text.startswith(" ") for _kind, _index, text in rows))

    def test_code_blocks_keep_their_whitespace(self):
        rows = build_display_rows(
            ["    indented code line that is long"], {}, width=14, preserve_space={0}
        )

        self.assertTrue(rows[0][2].startswith("    indented"))

    def test_horizontal_rule_is_its_own_block_and_drawn_as_a_line(self):
        blocks = group_logical_blocks(["Text before", "", "---", "", "Text after"])
        self.assertEqual(blocks, ["Text before", "---", "Text after"])

        for rule in ("---", "***", "___", "- - -", "*****"):
            self.assertEqual(format_markdown_lines([rule], 20), [("─" * 20, "rule")])
        self.assertEqual(format_markdown_lines(["---"]), [("─" * 40, "rule")])

    def test_rule_like_text_is_not_a_rule(self):
        self.assertEqual(format_markdown_lines(["--"])[0][1], "normal")
        self.assertEqual(format_markdown_lines(["- item"])[0][1], "bullet")
        self.assertEqual(format_markdown_lines(["|---|---|"])[0][1], "table")

    def test_code_fence_splits_into_one_block_per_line(self):
        blocks = split_markdown_blocks(
            "Intro.\n\n```md\n### Languages\n\nTypeScript · Go\n  indented\n```\n\nAfter."
        )

        self.assertEqual(
            blocks,
            [
                ("Intro.", ""),
                ("```md", "fence"),
                ("### Languages", "code"),
                ("TypeScript · Go", "code_gap"),
                ("  indented", "code"),
                ("After.", ""),
            ],
        )

    def test_unclosed_code_fence_keeps_its_lines(self):
        self.assertEqual(
            split_code_fences(["```\nline one\nline two"]),
            [("```", "fence"), ("line one", "code"), ("line two", "code")],
        )

    def test_code_lines_are_not_formatted_as_markdown(self):
        formatted = format_markdown_lines(
            ["```md", "### Languages", "- **item**"], code=["fence", "code", "code"]
        )

        self.assertEqual(
            formatted,
            [
                ("─ code · md " + "─" * 8, "code"),
                ("  ### Languages", "code"),
                ("  - **item**", "code"),
            ],
        )

    def test_join_blocks_keeps_code_lines_together(self):
        lines = ["Intro.", "```md", "### A", "x", "y", "After."]
        code = ["", "fence", "code", "code_gap", "code", ""]

        self.assertEqual(join_blocks(lines, code, 1, 4), "```md\n### A\n\nx\ny")
        self.assertEqual(join_blocks(lines, code, 0, 1), "Intro.\n\n```md")
        self.assertEqual(join_blocks(lines, code, 4, 5), "y\n\nAfter.")

    def test_markdown_table_is_rendered_with_aligned_columns(self):
        rendered = render_markdown_table(
            "| Name | Value |\n|---|---|\n| **alpha** | 1 |\n| beta | 22 |"
        )

        self.assertEqual(
            rendered.splitlines(),
            [
                "Name  │ Value",
                "──────┼──────",
                "alpha │ 1",
                "beta  │ 22",
            ],
        )

    def test_wide_markdown_table_truncates_widest_column(self):
        rendered = render_markdown_table(
            "| Key | Description |\n| a | a very long description |", width=16
        )

        self.assertEqual(
            rendered.splitlines(),
            ["Key │ Descripti…", "a   │ a very lo…"],
        )
        self.assertTrue(all(len(row) <= 16 for row in rendered.splitlines()))

    def test_formats_table_block_with_table_style(self):
        formatted = format_markdown_lines(["| a | b |\n| 1 | 2 |"])

        self.assertEqual(formatted, [("a │ b\n1 │ 2", "table")])

    def test_box_drawn_table_lines_are_not_joined(self):
        blocks = group_logical_blocks(["┌───┐", "│ a │", "└───┘", "text"])

        self.assertEqual(blocks, ["┌───┐\n│ a │\n└───┘", "text"])

    def test_no_wrap_rows_are_truncated_not_wrapped(self):
        rows = build_display_rows(["abcdefghij"], {}, width=4, no_wrap={0})

        self.assertEqual(rows, [("line", 0, "abcd")])

    def test_comment_preview_flattens_and_truncates_block(self):
        self.assertEqual(comment_preview("short\n  block"), "short block")
        self.assertEqual(comment_preview("a" * 50, limit=10), "aaaaaaaaa…")

    def test_page_target_moves_by_display_rows(self):
        # Blocks 0-4, block 1 spans three rows.
        rows = [
            ("line", 0, "a"),
            ("line", 1, "b1"),
            ("continuation", 1, "b2"),
            ("continuation", 1, "b3"),
            ("line", 2, "c"),
            ("line", 3, "d"),
            ("line", 4, "e"),
        ]

        self.assertEqual(page_target(rows, 0, 4), 2)
        self.assertEqual(page_target(rows, 4, -3), 1)
        self.assertEqual(page_target(rows, 3, 50), 4)
        self.assertEqual(page_target(rows, 2, -50), 0)

    def test_page_target_always_advances_past_tall_block(self):
        rows = [("line", 0, "a")] + [("continuation", 0, "x")] * 10 + [("line", 1, "b")]

        self.assertEqual(page_target(rows, 0, 3), 1)
        self.assertEqual(page_target(rows, 1, -1), 0)

    def test_transcript_max_lines_defaults_and_env_override(self):
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("OCC_MAX_LINES", None)
            self.assertEqual(transcript_max_lines(), 500)
        with patch.dict("os.environ", {"OCC_MAX_LINES": "120"}):
            self.assertEqual(transcript_max_lines(), 120)
        for invalid in ("abc", "0", "-5"):
            with patch.dict("os.environ", {"OCC_MAX_LINES": invalid}):
                self.assertEqual(transcript_max_lines(), 500)

    def test_bold_is_marked_in_every_text_style(self):
        lines = ["- **Pane:** text", "1. **Step** one", "## **Title**", "> **q** x", "plain **b**"]
        formatted = [text for text, _kind in format_markdown_lines(lines)]

        self.assertEqual(
            formatted,
            [
                f"  • {BOLD_ON}Pane:{BOLD_OFF} text",
                f"  1. {BOLD_ON}Step{BOLD_OFF} one",
                f"{BOLD_ON}Title{BOLD_OFF}",
                f"│ {BOLD_ON}q{BOLD_OFF} x",
                f"plain {BOLD_ON}b{BOLD_OFF}",
            ],
        )
        self.assertFalse(any("**" in text for text in formatted))

    def test_code_spans_keep_underscores_literal(self):
        self.assertEqual(mark_inline_markup("call `__init__` and __bold__"), f"call __init__ and {BOLD_ON}bold{BOLD_OFF}")
        self.assertEqual(mark_inline_markup("snake_case_name"), "snake_case_name")

    def test_bold_segments_carry_state_across_rows(self):
        first, bold = bold_segments(f"a {BOLD_ON}wrapped")
        second, bold_after = bold_segments(f"span{BOLD_OFF} end", bold)

        self.assertEqual(first, [("a ", False), ("wrapped", True)])
        self.assertTrue(bold)
        self.assertEqual(second, [("span", True), (" end", False)])
        self.assertFalse(bold_after)

    def test_comment_preview_strips_bold_markers(self):
        self.assertEqual(comment_preview("- **Pane:** text"), "- Pane: text")

    def test_text_buffer_starts_at_end_of_existing_text(self):
        buffer = TextBuffer("one\ntwo")

        self.assertEqual((buffer.row, buffer.col), (1, 3))
        self.assertEqual(TextBuffer().lines, [""])

    def test_text_buffer_insert_and_newline_split_line(self):
        buffer = TextBuffer("helloworld")
        buffer.col = 5
        buffer.newline()
        buffer.insert("big ")

        self.assertEqual(buffer.text, "hello\nbig world")
        self.assertEqual((buffer.row, buffer.col), (1, 4))

    def test_text_buffer_backspace_joins_lines_at_line_start(self):
        buffer = TextBuffer("ab\ncd")
        buffer.col = 0
        buffer.backspace()

        self.assertEqual(buffer.text, "abcd")
        self.assertEqual((buffer.row, buffer.col), (0, 2))
        buffer.backspace()
        self.assertEqual(buffer.text, "acd")

    def make_composer(self, blocks=("a", "b", "c", "d")):
        composer = Composer("pane")
        composer.lines = list(blocks)
        composer.block_kinds = ["assistant"] * len(blocks)
        composer.block_code = [""] * len(blocks)
        return composer

    def test_closing_needs_confirmation_only_with_unsent_comments(self):
        self.assertFalse(needs_close_confirmation({}))
        self.assertFalse(needs_close_confirmation({1: "   "}))
        self.assertTrue(needs_close_confirmation({2: "fix this"}))

    def test_close_without_comments_never_asks(self):
        composer = self.make_composer()
        with patch.object(Composer, "confirm_close") as confirm:
            self.assertTrue(composer.request_close(None, escape=False))
            self.assertTrue(composer.request_close(None, escape=True))
        confirm.assert_not_called()

    def test_close_with_comments_asks_and_follows_the_answer(self):
        composer = self.make_composer()
        composer.comments = {1: "unsent"}
        with patch.object(Composer, "confirm_close", return_value=False) as confirm:
            self.assertFalse(composer.request_close(None, escape=False))
            self.assertFalse(composer.request_close(None, escape=True))
        self.assertEqual(confirm.call_count, 2)
        with patch.object(Composer, "confirm_close", return_value=True):
            self.assertTrue(composer.request_close(None, escape=True))
        self.assertEqual(composer.comments, {1: "unsent"})

    def test_escape_clears_a_selection_before_it_closes(self):
        composer = self.make_composer()
        composer.comments = {1: "unsent"}
        composer.toggle_selection()  # selection started on block 0
        composer.cursor = 2
        self.assertTrue(composer.has_selection)
        with patch.object(Composer, "confirm_close", return_value=True) as confirm:
            self.assertFalse(composer.request_close(None, escape=True))
            confirm.assert_not_called()
            self.assertFalse(composer.has_selection)
            self.assertEqual(composer.status, "Selection cleared")
            self.assertTrue(composer.request_close(None, escape=True))

    def test_q_does_not_touch_the_selection(self):
        composer = self.make_composer()
        composer.toggle_selection()
        composer.toggle_selection()  # finished range
        self.assertTrue(composer.has_selection)

        self.assertTrue(composer.request_close(None, escape=False))
        self.assertTrue(composer.has_selection)

    def test_clear_selection_reports_whether_there_was_one(self):
        composer = self.make_composer()
        self.assertFalse(composer.clear_selection())
        composer.toggle_selection()
        self.assertTrue(composer.clear_selection())
        self.assertEqual(composer.current_selection(), (composer.cursor, composer.cursor))

    def test_copy_copies_the_range_and_ends_the_selection(self):
        composer = self.make_composer()
        composer.cursor = 1
        composer.toggle_selection()
        composer.cursor = 2
        with patch("occ.ui.copy_text_to_clipboard") as copy:
            composer.copy_selection()

        copy.assert_called_once_with("b\n\nc")
        self.assertFalse(composer.has_selection)
        self.assertEqual(composer.status, "Copied 2 block(s)")

    def test_text_buffer_clear_line_erases_only_the_current_line(self):
        buffer = TextBuffer("one\ntwo\nthree")
        buffer.row, buffer.col = 1, 2
        buffer.clear_line()

        self.assertEqual(buffer.text, "one\n\nthree")
        self.assertEqual((buffer.row, buffer.col), (1, 0))

    def test_ctrl_u_is_bound_in_the_comment_box(self):
        self.assertIs(_EDITOR_KEYS["\x15"], TextBuffer.clear_line)

    def test_text_buffer_backspace_at_start_does_nothing(self):
        buffer = TextBuffer("x")
        buffer.col = 0
        buffer.backspace()

        self.assertEqual(buffer.text, "x")

    def test_text_buffer_horizontal_moves_wrap_across_lines(self):
        buffer = TextBuffer("ab\ncd")
        buffer.col = 0
        buffer.move_left()
        self.assertEqual((buffer.row, buffer.col), (0, 2))
        buffer.move_right()
        self.assertEqual((buffer.row, buffer.col), (1, 0))

    def test_text_buffer_vertical_moves_clamp_column(self):
        buffer = TextBuffer("long line\nab")
        buffer.move_up()
        self.assertEqual((buffer.row, buffer.col), (0, 2))
        buffer.col = 9
        buffer.move_down()
        self.assertEqual((buffer.row, buffer.col), (1, 2))
        buffer.move_down()
        self.assertEqual((buffer.row, buffer.col), (1, 2))

    def test_scrollbar_hidden_when_content_fits(self):
        self.assertIsNone(scrollbar_thumb(10, 10, 0))
        self.assertIsNone(scrollbar_thumb(3, 10, 0))

    def test_scrollbar_thumb_tracks_position(self):
        # 100 rows, 10 visible: thumb of 1 row moving through a 10-row track.
        self.assertEqual(scrollbar_thumb(100, 10, 0), (0, 1))
        self.assertEqual(scrollbar_thumb(100, 10, 45), (4, 1))
        self.assertEqual(scrollbar_thumb(100, 10, 90), (9, 1))

    def test_scrollbar_thumb_size_matches_visible_share(self):
        self.assertEqual(scrollbar_thumb(20, 10, 0), (0, 5))
        self.assertEqual(scrollbar_thumb(20, 10, 10), (5, 5))

    def test_scroll_position_label(self):
        self.assertEqual(scroll_position_label(10, 10, 0), "")
        self.assertEqual(scroll_position_label(100, 10, 0), "top")
        self.assertEqual(scroll_position_label(100, 10, 45), "50%")
        self.assertEqual(scroll_position_label(100, 10, 90), "end")

    def test_parse_config_env_handles_comments_quotes_and_export(self):
        text = "# comment\n\nOCC_SIGNATURE='@me'\nexport OCC_MAX_LINES = 800\nBROKEN\n=x\n"

        self.assertEqual(
            parse_config_env(text), {"OCC_SIGNATURE": "@me", "OCC_MAX_LINES": "800"}
        )

    def test_setting_reads_config_file_and_env_wins(self):
        with tempfile.TemporaryDirectory() as config_dir:
            with open(os.path.join(config_dir, "config.env"), "w", encoding="utf-8") as config:
                config.write("OCC_SIGNATURE=@from-file\nOCC_MAX_LINES=120\n")
            base = {"HERDR_PLUGIN_CONFIG_DIR": config_dir}
            with patch.dict("os.environ", base, clear=True):
                self.assertEqual(setting("OCC_SIGNATURE"), "@from-file")
                self.assertEqual(transcript_max_lines(), 120)
                self.assertEqual(setting("MISSING", "fallback"), "fallback")
            with patch.dict("os.environ", {**base, "OCC_SIGNATURE": "@from-env"}, clear=True):
                self.assertEqual(setting("OCC_SIGNATURE"), "@from-env")

    def test_setting_without_config_dir_uses_default(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(setting("OCC_SIGNATURE"), "")
            self.assertEqual(transcript_max_lines(), 500)

    def test_comment_preview_uses_table_header_cells(self):
        self.assertEqual(
            comment_preview("| **Item** | Status |\n|---|---|\n| a | b |"),
            "Item · Status",
        )


if __name__ == "__main__":
    unittest.main()
