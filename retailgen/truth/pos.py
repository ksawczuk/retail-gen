"""Clean truth for in-store point of sale: sales baskets and returns, one row per line."""
import numpy as np
import pandas as pd

from .. import reference as ref
from ..util import seasonality, bounded_weighted_pick, seconds_in_day
from .masterdata import price_lookup, fx_on, store_open_matrix

NS = "datetime64[ns]"
STORE_HOURS = [0] * 9 + [2, 3, 4, 5, 5, 5, 5, 5, 5, 4, 3, 2, 0, 0, 0]


def _local_to_utc(local: pd.Series, tz: pd.Series) -> np.ndarray:
    out = np.empty(len(local), dtype=NS)
    for z, idx in local.groupby(tz).groups.items():
        conv = (pd.DatetimeIndex(local.loc[idx]).tz_localize(z, nonexistent="shift_forward", ambiguous=False)
                .tz_convert("UTC").tz_localize(None))
        out[local.index.get_indexer(idx)] = conv.to_numpy().astype(NS)
    return out


def generate_pos(cfg, rng, stores, store_events, customers, products, price_history, promos, fx,
                 online_orders, online_lines, online_returns):
    days = pd.date_range(cfg.history_start, cfg.increment_end, freq="D")
    open_m = store_open_matrix(stores, store_events, days)
    counts = rng.poisson(cfg.pos_txns_per_day * seasonality(days))
    sqft = stores["sqft"].to_numpy(float)
    day_l, store_l = [], []
    for d, c in enumerate(counts):
        w = sqft * open_m[d]
        if c == 0 or w.sum() == 0:
            continue
        day_l.append(np.repeat(days[d].to_datetime64(), c))
        store_l.append(rng.choice(len(stores), size=c, p=w / w.sum()))
    tday = np.concatenate(day_l).astype(NS)
    sidx = np.concatenate(store_l)
    n = len(tday)
    txn = pd.DataFrame({"store_id": stores["store_id"].to_numpy()[sidx],
                        "local_ts": tday + seconds_in_day(rng, n, STORE_HOURS).astype("timedelta64[s]"),
                        "register": rng.integers(1, 7, n),
                        "tender_type": rng.choice(["debit", "credit", "cash", "gift_card"], size=n, p=[.4, .45, .1, .05])})
    txn["cashier_id"] = [f"E{s}{k:02d}" for s, k in zip(txn["store_id"], rng.integers(1, 13, n))]

    # Loyalty scans: a member who had signed up by then; a few are staff buying with discount.
    members = customers[customers["loyalty_number"].notna()].sort_values("created_at").reset_index(drop=True)
    staff = members[members["is_employee"]]
    cumw = np.cumsum(members["activity"].to_numpy())
    ub = np.searchsorted(members["created_at"].to_numpy(), txn["local_ts"].to_numpy(), side="right")
    scan = (rng.random(n) < 0.40) & (ub > 0)
    pick = bounded_weighted_pick(rng, cumw, np.maximum(ub, 1))
    txn["customer_id"] = np.where(scan, members["customer_id"].to_numpy()[pick], None)
    emp = (rng.random(n) < 0.01) & (len(staff) > 0)
    if emp.any():
        txn.loc[emp, "customer_id"] = staff["customer_id"].to_numpy()[rng.integers(0, len(staff), int(emp.sum()))]
    txn["employee_sale"] = emp

    # Lines.
    n_lines = 1 + rng.poisson(0.7, n)
    ti = np.repeat(np.arange(n), n_lines)
    prods = products.sort_values("launched_at").reset_index(drop=True)
    pcum = np.cumsum(prods["popularity"].to_numpy())
    lts = txn["local_ts"].to_numpy()[ti]
    pub = np.maximum(np.searchsorted(prods["launched_at"].to_numpy(), lts, side="right"), 1)
    lines = pd.DataFrame({"ti": ti, "sku": prods["sku"].to_numpy()[bounded_weighted_pick(rng, pcum, pub)]})
    lines = lines.drop_duplicates(["ti", "sku"]).reset_index(drop=True)
    lines["qty"] = rng.choice([1, 2, 3], size=len(lines), p=[.85, .12, .03])
    lines = lines.merge(txn, left_on="ti", right_index=True)
    lines = _price_lines(cfg, rng, lines, stores, price_history, promos, fx)
    lines["orig_txn_ref"] = None
    lines["orig_order_ref"] = None
    lines["is_return"] = False

    returns = _returns(cfg, rng, lines, stores, store_events, online_orders, online_lines, online_returns, fx)
    allp = pd.concat([lines.drop(columns=["ti"]), returns], ignore_index=True)

    # Transaction ids: store + local date + register + sequence; returns are their own baskets.
    allp["basket"] = np.where(allp["is_return"], -1 - np.arange(len(allp)), allp["basket_src"])
    allp = allp.sort_values(["store_id", "local_ts", "basket"]).reset_index(drop=True)
    first = ~allp.duplicated("basket")
    allp["day_key"] = allp["local_ts"].dt.strftime("%Y%m%d")
    seq = first.groupby([allp["store_id"], allp["day_key"]]).cumsum()
    allp["txn_id"] = [f"{s}-{d}-{r:02d}-{q:04d}" for s, d, r, q in
                      zip(allp["store_id"], allp["day_key"], allp["register"], seq)]
    # every line in a basket shares the basket's first timestamp/register, so ids agree
    allp["txn_id"] = allp.groupby("basket")["txn_id"].transform("first")
    allp["line_no"] = allp.groupby("txn_id").cumcount() + 1
    tz = allp["store_id"].map(stores.set_index("store_id")["timezone"])
    allp["utc_ts"] = _local_to_utc(allp["local_ts"], tz)
    # Fill return references from sale baskets.
    bmap = allp.drop_duplicates("basket").set_index("basket")["txn_id"]
    m = allp["orig_basket"].notna()
    allp.loc[m, "orig_txn_ref"] = allp.loc[m, "orig_basket"].astype(int).map(bmap)
    return allp.drop(columns=["basket", "basket_src", "orig_basket", "day_key"])


