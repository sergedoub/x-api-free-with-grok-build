"""Synthetic X records; no real account content or credentials."""

from datetime import datetime


def post(
    stamp="2026-09-20T12:00:00Z", *, handle="example", text="Synthetic post", **extra
):
    timestamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    post_id = str((int(timestamp.timestamp() * 1000) - 1288834974657) << 22)
    return {
        "id": post_id,
        "created_at": stamp,
        "author_handle": handle,
        "text": text,
        **extra,
    }


def envelope(*rows):
    return {"structuredOutput": {"posts": list(rows)}}
