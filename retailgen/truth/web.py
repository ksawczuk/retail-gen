"""Clean truth for web analytics: sessions and events, tied to real online orders."""
import numpy as np
import pandas as pd

from .. import reference as ref
from ..util import bounded_weighted_pick, seconds_in_day
from .masterdata import price_lookup
from .demand import NONE

NS = "datetime64[ns]"
HOURS = [1, .6, .4, .3, .3, .5, 1, 1.5, 2, 2.5, 3, 3, 3, 3, 3, 3.5, 4, 4.5, 5, 5.5, 5, 4, 3, 2]


def _email_sessions(cfg, rng, clicks):
    """One session per email click inside the clickstream window: a landing page view and a product view.
    Returns (sessions, events)."""
    empty_sessions = pd.DataFrame(columns=["session_id", "order_id", "customer_id", "start", "channel", "utm_campaign"])
    empty_events = pd.DataFrame(columns=["session_id", "event_type", "event_ts", "page", "sku", "order_id"])
    if clicks is None or not len(clicks):
        return empty_sessions, empty_events
    c = clicks[clicks["click_ts"] >= cfg.clickstream_start].reset_index(drop=True)
    if not len(c):
        return empty_sessions, empty_events
    start = (c["click_ts"] + pd.to_timedelta(rng.integers(1, 6, len(c)), unit="s")).astype(NS)
    sessions = pd.DataFrame({"session_id": _hex(rng, len(c), 8), "order_id": None, "customer_id": c["customer_id"],
                             "start": start, "channel": "web", "utm_campaign": c["utm_campaign"]})
    events = pd.DataFrame({"session_id": sessions["session_id"], "event_type": "page_view", "event_ts": start,
                           "page": "/c/" + c["utm_campaign"].astype(str), "sku": None, "order_id": None})
    return sessions, events


def _tag_first_sessions(sessions, prospect_tags):
    """Give each Prospects customer's earliest signed-in session the paid-agency tags (in place)."""
    if prospect_tags is None or not len(prospect_tags):
        return
    tags = prospect_tags.drop_duplicates("customer_id").set_index("customer_id")["utm_campaign"]
    known = sessions[sessions["customer_id"].isin(tags.index) & sessions["utm_campaign"].isna()]
    first = known.sort_values("start").drop_duplicates("customer_id")
    sessions.loc[first.index, ["utm_source", "utm_medium"]] = ["agency", "paid"]
    sessions.loc[first.index, "utm_campaign"] = first["customer_id"].map(tags).to_numpy()


def _hex(rng, n, nbytes):
    raw = rng.bytes(n * nbytes)
    h = raw.hex()
    return [h[i * 2 * nbytes:(i + 1) * 2 * nbytes] for i in range(n)]


