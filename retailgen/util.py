"""Small sampling and date helpers shared by the generators."""
import unicodedata

import numpy as np
import pandas as pd


def seasonality(days: pd.DatetimeIndex) -> np.ndarray:
    """Demand multiplier per day: holiday peak, January slump, weekend lift, mild growth."""
    month_factor = {1: 0.8, 2: 0.85, 3: 0.95, 4: 1.0, 5: 1.0, 6: 1.05, 7: 1.1, 8: 1.05,
                    9: 0.95, 10: 1.0, 11: 1.35, 12: 1.6}
    m = np.array([month_factor[x] for x in days.month])
    weekend = np.where(days.dayofweek >= 5, 1.15, 1.0)
    growth = 1.0 + 0.15 * (days - days[0]).days / 365.0
    bf = np.where((days.month == 11) & (days.day >= 24) & (days.day <= 30), 1.8, 1.0)
    return m * weekend * growth * bf


def bounded_weighted_pick(rng, cumw: np.ndarray, upper: np.ndarray) -> np.ndarray:
    """For each i pick an index in [0, upper[i]) with probability proportional to the weights
    behind the cumulative-weight array `cumw`. Requires upper >= 1."""
    upper = np.asarray(upper)
    u = rng.random(len(upper)) * cumw[upper - 1]
    return np.minimum(np.searchsorted(cumw, u, side="right"), upper - 1)


def seconds_in_day(rng, n: int, hour_weights) -> np.ndarray:
    """Random second-of-day offsets following an hourly weight profile."""
    w = np.asarray(hour_weights, dtype=float)
    hours = rng.choice(24, size=n, p=w / w.sum())
    return hours * 3600 + rng.integers(0, 3600, size=n)


def ascii_fold(s: str) -> str:
    """'Chloé Côté' -> 'Chloe Cote' (used for email local parts)."""
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def mojibake(s: str) -> str:
    """Simulate UTF-8 bytes being decoded as Latin-1: 'Zoë' -> 'ZoÃ«'."""
    try:
        return s.encode("utf-8").decode("latin-1")
    except UnicodeDecodeError:
        return s


def fmt_dates(rng, ts: pd.Series, formats, p) -> pd.Series:
    """Render each timestamp with a randomly chosen strftime format (NaT -> None)."""
    choice = rng.choice(len(formats), size=len(ts), p=p)
    out = pd.Series([None] * len(ts), index=ts.index, dtype=object)
    for i, f in enumerate(formats):
        m = (choice == i) & ts.notna().to_numpy()
        if m.any():
            out[m] = ts[m].dt.strftime(f)
    return out


def pick_rows(rng, n_total: int, k: int) -> np.ndarray:
    """k distinct row positions out of n_total (fewer if n_total is small)."""
    k = int(min(k, n_total))
    if k <= 0:
        return np.array([], dtype=int)
    return np.sort(rng.choice(n_total, size=k, replace=False))
