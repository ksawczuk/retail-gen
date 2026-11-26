"""Generate the dirty retail dataset.

    python generate.py                     # full size (~1.5M transaction lines)
    python generate.py --scale 0.01        # quick smoke run
    python generate.py --no-truth          # skip the clean truth tables in answer_key/

Output:
    <out>/landing_staging/history/...                  upload these to the volume
    <out>/landing_staging/increments/day=YYYY-MM-DD/...
    <out>/answer_key/                                  keep sealed; for checking your work
"""
import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np

from retailgen.avro import MissingDependency
from retailgen.config import Config
from retailgen.manifest import Manifest
from retailgen.sources import EMITTERS
from retailgen.truth import build_truth
from retailgen.writers import Output, floor_timestamps


def write_truth(t, folder: Path):
    """Clean truth tables, so silver/gold results can be scored against what really happened."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in ["customers", "addresses", "customer_events", "address_events", "orders", "order_lines",
                 "payments", "shipments", "returns", "pos_lines", "products", "price_history",
                 "categories", "suppliers", "promotions", "stores", "fx", "inventory", "clickstream",
                 "campaigns", "campaign_assignment", "campaign_truth", "prospect_customers", "engagement_events"]:
        df = getattr(t, name).copy()
        for c in df.columns:
            if df[c].dtype == object:
                df[c] = df[c].map(lambda v: None if v is None else str(v))
        # Microsecond timestamps, the same as the landing files (GEN-01)
        floor_timestamps(df).to_parquet(folder / f"{name}.parquet", index=False, coerce_timestamps="us")
    events = [{k: (str(v) if k == "day" or k == "closed_at" else v) for k, v in e.items()} for e in t.store_events]
    with open(folder / "store_events.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump({"store_events": events, "deleted_customers": sorted(t.deleted_customers)}, f, indent=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=Config.seed)
    ap.add_argument("--out", default="out")
    ap.add_argument("--no-truth", action="store_true")
    ap.add_argument("--skip-source", action="append", default=[], choices=[name for name, _ in EMITTERS],
                    help="leave one source out of the run (repeatable); recorded in answer_key/run.json")
    args = ap.parse_args()

    cfg = Config(scale=args.scale, seed=args.seed)
    rng = np.random.default_rng(cfg.seed)
    root = Path(args.out)
    if root.exists():
        shutil.rmtree(root)
    t0 = time.time()

    def log(msg):
        print(f"[{time.time() - t0:6.1f}s] {msg}", flush=True)

    truth = build_truth(cfg, rng, log)
    man = Manifest()
    out = Output(root / "landing_staging", man)
    for name, emit in EMITTERS:
        if name in args.skip_source:
            log(f"source: {name} skipped")
            continue
        log(f"source: {name}")
        try:
            emit(cfg, rng, truth, out, man)
        except MissingDependency as exc:
            raise SystemExit(f"stopped at source {name}: {exc}") from None
    man.write(root / "answer_key")
    missing = man.unrecorded(args.skip_source)
    # Stop without run.json when a declared defect was never recorded; the ids go to the sealed folder, not the screen
    if missing:
        man.write_unrecorded(root / "answer_key")
        raise SystemExit(man.incomplete_message(cfg.scale, cfg.seed, args.skip_source))
    if not args.no_truth:
        log("answer key: truth tables")
        write_truth(truth, root / "answer_key" / "truth")
    with open(root / "answer_key" / "run.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump({"scale": cfg.scale, "seed": cfg.seed, "skipped_sources": sorted(args.skip_source)}, f)
    size = sum(p.stat().st_size for p in (root / "landing_staging").rglob("*") if p.is_file())
    log(f"done: {len(man.files)} files, {size / 1e6:.1f} MB in landing_staging")


if __name__ == "__main__":
    main()
