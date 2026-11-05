import tempfile
import unittest

from herdr_shared_ui.mermaid import (
    bundled_mermaid_binary,
    extract_mermaid_source,
    prepare_mermaid_blocks,
    remap_mermaid_comments,
    render_mermaid_ascii,
)


class MermaidTests(unittest.TestCase):
    def test_extracts_only_when_cursor_is_inside_a_mermaid_fence(self):
        blocks = ["intro", "```mermaid", "graph TD", "  A --> B", "```", "tail"]
        roles = ["", "fence", "code", "code", "fence", ""]

        self.assertEqual(extract_mermaid_source(blocks, roles, 0), None)
        self.assertEqual(extract_mermaid_source(blocks, roles, 5), None)
        self.assertEqual(extract_mermaid_source(blocks, roles, 2), "graph TD\n  A --> B")

    def test_does_not_extract_other_languages_or_mismatched_lists(self):
        self.assertIsNone(extract_mermaid_source(["```python", "print(1)"], ["fence", "code"], 1))
        self.assertIsNone(extract_mermaid_source(["```mermaid", "graph TD"], ["fence"], 1))

    def test_renderer_unavailable_falls_back_without_running(self):
        result = render_mermaid_ascii("graph TD\nA-->B", 60, binary_path="/missing/renderer")

        self.assertFalse(result.rendered)
        self.assertIn("unavailable", result.reason)

    def test_rejects_empty_oversized_and_narrow_inputs(self):
        self.assertFalse(render_mermaid_ascii("  ", 60, binary_path="/missing").rendered)
        self.assertFalse(render_mermaid_ascii("x" * (32 * 1024 + 1), 60, binary_path="/missing").rendered)
        self.assertIn("narrow", render_mermaid_ascii("graph TD\nA-->B", 19, binary_path="/missing").reason)

    def test_renders_supported_diagram_with_packaged_binary(self):
        with tempfile.TemporaryDirectory() as cache:
            binary = bundled_mermaid_binary(cache_dir=cache)
            if binary is None:
                self.skipTest("no bundled binary for this operating system and architecture")
            result = render_mermaid_ascii(
                "graph TD\n  A[Start] --> B[Done]", 60, binary_path=binary
            )

        self.assertTrue(result.rendered, result.reason)
        self.assertTrue(any("Start" in line for line in result.lines))

    def test_unsupported_diagram_returns_source_fallback_reason(self):
        with tempfile.TemporaryDirectory() as cache:
            binary = bundled_mermaid_binary(cache_dir=cache)
            if binary is None:
                self.skipTest("no bundled binary for this operating system and architecture")
            result = render_mermaid_ascii("classDiagram\nA <|-- B", 60, binary_path=binary)

        self.assertFalse(result.rendered)
        self.assertTrue(result.reason)

    def test_diagram_wider_than_terminal_uses_source_fallback(self):
        with tempfile.TemporaryDirectory() as cache:
            binary = bundled_mermaid_binary(cache_dir=cache)
            if binary is None:
                self.skipTest("no bundled binary for this operating system and architecture")
            result = render_mermaid_ascii(
                "graph LR\n A[This is an extremely long label that cannot fit] --> B[Also long]",
                20,
                binary_path=binary,
            )

        self.assertFalse(result.rendered)
        self.assertIn("wider", result.reason)

    def test_compatible_fence_is_rendered_automatically_and_maps_source_blocks(self):
        blocks = ["before", "```mermaid", "graph TD", "A --> B", "```", "after"]
        roles = ["", "fence", "code", "code", "fence", ""]

        display, display_roles, hidden, targets = prepare_mermaid_blocks(blocks, roles, 60)

        self.assertEqual(display_roles[1], "mermaid_label")
        self.assertEqual(display[1], "Mermaid preview")
        self.assertIn("┌", display[2] + display[3])
        self.assertEqual(display_roles[4], "mermaid_tail")
        self.assertIn(4, hidden)
        self.assertEqual(targets[4], 3)
        self.assertEqual((display[0], display[5]), ("before", "after"))

    def test_unsupported_fence_remains_source_code(self):
        blocks = ["```mermaid", "classDiagram", "A <|-- B", "```"]
        roles = ["fence", "code", "code", "fence"]

        display, display_roles, hidden, targets = prepare_mermaid_blocks(blocks, roles, 60)

        self.assertEqual(display, blocks)
        self.assertEqual(display_roles, roles)
        self.assertFalse(hidden)
        self.assertEqual(targets, list(range(len(blocks))))

    def test_comments_on_hidden_fence_lines_move_to_the_visible_diagram(self):
        self.assertEqual(
            remap_mermaid_comments({1: "opening", 4: "closing", 5: "after"}, [0, 2, 2, 3, 3, 5]),
            {2: "opening", 3: "closing", 5: "after"},
        )


if __name__ == "__main__":
    unittest.main()