def _price_lines(cfg, rng, lines, stores, price_history, promos, fx):
    s = stores.set_index("store_id")
    lines["currency"] = np.where(lines["store_id"].map(s["country"]) == "US", "USD", "CAD")
    lines["province"] = lines["store_id"].map(s["province"]).to_numpy()
    cad = price_lookup(price_history, lines["sku"].to_numpy(), lines["local_ts"].to_numpy())
    rate = fx_on(fx, lines["local_ts"])
    lines["unit_price"] = np.where(lines["currency"] == "USD", np.round(cad / rate, 2), cad)
    disc_pct = np.zeros(len(lines))
    promo = np.full(len(lines), None, dtype=object)
    for p in promos[promos["channels"].str.contains("pos")].itertuples(index=False):
        end = p.ends_at + pd.Timedelta(days=1)
        hit = ((lines["local_ts"] >= p.starts_at) & (lines["local_ts"] < end)).to_numpy() & (rng.random(len(lines)) < 0.3)
        disc_pct[hit] = p.value
        promo[hit] = p.code
    emp = lines["employee_sale"].to_numpy()
    disc_pct[emp] = 30
    promo[emp] = "STAFF30"
    lines["promo_code"] = promo
    gross = lines["qty"] * lines["unit_price"]
    lines["line_discount"] = np.round(gross * disc_pct / 100.0, 2)
    lines["line_tax"] = np.round((gross - lines["line_discount"]) * lines["province"].map(ref.TAX_RATES), 2)
    lines["basket_src"] = lines["ti"]
    lines["orig_basket"] = np.nan
    return lines


