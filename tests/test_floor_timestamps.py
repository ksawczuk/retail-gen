"""Checks that flooring timestamps to microseconds (GEN-01) keeps the data usable.
Unit tests for floor_timestamps, and a scale 0.01 generation that proves flooring creates no new ties between rows
that share a key. Only landing files' data frames are inspected; the answer key is never opened.
Run with: python -m unittest"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import generate
from retailgen.writers import Output, floor_timestamps
from tests.generator_args import source_args

# What identifies a row of each Parquet entity, for the tie check
KEYS = {
    ("oms", "orders"): ["order_id"],
    ("oms", "order_lines"): ["order_id", "line_number"],
    ("oms", "payments"): ["payment_event_id"],
    ("oms", "returns"): ["return_id"],
    ("oms", "shipments"): ["shipment_id"],
    ("inventory", "snapshots"): ["store_id", "sku", "snapshot_date"],
}


class FloorTimestampsTest(unittest.TestCase):
    def test_floors_naive_and_aware_columns_and_leaves_the_rest(self):
        """Sub-microsecond parts are dropped from both kinds of timestamp; other columns and the input are untouched."""
        naive = pd.Series(pd.to_datetime([1736383903298260099, 1736383903298260999], unit="ns"))
        aware = naive.dt.tz_localize("UTC")
        df = pd.DataFrame({"a": naive, "b": aware, "n": [1, 2], "s": ["x", "y"]})

        out = floor_timestamps(df)

        self.assertEqual(out["a"].dt.nanosecond.tolist(), [0, 0])
        self.assertEqual(out["b"].dt.nanosecond.tolist(), [0, 0])
        self.assertEqual(out["a"].iloc[0], pd.Timestamp(1736383903298260000, unit="ns"))
        self.assertEqual(out["n"].tolist(), [1, 2])
        self.assertEqual(df["a"].dt.nanosecond.tolist(), [99, 999])


class NoNewTiesTest(unittest.TestCase):
    def test_flooring_makes_no_two_keyed_timestamps_equal(self):
        """For each Parquet entity and timestamp column, distinct (key, timestamp) pairs are the same before and after."""
        pairs = {}
        original = Output.parquet

        def spy(self, df, day, source, entity, filename):
            """Collect the (key, timestamp) pairs before and after flooring, then write the file as usual."""
            keys = KEYS[(source, entity)]
            floored = floor_timestamps(df)
            for column in df.columns:
                if pd.api.types.is_datetime64_any_dtype(df[column]):
                    subset = keys + [column]
                    bucket = pairs.setdefault((entity, column), {"before": [], "after": []})
                    bucket["before"].append(df[subset])
                    bucket["after"].append(floored[subset])
            return original(self, df, day, source, entity, filename)

        with tempfile.TemporaryDirectory() as tmp:
            argv = ["generate.py", "--scale", "0.01", "--out", str(Path(tmp)), "--no-truth", *source_args()]
            with mock.patch("sys.argv", argv), mock.patch.object(Output, "parquet", spy):
                generate.main()

        # Timestamp columns were actually checked
        self.assertGreater(len(pairs), 0)
        # No (key, timestamp) pair count changes after flooring
        changed = []
        for (entity, column), bucket in pairs.items():
            before = pd.concat(bucket["before"]).drop_duplicates().shape[0]
            after = pd.concat(bucket["after"]).drop_duplicates().shape[0]
            if before != after:
                changed.append((entity, column, before, after))
        self.assertEqual(changed, [])


if __name__ == "__main__":
    unittest.main()
