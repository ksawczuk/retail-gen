"""Unit tests for pusher.volume_client.FilesApiClient against a fake HTTP connection."""

import tempfile
import unittest
from pathlib import Path

from pusher.tests.fakes import FakeResponse, make_factory
from pusher.volume_client import FilesApiClient, PushError

TOKEN = "fake-token-value"


def client_for(responses, sleeps=None):
    """Build a client over scripted responses; returns (client, request log)."""
    factory, log = make_factory(responses)
    client = FilesApiClient(
        "example.cloud.databricks.com", TOKEN, connection_factory=factory,
        sleep=(sleeps.append if sleeps is not None else (lambda seconds: None)),
    )
    return client, log


class FilesApiClientTest(unittest.TestCase):
    """Covers headers, the three calls, retries, redirects and token safety."""

    def setUp(self):
        """Make a small local file to upload."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.file = Path(self._tmp.name) / "f.csv"
        self.file.write_bytes(b"hello")

    def test_upload_sends_the_file_with_a_bearer_token(self):
        """A PUT with overwrite carries the body, the length and the bearer header; 204 is success."""
        client, log = client_for([FakeResponse(204)])
        self.assertEqual(client.upload(self.file, "/Volumes/workspace/retail/raw/landing/a/b/f.csv"), 204)
        request = log[0]
        self.assertEqual(request["method"], "PUT")
        self.assertEqual(request["url"], "/api/2.0/fs/files/Volumes/workspace/retail/raw/landing/a/b/f.csv?overwrite=true")
        self.assertEqual(request["body"], b"hello")
        self.assertEqual(request["headers"]["Content-Length"], "5")
        self.assertEqual(request["headers"]["Authorization"], f"Bearer {TOKEN}")

    def test_size_of_reads_content_length_or_none(self):
        """HEAD gives the size on 200 and None on 404."""
        client, _ = client_for([FakeResponse(200, {"Content-Length": "42"}), FakeResponse(404)])
        self.assertEqual(client.size_of("/Volumes/x"), 42)
        self.assertIsNone(client.size_of("/Volumes/y"))

    def test_ensure_directory_accepts_204(self):
        """The directory call succeeds on 204 and fails on an error status."""
        client, log = client_for([FakeResponse(204), FakeResponse(403)])
        client.ensure_directory("/Volumes/x/y")
        self.assertEqual(log[0]["url"], "/api/2.0/fs/directories/Volumes/x/y")
        with self.assertRaises(PushError):
            client.ensure_directory("/Volumes/x/z")

    def test_server_errors_are_retried_then_succeed(self):
        """A 503 is retried after short waits, then a 204 succeeds."""
        sleeps = []
        client, log = client_for([FakeResponse(503), FakeResponse(429), FakeResponse(204)], sleeps)
        self.assertEqual(client.upload(self.file, "/Volumes/x"), 204)
        self.assertEqual(len(log), 3)
        self.assertEqual(sleeps, [1, 4])

    def test_retries_stop_and_fail(self):
        """After the allowed retries a persistent 500 is an error."""
        client, log = client_for([FakeResponse(500)] * 3)
        with self.assertRaises(PushError):
            client.upload(self.file, "/Volumes/x")
        self.assertEqual(len(log), 3)

    def test_redirect_is_a_failure(self):
        """A 3xx is refused so the token cannot be sent elsewhere."""
        client, _ = client_for([FakeResponse(302, {"Location": "https://evil.example"})])
        with self.assertRaises(PushError):
            client.upload(self.file, "/Volumes/x")

    def test_the_token_is_not_in_errors_or_repr(self):
        """Neither an error message nor the client's printed form contains the token."""
        client, _ = client_for([FakeResponse(403)])
        with self.assertRaises(PushError) as caught:
            client.upload(self.file, "/Volumes/x")
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertNotIn(TOKEN, repr(client))


if __name__ == "__main__":
    unittest.main()
