"""Checks that every Parquet file the generator writes stores timestamps in microseconds.
Runs generate.py at scale 0.01 into a temporary folder; only landing files are read. Run with: python -m unittest"""
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from tests.test_determinism import generate


class ParquetTimestampTest(unittest.TestCase):
    def test_every_parquet_timestamp_is_microseconds(self):
        """Generate a small landing folder, then read each Parquet schema and check the timestamp unit."""
        with tempfile.TemporaryDirectory() as tmp:
            # Generate at small scale
            self.assertEqual(generate(Path(tmp)), 0)

            # Read every Parquet schema and collect its timestamp units
            files = sorted((Path(tmp) / "landing_staging").rglob("*.parquet"))
            self.assertGreater(len(files), 0)
            units = set()
            for path in files:
                for field in pq.read_schema(path):
                    if pa.types.is_timestamp(field.type):
                        units.add(field.type.unit)

            # Timestamps exist, and all of them are microseconds
            self.assertEqual(units, {"us"})


if __name__ == "__main__":
    unittest.main()
