"""Clean truth for people: customers (with real-world person ids), addresses, and CRM changes."""
import numpy as np
import pandas as pd

from .. import reference as ref
from ..util import ascii_fold
from .lifecycle import MEMBER_SHARE, loyalty_join_dates, tiers_by_activity

NS = "datetime64[ns]"
POSTAL_LETTERS = list("ABCEGHJKLMNPRSTVWXYZ")


def _postal(rng, prefix: str, country: str) -> str:
    if country == "US":
        return prefix
    L = POSTAL_LETTERS
    return f"{prefix} {rng.integers(10)}{L[rng.integers(len(L))]}{rng.integers(10)}"


def _email_local(first: str, last: str) -> str:
    return (ascii_fold(first).lower() + "." +
            ascii_fold(last).lower().replace("'", "").replace(" ", ""))


def _typo(rng, s: str) -> str:
    if len(s) < 4:
        return s
    i = int(rng.integers(1, len(s) - 2))
    return s[:i] + s[i + 1] + s[i] + s[i + 2:]


def _random_times(rng, start, end, n):
    span = int((pd.Timestamp(end) - pd.Timestamp(start)).total_seconds())
    return (pd.Timestamp(start) + pd.to_timedelta(rng.integers(0, span, n), unit="s")).astype(NS)


def generate_customers(cfg, rng):
    """Customers and addresses. About 3% of people have a second customer record (person_id
    links them in the truth only)."""
    n = cfg.n_customers
    n_dup = max(5, int(n * 0.03))
    n_p = n - n_dup
    fi = rng.integers(len(ref.FIRST_NAMES), size=n_p)
    li = rng.integers(len(ref.LAST_NAMES), size=n_p)
    cw = np.array([c[6] for c in ref.CITIES], float)
    city = rng.choice(len(ref.CITIES), size=n_p, p=cw / cw.sum())
    early = rng.random(n_p) < 0.55
    created = np.where(early,
                       _random_times(rng, "2021-01-01", cfg.history_start, n_p),
                       _random_times(rng, cfg.history_start, cfg.increment_end, n_p))
    birth = pd.Timestamp("1950-01-01") + pd.to_timedelta(rng.integers(0, 365 * 57, n_p), unit="D")
    birth = pd.Series(birth).where(rng.random(n_p) > 0.08)
    is_emp = rng.random(n_p) < 0.01
    phones, emails = [], []
    for k in range(n_p):
        area = ref.CITIES[city[k]][5][rng.integers(len(ref.CITIES[city[k]][5]))]
        phones.append(f"+1{area}555{rng.integers(0, 10000):04d}")
        local = _email_local(ref.FIRST_NAMES[fi[k]][0], ref.LAST_NAMES[li[k]])
        if rng.random() < 0.6:
            local += str(rng.integers(1, 999))
        dom = cfg.employee_domain if is_emp[k] else ref.EMAIL_DOMAINS[rng.integers(len(ref.EMAIL_DOMAINS))]
        emails.append(f"{local}@{dom}")
    people = pd.DataFrame({
        "person_id": np.arange(1, n_p + 1),
        "first_name": [ref.FIRST_NAMES[i][0] for i in fi],
        "nickname": [ref.FIRST_NAMES[i][1] for i in fi],
        "last_name": [ref.LAST_NAMES[i] for i in li],
        "email": emails, "phone": phones, "birth_date": birth.astype(NS).to_numpy(),
        "city_idx": city, "created_at": pd.to_datetime(created).astype(NS), "is_employee": is_emp,
    })

    # Second records for some people: nickname, typo, different email, later signup.
    cand = people[(~people["is_employee"]) &
                  (people["created_at"] < cfg.increment_end - pd.Timedelta(days=60))]
    dups = cand.sample(n=min(n_dup, len(cand)), random_state=int(rng.integers(1 << 31))).copy()
    new_first, new_last, new_email, new_phone, new_created, new_birth = [], [], [], [], [], []
    for r in dups.itertuples(index=False):
        has_nick = isinstance(r.nickname, str) and r.nickname != ""
        new_first.append(r.nickname if (has_nick and rng.random() < 0.6) else r.first_name)
        new_last.append(_typo(rng, r.last_name) if rng.random() < 0.25 else r.last_name)
        local, dom = r.email.split("@")
        roll = rng.random()
        if roll < 0.4:
            new_email.append(f"{local}@{ref.EMAIL_DOMAINS[rng.integers(len(ref.EMAIL_DOMAINS))]}")
        elif roll < 0.7:
            new_email.append(f"{ascii_fold(r.first_name)[0].lower()}{_email_local('', r.last_name)[1:]}"
                             f"{rng.integers(10, 99)}@{dom}")
        else:
            new_email.append(f"{local}+shop@{dom}")
        new_phone.append(r.phone if rng.random() < 0.7 else r.phone[:-4] + f"{rng.integers(0, 10000):04d}")
        c = r.created_at + pd.Timedelta(days=int(rng.integers(30, 600)))
        new_created.append(min(c, cfg.increment_end - pd.Timedelta(days=1)))
        new_birth.append(r.birth_date if rng.random() < 0.6 else pd.NaT)
    dups = dups.assign(first_name=new_first, last_name=new_last, email=new_email, phone=new_phone,
                       created_at=pd.to_datetime(new_created).astype(NS),
                       birth_date=pd.to_datetime(pd.Series(new_birth)).astype(NS).to_numpy())

    cust = pd.concat([people, dups], ignore_index=True)
    # Make emails unique across records (two people can't share a login).
    while cust["email"].duplicated().any():
        dupe_n = cust.groupby("email").cumcount()
        cust["email"] = [e if k == 0 else e.replace("@", f"{k}@", 1)
                         for e, k in zip(cust["email"], dupe_n)]
    cust = cust.sort_values("created_at").reset_index(drop=True)
    cust.insert(0, "customer_id", [f"C{1000001 + i}" for i in range(len(cust))])

    # Loyalty: membership by the end of the window, a join date per member, and a tier from activity
    m = len(cust)
    is_emp_all = cust["is_employee"].to_numpy()
    in_loyalty = (rng.random(m) < MEMBER_SHARE) | is_emp_all
    nums = rng.permutation(np.unique(rng.integers(100_000_000, 999_999_999, size=int(m * 1.2))))[:m]
    cust["loyalty_number"] = np.where(in_loyalty, [f"L{x}" for x in nums], None)
    cust["marketing_opt_in"] = rng.random(m) < 0.55
    cust["activity"] = rng.lognormal(0, 1.0, m)
    cust["loyalty_tier"] = tiers_by_activity(cust["activity"], in_loyalty)
    joined = loyalty_join_dates(rng, cust["created_at"], in_loyalty, cfg.increment_end)
    cust["loyalty_join_at"] = np.where(is_emp_all, cust["created_at"].to_numpy().astype(NS), joined).astype(NS)
    cust["province"] = [ref.CITIES[i][1] for i in cust["city_idx"]]
    cust["country"] = [ref.CITIES[i][2] for i in cust["city_idx"]]

    addresses = _addresses(cfg, rng, cust)
    return cust.drop(columns=["nickname"]), addresses


