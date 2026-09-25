"""Fail-closed decoding and validation of model-produced X results."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .model import RetrievedPost


class GrokSearchError(RuntimeError):
    pass


POST_ID = re.compile(r"^[0-9]+$")
HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
POST_FIELDS = tuple(RetrievedPost.__dataclass_fields__)
OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {key: {"type": "string"} for key in POST_FIELDS},
                "required": ["id", "text", "created_at", "author_handle"],
            },
        }
    },
    "required": ["posts"],
}


def _recover(text: object) -> dict:
    if not isinstance(text, str):
        raise GrokSearchError("recovery requires JSON text")
    decoder = json.JSONDecoder()
    objects = []
    remaining = text.strip()
    try:
        while remaining:
            value, end = decoder.raw_decode(remaining)
            objects.append(value)
            remaining = remaining[end:].lstrip()
    except json.JSONDecodeError as exc:
        raise GrokSearchError("malformed JSON or surrounding prose") from exc
    if len(objects) < 2 or not isinstance(objects[-1], dict):
        raise GrokSearchError("recovery requires concatenated result objects")
    final = objects[-1]
    if set(final) != {"posts"} or not isinstance(final["posts"], list):
        raise GrokSearchError("unexpected recovery result shape")
    if any(prior != {"posts": []} and prior != final for prior in objects[:-1]):
        raise GrokSearchError("conflicting preliminary results")
    return final


def structured_payload(envelope: object) -> dict:
    if not isinstance(envelope, dict):
        raise GrokSearchError("Grok output envelope is not an object")
    error = envelope.get("structuredOutputError")
    if error:
        if "trailing characters" not in str(error):
            raise GrokSearchError(f"Grok structured output failed: {error}")
        value = _recover(envelope.get("text"))
    else:
        value = (
            envelope.get("structuredOutput")
            if "structuredOutput" in envelope
            else envelope.get("text")
        )
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise GrokSearchError("Grok returned non-JSON structured text") from exc
    if not isinstance(value, dict) or set(value) != {"posts"}:
        raise GrokSearchError("Grok output lacks a structured posts object")
    return value


def _post(row: object) -> RetrievedPost:
    if not isinstance(row, dict) or set(row) - set(POST_FIELDS):
        raise GrokSearchError("invalid post fields")
    for key in ("id", "text", "created_at", "author_handle"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise GrokSearchError(f"missing or invalid post field: {key}")
    if any(not isinstance(value, str) for value in row.values()):
        raise GrokSearchError("post fields must be strings")
    values = {key: value.strip() for key, value in row.items()}
    values["author_handle"] = values["author_handle"].lstrip("@")
    if (
        not POST_ID.fullmatch(values["id"])
        or len(values["id"]) > 20
        or not 0 < int(values["id"]) < 2**64
    ):
        raise GrokSearchError("invalid post ID")
    if not HANDLE.fullmatch(values["author_handle"]):
        raise GrokSearchError("invalid author handle")
    try:
        stamp = datetime.fromisoformat(values["created_at"].replace("Z", "+00:00"))
        if stamp.utcoffset() is None:
            raise ValueError("timestamp lacks timezone")
        derived = datetime.fromtimestamp(
            ((int(values["id"]) >> 22) + 1288834974657) / 1000, timezone.utc
        )
        if abs((stamp - derived).total_seconds()) > 1:
            raise ValueError("timestamp conflicts with snowflake ID")
    except (ValueError, OverflowError, OSError) as exc:
        raise GrokSearchError(f"post {values['id']}: {exc}") from exc
    values["created_at"] = (
        stamp.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    return RetrievedPost(**values)


def normalize_posts(
    envelope: object,
    *,
    limit: int,
    expected_handle: str | None = None,
    requested_id: str | None = None,
    latest: bool = False,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[RetrievedPost]:
    if not 1 <= limit <= 100:
        raise GrokSearchError("limit must be from 1 to 100")
    rows = structured_payload(envelope).get("posts")
    if not isinstance(rows, list):
        raise GrokSearchError("structured output posts is not an array")
    seen: dict[str, RetrievedPost] = {}
    for row in rows:
        post = _post(row)
        stamp = datetime.fromisoformat(post.created_at.replace("Z", "+00:00"))
        if expected_handle and (not requested_id or post.id == requested_id):
            if post.author_handle.lower() != expected_handle.lstrip("@").lower():
                raise GrokSearchError(
                    f"post {post.id} is not from the requested author"
                )
        if (since and stamp < since) or (until and stamp >= until):
            raise GrokSearchError(
                f"post {post.id} is outside the requested date window"
            )
        if post.id in seen and seen[post.id] != post:
            raise GrokSearchError(f"conflicting duplicate post {post.id}")
        seen[post.id] = post
    posts = list(seen.values())
    if latest:
        posts.sort(key=lambda post: (post.created_at, int(post.id)), reverse=True)
    if requested_id:
        if requested_id not in seen:
            raise GrokSearchError(
                f"requested post {requested_id} missing from response"
            )
        posts = [seen[requested_id]] + [
            post for post in posts if post.id != requested_id
        ]
    return posts[:limit]
