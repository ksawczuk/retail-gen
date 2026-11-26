"""Store generator guards at the smallest scale: a QC store and a US store are both present for every tested seed (GEN-04)."""
import unittest
from collections import Counter

import numpy as np

from retailgen import reference as ref
from retailgen.config import Config
from retailgen.truth.masterdata import generate_fx, generate_stores, us_slot

SEEDS = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20)
QC_CITY = next(i for i, c in enumerate(ref.CITIES) if c[1] == "QC")
US_CITY = next(i for i, c in enumerate(ref.CITIES) if c[2] == "US")
OTHER_CITY = next(i for i, c in enumerate(ref.CITIES) if c[1] != "QC" and c[2] != "US")


def raw_draw(cfg):
    """Return the city indexes the store draw gives before any guard, for the same seed and stream position."""
    rng = np.random.default_rng(cfg.seed)
    generate_fx(cfg, rng)
    w = np.array([c[6] for c in ref.CITIES], float)
    return list(rng.choice(len(ref.CITIES), size=cfg.n_stores, p=w / w.sum()))


def guarded_seed():
    """The first seed whose raw draw at scale 0.01 has no US store and its only QC store at slot 1, the case the
    US guard once removed (Bug 677). Found by shape, so a change in the random stream does not lose the case."""
    for seed in range(1, 1000):
        draw = raw_draw(Config(scale=0.01, seed=seed))
        no_us = not any(ref.CITIES[i][2] == "US" for i in draw)
        if no_us and [k for k, i in enumerate(draw) if ref.CITIES[i][1] == "QC"] == [1]:
            return seed
    raise AssertionError("no seed below 1000 gives the guarded case")


class UsSlotTest(unittest.TestCase):
    """The helper picks the first slot from 1 up that does not hold the only QC store."""

    def test_slot_one_is_used_when_it_is_not_the_only_qc_store(self):
        """QC at slot 0 only, or a second QC store, leaves slot 1 free to replace."""
        self.assertEqual(us_slot([QC_CITY, OTHER_CITY, OTHER_CITY]), 1)
        self.assertEqual(us_slot([OTHER_CITY, QC_CITY, QC_CITY]), 1)

    def test_the_only_qc_store_at_slot_one_moves_the_choice_up(self):
        """A single QC store at slot 1 sends the choice to slot 2."""
        self.assertEqual(us_slot([OTHER_CITY, QC_CITY, OTHER_CITY]), 2)

    def test_the_choice_skips_every_slot_that_would_remove_the_only_qc_store(self):
        """The search continues past slot 2 when the only QC store is there too."""
        self.assertEqual(us_slot([QC_CITY, OTHER_CITY, OTHER_CITY, OTHER_CITY]), 1)
        self.assertEqual(us_slot([OTHER_CITY, OTHER_CITY, QC_CITY, OTHER_CITY]), 1)


class GenerateStoresTest(unittest.TestCase):
    """generate_stores at scale 0.01 keeps the store count and changes only the guarded slot."""

    def stores_for(self, seed):
        """Run the store generator at scale 0.01 with the stream position the full run gives it."""
        cfg = Config(scale=0.01, seed=seed)
        rng = np.random.default_rng(seed)
        generate_fx(cfg, rng)
        return cfg, generate_stores(cfg, rng)

    def test_the_guarded_seed_completes_with_a_qc_and_a_us_store(self):
        """The case that used to raise now returns stores and a recode event for a QC store."""
        cfg, (stores, events) = self.stores_for(guarded_seed())
        self.assertEqual(len(stores), cfg.n_stores)
        self.assertIn("QC", set(stores["province"]))
        self.assertIn("US", set(stores["country"]))
        self.assertTrue(events)

    def test_the_guarded_seed_changes_only_the_guarded_slot_of_the_raw_draw(self):
        """The store count equals the draw's, and exactly one raw city is swapped for the US city."""
        cfg, (stores, _) = self.stores_for(guarded_seed())
        raw = Counter(ref.CITIES[i][0] for i in raw_draw(cfg))
        now = Counter(stores["city"])
        self.assertEqual(sum(now.values()), sum(raw.values()))
        self.assertEqual(list((now - raw).keys()), [ref.CITIES[US_CITY][0]])
        self.assertEqual(sum((raw - now).values()), 1)
        self.assertEqual(raw[ref.CITIES[QC_CITY][0]], now[ref.CITIES[QC_CITY][0]])

    def test_listed_seeds_have_a_qc_and_a_us_store(self):
        """Every seed in the explicit list places both stores at the smallest scale."""
        for seed in SEEDS:
            with self.subTest(seed=seed):
                _, (stores, events) = self.stores_for(seed)
                self.assertIn("QC", set(stores["province"]))
                self.assertIn("US", set(stores["country"]))
                self.assertTrue(events)


if __name__ == "__main__":
    unittest.main()
