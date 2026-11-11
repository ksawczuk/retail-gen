"""Smaller feeds: store master (daily snapshots), FX rates, promotions and coupon redemptions."""
import numpy as np
import pandas as pd

from .. import reference as ref
from ..truth.masterdata import stores_as_of
from ..util import pick_rows
from .common import variant, route, by_month, code_variant, is_null


# ---------------------------------------------------------------- store ops
def emit_stores(cfg, rng, t, out, man):
    def snap(day):
        s = stores_as_of(t.stores, t.store_events, day)
        return pd.DataFrame({
            "store_id": s["store_id"], "store_code": s["store_code"], "store_name": s["store_name"],
            "city": s["city"], "province": variant(rng, s["province"], ref.PROVINCE_VARIANTS, keep_p=0.7),
            "country": variant(rng, s["country"], ref.COUNTRY_VARIANTS, keep_p=0.7), "timezone": s["timezone"],
            "sqft": s["sqft"], "open_date": s["opened_at"].dt.strftime("%m/%d/%Y"),
            "close_date": s["closed_at"].dt.strftime("%m/%d/%Y"),
            "extracted_at": f"{day:%Y-%m-%d} 02:00:00"})

    out.csv(snap(cfg.history_end), None, "storeops", "stores", "stores_20260930.csv")
    skip = cfg.increment_day(25)
    for day in cfg.increment_days:
        if day == skip:
            continue
        rel = out.csv(snap(day), day, "storeops", "stores", f"stores_{day:%Y%m%d}.csv")
        if day == cfg.increment_day(7):
            out.duplicate(rel, f"stores_{day:%Y%m%d}_retry.csv")
    man.record("storeops.missing_snapshot", 1, day=skip)
    man.record("storeops.duplicate_snapshot", 1, day=cfg.increment_day(7))
    for e in t.store_events:
        kind = "storeops.store_recoded" if "store_code" in e else "storeops.store_closed"
        man.record(kind, 1, keys=[e["store_id"]], store_id=e["store_id"], day=e["day"])
    man.record("storeops.us_date_format", 1)


# ---------------------------------------------------------------- finance
def emit_fx(cfg, rng, t, out, man):
    fx = t.fx[t.fx["date"] >= cfg.history_start - pd.Timedelta(days=5)].copy()
    holidays = {(1, 1), (7, 1), (12, 25), (12, 26), (11, 11)}
    biz = (fx["date"].dt.dayofweek < 5) & ~fx["date"].map(lambda d: (d.month, d.day) in holidays)
    man.record("finance.no_weekend_rates", int((~biz).sum()))
    fx = fx[biz].reset_index(drop=True)
    df = pd.DataFrame({"rate_date": fx["date"], "from_ccy": "USD", "to_ccy": "CAD", "rate": fx["usd_cad"]})
    inv = pick_rows(rng, len(df), cfg.count(5, 2))
    df.loc[inv, "rate"] = (1 / df.loc[inv, "rate"]).round(4)
    man.record("finance.inverted_rate", len(inv), keys=df.loc[inv, "rate_date"].dt.strftime("%Y-%m-%d"))
    dd = pick_rows(rng, len(df), cfg.count(3, 1))
    extra = df.iloc[dd].copy()
    extra["rate"] = (extra["rate"] * rng.uniform(0.995, 1.005, len(extra))).round(4)
    df = pd.concat([df, extra]).sort_values("rate_date", kind="stable").reset_index(drop=True)
    man.record("finance.conflicting_duplicate_dates", len(dd),
               keys=extra["rate_date"].dt.strftime("%Y-%m-%d"))
    hist, days = route(cfg, df, df["rate_date"])
    h = hist.assign(rate_date=hist["rate_date"].dt.strftime("%Y-%m-%d"))
    out.csv(h, None, "finance", "fx_rates", "fx_rates_history.csv")
    for day, g in days.items():
        out.csv(g.assign(rate_date=g["rate_date"].dt.strftime("%Y/%m/%d")), day, "finance", "fx_rates",
                f"fx_rates_{day:%Y%m%d}.csv")
    man.record("finance.date_format_drift", 1)


