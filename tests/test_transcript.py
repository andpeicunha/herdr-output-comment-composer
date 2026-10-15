import json
import os
import tempfile
import unittest
from unittest.mock import patch

from output_comment_composer import (
    ComposerApp,
    find_claude_transcript,
    read_claude_transcript,
    transcript_lines,
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
                self.assertEqual(app._do_fetch(), ["❯ hello", "", "● hi"])
                with open(meta, "w", encoding="utf-8") as f:
                    f.write("SOURCE_PANE_ID=w1:p1\nSESSION_ID=missing\nAGENT=claude\n")
                self.assertEqual(app._do_fetch(), ["pane"])


if __name__ == "__main__":
    unittest.main()
