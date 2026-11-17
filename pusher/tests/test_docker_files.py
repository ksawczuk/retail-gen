"""Text checks of the Docker files against the container contract (no Docker needed)."""

import re
import unittest
from pathlib import Path

PUSHER_DIR = Path(__file__).resolve().parent.parent


class DockerFilesTest(unittest.TestCase):
    """Reads the Dockerfile and compose file and checks the contract items."""

    def setUp(self):
        """Load the files."""
        self.dockerfile = (PUSHER_DIR / "Dockerfile").read_text(encoding="utf-8")
        self.compose = (PUSHER_DIR / "compose.yaml").read_text(encoding="utf-8")
        self.dockerignore = (PUSHER_DIR / ".dockerignore").read_text(encoding="utf-8")

    def test_base_image_is_pinned_slim_python(self):
        """The base is a Python slim image with a full version, not latest."""
        match = re.search(r"^FROM python:(\S+)", self.dockerfile, re.M)
        self.assertIsNotNone(match)
        tag = match.group(1)
        self.assertNotIn("latest", tag)
        self.assertRegex(tag, r"^\d+\.\d+\.\d+-slim")

    def test_runs_as_a_non_root_user(self):
        """A USER line switches to a non-root user."""
        users = re.findall(r"^USER (\S+)", self.dockerfile, re.M)
        self.assertTrue(users)
        self.assertNotIn(users[-1], ("root", "0"))

    def test_no_installs_ports_or_secrets(self):
        """No pip install, no EXPOSE, no secrets baked in."""
        self.assertNotIn("pip install", self.dockerfile)
        self.assertNotIn("EXPOSE", self.dockerfile)
        self.assertNotIn("DATABRICKS_TOKEN", self.dockerfile)

    def test_entrypoint_runs_the_pusher(self):
        """The entrypoint is python -m pusher."""
        self.assertIn('ENTRYPOINT ["python", "-m", "pusher"]', self.dockerfile)

    def test_compose_is_one_shot_hardened_and_read_only(self):
        """The compose file mounts the data read-only, publishes no ports, and drops privileges."""
        self.assertIn(":/data/landing_staging:ro", self.compose)
        self.assertNotRegex(self.compose, r"^\s*ports:", )
        for item in ("read_only: true", "cap_drop:", "- ALL", "no-new-privileges:true", "mem_limit:", "cpus:",
                     'restart: "no"'):
            self.assertIn(item, self.compose)

    def test_compose_mounts_nothing_else(self):
        """Only one volume line, and it is the landing folder."""
        lines = [line for line in self.compose.splitlines() if line.strip().startswith("- ${")]
        self.assertEqual(len(lines), 1)

    def test_dockerignore_keeps_env_and_tests_out(self):
        """The image context leaves out .env and the tests."""
        self.assertIn(".env", self.dockerignore)
        self.assertIn("tests/", self.dockerignore)

    def test_env_example_holds_no_real_secret(self):
        """The example file names the variables with placeholder values."""
        text = (PUSHER_DIR / ".env.example").read_text(encoding="utf-8")
        self.assertIn("DATABRICKS_TOKEN=replace-with", text)


if __name__ == "__main__":
    unittest.main()
