from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from x_grok_reader import grok_search
from x_grok_reader.grok_search import (
    GrokSearchError,
    fetch_thread,
    normalize_posts,
    search,
)


def _envelope(*posts: dict) -> dict:
    return {"structuredOutput": {"posts": list(posts)}}


class GrokSearchTests(unittest.TestCase):
    def test_normalizes_and_deduplicates_posts(self) -> None:
        envelope = _envelope(
            {
                "id": "123",
                "text": "First post",
                "created_at": "2026-07-18T01:02:03+00:00",
                "author_handle": "reader",
            },
            {
                "id": "123",
                "text": "First post",
                "created_at": "2026-07-18T01:02:03Z",
                "author_handle": "reader",
            },
        )
        posts = normalize_posts(envelope, limit=20, expected_handle="reader")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].created_at, "2026-07-18T01:02:03Z")
        self.assertEqual(posts[0].source_url, "https://x.com/reader/status/123")

    def test_rejects_invalid_post_id(self) -> None:
        envelope = _envelope(
            {
                "id": "not-an-id",
                "text": "No",
                "created_at": "2026-07-18T01:02:03Z",
                "author_handle": "reader",
            }
        )
        with self.assertRaises(GrokSearchError):
            normalize_posts(envelope, limit=20)

    def test_x_keyword_search_invokes_tool_and_normalizes(self) -> None:
        envelope = _envelope(
            {
                "id": "2078289996323148076",
                "text": "Our 2T model will finish initial training next week.",
                "created_at": "2026-07-18T01:25:22Z",
                "author_handle": "elonmusk",
            }
        )
        completed = MagicMock(returncode=0, stdout=json.dumps(envelope).encode())
        with patch(
            "x_grok_reader.grok_search.subprocess.run", return_value=completed
        ) as run:
            posts = search(
                grok_bin="grok",
                cwd=Path("/tmp"),
                query='from:elonmusk "Our 2T model"',
                limit=5,
                mode="Latest",
                expected_handle="elonmusk",
            )
        command = run.call_args.args[0]
        prompt = command[command.index("-p") + 1]
        self.assertEqual(command[0], "grok")
        self.assertIn("x_keyword_search", prompt)
        self.assertIn("Latest", prompt)
        self.assertIn("from:elonmusk", prompt)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].id, "2078289996323148076")
        self.assertEqual(posts[0].author_handle, "elonmusk")

    def test_x_thread_fetch_invokes_tool_and_normalizes(self) -> None:
        envelope = _envelope(
            {
                "id": "2078289996323148076",
                "text": "Our 2T model will finish initial training next week.",
                "created_at": "2026-07-18T01:25:22Z",
                "author_handle": "elonmusk",
                "conversation_id": "2078289996323148076",
            },
            {
                "id": "2078290000000000001",
                "text": "A reply in the thread.",
                "created_at": "2026-07-18T01:30:00Z",
                "author_handle": "reader",
                "conversation_id": "2078289996323148076",
                "in_reply_to": "2078289996323148076",
            },
        )
        completed = MagicMock(returncode=0, stdout=json.dumps(envelope).encode())
        with patch(
            "x_grok_reader.grok_search.subprocess.run", return_value=completed
        ) as run:
            posts = fetch_thread(
                grok_bin="grok",
                cwd=Path("/tmp"),
                post_id="2078289996323148076",
                limit=20,
                expected_handle=None,
            )
        command = run.call_args.args[0]
        prompt = command[command.index("-p") + 1]
        self.assertEqual(command[0], "grok")
        self.assertIn("x_thread_fetch", prompt)
        self.assertIn("2078289996323148076", prompt)
        self.assertNotIn("x_keyword_search", prompt)
        self.assertIn("--sandbox", command)
        self.assertIn("strict", command)
        self.assertIn("--disallowed-tools", command)
        self.assertEqual([post.id for post in posts], [
            "2078289996323148076",
            "2078290000000000001",
        ])
        self.assertEqual(posts[0].author_handle, "elonmusk")
        self.assertEqual(posts[0].conversation_id, "2078289996323148076")
        self.assertEqual(posts[1].in_reply_to, "2078289996323148076")
        self.assertEqual(
            posts[0].source_url,
            "https://x.com/elonmusk/status/2078289996323148076",
        )

    def test_x_thread_fetch_rejects_invalid_post_id_before_invoke(self) -> None:
        with patch("x_grok_reader.grok_search.subprocess.run") as run:
            with self.assertRaises(GrokSearchError):
                fetch_thread(
                    grok_bin="grok",
                    cwd=Path("/tmp"),
                    post_id="not-an-id",
                    limit=5,
                    expected_handle=None,
                )
        run.assert_not_called()

    def test_x_thread_fetch_keeps_other_authors_when_root_handle_checked(self) -> None:
        envelope = _envelope(
            {
                "id": "2078289996323148076",
                "text": "Root post",
                "created_at": "2026-07-18T01:25:22Z",
                "author_handle": "elonmusk",
            },
            {
                "id": "2078290000000000001",
                "text": "Reply from someone else",
                "created_at": "2026-07-18T01:30:00Z",
                "author_handle": "reader",
            },
        )
        completed = MagicMock(returncode=0, stdout=json.dumps(envelope).encode())
        with patch(
            "x_grok_reader.grok_search.subprocess.run", return_value=completed
        ):
            posts = fetch_thread(
                grok_bin="grok",
                cwd=Path("/tmp"),
                post_id="2078289996323148076",
                limit=20,
                expected_handle="elonmusk",
            )
        self.assertEqual(
            [post.author_handle for post in posts],
            ["elonmusk", "reader"],
        )

    def test_x_thread_fetch_rejects_root_handle_mismatch(self) -> None:
        envelope = _envelope(
            {
                "id": "2078289996323148076",
                "text": "Root post",
                "created_at": "2026-07-18T01:25:22Z",
                "author_handle": "someoneelse",
            }
        )
        completed = MagicMock(returncode=0, stdout=json.dumps(envelope).encode())
        with patch(
            "x_grok_reader.grok_search.subprocess.run", return_value=completed
        ):
            with self.assertRaises(GrokSearchError):
                fetch_thread(
                    grok_bin="grok",
                    cwd=Path("/tmp"),
                    post_id="2078289996323148076",
                    limit=5,
                    expected_handle="elonmusk",
                )

    def test_x_thread_fetch_rejects_missing_root_when_handle_checked(self) -> None:
        envelope = _envelope(
            {
                "id": "999",
                "text": "Not the requested root",
                "created_at": "2026-07-18T01:25:22Z",
                "author_handle": "elonmusk",
            }
        )
        completed = MagicMock(returncode=0, stdout=json.dumps(envelope).encode())
        with patch(
            "x_grok_reader.grok_search.subprocess.run", return_value=completed
        ):
            with self.assertRaises(GrokSearchError):
                fetch_thread(
                    grok_bin="grok",
                    cwd=Path("/tmp"),
                    post_id="2078289996323148076",
                    limit=5,
                    expected_handle="elonmusk",
                )

    def test_run_grok_raises_on_nonzero_exit(self) -> None:
        completed = MagicMock(returncode=1, stdout=b"", stderr=b"fail")
        with patch(
            "x_grok_reader.grok_search.subprocess.run", return_value=completed
        ):
            with self.assertRaises(GrokSearchError):
                search(
                    grok_bin="grok",
                    cwd=Path("/tmp"),
                    query="from:elonmusk",
                    limit=1,
                    mode="Latest",
                    expected_handle=None,
                )

    def test_cli_post_id_routes_to_fetch_thread(self) -> None:
        posts = [
            normalize_posts(
                _envelope(
                    {
                        "id": "123",
                        "text": "Root",
                        "created_at": "2026-07-18T01:02:03Z",
                        "author_handle": "reader",
                    }
                ),
                limit=1,
            )[0]
        ]
        with patch.object(grok_search, "fetch_thread", return_value=posts) as fetch:
            with patch.object(
                sys,
                "argv",
                ["grok_search", "--post-id", "123", "--limit", "5"],
            ):
                with patch("builtins.print") as printed:
                    code = grok_search.main()
        self.assertEqual(code, 0)
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.kwargs["post_id"], "123")
        self.assertEqual(fetch.call_args.kwargs["limit"], 5)
        printed.assert_called_once()
        payload = json.loads(printed.call_args.args[0])
        self.assertEqual(payload["posts"][0]["id"], "123")
