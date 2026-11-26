"""Test that the manifest records a planted defect only for the rows that reach the written files (Bug 579).
Run with: python -m unittest"""
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd

from retailgen.config import Config
from retailgen.manifest import Manifest
from retailgen.sources.web_inventory import emit_inventory

HISTORY_WEEKS = list(pd.date_range(end="2026-09-27", periods=8, freq="W-SUN"))
IN_WINDOW_WEEK = pd.Timestamp("2026-10-25")
AFTER_WINDOW_WEEK = pd.Timestamp("2026-11-01")


class FakeOutput:
    """Stands in for the writer: keeps every Parquet frame the inventory emitter writes."""

    def __init__(self):
        self.frames = []

    def parquet(self, df, day, source, entity, filename):
        self.frames.append(df)


def _inventory() -> pd.DataFrame:
    """Two stores, two SKUs, eight history weeks plus one week inside and one after the increment window."""
    weeks = HISTORY_WEEKS + [IN_WINDOW_WEEK, AFTER_WINDOW_WEEK]
    rows = [(store, sku, week, 10) for store in (1, 2) for sku in ("000001", "000002") for week in weeks]
    return pd.DataFrame(rows, columns=["store_id", "sku", "snapshot_date", "on_hand"])


def _position(inv, store, week, sku="000001") -> int:
    """The row position of one store, SKU and week in the fake inventory."""
    hit = (inv["store_id"] == store) & (inv["sku"] == sku) & (inv["snapshot_date"] == week)
    return int(np.flatnonzero(hit.to_numpy())[0])


class InventoryManifestWrittenRowsTest(unittest.TestCase):
    def setUp(self):
        """Plant three rows: one in a removed span, one delivered after the window, one that is written."""
        self.inv = _inventory()
        gap_week = HISTORY_WEEKS[len(HISTORY_WEEKS) // 2]
        planted = [_position(self.inv, 1, gap_week),
                   _position(self.inv, 2, AFTER_WINDOW_WEEK),
                   _position(self.inv, 2, HISTORY_WEEKS[0])]
        self.survivor_key = f"2|000001|{HISTORY_WEEKS[0]:%Y-%m-%d}"
        self.manifest = Manifest()
        self.out = FakeOutput()
        with mock.patch("retailgen.sources.web_inventory.pick_rows", return_value=np.array(sorted(planted))):
            emit_inventory(Config(scale=0.01), np.random.default_rng(1), SimpleNamespace(inventory=self.inv),
                           self.out, self.manifest)

    def test_manifest_counts_only_planted_rows_that_were_written(self):
        """A planted row removed before writing is not in the manifest."""
        self.assertEqual(self.manifest.count("inventory.negative_on_hand"), 1)

    def test_manifest_keys_are_the_written_planted_rows(self):
        entry = self.manifest._entries["inventory.negative_on_hand"]
        self.assertEqual(entry["keys"], [self.survivor_key])

    def test_no_written_row_of_this_kind_lies_outside_the_planted_set(self):
        """The truth has none of these rows, so every one written must be a planted one."""
        written = pd.concat(self.out.frames)
        negative = written[written["on_hand"] < 0]
        keys = (negative["store_id"].astype(str) + "|" + negative["sku"] + "|" +
                pd.to_datetime(negative["snapshot_date"]).dt.strftime("%Y-%m-%d"))
        self.assertEqual(sorted(keys), [self.survivor_key])


if __name__ == "__main__":
    unittest.main()
