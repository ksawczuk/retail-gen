"""CRM: legacy upper-case CSV exports. Full extract at cut-over, then daily CDC files."""
import numpy as np
import pandas as pd

from .. import reference as ref
from ..util import mojibake, pick_rows
from .common import phone_formats, variant, postal_variant, disguised_null, is_null

SRC = "crm"
CUST_COLS = ["CUST_ID", "FIRST_NM", "LAST_NM", "EMAIL_ADDR", "PHONE", "DOB", "LOYALTY_NO",
             "OPT_IN", "CREATED_DT", "LAST_MOD_DT"]
ADDR_COLS = ["ADDR_ID", "CUST_ID", "ADDR_TYPE", "LINE1", "LINE2", "CITY", "PROV", "POSTAL",
             "COUNTRY", "DEFAULT_FLG"]


def _pacific(ts: pd.Series) -> pd.Series:
    """CRM stamps in server local time (Pacific) with no zone marker."""
    return (pd.to_datetime(ts).dt.tz_localize("UTC").dt.tz_convert("America/Vancouver")
            .dt.tz_localize(None).dt.strftime("%Y-%m-%d %H:%M:%S"))


def _customer_frame(cfg, rng, c: pd.DataFrame, man, entity) -> pd.DataFrame:
    n = len(c)
    phone = phone_formats(rng, c["phone"])
    lost = rng.random(n) < 0.04
    tokens = disguised_null(rng, int(lost.sum()))
    phone = np.array(phone, dtype=object)
    phone[lost] = tokens
    man.record(f"crm.{entity}.phone_disguised_null", lost.sum(), keys=c["customer_id"][lost])

    dob = []
    fmts = ["%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y"]
    k = rng.choice(3, size=n, p=[.7, .2, .1])
    n_alt = n_null = 0
    for b, kk in zip(c["birth_date"], k):
        if is_null(b):
            dob.append(["", "0000-00-00", "1900-01-01"][rng.integers(3)])
            n_null += 1
        else:
            dob.append(pd.Timestamp(b).strftime(fmts[kk]))
            n_alt += kk > 0
    man.record(f"crm.{entity}.dob_placeholder", n_null)
    man.record(f"crm.{entity}.dob_mixed_formats", n_alt)

    email = c["email"].to_numpy(dtype=object).copy()
    em = pick_rows(rng, n, int(n * 0.02))
    for i in em:
        email[i] = [email[i].upper(), " " + email[i], email[i] + " ", email[i].title()][rng.integers(4)]
    man.record(f"crm.{entity}.email_case_whitespace", len(em), keys=c["customer_id"].iloc[em])

    opt = [(["Y", "Yes", "1", "y"] if v else ["N", "No", "0", ""])[rng.integers(4)] for v in c["marketing_opt_in"]]
    man.record(f"crm.{entity}.opt_in_variants", n)
    created = _pacific(c["created_at"])
    man.record(f"crm.{entity}.created_dt_local_time", n)
    return pd.DataFrame({"CUST_ID": c["customer_id"].to_numpy(), "FIRST_NM": c["first_name"].to_numpy(),
                         "LAST_NM": c["last_name"].to_numpy(), "EMAIL_ADDR": email, "PHONE": phone,
                         "DOB": dob, "LOYALTY_NO": c["loyalty_number"].to_numpy(), "OPT_IN": opt,
                         "CREATED_DT": created.to_numpy(), "LAST_MOD_DT": created.to_numpy()})


