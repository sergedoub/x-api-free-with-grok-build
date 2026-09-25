"""Prepare retrieval scope without rewriting complex X query expressions."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .response import GrokSearchError, HANDLE


STATUS_URL = re.compile(
    r"https?://(?:www\.)?(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})/status/([0-9]+)(?:[/?#].*)?",
    re.I,
)


@dataclass(frozen=True)
class Scope:
    query: str
    expected_handle: str | None = None
    requested_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None


def prepare_query(
    query: str,
    *,
    operation: str,
    mode: str,
    expected_handle: str | None = None,
    lookback_days: int = 0,
    now: datetime | None = None,
) -> Scope:
    query = query.strip()
    if operation not in {"keyword", "semantic", "thread"} or mode not in {
        "Latest",
        "Top",
    }:
        raise GrokSearchError("unsupported operation or mode")
    if not query or not 0 <= lookback_days <= 36500:
        raise GrokSearchError("query is empty or lookback-days is outside 0–36500")
    expected = expected_handle.lstrip("@") if expected_handle else None
    if expected and not HANDLE.fullmatch(expected):
        raise GrokSearchError("invalid expected handle")
    if operation == "thread":
        match = STATUS_URL.fullmatch(query)
        if match:
            author, query = match.groups()
            if expected and expected.lower() != author.lower():
                raise GrokSearchError("expected handle conflicts with URL author")
            expected = author
        if not query.isascii() or not query.isdigit() or int(query) <= 0:
            raise GrokSearchError(
                "thread requires an X status URL or positive numeric ID"
            )
        return Scope(query, expected, query)
    if operation == "semantic":
        if lookback_days:
            raise GrokSearchError("lookback-days applies only to keyword searches")
        return Scope(query, expected)
    try:
        tokens = shlex.split(query, posix=False)
    except ValueError as exc:
        raise GrokSearchError("unbalanced query quoting") from exc
    # Preserve boolean/grouped expressions. Quoted operators are literal terms.
    if any(token in {"OR", "AND"} or "(" in token or ")" in token for token in tokens):
        return Scope(query, expected)
    now = now or datetime.now(timezone.utc)
    if (
        mode == "Latest"
        and lookback_days
        and not any(
            token.startswith(("since:", "until:", "since_id:", "max_id:"))
            for token in tokens
        )
    ):
        tokens += [
            "since:" + (now - timedelta(days=lookback_days)).date().isoformat(),
            "until:" + (now + timedelta(days=1)).date().isoformat(),
        ]
        query = " ".join(tokens)
    authors = [token[5:] for token in tokens if token.startswith("from:")]
    if len(authors) == 1 and HANDLE.fullmatch(authors[0]):
        if expected and expected.lower() != authors[0].lower():
            raise GrokSearchError("expected handle conflicts with from: query")
        expected = authors[0]
    bounds = {}
    for operator in ("since", "until"):
        values = [
            token.split(":", 1)[1]
            for token in tokens
            if token.startswith(operator + ":")
        ]
        if len(values) == 1 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", values[0]):
            try:
                bounds[operator] = datetime.fromisoformat(values[0]).replace(
                    tzinfo=timezone.utc
                )
            except ValueError as exc:
                raise GrokSearchError(f"invalid {operator} date") from exc
    if (
        bounds.get("since")
        and bounds.get("until")
        and bounds["since"] >= bounds["until"]
    ):
        raise GrokSearchError("since date must precede until date")
    return Scope(query, expected, **bounds)