def generate_clickstream(cfg, rng, orders, lines, customers, products, price_history, engine, email_clicks=None,
                         prospect_tags=None):
    """Events from clickstream_start onward. 65% of online orders were tracked (consent); the
    rest of the traffic is browsing sessions that never bought."""
    o = orders[(orders["order_ts"] >= cfg.clickstream_start)]
    o = o[rng.random(len(o)) < 0.65].reset_index(drop=True)
    l = lines[lines["order_id"].isin(o["order_id"])]
    sess_conv = pd.DataFrame({
        "session_id": _hex(rng, len(o), 8), "order_id": o["order_id"], "order_ts": o["order_ts"],
        "customer_id": np.where(rng.random(len(o)) < 0.8, o["customer_id"], None),
        "start": (o["order_ts"] - pd.to_timedelta(rng.integers(180, 2400, len(o)), unit="s")).astype(NS),
        "channel": o["channel"],
    })
    ev = []
    ev.append(pd.DataFrame({"session_id": sess_conv["session_id"], "event_type": "page_view",
                            "event_ts": sess_conv["start"], "page": "/", "sku": None, "order_id": None}))
    lj = l.merge(sess_conv[["session_id", "order_id", "start", "order_ts"]], on="order_id")
    span = (lj["order_ts"] - lj["start"]).dt.total_seconds().to_numpy()
    f1 = rng.uniform(0.05, 0.5, len(lj))
    f2 = np.minimum(f1 + rng.uniform(0.02, 0.3, len(lj)), 0.9)
    ev.append(pd.DataFrame({"session_id": lj["session_id"], "event_type": "product_view",
                            "event_ts": lj["start"] + pd.to_timedelta(span * f1, unit="s"),
                            "page": "/p/" + lj["sku"], "sku": lj["sku"], "order_id": None}))
    ev.append(pd.DataFrame({"session_id": lj["session_id"], "event_type": "add_to_cart",
                            "event_ts": lj["start"] + pd.to_timedelta(span * f2, unit="s"),
                            "page": "/p/" + lj["sku"], "sku": lj["sku"], "order_id": None}))
    ev.append(pd.DataFrame({"session_id": sess_conv["session_id"], "event_type": "begin_checkout",
                            "event_ts": sess_conv["order_ts"] - pd.to_timedelta(rng.integers(30, 120, len(o)), unit="s"),
                            "page": "/checkout", "sku": None, "order_id": None}))
    ev.append(pd.DataFrame({"session_id": sess_conv["session_id"], "event_type": "purchase",
                            "event_ts": sess_conv["order_ts"], "page": "/checkout/confirmation",
                            "sku": None, "order_id": sess_conv["order_id"]}))

    # Browsing-only sessions.
    days = pd.date_range(cfg.clickstream_start, cfg.increment_end, freq="D")
    per_day = o.groupby(o["order_ts"].dt.normalize()).size().reindex(days, fill_value=0).to_numpy()
    nc = rng.poisson(np.maximum(per_day * 0.8, 1))
    nday = np.repeat(days.to_numpy().astype(NS), nc)
    m = len(nday)
    start = (nday + seconds_in_day(rng, m, HOURS).astype("timedelta64[s]")).astype(NS)
    # Signed-in browsers are customers the demand engine would pick that day
    signed_in = rng.random(m) < 0.2
    day_index = ((start.astype("datetime64[D]") - engine.days[0].to_datetime64().astype("datetime64[D]"))
                 // np.timedelta64(1, "D")).astype(int)
    browser = np.full(m, NONE)
    browser[signed_in] = engine.pick(day_index[signed_in])
    ids = customers["customer_id"].to_numpy()
    sess_nc = pd.DataFrame({"session_id": _hex(rng, m, 8), "order_id": None,
                            "customer_id": np.where(browser >= 0, ids[np.maximum(browser, 0)], None),
                            "start": start, "channel": rng.choice(["web", "app"], size=m, p=[.65, .35])})
    ev.append(pd.DataFrame({"session_id": sess_nc["session_id"], "event_type": "page_view",
                            "event_ts": sess_nc["start"], "page": "/", "sku": None, "order_id": None}))
    nv = rng.poisson(1.3, m)
    si = np.repeat(np.arange(m), nv)
    prods = products[~products["pim_excluded"]].sort_values("launched_at").reset_index(drop=True)
    pub = np.maximum(np.searchsorted(prods["launched_at"].to_numpy(), start[si], side="right"), 1)
    skus = prods["sku"].to_numpy()[bounded_weighted_pick(rng, np.cumsum(prods["popularity"].to_numpy()), pub)]
    vts = start[si] + (np.arange(len(si)) - np.searchsorted(si, si)).astype("timedelta64[s]") * 45 + \
        rng.integers(5, 40, len(si)).astype("timedelta64[s]")
    pv = pd.DataFrame({"session_id": sess_nc["session_id"].to_numpy()[si], "event_type": "product_view",
                       "event_ts": vts.astype(NS), "page": ["/p/" + s for s in skus], "sku": skus, "order_id": None})
    ev.append(pv)
    atc = pv[rng.random(len(pv)) < 0.15].copy()
    atc["event_type"] = "add_to_cart"
    atc["event_ts"] = atc["event_ts"] + pd.to_timedelta(rng.integers(5, 60, len(atc)), unit="s")
    ev.append(atc)

    events = pd.concat(ev, ignore_index=True)
    events["event_ts"] = events["event_ts"].astype(NS)
    # Email clicks land on the site in their own session, carrying the campaign's tag
    sess_mail, mail_events = _email_sessions(cfg, rng, email_clicks)
    events = pd.concat([events, mail_events], ignore_index=True)
    events["event_ts"] = events["event_ts"].astype(NS)
    sessions = pd.concat([sess_conv.drop(columns=["order_ts"]), sess_nc, sess_mail], ignore_index=True)
    dev = rng.integers(0, len(ref.DEVICES), len(sessions))
    sessions["device_type"] = [ref.DEVICES[i][0] for i in dev]
    sessions["os"] = [ref.DEVICES[i][1] for i in dev]
    sessions["browser"] = np.where(sessions["channel"] == "app", "LarchwoodApp", [ref.DEVICES[i][2] for i in dev])
    sessions["anonymous_id"] = _hex(rng, len(sessions), 12)
    utm = rng.integers(0, len(ref.UTM_SOURCES), len(sessions))
    has_utm = rng.random(len(sessions)) < 0.4
    sessions["utm_source"] = np.where(has_utm, [ref.UTM_SOURCES[i][0] for i in utm], None)
    sessions["utm_medium"] = np.where(has_utm, [ref.UTM_SOURCES[i][1] for i in utm], None)
    sessions["utm_campaign"] = None

    # Email sessions say where they came from; a Prospects customer's first session carries the flight's tag
    mail = sessions["session_id"].isin(set(sess_mail["session_id"]))
    sessions.loc[mail, ["utm_source", "utm_medium"]] = ["newsletter", "email"]
    sessions.loc[mail, "utm_campaign"] = sess_mail.set_index("session_id").loc[sessions.loc[mail, "session_id"],
                                                                               "utm_campaign"].to_numpy()
    _tag_first_sessions(sessions, prospect_tags)
    events = events.merge(sessions.drop(columns=["order_id", "start"]), on="session_id")
    priced = events["sku"].notna().to_numpy()
    events["price"] = np.nan
    events.loc[priced, "price"] = price_lookup(price_history, events.loc[priced, "sku"].to_numpy(),
                                               events.loc[priced, "event_ts"].to_numpy())
    events = events[events["event_ts"] >= cfg.clickstream_start].sort_values("event_ts").reset_index(drop=True)
    events.insert(0, "event_id", _hex(rng, len(events), 16))
    events["is_bot"] = False
    return events
