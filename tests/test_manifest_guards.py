"""Tests for the three guards that keep the defect catalogue and the code that plants defects in step.
They use a two-entry fake catalogue, so they never touch the real one. Run with: python -m unittest"""
import tempfile
import unittest
from pathlib import Path

from retailgen.defects import Defect
from retailgen.manifest import Manifest

FAKE_REGISTRY = {
    "src.plain": Defect("src.plain", "src", "plain", "cat", "a defect with no placeholders"),
    "src.filled": Defect("src.filled", "src", "filled", "cat", "a defect with {n} placeholder"),
}


class ManifestGuardsTest(unittest.TestCase):
    def setUp(self):
        """Give each test a fresh manifest backed by the fake catalogue."""
        self.manifest = Manifest(registry=FAKE_REGISTRY)

    def test_undeclared_defect_id_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.manifest.record("src.not_declared", 1)

    def test_mismatched_detail_names_raise_value_error(self):
        with self.assertRaises(ValueError):
            self.manifest.record("src.filled", 1, wrong_name=3)

    def test_missing_detail_names_raise_value_error(self):
        with self.assertRaises(ValueError):
            self.manifest.record("src.filled", 1)

    def test_declared_defect_never_recorded_is_reported(self):
        self.manifest.record("src.plain", 2)
        self.assertEqual(self.manifest.unrecorded(), ["src.filled"])

    def test_everything_recorded_reports_nothing_unrecorded(self):
        self.manifest.record("src.plain", 2)
        self.manifest.record("src.filled", 1, n=3)
        self.assertEqual(self.manifest.unrecorded(), [])

    def test_repeated_records_add_up(self):
        self.manifest.record("src.plain", 2)
        self.manifest.record("src.plain", 3)
        self.assertEqual(self.manifest.count("src.plain"), 5)

    def test_incomplete_message_names_scale_seed_and_counts_but_no_ids(self):
        """The screen message for a run with unrecorded defects carries scale, seed and counts, never a defect id."""
        self.manifest.record("src.plain", 2)
        message = self.manifest.incomplete_message(0.01, 7)
        self.assertIn("scale 0.01, seed 7", message)
        self.assertIn("1 of 2 declared", message)
        self.assertNotIn("src.filled", message)
        self.assertNotIn("src.plain", message)

    def test_unrecorded_ids_go_to_the_answer_key_folder(self):
        """The ids are written one per line to unrecorded_defects.txt in the folder given."""
        self.manifest.record("src.plain", 2)
        with tempfile.TemporaryDirectory() as tmp:
            self.manifest.write_unrecorded(Path(tmp) / "answer_key")
            text = (Path(tmp) / "answer_key" / "unrecorded_defects.txt").read_text(encoding="utf-8")
        self.assertEqual(text.split(), ["src.filled"])


if __name__ == "__main__":
    unittest.main()
