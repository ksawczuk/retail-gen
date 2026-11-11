"""Clean truth for e-commerce: orders, lines, payment events, shipments and returns."""
import numpy as np
import pandas as pd

from .. import reference as ref
from ..util import seasonality, bounded_weighted_pick, seconds_in_day
from .masterdata import price_lookup, fx_on
from .customers import ship_to

NS = "datetime64[ns]"
ONLINE_HOURS = [1, .6, .4, .3, .3, .5, 1, 1.5, 2, 2.5, 3, 3, 3, 3, 3, 3.5, 4, 4.5, 5, 5.5, 5, 4, 3, 2]


def _hours(rng, n, lo, hi):
    return pd.to_timedelta(rng.uniform(lo, hi, n), unit="h")


def generate_online(cfg, rng, customers, addresses, products, price_history, promos, fx):
    days = pd.date_range(cfg.history_start, cfg.increment_end, freq="D")
    counts = rng.poisson(cfg.web_orders_per_day * seasonality(days))
    n = int(counts.sum())
    day = np.repeat(days.to_numpy().astype(NS), counts)
    ts = np.sort(day + seconds_in_day(rng, n, ONLINE_HOURS).astype("timedelta64[s]")).astype(NS)
    orders = pd.DataFrame({"order_id": [f"ORD-{100000001 + i}" for i in range(n)], "order_ts": ts})

    # Who ordered: an existing customer weighted by activity, or a guest.
    cust = customers.sort_values("created_at").reset_index(drop=True)
    cumw = np.cumsum(cust["activity"].to_numpy())
    ub = np.searchsorted(cust["created_at"].to_numpy(), ts, side="right")
    guest = (rng.random(n) < 0.12) | (ub == 0)
    ci = bounded_weighted_pick(rng, cumw, np.maximum(ub, 1))
    orders["customer_id"] = np.where(guest, None, cust["customer_id"].to_numpy()[ci])
    orders["guest_email"] = np.where(guest, [f"guest{rng.integers(10**6, 10**7)}@{ref.EMAIL_DOMAINS[rng.integers(5)]}"
                                             for _ in range(n)], None)

    st = ship_to(addresses)
    orders = orders.merge(st.rename(columns={"address_id": "ship_address_id", "city": "ship_city",
                                             "province": "ship_province", "postal_code": "ship_postal",
                                             "country": "ship_country"}),
                          on="customer_id", how="left")
    g = orders["ship_province"].isna().to_numpy()
    cw = np.array([c[6] for c in ref.CITIES], float)
    gc = rng.choice(len(ref.CITIES), size=int(g.sum()), p=cw / cw.sum())
    orders.loc[g, "ship_city"] = [ref.CITIES[i][0] for i in gc]
    orders.loc[g, "ship_province"] = [ref.CITIES[i][1] for i in gc]
    orders.loc[g, "ship_country"] = [ref.CITIES[i][2] for i in gc]
    orders.loc[g, "ship_postal"] = [ref.CITIES[i][4][0] if ref.CITIES[i][2] == "US" else
                                    f"{ref.CITIES[i][4][0]} {rng.integers(10)}A{rng.integers(10)}" for i in gc]
    orders["currency"] = np.where(orders["ship_country"] == "US", "USD", "CAD")
    orders["channel"] = rng.choice(["web", "app"], size=n, p=[0.65, 0.35])

    # Lines: popularity-weighted SKUs that had launched by the order time.
    n_lines = 1 + rng.poisson(1.2, n)
    oi = np.repeat(np.arange(n), n_lines)
    prods = products[~products["pim_excluded"]].sort_values("launched_at").reset_index(drop=True)
    pcum = np.cumsum(prods["popularity"].to_numpy())
    pub = np.maximum(np.searchsorted(prods["launched_at"].to_numpy(), ts[oi], side="right"), 1)
    lines = pd.DataFrame({"oi": oi, "sku": prods["sku"].to_numpy()[bounded_weighted_pick(rng, pcum, pub)]})
    lines = lines.drop_duplicates(["oi", "sku"]).reset_index(drop=True)
    lines["order_id"] = orders["order_id"].to_numpy()[lines["oi"]]
    lines["line_no"] = lines.groupby("oi").cumcount() + 1
    lines["qty"] = rng.choice([1, 2, 3, 4], size=len(lines), p=[0.8, 0.14, 0.04, 0.02])
    lts = ts[lines["oi"].to_numpy()]
    price_cad = price_lookup(price_history, lines["sku"].to_numpy(), lts)
    usd = (orders["currency"].to_numpy()[lines["oi"]] == "USD")
    rate = fx_on(fx, lts)
    lines["unit_price"] = np.where(usd, np.round(price_cad / rate, 2), price_cad)
    lines["gross"] = np.round(lines["qty"] * lines["unit_price"], 2)

    # Coupons: each promo is used by a share of orders placed while it runs.
    coupon = np.full(n, None, dtype=object)
    web_promos = promos[promos["channels"].str.contains("web")]
    for p in web_promos.sample(frac=1, random_state=int(rng.integers(1 << 31))).itertuples(index=False):
        end = p.ends_at + pd.Timedelta(days=1) if pd.notna(p.ends_at) else cfg.increment_end + pd.Timedelta(days=1)
        share = 0.03 if pd.isna(p.ends_at) else 0.25
        hit = (ts >= p.starts_at.to_datetime64()) & (ts < end.to_datetime64()) & pd.isna(coupon) & (rng.random(n) < share)
        coupon[hit] = p.code
    orders["coupon_code"] = coupon
    subtotal = lines.groupby("oi")["gross"].sum().reindex(range(n)).to_numpy()
    pinfo = promos.set_index("code")
    lc = coupon[lines["oi"].to_numpy()]
    disc = np.zeros(len(lines))
    valid = np.ones(n, dtype=bool)
    for code in pd.unique(pd.Series(coupon).dropna()):
        p = pinfo.loc[code]
        lm = lc == code
        if p["promo_type"] == "pct":
            disc[lm] = np.round(lines["gross"].to_numpy()[lm] * p["value"] / 100.0, 2)
        else:
            om = coupon == code
            ok = subtotal >= (p["min_spend"] or 0)
            valid[om & ~ok] = False
            share = lines["gross"].to_numpy()[lm] / subtotal[lines["oi"].to_numpy()[lm]]
            disc[lm] = np.where(ok[lines["oi"].to_numpy()[lm]], np.round(p["value"] * share, 2), 0.0)
    orders.loc[~valid, "coupon_code"] = None
    lines["line_discount"] = disc
    lines["line_total"] = np.round(lines["gross"] - lines["line_discount"], 2)

    orders["subtotal"] = np.round(subtotal, 2)
    orders["discount_total"] = np.round(lines.groupby("oi")["line_discount"].sum().reindex(range(n)).to_numpy(), 2)
    orders["tax_rate"] = orders["ship_province"].map(ref.TAX_RATES).to_numpy()
    net = orders["subtotal"] - orders["discount_total"]
    orders["tax_total"] = np.round(net * orders["tax_rate"], 2)
    orders["shipping_fee"] = np.where(net >= 75, 0.0, 9.95)
    orders["order_total"] = np.round(net + orders["tax_total"] + orders["shipping_fee"], 2)

    # Lifecycle timestamps.
    cancelled = rng.random(n) < 0.03
    t = pd.Series(ts)
    orders["cancelled_at"] = (t + _hours(rng, n, 0.5, 20)).where(cancelled).astype(NS)
    shipped = (t + _hours(rng, n, 8, 72)).where(~cancelled)
    orders["shipped_at"] = shipped.astype(NS)
    orders["delivered_at"] = (shipped + _hours(rng, n, 24, 24 * 6)).astype(NS)

    payments = _payments(rng, orders)
    shipments = _shipments(rng, orders)
    returns = _returns(rng, orders, lines)
    refunds = returns.loc[returns["channel"] == "mail", ["order_id", "refund_amount", "returned_at"]].copy()
    refunds = refunds.merge(payments.drop_duplicates("order_id")[["order_id", "payment_method", "card_brand", "currency"]],
                            on="order_id")
    refunds = pd.DataFrame({"order_id": refunds["order_id"], "payment_method": refunds["payment_method"],
                            "card_brand": refunds["card_brand"], "event_type": "refund",
                            "amount": refunds["refund_amount"], "currency": refunds["currency"],
                            "event_ts": (refunds["returned_at"] + _hours(rng, len(refunds), 24, 72)).astype(NS)})
    payments = pd.concat([payments, refunds], ignore_index=True).sort_values("event_ts").reset_index(drop=True)
    payments.insert(0, "payment_event_id", [f"PAY-{200000001 + i}" for i in range(len(payments))])

    lines = lines.drop(columns=["oi"])
    orders = orders.drop(columns=["tax_rate"])
    return orders, lines, payments, shipments, returns


