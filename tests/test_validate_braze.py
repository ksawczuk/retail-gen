"""validate.py's Braze checks on a small Braze layout written through the Output seam. A JSON stand-in replaces the
Avro writer and reader, so the checks run without fastavro. Run from the repo root with: python -m unittest"""
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import validate
from retailgen.manifest import Manifest
from retailgen.writers import Output

CUT_DAY = pd.Timestamp("2026-10-20")
CUT_NAME = f"email_opens_{CUT_DAY:%Y%m%d}.avro"


class JsonWriter:
    """Writes the records as JSON bytes, so a cut-off file fails to parse as a cut-off Avro file would."""

    def to_bytes(self, schema, records):
        return json.dumps(records).encode("utf-8")


def read_json(path):
    """Read one file written by JsonWriter."""
    return json.loads(Path(path).read_bytes())


def records(*ids):
    """Minimal Braze records with the given event ids."""
    return [{"id": i, "time": 0} for i in ids]


class BrazeChecksTest(unittest.TestCase):

    def setUp(self):
        validate.results.clear()
        validate.unreadable.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.stage = Path(self._tmp.name)
        self.out = Output(self.stage, Manifest(), avro_writer=JsonWriter())
        schema = {"name": "braze_opens", "fields": []}
        self.out.avro(records("h1", "h2"), schema, None, "braze", "opens", "email_opens_2026-09.avro")
        self.out.avro(records("a", "b", "c", "d"), schema, CUT_DAY, "braze", "opens", CUT_NAME, keep_share=0.5)
        # One event delivered twice: once on the day after, once two days after
        self.out.avro(records("e", "dup"), schema, CUT_DAY + pd.Timedelta(days=1), "braze", "opens",
                      f"email_opens_{CUT_DAY + pd.Timedelta(days=1):%Y%m%d}.avro")
        self.out.avro(records("dup"), schema, CUT_DAY + pd.Timedelta(days=2), "braze", "opens",
                      f"email_opens_{CUT_DAY + pd.Timedelta(days=2):%Y%m%d}.avro")

    def tearDown(self):
        self._tmp.cleanup()

    def resend(self):
        """Re-send the cut-off file whole the next day."""
        self.out.avro(records("a", "b", "c", "d"), {"name": "braze_opens", "fields": []},
                      CUT_DAY + pd.Timedelta(days=1), "braze", "opens", CUT_NAME.replace(".avro", "_resend.avro"))

    def run_checks(self):
        validate.braze_checks(self.stage, lambda k: 1 if k == "braze.duplicate_events" else 0, {CUT_NAME},
                              read_records=read_json)

    def test_correct_output_passes_and_the_cut_off_file_is_not_unreadable(self):
        self.resend()
        self.run_checks()
        self.assertEqual(validate.results, [True, True, True])
        self.assertEqual(validate.unreadable, [])

    def test_a_missing_resend_fails(self):
        self.run_checks()
        self.assertFalse(validate.results[0])

    def test_another_file_that_does_not_read_is_unreadable(self):
        self.resend()
        broken = next(self.stage.rglob("email_opens_2026-09.avro"))
        broken.write_bytes(broken.read_bytes()[:5])
        self.run_checks()
        self.assertEqual(validate.unreadable, ["email_opens_2026-09.avro"])

    def test_the_original_is_found_in_the_previous_day_folder(self):
        resend = self.stage / "increments/day=2026-10-21/braze/opens/email_opens_20261020_resend.avro"
        self.assertEqual(validate.day_before(resend),
                         self.stage / "increments/day=2026-10-20/braze/opens/email_opens_20261020.avro")


if __name__ == "__main__":
    unittest.main()
