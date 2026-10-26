import unittest

from unittest.mock import patch

from output_comment_composer_plain import (
    build_display_rows,
    build_prompt,
    codex_transcript_blocks,
    comment_preview,
    content_rows_available,
    editor_cursor_position,
    editor_visual_rows,
    expand_transcript_blocks,
    format_markdown_lines,
    group_logical_blocks,
    limit_transcript_blocks,
    needs_discard_confirmation,
    selected_color_pair,
    selection_bounds,
    send_comments,
    split_markdown_blocks,
)


class PlainComposerTests(unittest.TestCase):
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

    def test_multiline_comment_gets_one_display_row_per_line(self):
        rows = build_display_rows(["one"], {0: "first\nsecond"})

        self.assertEqual(
            rows,
            [
                ("line", 0, "one"),
                ("comment", 0, "first"),
                ("comment", 0, "second"),
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
        self.assertEqual(content_rows_available(40), 34)
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
                "Intro paragraph that wraps onto a second source line.",
                "- first",
                "- second",
            ],
        )

    def test_message_marker_only_belongs_to_first_semantic_block(self):
        expanded = expand_transcript_blocks(
            [("assistant", "Paragraph.\n\n- first\n- second")]
        )

        self.assertEqual(
            expanded,
            [
                ("assistant", "Paragraph.", True),
                ("assistant", "- first", False),
                ("assistant", "- second", False),
            ],
        )

    @patch("output_comment_composer_plain.subprocess.run")
    def test_send_uses_agent_prompt(self, run):
        run.return_value.returncode = 0
        run.return_value.stderr = ""

        success, error = send_comments("pane-1", ["one"], {0: "review"})

        self.assertTrue(success)
        self.assertEqual(error, "")
        self.assertEqual(run.call_args.args[0][1:4], ["agent", "prompt", "pane-1"])

    def test_comment_preview_flattens_and_truncates_block(self):
        self.assertEqual(comment_preview("short\n  block"), "short block")
        self.assertEqual(comment_preview("a" * 50, limit=10), "aaaaaaaaa…")


if __name__ == "__main__":
    unittest.main()
