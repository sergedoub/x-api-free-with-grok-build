from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path


SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Query:
    name: str
    query: str
    mode: str = "Latest"
    limit: int = 20
    expected_handle: str | None = None


def load_queries(path: Path) -> list[Query]:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read query configuration: {path}") from exc
    rows = payload.get("queries", [])
    if not isinstance(rows, list):
        raise ConfigError("queries must be an array of tables")
    queries: list[Query] = []
    names: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ConfigError("each query must be a table")
        if not row.get("enabled", True):
            continue
        name = str(row.get("name", "")).strip()
        expression = str(row.get("query", "")).strip()
        mode = str(row.get("mode", "Latest")).strip()
        limit = int(row.get("limit", 20))
        expected = str(row.get("expected_handle", "")).lstrip("@").strip() or None
        if not SLUG.fullmatch(name):
            raise ConfigError(f"invalid query name: {name!r}")
        if name in names:
            raise ConfigError(f"duplicate query name: {name}")
        if not expression:
            raise ConfigError(f"query {name} is empty")
        if mode not in {"Latest", "Top"}:
            raise ConfigError(f"query {name} mode must be Latest or Top")
        if not 1 <= limit <= 100:
            raise ConfigError(f"query {name} limit must be from 1 to 100")
        if expected and not HANDLE.fullmatch(expected):
            raise ConfigError(f"query {name} has an invalid expected_handle")
        names.add(name)
        queries.append(Query(name, expression, mode, limit, expected))
    return queries
