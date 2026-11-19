"""In-store POS: CSV uploaded by each store's back-office PC. Amounts in cents, local time,
one row per basket line. History arrives as monthly consolidated files, then one file per
store per day."""
import numpy as np
import pandas as pd

from .. import reference as ref
from ..util import pick_rows
from .common import route, by_month, cents, is_null

SRC = "pos"


def emit(cfg, rng, t, out, man):
    p = t.pos_lines.copy().reset_index(drop=True)
    stores = t.stores.set_index("store_id")
    qc = set(stores.index[stores["province"] == "QC"])

    code = p["store_id"].map(stores["store_code"]).astype(object)
    for e in t.store_events:
        if "store_code" in e:
            m = (p["store_id"] == e["store_id"]) & (p["local_ts"] >= e["day"])
            code[m] = e["store_code"]

    prod = t.products.set_index("sku")
    is_qc = p["store_id"].isin(qc).to_numpy()
    color = p["sku"].map(prod["color"])
    color = np.where(is_qc, color.map(lambda c: ref.COLORS_FR.get(c, c)), color)
    size = p["sku"].map(prod["size"])
    desc = [f"{n} {c}" + ("" if is_null(s) else f" {s}") if not is_null(c) else n
            for n, c, s in zip(p["sku"].map(prod["product_name"]), color, size)]

    loyalty = p["customer_id"].map(t.customers.set_index("customer_id")["loyalty_number"])
    nocard = loyalty.isna().to_numpy()
    loyalty = loyalty.astype(object)
    # each register firmware writes "no card" its own way, consistently within a basket
    token = pd.Series(["", "0", "NONE"])[(pd.util.hash_array(p["txn_id"].to_numpy()) % 3).astype(int)].to_numpy()
    loyalty[nocard] = token[nocard]

    when = np.where(is_qc, p["local_ts"].dt.strftime("%d/%m/%Y %H:%M:%S"), p["local_ts"].dt.strftime("%Y-%m-%d %H:%M:%S"))
    unit = cents(p["unit_price"])
    disc = cents(p["line_discount"])
    tax = cents(p["line_tax"])
    df = pd.DataFrame({
        "TXN_ID": p["txn_id"], "STORE_CODE": code.to_numpy(), "REGISTER_NO": p["register"],
        "TXN_DATETIME": when, "CASHIER": p["cashier_id"], "LOYALTY_CARD": loyalty.to_numpy(),
        "LINE_NO": p["line_no"], "SKU": p["sku"].astype(int).astype(str), "DESCRIPTION": desc,
        "QTY": p["qty"], "UNIT_PRICE_CENTS": unit, "DISC_CENTS": disc, "TAX_CENTS": tax,
        "LINE_TOTAL_CENTS": p["qty"].to_numpy() * unit - disc + tax, "TENDER": p["tender_type"],
        "ORIG_TXN_ID": p["orig_txn_ref"], "ORIG_ORDER_REF": p["orig_order_ref"], "PROMO": p["promo_code"],
    })
    n = len(df)
    man.record("pos.sku_leading_zeros_dropped", n)
    man.record("pos.amounts_in_cents", n)
    man.record("pos.currency_not_labelled", int(p["currency"].eq("USD").sum()))
    man.record("pos.local_time_no_zone", n)
    man.record("pos.quebec_day_first_dates", int(is_qc.sum()))
    man.record("pos.returns_negative_qty", int(p["is_return"].sum()))
    man.record("pos.cross_channel_returns", int(p["orig_order_ref"].notna().sum()))
    man.record("pos.loyalty_blank_variants", int(nocard.sum()))
    man.record("pos.employee_purchases", int(p["employee_sale"].sum()))
    local_skus = sorted(set(p["sku"]) & set(t.products.loc[t.products["pim_excluded"], "sku"]))
    man.record("pos.skus_never_in_pim", int(p["sku"].isin(local_skus).sum()), keys=local_skus)
    for e in t.store_events:
        if "store_code" in e:
            n_after = int(((p["store_id"] == e["store_id"]) & (p["local_ts"] >= e["day"])).sum())
            man.record("pos.store_recode", n_after, store_id=e["store_id"], store_code=e["store_code"], day=e["day"])

    # training-mode baskets
    tx = p["txn_id"].drop_duplicates()
    tr_ids = set(tx.iloc[pick_rows(rng, len(tx), cfg.count(0.001 * len(tx), 3))])
    tr = df[df["TXN_ID"].isin(tr_ids)].copy()
    tr["TXN_ID"] = tr["TXN_ID"].str.replace(r"-\d\d-(\d{4})$", r"-99-\1", regex=True)
    tr["REGISTER_NO"] = 99
    tr["CASHIER"] = "TRAINING"
    man.record("pos.training_transactions", len(tr), keys=tr["TXN_ID"].unique())
    df = pd.concat([df, tr]).sort_index(kind="stable").reset_index(drop=True)
    local_ts = pd.concat([p["local_ts"], p.loc[tr.index, "local_ts"]]).sort_index(kind="stable").reset_index(drop=True)
    sid = pd.concat([p["store_id"], p.loc[tr.index, "store_id"]]).sort_index(kind="stable").reset_index(drop=True)

    # embedded newlines (quoted) in a few descriptions
    nl = pick_rows(rng, len(df), cfg.count(5, 2))
    df.loc[nl, "DESCRIPTION"] = df.loc[nl, "DESCRIPTION"] + "\nSPECIAL ORDER"
    man.record("pos.embedded_newline", len(nl), keys=df.loc[nl, "TXN_ID"])

    deliver = local_ts.dt.normalize()
    ca = [s for s in stores.index if stores.loc[s, "country"] == "CA" and s not in qc]
    late_store = ca[len(ca) // 3]
    d5, d6, d8 = cfg.increment_day(5), cfg.increment_day(6), cfg.increment_day(8)
    lm = (sid == late_store) & deliver.isin([d5, d6])
    deliver[lm] = d8
    man.record("pos.offline_store_late_upload", int(lm.sum()), keys=[late_store],
               store=late_store, d5=d5, d6=d6, d8=d8)

    hist, days = route(cfg, df.assign(_sid=sid.to_numpy()), deliver)
    hist = hist.assign(_ts=local_ts[hist.index].to_numpy())
    months = by_month(hist, hist["_ts"])
    month_keys = list(months)
    per_month = np.bincount(rng.integers(0, len(month_keys), cfg.count(0.0002 * len(hist), 2)),
                            minlength=len(month_keys))
    n_bad = 0
    for mi, (m, g) in enumerate(months.items()):
        g = g.drop(columns=["_ts", "_sid"]).reset_index(drop=True)
        chosen = pick_rows(rng, len(g), per_month[mi])
        bad = []
        for k, i in enumerate(chosen):  # k rows already removed before position i
            row = g.iloc[i].copy()
            row["DESCRIPTION"] = str(row["DESCRIPTION"]).replace("\n", " ") + ", gift receipt"
            bad.append((i - k, ",".join("" if is_null(v) else str(v) for v in row.to_numpy())))
        g = g.drop(index=chosen).reset_index(drop=True)
        n_bad += len(bad)
        out.csv(g, None, SRC, "transactions", f"pos_{m}.csv", bad_lines=bad)
    man.record("pos.malformed_rows", n_bad)

    empty_store = ca[(2 * len(ca)) // 3] if len(ca) > 2 else ca[0]
    d3, d14, d15 = cfg.increment_day(3), cfg.increment_day(14), cfg.increment_day(15)
    held = None
    guarded_done, first_written = False, None
    for day, g in days.items():
        for s, gs in g.groupby("_sid"):
            gs = gs.drop(columns=["_sid"])
            fname = f"pos_{gs['STORE_CODE'].iloc[0]}_{day:%Y%m%d}.csv"
            enc = "cp1252" if s in qc else "utf-8"
            if day == d14 and s == empty_store:
                out.empty(day, SRC, "transactions", fname)
                held = (gs, fname)
                continue
            rel = out.csv(gs, day, SRC, "transactions", fname, encoding=enc)
            first_written = first_written or (rel, gs, fname)
            # Run the guarded step on the first day from d3 on that this store has a file (GEN-02)
            if not guarded_done and day >= d3 and s == ca[0]:
                out.duplicate(rel, fname.replace(".csv", "_dup.csv"))
                man.record("pos.duplicate_file", len(gs), keys=[fname], fname=fname)
                guarded_done = True
    # If the store never had a file, run the guarded step on the first file written (GEN-02)
    if not guarded_done and first_written is not None:
        rel, gs, fname = first_written
        out.duplicate(rel, fname.replace(".csv", "_dup.csv"))
        man.record("pos.duplicate_file", len(gs), keys=[fname], fname=fname)
    if held is not None:
        gs, fname = held
        out.csv(gs, d15, SRC, "transactions", fname.replace(".csv", "_resend.csv"))
        man.record("pos.empty_file_then_resend", len(gs), keys=[fname], fname=fname)
    man.record("pos.quebec_files_cp1252", 1)
