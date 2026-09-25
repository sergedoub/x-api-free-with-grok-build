from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from x_grok_reader.config import ConfigError, load_queries


class ConfigTests(unittest.TestCase):
    def test_loads_only_enabled_queries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "queries.toml"
            path.write_text(
                """
[[queries]]
name = "agents"
query = '"ai agents"'
limit = 12
enabled = true

[[queries]]
name = "off"
query = 'ignored'
enabled = false
""",
                encoding="utf-8",
            )
            queries = load_queries(path)
        self.assertEqual([query.name for query in queries], ["agents"])
        self.assertEqual(queries[0].limit, 12)

    def test_rejects_invalid_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "queries.toml"
            path.write_text(
                '[[queries]]\nname = "Not Safe"\nquery = "x"\n',
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                load_queries(path)

    def test_operation_and_window_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queries.toml"
            path.write_text(
                '[[queries]]\nname="recent"\nquery="from:example"\noperation="keyword"\nlookback_days=7\n'
            )
            query = load_queries(path)[0]
            self.assertEqual((query.operation, query.lookback_days), ("keyword", 7))
            for values in (
                'operation="bad"',
                "lookback_days=-1",
                "lookback_days=true",
                'operation="thread"\nlookback_days=7',
            ):
                path.write_text(
                    '[[queries]]\nname="recent"\nquery="example"\n' + values + "\n"
                )
                with self.subTest(values=values), self.assertRaises(ConfigError):
                    load_queries(path)