# ---------------------------------------------------------------- promotions
def _promo_records(rng, p):
    recs = []
    for r in p.itertuples(index=False):
        alt = rng.random() < 0.3
        recs.append({
            "promoId": r.promo_id, "code": r.code,
            "type": ("PERCENT" if r.promo_type == "pct" else "FIXED_AMOUNT"),
            "value": (f"{r.value}%" if r.promo_type == "pct" else f"${r.value:.2f}"),
            "minSpend": None if is_null(r.min_spend) else f"${r.min_spend:.2f}",
            "startDate": r.starts_at.strftime("%m/%d/%Y" if alt else "%Y-%m-%d"),
            "endDate": None if is_null(r.ends_at) else r.ends_at.strftime("%m/%d/%Y" if alt else "%Y-%m-%d"),
            "channels": r.channels.split(","),
        })
    return recs


def emit_promo(cfg, rng, t, out, man):
    he = cfg.history_end + pd.Timedelta(days=1)
    p = t.promotions
    out.json_array(_promo_records(rng, p[p["created_at"] < he]), None, "promo", "promotions", "promotions.json")
    for day in sorted(p.loc[p["created_at"] >= he, "created_at"].dt.normalize().unique()):
        day = pd.Timestamp(day)
        out.json_array(_promo_records(rng, p[p["created_at"] <= day + pd.Timedelta(days=1)]), day,
                       "promo", "promotions", f"promotions_{day:%Y%m%d}.json")
    man.record("promo.json_array_file", 1)
    man.record("promo.value_as_text", len(p))
    man.record("promo.mixed_date_formats", 1)

    o = t.orders[t.orders["coupon_code"].notna()].reset_index(drop=True)
    good = o[o["cancelled_at"].isna()]
    unrev = o[o["cancelled_at"].notna()]
    man.record("promo.redemption_on_cancelled_order", len(unrev), keys=unrev["order_id"])
    r = pd.concat([good, unrev], ignore_index=True).sort_values("order_ts").reset_index(drop=True)
    disc = r["discount_total"].to_numpy()
    fr = (r["ship_province"] == "QC").to_numpy()
    amount = [f"{d:.2f}".replace(".", ",") if q else (f"${d:.2f}" if rng.random() < 0.5 else f"{d:.2f}")
              for d, q in zip(disc, fr)]
    codes = code_variant(rng, r["coupon_code"])
    typo = pick_rows(rng, len(r), cfg.count(0.005 * len(r), 2))
    for i in typo:
        c = r["coupon_code"].iloc[i]
        j = int(rng.integers(1, len(c) - 1))
        codes[i] = c[:j] + c[j + 1:]
    man.record("promo.unknown_code_typo", len(typo), keys=r["order_id"].iloc[typo])
    man.record("promo.code_case_whitespace", 1)
    man.record("promo.amount_text_locale", len(r))
    df = pd.DataFrame({"redemptionId": [f"RDM-{700000001 + i}" for i in range(len(r))],
                       "orderId": r["order_id"], "code": codes, "discountAmount": amount,
                       "redeemedAt": (r["order_ts"].astype("int64") // 10**6).to_numpy(),
                       "_ts": r["order_ts"]})
    hist, days = route(cfg, df, df["_ts"])
    for m, g in by_month(hist, hist["_ts"]).items():
        out.jsonl(g.drop(columns="_ts").to_dict("records"), None, "promo", "coupon_redemptions",
                  f"coupon_redemptions_{m}.jsonl")
    for day, g in days.items():
        out.jsonl(g.drop(columns="_ts").to_dict("records"), day, "promo", "coupon_redemptions",
                  f"coupon_redemptions_{day:%Y%m%d}.jsonl")
