from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from x_grok_reader.candidate import (
    CandidateError,
    Change,
    apply_candidate,
    diff_changes,
    validate_candidate,
)


CONTENT = """---
author: "@example"
source_url: "https://x.com/example/status/123"
---

Post text
"""


class CandidateTests(unittest.TestCase):
    def test_reads_candidate_addition_from_git_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            subprocess.run(
                ["git", "init", "-b", "main"],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True
            )
            (repo / "README.md").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-m", "base"],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "switch", "-c", "ingest/hetzner/test"],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            path = repo / "raw/x/topic/2026-07-18__123.md"
            path.parent.mkdir(parents=True)
            path.write_text(CONTENT, encoding="utf-8")
            subprocess.run(["git", "add", "raw/x"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-m", "candidate"],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            changes = diff_changes(repo, "main")
        self.assertEqual(changes, [Change("A", "raw/x/topic/2026-07-18__123.md")])

    def test_accepts_only_new_raw_x_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "raw/x/topic/2026-07-18__123.md"
            path.parent.mkdir(parents=True)
            path.write_text(CONTENT, encoding="utf-8")
            result = validate_candidate(
                root, [Change("A", "raw/x/topic/2026-07-18__123.md")]
            )
        self.assertEqual(result, ["raw/x/topic/2026-07-18__123.md"])

    def test_rejects_code_and_modifications(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text("changed", encoding="utf-8")
            with self.assertRaises(CandidateError):
                validate_candidate(root, [Change("M", "README.md")])

    def test_deduplicates_identical_and_rejects_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            main = root / "main"
            candidate = root / "candidate"
            relative = Path("raw/x/topic/2026-07-18__123.md")
            for repo in (main, candidate):
                path = repo / relative
                path.parent.mkdir(parents=True)
                path.write_text(CONTENT, encoding="utf-8")
            result = apply_candidate(main, candidate, [relative.as_posix()])
            self.assertEqual(result[0].outcome, "deduplicated")
            (candidate / relative).write_text(CONTENT + "changed\n", encoding="utf-8")
            with self.assertRaises(CandidateError):
                apply_candidate(main, candidate, [relative.as_posix()])
