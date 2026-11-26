"""Web analytics (gzipped nested JSON Lines) and warehouse inventory snapshots (Parquet)."""
import json

import numpy as np
import pandas as pd

from .. import reference as ref
from ..util import pick_rows
from ..writers import to_jsonable
from .common import route, by_month, is_null

NS = "datetime64[ns]"


def _bot_events(cfg, rng, start_day, n_sessions):
    rows = []
    days = pd.date_range(start_day, cfg.increment_end, freq="D")
    for _ in range(n_sessions):
        day = days[rng.integers(len(days))]
        t0 = day + pd.Timedelta(seconds=int(rng.integers(0, 86400)))
        sid = rng.bytes(8).hex()
        ua = ref.BOT_AGENTS[rng.integers(len(ref.BOT_AGENTS))]
        k = int(rng.integers(30, 150))
        offs = np.cumsum(rng.uniform(0.3, 3.0, k))
        for j in range(k):
            sku = f"{rng.integers(1000, 200000):06d}"
            rows.append({"event_id": rng.bytes(16).hex(), "session_id": sid, "event_type": "product_view",
                         "event_ts": t0 + pd.Timedelta(seconds=float(offs[j])), "page": f"/p/{sku}", "sku": sku,
                         "order_id": None, "customer_id": None, "channel": "web", "device_type": "desktop",
                         "os": "Linux", "browser": "bot", "anonymous_id": rng.bytes(12).hex(),
                         "utm_source": None, "utm_medium": None, "price": np.nan, "is_bot": True, "user_agent": ua})
    b = pd.DataFrame(rows)
    b["event_ts"] = b["event_ts"].astype(NS)
    return b


def _tracked_campaigns(rng, ev, man):
    """The utm campaign each event's session reports: some email sessions lose it, some arrive mangled.
    Called by emit_web before the records are built."""
    tags = ev["utm_campaign"].copy() if "utm_campaign" in ev else pd.Series(None, index=ev.index, dtype=object)
    email = ev["utm_source"].eq("newsletter") & tags.notna()
    sessions = ev.loc[email, "session_id"].unique()
    draw = rng.random(len(sessions))

    # A share of email sessions lose the tag, another share report it mangled
    lost = set(sessions[draw < 0.08])
    mangled = set(sessions[(draw >= 0.08) & (draw < 0.13)])
    tags[ev["session_id"].isin(lost) & email] = None
    bad = ev["session_id"].isin(mangled) & email
    tags[bad] = [t.upper() if len(t) % 2 else t.replace("_", "-") for t in tags[bad]]
    man.record("web.utm_campaign_missing", len(lost), keys=sorted(lost))
    man.record("web.utm_campaign_variants", len(mangled), keys=sorted(mangled))
    return tags


