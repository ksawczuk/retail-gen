"""Unit tests for pusher.mode: parsing the command line."""

import unittest
from datetime import date

from pusher.errors import InputError
from pusher.mode import Mode


class ModeTest(unittest.TestCase):
    """Covers the two modes and the refusal of bad input."""

    def test_history(self):
        """History needs no date and reads the history folder."""
        mode = Mode.parse(["history"])
        self.assertEqual(mode.relative_dir(), "history")
        self.assertEqual(mode.delivery_label(), "history")

    def test_day(self):
        """A day reads that day's increment folder."""
        mode = Mode.parse(["day", "2026-10-01"])
        self.assertEqual(mode.day, date(2026, 10, 1))
        self.assertEqual(mode.relative_dir(), "increments/day=2026-10-01")
        self.assertEqual(mode.delivery_label(), "increment day=2026-10-01")

    def test_bad_input_is_refused(self):
        """Unknown modes, a missing or malformed date, a fake date and extra words are refused."""
        for args in (
            [], ["now"], ["day"], ["day", "yesterday"], ["day", "2026-13-01"], ["day", "20261001"],
            ["day", "2026-10-01", "extra"], ["history", "2026-10-01"], ["day", "2026-10-01/../x"],
        ):
            with self.assertRaises(InputError, msg=str(args)):
                Mode.parse(args)


if __name__ == "__main__":
    unittest.main()