def _payments(rng, orders):
    n = len(orders)
    method = rng.choice(["credit_card", "paypal", "apple_pay", "gift_card"], size=n, p=[.62, .2, .13, .05])
    brand = np.where(method == "credit_card", rng.choice(["visa", "mastercard", "amex"], size=n, p=[.55, .35, .1]), None)
    base = pd.DataFrame({"order_id": orders["order_id"], "payment_method": method, "card_brand": brand,
                         "amount": orders["order_total"], "currency": orders["currency"]})
    failed = rng.random(n) < 0.02
    parts = [
        base[failed].assign(event_type="failed",
                            event_ts=(orders["order_ts"][failed] - pd.to_timedelta(rng.integers(60, 300, int(failed.sum())), unit="s"))),
        base.assign(event_type="authorize", event_ts=orders["order_ts"]),
        base[orders["shipped_at"].notna()].assign(event_type="capture", event_ts=orders["shipped_at"].dropna()),
        base[orders["cancelled_at"].notna()].assign(event_type="void", event_ts=orders["cancelled_at"].dropna()),
    ]
    p = pd.concat(parts, ignore_index=True)
    p["event_ts"] = p["event_ts"].astype(NS)
    return p


def _shipments(rng, orders):
    o = orders[orders["shipped_at"].notna()]
    us = (o["ship_country"] == "US").to_numpy()
    carrier = np.where(us, rng.choice(ref.CARRIERS_US, size=len(o)), rng.choice(ref.CARRIERS_CA, size=len(o)))
    return pd.DataFrame({
        "shipment_id": [f"SHP-{300000001 + i}" for i in range(len(o))],
        "order_id": o["order_id"].to_numpy(), "carrier": carrier,
        "tracking_number": [f"{rng.integers(10**11, 10**12)}" for _ in range(len(o))],
        "shipped_at": o["shipped_at"].to_numpy(), "delivered_at": o["delivered_at"].to_numpy(),
    })


def _returns(rng, orders, lines):
    o = orders.set_index("order_id")
    l = lines[lines["order_id"].map(o["delivered_at"]).notna()]
    l = l[rng.random(len(l)) < 0.06]
    delivered = l["order_id"].map(o["delivered_at"])
    ret_qty = np.array([rng.integers(1, q + 1) for q in l["qty"]])
    tax = l["order_id"].map(orders.set_index("order_id")["tax_rate"]).to_numpy()
    r = pd.DataFrame({
        "order_id": l["order_id"].to_numpy(), "line_no": l["line_no"].to_numpy(), "sku": l["sku"].to_numpy(),
        "qty": ret_qty,
        "refund_amount": np.round(l["line_total"].to_numpy() / l["qty"].to_numpy() * ret_qty * (1 + tax), 2),
        "reason": rng.choice(ref.RETURN_REASONS, size=len(l)),
        "returned_at": (delivered + _hours(rng, len(l), 72, 24 * 30)).astype(NS).to_numpy(),
        "channel": rng.choice(["mail", "store"], size=len(l), p=[0.75, 0.25]),
    })
    r = r.sort_values("returned_at").reset_index(drop=True)
    r.insert(0, "return_id", [f"RET-{400000001 + i}" for i in range(len(r))])
    return r
