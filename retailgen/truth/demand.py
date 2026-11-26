"""The demand engine: which customers buy on which day, online and in store, from one model.

Built by build_truth; generate_online and generate_pos draw their purchases from it, and generate_clickstream picks
its signed-in browsers from it.
"""
from dataclasses import dataclass

import numpy as np

NS = "datetime64[ns]"
NONE = -1


@dataclass(frozen=True)
class Channel:
    """One way to buy: its base purchases per day and the share of purchases with no known customer."""

    name: str
    per_day: float
    guest_share: float


class DemandModifier:
    """Changes customers' buying weights on a day. The engine applies each one in turn; campaigns (Story 771)
    are implementations. This base changes nothing."""

    def weights(self, channel, day_index, weights):
        """Return the adjusted weights for one channel and day (same length as `weights`)."""
        return weights


class DemandEngine:
    """Turns customers' activity, lifecycle and the seasonality into purchase events per day."""

    def __init__(self, rng, days, created_at, activity, lifecycle, seasonality, modifiers=()):
        """Keep the inputs. Customers must be sorted by `created_at`; arrays are in that order."""
        self._rng = rng
        self.days = days
        self._created = np.asarray(created_at).astype(NS)
        self._activity = np.asarray(activity, float)
        self._lifecycle = lifecycle
        self._seasonality = seasonality
        self._modifiers = list(modifiers)

    def expected_daily(self, channel):
        """The expected purchases per day for a channel: its base rate times the seasonality."""
        return channel.per_day * self._seasonality.shared()

    def base_weights(self, day_index):
        """Each customer's buying weight on a day before any modifier: activity times lifecycle level,
        zero for customers who had not signed up before the day started."""
        day = self.days[day_index].to_datetime64()
        signed_up = self._created < day
        return np.where(signed_up, self._activity * self._lifecycle.factor(day), 0.0)

    def weights(self, channel, day_index, base=None):
        """Each customer's buying weight on a day after every modifier (from `base` when already computed)."""
        weights = self.base_weights(day_index) if base is None else base
        for modifier in self._modifiers:
            weights = modifier.weights(channel, day_index, weights)
        return weights

    def draw(self, channel):
        """Draw a channel's purchases: returns (day_index, customer_index) arrays, NONE for a purchase with
        no known customer. Called once per channel."""
        expected = self.expected_daily(channel)
        day_parts, cust_parts = [], []
        for d in range(len(self.days)):
            # Scale the day's total by how much the modifiers raised or lowered the weights
            base = self.base_weights(d)
            weights = self.weights(channel, d, base)
            ratio = weights.sum() / base.sum() if base.sum() > 0 else 1.0
            count = int(self._rng.poisson(expected[d] * ratio))
            if count == 0:
                continue

            # Guests, or everyone when no customer can buy yet, have no customer
            customers = np.full(count, NONE)
            known = (self._rng.random(count) >= channel.guest_share) & (weights.sum() > 0)
            if known.any():
                customers[known] = self._pick(weights, int(known.sum()))
            day_parts.append(np.full(count, d))
            cust_parts.append(customers)
        if not day_parts:
            return np.array([], dtype=int), np.array([], dtype=int)
        return np.concatenate(day_parts), np.concatenate(cust_parts)

    def pick(self, channel, day_index):
        """Pick one customer per entry of `day_index`, weighted by that day's weights (NONE if nobody can buy).
        Called by the clickstream for signed-in browsing sessions."""
        day_index = np.asarray(day_index)
        out = np.full(len(day_index), NONE)
        for d in np.unique(day_index):
            rows = np.flatnonzero(day_index == d)
            weights = self.weights(channel, int(d))
            if weights.sum() > 0:
                out[rows] = self._pick(weights, len(rows))
        return out

    def _pick(self, weights, count):
        """Draw `count` customer positions in proportion to the weights."""
        cumulative = np.cumsum(weights)
        return np.searchsorted(cumulative, self._rng.random(count) * cumulative[-1], side="right")
