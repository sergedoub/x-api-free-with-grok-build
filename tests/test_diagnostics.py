import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.fixtures import envelope, post
from x_grok_reader.diagnostics import Trace, run_process
from x_grok_reader.response import GrokSearchError


ROOT = Path(__file__).resolve().parents[1]


class DiagnosticsTests(unittest.TestCase):
    def test_private_unique_trace_and_exclusive_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Trace(Path(tmp)), Trace(Path(tmp))
            self.assertNotEqual(first.path, second.path)
            first.write("data.json", {"value": "test"})
            self.assertEqual(first.path.stat().st_mode & 0o777, 0o700)
            self.assertEqual((first.path / "data.json").stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                first.write("data.json", {})

    def test_process_success_and_nonzero_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            for code in (0, 7):
                trace = Trace(Path(tmp))
                result = run_process(
                    [
                        sys.executable,
                        "-c",
                        f'import sys;print("out");print("err",file=sys.stderr);sys.exit({code})',
                    ],
                    cwd=Path(tmp),
                    timeout=5,
                    trace=trace,
                )
                self.assertEqual(result.returncode, code)
                self.assertEqual((trace.path / "stdout.json").read_text(), "out\n")
                self.assertEqual((trace.path / "stderr.txt").read_text(), "err\n")

    def test_deadline_kills_descendant_and_preserves_partial_output(self):
        child = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)"
        parent = f'import subprocess,sys,time;p=subprocess.Popen([sys.executable,"-c",{child!r}]);print(p.pid,flush=True);print("partial",file=sys.stderr,flush=True);time.sleep(30)'
        with tempfile.TemporaryDirectory() as tmp:
            trace = Trace(Path(tmp))
            start = time.monotonic()
            with self.assertRaisesRegex(GrokSearchError, "exceeded"):
                run_process(
                    [sys.executable, "-c", parent],
                    cwd=Path(tmp),
                    timeout=0.5,
                    kill_grace=0.2,
                    trace=trace,
                )
            self.assertLess(time.monotonic() - start, 5)
            pid = int((trace.path / "stdout.json").read_text().strip())
            status = subprocess.run(
                ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True
            ).stdout.strip()
            self.assertTrue(not status or status.startswith("Z"), status)
            self.assertIn("partial", (trace.path / "stderr.txt").read_text())
            self.assertTrue(
                json.loads((trace.path / "transport.json").read_text())["timed_out"]
            )

    def test_cli_real_fake_grok_with_trace_and_compatible_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "grok"
            row = post()
            fake.write_text(
                f"#!{sys.executable}\nprint({json.dumps(envelope(row))!r})\n"
            )
            fake.chmod(0o700)
            command = [
                sys.executable,
                "-m",
                "x_grok_reader.grok_search",
                "--operation",
                "thread",
                "--query",
                row["id"],
                "--limit",
                "1",
                "--grok-bin",
                str(fake),
                "--cwd",
                tmp,
                "--trace-dir",
                str(root / "traces"),
            ]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["posts"][0]["id"], row["id"])
            self.assertEqual(payload["retrieval"]["status"], "results_returned")
            trace = Path(payload["retrieval"]["trace_directory"])
            self.assertTrue((trace / "request.json").exists())
            self.assertTrue((trace / "result.json").exists())
            self.assertEqual(
                json.loads((trace / "stdout.json").read_text()), envelope(row)
            )

    def test_cli_timeout_returns_error_with_durable_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "grok"
            fake.write_text(
                f'#!{sys.executable}\nimport time\nprint("partial",flush=True)\ntime.sleep(30)\n'
            )
            fake.chmod(0o700)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "x_grok_reader.grok_search",
                    "--query",
                    "example",
                    "--grok-bin",
                    str(fake),
                    "--cwd",
                    tmp,
                    "--timeout-seconds",
                    "1",
                    "--trace-dir",
                    str(root / "traces"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("exceeded", result.stderr)
            trace = next((root / "traces").iterdir())
            self.assertTrue((trace / "error.json").exists())
            self.assertIn("partial", (trace / "stdout.json").read_text())
