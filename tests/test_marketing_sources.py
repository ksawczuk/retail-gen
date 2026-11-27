"""Unit tests for the Braze, ads, web utm and CRM consent outputs. Builds the truth at scale 0.01 once and runs the
emitters with a stand-in Avro writer, so the Avro bytes themselves are not checked here (see test_avro_seam)."""
import re
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from retailgen.config import Config
from retailgen.manifest import Manifest
from retailgen.sources import ads, braze, crm
from retailgen.truth import build_truth
from retailgen.writers import Output


class StandInWriter:
    """Records each Avro write's schema fields and records; returns placeholder bytes."""

    def __init__(self):
        self.writes = []

    def to_bytes(self, schema, records):
        self.writes.append((schema["name"], [f["name"] for f in schema["fields"]], list(records)))
        return b"Obj" + bytes(len(records) % 256)


class MarketingSourcesTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Build the truth and run the CRM, ads and Braze emitters into a temporary folder."""
        cls.cfg = Config(scale=0.01)
        rng = np.random.default_rng(cls.cfg.seed)
        cls.t = build_truth(cls.cfg, rng, log=lambda *a: None)
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.man, cls.writer = Manifest(), StandInWriter()
        out = Output(cls.root, cls.man, avro_writer=cls.writer)
        crm.emit(cls.cfg, rng, cls.t, out, cls.man)
        ads.emit(cls.cfg, rng, cls.t, out, cls.man)
        braze.emit(cls.cfg, rng, cls.t, out, cls.man)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _files(self, source):
        """The written files of one source, by relative path."""
        return [p for p in self.man.files if f"/{source}/" in p]

    def test_every_braze_and_ads_defect_is_recorded(self):
        declared = [d for d in braze_and_ads_ids()]
        for defect_id in declared:
            self.assertIn(defect_id, self.man._entries, defect_id)

    def test_increment_names_carry_the_day_and_history_names_the_month(self):
        for rel in self._files("braze") + self._files("ads"):
            if rel.startswith("increments/"):
                day = re.search(r"day=(\d{4})-(\d{2})-(\d{2})", rel).groups()
                self.assertTrue(re.search(r"_\d{8}(_resend)?\.(avro|csv|json)$", rel), rel)
                if "_resend" not in rel:
                    self.assertIn("".join(day), rel)
            else:
                self.assertTrue(re.search(r"_(\d{4}-\d{2}|\d{8})\.(avro|csv|json)$", rel), rel)

    def test_exactly_one_cut_off_file_and_its_resend_the_next_day(self):
        day20 = self.cfg.increment_day(20)
        name = f"email_opens_{day20:%Y%m%d}.avro"
        original = [p for p in self.man.files if p.endswith("/" + name)]
        resend = [p for p in self.man.files if p.endswith(f"email_opens_{day20:%Y%m%d}_resend.avro")]
        self.assertEqual(len(original), 1)
        self.assertEqual(len(resend), 1)
        self.assertIn(f"day={day20 + pd.Timedelta(days=1):%Y-%m-%d}", resend[0])
        self.assertEqual(self.man.files[original[0]]["rows"], self.man.files[resend[0]]["rows"])
        whole = (self.root / resend[0]).stat().st_size
        self.assertLess((self.root / original[0]).stat().st_size, whole)
        self.assertEqual(self.man.count("braze.corrupt_file_resent"), 1)

    def test_schemas_change_on_their_dates(self):
        fields = {}
        for name, cols, records in self.writer.writes:
            if records:
                first = min(r["time"] for r in records)
                fields.setdefault(name, []).append((first, set(cols)))
        ms = lambda d: int(pd.Timestamp(d).value // 10**6)  # noqa: E731
        for first, cols in fields["braze_opens"]:
            if first < ms("2026-03-01"):
                self.assertNotIn("machine_open", cols)
        self.assertTrue(any("machine_open" in c for _, c in fields["braze_opens"]))
        self.assertTrue(any("dispatch_id" in c for _, c in fields["braze_sends"]))
        self.assertTrue(any("send_id" in c for _, c in fields["braze_sends"]))

    def test_every_record_in_a_file_is_on_the_side_of_its_schema_date(self):
        ms = lambda d: int(pd.Timestamp(d).value // 10**6)  # noqa: E731
        changes = {"braze_opens": ("machine_open", braze.MACHINE_OPEN_FROM),
                   "braze_clicks": ("link_alias", braze.LINK_ALIAS_FROM),
                   "braze_sends": ("dispatch_id", braze.SEND_RENAME_FROM)}
        for name, cols, records in self.writer.writes:
            if name not in changes or not records:
                continue
            column, day = changes[name]
            times = [r["time"] for r in records]
            if column in cols:
                self.assertGreaterEqual(min(times), ms(day), (name, column))
            else:
                self.assertLess(max(times), ms(day), (name, column))

    def test_anonymous_events_have_no_external_id(self):
        sends = [r for name, _, recs in self.writer.writes if name == "braze_sends" for r in recs]
        missing = sum(r["external_user_id"] is None for r in sends)
        self.assertGreater(missing, 0)
        self.assertLess(missing / len(sends), 0.2)

    def test_ads_spend_matches_the_answer_key_less_the_missing_days(self):
        rows = pd.concat([pd.read_csv(self.root / p) for p in self._files("ads")], ignore_index=True)
        self.assertEqual(set(rows["currency"]), {"CAD", "USD"})
        self.assertEqual(rows.groupby("agency")["currency"].nunique().max(), 1)
        rate = pd.to_datetime(rows["date"]).map(self.t.fx.set_index("date")["usd_cad"]).ffill().bfill()
        cad = np.where(rows["currency"] == "USD", rows["spend"] * rate, rows["spend"]).sum()
        truth = self.t.campaign_truth.loc[self.t.campaign_truth["kind"] == "prospects", "spend"].sum()
        self.assertLess(cad, truth)
        self.assertGreater(cad, 0.5 * truth)

    def test_the_crm_extract_has_no_loyalty_join_column(self):
        extract = [p for p in self._files("crm") if "customers_full" in p][0]
        header = (self.root / extract).read_text(encoding="utf-8-sig").splitlines()[0]
        self.assertNotIn("LOYALTY_JOIN", header)

    def test_synced_unsubscribes_turn_opt_in_off_in_the_change_feed(self):
        synced = self.t.consent_sync.dropna(subset=["crm_synced_at"])
        synced = synced[synced["crm_synced_at"] >= self.cfg.history_end + pd.Timedelta(days=1)]
        ev = self.t.customer_events
        for r in synced.itertuples(index=False):
            hit = ev[(ev["customer_id"] == r.customer_id) & (ev["change_ts"] == r.crm_synced_at)]
            if len(hit):
                self.assertFalse(bool(hit["marketing_opt_in"].iloc[0]))

    def test_email_click_sessions_carry_the_campaign_tag(self):
        sessions = self.t.clickstream.drop_duplicates("session_id")
        email = sessions[sessions["utm_source"] == "newsletter"]
        tags = set(self.t.campaigns["utm_campaign"])
        tagged = email["utm_campaign"].dropna()
        self.assertGreater(len(tagged), 0)
        self.assertTrue(set(tagged) <= tags)


def braze_and_ads_ids():
    """The catalogued defect ids of the braze and ads sources."""
    from retailgen.defects import REGISTRY
    return [k for k, d in REGISTRY.items() if d.source in ("braze", "ads")]


if __name__ == "__main__":
    unittest.main()
