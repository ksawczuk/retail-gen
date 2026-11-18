"""Sends a list of files to the volume: skip a file already there with the same size, otherwise upload it.

Called by the entry point with the planner's items; keeps going after a failed file and returns the counts.
"""

from dataclasses import dataclass

from pusher.volume_client import PushError

VOLUME_LANDING_ROOT = "/Volumes/workspace/retail/raw/landing"


@dataclass
class PushResult:
    """How many files were sent, skipped and failed."""

    sent: int = 0
    skipped: int = 0
    failed: int = 0

    @property
    def exit_code(self):
        """0 when nothing failed, 1 when some files failed."""
        return 1 if self.failed else 0


class Pusher:
    """Sends items through a volume client, logging each one."""

    def __init__(self, client, log, dry_run=False, remote_root=VOLUME_LANDING_ROOT):
        """Keep the client (None is fine for a dry run), the log, the dry-run flag and the volume folder."""
        self._client = client
        self._log = log
        self._dry_run = dry_run
        self._remote_root = remote_root

    def run(self, items, delivery):
        """Send every item in order and return the counts; a failed file does not stop the run."""
        result = PushResult()
        made_dirs = set()
        for item in items:
            self._push_one(item, delivery, result, made_dirs)
        return result

    def _push_one(self, item, delivery, result, made_dirs):
        """Handle one file: dry run, skip, upload or fail."""
        remote_dir = f"{self._remote_root}/{item.source}/{item.entity}"
        remote_path = f"{remote_dir}/{item.file_name}"
        # A dry run only lists the file
        if self._dry_run:
            self._log.file_line(item, "dry-run", delivery)
            return
        try:
            # Make the entity's folder once
            if remote_dir not in made_dirs:
                self._client.ensure_directory(remote_dir)
                made_dirs.add(remote_dir)
            # Skip a file already there with the same size
            if self._client.size_of(remote_path) == item.size:
                result.skipped += 1
                self._log.file_line(item, "skipped", delivery)
                return
            # Otherwise upload it
            status = self._client.upload(item.local_path, remote_path)
        except PushError as exc:
            result.failed += 1
            self._log.file_line(item, "failed", delivery, error=str(exc).replace(" ", "_"))
            return
        result.sent += 1
        self._log.file_line(item, str(status), delivery)
