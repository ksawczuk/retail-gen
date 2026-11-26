"""Builds the truth once at scale 0.01 and checks the sales come from the demand engine, the card-scan rule
holds, and the CRM change feed shows loyalty joins."""
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from retailgen.config import Config
from retailgen.truth import build_truth
from retailgen.truth.demand import DemandEngine

ORIGINAL_DRAW = DemandEngine.draw


class TruthDemandTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Build the truth with the engine's draws recorded per channel."""
        cls.draws = {}

        def spy(engine, channel):
            """Call the real draw and keep its result."""
            result = ORIGINAL_DRAW(engine, channel)
            cls.draws[channel.name] = result
            return result

        cls.cfg = Config(scale=0.01)
        with mock.patch.object(DemandEngine, "draw", spy):
            cls.t = build_truth(cls.cfg, np.random.default_rng(cls.cfg.seed), log=lambda *a: None)
        cls.ids = cls.t.customers["customer_id"].to_numpy()

    def test_online_orders_are_the_engines_draws(self):
        """Same number of orders, and the same customers (guests as None), as the engine drew."""
        day_idx, cust_idx = self.draws["online"]
        self.assertEqual(len(self.t.orders), len(day_idx))
        drawn = pd.Series(np.where(cust_idx >= 0, self.ids[np.maximum(cust_idx, 0)], "guest")).value_counts()
        made = self.t.orders["customer_id"].fillna("guest").value_counts()
        pd.testing.assert_series_equal(made.sort_index(), drawn.sort_index(), check_names=False)

    def test_store_baskets_are_the_engines_draws(self):
        """Every sale basket is one engine draw; only draws on days with no open store are dropped."""
        day_idx, _ = self.draws["store"]
        baskets = self.t.pos_lines.loc[~self.t.pos_lines["is_return"], "txn_id"].nunique()
        self.assertLessEqual(baskets, len(day_idx))
        self.assertGreater(baskets, 0.99 * len(day_idx))

    def test_every_sale_has_a_true_customer(self):
        sales = self.t.pos_lines[~self.t.pos_lines["is_return"]]
        self.assertTrue(sales["true_customer_id"].notna().all())

    def test_a_card_shows_only_a_member_who_had_joined(self):
        """Scanned sales name the true customer, who had joined the loyalty program by the sale."""
        sales = self.t.pos_lines[~self.t.pos_lines["is_return"] & self.t.pos_lines["customer_id"].notna()]
        self.assertTrue((sales["customer_id"] == sales["true_customer_id"]).all())
        joined = sales["customer_id"].map(self.t.customers.set_index("customer_id")["loyalty_join_at"])
        self.assertTrue((joined <= sales["local_ts"]).all())

    def test_joins_after_the_cutover_are_change_events(self):
        """A member who joins in the increments, after signing up, gets an update carrying their number."""
        cut = self.cfg.history_end + pd.Timedelta(days=1)
        c = self.t.customers
        late = c[(c["loyalty_join_at"] >= cut) & (c["loyalty_join_at"] > c["created_at"])
                 & ~c["customer_id"].isin(self.t.deleted_customers)]
        self.assertGreater(len(late), 0)
        ev = self.t.customer_events
        for r in late.itertuples(index=False):
            hit = ev[(ev["customer_id"] == r.customer_id) & (ev["op"] == "U") & (ev["change_ts"] == r.loyalty_join_at)]
            self.assertEqual(len(hit), 1, r.customer_id)
            self.assertEqual(hit["loyalty_number"].iloc[0], r.loyalty_number)

    def test_new_signups_carry_loyalty_only_when_joining_at_signup(self):
        ev = self.t.customer_events
        inserts = ev[ev["op"] == "I"].merge(self.t.customers[["customer_id", "created_at", "loyalty_join_at"]],
                                            on="customer_id", suffixes=("", "_truth"))
        at_signup = inserts["loyalty_join_at_truth"] == inserts["created_at_truth"]
        self.assertTrue(inserts.loc[at_signup, "loyalty_number"].notna().all())
        self.assertTrue(inserts.loc[~at_signup, "loyalty_number"].isna().all())


if __name__ == "__main__":
    unittest.main()
