"""Read-only cause check for Bug 579: compares the negative-stock entries of two full-scale manifests.
Run by hand from a folder holding base/ and fix/ outputs (Learning 795); not part of the unit suite."""
import json
import sys

import pandas as pd

DEFECT_ID = "inventory.negative_on_hand"
WINDOW_END = "2026-10-30"


def negatives(manifest_path):
    """Return the recorded count and the set of keys for the negative-stock defect in one manifest."""
    with open(manifest_path, encoding="utf-8") as f:
        entries = {e["defect_id"]: e for e in json.load(f)["defects"]}
    entry = entries[DEFECT_ID]
    return entry["count"], set(entry["keys"])


def main():
    """Print the count change, the keys that differ, and a one-line reason for each key only the baseline has."""
    base_count, base_keys = negatives("base/out/answer_key/defects_manifest.json")
    fix_count, fix_keys = negatives("fix/out/answer_key/defects_manifest.json")
    print("count", base_count, "to", fix_count)
    print("only in baseline:", sorted(base_keys - fix_keys))
    print("only in fix:", sorted(fix_keys - base_keys))

    # The first store is the one whose weeks the generator removes
    truth = pd.read_parquet("base/out/answer_key/truth/inventory.parquet", columns=["store_id"])
    first_store = truth["store_id"].min()

    # Name the step that removed each key the fix no longer records
    unexpected = False
    for key in sorted(base_keys - fix_keys):
        store, _sku, day = key.split("|")
        if day >= WINDOW_END:
            print(key, "removed because it was delivered after the increment window")
        elif int(store) == first_store:
            print(key, "removed because it is in the first store, whose weeks are removed")
        else:
            print(key, "neither: tell the Architect")
            unexpected = True
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