def _address_frame(rng, a: pd.DataFrame, man, entity) -> pd.DataFrame:
    n = len(a)
    line1 = a["line1"].to_numpy(dtype=object).copy()
    line2 = a["line2"].to_numpy(dtype=object).copy()
    merged = 0
    for i in range(n):
        if not is_null(line2[i]) and rng.random() < 0.3:
            line1[i] = f"{line2[i]}, {line1[i]}"
            line2[i] = None
            merged += 1
    man.record(f"crm.{entity}.addr_unit_in_line1", merged)
    nl = pick_rows(rng, n, max(1, int(n * 0.002)))
    for i in nl:
        line1[i] = f"{line1[i]}\nBuzzer {rng.integers(1, 99)}"
    man.record(f"crm.{entity}.addr_embedded_newline", len(nl), keys=a["address_id"].iloc[nl])
    man.record(f"crm.{entity}.province_variants", n)
    man.record(f"crm.{entity}.postal_variants", n)
    man.record(f"crm.{entity}.country_variants", n)
    return pd.DataFrame({
        "ADDR_ID": a["address_id"].to_numpy(), "CUST_ID": a["customer_id"].to_numpy(),
        "ADDR_TYPE": a["address_type"].map({"billing": "B", "shipping": "S"}).to_numpy(),
        "LINE1": line1, "LINE2": line2, "CITY": a["city"].to_numpy(),
        "PROV": variant(rng, a["province"], ref.PROVINCE_VARIANTS),
        "POSTAL": postal_variant(rng, a["postal_code"]),
        "COUNTRY": variant(rng, a["country"], ref.COUNTRY_VARIANTS),
        "DEFAULT_FLG": np.where(a["is_default"].astype(bool), "Y", "N"),
    })


def emit(cfg, rng, t, out, man):
    he = cfg.history_end + pd.Timedelta(days=1)
    # ---------------- history: full extract at cut-over
    c = t.customers[t.customers["created_at"] < he].reset_index(drop=True)
    # A member who joins after the cut-over has no loyalty number in the extract yet
    later = (c["loyalty_join_at"] >= he).to_numpy()
    c.loc[later, ["loyalty_number", "loyalty_tier"]] = None
    # Email unsubscribes the CRM had learned by the cut-over show as opted out
    synced = t.consent_sync[t.consent_sync["crm_synced_at"] < he]
    c.loc[c["customer_id"].isin(synced["customer_id"]), "marketing_opt_in"] = False
    lagging = t.consent_sync[t.consent_sync["crm_synced_at"].isna() | (t.consent_sync["crm_synced_at"] >=
                                                                         t.consent_sync["unsubscribed_at"].dt.normalize()
                                                                         + pd.Timedelta(days=1))]
    man.record("crm.consent_sync_lag", len(lagging), keys=lagging["customer_id"])
    cf = _customer_frame(cfg, rng, c, man, "customers")
    accented = cf["FIRST_NM"].str.cat(cf["LAST_NM"]).map(lambda s: any(ord(ch) > 127 for ch in s))
    mj = accented & (rng.random(len(cf)) < 0.3)
    cf.loc[mj, "FIRST_NM"] = cf.loc[mj, "FIRST_NM"].map(mojibake)
    cf.loc[mj, "LAST_NM"] = cf.loc[mj, "LAST_NM"].map(mojibake)
    man.record("crm.mojibake_names", mj.sum(), keys=cf.loc[mj, "CUST_ID"])
    dup_pairs = c[c.duplicated("person_id", keep=False)].groupby("person_id")["customer_id"].apply(list)
    man.record("crm.near_duplicate_customers", len(dup_pairs), keys=["|".join(p) for p in dup_pairs])
    emp = c["is_employee"].to_numpy()
    man.record("crm.employee_accounts", emp.sum(), keys=c["customer_id"][emp], domain=cfg.employee_domain)
    di = pick_rows(rng, len(cf), cfg.count(150, 3))
    cf = pd.concat([cf, cf.iloc[di]]).sample(frac=1, random_state=int(rng.integers(1 << 31))).reset_index(drop=True)
    man.record("crm.exact_duplicate_rows", len(di))
    out.csv(cf, None, SRC, "customers", "customers_full_20260930.csv", bom=True)
    man.record("crm.utf8_bom", 1)

    a = t.addresses[t.addresses["customer_id"].isin(c["customer_id"])].reset_index(drop=True)
    af = _address_frame(rng, a, man, "customer_addresses")
    oi = pick_rows(rng, len(af), cfg.count(20, 3))
    orphans = af.iloc[oi].copy()
    orphans["ADDR_ID"] = [f"A{90000001 + i}" for i in range(len(orphans))]
    orphans["CUST_ID"] = [f"C{rng.integers(9000000, 9999999)}" for _ in range(len(orphans))]
    af = pd.concat([af, orphans], ignore_index=True)
    man.record("crm.orphan_addresses", len(orphans), keys=orphans["ADDR_ID"])
    out.csv(af, None, SRC, "customer_addresses", "customer_addresses_full_20260930.csv")

    # ---------------- increments: CDC
    _cdc(cfg, rng, t.customer_events, "customer_id", out, man, "customers_cdc",
         lambda df: _customer_frame(cfg, rng, df, man, "customers_cdc"), "customers_cdc")
    _cdc(cfg, rng, t.address_events, "address_id", out, man, "customer_addresses_cdc",
         lambda df: _address_frame(rng, df, man, "customer_addresses_cdc"), "addresses_cdc")


