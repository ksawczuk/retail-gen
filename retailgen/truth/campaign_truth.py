"""The answer key for the campaigns: what each one was, who it reached, and what it truly did.

Called by build_truth after the sales exist; also gives the online orders each promo code's audience.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .campaigns import CANVAS_LIFT, utm_tag


LIFT_KINDS = ("seasonal", "early_access", "newsletter", "reminder", "canvas")
HOLDOUT_REDEMPTION_SHARE = 0.03
OUTSIDE_REDEMPTION_SHARE = 0.06
SPEND_FLOOR_PER_CUSTOMER = 50.0
NEVER_SYNCED_SHARE = 0.10


@dataclass(frozen=True)
class CodeAudience:
    """Who a campaign's promo code was meant for, and whether it leaked to others."""

    treated: frozenset
    holdout: frozenset
    leaks: bool


def groups_by_campaign(ctx, customer_ids):
    """{campaign_id: {group: set of customer ids}} from the audiences the email campaigns recorded."""
    out = {}
    for campaign_id, group, idx, _ in ctx.assignments:
        out.setdefault(campaign_id, {}).setdefault(group, set()).update(customer_ids[idx].tolist())
    return out


def code_audiences(specs, groups):
    """{promo code: CodeAudience} for the seasonal campaigns that carry a code."""
    out = {}
    for spec in specs:
        if spec.kind == "seasonal" and spec.promo_code:
            g = groups.get(spec.campaign_id, {})
            holdout = g.get("holdout", set()) | g.get("holdout_contaminated", set())
            out[spec.promo_code] = CodeAudience(frozenset(g.get("treated", set())), frozenset(holdout),
                                                spec.code_leaks)
    return out


def campaigns_table(specs):
    """One row per campaign with its design: kind, sends, lifts, window, holdout and code."""
    rows = []
    for s in specs:
        rows.append({"campaign_id": s.campaign_id, "name": s.name, "kind": s.kind, "utm_campaign": utm_tag(s),
                     "sends": ",".join(x.day for x in s.sends), "send_lifts": ",".join(f"{x.lift:g}" for x in s.sends),
                     "window_days": s.window_days, "half_life_days": s.half_life, "pullback": s.pullback,
                     "pullback_days": s.pullback_days if s.pullback else 0, "holdout": s.holdout,
                     "promo_code": s.promo_code, "code_leaks": s.code_leaks, "lapsed_days": s.lapsed_days,
                     "categories": ",".join(s.categories), "parent_campaign": s.parent,
                     "flight_days": s.flight_days, "adds_customers": s.adds_customers})
    return pd.DataFrame(rows)


def assignment_table(ctx, customer_ids, days, signup):
    """One row per campaign, customer and group, with the day the customer was assigned."""
    parts = []
    for campaign_id, group, idx, day_index in ctx.assignments:
        if len(idx):
            parts.append(pd.DataFrame({"campaign_id": campaign_id, "customer_id": customer_ids[idx],
                                       "group": group, "assigned_day": days[day_index]}))
    for day, campaign_id, ids in signup.sends:
        parts.append(pd.DataFrame({"campaign_id": campaign_id, "customer_id": ids, "group": "treated",
                                   "assigned_day": pd.Timestamp(day)}))
    if not parts:
        return pd.DataFrame(columns=["campaign_id", "customer_id", "group", "assigned_day"])
    out = pd.concat(parts, ignore_index=True)
    return out.drop_duplicates(["campaign_id", "customer_id", "group"]).reset_index(drop=True)


