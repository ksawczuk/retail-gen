"""What one push run delivers: the history, or one increment day.

Parsed from the command line by the entry point, then read by the planner and the log.
"""

import re
from dataclasses import dataclass
from datetime import date

from pusher.errors import InputError

HISTORY = "history"
DAY = "day"
_DAY_TEXT = re.compile(r"^\d{4}-\d{2}-\d{2}$")
USAGE = "usage: history | day YYYY-MM-DD | next --state FILE | unmark YYYY-MM-DD --state FILE"


@dataclass(frozen=True)
class Mode:
    """One delivery: the history, or a single increment day."""

    kind: str
    day: date = None

    @classmethod
    def parse(cls, args):
        """Build a mode from the command-line words: `history` or `day YYYY-MM-DD`."""
        # History takes no further argument
        if args == [HISTORY]:
            return cls(HISTORY)
        # A day needs exactly one exact calendar date
        if len(args) == 2 and args[0] == DAY:
            if not _DAY_TEXT.match(args[1]):
                raise InputError(f"day must be YYYY-MM-DD, got {args[1]!r}")
            try:
                return cls(DAY, date.fromisoformat(args[1]))
            except ValueError:
                raise InputError(f"day is not a real date: {args[1]!r}") from None
        raise InputError(USAGE)

    def relative_dir(self):
        """The folder under landing_staging that holds this delivery's files."""
        if self.kind == HISTORY:
            return "history"
        return f"increments/day={self.day.isoformat()}"

    def delivery_label(self):
        """The delivery name written on each log line."""
        if self.kind == HISTORY:
            return "history"
        return f"increment day={self.day.isoformat()}"
