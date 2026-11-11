# How the generator works

The generator works in two stages. First it builds a **clean truth** world: what really
happened at Larchwood. Then it runs nine **source emulators**. Each one makes its system's
files from that truth, in that system's conventions, adding that system's defects.
Every defect is written to the answer-key manifest. Keeping the two stages apart is what
makes the answer key reliable: the truth stage ends with `check_truth()`, which proves the
clean world is consistent. So any inconsistency in the output must be one the emulators
added on purpose, and each of those was recorded.

```
generate.py
  Config(scale, seed)                     retailgen/config.py
  build_truth(cfg, rng)                   retailgen/truth/__init__.py
    masterdata  FX, stores (+ events), catalogue, price history, promos
    customers   people -> customer records (3% duplicates), addresses, CRM changes
    online      orders, lines, payment events, shipments, returns
    pos         baskets, in-store returns (incl. online orders returned in store)
    web         sessions/events tied to real online orders + browse-only traffic
    inventory   weekly stock model per store x tracked SKU
    check_truth referential + arithmetic assertions
  EMITTERS                                retailgen/sources/__init__.py
    crm, pim, storeops, finance, promo, oms, pos, web, inventory
      -> Output (retailgen/writers.py): CSV / JSONL / JSON / Parquet, LF endings
      -> Manifest (retailgen/manifest.py): defect id, count, example keys
           metadata looked up in the catalogue (retailgen/defects.py)
  write answer_key/; fail if a catalogued defect was never recorded
validate.py                               re-reads the files; does not import retailgen
```

## Concepts worth knowing

- **One RNG, passed in.** `numpy.random.default_rng(seed)` is created once and handed to
  every function, so a seed gives the same world every time and any piece can be tested
  on its own with its own rng.
- **Delivery date vs event date.** Every row has the time it happened and the time it
  arrives. `sources/common.py: route()` sends a row to the history load or to an
  increment day based on when it *arrives*. Late arrivals (`make_late`) are rows whose
  arrival is pushed back, so they land in a later day's folder than their own timestamp.
- **Versioned vs append-only feeds.** OMS orders and shipments resend the whole row on
  every status change (the latest `updated_at` wins). Lines, payments and returns are
  written once. The history files hold the *latest version as of cut-over*. The daily files
  hold every version that arrived that day.
- **Systemic vs injected defects.** A systemic defect is how a system always behaves (POS
  money in cents). An injected one hits specific rows (a duplicated order). The catalogue
  flags which is which.
- **The defect catalogue.** `retailgen/defects.py` declares every defect once as a frozen
  `Defect` (id, source, entity, category, description, systemic). Emitters only inject and
  then call `man.record(defect_id, count, keys=..., **detail)`. `detail` fills the
  description's `{placeholders}` with run-specific values (a store id, a date), and the
  names must match exactly. Three guards keep the catalogue and the code in step:
  recording an undeclared id fails, a wrong set of `detail` names fails, and `generate.py`
  fails at the end if a declared defect was never recorded. The catalogue is a spoiler,
  just like `answer_key/`.
- **`bounded_weighted_pick`** (`util.py`) picks, for each order, a customer or SKU that
  already existed at that time, weighted by activity or popularity, in one vectorised
  step. It uses cumulative weights plus `searchsorted`.

## Changing things

- Volumes: the `base_*` fields in `config.py`, or `--scale`.
- Dates: `history_start`, `history_end`, `increment_end`, `clickstream_start` in `config.py`.
- A new defect: declare it in `retailgen/defects.py`. Then inject it in the relevant
  `sources/*.py` and call `man.record(id, count, ...)` with the exact affected count. If
  it can be counted from the files, also add a check to `validate.py`.
- Reruns are byte-identical for the same seed and scale; the gzip header timestamp is
  fixed at 0. So after a refactor you can `diff -r` the old and new output folders to prove
  the data didn't change.
- Defect *rates* are the literals next to each injection (e.g. `0.004 * n`), so they're
  easy to find and tweak.

## Gotchas found while building

- pandas 3 stores strings as Arrow arrays by default, and walking them row by row is
  slow. `retailgen/__init__.py` switches back to object strings.
- Missing values in string columns come back as `NaN` (a float), not `None`. Code that
  tests `if value:` treats `NaN` as true, so use `isinstance(v, str)` or `is_null()`.
