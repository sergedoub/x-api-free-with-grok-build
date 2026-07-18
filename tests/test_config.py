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
