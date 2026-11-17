"""The connection to the Databricks volume: an interface and the Files API implementation.

Used by the pusher for every remote call; tests replace it with a fake. The token lives only in the real client.
"""

import http.client
import time
from abc import ABC, abstractmethod
from urllib.parse import quote

RETRY_STATUSES = (429, 500, 502, 503, 504)
RETRY_WAITS = (1, 4)


class PushError(Exception):
    """A remote call failed; the message never carries the token or a response body."""


class VolumeClient(ABC):
    """What the pusher needs from the volume."""

    @abstractmethod
    def size_of(self, remote_path):
        """Return the size in bytes of a remote file, or None if it does not exist."""

    @abstractmethod
    def ensure_directory(self, remote_dir):
        """Make sure a remote folder exists."""

    @abstractmethod
    def upload(self, local_path, remote_path):
        """Upload one file, replacing any file at that path; return the HTTP status."""


class FilesApiClient(VolumeClient):
    """Talks to the Databricks Files API over HTTPS with a bearer token; follows no redirects."""

    def __init__(self, host, token, connection_factory=http.client.HTTPSConnection, sleep=time.sleep, timeout=300):
        """Keep the host and token; the connection factory and sleep are injected so tests need no network."""
        self._host = host
        self._token = token
        self._connect = connection_factory
        self._sleep = sleep
        self._timeout = timeout

    def __repr__(self):
        """Show the host only, never the token."""
        return f"FilesApiClient(host={self._host!r})"

    def size_of(self, remote_path):
        """Ask for the file's size with HEAD; 404 means it is not there."""
        status, headers = self._send("HEAD", f"/api/2.0/fs/files{quote(remote_path)}")
        if status == 404:
            return None
        if status != 200:
            raise PushError(f"HEAD {remote_path} gave HTTP {status}")
        # A missing or non-numeric length is a failed check for this file, not a crash
        try:
            return int(headers.get("content-length", ""))
        except ValueError:
            raise PushError(f"HEAD {remote_path} gave no usable Content-Length") from None

    def ensure_directory(self, remote_dir):
        """Create the folder if needed; the call succeeds when it already exists."""
        status, _ = self._send("PUT", f"/api/2.0/fs/directories{quote(remote_dir)}")
        if status not in (200, 204):
            raise PushError(f"creating {remote_dir} gave HTTP {status}")

    def upload(self, local_path, remote_path):
        """Stream the file with PUT and overwrite; returns 204 on success."""
        url = f"/api/2.0/fs/files{quote(remote_path)}?overwrite=true"
        status, _ = self._send("PUT", url, local_path=local_path)
        if status != 204:
            raise PushError(f"PUT {remote_path} gave HTTP {status}")
        return status

    def _send(self, method, url, local_path=None):
        """Send one request, retrying throttling and server errors; returns (status, headers)."""
        attempt = 0
        while True:
            status, headers = self._once(method, url, local_path)
            # Retry only throttling and server errors, a few times
            if status in RETRY_STATUSES and attempt < len(RETRY_WAITS):
                self._sleep(RETRY_WAITS[attempt])
                attempt += 1
                continue
            # A redirect is a failure, so the token is never sent anywhere else
            if 300 <= status < 400:
                raise PushError(f"{method} was redirected (HTTP {status})")
            return status, headers

    def _once(self, method, url, local_path):
        """Make one HTTPS request on a new connection and return (status, headers)."""
        headers = {"Authorization": f"Bearer {self._token}"}
        connection = self._connect(self._host, timeout=self._timeout)
        try:
            if local_path is None:
                connection.request(method, url, headers=headers)
            else:
                with open(local_path, "rb") as handle:
                    headers["Content-Length"] = str(local_path.stat().st_size)
                    connection.request(method, url, body=handle, headers=headers)
            response = connection.getresponse()
            response.read()
            return response.status, {name.lower(): value for name, value in response.getheaders()}
        except (OSError, http.client.HTTPException) as exc:
            raise PushError(f"{method} failed: {type(exc).__name__}") from None
        finally:
            connection.close()
