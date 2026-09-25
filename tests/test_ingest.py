from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from x_grok_reader.config import Query
from x_grok_reader.ingest import raw_document, write_posts


POST = {
    "id": "2078257164242813420",
    "text": "A useful X post",
    "created_at": "2026-07-17T23:14:54Z",
    "author_handle": "example",
}


class IngestTests(unittest.TestCase):
    def test_writes_stable_markdown(self) -> None:
        query = Query("llm-wiki", '"llm wiki"')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(write_posts(root, query, [POST]), 1)
            self.assertEqual(write_posts(root, query, [POST]), 0)
            path = root / "raw/x/llm-wiki/2026-07-17__2078257164242813420.md"
            text = path.read_text(encoding="utf-8")
        self.assertIn(
            'source_url: "https://x.com/example/status/2078257164242813420"', text
        )
        self.assertTrue(text.endswith("A useful X post\n"))

    def test_document_has_no_retrieval_provider_identity(self) -> None:
        text = raw_document(Query("topic", "example"), POST)
        self.assertNotIn("grok", text.lower())
        self.assertNotIn("provider", text.lower())

    def test_retrieve_passes_operation_and_window_without_publishing_metadata(self):
        import json
        import subprocess
        from unittest.mock import patch
        from x_grok_reader.ingest import retrieve

        query = Query("recent", "from:example", operation="keyword", lookback_days=7)
        payload = {
            "posts": [POST],
            "retrieval": {
                "trace_directory": "/private/diagnostics",
                "usage": {"total_tokens": 10},
            },
        }
        with patch(
            "x_grok_reader.ingest.subprocess.run",
            return_value=subprocess.CompletedProcess(
                [], 0, json.dumps(payload).encode(), b""
            ),
        ) as run:
            rows = retrieve("helper", query)
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("--lookback-days") + 1], "7")
        self.assertEqual(args[args.index("--operation") + 1], "keyword")
        text = raw_document(query, rows[0])
        self.assertNotIn("trace_directory", text)
        self.assertNotIn("total_tokens", text)
