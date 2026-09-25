"""Exercise the real wrapper logic in temporary paths, never system paths."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import envelope, post

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(
    sys.platform.startswith("linux") and shutil.which("flock"),
    "Linux runtime wrapper; exercised in Ubuntu CI",
)
class RuntimeWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("runtime", "state", "grok-home"):
            (self.root / name).mkdir()
        (self.root / "state/auth.json").write_text('{"refresh":0}')
        for name in ("config.toml", "requirements.toml"):
            (self.root / "grok-home" / name).write_text("")
        self.fake = self.root / "grok"
        self.fake.write_text(f"""#!{sys.executable}
import json,os,time
from pathlib import Path
p=Path(os.environ['GROK_HOME'])/'auth.json'
state=json.loads(p.read_text())
time.sleep(.2)
p.write_text(json.dumps({{'refresh':state['refresh']+1}}))
print({json.dumps(envelope(post()))!r})
""")
        self.fake.chmod(0o700)
        self.wrapper = self.root / "wrapper"
        source = (ROOT / "scripts/libexec/xreader-grok-search").read_text()
        for old, new in [
            ("/run/x-grok-reader", str(self.root / "runtime")),
            ("/var/lib/xreader-grok", str(self.root / "state")),
            ("/usr/local/lib/x-grok-reader/grok-home", str(self.root / "grok-home")),
            ("/usr/local/lib/x-grok-reader", str(ROOT)),
            ("/usr/local/bin/grok", str(self.fake)),
            ("/usr/bin/python3", sys.executable),
            ("/usr/bin/flock", shutil.which("flock")),
        ]:
            source = source.replace(old, new)
        self.wrapper.write_text(source)
        self.wrapper.chmod(0o700)

    def command(self, *args):
        return [str(self.wrapper), "--query", "example", *args]

    def test_concurrent_refreshes_serialize_and_cleanup(self):
        processes = [
            subprocess.Popen(
                self.command(), stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            for _ in range(2)
        ]
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, stderr.decode())
            self.assertEqual(len(json.loads(stdout)["posts"]), 1)
        self.assertEqual(
            json.loads((self.root / "state/auth.json").read_text())["refresh"], 2
        )
        self.assertEqual(list((self.root / "runtime").iterdir()), [])
        self.assertEqual((self.root / "state/auth.json").stat().st_mode & 0o777, 0o600)

    def test_failed_grok_cleans_runtime_and_releases_lock(self):
        self.fake.write_text(f"#!{sys.executable}\nraise SystemExit(7)\n")
        result = subprocess.run(self.command(), capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(list((self.root / "runtime").iterdir()), [])
        probe = subprocess.run(
            [shutil.which("flock"), "-n", str(self.root / "state/auth.lock"), "true"]
        )
        self.assertEqual(probe.returncode, 0)

    def test_deadline_removes_runtime_and_preserves_diagnostic_output(self):
        self.fake.write_text(
            f'#!{sys.executable}\nimport time\nprint("partial",flush=True)\ntime.sleep(30)\n'
        )
        result = subprocess.run(
            self.command(
                "--timeout-seconds", "1", "--trace-dir", str(self.root / "traces")
            ),
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 2, result.stderr.decode())
        self.assertEqual(list((self.root / "runtime").iterdir()), [])
        trace = next((self.root / "traces").iterdir())
        self.assertIn("partial", (trace / "stdout.json").read_text())
        self.assertTrue((trace / "error.json").exists())

    def test_interrupt_forwards_to_child_before_cleanup(self):
        import time

        marker = self.root / "started"
        self.fake.write_text(
            f"#!{sys.executable}\nimport time\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\ntime.sleep(30)\n"
        )
        process = subprocess.Popen(
            self.command(), stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        try:
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(marker.exists())
            process.terminate()
            process.communicate(timeout=10)
            self.assertEqual(process.returncode, 143)
            self.assertEqual(list((self.root / "runtime").iterdir()), [])
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
