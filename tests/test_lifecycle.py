"""Unit tests for retailgen.truth.lifecycle: churn, fading, comebacks, basket size, category taste and loyalty."""
import unittest

import numpy as np
import pandas as pd

from retailgen.config import Config
from retailgen.truth.customers import generate_customers
from retailgen.truth.lifecycle import (CustomerLifecycle, DECAY_SHARE, GOLD_SHARE, MONTHLY_CHURN, SILVER_SHARE,
                                       loyalty_join_dates, tiers_by_activity)

NS = "datetime64[ns]"
T0 = np.datetime64("2025-01-01", "ns")


def synthetic_customers(n, seed=7):
    """n customers all created at T0 with lognormal activity, for the lifecycle draws."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"created_at": np.full(n, T0), "activity": rng.lognormal(0, 1.0, n)})


class FactorTest(unittest.TestCase):
    """The buying level on a day, from hand-set lifecycles."""

    def _life(self, decays, react_days):
        """One customer who churns on day 100 and comes back `react_days` after (None: never)."""
        churn = T0 + np.timedelta64(100, "D")
        react = churn + np.timedelta64(react_days if react_days is not None else 20_000, "D")
        return CustomerLifecycle(np.array([churn]), np.array([decays]), np.array([react]), np.ones(1), np.ones((1, 1)))

    def test_active_before_churn(self):
        self.assertEqual(self._life(False, None).factor(T0 + np.timedelta64(99, "D"))[0], 1.0)

    def test_stopper_drops_to_zero(self):
        self.assertEqual(self._life(False, None).factor(T0 + np.timedelta64(101, "D"))[0], 0.0)

    def test_fader_halves_every_120_days(self):
        life = self._life(True, None)
        self.assertAlmostEqual(life.factor(T0 + np.timedelta64(220, "D"))[0], 0.5)
        self.assertAlmostEqual(life.factor(T0 + np.timedelta64(340, "D"))[0], 0.25)

    def test_comeback_buys_at_half_level(self):
        life = self._life(False, 30)
        self.assertEqual(life.factor(T0 + np.timedelta64(120, "D"))[0], 0.0)
        self.assertEqual(life.factor(T0 + np.timedelta64(131, "D"))[0], 0.5)


class BuildTest(unittest.TestCase):
    """The drawn lifecycles, over many synthetic customers."""

    @classmethod
    def setUpClass(cls):
        """Draw 100,000 lifecycles once."""
        cls.customers = synthetic_customers(100_000)
        cls.life = CustomerLifecycle.build(np.random.default_rng(11), cls.customers, 13)

    def test_monthly_churn_averages_the_rate(self):
        """About MONTHLY_CHURN of customers churn within their first month."""
        first_month = (self.life.churn_at - T0) / np.timedelta64(1, "D") < 30.44
        self.assertAlmostEqual(first_month.mean(), MONTHLY_CHURN, delta=0.0015)

    def test_low_activity_customers_churn_sooner(self):
        """The lowest-activity quarter churns sooner, on median, than the highest."""
        activity = self.customers["activity"].to_numpy()
        days = (self.life.churn_at - T0) / np.timedelta64(1, "D")
        low, high = activity < np.quantile(activity, 0.25), activity > np.quantile(activity, 0.75)
        self.assertLess(np.median(days[low]), np.median(days[high]))

    def test_about_six_percent_come_back_within_a_year_of_churning(self):
        """Comebacks follow a yearly rate of 6%, so 1 - exp(-0.06), about 5.8%, come back within 365 days."""
        within_year = (self.life.reactivate_at - self.life.churn_at) / np.timedelta64(1, "D") < 365
        self.assertAlmostEqual(within_year.mean(), 1 - np.exp(-0.06), delta=0.003)

    def test_decay_share(self):
        self.assertAlmostEqual(self.life.decays.mean(), DECAY_SHARE, delta=0.01)

    def test_basket_multiplier_has_mean_one_and_spread(self):
        self.assertAlmostEqual(self.life.basket_mult.mean(), 1.0, delta=0.01)
        self.assertGreater(self.life.basket_mult.std(), 0.25)

    def test_preferences_sum_to_one_and_concentrate(self):
        """Each row sums to 1, and on average the top three categories hold over 60% of a customer's taste."""
        prefs = self.life.preferences
        np.testing.assert_allclose(prefs.sum(axis=1), 1.0)
        top3 = np.sort(prefs, axis=1)[:, ::-1][:, :3].sum(axis=1)
        self.assertGreater(top3.mean(), 0.6)


class LoyaltyTest(unittest.TestCase):
    """Join dates, tiers, and the membership share from generate_customers."""

    def test_join_dates_fall_between_signup_and_end(self):
        rng = np.random.default_rng(3)
        created = pd.Series(pd.to_datetime(["2023-05-01", "2025-06-01", "2026-11-01"] * 1000))
        member = rng.random(len(created)) < 0.65
        end = pd.Timestamp("2026-12-31")
        joined = loyalty_join_dates(rng, created, member, end)
        self.assertTrue(pd.isna(joined[~member]).all())
        self.assertTrue((joined[member] >= created.to_numpy()[member]).all())
        self.assertTrue((joined[member] <= np.datetime64(end, "ns")).all())

    def test_a_share_join_at_signup(self):
        """About 35% of all customers (35/65 of members) join the day they sign up."""
        rng = np.random.default_rng(4)
        created = pd.Series(np.full(50_000, T0))
        joined = loyalty_join_dates(rng, created, np.ones(50_000, bool), pd.Timestamp("2026-12-31"))
        self.assertAlmostEqual((joined == T0).mean(), 0.35 / 0.65, delta=0.01)

    def test_tiers_follow_activity(self):
        """Gold members out-rank every Silver, Silver every Bronze; non-members have none."""
        rng = np.random.default_rng(5)
        activity = rng.lognormal(0, 1, 10_000)
        member = rng.random(10_000) < 0.65
        tiers = tiers_by_activity(activity, member)
        self.assertTrue((tiers[~member] == None).all())  # noqa: E711
        gold, silver, bronze = (activity[tiers == t] for t in ("Gold", "Silver", "Bronze"))
        self.assertGreater(gold.min(), silver.max())
        self.assertGreater(silver.min(), bronze.max())
        self.assertAlmostEqual(len(gold) / member.sum(), GOLD_SHARE, delta=0.001)
        self.assertAlmostEqual(len(silver) / member.sum(), SILVER_SHARE, delta=0.001)

    def test_membership_ends_near_65_percent(self):
        """By the end of the window about 65% of customers have joined, staff included."""
        cfg = Config(scale=0.1)
        customers, _ = generate_customers(cfg, np.random.default_rng(cfg.seed))
        joined = customers["loyalty_join_at"].notna() & (customers["loyalty_join_at"] <= cfg.increment_end)
        self.assertAlmostEqual(joined.mean(), 0.65, delta=0.02)
        staff = customers[customers["is_employee"]]
        self.assertTrue((staff["loyalty_join_at"] == staff["created_at"]).all())


if __name__ == "__main__":
    unittest.main()
