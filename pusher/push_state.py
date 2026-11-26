"""The record of which increment days have been pushed, kept in one small text file whose path is given on the
command line. Read and written by the `next` and `unmark` commands; a lock file keeps two runs from overlapping.
"""

import os
import re
from datetime import date
from pathlib import Path

from pusher.errors import InputError
from pusher.planner import FORBIDDEN_NAMES

_DAY_LINE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PushState:
    """The pushed days, oldest first, as an unbroken run from the first increment day."""

    def __init__(self, path, landing_root):
        """Keep the state file's path, refusing one inside the landing root, under a forbidden name, or in a
        folder that does not exist."""
        self._path = Path(path)
        # The state must never be sent, so it may not sit inside the landing root or under a forbidden name
        if any(part.lower() in FORBIDDEN_NAMES for part in self._path.parts):
            raise InputError("the state file must not be inside a forbidden folder")
        landing_real = Path(landing_root).resolve()
        state_real = self._path.resolve()
        if state_real == landing_real or landing_real in state_real.parents:
            raise InputError("the state file must not be inside the landing folder")
        # A missing folder means a missing mount, not an empty state
        if not self._path.parent.is_dir():
            raise InputError(f"the state file's folder does not exist: {self._path.parent}")

    def days(self, all_days):
        """Return the recorded days, checked against the increment days; raises InputError if the file is
        inconsistent. A missing file means nothing has been pushed."""
        # Read the lines; a missing file is an empty state
        if not self._path.exists():
            return []
        lines = [line.strip() for line in self._path.read_text(encoding="utf-8").splitlines() if line.strip()]

        # Each line is one real date
        recorded = []
        for line in lines:
            if not _DAY_LINE.match(line):
                raise InputError(f"the state file has a line that is not a date: {line!r}")
            try:
                recorded.append(date.fromisoformat(line))
            except ValueError:
                raise InputError(f"the state file has a line that is not a real date: {line!r}") from None

        # The recorded days must be exactly the first increment days, in order, with no gap
        if recorded != list(all_days[:len(recorded)]):
            raise InputError("the state file is not an unbroken run of increment days from the first one")
        return recorded

    def next_after(self, all_days):
        """Return the earliest increment day not yet recorded, or None when every day is recorded."""
        recorded = self.days(all_days)
        if len(recorded) == len(all_days):
            return None
        return all_days[len(recorded)]

    def record(self, day, all_days):
        """Add a day after a successful push; it must be the next day in order."""
        recorded = self.days(all_days)
        if self.next_after(all_days) != day:
            raise InputError(f"{day.isoformat()} is not the next day to record")
        self._write(recorded + [day])

    def unmark(self, day, all_days):
        """Remove the newest recorded day so `next` pushes it again; any other day is refused, unchanged."""
        recorded = self.days(all_days)
        # Check the day is an increment day, is recorded, and is the newest one
        if day not in all_days:
            raise InputError(f"{day.isoformat()} is not an increment day")
        if day not in recorded:
            raise InputError(f"{day.isoformat()} is not recorded as pushed")
        if day != recorded[-1]:
            raise InputError(f"{day.isoformat()} is not the newest pushed day; unmark {recorded[-1].isoformat()} first")
        self._write(recorded[:-1])

    def lock(self):
        """Return the lock that keeps two runs from using this state at once."""
        return StateLock(self._path.with_name(self._path.name + ".lock"))

    def _write(self, days):
        """Replace the file in one step: write a temporary file beside it, then rename it over the old one."""
        temporary = self._path.with_name(self._path.name + ".tmp")
        temporary.write_text("".join(f"{day.isoformat()}\n" for day in days), encoding="utf-8")
        os.replace(temporary, self._path)


class StateLock:
    """An exclusive lock file beside the state; a second run that finds it stops with bad input."""

    def __init__(self, path):
        """Keep the lock file's path."""
        self._path = Path(path)
        self._fd = None

    def __enter__(self):
        """Create the lock file, failing if it already exists."""
        try:
            self._fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise InputError(
                f"another pusher run holds {self._path.name}; if no pusher is running, remove {self._path}"
            ) from None
        return self

    def __exit__(self, *exc):
        """Remove the lock file."""
        os.close(self._fd)
        self._path.unlink()
        return False
