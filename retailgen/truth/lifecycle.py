"""Each customer's buying life (churn, fading, coming back, basket size, category taste) and loyalty membership.

Built by build_truth after the customers exist; the demand engine and basket builder read it day by day.
"""
import numpy as np
import pandas as pd

MONTHLY_CHURN = 0.015
CHURN_ACTIVITY_POWER = -0.3
DAYS_PER_MONTH = 30.44
DECAY_SHARE = 0.30
DECAY_HALF_LIFE_DAYS = 120.0
YEARLY_REACTIVATION = 0.06
REACTIVATED_LEVEL = 0.5
MAX_DAYS = 36_500.0
BASKET_SIGMA = 0.3
PREFERENCE_ALPHA = 0.5
JOIN_AT_SIGNUP = 0.35
MEMBER_SHARE = 0.65
GOLD_SHARE = 0.12
SILVER_SHARE = 0.28

NS = "datetime64[ns]"
DAY = np.timedelta64(1, "D")


class CustomerLifecycle:
    """Per-customer arrays, in the customers' row order: churn time, fade or stop, comeback time, basket size
    multiplier and category preferences."""

    def __init__(self, churn_at, decays, reactivate_at, basket_mult, preferences):
        """Keep the arrays; build() draws them."""
        self.churn_at = churn_at
        self.decays = decays
        self.reactivate_at = reactivate_at
        self.basket_mult = basket_mult
        self.preferences = preferences

    @classmethod
    def build(cls, rng, customers, n_categories):
        """Draw every customer's lifecycle from their signup time and activity.
        Called once by build_truth, right after the customers are generated."""
        n = len(customers)
        created = customers["created_at"].to_numpy().astype(NS)
        activity = customers["activity"].to_numpy(float)

        # Churn: a monthly hazard, higher for low-activity customers, averaging MONTHLY_CHURN
        shape = (activity / activity.mean()) ** CHURN_ACTIVITY_POWER
        daily_hazard = MONTHLY_CHURN * shape / shape.mean() / DAYS_PER_MONTH
        churn_after = np.minimum(rng.exponential(1.0 / daily_hazard), MAX_DAYS)
        churn_at = created + (churn_after * 86400).astype("timedelta64[s]")

        # Some churners fade instead of stopping; some come back later at a lower level
        decays = rng.random(n) < DECAY_SHARE
        react_after = np.minimum(rng.exponential(365.0 / YEARLY_REACTIVATION, n), MAX_DAYS)
        reactivate_at = churn_at + (react_after * 86400).astype("timedelta64[s]")

        # Basket size multiplier (mean 1) and category preferences (the top three hold about two-thirds)
        basket_mult = rng.lognormal(-BASKET_SIGMA ** 2 / 2, BASKET_SIGMA, n)
        preferences = rng.dirichlet(np.full(n_categories, PREFERENCE_ALPHA), size=n)
        return cls(churn_at.astype(NS), decays, reactivate_at.astype(NS), basket_mult, preferences)

    def factor(self, day):
        """Each customer's buying level on a day, from 1 (active) down to 0 (gone).
        Called by the demand engine for every day it draws."""
        day = np.datetime64(day, "ns")
        level = np.ones(len(self.churn_at))

        # After churn: stoppers drop to 0, faders halve every DECAY_HALF_LIFE_DAYS
        since = (day - self.churn_at) / DAY
        churned = since >= 0
        level[churned & ~self.decays] = 0.0
        fading = churned & self.decays
        level[fading] = 0.5 ** (since[fading] / DECAY_HALF_LIFE_DAYS)

        # A churner who has come back buys at the reactivated level
        level[churned & (day >= self.reactivate_at)] = REACTIVATED_LEVEL
        return level


def loyalty_join_dates(rng, created_at, is_member, end):
    """When each member joined the loyalty program: at signup for some, otherwise any time up to `end`.
    Called by generate_customers; non-members get NaT."""
    created = pd.to_datetime(created_at).to_numpy().astype(NS)
    n = len(created)

    # A share of all customers join at signup; the other members join between signup and the end
    at_signup = rng.random(n) < JOIN_AT_SIGNUP / MEMBER_SHARE
    span = np.maximum((np.datetime64(end, "ns") - created) / np.timedelta64(1, "s"), 0)
    later = created + (rng.random(n) * span).astype("timedelta64[s]")
    joined = np.where(at_signup, created, later).astype(NS)
    return np.where(np.asarray(is_member), joined, np.datetime64("NaT")).astype(NS)


def tiers_by_activity(activity, is_member):
    """Loyalty tier per customer from activity rank among members: top Gold, next Silver, rest Bronze.
    Called by generate_customers; non-members get None."""
    activity = np.asarray(activity, float)
    member = np.asarray(is_member, bool)
    tiers = np.full(len(activity), None, dtype=object)
    if not member.any():
        return tiers

    # Rank members by activity, highest first, and cut at the Gold and Silver shares
    idx = np.flatnonzero(member)
    order = idx[np.argsort(-activity[idx], kind="stable")]
    n_gold = int(round(len(order) * GOLD_SHARE))
    n_silver = int(round(len(order) * SILVER_SHARE))
    tiers[order] = "Bronze"
    tiers[order[:n_gold]] = "Gold"
    tiers[order[n_gold:n_gold + n_silver]] = "Silver"
    return tiers
