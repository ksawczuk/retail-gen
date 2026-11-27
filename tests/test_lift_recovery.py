"""Lift recovery: a holdout comparison recovers the answer key's lift for the clean-holdout gifting campaigns.

Builds the truth at scale 0.1 for seeds 1, 2 and 3 (about a minute). For each of the four gifting campaigns with a
clean holdout (Mother's Day and Father's Day, 2025 and 2026), the measured lift is the treated customers' purchases in
the window over their purchases in the 90 days before, divided by the same ratio for the holdout, minus one. The 12
measured lifts are averaged and must land within 0.06 (about two standard errors) of the average realized lift in
campaign_truth. Negative control: the same estimator on a placebo window, 60 days before each send, when the campaign
had not been sent, must come out within 0.06 of zero and below the gifting estimate.
"""
import unittest

import numpy as np
import pandas as pd

from retailgen.config import Config
from retailgen.truth import build_truth

CAMPAIGNS = ("CMP-03", "CMP-05", "CMP-13", "CMP-15")
SEEDS = (1, 2, 3)
TOLERANCE = 0.06
PRE_DAYS = 90
PLACEBO_SHIFT_DAYS = 60


def purchases(t):
    """Every online order and store basket with its true customer and day."""
    store = t.pos_lines[~t.pos_lines["is_return"]].drop_duplicates("txn_id")
    return pd.concat([
        pd.DataFrame({"customer_id": t.orders["customer_id"], "day": t.orders["order_ts"].dt.normalize()}),
        pd.DataFrame({"customer_id": store["true_customer_id"], "day": store["local_ts"].dt.normalize()}),
    ]).dropna()


def measured_lift(t, buys, campaign_id, shift_days=0):
    """Treated over holdout, each as window purchases over pre-period purchases, minus one; `shift_days` moves the
    window earlier for the placebo."""
    spec = t.campaigns.set_index("campaign_id").loc[campaign_id]
    sends = spec["sends"].split(",")
    shift = pd.Timedelta(days=shift_days)
    start = pd.Timestamp(sends[0]) - shift
    end = pd.Timestamp(sends[-1]) + pd.Timedelta(days=int(spec["window_days"])) - shift
    a = t.campaign_assignment[t.campaign_assignment["campaign_id"] == campaign_id]

    # Purchases per group in the window and in the 90 days before
    def ratio(group):
        """A group's window purchases over its pre-period purchases."""
        who = buys["customer_id"].isin(set(a.loc[a["group"] == group, "customer_id"]))
        window = (who & (buys["day"] >= start) & (buys["day"] < end)).sum()
        before = (who & (buys["day"] >= start - pd.Timedelta(days=PRE_DAYS)) & (buys["day"] < start)).sum()
        return window / before

    return ratio("treated") / ratio("holdout") - 1


class LiftRecoveryTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Build the three seeds once and measure the gifting campaigns and their placebo windows."""
        cls.measured, cls.placebo, cls.realized = [], [], []
        for seed in SEEDS:
            cfg = Config(scale=0.1, seed=seed)
            t = build_truth(cfg, np.random.default_rng(seed), log=lambda *a: None)
            buys = purchases(t)
            truth = t.campaign_truth.set_index("campaign_id")["realized_lift"]
            for campaign_id in CAMPAIGNS:
                cls.measured.append(measured_lift(t, buys, campaign_id))
                cls.placebo.append(measured_lift(t, buys, campaign_id, PLACEBO_SHIFT_DAYS))
                cls.realized.append(truth[campaign_id])

    def test_holdout_comparison_recovers_the_realized_lift(self):
        gap = abs(np.mean(self.measured) - np.mean(self.realized))
        self.assertLess(gap, TOLERANCE, f"measured {np.mean(self.measured):.3f}, realized {np.mean(self.realized):.3f}")

    def test_negative_control_finds_no_lift_before_the_send(self):
        placebo = np.mean(self.placebo)
        self.assertLess(abs(placebo), TOLERANCE, f"placebo {placebo:.3f}")
        self.assertLess(placebo, np.mean(self.measured), f"placebo {placebo:.3f}, measured {np.mean(self.measured):.3f}")


if __name__ == "__main__":
    unittest.main()
