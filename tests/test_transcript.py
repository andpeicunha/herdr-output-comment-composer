import json
import os
import tempfile
import unittest
from unittest.mock import patch

from output_comment_composer import (
    ComposerApp,
    codex_transcript_lines,
    find_claude_transcript,
    find_codex_transcript,
    read_claude_transcript,
    read_codex_transcript,
    style_transcript_lines,
    transcript_lines,
    wrap_offsets,
)


def _user(content, **extra):
    return {"type": "user", "message": {"role": "user", "content": content}, **extra}


def _assistant(*blocks, **extra):
    return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}, **extra}


class TranscriptLinesTests(unittest.TestCase):
    def test_renders_prompts_text_and_tools(self):
        entries = [
            _user("Fix the scroll\n<system-reminder>hidden</system-reminder>"),
            _assistant({"type": "thinking", "thinking": "secret"}),
            _assistant({"type": "tool_use", "name": "Bash", "input": {"description": "Run tests", "command": "pytest"}}),
            _user([{"type": "tool_result", "content": "ok"}]),
            _assistant({"type": "text", "text": "Done.\nAll tests pass."}),
        ]

        self.assertEqual(
            transcript_lines(entries),
            [
                "❯ Fix the scroll",
                "",
                "● Bash(Run tests)",
                "",
                "● Done.",
                "  All tests pass.",
            ],
        )

    def test_skips_commands_meta_sidechain_and_other_entry_types(self):
        entries = [
            _user("<command-name>/login</command-name>"),
            _user("<local-command-stdout>Login successful</local-command-stdout>"),
            _user("meta prompt", isMeta=True),
            _assistant({"type": "text", "text": "subagent"}, isSidechain=True),
            {"type": "attachment", "attachment": {}},
            _assistant({"type": "text", "text": "visible"}),
        ]

        self.assertEqual(transcript_lines(entries), ["● visible"])

    def test_keeps_only_the_most_recent_lines(self):
        entries = [_assistant({"type": "text", "text": "\n".join(f"l{i}" for i in range(3000))})]

        lines = transcript_lines(entries)

        self.assertEqual(len(lines), 2000)
        self.assertEqual(lines[-1], "  l2999")


class TranscriptFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = os.path.join(self.tmp.name, "projects", "-home-user-repo")
        os.makedirs(self.project)
        self.path = os.path.join(self.project, "abc-123.jsonl")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(json.dumps(_user("hello")) + "\n")
            f.write("not json\n")
            f.write(json.dumps(_assistant({"type": "text", "text": "hi"})) + "\n")

    def test_finds_transcript_in_any_project_dir(self):
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.tmp.name}):
            self.assertEqual(find_claude_transcript("abc-123"), self.path)
            self.assertIsNone(find_claude_transcript("missing"))
            self.assertIsNone(find_claude_transcript("../escape"))
            self.assertIsNone(find_claude_transcript(""))

    def test_reads_transcript_ignoring_bad_lines(self):
        self.assertEqual(read_claude_transcript(self.path), ["❯ hello", "", "● hi"])

    def test_fetch_prefers_transcript_and_falls_back_to_pane_read(self):
        meta = os.path.join(self.tmp.name, "meta.env")
        with open(meta, "w", encoding="utf-8") as f:
            f.write("SOURCE_PANE_ID=w1:p1\nSESSION_ID=abc-123\nAGENT=claude\n")
        env = {"CLAUDE_CONFIG_DIR": self.tmp.name, "OUTPUT_COMMENT_COMPOSER_META": meta}
        with patch.dict(os.environ, env):
            app = ComposerApp()
            with patch.object(ComposerApp, "_fetch_pane_read", return_value=["pane"]):
                self.assertEqual(app._do_fetch(), (["❯ hello", "", "● hi"], True))
                with open(meta, "w", encoding="utf-8") as f:
                    f.write("SOURCE_PANE_ID=w1:p1\nSESSION_ID=missing\nAGENT=claude\n")
                self.assertEqual(app._do_fetch(), (["pane"], False))
                with open(meta, "w", encoding="utf-8") as f:
                    f.write("SOURCE_PANE_ID=w1:p1\nSESSION_ID=abc-123\nAGENT=cursor\n")
                self.assertEqual(app._do_fetch(), (["pane"], False))


