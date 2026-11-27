"""The data window: 92 increment days ending 2026-12-31, and promotion codes that cover November and December 2026."""
import unittest

import pandas as pd

from retailgen.config import Config
from retailgen.truth.masterdata import generate_promotions


class WindowTest(unittest.TestCase):

    def test_increments_run_from_october_to_the_end_of_december(self):
        days = Config().increment_days
        self.assertEqual(len(days), 92)
        self.assertEqual(days[0], pd.Timestamp("2026-10-01"))
        self.assertEqual(days[-1], pd.Timestamp("2026-12-31"))

    def test_codes_run_in_november_and_december_2026(self):
        """Black Friday, the gift guide and Boxing Day 2026 are in the promotions file and start in the window."""
        cfg = Config()
        promos = generate_promotions(cfg).set_index("code")
        for code, month in (("BFRIDAY26", 11), ("GIFT26", 11), ("BOXING26", 12)):
            self.assertIn(code, promos.index)
            self.assertEqual(promos.loc[code, "starts_at"].month, month)
            self.assertLessEqual(promos.loc[code, "created_at"], cfg.increment_end)


if __name__ == "__main__":
    unittest.main()
