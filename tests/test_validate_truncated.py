"""Proves validate.py reports FAIL, instead of crashing, when generated files are cut short.
Run from the repo root with: python -m unittest"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def run(*args):
    """Run a repo script with the current interpreter and capture its output.
    Called by the test below to drive generate.py and validate.py."""
    return subprocess.run([sys.executable, *args], cwd=REPO, capture_output=True, text=True)


def truncate(path):
    """Cut a file to half its length, as a failed copy or upload would.
    Called by the test below on one gzip and one Parquet file."""
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])


class ValidateTruncatedFileTest(unittest.TestCase):
    def test_truncated_files_give_fail_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"

            # Generate a small dataset
            gen = run("generate.py", "--scale", "0.01", "--out", str(out))
            self.assertEqual(gen.returncode, 0)

            # Cut one gzip file and one Parquet file short
            stage = out / "landing_staging"
            truncate(next(stage.rglob("web/events/*.jsonl.gz")))
            truncate(next(stage.rglob("oms/orders/*.parquet")))

            # Validate: expect a FAIL line, no traceback, and a non-zero exit
            result = run("validate.py", str(out))
            self.assertNotIn("Traceback", result.stderr)
            self.assertIn("FAIL  every file opens cleanly", result.stdout)
            self.assertNotEqual(result.returncode, 0)


class ValidateUnfinishedRunTest(unittest.TestCase):
    def test_output_without_run_json_is_refused(self):
        """validate.py refuses output from a run that did not finish (no run.json), without reading anything else."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "answer_key").mkdir()
            result = run("validate.py", tmp)
            self.assertEqual(result.returncode, 2)
            self.assertIn("run did not finish", result.stdout)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
