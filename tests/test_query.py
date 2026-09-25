import unittest
from datetime import datetime, timezone

from tests.fixtures import envelope, post
from x_grok_reader.query import prepare_query
from x_grok_reader.response import GrokSearchError, normalize_posts


class QueryTests(unittest.TestCase):
    def prepare(self, query, **kwargs):
        return prepare_query(
            query,
            operation="keyword",
            mode="Latest",
            now=datetime(2026, 9, 25, tzinfo=timezone.utc),
            **kwargs,
        )

    def test_no_implicit_window_and_opt_in_window(self):
        self.assertEqual(self.prepare("from:example").query, "from:example")
        scoped = self.prepare("from:example", lookback_days=7)
        self.assertEqual(scoped.query, "from:example since:2026-09-18 until:2026-09-26")
        self.assertEqual(scoped.expected_handle, "example")

    def test_historical_boolean_quoted_and_id_bounds_preserved(self):
        for query in (
            "from:a OR from:b",
            "(from:a)",
            '"from:literal"',
            "from:a until:2020-01-01",
            "from:a since_id:123",
        ):
            with self.subTest(query=query):
                scoped = self.prepare(query, lookback_days=7)
                if query == '"from:literal"':
                    self.assertIsNone(scoped.expected_handle)
                else:
                    self.assertEqual(scoped.query, query)

    def test_author_and_date_constraints(self):
        scoped = self.prepare("from:example since:2026-09-20 until:2026-09-21")
        kwargs = {
            "limit": 5,
            "expected_handle": scoped.expected_handle,
            "since": scoped.since,
            "until": scoped.until,
        }
        self.assertEqual(len(normalize_posts(envelope(post()), **kwargs)), 1)
        for row in (
            post("2026-09-19T12:00:00Z"),
            post("2026-09-21T00:00:00Z"),
            post(handle="wrong"),
        ):
            with self.subTest(row=row), self.assertRaises(GrokSearchError):
                normalize_posts(envelope(row), **kwargs)

    def test_invalid_or_conflicting_dates_and_handles(self):
        for query, kwargs in [
            ("from:a", {"expected_handle": "b"}),
            ("x since:2026-02-30", {}),
            ("x since:2026-09-21 until:2026-09-20", {}),
            ('"open', {}),
            ("x", {"lookback_days": -1}),
        ]:
            with self.subTest(query=query), self.assertRaises(GrokSearchError):
                self.prepare(query, **kwargs)

    def test_thread_url_scope_and_invalid_targets(self):
        target = post()["id"]
        scope = prepare_query(
            "https://x.com/example/status/" + target + "?s=20",
            operation="thread",
            mode="Latest",
        )
        self.assertEqual(
            (scope.requested_id, scope.expected_handle), (target, "example")
        )
        for value in (
            "https://evil.test/x.com/example/status/123",
            "https://x.com/example",
            "0",
            "not-id",
        ):
            with self.subTest(value=value), self.assertRaises(GrokSearchError):
                prepare_query(value, operation="thread", mode="Latest")
        with self.assertRaises(GrokSearchError):
            prepare_query(
                "https://x.com/example/status/" + target,
                operation="thread",
                mode="Latest",
                expected_handle="other",
            )