def truth_table(rng, specs, ctx, signup, purchases, days, customer_ids, orders, pos_lines):
    """One row per campaign with what it truly did: audience sizes, purchases in its window, incremental
    purchases credited to it and the realized lift; comebacks, joins, and each Prospects flight's economics."""
    groups = groups_by_campaign(ctx, customer_ids)
    day_idx = np.concatenate([p.day_index for p in purchases.values()])
    cust = np.concatenate([p.customer_index for p in purchases.values()])
    credit = np.concatenate([p.campaign for p in purchases.values()])
    buyer = pd.Series(np.where(cust >= 0, customer_ids[np.maximum(cust, 0)], None))
    send_day = {s.campaign_id: [int(days.get_indexer([pd.Timestamp(x.day)])[0]) for x in s.sends] for s in specs}
    fatigue = _fatigue_by_campaign(ctx)
    redemptions = _code_redemptions_by_group(specs, groups, orders)

    rows = []
    for s in specs:
        row = {"campaign_id": s.campaign_id, "kind": s.kind,
               "nominal_lift": s.sends[0].lift if s.sends else CANVAS_LIFT}
        g = groups.get(s.campaign_id, {})
        row["treated_customers"] = len(g.get("treated", set()))
        row["holdout_customers"] = len(g.get("holdout", set()) | g.get("holdout_contaminated", set()))
        row["contaminated_holdout_customers"] = len(groups.get(s.campaign_id + "R", {}).get("contaminating", set()))
        row.update(fatigue.get(s.campaign_id, {}))
        row.update(redemptions.get(s.campaign_id, {}))

        # Lift campaigns: purchases by the treated in the window, the credited ones, and the realized lift
        if s.kind in LIFT_KINDS:
            incremental = int((credit == s.campaign_id).sum())
            by_treated = buyer.isin(g.get("treated", set())).to_numpy()
            if s.kind == "canvas" or s.kind == "newsletter":
                window_buys = _per_send_window_purchases(ctx, s, day_idx, cust)
            else:
                lo, hi = send_day[s.campaign_id][0], send_day[s.campaign_id][-1] + s.window_days
                in_window = (day_idx >= lo) & (day_idx < hi) & by_treated
                window_buys = int(in_window.sum())
            row["treated_window_purchases"] = window_buys
            row["incremental_purchases"] = incremental
            base = window_buys - incremental
            row["realized_lift"] = incremental / base if base > 0 else np.nan
            if s.pullback:
                lo = send_day[s.campaign_id][0] + s.window_days
                after = (day_idx >= lo) & (day_idx < lo + s.pullback_days) & by_treated
                row["pullback_purchases_lost"] = int(round(after.sum() * s.pullback / (1 - s.pullback)))
                row["net_lift"] = (incremental - row["pullback_purchases_lost"]) / base if base > 0 else np.nan
        elif s.kind == "winback":
            row["incremental_comebacks"] = ctx.reactivations.get(s.campaign_id, 0)
        elif s.kind == "gain_loyalty":
            row["treated_customers"] = sum(len(ids) for _, cid, ids in signup.sends if cid == s.campaign_id)
            row["incremental_joins"] = len(signup.joins.get(s.campaign_id, []))
        elif s.kind == "prospects":
            row.update(_flight_economics(rng, s, signup, orders, pos_lines))
        rows.append(row)
    table = pd.DataFrame(rows)

    # Price the flights that add no customers like the others
    flights = table["kind"] == "prospects"
    paid = table.loc[flights & (table["incremental_customers"] > 0), "spend"]
    typical = float(paid.mean()) if len(paid) else 5_000.0
    idle = flights & (table["incremental_customers"] == 0)
    table.loc[idle, "spend"] = np.round(typical * rng.uniform(0.6, 1.2, int(idle.sum())), 2)
    return table


def _per_send_window_purchases(ctx, spec, day_idx, cust):
    """Purchases by each recipient inside their own send's window, for campaigns that send to a new audience each
    time; a window ends early where the same customer's next send begins, so no purchase counts twice."""
    starts = [(idx, np.full(len(idx), day)) for cid, group, idx, day in ctx.assignments
              if cid == spec.campaign_id and group == "treated" and len(idx)]
    if not starts:
        return 0
    who = np.concatenate([i for i, _ in starts]).astype(np.int64)
    when = np.concatenate([d for _, d in starts]).astype(np.int64)

    # Each window runs to the window length or to the customer's next send, whichever is first
    order = np.lexsort((when, who))
    who, when = who[order], when[order]
    nxt = np.where(np.r_[who[1:] == who[:-1], False], np.r_[when[1:], 0], when + spec.window_days)
    end = np.minimum(when + spec.window_days, nxt)

    # Count purchases per (customer, day range) with one sorted key
    known = cust >= 0
    keys = np.sort(cust[known].astype(np.int64) * 100_000 + day_idx[known].astype(np.int64))
    lo = np.searchsorted(keys, who * 100_000 + when, side="left")
    hi = np.searchsorted(keys, who * 100_000 + end, side="left")
    return int((hi - lo).sum())


