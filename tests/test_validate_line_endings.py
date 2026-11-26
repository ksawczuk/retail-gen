"""Tests that validate.py's line-ending and BOM scan flags text files only, never binary formats.
Run from the repo root with: python -m unittest"""
import tempfile
import unittest
from pathlib import Path

from validate import text_file_findings


class TextFileFindingsTest(unittest.TestCase):
    def scan(self, files):
        """Write the given name-to-bytes files into a fresh folder and scan it."""
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            for name, data in files.items():
                (stage / name).write_bytes(data)
            return text_file_findings(stage)

    def test_binary_files_holding_crlf_bytes_are_not_flagged(self):
        crlf, boms = self.scan({"a.avro": b"Obj\x01\r\n\x00", "b.parquet": b"PAR1\r\nPAR1"})
        self.assertEqual((crlf, boms), ([], []))

    def test_text_files_with_crlf_are_flagged(self):
        crlf, _ = self.scan({"a.csv": b"id,name\r\n1,x\r\n", "b.jsonl": b'{"a": 1}\r\n'})
        self.assertEqual(sorted(crlf), ["a.csv", "b.jsonl"])

    def test_text_file_with_bom_is_flagged(self):
        _, boms = self.scan({"a.csv": b"\xef\xbb\xbfid\n1\n"})
        self.assertEqual(boms, ["a.csv"])


if __name__ == "__main__":
    unittest.main()
