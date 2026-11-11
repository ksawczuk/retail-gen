"""Helpers shared by the source-system emulators: delivery routing and value mangling."""
import numpy as np
import pandas as pd

from .. import reference as ref


def delivery_day(ts: pd.Series) -> pd.Series:
    return pd.to_datetime(ts).dt.normalize()


def make_late(rng, deliver: pd.Series, frac: float, lo: int, hi: int):
    """Push a fraction of deliveries back by lo..hi days. Returns (new_deliver, late_mask)."""
    late = rng.random(len(deliver)) < frac
    lag = pd.to_timedelta(rng.integers(lo, hi + 1, len(deliver)), unit="D")
    return deliver.where(~late, deliver + lag), late


def route(cfg, df: pd.DataFrame, deliver: pd.Series):
    """Split rows into the history load and per-increment-day batches by delivery day.
    Rows delivered after the window are dropped (they never arrive)."""
    d = delivery_day(deliver)
    hist = df[(d <= cfg.history_end).to_numpy()]
    in_win = ((d > cfg.history_end) & (d <= cfg.increment_end)).to_numpy()
    days = {day: g for day, g in df[in_win].groupby(d[in_win].to_numpy())}
    return hist, days


def by_month(df: pd.DataFrame, ts: pd.Series):
    """Group history rows into monthly files keyed 'YYYY-MM'."""
    key = pd.to_datetime(ts).dt.strftime("%Y-%m").to_numpy()
    return {k: g for k, g in df.groupby(key)}


def phone_formats(rng, e164) -> list:
    out = []
    for e in e164:
        if e is None or (isinstance(e, float) and np.isnan(e)):
            out.append(None)
            continue
        a, b, c = e[2:5], e[5:8], e[8:12]
        k = rng.integers(5)
        out.append([f"({a}) {b}-{c}", f"{a}-{b}-{c}", f"{a}{b}{c}", f"+1 {a} {b} {c}", f"{a}.{b}.{c}"][k])
    return out


def variant(rng, values, mapping, keep_p=0.6) -> list:
    """Replace canonical codes with a spelling variant some of the time."""
    out = []
    for v in values:
        opts = mapping.get(v)
        if not opts or rng.random() < keep_p:
            out.append(v)
        else:
            out.append(opts[rng.integers(len(opts))])
    return out


def postal_variant(rng, values, frac=0.3) -> list:
    out = []
    for v in values:
        if v is None or not isinstance(v, str) or " " not in v or rng.random() > frac:
            out.append(v)
            continue
        k = rng.integers(3)
        out.append([v.lower(), v.replace(" ", ""), v.replace(" ", "-")][k])
    return out


def disguised_null(rng, n, tokens=("", "N/A", "null", "-")) -> list:
    return [tokens[i] for i in rng.integers(0, len(tokens), n)]


def cents(x) -> np.ndarray:
    return np.round(np.asarray(x, dtype=float) * 100).astype(np.int64)


def code_variant(rng, codes, frac=0.15) -> list:
    """Coupon/promo codes typed by humans: lower case, stray spaces."""
    out = []
    for c in codes:
        if c is None or (isinstance(c, float) and np.isnan(c)) or rng.random() > frac:
            out.append(c)
        else:
            out.append([c.lower(), c + " ", " " + c, c.title()][rng.integers(4)])
    return out


def is_null(v) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT


CITY_LOOKUP = {c[0]: c for c in ref.CITIES}
