"""Unit tests for pusher.config: the environment settings."""

import unittest

from pusher.config import PushConfig
from pusher.errors import InputError

GOOD = {"DATABRICKS_HOST": "https://example.cloud.databricks.com", "DATABRICKS_TOKEN": "fake-token-value"}


class ConfigTest(unittest.TestCase):
    """Covers required settings, the dry-run exception and the host rules."""

    def test_good_settings(self):
        """A host and token are read, and the host becomes a bare name."""
        config = PushConfig.from_env(GOOD)
        self.assertEqual(config.host, "example.cloud.databricks.com")
        self.assertFalse(config.dry_run)

    def test_host_and_token_are_required_for_a_real_run(self):
        """A real run without a host or without a token is refused."""
        for missing in ("DATABRICKS_HOST", "DATABRICKS_TOKEN"):
            env = {k: v for k, v in GOOD.items() if k != missing}
            with self.assertRaises(InputError, msg=missing):
                PushConfig.from_env(env)

    def test_dry_run_needs_no_credentials(self):
        """A dry run is accepted with no host and no token."""
        config = PushConfig.from_env({"PUSH_DRY_RUN": "1"})
        self.assertTrue(config.dry_run)
        self.assertIsNone(config.host)
        self.assertIsNone(config.token)

    def test_dry_run_flag_must_be_exactly_one(self):
        """Only PUSH_DRY_RUN=1 turns on a dry run; other values do not."""
        with self.assertRaises(InputError):
            PushConfig.from_env({"PUSH_DRY_RUN": "true"})

    def test_a_given_host_is_still_checked_in_a_dry_run(self):
        """A bad host is refused even when the run is a dry run."""
        with self.assertRaises(InputError):
            PushConfig.from_env({"PUSH_DRY_RUN": "1", "DATABRICKS_HOST": "http://example.com"})

    def test_bad_hosts_are_refused(self):
        """Plain http, paths, credentials, queries and bare names are refused."""
        for host in (
            "http://example.com", "example.com", "https://user:pw@example.com",
            "https://example.com/path", "https://example.com?x=1", "ftp://example.com",
        ):
            with self.assertRaises(InputError, msg=host):
                PushConfig.from_env({**GOOD, "DATABRICKS_HOST": host})

    def test_token_with_whitespace_is_refused(self):
        """A token with a space or newline is refused."""
        with self.assertRaises(InputError):
            PushConfig.from_env({**GOOD, "DATABRICKS_TOKEN": "abc def"})

    def test_repr_hides_the_token(self):
        """The token never appears in the printed form of the settings."""
        self.assertNotIn("fake-token-value", repr(PushConfig.from_env(GOOD)))


if __name__ == "__main__":
    unittest.main()
