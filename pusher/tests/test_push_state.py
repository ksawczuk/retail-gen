"""Unit tests for pusher.push_state: reading, checking, recording and unmarking pushed days, and the lock."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from pusher.errors import InputError
from pusher.push_state import PushState

DAYS = [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)]


class PushStateTest(unittest.TestCase):
    """Covers the state file's rules, with a temporary folder beside a fake landing root."""

    def setUp(self):
        """Make a state folder and a separate landing folder."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.landing = base / "landing_staging"
        self.landing.mkdir()
        (base / "state").mkdir()
        self.path = base / "state" / "pushed_days.txt"

    def _state(self, text=None):
        """Write the state file's text (None leaves it missing) and return a PushState on it."""
        if text is not None:
            self.path.write_text(text, encoding="utf-8")
        return PushState(self.path, self.landing)

    def test_missing_file_means_nothing_pushed(self):
        state = self._state()
        self.assertEqual(state.days(DAYS), [])
        self.assertEqual(state.next_after(DAYS), DAYS[0])

    def test_record_then_reload(self):
        state = self._state()
        state.record(DAYS[0], DAYS)
        state.record(DAYS[1], DAYS)
        self.assertEqual(PushState(self.path, self.landing).days(DAYS), DAYS[:2])
        self.assertEqual(self.path.read_text(encoding="utf-8"), "2026-10-01\n2026-10-02\n")

    def test_write_leaves_no_temporary_file(self):
        self._state().record(DAYS[0], DAYS)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["pushed_days.txt"])

    def test_next_after_partial_and_full(self):
        self.assertEqual(self._state("2026-10-01\n").next_after(DAYS), DAYS[1])
        self.assertIsNone(self._state("2026-10-01\n2026-10-02\n2026-10-03\n").next_after(DAYS))

    def test_record_refuses_a_day_out_of_order(self):
        with self.assertRaises(InputError):
            self._state().record(DAYS[1], DAYS)

    def test_inconsistent_files_are_refused(self):
        """A non-date, an unreal date, an unknown day, a gap or a wrong order is bad input."""
        for text in ("hello\n", "2026-02-30\n", "2026-09-30\n", "2026-10-01\n2026-10-03\n", "2026-10-02\n2026-10-01\n"):
            with self.subTest(text=text), self.assertRaises(InputError):
                self._state(text).days(DAYS)

    def test_unmark_newest_removes_it(self):
        state = self._state("2026-10-01\n2026-10-02\n")
        state.unmark(DAYS[1], DAYS)
        self.assertEqual(state.days(DAYS), DAYS[:1])
        self.assertEqual(state.next_after(DAYS), DAYS[1])

    def test_unmark_refusals_change_nothing(self):
        """An unrecorded day, a non-increment day or an older day is refused and the file is unchanged."""
        text = "2026-10-01\n2026-10-02\n"
        for day in (DAYS[2], date(2026, 9, 30), DAYS[0]):
            with self.subTest(day=day):
                state = self._state(text)
                with self.assertRaises(InputError):
                    state.unmark(day, DAYS)
                self.assertEqual(self.path.read_text(encoding="utf-8"), text)

    def test_state_inside_landing_or_forbidden_folder_is_refused(self):
        """The state may not sit inside the landing root, under answer_key or out, or in a missing folder."""
        base = Path(self._tmp.name)
        for path in (self.landing / "pushed_days.txt", base / "answer_key" / "s.txt", base / "out" / "s.txt",
                     base / "missing" / "s.txt"):
            with self.subTest(path=path), self.assertRaises(InputError):
                PushState(path, self.landing)

    def test_second_lock_is_refused_and_released_after(self):
        state = self._state()
        with state.lock():
            with self.assertRaises(InputError) as caught:
                with state.lock():
                    pass
            self.assertIn("pushed_days.txt.lock", str(caught.exception))
        with state.lock():
            pass
        self.assertFalse(self.path.with_name("pushed_days.txt.lock").exists())


if __name__ == "__main__":
    unittest.main()
