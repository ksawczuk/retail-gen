"""Braze: the email platform's export. Engagement events as Avro (one file set per event type), a daily campaign
snapshot (JSON) and a daily user map (CSV), each with the platform's own quirks.

Called by generate.py as the last source; reads the campaign answer key and the email events in the truth.
"""
import numpy as np
import pandas as pd

from ..util import pick_rows
from .common import by_month, make_late, route

SRC = "braze"
EVENT_FILES = {"send": "sends", "delivery": "deliveries", "bounce": "bounces", "open": "opens", "click": "clicks",
               "unsubscribe": "unsubscribes"}
MACHINE_OPEN_FROM = pd.Timestamp("2026-03-10")
LINK_ALIAS_FROM = pd.Timestamp("2026-06-01")
SEND_RENAME_FROM = pd.Timestamp("2026-07-15")
ANONYMOUS_SHARE = 0.08
IDENTIFIED_LATER = 0.70
EMAIL_ID_SHARE = 0.10
LEGACY_ID_SHARE = 0.05
OFF_CONVENTION_SHARE = 0.25
RENAMED = ("CMP-02", "CMP-07", "CMP-17")
REUSED = ("CMP-14", "CMP-04")
CORRUPT_DAY = 20
CORRUPT_ENTITY = "opens"
NS = "datetime64[ns]"


def emit(cfg, rng, t, out, man):
    """Write the Braze export: users, campaigns, then the engagement events."""
    profiles = user_profiles(rng, t, man)
    campaigns = campaign_catalog(rng, t, man)
    _write_users(cfg, out, profiles)
    _write_campaign_snapshots(cfg, out, campaigns)
    events = event_rows(cfg, rng, t, profiles, campaigns, man)
    _write_events(cfg, out, events, man)


def user_profiles(rng, t, man):
    """One Braze profile per customer who got an email: braze_id, external_id in its format, and when (if ever)
    an anonymous profile was identified. A person with two CRM records has one profile, on one of the two ids."""
    events = t.engagement_events
    first = events.groupby("customer_id")["event_ts"].min()
    people = t.customers.set_index("customer_id").loc[first.index, ["person_id", "email"]]
    n = len(first)

    # The external_id: usually the customer id, sometimes the email or a legacy id
    kind = rng.random(n)
    external = np.where(kind < EMAIL_ID_SHARE, people["email"].str.lower().to_numpy(),
                        np.where(kind < EMAIL_ID_SHARE + LEGACY_ID_SHARE,
                                 [f"legacy-{x}" for x in rng.integers(100_000, 999_999, n)], first.index.to_numpy()))
    profiles = pd.DataFrame({"customer_id": first.index.to_numpy(), "person_id": people["person_id"].to_numpy(),
                             "braze_id": [rng.bytes(12).hex() for _ in range(n)], "external_id": external,
                             "first_seen": first.to_numpy()})
    man.record("braze.external_id_formats", int((kind < EMAIL_ID_SHARE + LEGACY_ID_SHARE).sum()))

    # Some profiles start anonymous; most are identified later, the rest never
    anon = rng.random(n) < ANONYMOUS_SHARE
    later = anon & (rng.random(n) < IDENTIFIED_LATER)
    delay = pd.to_timedelta(rng.integers(1, 60, n), unit="D")
    profiles["identified_at"] = (profiles["first_seen"] + delay).where(later)
    profiles.loc[~anon, "identified_at"] = profiles.loc[~anon, "first_seen"]
    man.record("braze.anonymous_users", int(anon.sum()), keys=profiles.loc[anon, "braze_id"])

    # A person with two customer records shares one profile
    shared = profiles.duplicated("person_id", keep="first")
    keeper = profiles.drop_duplicates("person_id").set_index("person_id")
    profiles.loc[shared, ["braze_id", "external_id", "identified_at"]] = (
        keeper.loc[profiles.loc[shared, "person_id"], ["braze_id", "external_id", "identified_at"]].to_numpy())
    man.record("braze.one_profile_two_customers", int(shared.sum()), keys=profiles.loc[shared, "customer_id"])
    return profiles


