"""Deterministic entrypoint for virtual-terminal Composer UI tests."""
from __future__ import annotations

import curses
import os
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from occ.ui import Composer


def main() -> None:
    composer = Composer("e2e")
    scenario = os.environ.get("OCC_E2E_SCENARIO", "theme")
    if scenario in {"theme", "close-no", "close-yes"}:
        composer.comments = {0: "unsent test comment"}
    def fake_run(args, **kwargs):
        if len(args) > 3 and args[1:3] == ["agent", "prompt"]:
            with open(os.environ["OCC_E2E_PROMPT"], "w", encoding="utf-8") as stream:
                stream.write(args[4])
        return SimpleNamespace(returncode=0, stderr="")
    with patch("occ.ui.fetch_transcript", return_value=[]), \
         patch("occ.ui.fetch_snapshot", return_value=[
             "# UI preview", "A paragraph for terminal rendering.", "- first item", "- second item",
         ]), patch("occ.herdr_io.subprocess.run", side_effect=fake_run):
        curses.wrapper(composer.run)


if __name__ == "__main__":
    main()
