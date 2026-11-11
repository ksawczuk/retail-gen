"""E-commerce OMS: Parquet. Orders and shipments are versioned (a row per status change);
lines, payment events and returns are append-only."""
import numpy as np
import pandas as pd

from .. import reference as ref
from ..util import pick_rows
from .common import route, by_month, make_late, variant, postal_variant, code_variant

SRC = "oms"
NS = "datetime64[ns]"


def _utc(s):
    return pd.to_datetime(s).dt.tz_localize("UTC")


def _order_versions(o: pd.DataFrame) -> pd.DataFrame:
    parts = [o.assign(status="placed", updated_at=o["_placed"])]
    for col, status in (("shipped_at", "shipped"), ("delivered_at", "delivered"), ("cancelled_at", "cancelled")):
        m = o[col].notna()
        parts.append(o[m].assign(status=status, updated_at=o.loc[m, col]))
    v = pd.concat(parts, ignore_index=True)
    v["updated_at"] = v["updated_at"].astype(NS)
    return v.sort_values("updated_at", kind="stable").reset_index(drop=True)


def _latest_as_of(v: pd.DataFrame, deliver: pd.Series, cutoff):
    m = (deliver <= cutoff).to_numpy()
    return v[m].sort_values("updated_at").drop_duplicates("order_id", keep="last")


def _write(out, cfg, hist, days, entity, prefix, month_col, fmt=lambda df, day: df):
    for m, g in by_month(hist, hist[month_col]).items():
        out.parquet(fmt(g, None), None, SRC, entity, f"{prefix}_{m}.parquet")
    for day, g in days.items():
        out.parquet(fmt(g, day), day, SRC, entity, f"{prefix}_{day:%Y%m%d}.parquet")


