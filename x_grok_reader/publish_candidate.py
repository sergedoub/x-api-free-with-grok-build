#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .candidate import (
    CandidateError,
    apply_candidate,
    diff_changes,
    validate_candidate,
)


def _append_output(path: str | None, name: str, value: str) -> None:
    if path:
        with Path(path).open("a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", default="HEAD")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = parser.parse_args()
    try:
        changes = diff_changes(args.candidate_root, args.base_ref, args.head_ref)
        paths = validate_candidate(args.candidate_root, changes)
        results = apply_candidate(args.main_root, args.candidate_root, paths)
    except CandidateError as exc:
        parser.exit(2, f"candidate rejected: {exc}\n")
    added = [item for item in results if item.outcome == "added"]
    summary = {
        "accepted": True,
        "added": len(added),
        "deduplicated": len(results) - len(added),
        "files": [item.__dict__ for item in results],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    _append_output(args.github_output, "changed", "true" if added else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
