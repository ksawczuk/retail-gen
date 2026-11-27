"""The four commands a run can be: push the history or one day, push the next day, or unmark a day.

Built by `parse_command` from the command line; the entry point runs the one it gets with a RunContext.
"""

from dataclasses import dataclass
from pathlib import Path

from pusher.config import PushConfig, landing_root_from
from pusher.connectors import DirectConnector, TunnelConnector
from pusher.errors import InputError
from pusher.mode import DAY, USAGE, Mode
from pusher.planner import FilePlanner
from pusher.push_state import PushState
from pusher.pusher import Pusher

NEXT = "next"
UNMARK = "unmark"
STATE_FLAG = "--state"


@dataclass(frozen=True)
class RunContext:
    """What every command may use: the environment, the log and the factory that builds a volume client."""

    env: dict
    log: object
    client_factory: object


class PushDelivery:
    """Push the history or one named day; the state file is not touched."""

    def __init__(self, mode):
        """Keep the delivery to push."""
        self._mode = mode

    def run(self, ctx):
        """Read the settings, then push. Returns 0 sent, 1 some files failed; bad input raises InputError."""
        return self.push(ctx, PushConfig.from_env(ctx.env))

    def push(self, ctx, config):
        """Plan the delivery's files, send them and write the summary; also called by PushNext."""
        # List the files; a missing or empty delivery folder is bad input
        items = FilePlanner(config.landing_root).plan(self._mode)
        # Tunnel through the proxy when HTTPS_PROXY is set, otherwise connect directly
        connector = TunnelConnector(config.proxy) if config.proxy else DirectConnector()
        # A dry run has no client, so it makes no network call
        client = None if config.dry_run else ctx.client_factory(config.host, config.token, connector)
        # Send the files and report
        result = Pusher(client, ctx.log, dry_run=config.dry_run).run(items, self._mode.delivery_label())
        ctx.log.summary(result)
        return result.exit_code


class PushNext:
    """Push the earliest increment day not yet recorded, and record it only when every file went."""

    def __init__(self, state_path):
        """Keep the state file's path."""
        self._state_path = state_path

    def run(self, ctx):
        """Find the next day and push it. Returns 0 pushed and recorded (or nothing left), 1 some files failed."""
        # Check the settings and the state file's place before taking the lock
        config = PushConfig.from_env(ctx.env)
        planner = FilePlanner(config.landing_root)
        state = PushState(self._state_path, config.landing_root)
        with state.lock():
            # Find the next day; none left is a clean finish
            all_days = planner.increment_days()
            day = state.next_after(all_days)
            if day is None:
                ctx.log.note(f"ALL PUSHED last={all_days[-1].isoformat()}")
                return 0

            # Push it exactly as `day` would
            ctx.log.note(f"NEXT day={day.isoformat()}")
            code = PushDelivery(Mode(DAY, day)).push(ctx, config)

            # Record it only after a clean, real push
            if code != 0:
                ctx.log.note(f"NOT RECORDED day={day.isoformat()} reason=failed_files")
            elif config.dry_run:
                ctx.log.note(f"NOT RECORDED day={day.isoformat()} reason=dry_run")
            else:
                state.record(day, all_days)
                ctx.log.note(f"RECORDED day={day.isoformat()}")
            return code


class Unmark:
    """Take the newest pushed day out of the state so `next` pushes it again. Never pushes or builds a client."""

    def __init__(self, day, state_path):
        """Keep the day to unmark and the state file's path."""
        self._day = day
        self._state_path = state_path

    def run(self, ctx):
        """Remove the day from the state. Returns 0; a day that may not be unmarked raises InputError."""
        # Unmark needs only the landing folder (for the day list), never a host or token
        landing_root = landing_root_from(ctx.env)
        planner = FilePlanner(landing_root)
        state = PushState(self._state_path, landing_root)
        with state.lock():
            state.unmark(self._day, planner.increment_days())
        ctx.log.note(f"UNMARKED day={self._day.isoformat()}")
        return 0


def parse_command(args):
    """Build the command from the command-line words; raises InputError with the usage on anything else."""
    args = list(args)
    # next --state FILE
    if args[:1] == [NEXT]:
        if len(args) != 3 or args[1] != STATE_FLAG or not args[2]:
            raise InputError(USAGE)
        return PushNext(Path(args[2]))
    # unmark YYYY-MM-DD --state FILE; the date is checked as `day` checks it
    if args[:1] == [UNMARK]:
        if len(args) != 4 or args[2] != STATE_FLAG or not args[3]:
            raise InputError(USAGE)
        return Unmark(Mode.parse([DAY, args[1]]).day, Path(args[3]))
    # history, or day YYYY-MM-DD
    return PushDelivery(Mode.parse(args))
