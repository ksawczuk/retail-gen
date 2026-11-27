"""Chooses the lines of each order or store basket: how many, which category, which SKU and what quantity.

Built by build_truth; generate_online and generate_pos call lines() with the purchases the demand engine drew.
"""
import numpy as np
import pandas as pd

from ..util import bounded_weighted_pick

NS = "datetime64[ns]"
CAMPAIGN_TILT = 3.0
CROSS_SELL_TILT = 1.5


class BasketBuilder:
    """Draws basket lines from each customer's category taste, the category seasonality and SKU popularity."""

    def __init__(self, products, seasonality, preferences, basket_mult, campaign_categories=None, cross_sell=()):
        """Keep the catalogue grouped by category, the seasonality, the per-customer preference matrix and basket
        multipliers (rows in the customers' order), and the categories each campaign promotes."""
        self._seasonality = seasonality
        self._tilts = self._tilt_rows(campaign_categories or {}, seasonality.category_names)
        self._cross_sell = set(cross_sell)
        self._preferences = preferences
        self._basket_mult = basket_mult
        self._names = seasonality.category_names
        self._uniform = np.full(len(self._names), 1.0 / len(self._names))

        # One launch-ordered SKU list per category, for picking among SKUs launched by the line's time
        self._by_category = [self._ordered(products[products["category_name"] == name]) for name in self._names]
        self._catalog = self._ordered(products[~products["pim_excluded"]])
        self._local = self._ordered(products[products["pim_excluded"]])
        local_pop = products.loc[products["pim_excluded"], "popularity"].sum()
        self._local_share = float(local_pop / products["popularity"].sum())

    def basket_multipliers(self, customer_index):
        """The basket size multiplier per purchase: the customer's own, or 1 for a purchase with no customer."""
        customer_index = np.asarray(customer_index)
        return np.where(customer_index >= 0, self._basket_mult[np.maximum(customer_index, 0)], 1.0)

    def lines(self, rng, ts, day_index, customer_index, extra_lines, qty_rate, qty_max, local_items, campaign=None):
        """Return a DataFrame of (row, sku, qty) for purchases at times `ts`, one or more lines each; a purchase a
        campaign caused leans to that campaign's categories. `row` points back to the purchase."""
        ts = np.asarray(ts).astype(NS)
        day_index = np.asarray(day_index)
        mult = self.basket_multipliers(customer_index)

        # How many lines each basket has
        n_lines = 1 + rng.poisson(extra_lines * mult)
        row = np.repeat(np.arange(len(ts)), n_lines)
        line_ts = ts[row]

        # Choose a category per line from the customer's taste times that day's category season
        cause = np.full(len(ts), None, dtype=object) if campaign is None else np.asarray(campaign, dtype=object)
        category = self._categories(rng, np.asarray(customer_index)[row], day_index[row], cause[row])

        # Choose the SKU within the category, among those launched by then
        sku = np.empty(len(row), dtype=object)
        for k, group in enumerate(self._by_category):
            hit = np.flatnonzero(category == k)
            if len(hit):
                sku[hit] = self._pick_launched(rng, group, line_ts[hit])

        # Store baskets sometimes hold a store-local item the catalogue never lists
        if local_items and len(self._local["sku"]):
            local = rng.random(len(row)) < self._local_share
            if local.any():
                sku[local] = self._pick_launched(rng, self._local, line_ts[local])

        # Quantity grows with the customer's basket size
        qty = 1 + np.minimum(rng.poisson(qty_rate * mult[row]), qty_max - 1)
        lines = pd.DataFrame({"row": row, "sku": sku, "qty": qty})
        return lines.drop_duplicates(["row", "sku"]).reset_index(drop=True)

    def _categories(self, rng, customer_index, day_index, cause, chunk=200_000):
        """Draw a category position per line, in chunks so the line-by-category matrices stay small."""
        out = np.empty(len(customer_index), dtype=int)
        for start in range(0, len(customer_index), chunk):
            cust = customer_index[start:start + chunk]
            taste = np.where((cust >= 0)[:, None], self._preferences[np.maximum(cust, 0)], self._uniform)
            weights = taste * self._seasonality.category(day_index[start:start + chunk])
            weights = weights * self._tilt(cause[start:start + chunk], taste)
            cumulative = np.cumsum(weights, axis=1)
            draw = rng.random(len(cust)) * cumulative[:, -1]
            out[start:start + chunk] = (cumulative < draw[:, None]).sum(axis=1)
        return out

    def _tilt(self, cause, taste):
        """Per line, the category multipliers of the campaign that caused the purchase: its promoted categories,
        or for a cross-sell campaign the customer's second-favorite category. 1 where no campaign caused it."""
        tilt = np.ones_like(taste)
        for campaign_id in set(cause[cause != None]):  # noqa: E711
            rows = np.flatnonzero(cause == campaign_id)
            if campaign_id in self._tilts:
                tilt[rows] = self._tilts[campaign_id]
            elif campaign_id in self._cross_sell:
                second = np.argsort(-taste[rows], axis=1)[:, 1]
                tilt[rows, second] = CROSS_SELL_TILT
        return tilt

    @staticmethod
    def _tilt_rows(campaign_categories, names):
        """{campaign_id: multiplier per category}, CAMPAIGN_TILT on the campaign's categories."""
        rows = {}
        for campaign_id, categories in campaign_categories.items():
            if categories:
                rows[campaign_id] = np.array([CAMPAIGN_TILT if n in categories else 1.0 for n in names])
        return rows

    def _pick_launched(self, rng, group, ts):
        """Pick a SKU per time from a launch-ordered group by popularity; before the group's first launch,
        pick from the whole catalogue instead."""
        upper = np.searchsorted(group["launched_at"], ts, side="right")
        out = np.empty(len(ts), dtype=object)
        ok = upper > 0
        if ok.any():
            out[ok] = group["sku"][bounded_weighted_pick(rng, group["cumw"], upper[ok])]
        if (~ok).any():
            fallback = np.maximum(np.searchsorted(self._catalog["launched_at"], ts[~ok], side="right"), 1)
            out[~ok] = self._catalog["sku"][bounded_weighted_pick(rng, self._catalog["cumw"], fallback)]
        return out

    @staticmethod
    def _ordered(products):
        """A launch-ordered view of some products: SKUs, launch times and cumulative popularity."""
        p = products.sort_values("launched_at", kind="stable")
        return {"sku": p["sku"].to_numpy(), "launched_at": p["launched_at"].to_numpy().astype(NS),
                "cumw": np.cumsum(p["popularity"].to_numpy(float))}
