"""Unit tests for retailgen.truth.seasonality: gifting dates and windows, the shared curve and category curves."""
import unittest

import numpy as np
import pandas as pd

from retailgen.truth.seasonality import GIFTING_TOTAL, Seasonality, fathers_day, mothers_day
from retailgen.util import seasonality as base_curve

DAYS = pd.date_range("2025-01-01", "2026-12-31", freq="D")
NAMES = ["Tops", "Outerwear", "Water Sports", "Decor", "Audio", "Kitchen"]


class SeasonalityTest(unittest.TestCase):
    """Built over the whole window with a few category names."""

    @classmethod
    def setUpClass(cls):
        cls.s = Seasonality(DAYS, NAMES)

    def _day(self, text):
        """The position of a date in DAYS."""
        return DAYS.get_loc(pd.Timestamp(text))

    def test_gifting_dates(self):
        self.assertEqual(mothers_day(2025), pd.Timestamp("2025-05-11"))
        self.assertEqual(mothers_day(2026), pd.Timestamp("2026-05-10"))
        self.assertEqual(fathers_day(2025), pd.Timestamp("2025-06-15"))
        self.assertEqual(fathers_day(2026), pd.Timestamp("2026-06-21"))

    def test_windows_are_the_ten_days_before(self):
        gifting = self.s.gifting_days()
        self.assertTrue(gifting[self._day("2025-05-01")] and gifting[self._day("2025-05-10")])
        self.assertFalse(gifting[self._day("2025-04-30")] or gifting[self._day("2025-05-11")])
        self.assertEqual(int(gifting.sum()), 40)

    def test_shared_curve_is_the_base_curve_lifted_in_gifting_windows(self):
        ratio = self.s.shared() / base_curve(DAYS)
        gifting = self.s.gifting_days()
        np.testing.assert_allclose(ratio[gifting], GIFTING_TOTAL)
        np.testing.assert_allclose(ratio[~gifting], 1.0)

    def test_category_months(self):
        dec, jul = self._day("2025-12-10"), self._day("2025-07-10")
        cat = self.s.category([dec, jul])
        self.assertAlmostEqual(cat[0, NAMES.index("Outerwear")], 1.6)
        self.assertAlmostEqual(cat[1, NAMES.index("Outerwear")], 0.5)
        self.assertAlmostEqual(cat[1, NAMES.index("Water Sports")], 2.0)
        self.assertAlmostEqual(cat[0, NAMES.index("Tops")], 1.0)

    def test_gifting_lifts_that_holidays_categories(self):
        before_mothers, before_fathers = self._day("2026-05-05"), self._day("2026-06-15")
        cat = self.s.category([before_mothers, before_fathers])
        self.assertAlmostEqual(cat[0, NAMES.index("Decor")], 1.8)
        self.assertAlmostEqual(cat[0, NAMES.index("Audio")], 1.0)
        self.assertAlmostEqual(cat[1, NAMES.index("Audio")], 1.3 * 1.8)
        self.assertAlmostEqual(cat[1, NAMES.index("Kitchen")], 1.0)


if __name__ == "__main__":
    unittest.main()
