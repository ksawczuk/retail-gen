"""The command line: wires the parts together and returns the exit code (0 sent, 1 some failed, 2 bad input).

Called by `python -m pusher`; this is where the concrete classes are chosen.
"""

from pusher.config import PushConfig
from pusher.errors import InputError
from pusher.mode import Mode
from pusher.planner import FilePlanner
from pusher.pusher import Pusher
from pusher.send_log import SendLog
from pusher.volume_client import FilesApiClient


def main(argv, env, out, client_factory=FilesApiClient):
    """Run one push from the command-line words and environment, writing the log to `out`."""
    log = SendLog(out)
    # Read the mode, the settings and the file list; any bad input stops here with exit 2
    try:
        mode = Mode.parse(list(argv))
        config = PushConfig.from_env(env)
        items = FilePlanner(config.landing_root).plan(mode)
    except InputError as exc:
        log.error(str(exc))
        return 2
    # A dry run has no client, so it makes no network call
    client = None if config.dry_run else client_factory(config.host, config.token)
    # Send the files and report
    result = Pusher(client, log, dry_run=config.dry_run).run(items, mode.delivery_label())
    log.summary(result)
    return result.exit_code
