"""Unit tests for pusher.planner: which files a run sends and what it refuses."""

import os
import tempfile
import unittest
from pathlib import Path

from pusher.errors import InputError
from pusher.mode import Mode
from pusher.planner import FilePlanner
from pusher.tests.fakes import make_landing

FILES = {
    "history/crm/customers/customers_full_20260930.csv": b"a,b\n1,2\n",
    "history/oms/orders/orders_2025-01.parquet": b"PAR1",
    "increments/day=2026-10-01/crm/customers_cdc/customers_cdc_20261001.csv": b"x\n",
    "increments/day=2026-10-01/pos/transactions/pos_AAA-001_20261001.csv": b"y\n",
    "increments/day=2026-10-02/pos/transactions/pos_AAA-001_20261002.csv": b"z\n",
}


class PlannerTest(unittest.TestCase):
    """Covers the history and day listings and the refusals."""

    def setUp(self):
        """Build a fake landing_staging in a temporary folder."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_landing(Path(self._tmp.name) / "landing_staging", FILES)

    def test_history_lists_only_history_files(self):
        """History returns the history files, named source/entity/file."""
        items = FilePlanner(self.root).plan(Mode.parse(["history"]))
        self.assertEqual(
            [item.relative_name for item in items],
            ["crm/customers/customers_full_20260930.csv", "oms/orders/orders_2025-01.parquet"],
        )
        self.assertEqual(items[0].size, len(FILES["history/crm/customers/customers_full_20260930.csv"]))

    def test_day_lists_only_that_day(self):
        """A day returns only that day's files."""
        items = FilePlanner(self.root).plan(Mode.parse(["day", "2026-10-01"]))
        self.assertEqual(
            [item.relative_name for item in items],
            ["crm/customers_cdc/customers_cdc_20261001.csv", "pos/transactions/pos_AAA-001_20261001.csv"],
        )

    def test_missing_day_and_empty_folder_are_errors(self):
        """A day with no folder, or a folder with no usable files, is refused."""
        with self.assertRaises(InputError):
            FilePlanner(self.root).plan(Mode.parse(["day", "2026-11-01"]))
        (self.root / "increments" / "day=2026-10-05").mkdir()
        with self.assertRaises(InputError):
            FilePlanner(self.root).plan(Mode.parse(["day", "2026-10-05"]))

    def test_files_outside_the_layout_are_ignored(self):
        """A file too shallow or too deep, or with an unsafe name, is not sent."""
        make_landing(self.root, {
            "history/readme.txt": b"x",
            "history/crm/customers/deep/extra.csv": b"x",
            "history/crm/customers/bad name.csv": b"x",
        })
        names = [item.relative_name for item in FilePlanner(self.root).plan(Mode.parse(["history"]))]
        self.assertEqual(len(names), 2)

    def test_forbidden_names_are_refused(self):
        """An answer_key folder under a delivery, or a root inside answer_key or out, is refused."""
        make_landing(self.root, {"history/answer_key/defects/defects.md": b"x"})
        with self.assertRaises(InputError):
            FilePlanner(self.root).plan(Mode.parse(["history"]))
        with self.assertRaises(InputError):
            FilePlanner(Path(self._tmp.name) / "answer_key" / "landing_staging")
        with self.assertRaises(InputError):
            FilePlanner(Path(self._tmp.name) / "out" / "landing_staging")

    @unittest.skipUnless(hasattr(os, "symlink"), "no symlinks")
    def test_a_link_leaving_the_root_is_refused(self):
        """A symlink that points outside the landing folder is refused."""
        outside = Path(self._tmp.name) / "secret.csv"
        outside.write_bytes(b"s")
        link = self.root / "history" / "crm" / "customers" / "link.csv"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("cannot create symlinks here")
        with self.assertRaises(InputError):
            FilePlanner(self.root).plan(Mode.parse(["history"]))


if __name__ == "__main__":
    unittest.main()
