#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .config import Query, load_queries


class IngestError(RuntimeError):
    pass


def retrieve(helper: str, query: Query) -> list[dict]:
    command = [
        helper,
        "--query",
        query.query,
        "--limit",
        str(query.limit),
        "--mode",
        query.mode,
    ]
    if query.expected_handle:
        command += ["--expected-handle", query.expected_handle]
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise IngestError(f"Grok helper failed for query {query.name}")
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise IngestError(f"Grok helper returned invalid JSON for {query.name}") from exc
    posts = payload.get("posts") if isinstance(payload, dict) else None
    if not isinstance(posts, list):
        raise IngestError(f"Grok helper omitted posts for {query.name}")
    return posts


def raw_document(query: Query, post: dict) -> str:
    required = ("id", "text", "created_at", "author_handle")
    if any(not str(post.get(field, "")).strip() for field in required):
        raise IngestError(f"query {query.name} returned an incomplete post")
    author = str(post["author_handle"]).lstrip("@")
    post_id = str(post["id"])
    source_url = f"https://x.com/{author}/status/{post_id}"
    fields = {
        "author": f"@{author}",
        "created_at": str(post["created_at"]),
        "query_name": query.name,
        "query": query.query,
        "source_url": source_url,
    }
    frontmatter = "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in fields.items()
    )
    return f"---\n{frontmatter}\n---\n\n{str(post['text']).strip()}\n"


def write_posts(staging_root: Path, query: Query, posts: list[dict]) -> int:
    written = 0
    bucket = staging_root / "raw" / "x" / query.name
    for post in posts:
        created_at = str(post.get("created_at", ""))
        post_id = str(post.get("id", ""))
        day = created_at[:10]
        if len(day) != 10 or not post_id.isdigit():
            raise IngestError(f"query {query.name} returned an invalid id or date")
        path = bucket / f"{day}__{post_id}.md"
        content = raw_document(query, post)
        if path.exists():
            if path.read_text(encoding="utf-8") != content:
                raise IngestError(f"same-path different-content result: {path}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written += 1
    return written


def run(staging_root: Path, config_path: Path, helper: str) -> dict[str, object]:
    queries = load_queries(config_path)
    summary: dict[str, object] = {"queries": {}, "seen": 0, "written": 0}
    for query in queries:
        posts = retrieve(helper, query)
        count = write_posts(staging_root, query, posts)
        summary["seen"] = int(summary["seen"]) + len(posts)
        summary["written"] = int(summary["written"]) + count
        summary["queries"][query.name] = {"seen": len(posts), "written": count}
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--grok-helper", required=True)
    args = parser.parse_args()
    try:
        summary = run(args.staging_root, args.config, args.grok_helper)
    except (IngestError, ValueError) as exc:
        parser.exit(2, f"ingest failed: {exc}\n")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
