"""Unit tests for the campaigns: the calendar, holdouts get baseline demand, the signup campaigns, and the campaign
answer key from one small build."""
import unittest

import numpy as np
import pandas as pd

from retailgen.config import Config
from retailgen.truth import build_truth
from retailgen.truth.campaigns import (CampaignContext, HOLDOUT_SHARE, POST_UNSUBSCRIBE_SENDS, SeasonalCampaign,
                                       calendar)
from retailgen.truth.customers import generate_customers
from retailgen.truth.demand import DemandState
from retailgen.truth.signups import apply_signup_campaigns

DAYS = pd.date_range("2025-01-01", "2026-12-31", freq="D")


class CalendarTest(unittest.TestCase):

    def test_campaign_counts_follow_the_plan(self):
        specs = calendar()
        kinds = pd.Series([s.kind for s in specs]).value_counts().to_dict()
        self.assertEqual(kinds["seasonal"], 21)
        self.assertEqual(kinds["winback"], 8)
        self.assertEqual(kinds["gain_loyalty"], 7)
        self.assertEqual(kinds["prospects"], 9)
        self.assertEqual(kinds["newsletter"], 1)
        newsletter = [s for s in specs if s.kind == "newsletter"][0]
        self.assertEqual(len(newsletter.sends), 24)
        self.assertEqual((newsletter.sends[0].day, newsletter.sends[-1].day), ("2025-01-10", "2026-12-10"))
        self.assertEqual(kinds["canvas"], 1)

    def test_holdouts_follow_decision_4(self):
        """7 clean and 4 contaminated holdouts among the 37 broadcast campaigns; each contaminated one has a
        reminder; no holdout anywhere else."""
        specs = calendar()
        broadcast = [s for s in specs if s.kind in ("seasonal", "newsletter", "winback", "gain_loyalty")]
        self.assertEqual(len(broadcast), 37)
        holdouts = pd.Series([s.holdout for s in broadcast]).value_counts().to_dict()
        self.assertEqual((holdouts.get("clean"), holdouts.get("contaminated")), (7, 4))
        reminders = {s.parent for s in specs if s.kind == "reminder"}
        self.assertEqual(reminders, {s.campaign_id for s in broadcast if s.holdout == "contaminated"})

    def test_one_winback_is_mistargeted_and_three_flights_add_customers(self):
        specs = calendar()
        self.assertEqual(sorted(s.lapsed_days for s in specs if s.kind == "winback"), [45] + [180] * 7)
        self.assertEqual([s.sends[0].lift for s in specs if s.lapsed_days == 45], [0.0])
        self.assertEqual(sum(s.adds_customers for s in specs if s.kind == "prospects"), 3)


class HoldoutTest(unittest.TestCase):
    """A seasonal campaign over synthetic customers: the holdout gets no lift."""

    def test_holdout_customers_get_baseline_demand_only(self):
        n = 5_000
        rng = np.random.default_rng(1)
        ctx = CampaignContext(rng, DAYS, np.full(n, np.datetime64("2021-01-01", "ns")), np.ones(n, bool),
                              np.full(n, np.datetime64("NaT", "ns")), lifecycle=None)
        spec = [s for s in calendar() if s.campaign_id == "CMP-03"][0]
        campaign = SeasonalCampaign(spec, ctx)
        send_day = DAYS.get_loc(pd.Timestamp(spec.sends[0].day))
        campaign.start_day(send_day, DemandState(n))
        lift = campaign.lift(send_day, None)
        self.assertTrue((lift[campaign.holdout] == 0).all())
        treated = np.setdiff1d(np.arange(n), campaign.holdout)
        self.assertTrue((lift[treated] > 0).all())
        self.assertAlmostEqual(len(campaign.holdout) / n, HOLDOUT_SHARE, delta=0.015)


