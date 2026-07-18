from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence


SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:+-]*$")
RAW_FILENAME = re.compile(
    r"^(?P<day>\d{4}-\d{2}-\d{2})__(?P<identifier>[0-9]+)\.md$"
)


class CandidateError(ValueError):
    pass


@dataclass(frozen=True)
class Change:
    status: str
    path: str


@dataclass(frozen=True)
class AppliedFile:
    path: str
    sha256: str
    outcome: str


def _git(repo: Path, args: Sequence[str]) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise CandidateError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def diff_changes(repo: Path, base_ref: str, head_ref: str = "HEAD") -> list[Change]:
    output = _git(
        repo,
        ["diff", "--name-status", "-z", "--find-renames", f"{base_ref}..{head_ref}"],
    )
    fields = output.decode("utf-8", errors="strict").split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    changes: list[Change] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        path_count = 2 if status.startswith(("R", "C")) else 1
        if index + path_count > len(fields):
            raise CandidateError("malformed git diff output")
        paths = fields[index : index + path_count]
        index += path_count
        path = f"{paths[0]} -> {paths[1]}" if path_count == 2 else paths[0]
        changes.append(Change(status, path))
    return changes


def _safe_repo_path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise CandidateError(f"unsafe path: {relative!r}")
    target = root.joinpath(*pure.parts)
    try:
        target.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise CandidateError(f"path escapes repository: {relative!r}") from exc
    return target


def validate_raw_path(relative: str) -> None:
    parts = PurePosixPath(relative).parts
    if len(parts) != 4 or parts[:2] != ("raw", "x"):
        raise CandidateError(f"path is outside raw/x/<query>/: {relative}")
    if not SAFE_COMPONENT.fullmatch(parts[2]):
        raise CandidateError(f"unsafe query bucket: {relative}")
    match = RAW_FILENAME.fullmatch(parts[3])
    if match is None:
        raise CandidateError(f"raw filename must be YYYY-MM-DD__<post-id>.md: {relative}")
    try:
        date.fromisoformat(match.group("day"))
    except ValueError as exc:
        raise CandidateError(f"raw filename has an invalid date: {relative}") from exc


def _validate_markdown(path: Path, relative: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise CandidateError(f"candidate must be a regular file: {relative}")
    data = path.read_bytes()
    if not data or len(data) > 1_000_000:
        raise CandidateError(f"candidate file is empty or too large: {relative}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CandidateError(f"candidate is not UTF-8: {relative}") from exc
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise CandidateError(f"candidate lacks YAML frontmatter: {relative}")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise CandidateError(f"candidate has unclosed frontmatter: {relative}") from exc
    if end == 1 or not any(line.strip() for line in lines[end + 1 :]):
        raise CandidateError(f"candidate lacks metadata or content: {relative}")
    return data


def validate_candidate(candidate_root: Path, changes: Iterable[Change]) -> list[str]:
    paths: list[str] = []
    for change in changes:
        if change.status != "A":
            raise CandidateError(
                f"candidate branches may only add files; found {change.status} {change.path}"
            )
        validate_raw_path(change.path)
        _validate_markdown(_safe_repo_path(candidate_root, change.path), change.path)
        paths.append(change.path)
    if not paths:
        raise CandidateError("candidate branch contains no raw additions")
    if len(paths) != len(set(paths)):
        raise CandidateError("candidate branch contains duplicate paths")
    return sorted(paths)


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def apply_candidate(
    main_root: Path,
    candidate_root: Path,
    paths: Iterable[str],
) -> list[AppliedFile]:
    results: list[AppliedFile] = []
    for relative in sorted(paths):
        candidate_data = _validate_markdown(
            _safe_repo_path(candidate_root, relative), relative
        )
        main_path = _safe_repo_path(main_root, relative)
        if main_path.exists():
            if main_path.is_symlink() or not main_path.is_file():
                raise CandidateError(f"existing path is not a regular file: {relative}")
            if main_path.read_bytes() != candidate_data:
                raise CandidateError(f"same-path different-content collision: {relative}")
            results.append(AppliedFile(relative, hash_bytes(candidate_data), "deduplicated"))
            continue
        main_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_safe_repo_path(candidate_root, relative), main_path)
        results.append(AppliedFile(relative, hash_bytes(candidate_data), "added"))
    return results
