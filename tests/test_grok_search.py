from __future__ import annotations

import unittest

from x_grok_reader.grok_search import GrokSearchError, normalize_posts


class GrokSearchTests(unittest.TestCase):
    def test_normalizes_and_deduplicates_posts(self) -> None:
        envelope = {
            "structuredOutput": {
                "posts": [
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
                ]
            }
        }
        posts = normalize_posts(envelope, limit=20, expected_handle="reader")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].created_at, "2026-07-18T01:02:03Z")
        self.assertEqual(posts[0].source_url, "https://x.com/reader/status/123")

    def test_rejects_invalid_post_id(self) -> None:
        envelope = {
            "structuredOutput": {
                "posts": [
                    {
                        "id": "not-an-id",
                        "text": "No",
                        "created_at": "2026-07-18T01:02:03Z",
                        "author_handle": "reader",
                    }
                ]
            }
        }
        with self.assertRaises(GrokSearchError):
            normalize_posts(envelope, limit=20)