def campaign_catalog(rng, t, man):
    """Braze's campaign list: an id, the name over time (three renamed), tags, and one id reused for a later
    campaign. A quarter of names break the naming convention."""
    c = t.campaigns[t.campaigns["kind"] != "prospects"].reset_index(drop=True)
    ids = {cid: rng.bytes(8).hex() for cid in c["campaign_id"]}

    # The reused id: a later campaign was cloned from an older one and kept its id
    newer, older = REUSED
    if newer in ids and older in ids:
        ids[newer] = ids[older]
    man.record("braze.campaign_id_reused", 1, keys=[ids[older]])

    # Names: snake case by convention, a quarter in other styles; three renamed partway
    off = rng.random(len(c)) < OFF_CONVENTION_SHARE
    names = [_styled(name, rng) if odd else tag for name, tag, odd in zip(c["name"], c["utm_campaign"], off)]
    man.record("braze.campaign_name_convention", int(off.sum()))
    first_send = pd.to_datetime(c["sends"].str.split(",").str[0].replace("", None))
    renamed_on = first_send + pd.Timedelta(days=20)
    catalog = pd.DataFrame({"campaign_id": c["campaign_id"], "braze_campaign_id": c["campaign_id"].map(ids),
                            "name": names, "utm_campaign": c["utm_campaign"], "created_at": first_send,
                            "renamed_to": [f"{n} (v2)" if cid in RENAMED else None
                                           for n, cid in zip(names, c["campaign_id"])],
                            "renamed_at": renamed_on.where(c["campaign_id"].isin(RENAMED))})
    man.record("braze.campaign_renamed", len(RENAMED), keys=list(RENAMED))
    return catalog


def event_rows(cfg, rng, t, profiles, campaigns, man):
    """The engagement events as Braze exports them: ids, campaign, user and the per-type fields, with late and
    duplicate deliveries. One row per delivered event, with its delivery day."""
    e = t.engagement_events.merge(profiles[["customer_id", "braze_id", "external_id", "identified_at"]],
                                  on="customer_id", how="inner")
    e = e.merge(campaigns[["campaign_id", "braze_campaign_id", "name"]], on="campaign_id", how="left")

    # The user: anonymous until identified
    identified = e["identified_at"].notna() & (e["identified_at"] <= e["event_ts"])
    e["external_id"] = e["external_id"].where(identified)
    e["event_id"] = [rng.bytes(16).hex() for _ in range(len(e))]
    man.record("braze.sends_without_consent", int((e["event_type"].eq("send") & e["no_consent"]).sum()))
    man.record("braze.sends_after_unsubscribe", int((e["event_type"].eq("send") & e["after_unsubscribe"]).sum()))
    man.record("braze.machine_opens", 1, day=MACHINE_OPEN_FROM.strftime("%Y-%m-%d"))

    # Late and duplicated deliveries
    deliver, late = make_late(rng, e["event_ts"].dt.normalize(), 0.012, 1, 5)
    e["deliver_day"] = deliver
    man.record("braze.late_events", int(late.sum()), keys=e.loc[late, "event_id"])
    dup = e.iloc[pick_rows(rng, len(e), cfg.count(0.005 * len(e), 2))]
    man.record("braze.duplicate_events", len(dup), keys=dup["event_id"])
    man.record("braze.schema_drift", 3, opens=MACHINE_OPEN_FROM.strftime("%Y-%m-%d"),
               clicks=LINK_ALIAS_FROM.strftime("%Y-%m-%d"), sends=SEND_RENAME_FROM.strftime("%Y-%m-%d"))
    return pd.concat([e, dup], ignore_index=True).sort_values("event_ts", kind="stable").reset_index(drop=True)


