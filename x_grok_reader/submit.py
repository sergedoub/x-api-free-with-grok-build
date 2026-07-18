#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from .candidate import CandidateError, Change, hash_bytes, validate_candidate


SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _run(args: list[str], *, cwd: Path | None = None) -> bytes:
    result = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise CandidateError(f"command failed: {' '.join(args)} {detail}")
    return result.stdout


def staged_paths(staging_root: Path) -> list[str]:
    if not staging_root.is_dir() or staging_root.is_symlink():
        raise CandidateError(f"staging root is not a directory: {staging_root}")
    paths: list[str] = []
    for item in sorted(staging_root.rglob("*")):
        if item.is_symlink():
            raise CandidateError(f"symlinks are forbidden in staging: {item}")
        if item.is_file():
            paths.append(item.relative_to(staging_root).as_posix())
    validate_candidate(staging_root, [Change("A", path) for path in paths])
    return paths


def _main_matches(repo_url: str, expected: dict[str, str], root: Path) -> bool:
    repo = root / "verify-main"
    if repo.exists():
        shutil.rmtree(repo)
    _run(
        [
            "git",
            "clone",
            "--filter=blob:none",
            "--no-checkout",
            "--depth=1",
            "--branch=main",
            repo_url,
            str(repo),
        ]
    )
    try:
        for relative, digest in expected.items():
            result = subprocess.run(
                ["git", "show", f"HEAD:{relative}"],
                cwd=repo,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode or hash_bytes(result.stdout) != digest:
                return False
        return True
    finally:
        shutil.rmtree(repo)


def _remote_branch_exists(repo_url: str, branch: str) -> bool:
    output = _run(
        ["git", "ls-remote", "--heads", repo_url, f"refs/heads/{branch}"]
    )
    return bool(output.strip())


def submit(
    *,
    staging_root: Path,
    repo_url: str,
    location: str,
    run_id: str,
    timeout_seconds: int,
    poll_seconds: int,
) -> dict[str, object]:
    if not SLUG.fullmatch(location) or not SLUG.fullmatch(run_id):
        raise CandidateError("location and run-id must be lower-case slugs")
    paths = staged_paths(staging_root)
    branch = f"ingest/{location}/{run_id}"
    with tempfile.TemporaryDirectory(prefix="xreader-submit-") as temporary:
        temporary_root = Path(temporary)
        repo = temporary_root / "repo"
        _run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                "--depth=1",
                "--branch=main",
                repo_url,
                str(repo),
            ]
        )
        _run(["git", "sparse-checkout", "init", "--cone"], cwd=repo)
        _run(["git", "sparse-checkout", "set", "raw"], cwd=repo)
        _run(["git", "checkout", "main"], cwd=repo)
        expected: dict[str, str] = {}
        proposed: list[str] = []
        for relative in paths:
            data = (staging_root / relative).read_bytes()
            result = subprocess.run(
                ["git", "show", f"HEAD:{relative}"],
                cwd=repo,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            if not result.returncode:
                if result.stdout != data:
                    raise CandidateError(
                        f"same-path different-content collision on main: {relative}"
                    )
                continue
            target = repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            proposed.append(relative)
            expected[relative] = hash_bytes(data)
        if not proposed:
            shutil.rmtree(staging_root)
            return {"status": "already-accepted", "branch": None, "files": {}}
        _run(["git", "switch", "-c", branch], cwd=repo)
        _run(["git", "config", "user.name", "xreader-ingest[bot]"], cwd=repo)
        _run(
            [
                "git",
                "config",
                "user.email",
                "xreader-ingest@users.noreply.github.com",
            ],
            cwd=repo,
        )
        _run(["git", "add", "--", *proposed], cwd=repo)
        _run(["git", "commit", "-m", f"ingest: submit {location} {run_id}"], cwd=repo)
        _run(["git", "push", "origin", f"HEAD:refs/heads/{branch}"], cwd=repo)
        shutil.rmtree(repo)
        shutil.rmtree(staging_root)
        deadline = time.monotonic() + timeout_seconds
        while True:
            if not _remote_branch_exists(repo_url, branch):
                if _main_matches(repo_url, expected, temporary_root):
                    return {"status": "published", "branch": branch, "files": expected}
            if time.monotonic() >= deadline:
                raise CandidateError(
                    f"candidate {branch} is durable on GitHub but not published to main"
                )
            time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--repo-url", required=True)
    parser.add_argument("--location", default="hetzner")
    parser.add_argument(
        "--run-id",
        default=f"{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:8]}",
    )
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--poll-seconds", type=int, default=10)
    args = parser.parse_args()
    try:
        result = submit(
            staging_root=args.staging_root.resolve(),
            repo_url=args.repo_url,
            location=args.location,
            run_id=args.run_id,
            timeout_seconds=max(0, args.timeout_seconds),
            poll_seconds=max(1, args.poll_seconds),
        )
    except CandidateError as exc:
        parser.exit(2, f"submission failed: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
