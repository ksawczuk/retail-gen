"""The campaigns that act on signups before any purchase is drawn: gain-loyalty emails and the Prospects flights.

Called by build_truth right after the customers are generated; it returns changed customers and addresses and a
record of what each campaign truly did.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .campaigns import GAIN_LOYALTY_DAYS, PROSPECT_EXTRA, PROSPECT_REACH_DAYS
from .customers import add_customers

NS = "datetime64[ns]"


@dataclass
class SignupResult:
    """What the signup campaigns did: gain-loyalty sends and joins, Prospects moves and new customers."""

    sends: list = field(default_factory=list)
    joins: dict = field(default_factory=dict)
    moved: dict = field(default_factory=dict)
    added: dict = field(default_factory=dict)


def apply_signup_campaigns(cfg, rng, customers, addresses, specs):
    """Run the gain-loyalty and Prospects campaigns on the customers; returns (customers, addresses, result)."""
    result = SignupResult()
    customers = customers.copy()
    cutover = np.datetime64(cfg.history_end + pd.Timedelta(days=1), "ns")
    for spec in [s for s in specs if s.kind == "gain_loyalty"]:
        customers = _gain_loyalty(rng, customers, spec, result)
    for spec in [s for s in specs if s.kind == "prospects"]:
        customers, addresses = _prospects(cfg, rng, customers, addresses, spec, cutover, result)
    customers = customers.sort_values("created_at", kind="stable").reset_index(drop=True)
    return customers, addresses, result


def _gain_loyalty(rng, customers, spec, result):
    """Email opted-in non-members; a share join within 14 days who otherwise would have joined later or never."""
    day = np.datetime64(pd.Timestamp(spec.sends[0].day), "ns")
    created = customers["created_at"].to_numpy().astype(NS)
    joined = customers["loyalty_join_at"].to_numpy().astype(NS)

    # The audience: opted-in, signed up, not yet a member, not staff
    non_member = np.isnat(joined) | (joined >= day)
    audience = np.flatnonzero(customers["marketing_opt_in"].to_numpy() & (created < day) & non_member
                              & ~customers["is_employee"].to_numpy())
    result.sends.append((day, spec.campaign_id, customers["customer_id"].to_numpy()[audience]))

    # Some join in the next 14 days; a customer who was never going to join gets a number now
    joins = audience[rng.random(len(audience)) < spec.sends[0].lift]
    when = day + (rng.random(len(joins)) * GAIN_LOYALTY_DAYS * 86400).astype("timedelta64[s]")
    customers.loc[joins, "loyalty_join_at"] = when.astype(NS)
    never = joins[customers.loc[joins, "loyalty_number"].isna().to_numpy()]
    taken = set(customers["loyalty_number"].dropna())
    numbers = []
    while len(numbers) < len(never):
        candidate = f"L{rng.integers(100_000_000, 999_999_999)}"
        if candidate not in taken:
            taken.add(candidate)
            numbers.append(candidate)
    customers.loc[never, "loyalty_number"] = numbers
    customers.loc[never, "loyalty_tier"] = "Bronze"
    result.joins[spec.campaign_id] = customers["customer_id"].to_numpy()[joins].tolist()
    return customers


def _prospects(cfg, rng, customers, addresses, spec, cutover, result):
    """A paid flight: pulls some later signups forward into the flight (same side of the cut-over), and for the
    flights that work, adds new customers who would never have come."""
    start = np.datetime64(pd.Timestamp(spec.sends[0].day), "ns")
    end = start + np.timedelta64(spec.flight_days, "D")
    created = customers["created_at"].to_numpy().astype(NS)
    in_flight = int(((created >= start) & (created < end)).sum())

    # Pull forward: signups due within 60 days after the flight move into it, never across the cut-over
    span = (end - start) / np.timedelta64(1, "s")
    later = np.flatnonzero((created >= end) & (created < end + np.timedelta64(PROSPECT_REACH_DAYS, "D")))
    later = later[(created[later] >= cutover) == (start >= cutover)]
    k = min(len(later), int(round(in_flight * spec.sends[0].lift)))
    moved = rng.choice(later, size=k, replace=False) if k else np.array([], dtype=int)
    new_time = (start + (rng.random(k) * span).astype("timedelta64[s]")).astype(NS)
    at_signup = customers.loc[moved, "loyalty_join_at"].to_numpy() == created[moved]
    customers.loc[moved, "created_at"] = new_time
    customers.loc[moved[at_signup], "loyalty_join_at"] = new_time[at_signup]
    moved_ids = customers["customer_id"].to_numpy()[moved]
    shift = dict(zip(moved_ids, new_time))
    hit = addresses["customer_id"].isin(shift)
    addresses.loc[hit, "created_at"] = addresses.loc[hit, "customer_id"].map(shift).astype(NS)
    result.moved[spec.campaign_id] = moved_ids.tolist()

    # The flights that work also bring new customers, signed up during the flight
    if spec.adds_customers:
        n_new = max(1, int(round(in_flight * PROSPECT_EXTRA)))
        times = (start + (rng.random(n_new) * span).astype("timedelta64[s]")).astype(NS)
        customers, addresses, new_ids = add_customers(cfg, rng, customers, addresses, times)
        result.added[spec.campaign_id] = new_ids
    else:
        result.added[spec.campaign_id] = []
    return customers, addresses
