"""Clean truth for slow-moving reference data: FX rates, stores, catalogue, promotions."""
import numpy as np
import pandas as pd

from .. import reference as ref

NS = "datetime64[ns]"


# ---------------------------------------------------------------- FX
def generate_fx(cfg, rng) -> pd.DataFrame:
    """Daily USD->CAD rate (CAD per 1 USD) for every calendar day, as a bounded random walk."""
    days = pd.date_range(cfg.history_start - pd.Timedelta(days=10), cfg.increment_end, freq="D")
    rate = 1.36 * np.exp(np.cumsum(rng.normal(0, 0.003, len(days))))
    return pd.DataFrame({"date": days.astype(NS), "usd_cad": np.clip(rate, 1.28, 1.46).round(4)})


def fx_on(fx: pd.DataFrame, ts) -> np.ndarray:
    """USD->CAD rate for each timestamp's calendar day."""
    m = pd.Series(fx["usd_cad"].to_numpy(), index=fx["date"].to_numpy())
    days = pd.DatetimeIndex(pd.to_datetime(ts)).normalize().astype(NS)
    return m.reindex(days).to_numpy()


# ---------------------------------------------------------------- stores
def generate_stores(cfg, rng):
    """Store master plus two dated events: a recode/rename (day 12) and a closure (day 20)."""
    n = cfg.n_stores
    w = np.array([c[6] for c in ref.CITIES], float)
    idx = list(rng.choice(len(ref.CITIES), size=n, p=w / w.sum()))
    qc = [i for i, c in enumerate(ref.CITIES) if c[1] == "QC"]
    us = [i for i, c in enumerate(ref.CITIES) if c[2] == "US"]
    if not any(ref.CITIES[i][1] == "QC" for i in idx):
        idx[0] = qc[0]
    if not any(ref.CITIES[i][2] == "US" for i in idx):
        idx[1] = us[0]
    idx.sort()
    counters, rows = {}, []
    for k, ci in enumerate(idx):
        city, prov, country, tz, _, _, _, code = ref.CITIES[ci]
        counters[code] = counters.get(code, 0) + 1
        c = counters[code]
        opened = pd.Timestamp("2012-01-01") + pd.Timedelta(days=int(rng.integers(0, 365 * 12)))
        rows.append({"store_id": 101 + k, "store_code": f"{code}-{c:03d}",
                     "store_name": f"Larchwood {city}" + (f" {c}" if c > 1 else ""),
                     "city": city, "province": prov, "country": country, "timezone": tz,
                     "sqft": int(rng.integers(16, 60)) * 500, "opened_at": opened, "closed_at": pd.NaT})
    stores = pd.DataFrame(rows)
    new_idx = 2 if n > 4 else n - 1
    stores.loc[new_idx, "opened_at"] = pd.Timestamp("2025-06-14")
    stores["opened_at"] = stores["opened_at"].astype(NS)
    stores["closed_at"] = stores["closed_at"].astype(NS)

    recode_pos = int(stores.index[stores["province"] == "QC"][0])
    recode = stores.loc[recode_pos]
    city_code = recode["store_code"].split("-")[0]
    events = [{"day": cfg.increment_day(12), "store_id": int(recode["store_id"]),
               "store_code": f"{city_code}-1{int(recode['store_code'][-2:]):02d}",
               "store_name": f"Larchwood {recode['city']} Centre-Ville"}]
    closable = [i for i in stores.index if i not in (recode_pos, new_idx)]
    close_pos = closable[len(closable) // 2]
    events.append({"day": cfg.increment_day(20), "store_id": int(stores.loc[close_pos, "store_id"]),
                   "closed_at": cfg.increment_day(20)})
    return stores, events


def stores_as_of(stores: pd.DataFrame, events, day) -> pd.DataFrame:
    """Store master with every event on or before `day` applied."""
    s = stores.copy().set_index("store_id")
    for e in events:
        if e["day"] <= pd.Timestamp(day):
            for k, v in e.items():
                if k not in ("day", "store_id"):
                    s.loc[e["store_id"], k] = v
    return s.reset_index()


def store_open_matrix(stores, events, days: pd.DatetimeIndex) -> np.ndarray:
    """Boolean [day, store] matrix: is the store trading that day."""
    closed = stores["closed_at"].copy()
    for e in events:
        if "closed_at" in e:
            closed[stores["store_id"] == e["store_id"]] = e["closed_at"]
    d = days.to_numpy()[:, None]
    opened = stores["opened_at"].to_numpy()[None, :]
    cl = closed.to_numpy()[None, :]
    return (opened <= d) & (pd.isna(cl) | (d < cl))


# ---------------------------------------------------------------- catalogue
def generate_catalog(cfg, rng):
    """Category tree, suppliers, products (one row per SKU variant) and SCD2 price history."""
    cat_rows, leaf = [], []
    cid = 10
    for dept, cats in ref.CATALOG.items():
        dept_id = cid
        cat_rows.append({"category_id": dept_id, "category_name": dept, "parent_id": None, "level": 1})
        cid += 1
        for cname, spec in cats.items():
            cat_rows.append({"category_id": cid, "category_name": cname, "parent_id": dept_id, "level": 2})
            leaf.append((cid, cname, dept, spec))
            cid += 1
    categories = pd.DataFrame(cat_rows)

    pairs = [(p, s) for p in ref.SUPPLIER_PREFIXES for s in ref.SUPPLIER_SUFFIXES]
    sp = rng.choice(len(pairs), size=min(cfg.n_suppliers, len(pairs)), replace=False)
    suppliers = pd.DataFrame({
        "supplier_id": [f"SUP-{i + 1:03d}" for i in range(len(sp))],
        "supplier_name": [f"{pairs[j][0]} {pairs[j][1]}" for j in sp],
        "country": rng.choice(["CA", "US", "VN", "PT", "CN", "MX"], size=len(sp), p=[.4, .2, .15, .1, .1, .05]),
    })

    n = cfg.n_products
    sku_ints = rng.choice(np.arange(1000, 200000), size=n, replace=False)
    leaf_i = rng.integers(0, len(leaf), size=n)
    rows = []
    h0, h1, i1 = cfg.history_start, cfg.history_end, cfg.increment_end
    launch_kind = rng.choice(3, size=n, p=[0.80, 0.17, 0.03])
    launch_kind[:2] = 2  # at least two in-window launches even at tiny scale
    for k in range(n):
        cat_id, cname, dept, (adjs, nouns, (lo, hi), sized) = leaf[leaf_i[k]]
        color = ref.COLORS[rng.integers(len(ref.COLORS))]
        size = ref.SIZES[rng.integers(len(ref.SIZES))] if sized else None
        base = round(float(np.floor(rng.uniform(lo, hi))) + 0.99, 2)
        if launch_kind[k] == 0:
            launched = pd.Timestamp("2021-01-01") + pd.Timedelta(days=int(rng.integers(0, 1460)))
        elif launch_kind[k] == 1:
            launched = h0 + pd.Timedelta(days=int(rng.integers(0, (h1 - h0).days)))
        else:
            launched = h1 + pd.Timedelta(days=int(rng.integers(1, (i1 - h1).days - 3)))
        rows.append({"sku": f"{sku_ints[k]:06d}",
                     "product_name": f"{adjs[rng.integers(len(adjs))]} {nouns[rng.integers(len(nouns))]}",
                     "category_id": cat_id, "category_name": cname, "department": dept,
                     "supplier_id": suppliers["supplier_id"].iloc[rng.integers(len(suppliers))],
                     "color": color, "size": size, "base_price": base,
                     "launched_at": launched, "pim_excluded": False})
    products = pd.DataFrame(rows)
    # Store-local items sold at POS that the PIM never learns about.
    local = pd.DataFrame([{"sku": f"99{k:04d}", "product_name": name, "category_id": None,
                           "category_name": None, "department": None, "supplier_id": None,
                           "color": None, "size": None, "base_price": price,
                           "launched_at": pd.Timestamp("2023-05-01"), "pim_excluded": True}
                          for k, (name, price) in enumerate([("Local Honey 500g", 12.99),
                                                             ("Gift Wrap Service", 4.99),
                                                             ("Reusable Tote", 2.99)], start=1)])
    products = pd.concat([products, local], ignore_index=True)
    products["launched_at"] = products["launched_at"].astype(NS)
    products["popularity"] = rng.lognormal(0, 1.1, len(products))
    products.loc[products["pim_excluded"], "popularity"] = 3.0
    disc = rng.random(len(products)) < 0.04
    disc_at = products["launched_at"] + pd.to_timedelta(rng.integers(200, 900, len(products)), unit="D")
    products["discontinued_at"] = disc_at.where(disc & (disc_at < i1)).astype(NS)

    price_history = _price_history(cfg, rng, products)
    return categories, suppliers, products, price_history


def _price_history(cfg, rng, products) -> pd.DataFrame:
    rows = []
    for p in products.itertuples(index=False):
        price, start = p.base_price, p.launched_at
        n_changes = 0 if p.pim_excluded else rng.poisson(1.2)
        lo = max(start + pd.Timedelta(days=30), pd.Timestamp("2024-06-01"))
        span = (cfg.increment_end - lo).days
        dates = sorted(lo + pd.Timedelta(days=int(d)) for d in rng.integers(0, span, n_changes)) if span > 1 else []
        reason = "launch"
        for d in dates:
            if d <= start:
                continue
            rows.append({"sku": p.sku, "price": price, "valid_from": start, "valid_to": d, "reason": reason})
            mult = float(rng.choice([0.8, 0.85, 0.9, 1.05, 1.1]))
            price = round(float(np.floor(price * mult)) + 0.99, 2)
            reason = "markdown" if mult < 1 else "increase"
            start = d
        rows.append({"sku": p.sku, "price": price, "valid_from": start, "valid_to": pd.NaT, "reason": reason})
    ph = pd.DataFrame(rows)
    ph["valid_from"] = ph["valid_from"].astype(NS)
    ph["valid_to"] = ph["valid_to"].astype(NS)
    return ph


def price_lookup(price_history: pd.DataFrame, skus, ts) -> np.ndarray:
    """Price in effect for each (sku, timestamp) pair."""
    left = pd.DataFrame({"sku": np.asarray(skus, dtype=object).astype(str),
                         "ts": pd.to_datetime(ts).astype(NS), "pos": np.arange(len(skus))})
    left = left.sort_values("ts")
    right = price_history[["sku", "valid_from", "price"]].copy()
    right["sku"] = right["sku"].astype(str)
    right = right.sort_values("valid_from")
    m = pd.merge_asof(left, right, left_on="ts", right_on="valid_from", by="sku", direction="backward")
    if m["price"].isna().any():  # a sale stamped before launch: fall back to the first price
        first = price_history.sort_values("valid_from").drop_duplicates("sku").set_index("sku")["price"]
        m.loc[m["price"].isna(), "price"] = m.loc[m["price"].isna(), "sku"].map(first)
    out = np.empty(len(skus))
    out[m["pos"].to_numpy()] = m["price"].to_numpy()
    return out


# ---------------------------------------------------------------- promotions
def generate_promotions(cfg) -> pd.DataFrame:
    """Seasonal promo calendar for 2025-2026 plus an evergreen welcome code."""
    rows = [("WELCOME10", "pct", 10, None, "2024-01-01", None, "web,app")]
    for year in (2025, 2026):
        yy = str(year)[2:]
        rows += [
            (f"TAKE20-{yy}", "fixed", 20, 100, f"{year}-02-01", f"{year}-02-28", "web,app"),
            (f"SPRING{yy}", "pct", 15, None, f"{year}-03-15", f"{year}-04-15", "web,app,pos"),
            (f"SAVE10-{yy}", "fixed", 10, 50, f"{year}-05-15", f"{year}-06-15", "web,app"),
            (f"SUMMER{yy}", "pct", 20, None, f"{year}-07-01", f"{year}-07-31", "web,app,pos"),
            (f"FALL{yy}", "pct", 10, None, f"{year}-09-20", f"{year}-10-20", "web,app"),
            (f"BFRIDAY{yy}", "pct", 25, None, f"{year}-11-24", f"{year}-12-01", "web,app,pos"),
            (f"BOXING{yy}", "pct", 30, None, f"{year}-12-26", f"{year + 1}-01-02", "web,app,pos"),
        ]
    rows.append(("HALLOWEEN26", "pct", 15, None, "2026-10-24", "2026-10-31", "web,app,pos"))
    p = pd.DataFrame(rows, columns=["code", "promo_type", "value", "min_spend", "starts_at", "ends_at", "channels"])
    p["starts_at"] = pd.to_datetime(p["starts_at"]).astype(NS)
    p["ends_at"] = pd.to_datetime(p["ends_at"]).astype(NS)
    p["created_at"] = (p["starts_at"] - pd.Timedelta(days=14)).astype(NS)
    p.loc[p["code"] == "HALLOWEEN26", "created_at"] = cfg.increment_day(15)
    p = p[p["created_at"] <= cfg.increment_end].reset_index(drop=True)
    p.insert(0, "promo_id", [f"P-{i + 1:04d}" for i in range(len(p))])
    return p