def emit(cfg, rng, t, out, man):
    o = t.orders.copy()
    n = len(o)

    # ---- test orders (QA traffic that never got cleaned out)
    k = cfg.count(25, 3)
    src = o.iloc[pick_rows(rng, n, k)].copy()
    src["order_id"] = [f"ORD-{900000001 + i}" for i in range(len(src))]
    src["customer_id"] = None
    src["guest_email"] = [f"qa+{i}@{cfg.employee_domain}" for i in range(len(src))]
    src["ship_postal"] = "X0X 0X0"
    tl = t.order_lines[t.order_lines["order_id"].isin(t.orders["order_id"].iloc[:50])].head(len(src)).copy()
    tl["order_id"] = src["order_id"].to_numpy()[: len(tl)]
    tl["line_no"] = 1
    weird = rng.random(len(tl)) < 0.5
    tl["qty"] = np.where(weird, 9999, tl["qty"])
    tl["unit_price"] = np.where(weird, tl["unit_price"], 0.01)
    tl["line_total"] = np.round(tl["qty"] * tl["unit_price"], 2)
    o = pd.concat([o, src], ignore_index=True)
    lines = pd.concat([t.order_lines, tl], ignore_index=True)
    man.record("oms.test_orders", len(src), keys=src["order_id"])

    # ---- future-dated orders (device clock wrong)
    o["_placed"] = o["order_ts"]
    late_hist = o.index[(o["order_ts"] >= pd.Timestamp("2026-06-01")) & (o["order_ts"] < cfg.history_end)]
    fut = rng.choice(late_hist, size=min(len(late_hist), cfg.count(10, 2)), replace=False)
    shift = pd.Timedelta(days=400)
    for c in ("order_ts",):
        o.loc[fut, c] = o.loc[fut, c] + shift
    man.record("oms.future_dated_orders", len(fut), keys=o.loc[fut, "order_id"])

    # ---- totals that don't add up
    shipping = o.index[o["shipping_fee"] > 0]
    mm = rng.choice(shipping, size=min(len(shipping), cfg.count(0.004 * n, 2)), replace=False)
    o.loc[mm, "order_total"] = (o.loc[mm, "order_total"] - o.loc[mm, "shipping_fee"]).round(2)
    man.record("oms.total_excludes_shipping", len(mm), keys=o.loc[mm, "order_id"])
    rest = np.setdiff1d(o.index.to_numpy(), mm)
    off = rng.choice(rest, size=cfg.count(0.01 * n, 2), replace=False)
    o.loc[off, "order_total"] = (o.loc[off, "order_total"] + rng.choice([-0.01, 0.01], len(off))).round(2)
    man.record("oms.total_off_by_a_cent", len(off), keys=o.loc[off, "order_id"])

    # ---- lost headers: orders whose header rows never arrive (lines do)
    lost = rng.choice(o.index[:n], size=cfg.count(0.0005 * n, 2), replace=False)
    lost_ids = set(o.loc[lost, "order_id"])
    man.record("oms.lost_order_headers", len(lost_ids), keys=sorted(lost_ids))

    # ---- disguised guest ids, casing noise
    guest = o["customer_id"].isna()
    o.loc[guest, "customer_id"] = rng.choice(np.array(["", "0", "GUEST", None], dtype=object), size=int(guest.sum()))
    man.record("oms.guest_customer_id", int(guest.sum()))
    o["channel"] = [c if rng.random() < 0.8 else {"web": ["WEB", "Web"], "app": ["APP", "mobile_app"]}[c][rng.integers(2)]
                    for c in o["channel"]]
    man.record("oms.channel_variants", 1)
    o["ship_province"] = variant(rng, o["ship_province"], ref.PROVINCE_VARIANTS, keep_p=0.85)
    o["ship_country"] = variant(rng, o["ship_country"], ref.COUNTRY_VARIANTS, keep_p=0.85)
    o["ship_postal"] = postal_variant(rng, o["ship_postal"], 0.15)
    o["coupon_code"] = code_variant(rng, o["coupon_code"])
    man.record("oms.address_code_variants", 1)

    # ---- order versions -> history snapshot + daily change files
    v = _order_versions(o[~o["order_id"].isin(lost_ids)])
    deliver, late = make_late(rng, v["updated_at"].dt.normalize(), 0.01, 1, 4)
    man.record("oms.late_order_versions", int(late.sum()), keys=v.loc[late, "order_id"])
    hist = _latest_as_of(v, deliver, cfg.history_end)
    dup = hist.iloc[pick_rows(rng, len(hist), cfg.count(0.002 * len(hist), 2))]
    hist = pd.concat([hist, dup]).sort_values("order_ts", kind="stable")
    man.record("oms.exact_duplicate_orders", len(dup), keys=dup["order_id"])
    inc = v[((deliver > cfg.history_end) & (deliver <= cfg.increment_end)).to_numpy()]
    days = {d: g for d, g in inc.groupby(deliver[inc.index].to_numpy())}
    cols = ["order_id", "customer_id", "guest_email", "order_ts", "channel", "currency", "ship_city",
            "ship_province", "ship_postal", "ship_country", "status", "subtotal", "discount_total",
            "tax_total", "shipping_fee", "order_total", "coupon_code", "updated_at"]
    rename_day = cfg.increment_day(18)

    def fmt_orders(df, day):
        df = df[cols].copy()
        df["order_ts"] = _utc(df["order_ts"])
        df["updated_at"] = _utc(df["updated_at"])
        if day is not None and day >= rename_day:
            df = df.rename(columns={"shipping_fee": "shipping_amount"})
        return df.reset_index(drop=True)

    hist = hist.assign(_m=hist["_placed"])
    _write(out, cfg, hist, days, "orders", "orders", "_m", fmt_orders)
    replay_day, src_day = cfg.increment_day(9), cfg.increment_day(8)
    if src_day in days:
        out.parquet(fmt_orders(days[src_day], src_day), replay_day, SRC, "orders", f"orders_{src_day:%Y%m%d}_r1.parquet")
        man.record("oms.replayed_batch", len(days[src_day]), keys=days[src_day]["order_id"],
                   src_day=src_day, replay_day=replay_day)
    man.record("oms.schema_drift_shipping_amount", 1, day=rename_day)

    # ---- lines: delivered with the order's 'placed' event
    placed = o.set_index("order_id")["_placed"]
    lines = lines.assign(_ts=lines["order_id"].map(placed).astype(NS))
    ldeliver = lines["_ts"].dt.normalize()
    ld =lines.iloc[pick_rows(rng, len(lines), cfg.count(0.001 * len(lines), 2))]
    man.record("oms.duplicate_order_lines", len(ld), keys=ld["order_id"] + "#" + ld["line_no"].astype(str))
    lines = pd.concat([lines, ld])
    ldeliver = pd.concat([ldeliver, ldeliver.loc[ld.index]])
    lines = lines.reset_index(drop=True)
    ldeliver = ldeliver.reset_index(drop=True)
    qty_day = cfg.increment_day(22)

    def fmt_lines(df, day):
        d = pd.DataFrame({"order_id": df["order_id"], "line_number": df["line_no"].astype("int32"), "sku": df["sku"],
                          "quantity": df["qty"].astype("int64"), "unit_price": df["unit_price"],
                          "discount_amount": df["line_discount"].fillna(0.0), "line_total": df["line_total"]})
        if day is not None and day >= qty_day:
            d["quantity"] = d["quantity"].astype(float).map(lambda x: f"{x:.1f}")
        return d.reset_index(drop=True)

    lh, ldays = route(cfg, lines, ldeliver)
    _write(out, cfg, lh, ldays, "order_lines", "order_lines", "_ts", fmt_lines)
    headers = set(hist["order_id"]) | set(inc["order_id"])
    sent = pd.concat([lh] + list(ldays.values()))
    orphan = sent[~sent["order_id"].isin(headers)]
    man.record("oms.orphan_order_lines", len(orphan), keys=orphan["order_id"].unique())
    man.record("oms.schema_drift_quantity_string", 1, day=qty_day)

    # ---- payment events
    p = t.payments.copy()
    caps = p.index[p["event_type"] == "capture"]
    dc = rng.choice(caps, size=min(len(caps), cfg.count(0.001 * n, 2)), replace=False)
    extra = p.loc[dc].copy()
    extra["payment_event_id"] = [f"PAY-{290000001 + i}" for i in range(len(extra))]
    extra["event_ts"] = extra["event_ts"] + pd.Timedelta(minutes=2)
    man.record("oms.double_capture", len(extra), keys=extra["order_id"])
    orph = p.iloc[pick_rows(rng, len(p), cfg.count(0.0002 * len(p), 2))].copy()
    orph["payment_event_id"] = [f"PAY-{299000001 + i}" for i in range(len(orph))]
    orph["order_id"] = [f"ORD-{rng.integers(800000000, 899999999)}" for _ in range(len(orph))]
    man.record("oms.orphan_payments", len(orph), keys=orph["payment_event_id"])
    p = pd.concat([p, extra, orph], ignore_index=True).sort_values("event_ts").reset_index(drop=True)

    def fmt_pay(df, day):
        d = df.drop(columns=[c for c in df.columns if c.startswith("_")]).copy()
        d["event_ts"] = _utc(d["event_ts"])
        return d.reset_index(drop=True)

    ph, pdays = route(cfg, p, p["event_ts"])
    _write(out, cfg, ph, pdays, "payments", "payments", "event_ts", fmt_pay)

    # ---- shipments: versioned (shipped, then delivered)
    s = t.shipments.copy()
    sw = pick_rows(rng, len(s), cfg.count(0.002 * len(s), 2))
    a, b = s.loc[sw, "shipped_at"].copy(), s.loc[sw, "delivered_at"].copy()
    s.loc[sw, "shipped_at"], s.loc[sw, "delivered_at"] = b.to_numpy(), a.to_numpy()
    man.record("oms.delivered_before_shipped", len(sw), keys=s.loc[sw, "shipment_id"])
    s["carrier"] = variant(rng, s["carrier"], ref.CARRIER_VARIANTS, keep_p=0.7)
    man.record("oms.carrier_variants", 1)
    sv = pd.concat([s.assign(status="in_transit", delivered_at=pd.NaT, updated_at=s["shipped_at"]),
                    s.assign(status="delivered", updated_at=s[["shipped_at", "delivered_at"]].max(axis=1))],
                   ignore_index=True)
    sv["updated_at"] = sv["updated_at"].astype(NS)
    sd = sv["updated_at"].dt.normalize()
    shist = sv[(sd <= cfg.history_end).to_numpy()].sort_values("updated_at").drop_duplicates("shipment_id", keep="last")
    sinc = sv[((sd > cfg.history_end) & (sd <= cfg.increment_end)).to_numpy()]
    sdays = {d: g for d, g in sinc.groupby(sd[sinc.index].to_numpy())}

    def fmt_ship(df, day):
        d = df.copy()
        for c in ("shipped_at", "delivered_at", "updated_at"):
            d[c] = _utc(d[c])
        return d.reset_index(drop=True)

    _write(out, cfg, shist, sdays, "shipments", "shipments", "shipped_at", fmt_ship)

    # ---- returns (mail-in only; store returns show up in POS)
    r = t.returns[t.returns["channel"] == "mail"].drop(columns=["channel"]).reset_index(drop=True)
    big = pick_rows(rng, len(r), cfg.count(0.003 * len(r), 2))
    r.loc[big, "refund_amount"] = (r.loc[big, "refund_amount"] * rng.uniform(2, 3, len(big))).round(2)
    man.record("oms.refund_exceeds_charge", len(big), keys=r.loc[big, "return_id"])

    def fmt_ret(df, day):
        d = df.copy()
        d["returned_at"] = _utc(d["returned_at"])
        return d.reset_index(drop=True)

    rh, rdays = route(cfg, r, r["returned_at"])
    _write(out, cfg, rh, rdays, "returns", "returns", "returned_at", fmt_ret)
