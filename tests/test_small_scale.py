"""Slow regression: small-scale runs at chosen seeds finish. Skipped unless RETAILGEN_SLOW=1 is set, because each run
takes a minute or two. Run with: RETAILGEN_SLOW=1 python -m unittest tests.test_small_scale"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from tests.generator_args import source_args

REPO = Path(__file__).resolve().parent.parent
SLOW = os.environ.get("RETAILGEN_SLOW") == "1"


def generate(out, seed):
    """Run generate.py at scale 0.01 with the given seed into the given folder.
    Called by the test below once per seed; returns the finished process."""
    return subprocess.run(
        [sys.executable, "generate.py", "--scale", "0.01", "--seed", str(seed), "--out", str(out), "--no-truth",
         *source_args()],
        cwd=REPO, capture_output=True, text=True)


@unittest.skipUnless(SLOW, "set RETAILGEN_SLOW=1 to run the slow small-scale runs")
class SmallScaleRunsTest(unittest.TestCase):
    def test_small_scale_runs_finish_at_chosen_seeds(self):
        """Seeds 1, 5 and 7 used to stop the run at this scale (Bug 553), and seed 13 crashed in the store generator (Bug 677); they now finish and write run.json."""
        for seed in (1, 5, 7, 13):
            with self.subTest(seed=seed), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "out"
                result = generate(out, seed)
                self.assertEqual(result.returncode, 0, result.stderr[-300:])
                self.assertTrue((out / "answer_key" / "run.json").exists())


if __name__ == "__main__":
    unittest.main()