def _address_row(rng, ci):
    city, prov, country, _, prefixes, *_ = ref.CITIES[ci]
    line2 = f"Apt {rng.integers(1, 2400)}" if rng.random() < 0.3 else None
    return {"line1": f"{rng.integers(1, 9999)} {ref.STREETS[rng.integers(len(ref.STREETS))]} "
                     f"{ref.STREET_SUFFIXES[rng.integers(len(ref.STREET_SUFFIXES))]}",
            "line2": line2, "city": city, "province": prov,
            "postal_code": _postal(rng, prefixes[rng.integers(len(prefixes))], country), "country": country}


def _addresses(cfg, rng, cust) -> pd.DataFrame:
    rows = []
    first_addr = {}
    for r in cust.itertuples(index=False):
        base = first_addr.get(r.person_id)
        if base is None:
            base = _address_row(rng, r.city_idx)
            first_addr[r.person_id] = base
        rows.append({"customer_id": r.customer_id, "address_type": "billing", "is_default": True,
                     "created_at": r.created_at, **base})
        if rng.random() < 0.3:
            same_country = [i for i, c in enumerate(ref.CITIES) if c[2] == r.country]
            rows.append({"customer_id": r.customer_id, "address_type": "shipping", "is_default": False,
                         "created_at": r.created_at, **_address_row(rng, int(rng.choice(same_country)))})
    a = pd.DataFrame(rows)
    a.insert(0, "address_id", [f"A{10000001 + i}" for i in range(len(a))])
    a["created_at"] = a["created_at"].astype(NS)
    return a


def ship_to(addresses: pd.DataFrame) -> pd.DataFrame:
    """One ship-to address per customer: the shipping address if any, else billing."""
    a = addresses.sort_values("address_type", key=lambda s: s.map({"shipping": 0, "billing": 1}))
    return a.drop_duplicates("customer_id")[["customer_id", "address_id", "city", "province",
                                             "postal_code", "country"]]


