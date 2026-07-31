#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .model import RetrievedPost


POST_ID = re.compile(r"^[0-9]+$")
HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
DISALLOWED_TOOLS = ",".join(
    [
        "run_terminal_cmd",
        "read_file",
        "write_file",
        "edit_file",
        "search_replace",
        "grep",
        "glob",
        "list_dir",
        "web_search",
        "web_fetch",
    ]
)
OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "created_at": {"type": "string"},
                    "author_handle": {"type": "string"},
                    "author_id": {"type": "string"},
                    "conversation_id": {"type": "string"},
                    "in_reply_to": {"type": "string"},
                    "lang": {"type": "string"},
                },
                "required": ["id", "text", "created_at", "author_handle"],
            },
        }
    },
    "required": ["posts"],
}


class GrokSearchError(RuntimeError):
    pass


def _structured_payload(envelope: object) -> dict:
    if not isinstance(envelope, dict):
        raise GrokSearchError("Grok output envelope is not an object")
    value = envelope.get("structuredOutput")
    if value is None:
        value = envelope.get("text")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise GrokSearchError("Grok returned non-JSON structured text") from exc
    if not isinstance(value, dict):
        raise GrokSearchError("Grok output lacks structured posts")
    return value


def _timestamp(value: object) -> str:
    raw = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GrokSearchError(f"invalid post timestamp: {raw!r}") from exc
    if parsed.tzinfo is None:
        raise GrokSearchError(f"post timestamp lacks timezone: {raw!r}")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def normalize_posts(
    envelope: object,
    *,
    limit: int,
    expected_handle: str | None = None,
) -> list[RetrievedPost]:
    payload = _structured_payload(envelope)
    rows = payload.get("posts")
    if not isinstance(rows, list):
        raise GrokSearchError("structured output posts is not an array")
    expected = (expected_handle or "").lstrip("@").lower()
    seen: set[str] = set()
    posts: list[RetrievedPost] = []
    for row in rows:
        if not isinstance(row, dict):
            raise GrokSearchError("post result is not an object")
        post_id = str(row.get("id", "")).strip()
        handle = str(row.get("author_handle", "")).lstrip("@").strip()
        text = str(row.get("text", "")).strip()
        if not POST_ID.fullmatch(post_id):
            raise GrokSearchError(f"invalid post id: {post_id!r}")
        if not HANDLE.fullmatch(handle):
            raise GrokSearchError(f"invalid author handle: {handle!r}")
        if expected and handle.lower() != expected:
            continue
        if not text:
            raise GrokSearchError(f"post {post_id} has empty text")
        if post_id in seen:
            continue
        seen.add(post_id)
        posts.append(
            RetrievedPost(
                id=post_id,
                text=text,
                created_at=_timestamp(row.get("created_at")),
                author_handle=handle,
                author_id=str(row.get("author_id", "")).strip(),
                conversation_id=str(row.get("conversation_id", "")).strip(),
                in_reply_to=str(row.get("in_reply_to", "")).strip(),
                lang=str(row.get("lang", "")).strip(),
            )
        )
        if len(posts) >= limit:
            break
    return posts