def _fatigue_by_campaign(ctx):
    """Per campaign: sends, the mean response factor, and the share of sends to someone over-sent (more than four
    sends in 30 days), plus sends after an unsubscribe and without consent."""
    out = {}
    for s in ctx.sends:
        row = out.setdefault(s.campaign_id, {"sends": 0, "_factor": 0.0, "_over": 0, "sends_after_unsubscribe": 0,
                                             "sends_without_consent": 0})
        row["sends"] += len(s.customers)
        row["_factor"] += float(s.fatigue.sum())
        row["_over"] += int((s.fatigue < 1.0).sum())
        row["sends_after_unsubscribe"] += int(s.after_unsubscribe.sum())
        row["sends_without_consent"] += int(s.no_consent.sum())
    for row in out.values():
        n = max(row["sends"], 1)
        row["mean_fatigue_factor"] = round(row.pop("_factor") / n, 4)
        row["over_sent_share"] = round(row.pop("_over") / n, 4)
    return out


def _code_redemptions_by_group(specs, groups, orders):
    """Per campaign with a code: online redemptions by its treated, its holdout, and everyone else."""
    out = {}
    for s in specs:
        if not s.promo_code:
            continue
        g = groups.get(s.campaign_id, {})
        holdout = g.get("holdout", set()) | g.get("holdout_contaminated", set())
        users = orders.loc[orders["coupon_code"] == s.promo_code, "customer_id"]
        treated = users.isin(g.get("treated", set()))
        held = users.isin(holdout)
        out[s.campaign_id] = {"redemptions_treated": int(treated.sum()), "redemptions_holdout": int(held.sum()),
                              "redemptions_outside": int((~treated & ~held).sum())}
    return out


def _flight_economics(rng, spec, signup, orders, pos_lines):
    """A flight's pulled-forward and new customers, what the new ones spent, and its spend."""
    added = signup.added.get(spec.campaign_id, [])
    value = 0.0
    if added:
        online = orders[orders["customer_id"].isin(added)]
        store = pos_lines[pos_lines["true_customer_id"].isin(added) & ~pos_lines["is_return"]]
        total = float((online["subtotal"] - online["discount_total"]).sum() +
                      (store["qty"] * store["unit_price"] - store["line_discount"]).sum())
        value = total / len(added)
    spend = np.nan
    if added:
        spend = round(len(added) * max(value, SPEND_FLOOR_PER_CUSTOMER) * float(rng.uniform(2.0, 3.0)), 2)
    return {"pulled_forward_customers": len(signup.moved.get(spec.campaign_id, [])),
            "incremental_customers": len(added), "value_per_incremental_customer": round(value, 2),
            "spend": spend}


def email_clicks(engagement, campaigns):
    """Every email click with its customer, time and the campaign's tag; read by the clickstream."""
    clicks = engagement[engagement["event_type"] == "click"]
    tags = campaigns.set_index("campaign_id")["utm_campaign"]
    return pd.DataFrame({"customer_id": clicks["customer_id"].to_numpy(), "click_ts": clicks["event_ts"].to_numpy(),
                         "utm_campaign": clicks["campaign_id"].map(tags).to_numpy()})


def prospect_tags(prospects, campaigns):
    """Each customer a Prospects flight brought or pulled forward, with the flight's tag."""
    tags = campaigns.set_index("campaign_id")["utm_campaign"]
    return pd.DataFrame({"customer_id": prospects["customer_id"].to_numpy(),
                         "utm_campaign": prospects["campaign_id"].map(tags).to_numpy()})


def consent_sync(rng, engagement):
    """When each email unsubscribe reached the CRM: 0 to 2 days later, or never for 10% of them."""
    unsub = engagement[engagement["event_type"] == "unsubscribe"].drop_duplicates("customer_id")
    n = len(unsub)
    lag = pd.to_timedelta(rng.random(n) * 2 * 86400, unit="s")
    synced = (unsub["event_ts"] + lag).where(rng.random(n) >= NEVER_SYNCED_SHARE)
    return pd.DataFrame({"customer_id": unsub["customer_id"].to_numpy(),
                         "unsubscribed_at": unsub["event_ts"].to_numpy(), "crm_synced_at": synced.to_numpy()})


def prospect_customers_table(signup):
    """One row per customer a Prospects flight touched: pulled forward into the flight, or brought in new."""
    rows = [(cid, c, "pulled_forward") for cid, ids in signup.moved.items() for c in ids]
    rows += [(cid, c, "incremental") for cid, ids in signup.added.items() for c in ids]
    return pd.DataFrame(rows, columns=["campaign_id", "customer_id", "effect"])
