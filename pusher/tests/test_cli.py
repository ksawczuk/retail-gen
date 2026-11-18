"""Unit tests for pusher.cli: exit codes, the log, dry runs without credentials and token safety."""

import io
import tempfile
import unittest
from pathlib import Path

from pusher.cli import main
from pusher.connectors import DirectConnector, TunnelConnector
from pusher.tests.fakes import FakeVolumeClient, make_landing

TOKEN = "fake-token-value"


class CliTest(unittest.TestCase):
    """Covers exit codes 0, 1 and 2 and the output."""

    def setUp(self):
        """Build a fake landing_staging and the base environment."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_landing(Path(self._tmp.name) / "landing_staging", {
            "history/crm/customers/a.csv": b"1234",
            "increments/day=2026-10-01/crm/customers_cdc/b.csv": b"12",
        })
        self.env = {
            "DATABRICKS_HOST": "https://example.cloud.databricks.com",
            "DATABRICKS_TOKEN": TOKEN,
            "PUSH_LANDING_ROOT": str(self.root),
        }
        self.out = io.StringIO()

    def _run(self, argv, env=None, client=None):
        """Run the CLI with a fake client factory."""
        fake = client or FakeVolumeClient()
        code = main(argv, env or self.env, self.out, client_factory=lambda host, token, connector: fake)
        return code, fake

    def test_history_exits_zero_and_logs(self):
        """A good history run sends the file and ends with a DONE line."""
        code, fake = self._run(["history"])
        self.assertEqual(code, 0)
        self.assertEqual(len(fake.files), 1)
        self.assertIn("PUSH crm/customers/a.csv size=4 status=204 delivery=history", self.out.getvalue())
        self.assertIn("DONE sent=1 skipped=0 failed=0", self.out.getvalue())

    def test_day_mode_sends_that_day(self):
        """A day run sends that day's file with the increment label."""
        code, _ = self._run(["day", "2026-10-01"])
        self.assertEqual(code, 0)
        self.assertIn("delivery=increment day=2026-10-01", self.out.getvalue())

    def test_failed_file_exits_one(self):
        """Some files failed gives exit code 1."""
        code, _ = self._run(["history"], client=FakeVolumeClient(fail_on=("a.csv",)))
        self.assertEqual(code, 1)

    def test_bad_input_exits_two_and_sends_nothing(self):
        """A bad mode, a bad date, a missing folder or missing credentials give exit code 2."""
        cases = (
            (["nonsense"], self.env),
            (["day", "2026-13-40"], self.env),
            (["day", "2026-12-25"], self.env),
            (["history"], {k: v for k, v in self.env.items() if k != "DATABRICKS_TOKEN"}),
        )
        for argv, env in cases:
            self.out = io.StringIO()
            code, fake = self._run(argv, env)
            self.assertEqual(code, 2, argv)
            self.assertEqual(fake.calls, [])
            self.assertTrue(self.out.getvalue().startswith("ERROR"))

    def test_dry_run_needs_no_credentials_and_makes_no_client(self):
        """With PUSH_DRY_RUN=1 and no host or token the run lists files and never builds a client."""
        env = {"PUSH_DRY_RUN": "1", "PUSH_LANDING_ROOT": str(self.root)}

        def refuse(host, token, connector):
            """Fail if a client is built."""
            raise AssertionError("a dry run must not build a client")

        code = main(["history"], env, self.out, client_factory=refuse)
        self.assertEqual(code, 0)
        self.assertIn("status=dry-run", self.out.getvalue())

    def test_dry_run_still_exits_two_on_bad_input(self):
        """A dry run with a bad date or a missing landing folder is still exit code 2."""
        for argv, root in ((["day", "bad"], self.root), (["history"], Path(self._tmp.name) / "missing")):
            code = main(argv, {"PUSH_DRY_RUN": "1", "PUSH_LANDING_ROOT": str(root)}, io.StringIO(),
                        client_factory=lambda host, token, connector: None)
            self.assertEqual(code, 2, argv)

    def _connector_used(self, env):
        """Run the CLI and return the connector it handed to the client factory."""
        seen = []

        def factory(host, token, connector):
            """Remember the connector and return a fake client."""
            seen.append(connector)
            return FakeVolumeClient()

        main(["history"], env, self.out, client_factory=factory)
        return seen[0]

    def test_no_proxy_setting_connects_directly(self):
        """With HTTPS_PROXY unset the client gets the direct connector."""
        self.assertIsInstance(self._connector_used(self.env), DirectConnector)

    def test_a_proxy_setting_tunnels(self):
        """With HTTPS_PROXY set the client gets the tunnel connector."""
        env = {**self.env, "HTTPS_PROXY": "http://pusher-proxy:3128"}
        self.assertIsInstance(self._connector_used(env), TunnelConnector)

    def test_a_bad_proxy_setting_exits_two_and_sends_nothing(self):
        """A bad HTTPS_PROXY is exit code 2 with one ERROR line and no client built."""
        for value in ("https://pusher-proxy:3128", "http://user:secret@pusher-proxy:3128", "pusher-proxy"):
            self.out = io.StringIO()
            code, fake = self._run(["history"], {**self.env, "HTTPS_PROXY": value})
            self.assertEqual(code, 2, value)
            self.assertEqual(fake.calls, [])
            self.assertTrue(self.out.getvalue().startswith("ERROR HTTPS_PROXY"))
            self.assertNotIn("secret", self.out.getvalue())

    def test_a_refused_tunnel_is_a_failed_file_with_the_proxy_status(self):
        """A file whose tunnel was refused is logged failed with the status, and the run exits 1."""
        env = {**self.env, "HTTPS_PROXY": "http://pusher-proxy:3128"}
        client = FakeVolumeClient(fail_on=("a.csv",), fail_message="PUT proxy refused the tunnel: HTTP 403")
        code, _ = self._run(["history"], env, client=client)
        self.assertEqual(code, 1)
        self.assertIn("status=failed", self.out.getvalue())
        self.assertIn("error=PUT_proxy_refused_the_tunnel:_HTTP_403", self.out.getvalue())
        self.assertNotIn("pusher-proxy", self.out.getvalue())
        self.assertNotIn(TOKEN, self.out.getvalue())

    def test_the_token_never_appears_in_the_output(self):
        """No run prints the token."""
        self._run(["history"])
        self._run(["nonsense"])
        self.assertNotIn(TOKEN, self.out.getvalue())


if __name__ == "__main__":
    unittest.main()
