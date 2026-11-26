"""Unit tests for the `next` and `unmark` commands through the CLI: what is pushed, what is recorded, exit codes."""

import io
import tempfile
import unittest
from pathlib import Path

from pusher.cli import main
from pusher.tests.fakes import FakeVolumeClient, make_landing

TOKEN = "fake-token-value"


class NextAndUnmarkTest(unittest.TestCase):
    """Runs the CLI against a fake landing_staging with three increment days and a fake volume."""

    def setUp(self):
        """Build the landing folder, a state folder beside it, and the environment."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.root = make_landing(base / "landing_staging", {
            "history/crm/customers/a.csv": b"1234",
            "increments/day=2026-10-01/crm/customers_cdc/d1.csv": b"1",
            "increments/day=2026-10-02/crm/customers_cdc/d2.csv": b"22",
            "increments/day=2026-10-03/pos/transactions/d3.csv": b"333",
        })
        (base / "state").mkdir()
        self.state = base / "state" / "pushed_days.txt"
        self.env = {
            "DATABRICKS_HOST": "https://example.cloud.databricks.com",
            "DATABRICKS_TOKEN": TOKEN,
            "PUSH_LANDING_ROOT": str(self.root),
        }
        self.volume = FakeVolumeClient()

    def _run(self, argv, env=None, factory=None):
        """Run the CLI once; return the exit code and the output."""
        out = io.StringIO()
        code = main(argv, env or self.env, out,
                    client_factory=factory or (lambda host, token, connector: self.volume))
        return code, out.getvalue()

    def _next(self, **kwargs):
        """Run `next` against the test state file."""
        return self._run(["next", "--state", str(self.state)], **kwargs)

    def _recorded(self):
        """Return the state file's lines, or [] when it is missing."""
        return self.state.read_text(encoding="utf-8").split() if self.state.exists() else []

    def test_next_with_no_state_pushes_the_first_day(self):
        code, out = self._next()
        self.assertEqual(code, 0)
        self.assertIn("NEXT day=2026-10-01", out)
        self.assertIn("delivery=increment day=2026-10-01", out)
        self.assertIn("RECORDED day=2026-10-01", out)
        self.assertEqual(self._recorded(), ["2026-10-01"])

    def test_next_pushes_days_in_order_then_finishes_cleanly(self):
        for _ in range(3):
            self.assertEqual(self._next()[0], 0)
        self.assertEqual(self._recorded(), ["2026-10-01", "2026-10-02", "2026-10-03"])
        uploads = len([c for c in self.volume.calls if c[0] == "upload"])
        code, out = self._next()
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "ALL PUSHED last=2026-10-03")
        self.assertEqual(len([c for c in self.volume.calls if c[0] == "upload"]), uploads)

    def test_a_failed_file_records_nothing_and_the_next_run_repeats_the_day(self):
        code, out = self._next(factory=lambda host, token, connector: FakeVolumeClient(fail_on=("d1.csv",)))
        self.assertEqual(code, 1)
        self.assertIn("NOT RECORDED day=2026-10-01 reason=failed_files", out)
        self.assertEqual(self._recorded(), [])
        code, out = self._next()
        self.assertEqual(code, 0)
        self.assertIn("RECORDED day=2026-10-01", out)

    def test_unmark_then_next_pushes_the_day_again(self):
        self._next()
        self._next()
        code, out = self._run(["unmark", "2026-10-02", "--state", str(self.state)])
        self.assertEqual((code, out.strip()), (0, "UNMARKED day=2026-10-02"))
        self.assertEqual(self._recorded(), ["2026-10-01"])
        code, out = self._next()
        self.assertIn("NEXT day=2026-10-02", out)

    def test_unmark_never_builds_a_client_and_needs_no_credentials(self):
        self._next()
        calls_before = list(self.volume.calls)

        def refuse(host, token, connector):
            """Fail if a client is built."""
            raise AssertionError("unmark must not build a client")

        code, _ = self._run(["unmark", "2026-10-01", "--state", str(self.state)],
                            env={"PUSH_LANDING_ROOT": str(self.root)}, factory=refuse)
        self.assertEqual(code, 0)
        self.assertEqual(self.volume.calls, calls_before)

    def test_unmark_refusals_exit_two_and_change_nothing(self):
        """An unrecorded day, a non-increment day, an older day and a bad date are refused."""
        self._next()
        self._next()
        for day in ("2026-10-03", "2026-09-30", "2026-10-01", "2026-10-32"):
            with self.subTest(day=day):
                code, out = self._run(["unmark", day, "--state", str(self.state)])
                self.assertEqual(code, 2)
                self.assertTrue(out.startswith("ERROR"))
                self.assertEqual(self._recorded(), ["2026-10-01", "2026-10-02"])

    def test_bad_state_arguments_exit_two_and_push_nothing(self):
        """No --state, a state inside the landing root, under answer_key, or in a missing folder."""
        base = Path(self._tmp.name)
        for argv in (["next"], ["next", "--state"], ["next", str(self.state)],
                     ["next", "--state", str(self.root / "pushed_days.txt")],
                     ["next", "--state", str(base / "answer_key" / "s.txt")],
                     ["next", "--state", str(base / "missing" / "s.txt")],
                     ["unmark", "2026-10-01"]):
            with self.subTest(argv=argv):
                code, out = self._run(argv)
                self.assertEqual(code, 2)
                self.assertTrue(out.startswith("ERROR"))
        self.assertEqual(self.volume.calls, [])

    def test_a_forbidden_landing_root_is_refused_with_next(self):
        for name in ("answer_key", "out"):
            with self.subTest(name=name):
                root = make_landing(Path(self._tmp.name) / name / "landing_staging",
                                    {"increments/day=2026-10-01/crm/customers_cdc/d1.csv": b"1"})
                code, _ = self._next(env={**self.env, "PUSH_LANDING_ROOT": str(root)})
                self.assertEqual(code, 2)
        self.assertEqual(self.volume.calls, [])

    def test_a_dry_run_next_records_nothing(self):
        code, out = self._next(env={"PUSH_DRY_RUN": "1", "PUSH_LANDING_ROOT": str(self.root)})
        self.assertEqual(code, 0)
        self.assertIn("status=dry-run", out)
        self.assertIn("NOT RECORDED day=2026-10-01 reason=dry_run", out)
        self.assertEqual(self._recorded(), [])

    def test_a_held_lock_stops_a_second_run(self):
        lock = self.state.with_name("pushed_days.txt.lock")
        lock.write_text("", encoding="utf-8")
        code, out = self._next()
        self.assertEqual(code, 2)
        self.assertIn("another pusher run holds pushed_days.txt.lock", out)
        self.assertEqual(self.volume.calls, [])
        self.assertTrue(lock.exists())

    def test_the_lock_is_released_after_a_failed_push(self):
        self._next(factory=lambda host, token, connector: FakeVolumeClient(fail_on=("d1.csv",)))
        self.assertFalse(self.state.with_name("pushed_days.txt.lock").exists())

    def test_the_token_never_appears_in_the_output(self):
        outputs = [self._next()[1], self._run(["unmark", "2026-10-01", "--state", str(self.state)])[1],
                   self._run(["next", "--state"])[1]]
        for out in outputs:
            self.assertNotIn(TOKEN, out)


if __name__ == "__main__":
    unittest.main()
