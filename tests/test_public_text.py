"""Public text stays spoiler-free: the README, the docs and the test names never name a catalogued defect id or a
planted marketing flaw. The answer key and retailgen/defects.py are the only places those are spelled out."""
import re
import unittest
from pathlib import Path

from retailgen.defects import REGISTRY

REPO = Path(__file__).resolve().parent.parent
FLAW_TERMS = ("mis-target", "mistarget", "leak", "lose money", "loses money", "contaminat", "fatigue", "negative net",
              "pull-forward", "pullback", "zero lift", "bad timing", "out of season", "wrong category",
              "without consent", "after an unsubscribe", "after unsubscrib", "identification trap", "over-sent",
              "true lift")


def public_docs():
    """The README and every Markdown file under docs/."""
    return [REPO / "README.md"] + sorted((REPO / "docs").glob("*.md"))


def test_names():
    """Every test method name in tests/."""
    names = []
    for path in sorted((REPO / "tests").glob("test_*.py")):
        names += re.findall(r"^\s+def (test_\w+)\(", path.read_text(encoding="utf-8"), flags=re.M)
    return names


class PublicTextTest(unittest.TestCase):

    def test_docs_name_no_defect_id(self):
        for path in public_docs():
            text = path.read_text(encoding="utf-8")
            found = [d for d in REGISTRY if d in text]
            self.assertEqual(found, [], path.name)

    def test_docs_name_no_planted_flaw(self):
        for path in public_docs():
            text = path.read_text(encoding="utf-8").lower()
            found = [term for term in FLAW_TERMS if term in text]
            self.assertEqual(found, [], path.name)

    def test_test_names_name_no_planted_flaw(self):
        words = [term.replace(" ", "_").replace("-", "_") for term in FLAW_TERMS]
        found = [name for name in test_names() if any(w in name for w in words)]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
