#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


INSTALL_ROOT = Path("/usr/local/lib/x-grok-reader")
RUNTIME_ROOT = Path("/run/x-grok-reader")
STATE_PATH = Path("/var/lib/xreader-worker/health.json")


def _run_json(command: list[str]) -> dict:
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise RuntimeError(f"worker subprocess failed with exit code {result.returncode}")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("worker subprocess returned a non-object")
    return payload


def _health(status: str, *, raw_count: int = 0, published: bool = False) -> dict:
    return {
        "version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status,
        "raw_count": raw_count,
        "published": published,
    }


def _write_health(payload: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(STATE_PATH)


def _open_submission_handoff(run_root: Path, stage: Path) -> None:
    if stage.parent != run_root or not stage.is_dir() or stage.is_symlink():
        raise RuntimeError("invalid staging directory")
    items = [stage, *stage.rglob("*")]
    if any(item.is_symlink() for item in items):
        raise RuntimeError("staging may not contain symlinks")
    run_root.chmod(0o770)
    for item in items:
        item.chmod(0o770 if item.is_dir() else 0o640)


def main() -> int:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix="run-", dir=RUNTIME_ROOT))
    stage = run_root / "stage"
    try:
        ingest = _run_json(
            [
                "/usr/local/libexec/xreader-ingest",
                "--staging-root",
                str(stage),
                "--config",
                "/etc/x-grok-reader/queries.toml",
            ]
        )
        raw_count = int(ingest.get("written", 0))
        if raw_count == 0:
            health = _health("no-results")
        else:
            _open_submission_handoff(run_root, stage)
            submission = _run_json(["/usr/local/libexec/xreader-submit-as-user", str(stage)])
            status = str(submission.get("status", "published"))
            health = _health(
                status,
                raw_count=raw_count,
                published=status in {"published", "already-accepted"},
            )
        _write_health(health)
        print(json.dumps(health, sort_keys=True))
        return 0
    except Exception as exc:
        health = _health("failed")
        _write_health(health)
        print(f"worker error: {exc}", file=sys.stderr)
        print(json.dumps(health, sort_keys=True), file=sys.stderr)
        return 1
    finally:
        if run_root.exists():
            shutil.rmtree(run_root)


if __name__ == "__main__":
    raise SystemExit(main())
