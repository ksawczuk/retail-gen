"""Unit tests for retailgen.truth.baskets: category taste, launch dates, store-local items and basket size."""
import unittest

import numpy as np
import pandas as pd

from retailgen.truth.baskets import BasketBuilder
from retailgen.truth.seasonality import Seasonality

DAYS = pd.date_range("2025-01-01", "2026-12-31", freq="D")
NAMES = ["Tops", "Camping"]
NS = "datetime64[ns]"


def products():
    """Two categories of four SKUs, one launched mid-2026, and one store-local item."""
    rows = [{"sku": f"1{k}", "category_name": "Tops", "pim_excluded": False, "launched_at": "2024-01-01"}
            for k in range(4)]
    rows += [{"sku": f"2{k}", "category_name": "Camping", "pim_excluded": False, "launched_at": "2024-01-01"}
             for k in range(3)]
    rows.append({"sku": "29", "category_name": "Camping", "pim_excluded": False, "launched_at": "2026-06-01"})
    rows.append({"sku": "990001", "category_name": None, "pim_excluded": True, "launched_at": "2023-05-01"})
    p = pd.DataFrame(rows)
    p["launched_at"] = pd.to_datetime(p["launched_at"]).astype(NS)
    p["popularity"] = 1.0
    return p


def builder(preferences, basket_mult=None):
    """A BasketBuilder over the test products, with the given per-customer preferences."""
    n = len(preferences)
    mult = np.ones(n) if basket_mult is None else basket_mult
    return BasketBuilder(products(), Seasonality(DAYS, NAMES), np.asarray(preferences, float), mult)


def purchases(n, when="2025-03-01"):
    """n purchase times on one day, and that day's position."""
    day = DAYS.get_loc(pd.Timestamp(when))
    return np.full(n, np.datetime64(when, "ns")), np.full(n, day)


class BasketTest(unittest.TestCase):

    def test_a_customer_buys_only_from_their_category(self):
        ts, day = purchases(500)
        lines = builder([[0.0, 1.0]]).lines(np.random.default_rng(1), ts, day, np.zeros(500, int),
                                            extra_lines=1.0, qty_rate=0.2, qty_max=3, local_items=False)
        self.assertTrue(lines["sku"].str.startswith("2").all())

    def test_skus_not_launched_yet_are_never_picked(self):
        ts, day = purchases(2000, "2026-03-01")
        lines = builder([[0.0, 1.0]]).lines(np.random.default_rng(2), ts, day, np.zeros(2000, int),
                                            extra_lines=1.0, qty_rate=0.2, qty_max=3, local_items=False)
        self.assertNotIn("29", set(lines["sku"]))

    def test_local_items_only_in_store_baskets(self):
        ts, day = purchases(3000)
        b = builder([[0.5, 0.5]])
        args = dict(extra_lines=1.0, qty_rate=0.2, qty_max=3)
        online = b.lines(np.random.default_rng(3), ts, day, np.zeros(3000, int), local_items=False, **args)
        store = b.lines(np.random.default_rng(3), ts, day, np.zeros(3000, int), local_items=True, **args)
        self.assertNotIn("990001", set(online["sku"]))
        self.assertIn("990001", set(store["sku"]))

    def test_guests_use_an_even_taste_times_the_season(self):
        """In March Camping's season is 1.5 and Tops' 1.0, so an even taste gives Tops 1.0 / 2.5 of the lines."""
        ts, day = purchases(4000)
        lines = builder([[1.0, 0.0]]).lines(np.random.default_rng(4), ts, day, np.full(4000, -1),
                                            extra_lines=0.0, qty_rate=0.0, qty_max=1, local_items=False)
        share_tops = lines["sku"].str.startswith("1").mean()
        self.assertAlmostEqual(share_tops, 0.4, delta=0.03)

    def test_bigger_baskets_have_more_lines_and_units(self):
        ts, day = purchases(3000)
        b = builder([[0.5, 0.5], [0.5, 0.5]], basket_mult=np.array([0.5, 2.0]))
        args = dict(extra_lines=0.8, qty_rate=0.3, qty_max=4, local_items=False)
        small = b.lines(np.random.default_rng(5), ts, day, np.zeros(3000, int), **args)
        big = b.lines(np.random.default_rng(5), ts, day, np.ones(3000, int), **args)
        self.assertGreater(len(big), len(small))
        self.assertGreater(big["qty"].mean(), small["qty"].mean())
        self.assertLessEqual(big["qty"].max(), 4)

    def test_no_sku_twice_in_one_basket(self):
        ts, day = purchases(1000)
        lines = builder([[0.5, 0.5]]).lines(np.random.default_rng(6), ts, day, np.zeros(1000, int),
                                            extra_lines=3.0, qty_rate=0.2, qty_max=3, local_items=True)
        self.assertFalse(lines.duplicated(["row", "sku"]).any())


if __name__ == "__main__":
    unittest.main()
