"""Source-text guard: the pusher depends on the landing layout only, never on the generator or the answer key."""

import unittest
from pathlib import Path

PUSHER_DIR = Path(__file__).resolve().parent.parent
FORBIDDEN_EVERYWHERE = ("retailgen", "defects", "manifest")


class SourceScanTest(unittest.TestCase):
    """Reads each pusher module and checks what it mentions."""

    def _modules(self):
        """Return the pusher's own source files, excluding tests."""
        return [path for path in PUSHER_DIR.glob("*.py")]

    def test_no_module_imports_or_names_the_generator(self):
        """No pusher module mentions the generator library, the defect catalogue or the manifest."""
        for path in self._modules():
            text = path.read_text(encoding="utf-8").lower()
            for word in FORBIDDEN_EVERYWHERE:
                self.assertNotIn(word, text, f"{path.name} mentions {word}")

    def test_only_the_planner_names_the_answer_key(self):
        """The answer-key folder name appears only in the planner's refusal list."""
        for path in self._modules():
            text = path.read_text(encoding="utf-8").lower()
            if path.name != "planner.py":
                self.assertNotIn("answer_key", text, path.name)

    def test_modules_only_import_the_standard_library_and_the_package(self):
        """Every import is standard library or the pusher package."""
        allowed = {
            "abc", "dataclasses", "datetime", "http", "os", "pathlib", "pusher", "re", "sys", "time", "urllib",
        }
        for path in self._modules():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith(("import ", "from ")):
                    root = line.split()[1].split(".")[0]
                    self.assertIn(root, allowed, f"{path.name}: {line}")


if __name__ == "__main__":
    unittest.main()
