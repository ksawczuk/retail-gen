"""Independent checks: re-read the generated files and confirm the answer key matches them.

    python validate.py out

It never imports the generator, so it can't share the generator's bugs. Prints one line per
check and exits non-zero if any fails.
"""
import csv
import glob
import gzip
import io
import json
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def files(root, pattern):
    return sorted(Path(p) for p in glob.glob(str(root / pattern), recursive=True))


def main(out):
    out = Path(out)
    stage = out / "landing_staging"
    man = json.loads((out / "answer_key" / "defects_manifest.json").read_text(encoding="utf-8"))
    D = {d["defect_id"]: d for d in man["defects"]}
    cnt = lambda k: D[k]["count"] if k in D else 0

    on_disk = {p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()}
    check("manifest lists exactly the files on disk", on_disk == set(man["files"]),
          f"{len(on_disk)} on disk, {len(man['files'])} listed")

    crlf, boms = [], []
    for p in stage.rglob("*"):
        if not p.is_file() or p.suffix == ".parquet":
            continue
        data = gzip.decompress(p.read_bytes()) if p.suffix == ".gz" else p.read_bytes()
        if b"\r\n" in data:
            crlf.append(p.name)
        if data.startswith(b"\xef\xbb\xbf"):
            boms.append(p.name)
    check("no CRLF line endings anywhere", not crlf, ", ".join(crlf[:3]))
    check("only the CRM full extract has a BOM", boms == ["customers_full_20260930.csv"], str(boms))

    # web: truncated lines and duplicate event ids
    bad, ids = 0, []
    for p in files(stage, "**/web/events/*.jsonl.gz"):
        for line in gzip.decompress(p.read_bytes()).decode("utf-8").splitlines():
            try:
                ids.append(json.loads(line)["event_id"])
            except json.JSONDecodeError:
                bad += 1
    check("web truncated lines = manifest", bad == cnt("web.truncated_lines"), f"{bad} vs {cnt('web.truncated_lines')}")
    dups = len(ids) - len(set(ids))
    check("web duplicate event_ids = manifest", dups == cnt("web.duplicate_events"), f"{dups} vs {cnt('web.duplicate_events')}")

    # other JSON Lines parse cleanly
    broken = 0
    for p in files(stage, "**/*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                json.loads(line)
            except json.JSONDecodeError:
                broken += 1
    check("all other JSONL lines parse", broken == 0, f"{broken} broken")

    # POS: malformed rows (column count) in history, and cp1252 only from Quebec stores
    wrong = 0
    for p in files(stage, "history/pos/transactions/*.csv"):
        rows = list(csv.reader(io.StringIO(p.read_text(encoding="utf-8"))))
        wrong += sum(1 for r in rows[1:] if len(r) != len(rows[0]))
    check("POS malformed rows = manifest", wrong == cnt("pos.malformed_rows"), f"{wrong} vs {cnt('pos.malformed_rows')}")
    non_utf8 = []
    for p in files(stage, "increments/**/pos/transactions/*.csv"):
        try:
            p.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            non_utf8.append(p.name)
    check("non-UTF-8 POS files are all Quebec stores", all(n.split("_")[1][:3] in ("MTL", "QUE") for n in non_utf8),
          f"{len(non_utf8)} cp1252 files")
    empties = [p.name for p in files(stage, "**/*") if p.is_file() and p.stat().st_size == 0]
    check("exactly one empty file", len(empties) == 1, str(empties))

    # OMS
    hist_orders = pd.concat(pd.read_parquet(p) for p in files(stage, "history/oms/orders/*.parquet"))
    d = int(hist_orders.duplicated().sum())
    check("OMS exact duplicate history orders = manifest", d == cnt("oms.exact_duplicate_orders"),
          f"{d} vs {cnt('oms.exact_duplicate_orders')}")
    all_orders = pd.concat(pd.read_parquet(p, columns=["order_id", "order_ts"]) for p in files(stage, "**/oms/orders/*.parquet"))
    fut = all_orders.loc[all_orders["order_ts"] > pd.Timestamp("2026-11-01", tz="UTC"), "order_id"].nunique()
    check("OMS future-dated orders = manifest", fut == cnt("oms.future_dated_orders"), f"{fut} vs {cnt('oms.future_dated_orders')}")
    lines = pd.concat(pd.read_parquet(p, columns=["order_id", "sku"]) for p in files(stage, "**/oms/order_lines/*.parquet"))
    orph = int((~lines["order_id"].isin(set(all_orders["order_id"]))).sum())
    check("OMS orphan order lines = manifest", orph == cnt("oms.orphan_order_lines"), f"{orph} vs {cnt('oms.orphan_order_lines')}")

    # POS SKUs missing from PIM
    pim = set()
    for p in files(stage, "**/pim/products/*.jsonl"):
        pim |= {json.loads(l)["sku"] for l in p.read_text(encoding="utf-8").splitlines()}
    pos_skus = set()
    for p in files(stage, "**/pos/transactions/*.csv"):
        if p.stat().st_size == 0:
            continue
        enc = "utf-8"
        try:
            text = p.read_bytes().decode(enc)
        except UnicodeDecodeError:
            text = p.read_bytes().decode("cp1252")
        rows = list(csv.reader(io.StringIO(text)))
        i = rows[0].index("SKU")
        pos_skus |= {r[i].zfill(6) for r in rows[1:] if len(r) == len(rows[0])}
    missing = sorted(pos_skus - pim)
    check("POS SKUs never in PIM = manifest keys", missing == sorted(D["pos.skus_never_in_pim"]["keys"]), str(missing))
    lsku = set(lines["sku"])
    late = set(D["pim.late_arriving_new_skus"]["keys"])
    check("every online SKU eventually appears in PIM", lsku <= pim | late, f"{len(lsku - pim)} not in PIM")

    # FX and inventory
    fx = pd.concat([pd.read_csv(p) for p in files(stage, "**/finance/fx_rates/*.csv")])
    inv_n = int((fx["rate"] < 1).sum())
    check("FX inverted rates = manifest", inv_n == cnt("finance.inverted_rate"), f"{inv_n} vs {cnt('finance.inverted_rate')}")
    inv = pd.concat(pd.read_parquet(p, columns=["on_hand"]) for p in files(stage, "**/inventory/snapshots/*.parquet"))
    neg = int((inv["on_hand"] < 0).sum())
    check("negative on_hand = manifest", neg == cnt("inventory.negative_on_hand"), f"{neg} vs {cnt('inventory.negative_on_hand')}")

    # CRM
    cf = pd.read_csv(stage / "history/crm/customers/customers_full_20260930.csv", dtype=str, keep_default_na=False,
                     encoding="utf-8-sig")
    d = int(cf.duplicated().sum())
    check("CRM exact duplicate rows = manifest", d == cnt("crm.exact_duplicate_rows"), f"{d} vs {cnt('crm.exact_duplicate_rows')}")
    addr = pd.read_csv(stage / "history/crm/customer_addresses/customer_addresses_full_20260930.csv", dtype=str)
    o = int((~addr["CUST_ID"].isin(set(cf["CUST_ID"]))).sum())
    check("CRM orphan addresses = manifest", o == cnt("crm.orphan_addresses"), f"{o} vs {cnt('crm.orphan_addresses')}")

    # row counts recorded for Parquet files match the files
    mism = [k for k, v in man["files"].items() if v["kind"] == "parquet" and
            pq.read_metadata(stage / k).num_rows != v["rows"]]
    check("Parquet row counts match manifest", not mism, ", ".join(mism[:3]))

    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "out"))
