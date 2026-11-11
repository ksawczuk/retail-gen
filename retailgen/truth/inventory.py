"""Clean truth for weekly inventory snapshots (store x tracked SKU), from a simple stock model."""
import numpy as np
import pandas as pd

from .masterdata import store_open_matrix

NS = "datetime64[ns]"


def generate_inventory(cfg, rng, stores, store_events, products) -> pd.DataFrame:
    """Each Sunday: on-hand after a week of demand, with reorders when stock dips below the
    reorder point. Not reconciled to POS sales; the warehouse system models demand itself."""
    pool = products[(~products["pim_excluded"]) & (products["launched_at"] < cfg.history_start)]
    tracked = pool.nlargest(cfg.n_tracked_skus, "popularity")["sku"].to_numpy()
    first_sun = cfg.history_start + pd.Timedelta(days=(6 - cfg.history_start.dayofweek) % 7)
    weeks = pd.date_range(first_sun, cfg.increment_end, freq="7D")
    open_m = store_open_matrix(stores, store_events, weeks)
    S, K = len(stores), len(tracked)
    demand = rng.uniform(1, 12, (S, K))
    reorder = np.ceil(demand * 2).astype(int)
    order_qty = np.ceil(demand * 4).astype(int)
    on_hand = order_qty.copy()
    on_order = np.zeros((S, K), int)
    frames = []
    for w, wk in enumerate(weeks):
        on_hand = on_hand + on_order
        on_order = np.zeros((S, K), int)
        on_hand = np.maximum(on_hand - rng.poisson(demand), 0)
        low = on_hand < reorder
        on_order[low] = order_qty[low]
        si, ki = np.nonzero(np.repeat(open_m[w][:, None], K, axis=1))
        frames.append(pd.DataFrame({"snapshot_date": wk, "store_id": stores["store_id"].to_numpy()[si],
                                    "sku": tracked[ki], "on_hand": on_hand[si, ki],
                                    "on_order": on_order[si, ki], "reorder_point": reorder[si, ki]}))
    inv = pd.concat(frames, ignore_index=True)
    inv["snapshot_date"] = inv["snapshot_date"].astype(NS)
    return inv
