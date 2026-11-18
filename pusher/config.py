"""Settings read from the environment: the Databricks host and token, the dry-run flag and the landing folder.

Built once by the entry point; the token lives here and in the volume client and nowhere else.
"""

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from pusher.errors import InputError

DEFAULT_LANDING_ROOT = "/data/landing_staging"


@dataclass(frozen=True)
class PushConfig:
    """The validated settings for one run; the token never appears in repr."""

    host: str = None
    token: str = field(default=None, repr=False)
    dry_run: bool = False
    landing_root: Path = Path(DEFAULT_LANDING_ROOT)

    @classmethod
    def from_env(cls, env):
        """Read and validate the settings from an environment mapping; raises InputError when they are unusable."""
        # A dry run makes no network call, so it needs no host or token
        dry_run = env.get("PUSH_DRY_RUN") == "1"
        host = env.get("DATABRICKS_HOST") or None
        token = env.get("DATABRICKS_TOKEN") or None
        if not dry_run:
            if host is None:
                raise InputError("DATABRICKS_HOST is not set")
            if token is None:
                raise InputError("DATABRICKS_TOKEN is not set")
        # Check whatever was given
        if host is not None:
            host = _clean_host(host)
        if token is not None and any(ch.isspace() for ch in token):
            raise InputError("DATABRICKS_TOKEN must not contain whitespace")
        landing_root = Path(env.get("PUSH_LANDING_ROOT") or DEFAULT_LANDING_ROOT)
        return cls(host=host, token=token, dry_run=dry_run, landing_root=landing_root)


def _clean_host(value):
    """Return the host name from an https URL, refusing other schemes, paths, queries and credentials."""
    parts = urlsplit(value.strip())
    # Only a bare https host is accepted
    if parts.scheme != "https" or not parts.hostname:
        raise InputError("DATABRICKS_HOST must be an https URL")
    if parts.username or parts.password or parts.path not in ("", "/") or parts.query or parts.fragment:
        raise InputError("DATABRICKS_HOST must be the host only, with no path or credentials")
    return parts.netloc