def _codex(payload):
    return {"type": "response_item", "payload": payload}


class CodexTranscriptTests(unittest.TestCase):
    def test_renders_user_assistant_and_tool_calls(self):
        entries = [
            {"type": "session_meta", "payload": {"id": "t1"}},
            _codex({"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "rules"}]}),
            _codex({"type": "message", "role": "user", "content": [{"type": "input_text", "text": "# AGENTS.md instructions"}]}),
            _codex({"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>x</environment_context>"}]}),
            _codex({"type": "message", "role": "user", "content": [{"type": "input_text", "text": "list files"}]}),
            _codex({"type": "reasoning", "summary": []}),
            _codex({"type": "function_call", "name": "shell", "arguments": json.dumps({"command": ["ls", "-la"]})}),
            _codex({"type": "function_call_output", "output": "..."}),
            _codex({"type": "custom_tool_call", "name": "apply_patch", "input": "*** Begin Patch\n..."}),
            _codex({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done."}]}),
        ]

        self.assertEqual(
            codex_transcript_lines(entries),
            [
                "❯ list files",
                "",
                "● shell(ls -la)",
                "",
                "● apply_patch(*** Begin Patch)",
                "",
                "● Done.",
            ],
        )

    def test_finds_rollout_by_thread_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            day = os.path.join(tmp, "sessions", "2026", "10", "15")
            os.makedirs(day)
            path = os.path.join(day, "rollout-2026-10-15T10-00-00-t-123.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(_codex({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "hi"}]})) + "\n")
            with patch.dict(os.environ, {"CODEX_HOME": tmp}):
                self.assertEqual(find_codex_transcript("t-123"), path)
                self.assertIsNone(find_codex_transcript("other"))
            self.assertEqual(read_codex_transcript(path), ["● hi"])


def _spans(text):
    """Return (substring, style) pairs for the styled parts of a Text."""
    return [(text.plain[s.start : s.end], str(s.style)) for s in text.spans]


class StyleTranscriptLinesTests(unittest.TestCase):
    def test_renders_inline_markdown_without_markers(self):
        [line] = style_transcript_lines(["● Use **bold**, *italic* and `code` here"])

        self.assertEqual(line.plain, "● Use bold, italic and code here")
        styled = dict(_spans(line))
        self.assertIn("bold", styled["bold"])
        self.assertIn("italic", styled["italic"])
        self.assertIn("code", styled)

    def test_keeps_snake_case_and_globs_untouched(self):
        [line] = style_transcript_lines(["● run file_name_here with *.py and 2 * 3"])

        self.assertEqual(line.plain, "● run file_name_here with *.py and 2 * 3")

    def test_headings_bullets_and_fences(self):
        lines = style_transcript_lines([
            "● ## Title",
            "  - item **one**",
            "  ```python",
            "  x = **not bold**",
            "  ```",
        ])

        self.assertEqual(
            [line.plain for line in lines],
            ["● Title", "  • item one", "  ```python", "  x = **not bold**", "  ```"],
        )

    def test_user_prompt_is_not_parsed_as_markdown(self):
        lines = style_transcript_lines(["❯ keep **this**", "  and *this*"])

        self.assertEqual([line.plain for line in lines], ["❯ keep **this**", "  and *this*"])

    def test_tool_line_is_styled(self):
        [line] = style_transcript_lines(["● Bash(Run tests)"])

        self.assertEqual(line.plain, "● Bash(Run tests)")
        self.assertIn(("Bash", "bold"), _spans(line))


class WrapOffsetsTests(unittest.TestCase):
    def test_breaks_at_spaces_and_hard_cuts_long_words(self):
        self.assertEqual(wrap_offsets("aaa bbb ccc", 7), [8])
        self.assertEqual(wrap_offsets("abcdefghij", 4), [4, 8])
        self.assertEqual(wrap_offsets("short", 10), [])


if __name__ == "__main__":
    unittest.main()
