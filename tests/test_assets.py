from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AssetTests(unittest.TestCase):
    def test_service_has_vps_boundaries(self) -> None:
        service = (ROOT / "systemd/x-grok-reader.service").read_text(encoding="utf-8")
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn("ProtectHome=true", service)
        self.assertIn("SocketBindDeny=any", service)
        self.assertIn("/run/x-grok-reader", service)
        self.assertNotIn("/home/hermes", service)
        tmpfiles = (ROOT / "systemd/x-grok-reader.tmpfiles").read_text(
            encoding="utf-8"
        )
        self.assertIn("/run/x-grok-reader", tmpfiles)

    def test_publisher_has_no_candidate_push_trigger(self) -> None:
        workflow = (
            ROOT / ".github/workflows/publish-ingest-candidate.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("schedule:", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("\n  push:", workflow)
        self.assertIn("ref: main", workflow)
        self.assertIn("vars.X_READER_ENABLED == 'true'", workflow)
        self.assertIn("candidate-provided code is never executed", workflow.lower())

    def test_no_private_instance_identifiers(self) -> None:
        excluded = {".git", "tests", "__pycache__"}
        text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in ROOT.rglob("*")
            if path.is_file() and not excluded.intersection(path.parts)
        )
        self.assertNotIn("bowerbird" + "-serge", text)
        self.assertNotIn("grim" + "hermes", text)
        self.assertNotIn("sergedoub/" + "bowerbird", text)