def _cdc(cfg, rng, ev, key, out, man, entity, frame_fn, prefix):
    ev = ev.sort_values("change_ts").reset_index(drop=True)
    ev["SEQ_NO"] = np.arange(500001, 500001 + len(ev))
    body = frame_fn(ev)
    if "LAST_MOD_DT" in body.columns:
        body["LAST_MOD_DT"] = _pacific(ev["change_ts"]).to_numpy()
    body.insert(0, "CHANGE_TS", ev["change_ts"].dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ").str[:-4] + "Z")
    body.insert(0, "SEQ_NO", ev["SEQ_NO"].to_numpy())
    body.insert(0, "OP", ev["op"].to_numpy())
    if entity == "customers_cdc":
        body["LOYALTY_TIER"] = ev["loyalty_tier"].to_numpy()
    dmask = body["OP"] == "D"
    keep = {"OP", "SEQ_NO", "CHANGE_TS", body.columns[3]}
    for col in body.columns:
        if col not in keep:
            body.loc[dmask, col] = None

    deliver = ev["change_ts"].dt.normalize()
    late = pick_rows(rng, len(ev), cfg.count(5, 2))
    late = [i for i in late if deliver[i] < cfg.increment_end]
    deliver.iloc[late] = deliver.iloc[late] + pd.Timedelta(days=1)
    man.record(f"crm.{prefix}_late_events", len(late), keys=body["SEQ_NO"].iloc[late])
    if entity == "customers_cdc":
        fake = []
        for day in rng.choice(cfg.increment_days, size=cfg.count(4, 2), replace=False):
            row = {c: None for c in body.columns}
            row.update({"OP": "D", "SEQ_NO": int(rng.integers(500001, 500001 + len(ev))),
                        "CHANGE_TS": (pd.Timestamp(day) + pd.Timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                        "CUST_ID": f"C{rng.integers(9000000, 9999999)}"})
            fake.append((pd.Timestamp(day), row))
        body = pd.concat([body, pd.DataFrame([r for _, r in fake])], ignore_index=True)
        deliver = pd.concat([deliver, pd.Series([d for d, _ in fake])], ignore_index=True)
        man.record("crm.cdc_delete_unknown_key", len(fake), keys=[r["CUST_ID"] for _, r in fake])
        same_day = ev.groupby([ev["customer_id"], ev["change_ts"].dt.normalize()]).size()
        man.record("crm.cdc_multiple_changes_same_batch", int((same_day > 1).sum()))
        man.record("crm.cdc_schema_drift_loyalty_tier", 1)
    man.record(f"crm.{prefix}_unordered", 1)

    for day in cfg.increment_days:
        rows = body[(deliver == day).to_numpy()]
        if entity == "customers_cdc" and day < cfg.increment_day(10):
            rows = rows.drop(columns=["LOYALTY_TIER"])
        if len(rows) == 0:
            continue
        rows = rows.sample(frac=1, random_state=int(rng.integers(1 << 31)))
        out.csv(rows, day, "crm", entity, f"{prefix}_{day:%Y%m%d}.csv")