def _returns(cfg, rng, sales, stores, store_events, online_orders, online_lines, online_returns, fx):
    """Return baskets: 3% of POS sale lines come back to the same store; online returns marked
    'store' come back to a store in the shipping province."""
    days = pd.date_range(cfg.history_start, cfg.increment_end + pd.Timedelta(days=60), freq="D")
    open_m = store_open_matrix(stores, store_events, days)
    sp = sales[rng.random(len(sales)) < 0.03].copy()
    back = pd.to_timedelta(rng.integers(1, 30, len(sp)), unit="D")
    sp["local_ts"] = (sp["local_ts"].dt.normalize() + back +
                      pd.to_timedelta(seconds_in_day(rng, len(sp), STORE_HOURS), unit="s")).astype(NS)
    sp["orig_basket"] = sp["ti"].astype(float)
    orig_qty = sp["qty"].to_numpy()
    ret = np.array([rng.integers(1, q + 1) for q in orig_qty], dtype=int)
    sp["line_discount"] = -np.round(sp["line_discount"].to_numpy() * ret / orig_qty, 2)
    sp["qty"] = -ret
    sp["orig_order_ref"] = None

    o = online_orders.set_index("order_id")
    orr = online_returns[online_returns["channel"] == "store"].merge(
        online_lines[["order_id", "line_no", "unit_price", "line_discount", "qty"]]
        .rename(columns={"qty": "orig_qty", "line_discount": "orig_disc"}),
        on=["order_id", "line_no"], how="left")
    sid = stores["store_id"].to_numpy()
    prov = orr["order_id"].map(o["ship_province"]).to_numpy()
    st_store = []
    for p in prov:
        cand = sid[stores["province"].to_numpy() == p]
        st_store.append(int(rng.choice(cand)) if len(cand) else int(rng.choice(sid)))
    oc = pd.DataFrame({
        "store_id": st_store, "sku": orr["sku"].to_numpy(), "qty": -orr["qty"].to_numpy(),
        "local_ts": (orr["returned_at"].dt.normalize() +
                     pd.to_timedelta(seconds_in_day(rng, len(orr), STORE_HOURS), unit="s")).astype(NS).to_numpy(),
        "unit_price": orr["unit_price"].to_numpy(),
        "line_discount": -np.round(orr["orig_disc"].to_numpy() / orr["orig_qty"].to_numpy() * orr["qty"].to_numpy(), 2),
        "currency": orr["order_id"].map(o["currency"]).to_numpy(),
        "customer_id": orr["order_id"].map(o["customer_id"]).to_numpy(),
        "promo_code": None, "orig_order_ref": orr["order_id"].to_numpy(), "orig_basket": np.nan,
    })
    r = pd.concat([sp, oc], ignore_index=True)
    # drop returns that land after the window or on a day the store is shut
    di = ((r["local_ts"].dt.normalize() - days[0]).dt.days).to_numpy()
    si = pd.Series(np.arange(len(stores)), index=stores["store_id"]).reindex(r["store_id"]).to_numpy()
    ok = (r["local_ts"] < cfg.increment_end + pd.Timedelta(days=1)).to_numpy() & \
        open_m[np.clip(di, 0, len(days) - 1), si]
    r = r[ok].reset_index(drop=True)
    s = stores.set_index("store_id")
    r["province"] = r["store_id"].map(s["province"]).to_numpy()
    r["line_discount"] = r["line_discount"].astype(float)
    r["line_tax"] = np.round((r["qty"] * r["unit_price"] - r["line_discount"]) * r["province"].map(ref.TAX_RATES), 2)
    r["register"] = rng.integers(1, 7, len(r))
    r["cashier_id"] = [f"E{x}{k:02d}" for x, k in zip(r["store_id"], rng.integers(1, 13, len(r)))]
    r["tender_type"] = rng.choice(["original_tender", "store_credit"], size=len(r), p=[.8, .2])
    r["employee_sale"] = False
    r["is_return"] = True
    r["orig_txn_ref"] = None
    r["basket_src"] = -1
    keep = ["store_id", "local_ts", "register", "tender_type", "cashier_id", "customer_id", "employee_sale",
            "sku", "qty", "currency", "province", "unit_price", "promo_code", "line_discount", "line_tax",
            "orig_txn_ref", "orig_order_ref", "is_return", "basket_src", "orig_basket"]
    return r[keep]