def _run_grok(
    *,
    grok_bin: str,
    cwd: Path,
    prompt: str,
    timeout_seconds: int,
) -> object:
    command: Sequence[str] = [
        grok_bin,
        "-p",
        prompt,
        "--cwd",
        str(cwd),
        "--always-approve",
        "--sandbox",
        "strict",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(OUTPUT_SCHEMA, separators=(",", ":")),
        "--no-memory",
        "--no-subagents",
        "--no-plan",
        "--max-turns",
        "4",
        "--disable-web-search",
        "--disallowed-tools",
        DISALLOWED_TOOLS,
        "--deny",
        "Bash(*)",
        "--deny",
        "Edit(*)",
        "--deny",
        "Read(*)",
        "--deny",
        "Grep(*)",
        "--deny",
        "WebFetch(*)",
        "--deny",
        "MCPTool(*)",
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise GrokSearchError(
            f"Grok retrieval exceeded {timeout_seconds} seconds"
        ) from exc
    if result.returncode:
        raise GrokSearchError(
            f"Grok retrieval failed with exit code {result.returncode}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GrokSearchError("Grok command returned invalid JSON") from exc


def search(
    *,
    grok_bin: str,
    cwd: Path,
    query: str,
    limit: int,
    mode: str,
    expected_handle: str | None,
    timeout_seconds: int = 180,
) -> list[RetrievedPost]:
    if mode not in {"Latest", "Top"}:
        raise GrokSearchError("mode must be Latest or Top")
    prompt = (
        "Use the server-side x_keyword_search tool exactly as a read-only retrieval tool. "
        "Do not use terminal, filesystem, web, MCP, skills, subagents, or memory. "
        f"Search X with mode {mode}, query {json.dumps(query)}, and return at most {limit} posts. "
        "Return complete post text and UTC ISO-8601 created_at values. Do not summarize, "
        "invent fields, or include anything except the requested structured object."
    )
    envelope = _run_grok(
        grok_bin=grok_bin,
        cwd=cwd,
        prompt=prompt,
        timeout_seconds=timeout_seconds,
    )
    return normalize_posts(envelope, limit=limit, expected_handle=expected_handle)


def fetch_thread(
    *,
    grok_bin: str,
    cwd: Path,
    post_id: str,
    limit: int,
    expected_handle: str | None = None,
    timeout_seconds: int = 180,
) -> list[RetrievedPost]:
    cleaned_id = str(post_id).strip()
    if not POST_ID.fullmatch(cleaned_id):
        raise GrokSearchError(f"invalid post id: {cleaned_id!r}")
    prompt = (
        "Use the server-side x_thread_fetch tool exactly as a read-only retrieval tool. "
        "Do not use terminal, filesystem, web, MCP, skills, subagents, or memory. "
        f"Fetch the X post and its thread with post_id {cleaned_id}. "
        f"Return at most {limit} posts from the thread including the root post. "
        "Return complete post text and UTC ISO-8601 created_at values. Do not summarize, "
        "invent fields, or include anything except the requested structured object."
    )
    envelope = _run_grok(
        grok_bin=grok_bin,
        cwd=cwd,
        prompt=prompt,
        timeout_seconds=timeout_seconds,
    )
    posts = normalize_posts(envelope, limit=10_000, expected_handle=None)
    root = next((post for post in posts if post.id == cleaned_id), None)
    if root is None:
        raise GrokSearchError(f"thread root post {cleaned_id} missing from result")
    if expected_handle:
        expected = expected_handle.lstrip("@").lower()
        if root.author_handle.lower() != expected:
            raise GrokSearchError(
                f"thread root author {root.author_handle!r} does not match "
                f"expected handle {expected_handle!r}"
            )
    ordered = [root, *[post for post in posts if post.id != cleaned_id]]
    return ordered[: max(1, limit)]


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--query",
        help="X keyword search query (uses x_keyword_search)",
    )
    source.add_argument(
        "--post-id",
        help="X post id to fetch with its thread (uses x_thread_fetch)",
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--mode",
        choices=("Latest", "Top"),
        default=None,
        help="Search ranking mode for --query only (Latest or Top)",
    )
    parser.add_argument(
        "--expected-handle",
        help=(
            "With --query, keep only posts from this handle. "
            "With --post-id, require the thread root author to match this handle "
            "while keeping replies from other authors."
        ),
    )
    parser.add_argument("--grok-bin", default="grok")
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args()
    if args.post_id is not None and args.mode is not None:
        parser.error("--mode applies only with --query")
    limit = max(1, min(args.limit, 100))
    timeout_seconds = max(10, args.timeout_seconds)
    try:
        if args.post_id is not None:
            posts = fetch_thread(
                grok_bin=args.grok_bin,
                cwd=args.cwd,
                post_id=args.post_id,
                limit=limit,
                expected_handle=args.expected_handle,
                timeout_seconds=timeout_seconds,
            )
        else:
            posts = search(
                grok_bin=args.grok_bin,
                cwd=args.cwd,
                query=args.query,
                limit=limit,
                mode=args.mode or "Latest",
                expected_handle=args.expected_handle,
                timeout_seconds=timeout_seconds,
            )
    except GrokSearchError as exc:
        parser.exit(2, f"Grok retrieval failed: {exc}\n")
    print(json.dumps({"posts": [asdict(post) for post in posts]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
