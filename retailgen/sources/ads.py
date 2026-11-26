"""Ad agencies' daily spend reports for the paid Prospects flights, one CSV per day (monthly files in the history).

Called by generate.py after the other sources; reads the campaign answer key for each flight's dates and spend.
"""
import numpy as np
import pandas as pd

from ..util import pick_rows
from .common import by_month, route

SRC = "ads"
AGENCIES = ("Northline Media", "Brightpath Digital")
USD_AGENCY = "Brightpath Digital"
COST_PER_THOUSAND = 9.0
CLICK_RATE = 0.012


def emit(cfg, rng, t, out, man):
    """Write the agencies' daily spend by utm_campaign, with one agency in USD and a few days missing."""
    rows = _daily_spend(rng, t)

    # One agency reports in US dollars
    usd = rows["agency"].eq(USD_AGENCY).to_numpy()
    rate = rows["date"].map(t.fx.set_index("date")["usd_cad"]).ffill().bfill().to_numpy()
    rows.loc[usd, "spend"] = np.round(rows.loc[usd, "spend"].to_numpy() / rate[usd], 2)
    rows["currency"] = np.where(usd, "USD", "CAD")
    man.record("ads.usd_agency", 1, agency=USD_AGENCY)

    # A few days never arrive
    gone = pick_rows(rng, len(rows), cfg.count(3, 3))
    man.record("ads.missing_days", len(gone), keys=rows.iloc[gone]["date"].dt.strftime("%Y-%m-%d") + " " +
               rows.iloc[gone]["utm_campaign"])
    rows = rows.drop(index=rows.index[gone]).reset_index(drop=True)

    # History by month, then one file per increment day
    hist, days = route(cfg, rows, rows["date"])
    for month, g in by_month(hist, hist["date"]).items():
        out.csv(_formatted(g), None, SRC, "spend", f"ads_spend_{month}.csv")
    for day, g in days.items():
        out.csv(_formatted(g), day, SRC, "spend", f"ads_spend_{day:%Y%m%d}.csv")


def _daily_spend(rng, t):
    """Each flight's spend spread over its days, with impressions and clicks, in CAD."""
    flights = t.campaigns[t.campaigns["kind"] == "prospects"].merge(
        t.campaign_truth[["campaign_id", "spend"]], on="campaign_id")
    parts = []
    for k, f in enumerate(flights.itertuples(index=False)):
        days = pd.date_range(pd.Timestamp(f.sends.split(",")[0]), periods=int(f.flight_days), freq="D")
        share = rng.dirichlet(np.full(len(days), 5.0))
        spend = np.round(float(f.spend) * share, 2)
        impressions = np.round(spend / COST_PER_THOUSAND * 1000 * rng.uniform(0.8, 1.2, len(days))).astype(int)
        parts.append(pd.DataFrame({"date": days, "agency": AGENCIES[k % 2], "utm_campaign": f.utm_campaign,
                                   "impressions": impressions,
                                   "clicks": rng.binomial(impressions, CLICK_RATE), "spend": spend}))
    return pd.concat(parts, ignore_index=True).sort_values(["date", "utm_campaign"]).reset_index(drop=True)


def _formatted(g):
    """The agencies' file layout: ISO dates and the reported columns."""
    return pd.DataFrame({"date": g["date"].dt.strftime("%Y-%m-%d"), "agency": g["agency"],
                         "utm_campaign": g["utm_campaign"], "impressions": g["impressions"], "clicks": g["clicks"],
                         "spend": g["spend"].map(lambda v: f"{v:.2f}"), "currency": g["currency"]})
