"""Test doubles: a fake volume client, a fake HTTP connection and a helper that builds a fake landing_staging."""

import io
from pathlib import Path

from pusher.volume_client import PushError, VolumeClient


class FakeVolumeClient(VolumeClient):
    """Keeps uploaded files in memory and records every call; can be told to fail on chosen paths."""

    def __init__(self, existing=None, fail_on=()):
        """Start with remote files (path -> size) and a list of path fragments that make uploads fail."""
        self.files = dict(existing or {})
        self.fail_on = tuple(fail_on)
        self.calls = []

    def size_of(self, remote_path):
        """Return the stored size or None."""
        self.calls.append(("size_of", remote_path))
        return self.files.get(remote_path)

    def ensure_directory(self, remote_dir):
        """Record the call."""
        self.calls.append(("ensure_directory", remote_dir))

    def upload(self, local_path, remote_path):
        """Store the file size, or fail for a matching path."""
        self.calls.append(("upload", remote_path))
        if any(fragment in remote_path for fragment in self.fail_on):
            raise PushError("PUT gave HTTP 500")
        self.files[remote_path] = Path(local_path).stat().st_size
        return 204


class FakeResponse:
    """A canned HTTP response."""

    def __init__(self, status, headers=None, read_error=None):
        """Keep the status and headers, and an error to raise when the body is read."""
        self.status = status
        self._headers = headers or {}
        self._read_error = read_error

    def read(self):
        """Return an empty body, or raise the configured error."""
        if self._read_error is not None:
            raise self._read_error
        return b""

    def getheaders(self):
        """Return the headers as pairs."""
        return list(self._headers.items())


class FakeConnection:
    """Records one request and returns the next scripted response."""

    def __init__(self, script, log):
        """Keep the shared response script and the shared request log."""
        self._script = script
        self._log = log

    def request(self, method, url, body=None, headers=None):
        """Record the request; read the body if it is a file object."""
        sent = body.read() if hasattr(body, "read") else body
        self._log.append({"method": method, "url": url, "headers": dict(headers or {}), "body": sent})

    def getresponse(self):
        """Return the next scripted response, or raise it if it is an exception."""
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        """Nothing to close."""


def make_factory(responses):
    """Return (factory, log): a connection factory that serves the responses in order, and the request log."""
    script = list(responses)
    log = []

    def factory(host, timeout=None):
        """Build a fake connection."""
        return FakeConnection(script, log)

    return factory, log


def make_landing(root, files):
    """Create files (relative name -> bytes) under root; return root as a Path."""
    root = Path(root)
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


class Capture(io.StringIO):
    """A string stream for capturing the log."""
