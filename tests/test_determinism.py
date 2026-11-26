"""Proves the same seed and scale give byte-identical landing files, the refactor-safety check.
Only landing_staging is compared; the answer key is never opened. Run with: python -m unittest"""
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def generate(out):
    """Run generate.py at scale 0.01 with the default seed into the given folder.
    Called twice by the test below; skips the truth tables since only landing files are compared."""
    result = subprocess.run(
        [sys.executable, "generate.py", "--scale", "0.01", "--out", str(out), "--no-truth"],
        cwd=REPO, capture_output=True, text=True)
    return result.returncode


def fingerprint(stage):
    """Map each file under the landing folder to the SHA-256 of its bytes.
    Called by the test below on each run's output."""
    return {p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(stage.rglob("*")) if p.is_file()}


class DeterminismTest(unittest.TestCase):
    def test_same_seed_and_scale_give_identical_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / "first", Path(tmp) / "second"

            # Generate twice with the same seed and scale
            self.assertEqual(generate(first), 0)
            self.assertEqual(generate(second), 0)

            # Compare the file lists and the bytes of every file
            a, b = fingerprint(first / "landing_staging"), fingerprint(second / "landing_staging")
            self.assertGreater(len(a), 0)

            # The increments run to 2026-12-31 and no later
            days = sorted(p.name for p in (first / "landing_staging" / "increments").iterdir())
            self.assertEqual((len(days), days[-1]), (92, "day=2026-12-31"))
            self.assertEqual(sorted(a), sorted(b))
            self.assertEqual([k for k in a if a[k] != b[k]], [])


if __name__ == "__main__":
    unittest.main()