class SignupTest(unittest.TestCase):
    """The signup campaigns on scale 0.05 customers."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = Config(scale=0.05)
        rng = np.random.default_rng(cls.cfg.seed)
        cls.before, addresses = generate_customers(cls.cfg, rng)
        cls.after, cls.addresses, cls.result = apply_signup_campaigns(cls.cfg, rng, cls.before, addresses, calendar())

    def test_moved_signups_stay_on_their_side_of_the_cutover(self):
        cut = self.cfg.history_end + pd.Timedelta(days=1)
        old = self.before.set_index("customer_id")["created_at"]
        new = self.after.set_index("customer_id")["created_at"]
        moved = [c for ids in self.result.moved.values() for c in ids]
        self.assertGreater(len(moved), 0)
        self.assertTrue(((old[moved] >= cut) == (new[moved] >= cut)).all())

    def test_customers_stay_sorted_by_signup(self):
        self.assertTrue(self.after["created_at"].is_monotonic_increasing)

    def test_new_flight_customers_have_records_and_addresses(self):
        added = [c for ids in self.result.added.values() for c in ids]
        self.assertGreater(len(added), 0)
        self.assertTrue(set(added) <= set(self.after["customer_id"]))
        self.assertTrue(set(added) <= set(self.addresses["customer_id"]))
        self.assertTrue(self.after["customer_id"].is_unique and self.addresses["address_id"].is_unique)

    def test_gain_loyalty_joins_land_within_14_days_of_the_send(self):
        joined = self.after.set_index("customer_id")["loyalty_join_at"]
        for spec in [s for s in calendar() if s.kind == "gain_loyalty"]:
            day = pd.Timestamp(spec.sends[0].day)
            when = joined[self.result.joins[spec.campaign_id]]
            self.assertTrue(((when >= day) & (when < day + pd.Timedelta(days=14))).all(), spec.campaign_id)


class AnswerKeyTest(unittest.TestCase):
    """The campaign answer key from one scale 0.01 build."""

    @classmethod
    def setUpClass(cls):
        cfg = Config(scale=0.01)
        cls.t = build_truth(cfg, np.random.default_rng(cfg.seed), log=lambda *a: None)

    def test_every_prospects_customer_exists(self):
        self.assertTrue(set(self.t.prospect_customers["customer_id"]) <= set(self.t.customers["customer_id"]))

    def test_some_flights_add_customers_and_every_flight_loses_money(self):
        """Decision 2: at least one flight adds real customers, and spend per incremental customer is above
        their value for every flight (no incremental customers counts as infinite cost)."""
        flights = self.t.campaign_truth[self.t.campaign_truth["kind"] == "prospects"]
        self.assertGreater(flights["incremental_customers"].max(), 0)
        for f in flights.itertuples(index=False):
            cost = f.spend / f.incremental_customers if f.incremental_customers else np.inf
            self.assertGreater(cost, f.value_per_incremental_customer, f.campaign_id)
            self.assertGreater(f.spend, 0)

    def test_credited_purchases_name_real_campaigns(self):
        known = set(self.t.campaigns["campaign_id"])
        credited = set(self.t.orders["campaign_credit"].dropna()) | set(self.t.pos_lines["campaign_credit"].dropna())
        self.assertTrue(credited <= known)
        self.assertGreater(len(credited), 0)

    def test_engagement_flaws_are_present_and_bounded(self):
        ev = self.t.engagement_events
        sends = ev[ev["event_type"] == "send"]
        self.assertLessEqual(int(sends["after_unsubscribe"].sum()), POST_UNSUBSCRIBE_SENDS)
        wrong = set(sends.loc[sends["no_consent"], "campaign_id"])
        self.assertTrue(wrong <= {"CMP-06", "CMP-16"})
        opens = ev[ev["event_type"] == "open"]
        self.assertAlmostEqual(opens["machine_open"].mean(), 0.4, delta=0.1)

    def test_a_code_that_does_not_leak_is_only_used_by_its_treated(self):
        """BOXING25 does not leak: every order using it comes from a treated customer of CMP-10."""
        a = self.t.campaign_assignment
        treated = set(a[(a["campaign_id"] == "CMP-10") & (a["group"] == "treated")]["customer_id"])
        users = self.t.orders.loc[self.t.orders["coupon_code"] == "BOXING25", "customer_id"]
        self.assertTrue(set(users.dropna()) <= treated)
        self.assertFalse(users.isna().any())


if __name__ == "__main__":
    unittest.main()
