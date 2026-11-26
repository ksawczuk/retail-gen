"""The command line: picks the command, runs it and returns the exit code (0 done, 1 some files failed, 2 bad input).

Called by `python -m pusher`; this is where the concrete classes are chosen.
"""

from pusher.commands import RunContext, parse_command
from pusher.errors import InputError
from pusher.send_log import SendLog
from pusher.volume_client import FilesApiClient


def main(argv, env, out, client_factory=FilesApiClient):
    """Run one command from the command-line words and environment, writing the log to `out`."""
    log = SendLog(out)
    # Parse and run the command; any bad input stops with exit 2
    try:
        command = parse_command(argv)
        return command.run(RunContext(env=env, log=log, client_factory=client_factory))
    except InputError as exc:
        log.error(str(exc))
        return 2
