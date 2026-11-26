"""Unit tests for retailgen.truth.demand: expected and realized volumes, who can buy, and the modifier seam."""
import unittest

import numpy as np
import pandas as pd

from retailgen.truth.demand import NONE, Channel, DemandEngine, DemandModifier
from retailgen.truth.lifecycle import CustomerLifecycle
from retailgen.truth.seasonality import Seasonality
from retailgen.util import seasonality as base_curve

DAYS = pd.date_range("2025-01-01", "2026-12-31", freq="D")
HISTORY_END = pd.Timestamp("2026-09-30")
STORE = Channel("store", 100.0, 0.0)
ONLINE = Channel("online", 100.0, 0.12)
N = 2_000


class Scale(DemandModifier):
    """Lifts every customer by the same amount; stands in for a broadcast campaign."""

    def __init__(self, lift, campaign_id="scale"):
        self.amount, self.campaign_id = lift, campaign_id

    def lift(self, day_index, state):
        return np.full(N, self.amount)


class Favor(DemandModifier):
    """Lifts one customer; stands in for a targeted campaign."""

    def __init__(self, position, lift, campaign_id="favor"):
        self.position, self.amount, self.campaign_id = position, lift, campaign_id

    def lift(self, day_index, state):
        out = np.zeros(N)
        out[self.position] = self.amount
        return out


def engine(seed, modifiers=(), created=None, churn=None):
    """An engine over N synthetic customers, all active from 2021 unless `created` or `churn` say otherwise."""
    rng = np.random.default_rng(seed)
    created = created if created is not None else np.full(N, np.datetime64("2021-01-01", "ns"))
    far = np.full(N, np.datetime64("2100-01-01", "ns"))
    life = CustomerLifecycle(churn if churn is not None else far, np.zeros(N, bool), far, np.ones(N), np.ones((N, 1)))
    activity = np.random.default_rng(99).lognormal(0, 1, N)
    return DemandEngine(rng, DAYS, created, activity, life, Seasonality(DAYS, ["Tops"]), modifiers)


class VolumeTest(unittest.TestCase):
    """Expected volume per day and realized volume per month and over the history."""

    @classmethod
    def setUpClass(cls):
        """Draw the store channel with three seeds."""
        cls.draws = [engine(seed).draw(STORE) for seed in (1, 2, 3)]
        cls.expected = engine(1).expected_daily(STORE)

    def test_expected_daily_within_two_percent_of_rate_times_seasonality(self):
        """Per day, the engine's mean is the base rate times the seasonality (gifting windows included)."""
        target = STORE.per_day * base_curve(DAYS) * Seasonality(DAYS, ["Tops"]).shared() / base_curve(DAYS)
        np.testing.assert_allclose(self.expected, target, rtol=0.02)

    def test_realized_history_total_within_two_percent(self):
        """Over the history, each seed's total is within 2% of the expected total."""
        hist = np.asarray(DAYS <= HISTORY_END)
        expected = self.expected[hist].sum()
        for day_idx, _ in self.draws:
            realized = hist[day_idx].sum()
            self.assertAlmostEqual(realized / expected, 1.0, delta=0.02)

    def test_realized_months_within_six_percent_across_three_seeds(self):
        """Each month's total, averaged over the three seeds, is within 6% of expected (one month is ~3,000
        events, so the noise is about 1% after averaging)."""
        months = DAYS.to_period("M")
        expected = pd.Series(self.expected).groupby(months).sum()
        realized = sum(pd.Series(months[d]).value_counts().reindex(expected.index, fill_value=0)
                       for d, _ in self.draws) / 3
        ratio = realized / expected
        self.assertLess((ratio - 1).abs().max(), 0.06, ratio.round(3).to_dict())

    def test_guest_share(self):
        _, cust = engine(4).draw(ONLINE)
        self.assertAlmostEqual((cust == NONE).mean(), ONLINE.guest_share, delta=0.01)


class WhoBuysTest(unittest.TestCase):
    """Which customers the engine may pick."""

    def test_nobody_buys_before_signing_up(self):
        created = np.full(N, np.datetime64("2026-01-01", "ns"))
        created[:10] = np.datetime64("2021-01-01", "ns")
        day_idx, cust = engine(5, created=created).draw(STORE)
        early = DAYS[day_idx] <= pd.Timestamp("2026-01-01")
        self.assertTrue(set(cust[early]) <= set(range(10)))

    def test_a_stopped_customer_never_buys_after_churn(self):
        churn = np.full(N, np.datetime64("2100-01-01", "ns"))
        churn[0] = np.datetime64("2025-03-01", "ns")
        e = engine(6, churn=churn)
        day_idx, cust = e.draw(STORE)
        self.assertFalse((cust[DAYS[day_idx] > pd.Timestamp("2025-03-01")] == 0).any())


class OrderTest(unittest.TestCase):

    def test_customers_out_of_signup_order_are_refused(self):
        created = np.full(N, np.datetime64("2021-01-01", "ns"))
        created[0] = np.datetime64("2022-01-01", "ns")
        with self.assertRaises(ValueError):
            engine(10, created=created)


class ModifierTest(unittest.TestCase):
    """The DemandModifier seam that campaigns will use."""

    def test_scaling_every_weight_scales_the_total(self):
        base = len(engine(7).draw(STORE)[0])
        lifted = len(engine(7, [Scale(0.1)]).draw(STORE)[0])
        self.assertAlmostEqual(lifted / base, 1.1, delta=0.02)

    def test_favoring_one_customer_raises_their_share(self):
        plain = (engine(8).draw(STORE)[1] == 0).sum()
        favored = (engine(8, [Favor(0, 9.0)]).draw(STORE)[1] == 0).sum()
        self.assertGreater(favored, 5 * max(plain, 1))

    def test_overlapping_lifts_are_damped(self):
        """Two +10% campaigns on everyone give +17% (the second at 70%), not +20%."""
        e = engine(11, [Scale(0.1, "a"), Scale(0.1, "b")])
        factor, _, _ = e.campaign_factor(0, None)
        np.testing.assert_allclose(factor, 1.17)

    def test_incremental_purchases_are_credited_to_the_biggest_lift(self):
        """With +100% from one campaign and +10% from another, about 0.65 of purchases are incremental, all
        credited to the bigger one."""
        e = engine(12, [Scale(1.0, "big"), Scale(0.1, "small")])
        purchases = e.draw_all([STORE])["store"]
        credited = purchases.campaign[purchases.campaign != None]  # noqa: E711
        self.assertEqual(set(credited), {"big"})
        self.assertAlmostEqual(len(credited) / len(purchases.campaign), 1.07 / 2.07, delta=0.02)

    def test_pick_uses_base_weights_and_only_signed_up_customers(self):
        created = np.full(N, np.datetime64("2026-01-01", "ns"))
        created[:5] = np.datetime64("2021-01-01", "ns")
        e = engine(9, created=created)
        self.assertTrue((e.pick(np.full(200, 10)) < 5).all())


if __name__ == "__main__":
    unittest.main()
