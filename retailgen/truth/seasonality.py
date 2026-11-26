"""Demand seasonality: the shared daily curve with its gifting peaks, and a monthly curve per category.

Built once by build_truth; the demand engine reads the shared curve, the basket builder the category curves.
"""
import numpy as np
import pandas as pd

from ..util import seasonality as shared_curve

GIFTING_DAYS = 10
GIFTING_TOTAL = 1.25
MOTHERS_DAY_CATEGORIES = {"Decor": 1.8, "Kitchen": 1.5, "Bedding": 1.5, "Tops": 1.6}
FATHERS_DAY_CATEGORIES = {"Audio": 1.8, "Camping": 1.5, "Cycling": 1.5, "Sneakers": 1.6}

# Month 1..12 multipliers; a category not listed follows the shared curve only
CATEGORY_MONTHS = {
    "Outerwear": [1.3, 1.1, 0.9, 0.7, 0.6, 0.5, 0.5, 0.5, 0.9, 1.3, 1.6, 1.6],
    "Boots": [1.3, 1.1, 0.9, 0.7, 0.6, 0.5, 0.5, 0.5, 0.9, 1.3, 1.6, 1.6],
    "Water Sports": [0.3, 0.3, 0.3, 0.7, 1.2, 2.0, 2.0, 2.0, 1.2, 0.7, 0.3, 0.3],
    "Camping": [0.6, 0.6, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.0, 0.6, 0.6, 0.6],
    "Cycling": [0.6, 0.6, 1.5, 1.5, 1.5, 1.5, 1.5, 1.5, 1.0, 0.6, 0.6, 0.6],
    "Decor": [1.0, 1.0, 1.3, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.5, 1.5],
    "Bedding": [1.0, 1.0, 1.3, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.5, 1.5],
    "Audio": [1.0, 1.0, 1.0, 1.0, 1.0, 1.3, 1.0, 1.0, 1.0, 1.0, 1.6, 1.6],
}


def mothers_day(year):
    """The second Sunday of May."""
    may_first = pd.Timestamp(year=year, month=5, day=1)
    return may_first + pd.Timedelta(days=(6 - may_first.dayofweek) % 7 + 7)


def fathers_day(year):
    """The third Sunday of June."""
    june_first = pd.Timestamp(year=year, month=6, day=1)
    return june_first + pd.Timedelta(days=(6 - june_first.dayofweek) % 7 + 14)


class Seasonality:
    """The shared demand multiplier per day and each category's multiplier per day."""

    def __init__(self, days, category_names):
        """Build both curves for the given days and categories (names in the order the basket builder uses)."""
        self.days = pd.DatetimeIndex(days)
        self.category_names = list(category_names)

        # Mark the gifting windows: the days before each Mother's Day and Father's Day
        self._mothers = self._window(mothers_day)
        self._fathers = self._window(fathers_day)
        gifting = self._mothers | self._fathers

        # Shared curve: the generator's long-standing curve, raised in the gifting windows
        self._shared = np.asarray(shared_curve(self.days), float) * np.where(gifting, GIFTING_TOTAL, 1.0)

        # Category curves: the monthly shape, times the gifting lift for that holiday's categories
        months = self.days.month.to_numpy() - 1
        cat = np.ones((len(self.days), len(self.category_names)))
        for k, name in enumerate(self.category_names):
            if name in CATEGORY_MONTHS:
                cat[:, k] = np.asarray(CATEGORY_MONTHS[name])[months]
            if name in MOTHERS_DAY_CATEGORIES:
                cat[self._mothers, k] *= MOTHERS_DAY_CATEGORIES[name]
            if name in FATHERS_DAY_CATEGORIES:
                cat[self._fathers, k] *= FATHERS_DAY_CATEGORIES[name]
        self._category = cat

    def shared(self):
        """The demand multiplier for each day."""
        return self._shared

    def category(self, day_index):
        """A (len(day_index), n_categories) matrix of category multipliers for the given day positions."""
        return self._category[np.asarray(day_index)]

    def gifting_days(self):
        """A boolean per day: True inside a Mother's Day or Father's Day window."""
        return self._mothers | self._fathers

    def _window(self, holiday):
        """True for the GIFTING_DAYS days before the holiday in each year covered."""
        mask = np.zeros(len(self.days), dtype=bool)
        for year in sorted(set(self.days.year)):
            day = holiday(year)
            mask |= (self.days >= day - pd.Timedelta(days=GIFTING_DAYS)) & (self.days < day)
        return mask
