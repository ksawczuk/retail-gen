"""PIM / merchandising: nested JSON Lines. Full catalogue at cut-over, then daily deltas."""
import numpy as np
import pandas as pd

from ..util import pick_rows
from .common import is_null

SRC = "pim"


def _name_noise(rng, s):
    return [s.upper(), s.lower(), " " + s, s + "  ", s.title()][rng.integers(5)]


def _product_record(p, cat_id, cat_name, sup_id, sup_name, price, status, updated):
    title = f"{p.product_name} - {p.color}" + (f" / {p.size}" if not is_null(p.size) else "")
    return {"sku": p.sku, "title": title,
            "category": {"id": cat_id, "name": cat_name, "department": p.department},
            "supplier": {"id": sup_id, "name": sup_name},
            "attributes": {"color": p.color, "size": None if is_null(p.size) else p.size},
            "pricing": {"list_price": price, "currency": "CAD"},
            "status": status, "launch_date": f"{p.launched_at:%Y-%m-%d}",
            "updated_at": f"{updated:%Y-%m-%dT%H:%M:%SZ}"}


def emit(cfg, rng, t, out, man):
    he = cfg.history_end + pd.Timedelta(days=1)
    prods = t.products[~t.products["pim_excluded"]].reset_index(drop=True)

    # ---------------- categories, with casing noise and a duplicate category
    cats = t.categories.copy()
    noisy = rng.random(len(cats)) < 0.3
    cats["category_name"] = [_name_noise(rng, n) if z else n for n, z in zip(cats["category_name"], noisy)]
    man.record("pim.category_name_noise", noisy.sum(), keys=cats["category_id"][noisy])
    leaf = cats[cats["level"] == 2]
    dup_src = leaf.iloc[int(rng.integers(len(leaf)))]
    dup_id = int(cats["category_id"].max()) + 50
    cats = pd.concat([cats, pd.DataFrame([{"category_id": dup_id,
                                           "category_name": " " + str(dup_src["category_name"]).strip().lower(),
                                           "parent_id": dup_src["parent_id"], "level": 2}])], ignore_index=True)
    out.jsonl([{"category_id": int(r.category_id), "category_name": r.category_name,
                "parent_id": None if is_null(r.parent_id) else int(r.parent_id)}
               for r in cats.itertuples(index=False)], None, SRC, "categories", "categories.jsonl")
    cat_name = cats.drop_duplicates("category_id").set_index("category_id")["category_name"]
    in_dup = (prods["category_id"] == dup_src["category_id"]) & (rng.random(len(prods)) < 0.25)
    prod_cat = np.where(in_dup, dup_id, prods["category_id"].astype(int)).astype(int)
    man.record("pim.duplicate_category", in_dup.sum(), keys=prods["sku"][in_dup],
               dup_id=dup_id, src_id=int(dup_src["category_id"]))

    # ---------------- suppliers, with a near-duplicate
    sups = t.suppliers.copy()
    s0 = sups.iloc[0]
    dup_sid = f"SUP-{len(sups) + 101:03d}"
    sups = pd.concat([sups, pd.DataFrame([{"supplier_id": dup_sid, "supplier_name": s0["supplier_name"].upper() + " LTD",
                                           "country": s0["country"]}])], ignore_index=True)
    out.jsonl(sups.to_dict("records"), None, SRC, "suppliers", "suppliers.jsonl")
    sup_name = sups.set_index("supplier_id")["supplier_name"]
    sdup = (prods["supplier_id"] == s0["supplier_id"]) & (rng.random(len(prods)) < 0.3)
    prod_sup = np.where(sdup, dup_sid, prods["supplier_id"])
    man.record("pim.duplicate_supplier", sdup.sum(), keys=prods["sku"][sdup],
               dup_id=dup_sid, src_id=s0["supplier_id"])

    # ---------------- products
    ph = t.price_history

    def price_at(sku, ts):
        r = ph[(ph["sku"] == sku) & (ph["valid_from"] <= ts)]
        return float(r.sort_values("valid_from")["price"].iloc[-1])

    hist_mask = (prods["launched_at"] < he).to_numpy()
    recs, title_noise = [], []
    for i, p in enumerate(prods.itertuples(index=False)):
        if not hist_mask[i]:
            continue
        status = "discontinued" if (not is_null(p.discontinued_at) and p.discontinued_at < he) else "active"
        r = _product_record(p, int(prod_cat[i]), cat_name[prod_cat[i]], prod_sup[i], sup_name[prod_sup[i]],
                            price_at(p.sku, cfg.history_end), status, min(he - pd.Timedelta(hours=3), p.launched_at + pd.Timedelta(days=2)))
        if rng.random() < 0.01:
            r["title"] = _name_noise(rng, r["title"])
            title_noise.append(p.sku)
        recs.append(r)
    out.jsonl(recs, None, SRC, "products", "products_full_20260930.jsonl")
    man.record("pim.title_noise", len(title_noise), keys=title_noise)

    # deltas: new SKUs (arriving 1-4 days AFTER they start selling) and discontinuations
    delta = {}
    late_skus = []
    for i, p in enumerate(prods.itertuples(index=False)):
        if hist_mask[i]:
            continue
        lag = int(rng.integers(1, 5))
        day = (p.launched_at + pd.Timedelta(days=lag)).normalize()
        late_skus.append(p.sku)
        if day <= cfg.increment_end:
            delta.setdefault(day, []).append(_product_record(
                p, int(prod_cat[i]), cat_name[prod_cat[i]], prod_sup[i], sup_name[prod_sup[i]],
                price_at(p.sku, p.launched_at), "active", day + pd.Timedelta(hours=6)))
    man.record("pim.late_arriving_new_skus", len(late_skus), keys=late_skus)
    for i, p in enumerate(prods.itertuples(index=False)):
        if hist_mask[i] and not is_null(p.discontinued_at) and he <= p.discontinued_at <= cfg.increment_end:
            day = p.discontinued_at.normalize()
            delta.setdefault(day, []).append(_product_record(
                p, int(prod_cat[i]), cat_name[prod_cat[i]], prod_sup[i], sup_name[prod_sup[i]],
                price_at(p.sku, day), "discontinued", day + pd.Timedelta(hours=6)))
    for day, recs in sorted(delta.items()):
        out.jsonl(recs, day, SRC, "products", f"products_delta_{day:%Y%m%d}.jsonl")

    # ---------------- price history (full) + price change notifications (increments)
    h = ph[(ph["valid_from"] < he) & ph["sku"].isin(prods["sku"])].copy()
    h["valid_to"] = h["valid_to"].where(h["valid_to"] < he)
    h = h.reset_index(drop=True)
    multi = h[h.duplicated("sku", keep=False)]
    firsts = multi.drop_duplicates("sku", keep="first").index.to_numpy()
    ov = rng.choice(firsts, size=min(len(firsts), cfg.count(0.02 * len(prods), 2)), replace=False) if len(firsts) else []
    h.loc[ov, "valid_to"] = h.loc[ov, "valid_to"] + pd.Timedelta(days=7)
    man.record("pim.price_overlap", len(ov), keys=h.loc[ov, "sku"])
    closed = h.index[h["valid_to"].notna()].to_numpy()
    inv = rng.choice(closed, size=min(len(closed), cfg.count(3, 1)), replace=False) if len(closed) else []
    vf = h.loc[inv, "valid_from"].copy()
    h.loc[inv, "valid_from"] = h.loc[inv, "valid_to"]
    h.loc[inv, "valid_to"] = vf
    man.record("pim.price_inverted_interval", len(inv), keys=h.loc[inv, "sku"])
    recs, as_text, open_tokens = [], [], 0
    for r in h.itertuples(index=False):
        price = r.price
        if rng.random() < 0.03:
            price = f"${r.price:,.2f}"
            as_text.append(r.sku)
        if is_null(r.valid_to):
            k = rng.integers(3)
            end = [None, "9999-12-31", ""][k]
            open_tokens += k > 0
        else:
            end = f"{r.valid_to:%Y-%m-%d}"
        recs.append({"sku": r.sku, "price": price, "currency": "CAD",
                     "effective_from": f"{r.valid_from:%Y-%m-%d}", "effective_to": end})
    out.jsonl(recs, None, SRC, "price_history", "price_history_full_20260930.jsonl")
    man.record("pim.price_as_text", len(as_text), keys=as_text)
    man.record("pim.open_end_tokens", open_tokens)

    ch = ph[(ph["valid_from"] >= he) & (ph["valid_from"] <= cfg.increment_end) & ph["sku"].isin(prods["sku"])]
    ch = ch[ch["reason"] != "launch"].copy()
    deliver = ch["valid_from"].dt.normalize()
    retro = rng.random(len(ch)) < 0.1
    deliver = deliver.where(~retro, deliver + pd.to_timedelta(rng.integers(2, 6, len(ch)), unit="D"))
    man.record("pim.retroactive_price_changes", int(retro.sum()), keys=ch["sku"][retro])
    for day, g in ch.groupby(deliver.to_numpy()):
        if day > cfg.increment_end:
            continue
        out.jsonl([{"sku": r.sku, "new_price": r.price, "currency": "CAD",
                    "effective_from": f"{r.valid_from:%Y-%m-%dT%H:%M:%S}", "change_reason": r.reason}
                   for r in g.itertuples(index=False)], day, SRC, "price_changes", f"price_changes_{day:%Y%m%d}.jsonl")
