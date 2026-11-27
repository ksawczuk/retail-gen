"""Truth email events from the campaigns' sends: send, delivery, bounce, open (some by a mail client's machine),
click and unsubscribe, with response falling as customers are over-sent.

Called by build_truth after the demand engine has run, from the send log the email campaigns kept.
"""
import numpy as np
import pandas as pd

NS = "datetime64[ns]"
DELIVERY = 0.98
HARD_BOUNCE_SHARE = 1 / 3
OPEN = 0.38
MACHINE_OPEN_SHARE = 0.40
CLICK = 0.024
SEND_HOUR_UTC = 17
COLUMNS = ["campaign_id", "customer_id", "event_type", "event_ts", "machine_open", "bounce_type",
           "after_unsubscribe", "no_consent"]


def engagement_events(rng, days, customer_ids, sends, signup_sends):
    """Return one row per email event: campaign_id, customer_id, event_type, event_ts, machine_open,
    bounce_type, after_unsubscribe and no_consent."""
    parts = []
    # Email campaigns' sends, with fatigue and the planted wrong sends
    for s in sends:
        day = days[s.day_index].to_datetime64()
        parts.append(_events(rng, day, s.campaign_id, customer_ids[s.customers], s.fatigue, s.after_unsubscribe,
                             s.no_consent, s.unsubscribed))

    # Gain-loyalty sends, made before the engine ran, with no fatigue
    for day, campaign_id, ids in signup_sends:
        n = len(ids)
        none = np.zeros(n, bool)
        parts.append(_events(rng, day, campaign_id, np.asarray(ids), np.ones(n), none, none, none))
    blocks = [b for part in parts if part for b in part]
    out = pd.DataFrame({c: np.concatenate([b[c] for b in blocks]) if blocks else np.array([]) for c in COLUMNS})
    out["event_ts"] = out["event_ts"].astype(NS)
    return out.sort_values(["event_ts", "campaign_id"], kind="stable").reset_index(drop=True)


def _events(rng, day, campaign_id, ids, fatigue, after_unsubscribe, no_consent, unsubscribed):
    """The events of one send to `ids`, as a list of column blocks."""
    n = len(ids)
    if n == 0:
        return []
    sent = day + np.timedelta64(SEND_HOUR_UTC, "h") + (rng.random(n) * 3600).astype("timedelta64[s]")
    frames = [_frame(campaign_id, ids, "send", sent, after_unsubscribe, no_consent)]

    # Delivery or bounce
    delivered = rng.random(n) < DELIVERY
    arrive = sent + (rng.random(n) * 120).astype("timedelta64[s]")
    frames.append(_frame(campaign_id, ids[delivered], "delivery", arrive[delivered],
                         after_unsubscribe[delivered], no_consent[delivered]))
    bounced = ~delivered
    bounce = _frame(campaign_id, ids[bounced], "bounce", arrive[bounced], after_unsubscribe[bounced],
                    no_consent[bounced])
    bounce["bounce_type"] = np.where(rng.random(int(bounced.sum())) < HARD_BOUNCE_SHARE, "hard", "soft").astype(object)
    frames.append(bounce)

    # Opens: some by a mail client's machine, the rest by people, who open less when over-sent
    machine = delivered & (rng.random(n) < OPEN * MACHINE_OPEN_SHARE)
    human = delivered & ~machine & (rng.random(n) < OPEN * (1 - MACHINE_OPEN_SHARE) * fatigue)
    open_at = arrive + np.where(machine, rng.random(n) * 300,
                                rng.lognormal(np.log(3 * 3600), 1.2, n)).astype("timedelta64[s]")
    opened = machine | human
    opens = _frame(campaign_id, ids[opened], "open", open_at[opened], after_unsubscribe[opened], no_consent[opened])
    opens["machine_open"] = machine[opened].copy()
    frames.append(opens)

    # Clicks come from people who opened
    click = human & (rng.random(n) < CLICK / (OPEN * (1 - MACHINE_OPEN_SHARE)))
    click_at = open_at + (rng.random(n) * 600 + 5).astype("timedelta64[s]")
    frames.append(_frame(campaign_id, ids[click], "click", click_at[click], after_unsubscribe[click],
                         no_consent[click]))

    # Unsubscribes the send caused
    unsub_at = arrive + (rng.random(n) * 86400).astype("timedelta64[s]")
    frames.append(_frame(campaign_id, ids[unsubscribed], "unsubscribe", unsub_at[unsubscribed],
                         after_unsubscribe[unsubscribed], no_consent[unsubscribed]))
    return frames


def _frame(campaign_id, ids, event_type, when, after_unsubscribe, no_consent):
    """A block of events of one type, as columns of equal length."""
    n = len(ids)
    return {"campaign_id": np.full(n, campaign_id, dtype=object), "customer_id": np.asarray(ids, dtype=object),
            "event_type": np.full(n, event_type, dtype=object), "event_ts": np.asarray(when).astype(NS),
            "machine_open": np.zeros(n, bool), "bounce_type": np.full(n, None, dtype=object),
            "after_unsubscribe": np.asarray(after_unsubscribe, bool), "no_consent": np.asarray(no_consent, bool)}
