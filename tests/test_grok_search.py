from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import envelope, post
from x_grok_reader.grok_search import GrokSearchError, normalize_posts, retrieve, search
from x_grok_reader.response import structured_payload


class ResponseTests(unittest.TestCase):
    def test_normalization_preserves_complete_text_and_equivalent_duplicate(self):
        row = post(text='Article\n\nBraces { } and "quotes"\n' + "body " * 3000)
        duplicate = {**row, "created_at": "2026-09-20T05:00:00-07:00"}
        results = normalize_posts(envelope(row, duplicate), limit=2)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].text, row["text"].strip())
        self.assertEqual(results[0].created_at, "2026-09-20T12:00:00Z")

    def test_safe_concatenation_recovery(self):
        value = {"posts": [post()]}
        for prefix in ({"posts": []}, value):
            e = {
                "structuredOutputError": "trailing characters",
                "structuredOutput": None,
                "text": json.dumps(prefix) + json.dumps(value),
            }
            self.assertEqual(structured_payload(e), value)
            self.assertEqual(len(normalize_posts(e, limit=1)), 1)

    def test_damaged_or_conflicting_recovery_fails(self):
        good = json.dumps({"posts": [post()]})
        for text in (
            "prose " + good,
            good + " prose",
            '{"posts":[]}' + good[:-1],
            good + '{"posts":[]}',
            '{"users":[]}' + good,
            json.dumps({"posts": [post(text="placeholder")]}) + good,
        ):
            with self.subTest(text=text), self.assertRaises(GrokSearchError):
                structured_payload(
                    {"structuredOutputError": "trailing characters", "text": text}
                )

    def test_envelope_error_and_null_cannot_fall_back(self):
        for e in (
            [],
            {"structuredOutput": None, "text": '{"posts":[]}'},
            {"structuredOutputError": "auth failed", "structuredOutput": {"posts": []}},
            {"text": "not JSON"},
            {"structuredOutput": {"posts": [], "extra": True}},
        ):
            with self.subTest(e=e), self.assertRaises(GrokSearchError):
                structured_payload(e)
        self.assertEqual(structured_payload({"text": '{"posts":[]}'}), {"posts": []})

    def test_required_fields_types_ids_dates_and_optional_fields(self):
        bad = [
            ("id", "not-id"),
            ("id", 0),
            ("id", "0"),
            ("id", "9" * 100),
            ("text", None),
            ("text", " "),
            ("author_handle", "bad handle"),
            ("created_at", "yesterday"),
            ("created_at", "2026-09-20"),
            ("created_at", "2026-09-20T22:00:00Z"),
            ("lang", False),
        ]
        for field, value in bad:
            with (
                self.subTest(field=field, value=value),
                self.assertRaises(GrokSearchError),
            ):
                normalize_posts(envelope({**post(), field: value}), limit=1)
        for value in (None, "posts", [None], [{}]):
            with self.subTest(value=value), self.assertRaises(GrokSearchError):
                normalize_posts({"structuredOutput": {"posts": value}}, limit=1)

    def test_limit_does_not_hide_invalid_later_record(self):
        with self.assertRaises(GrokSearchError):
            normalize_posts(envelope(post(), {**post(), "text": None}), limit=1)

    def test_duplicate_conflict_rejected(self):
        with self.assertRaisesRegex(GrokSearchError, "conflicting duplicate"):
            normalize_posts(envelope(post(), post(text="different")), limit=2)

    def test_latest_order_before_limit_and_top_order_preserved(self):
        old, new = post(), post("2026-09-21T12:00:00Z")
        self.assertEqual(
            normalize_posts(envelope(old, new), limit=1, latest=True)[0].id, new["id"]
        )
        self.assertEqual(normalize_posts(envelope(old, new), limit=1)[0].id, old["id"])

    def test_thread_target_before_limit_and_only_target_author_constrained(self):
        parent, target = (
            post(handle="parent"),
            post("2026-09-21T12:00:00Z", handle="target"),
        )
        rows = normalize_posts(
            envelope(parent, target),
            limit=1,
            requested_id=target["id"],
            expected_handle="@TARGET",
        )
        self.assertEqual(rows[0].id, target["id"])
        for kwargs in (
            {"requested_id": "123"},
            {"requested_id": target["id"], "expected_handle": "wrong"},
            {"expected_handle": "target"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(GrokSearchError):
                normalize_posts(envelope(parent, target), limit=1, **kwargs)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.args = {
            "grok_bin": "grok",
            "cwd": Path.cwd(),
            "query": "from:example",
            "limit": 1,
            "mode": "Latest",
        }

    def test_command_boundaries_and_metadata(self):
        env = {
            **envelope(post()),
            "requestId": "test-request",
            "modelUsage": {"test-model": {}},
            "usage": {"total_tokens": 10},
        }
        with patch(
            "x_grok_reader.grok_search.run_process",
            return_value=subprocess.CompletedProcess(
                [], 0, json.dumps(env).encode(), b""
            ),
        ) as runner:
            result = retrieve(**self.args)
        command = runner.call_args.args[0]
        self.assertEqual(command[command.index("--tools") + 1], "x_search")
        for flag in (
            "--sandbox",
            "--json-schema",
            "--no-memory",
            "--no-subagents",
            "--disable-web-search",
        ):
            self.assertIn(flag, command)
        self.assertEqual(result["retrieval"]["model_ids"], ["test-model"])
        self.assertEqual(result["retrieval"]["request_id"], "test-request")
        self.assertEqual(result["posts"][0]["id"], post()["id"])

    def test_thread_and_semantic_prompts_and_compatibility_api(self):
        row = post()
        for operation in ("thread", "semantic"):
            with (
                self.subTest(operation=operation),
                patch(
                    "x_grok_reader.grok_search.run_process",
                    return_value=subprocess.CompletedProcess(
                        [], 0, json.dumps(envelope(row)).encode(), b""
                    ),
                ) as runner,
            ):
                rows = search(
                    **{
                        **self.args,
                        "operation": operation,
                        "query": row["id"]
                        if operation == "thread"
                        else "synthetic concept",
                    }
                )
                self.assertIn(
                    "x_thread_fetch" if operation == "thread" else "x_semantic_search",
                    runner.call_args.args[0][2],
                )
                self.assertEqual(rows[0].id, row["id"])

    def test_errors_preserved_and_no_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            for code, output in ((1, b"{}"), (0, b"bad json"), (0, b"\xff")):
                with (
                    self.subTest(code=code, output=output),
                    patch(
                        "x_grok_reader.grok_search.run_process",
                        return_value=subprocess.CompletedProcess([], code, output, b""),
                    ) as runner,
                ):
                    with self.assertRaises(GrokSearchError):
                        retrieve(**self.args, trace_dir=Path(tmp))
                    self.assertEqual(runner.call_count, 1)
            self.assertEqual(len(list(Path(tmp).glob("*/error.json"))), 3)

    def test_empty_result_explicitly_inconclusive(self):
        with patch(
            "x_grok_reader.grok_search.run_process",
            return_value=subprocess.CompletedProcess(
                [], 0, b'{"structuredOutput":{"posts":[]}}', b""
            ),
        ):
            self.assertEqual(
                retrieve(**self.args)["retrieval"]["status"], "empty_inconclusive"
            )

    def test_invalid_inputs_do_not_start_process(self):
        for change in (
            {"limit": 0},
            {"timeout_seconds": 0},
            {"operation": "bad"},
            {"query": ""},
        ):
            with (
                self.subTest(change=change),
                patch("x_grok_reader.grok_search.run_process") as runner,
            ):
                with self.assertRaises(GrokSearchError):
                    retrieve(**{**self.args, **change})
                runner.assert_not_called()