def emit_web(cfg, rng, t, out, man):
    ev = t.clickstream.copy()
    ev["user_agent"] = [f"Mozilla/5.0 ({o}) {b}" for o, b in zip(ev["os"], ev["browser"])]
    n_sess = ev["session_id"].nunique()
    bots = _bot_events(cfg, rng, cfg.clickstream_start, cfg.count(0.02 * n_sess, 3))
    man.record("web.bot_sessions", bots["session_id"].nunique(), keys=bots["session_id"].unique())
    man.record("web.bot_events", len(bots))
    ev = pd.concat([ev, bots], ignore_index=True).sort_values("event_ts").reset_index(drop=True)

    # app 4.1.0 (from 2026-08-15) sends ts in seconds instead of milliseconds
    app = (ev["channel"] == "app").to_numpy()
    new_app = app & (ev["event_ts"] >= pd.Timestamp("2026-08-15")).to_numpy() & \
        (pd.util.hash_array(ev["session_id"].to_numpy()) % 3 != 0)
    ev["app_version"] = np.where(app, np.where(new_app, "4.1.0", "4.0.2"), None)
    man.record("web.ts_in_seconds", int(new_app.sum()))
    man.record("web.purchase_without_tracking", 1)

    dup = pick_rows(rng, len(ev), cfg.count(0.005 * len(ev), 3))
    ev["deliver_day"] = ev["event_ts"].dt.normalize()
    d = ev.iloc[dup].copy()
    nxt = (rng.random(len(d)) < 0.3) & (d["deliver_day"] < cfg.increment_end).to_numpy()
    d.loc[nxt, "deliver_day"] = d.loc[nxt, "deliver_day"] + pd.Timedelta(days=1)
    man.record("web.duplicate_events", len(d), keys=d["event_id"])
    ev = pd.concat([ev, d], ignore_index=True)
    consent_day = cfg.increment_day(15)
    man.record("web.schema_drift_consent", 1, day=consent_day)
    ev["utm_campaign"] = _tracked_campaigns(rng, ev, man)

    def records(g):
        recs = []
        for r in g.itertuples(index=False):
            ms = int(pd.Timestamp(r.event_ts).value // 10**6)
            rec = {"event_id": r.event_id, "event_name": r.event_type,
                   "ts": ms // 1000 if r.app_version == "4.1.0" else ms,
                   "session": {"id": r.session_id, "channel": r.channel},
                   "user": {"customer_id": r.customer_id, "anonymous_id": r.anonymous_id},
                   "device": {"type": r.device_type, "os": r.os, "browser": r.browser, "user_agent": r.user_agent},
                   "page": {"path": r.page, "referrer": (f"https://{r.utm_source}.example/" if not is_null(r.utm_source) else None)}}
            if not is_null(r.app_version):
                rec["session"]["app_version"] = r.app_version
            if not is_null(r.sku):
                rec["product"] = {"sku": r.sku, "price": None if is_null(r.price) else round(float(r.price), 2)}
            if not is_null(r.order_id):
                rec["ecommerce"] = {"order_id": r.order_id}
            if not is_null(r.utm_source):
                rec["utm"] = {"source": r.utm_source, "medium": r.utm_medium}
                if not is_null(r.utm_campaign):
                    rec["utm"]["campaign"] = r.utm_campaign
            if r.deliver_day >= consent_day:
                rec["consent"] = {"analytics": True, "marketing": int(r.session_id[:2], 16) % 2 == 1}
            recs.append(rec)
        return recs

    hist, days = route(cfg, ev, ev["deliver_day"])
    files = [(None, f"events_{m}.jsonl.gz", g) for m, g in by_month(hist, hist["event_ts"]).items()]
    files += [(day, f"events_{day:%Y%m%d}.jsonl.gz", g) for day, g in days.items()]
    per_file = np.bincount(rng.integers(0, len(files), cfg.count(0.0002 * len(ev), 3)), minlength=len(files))
    n_trunc = 0
    for (day, name, g), k in zip(files, per_file):
        recs = records(g.sort_values("event_ts", kind="stable"))
        bad = []
        for pos in pick_rows(rng, len(recs), k):
            s = json.dumps(to_jsonable(recs[pos]), ensure_ascii=False)
            bad.append((int(pos), s[: int(rng.integers(20, max(21, len(s) - 5)))]))
        n_trunc += len(bad)
        out.jsonl(recs, day, "web", "events", name, gz=True, bad_lines=bad)
    man.record("web.truncated_lines", n_trunc)


def emit_inventory(cfg, rng, t, out, man):
    inv = t.inventory.copy()
    neg = pick_rows(rng, len(inv), cfg.count(0.001 * len(inv), 2))
    inv.loc[neg, "on_hand"] = -rng.integers(1, 20, len(neg))
    man.record("inventory.negative_on_hand", len(neg),
               keys=inv.loc[neg, "store_id"].astype(str) + "|" + inv.loc[neg, "sku"] + "|" +
               inv.loc[neg, "snapshot_date"].dt.strftime("%Y-%m-%d"))
    hist_mask = inv["snapshot_date"] <= cfg.history_end
    weeks = sorted(inv.loc[hist_mask, "snapshot_date"].unique())
    stores = sorted(inv["store_id"].unique())
    gap_store = stores[0]
    gap_weeks = weeks[len(weeks) // 2: len(weeks) // 2 + 3]
    gap = (inv["store_id"] == gap_store) & inv["snapshot_date"].isin(gap_weeks)
    man.record("inventory.missing_store_weeks", int(gap.sum()),
               keys=[f"{gap_store}|{pd.Timestamp(w):%Y-%m-%d}" for w in gap_weeks], store=gap_store)
    inv = inv[~gap]
    cw = weeks[len(weeks) // 3]
    cs = stores[-1]
    conf = inv[(inv["store_id"] == cs) & (inv["snapshot_date"] == cw)].copy()
    conf["on_hand"] = np.maximum(conf["on_hand"] + rng.integers(-5, 6, len(conf)), 0)
    man.record("inventory.conflicting_snapshot", len(conf), keys=[f"{cs}|{pd.Timestamp(cw):%Y-%m-%d}"],
               store=cs, week=pd.Timestamp(cw))
    inv = pd.concat([inv, conf], ignore_index=True)
    deliver = inv["snapshot_date"] + pd.Timedelta(days=1)  # Sunday snapshot lands Monday

    def fmt(df):
        d = df.copy()
        d["snapshot_date"] = d["snapshot_date"].dt.date
        d["store_id"] = d["store_id"].astype("int32")
        return d.reset_index(drop=True)

    hist, days = route(cfg, inv, deliver)
    for m, g in by_month(hist, hist["snapshot_date"]).items():
        out.parquet(fmt(g), None, "inventory", "snapshots", f"inventory_{m}.parquet")
    for day, g in days.items():
        out.parquet(fmt(g), day, "inventory", "snapshots", f"inventory_{day:%Y%m%d}.parquet")