def generate_crm_changes(cfg, rng, customers, addresses, last_activity: pd.Series):
    """CRM change events in the increment window: inserts (new signups), updates, address moves
    and deletes. Returns (customer_events, address_events, deleted_ids); every event carries a
    full row image and its change timestamp."""
    state = customers.set_index("customer_id").copy()
    # Loyalty as the CRM knows it at the cut-over: members who join later, and not at signup, wait for their join
    final_loyalty = state[["loyalty_number", "loyalty_tier"]].copy()
    cutover = np.datetime64(cfg.history_end + pd.Timedelta(days=1), "ns")
    join_at = state["loyalty_join_at"].to_numpy()
    pending = (join_at >= cutover) & (join_at > state["created_at"].to_numpy().astype(NS))
    state.loc[pending, ["loyalty_number", "loyalty_tier"]] = None
    joins = state.index[pending]
    cust_ev, addr_ev, deleted = [], [], set()
    next_addr = int(addresses["address_id"].str[1:].astype(int).max()) + 1
    addr_state = addresses.set_index("address_id").copy()

    for day in cfg.increment_days:
        day_end = day + pd.Timedelta(days=1)
        new = customers[(customers["created_at"] >= day) & (customers["created_at"] < day_end)]
        for r in new.itertuples(index=False):
            cust_ev.append({"op": "I", "change_ts": r.created_at, "customer_id": r.customer_id,
                            **state.loc[r.customer_id].to_dict()})
            for a in addresses[addresses["customer_id"] == r.customer_id].itertuples(index=False):
                addr_ev.append({"op": "I", "change_ts": r.created_at, **a._asdict()})

        # Loyalty joins: the member's number and tier appear in the CRM on the day they join
        joined_today = joins[(state.loc[joins, "loyalty_join_at"] >= day).to_numpy()
                             & (state.loc[joins, "loyalty_join_at"] < day_end).to_numpy()]
        for cid in joined_today:
            if cid in deleted:
                continue
            state.loc[cid, ["loyalty_number", "loyalty_tier"]] = final_loyalty.loc[cid].to_numpy()
            cust_ev.append({"op": "U", "change_ts": state.loc[cid, "loyalty_join_at"], "customer_id": cid,
                            **state.loc[cid].to_dict()})

        existing = state.index[(state["created_at"] < day) & ~state.index.isin(list(deleted))]
        if len(existing) == 0:
            continue
        n_upd = rng.poisson(0.003 * len(existing)) + cfg.count(2, 1)
        targets = list(rng.choice(existing, size=min(n_upd, len(existing)), replace=False))
        targets += targets[: cfg.count(2, 1)]  # some keys change twice on the same day
        for cid in targets:
            ts = day + pd.Timedelta(seconds=int(rng.integers(0, 86400)))
            kind = rng.choice(["email", "phone", "opt_in", "tier", "last_name"], p=[.3, .2, .25, .15, .1])
            row = state.loc[cid].copy()
            if kind == "email":
                local, dom = row["email"].split("@")
                row["email"] = f"{local}{rng.integers(1, 99)}@{ref.EMAIL_DOMAINS[rng.integers(len(ref.EMAIL_DOMAINS))]}"
            elif kind == "phone":
                row["phone"] = row["phone"][:-4] + f"{rng.integers(0, 10000):04d}"
            elif kind == "opt_in":
                row["marketing_opt_in"] = not bool(row["marketing_opt_in"])
            elif kind == "tier":
                # Only a member's tier moves
                if row["loyalty_number"] is None or pd.isna(row["loyalty_number"]):
                    continue
                row["loyalty_tier"] = {"Bronze": "Silver", "Silver": "Gold", "Gold": "Silver"}.get(
                    row["loyalty_tier"], "Bronze")
            else:
                row["last_name"] = ref.LAST_NAMES[rng.integers(len(ref.LAST_NAMES))]
            state.loc[cid] = row
            cust_ev.append({"op": "U", "change_ts": ts, "customer_id": cid, **row.to_dict()})

        # Address moves: a new default billing address, the old one demoted.
        for cid in rng.choice(existing, size=min(rng.poisson(0.0005 * len(existing)) + 1, len(existing)), replace=False):
            ts = day + pd.Timedelta(seconds=int(rng.integers(0, 86400)))
            ci = int(rng.integers(len(ref.CITIES)))
            old = addr_state[(addr_state["customer_id"] == cid) & (addr_state["is_default"])]
            for aid in old.index:
                addr_state.loc[aid, "is_default"] = False
                addr_ev.append({"op": "U", "change_ts": ts, "address_id": aid, **addr_state.loc[aid].to_dict()})
            aid = f"A{next_addr}"
            next_addr += 1
            new_row = {"customer_id": cid, "address_type": "billing", "is_default": True,
                       "created_at": ts, **_address_row(rng, ci)}
            addr_state.loc[aid] = pd.Series(new_row)
            addr_ev.append({"op": "I", "change_ts": ts, "address_id": aid, **new_row})

        # Deletes (privacy requests) only for customers with no later activity.
        if rng.random() < 0.35:
            quiet = [c for c in existing if pd.isna(last_activity.get(c, pd.NaT)) or last_activity.get(c) < day]
            if quiet:
                cid = quiet[int(rng.integers(len(quiet)))]
                ts = day + pd.Timedelta(seconds=int(rng.integers(0, 86400)))
                deleted.add(cid)
                cust_ev.append({"op": "D", "change_ts": ts, "customer_id": cid, **state.loc[cid].to_dict()})

    ce = pd.DataFrame(cust_ev)
    ae = pd.DataFrame(addr_ev)
    ce["change_ts"] = pd.to_datetime(ce["change_ts"]).astype(NS)
    ae["change_ts"] = pd.to_datetime(ae["change_ts"]).astype(NS)
    return ce.sort_values("change_ts").reset_index(drop=True), ae.sort_values("change_ts").reset_index(drop=True), deleted
