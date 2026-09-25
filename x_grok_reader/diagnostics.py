"""Private opt-in traces and bounded process-group execution (POSIX/Linux)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
from pathlib import Path

from .response import GrokSearchError


class Trace:
    def __init__(self, root: Path | None):
        self.path: Path | None = None
        if root is not None:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.path = Path(tempfile.mkdtemp(prefix="retrieval-", dir=root)).resolve()

    def write(self, name: str, value: object) -> None:
        if self.path is None:
            return
        data = (
            value
            if isinstance(value, bytes)
            else (
                value.encode()
                if isinstance(value, str)
                else (
                    json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n"
                ).encode()
            )
        )
        fd = os.open(self.path / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)


def _signal_group(process: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass


def run_process(
    command: list[str],
    *,
    cwd: Path,
    timeout: float,
    trace: Trace,
    kill_grace: float = 5,
) -> subprocess.CompletedProcess:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _signal_group(process, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=kill_grace)
        except subprocess.TimeoutExpired:
            _signal_group(process, signal.SIGKILL)
            stdout, stderr = process.communicate()
        finally:
            # A descendant may have closed its pipes but ignored TERM.
            _signal_group(process, signal.SIGKILL)
        trace.write("stdout.json", stdout)
        trace.write("stderr.txt", stderr)
        trace.write(
            "transport.json", {"returncode": process.returncode, "timed_out": True}
        )
        raise GrokSearchError(f"Grok search exceeded {timeout} seconds") from exc
    except BaseException:
        _signal_group(process, signal.SIGKILL)
        process.communicate()
        raise
    trace.write("stdout.json", stdout)
    trace.write("stderr.txt", stderr)
    trace.write(
        "transport.json", {"returncode": process.returncode, "timed_out": False}
    )
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
