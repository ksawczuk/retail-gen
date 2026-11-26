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
    customers   people -> customer records (3% duplicates), loyalty joins and tiers, addresses, CRM changes
    signups     gain-loyalty emails and paid Prospects flights change joins and signups
    build_demand  lifecycle (churn, fading, comebacks, basket size, category taste),
                  seasonality (shared curve, gifting peaks, category curves),
                  email campaigns (one DemandModifier per kind), DemandEngine.draw_all
                  (both channels, day by day), BasketBuilder (lines)
    online      orders drawn from the engine; lines, payment events, shipments, returns
    pos         baskets drawn from the engine (true customer, card scan), in-store returns
    web         sessions/events tied to real online orders + browse-only traffic
    inventory   weekly stock model per store x tracked SKU
    campaigns   answer key: designs, audiences, what each campaign truly did; email events
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
- **`bounded_weighted_pick`** (`util.py`) picks, for each line, a SKU that had launched by
  then, weighted by popularity, in one vectorised step. It uses cumulative weights plus
  `searchsorted`.
- **One demand engine.** `truth/demand.py` decides who buys on which day, online and in
  store, from one model. A customer's daily weight is their activity times their lifecycle
  level (`truth/lifecycle.py`: churn, fading, comebacks); the day's expected total is the
  channel's base rate times the seasonality (`truth/seasonality.py`). Customers are drawn
  in proportion to their weights, so recency and frequency carry real signal. The engine
  draws both channels day by day, so a campaign on a day sees what was bought before it.
- **Campaigns.** Each email campaign kind is a `DemandModifier` (`truth/campaigns.py`): on
  its send days it picks an audience (and a holdout, for some) and emails it; on later days
  it gives each treated customer a relative lift. The engine combines the lifts (the
  largest in full, others damped), raises the day's total accordingly, and marks a
  purchase above a customer's baseline as caused by the campaign. Gain-loyalty emails and
  paid flights act before the engine, on join dates and signups (`truth/signups.py`).
  A purchase a campaign caused leans to the campaign's promoted categories when its lines
  are picked. The answer key's `campaign_truth.parquet` holds what each campaign truly
  did, counted from those marks, with each campaign's nominal and realized lift.
- **What the store sees.** Every store basket has a true customer
  (`true_customer_id` in the truth). The POS shows `customer_id` only when a loyalty
  member who had already joined scans their card, about 40% of baskets.
- **Baskets.** `truth/baskets.py` picks each line's category from the customer's taste
  (a Dirichlet draw; the top three categories hold about two-thirds of a customer's
  taste) times that month's category season, then a SKU in that category launched by
  then. A customer's basket multiplier scales both the number of lines and the
  quantities.

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