def records_for(entity, g, day):
    """The Avro records and schema for one file of an event type; the schema depends on the file's day."""
    stamp = pd.Timestamp(day) if day is not None else g["event_ts"].max()
    fields = [("id", "string"), ("time", "long"), ("campaign_id", ["null", "string"]),
              ("campaign_name", ["null", "string"]), ("user_id", "string"), ("external_user_id", ["null", "string"])]
    if entity == "opens" and stamp >= MACHINE_OPEN_FROM:
        fields.append(("machine_open", ["null", "boolean"]))
    if entity == "clicks":
        fields.append(("url", ["null", "string"]))
        if stamp >= LINK_ALIAS_FROM:
            fields.append(("link_alias", ["null", "string"]))
    if entity == "bounces":
        fields.append(("bounce_type", ["null", "string"]))
    if entity == "sends":
        fields.append(("dispatch_id" if stamp >= SEND_RENAME_FROM else "send_id", ["null", "string"]))
    schema = {"type": "record", "name": f"braze_{entity}", "namespace": "com.braze.currents",
              "fields": [{"name": n, "type": ty} for n, ty in fields]}

    names = {n for n, _ in fields}
    records = []
    for r in g.itertuples(index=False):
        rec = {"id": r.event_id, "time": int(pd.Timestamp(r.event_ts).value // 10**6),
               "campaign_id": _none(r.braze_campaign_id), "campaign_name": _none(r.name), "user_id": r.braze_id,
               "external_user_id": _none(r.external_id)}
        if "machine_open" in names:
            rec["machine_open"] = bool(r.machine_open)
        if "url" in names:
            rec["url"] = f"https://larchwood.example/c/{r.campaign_id.lower()}?utm_source=newsletter&utm_medium=email"
        if "link_alias" in names:
            rec["link_alias"] = "hero"
        if "bounce_type" in names:
            rec["bounce_type"] = _none(r.bounce_type)
        for key in ("send_id", "dispatch_id"):
            if key in names:
                rec[key] = r.event_id[:12]
        records.append(rec)
    return records, schema


def _write_events(cfg, out, events, man):
    """One Avro file per event type per month of history and per increment day; the corrupt file and its re-send."""
    corrupt_day = cfg.increment_day(CORRUPT_DAY)
    for event_type, entity in EVENT_FILES.items():
        rows = events[events["event_type"] == event_type]
        hist, days = route(cfg, rows, rows["deliver_day"])
        for month, g in by_month(hist, hist["event_ts"]).items():
            records, schema = records_for(entity, g, None)
            out.avro(records, schema, None, SRC, entity, f"email_{entity}_{month}.avro")
        for day, g in days.items():
            records, schema = records_for(entity, g, day)
            name = f"email_{entity}_{day:%Y%m%d}.avro"
            if entity == CORRUPT_ENTITY and day == corrupt_day:
                out.avro(records, schema, day, SRC, entity, name, keep_share=0.5)
                out.avro(records, schema, day + pd.Timedelta(days=1), SRC, entity,
                         f"email_{entity}_{day:%Y%m%d}_resend.avro")
                man.record("braze.corrupt_file_resent", 1, keys=[name])
                continue
            out.avro(records, schema, day, SRC, entity, name)


def _write_campaign_snapshots(cfg, out, campaigns):
    """The campaign list as of the cut-over, then one snapshot per increment day."""
    def snapshot(as_of):
        """The campaigns created by `as_of`, with the name they had then."""
        live = campaigns[campaigns["created_at"].isna() | (campaigns["created_at"] <= as_of)]
        renamed = live["renamed_at"].notna() & (live["renamed_at"] <= as_of)
        return [{"id": r.braze_campaign_id, "name": (r.renamed_to if k else r.name), "tags": [r.utm_campaign],
                 "created_at": None if pd.isna(r.created_at) else r.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")}
                for r, k in zip(live.itertuples(index=False), renamed)]

    out.json_array(snapshot(cfg.history_end), None, SRC, "campaigns", f"campaigns_{cfg.history_end:%Y%m%d}.json")
    for day in cfg.increment_days:
        out.json_array(snapshot(day), day, SRC, "campaigns", f"campaigns_{day:%Y%m%d}.json")


def _write_users(cfg, out, profiles):
    """The user map as of the cut-over, then each day's new or newly identified users."""
    p = profiles.drop_duplicates("braze_id")
    frame = pd.DataFrame({"braze_id": p["braze_id"], "external_id": p["external_id"].where(p["identified_at"].notna()),
                          "first_seen": p["first_seen"].dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "identified_at": p["identified_at"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")})
    changed = p[["first_seen", "identified_at"]].max(axis=1)
    cut = cfg.history_end + pd.Timedelta(days=1)
    out.csv(frame[(changed < cut).to_numpy()], None, SRC, "users", f"users_{cfg.history_end:%Y%m%d}.csv")
    for day in cfg.increment_days:
        today = ((changed >= day) & (changed < day + pd.Timedelta(days=1))).to_numpy()
        if today.any():
            out.csv(frame[today], day, SRC, "users", f"users_{day:%Y%m%d}.csv")


def _styled(name, rng):
    """A campaign name in one of the styles that break the convention."""
    words = [w for w in name.replace("'", "").split() if w]
    style = int(rng.integers(3))
    if style == 0:
        return "".join(w.capitalize() for w in words)
    if style == 1:
        return " ".join(words).upper()
    return "-".join(w.lower() for w in words)


def _none(value):
    """None for a missing value, otherwise the value as text."""
    return None if value is None or (isinstance(value, float) and np.isnan(value)) else str(value)
