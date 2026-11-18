"""Unit tests for pusher.pusher: skip, upload, failure handling and dry run."""

import io
import tempfile
import unittest
from pathlib import Path

from pusher.mode import Mode
from pusher.planner import FilePlanner
from pusher.pusher import VOLUME_LANDING_ROOT, Pusher
from pusher.send_log import SendLog
from pusher.tests.fakes import FakeVolumeClient, make_landing

FILES = {
    "history/crm/customers/a.csv": b"1234567",
    "history/crm/customers/b.csv": b"123",
    "history/oms/orders/c.parquet": b"PAR1",
}


class PusherTest(unittest.TestCase):
    """Covers new files, skips, overwrites, failures and the dry run."""

    def setUp(self):
        """Plan the history of a fake landing_staging."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = make_landing(Path(self._tmp.name) / "landing_staging", FILES)
        self.items = FilePlanner(root).plan(Mode.parse(["history"]))
        self.out = io.StringIO()

    def _run(self, client, dry_run=False):
        """Run the pusher over the planned items."""
        return Pusher(client, SendLog(self.out), dry_run=dry_run).run(self.items, "history")

    def test_new_files_are_uploaded_to_the_entity_folder(self):
        """Each file goes to landing/<source>/<entity>/<file>; folders are made once per entity."""
        client = FakeVolumeClient()
        result = self._run(client)
        self.assertEqual((result.sent, result.skipped, result.failed), (3, 0, 0))
        self.assertIn(f"{VOLUME_LANDING_ROOT}/crm/customers/a.csv", client.files)
        made = [call for call in client.calls if call[0] == "ensure_directory"]
        self.assertEqual(len(made), 2)

    def test_same_size_is_skipped_and_different_size_is_overwritten(self):
        """A remote file of equal size is skipped; one of another size is uploaded again."""
        client = FakeVolumeClient(existing={
            f"{VOLUME_LANDING_ROOT}/crm/customers/a.csv": 7,
            f"{VOLUME_LANDING_ROOT}/crm/customers/b.csv": 99,
        })
        result = self._run(client)
        self.assertEqual((result.sent, result.skipped, result.failed), (2, 1, 0))
        self.assertEqual(client.files[f"{VOLUME_LANDING_ROOT}/crm/customers/b.csv"], 3)

    def test_a_failed_file_does_not_stop_the_run(self):
        """A failure is logged, counted, gives exit code 1, and the other files are still sent."""
        client = FakeVolumeClient(fail_on=("b.csv",))
        result = self._run(client)
        self.assertEqual((result.sent, result.skipped, result.failed), (2, 0, 1))
        self.assertEqual(result.exit_code, 1)
        self.assertIn("status=failed", self.out.getvalue())

    def test_log_has_one_line_per_file(self):
        """Each file gets a PUSH line with size, status and delivery."""
        self._run(FakeVolumeClient())
        lines = self.out.getvalue().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertIn("PUSH crm/customers/a.csv size=7 status=204 delivery=history", lines[0])

    def test_dry_run_makes_no_client_call(self):
        """A dry run logs each file and never touches the client (it may be None)."""
        result = self._run(None, dry_run=True)
        self.assertEqual((result.sent, result.skipped, result.failed), (0, 0, 0))
        self.assertEqual(self.out.getvalue().count("status=dry-run"), 3)

    def test_clean_run_exits_zero(self):
        """No failures means exit code 0."""
        self.assertEqual(self._run(FakeVolumeClient()).exit_code, 0)


if __name__ == "__main__":
    unittest.main()
