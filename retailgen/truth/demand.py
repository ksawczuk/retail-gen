"""The demand engine: which customers buy on which day, online and in store, from one model.

Built by build_truth; it draws every channel day by day so campaigns see what was bought before. generate_online and
generate_pos take its purchases, and generate_clickstream picks its signed-in browsers from it.
"""
from dataclasses import dataclass

import numpy as np

NS = "datetime64[ns]"
NONE = -1
OVERLAP_DAMPING = 0.7
NEVER = -1_000_000


@dataclass(frozen=True)
class Channel:
    """One way to buy: its base purchases per day and the share of purchases with no known customer."""

    name: str
    per_day: float
    guest_share: float


@dataclass
class Purchases:
    """One channel's drawn purchases: the day, the customer (NONE for none) and the credited campaign (None for a
    purchase no campaign caused)."""

    day_index: np.ndarray
    customer_index: np.ndarray
    campaign: np.ndarray


class DemandState:
    """What the engine has drawn so far, for campaigns to read: each customer's last purchase day."""

    def __init__(self, n_customers):
        """Start with nobody having bought."""
        self.last_purchase = np.full(n_customers, NEVER)

    def record(self, day_index, customer_index):
        """Note the day's purchases by known customers."""
        known = customer_index[customer_index >= 0]
        self.last_purchase[known] = day_index

    def days_since_purchase(self, day_index):
        """Days since each customer's last purchase (very large for customers who never bought)."""
        return day_index - self.last_purchase


class DemandModifier:
    """Changes customers' buying on a day. Campaigns (Story 771) implement it: start_day() lets a campaign send and
    pick its audience; lift() gives each customer's relative change in buying weight, or None on a quiet day."""

    campaign_id = None

    def start_day(self, day_index, state):
        """Called once at the start of each day, before any purchase is drawn."""

    def lift(self, day_index, state):
        """Each customer's relative lift for the day (0 none, 0.25 for +25%, negative for a pull-forward), or None."""
        return None


class DemandEngine:
    """Turns customers' activity, lifecycle, the seasonality and the campaigns into purchase events per day."""

    def __init__(self, rng, days, created_at, activity, lifecycle, seasonality, modifiers=()):
        """Keep the inputs. Customers must be sorted by `created_at`; arrays are in that order."""
        self._rng = rng
        self.days = days
        self._created = np.asarray(created_at).astype(NS)
        if (np.diff(self._created) < np.timedelta64(0, "ns")).any():
            raise ValueError("customers must be sorted by created_at")
        self._activity = np.asarray(activity, float)
        self._lifecycle = lifecycle
        self._seasonality = seasonality
        self._modifiers = list(modifiers)

    def expected_daily(self, channel):
        """The expected purchases per day for a channel with no campaign: its base rate times the seasonality."""
        return channel.per_day * self._seasonality.shared()

    def base_weights(self, day_index):
        """Each customer's buying weight on a day with no campaign: activity times lifecycle level, zero for
        customers who had not signed up before the day started."""
        day = self.days[day_index].to_datetime64()
        signed_up = self._created < day
        return np.where(signed_up, self._activity * self._lifecycle.factor(day), 0.0)

    def campaign_factor(self, day_index, state):
        """Combine the modifiers' lifts for a day: returns (factor per customer, credited modifier position per
        customer or NONE, chance a purchase is incremental). The biggest lift counts in full, the rest are damped."""
        lifts = [(k, m.lift(day_index, state)) for k, m in enumerate(self._modifiers)]
        lifts = [(k, lift) for k, lift in lifts if lift is not None]
        n = len(self._activity)
        if not lifts:
            return np.ones(n), np.full(n, NONE), np.zeros(n)

        # Positive lifts: the largest in full, every other one damped; negative lifts add as they are
        stack = np.vstack([lift for _, lift in lifts])
        positive = np.clip(stack, 0, None)
        ordered = -np.sort(-positive, axis=0)
        total_up = ordered[0] + OVERLAP_DAMPING * ordered[1:].sum(axis=0)
        total_down = np.clip(stack, None, 0).sum(axis=0)
        factor = np.clip(1.0 + total_up + total_down, 0.0, None)

        # Credit a purchase above the baseline to the campaign with the largest lift
        top = np.array([k for k, _ in lifts])[np.argmax(positive, axis=0)]
        credit = np.where(positive.max(axis=0) > 0, top, NONE)
        incremental = np.where(factor > 1.0, (factor - 1.0) / np.maximum(factor, 1e-12), 0.0)
        return factor, credit, incremental

    def draw_all(self, channels):
        """Draw every channel's purchases day by day, letting campaigns act on what was bought before.
        Returns {channel name: Purchases}. Called once by build_truth."""
        state = DemandState(len(self._activity))
        expected = {c.name: self.expected_daily(c) for c in channels}
        parts = {c.name: ([], [], []) for c in channels}
        for d in range(len(self.days)):
            # Campaigns send and choose audiences, then the day's weights are set
            for modifier in self._modifiers:
                modifier.start_day(d, state)
            base = self.base_weights(d)
            factor, credit, incremental = self.campaign_factor(d, state)
            weights = base * factor
            ratio = weights.sum() / base.sum() if base.sum() > 0 else 1.0

            for channel in channels:
                # The day's total moves with the campaigns' net effect
                count = int(self._rng.poisson(expected[channel.name][d] * ratio))
                if count == 0:
                    continue

                # Guests, or everyone when no customer can buy yet, have no customer
                customers = np.full(count, NONE)
                known = (self._rng.random(count) >= channel.guest_share) & (weights.sum() > 0)
                if known.any():
                    customers[known] = self._pick(weights, int(known.sum()))

                # A purchase above a customer's baseline is credited to the campaign that caused it
                campaign = np.full(count, None, dtype=object)
                chance = np.where(customers >= 0, incremental[np.maximum(customers, 0)], 0.0)
                caused = self._rng.random(count) < chance
                for row in np.flatnonzero(caused):
                    campaign[row] = self._modifiers[credit[customers[row]]].campaign_id
                day_list, cust_list, camp_list = parts[channel.name]
                day_list.append(np.full(count, d))
                cust_list.append(customers)
                camp_list.append(campaign)
                state.record(d, customers)
        return {name: self._join(*lists) for name, lists in parts.items()}

    def draw(self, channel):
        """Draw one channel on its own: returns (day_index, customer_index)."""
        purchases = self.draw_all([channel])[channel.name]
        return purchases.day_index, purchases.customer_index

    def pick(self, day_index):
        """Pick one customer per entry of `day_index` by that day's base weights (NONE if nobody can buy).
        Called by the clickstream for signed-in browsing sessions."""
        day_index = np.asarray(day_index)
        out = np.full(len(day_index), NONE)
        for d in np.unique(day_index):
            rows = np.flatnonzero(day_index == d)
            weights = self.base_weights(int(d))
            if weights.sum() > 0:
                out[rows] = self._pick(weights, len(rows))
        return out

    def _pick(self, weights, count):
        """Draw `count` customer positions in proportion to the weights."""
        cumulative = np.cumsum(weights)
        return np.searchsorted(cumulative, self._rng.random(count) * cumulative[-1], side="right")

    @staticmethod
    def _join(day_list, cust_list, camp_list):
        """Concatenate a channel's daily parts into one Purchases."""
        if not day_list:
            return Purchases(np.array([], dtype=int), np.array([], dtype=int), np.array([], dtype=object))
        return Purchases(np.concatenate(day_list), np.concatenate(cust_list), np.concatenate(camp_list))
