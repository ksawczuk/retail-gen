# databricks-retail-data

Tutorial datasets are usually too clean. Real first-party data comes from several systems that
disagree with each other, arrives late or twice, changes shape without warning, and is
documented by people who were slightly wrong. This repo generates that kind of data, at a
known level of dirtiness, for working through a Databricks medallion build: ingestion →
bronze → cleansing → silver → gold.

The company is *Larchwood Supply Co.*, a fictional Canadian retailer with nine source systems:
CRM, PIM, store ops, e-commerce OMS, POS, promotions, web analytics, inventory and FX. There
are ~21 months of history (2025-01-01 → 2026-09-30), then 92 daily increments
(2026-10-01 → 2026-12-31) that you release one day at a time, so your ingestion sees files
arrive the way it would in production.

### How it is built

```
seed ─▶ clean "truth" world ─▶ check_truth() ─▶ 9 source emulators ─▶ landing files
          (what really              (proves it's        (each adds its own     │
           happened)                 consistent)         defects, and logs     │
                                                         every one)            ▼
                                                    answer key ◀──── validate.py re-counts
```

- **Clean world first, dirt second.** The generator builds a consistent retailer and checks it,
  then hands it to emulators of each source system. Each one writes files in its own system's
  format, time zone and conventions, with its own bugs. So every inconsistency in the output
  was put there on purpose.
- **A sealed answer key.** About 100 kinds of defect, each counted, with example keys:
  duplicate customers under different IDs, CDC deletes of keys that never existed, a column
  renamed mid-month, refunds larger than the charge, files in the wrong encoding, bot traffic.
  The clean truth tables are included too, so you can score both your cleansing and your
  gold numbers.
- **Checked independently.** `validate.py` re-reads the written files and re-counts defects
  against the answer key without importing the generator, so a generator bug can't vouch for
  itself.
- **Reproducible.** The same seed and scale produce byte-identical files, and `--scale`
  shrinks the whole world for quick experiments.

> **Spoilers:** `answer_key/` and `retailgen/defects.py` list every defect. Work from the files
> and `docs/source_system_docs.md` first, and open those only to check yourself.

The output is plain CSV, JSON and Parquet files, so only the loading steps below are specific
to Databricks. The data works for any platform's tutorial.

| | full scale (default) |
|---|---|
| online orders | ~400k (≈900k lines) |
| POS basket lines | ~650k |
| customers | 60k |
| products | 5k SKUs |
| clickstream events | ~1.3M (from 2026-01-01) |
| inventory snapshot rows | ~1.5M |
| raw size | ~300 MB |
| run time | ~10–15 min |

The counts, size and run time above were measured on the 30-day window. The window now runs to 2026-12-31
(92 increment days); the full-scale figures for it are not measured yet. At `--scale 0.1` the 92-day run
takes about 3.5 minutes and writes about 42 MB.

## Generate

Needs Python 3 with numpy, pandas and pyarrow (built with numpy 2.4, pandas 3.0, pyarrow 23):

```bash
python generate.py
python validate.py out
```

`--scale 0.1` gives a ~10% copy for quick experiments. `--seed` changes the random world
(the same seed always gives the same files). `--no-truth` skips writing the truth tables.

A run can stop with a message naming the scale and seed when the output would not match the catalogue, which can
happen at small scales for some seeds. That output is incomplete (it has no `answer_key/run.json`, and `validate.py`
refuses it): regenerate it with a larger scale or another seed. The ids that were missed are listed in
`answer_key/unrecorded_defects.txt`, which belongs to the sealed answer key.

Output:

```
out/
  landing_staging/                 <- upload this whole folder to your volume
    history/<source>/<entity>/...
    increments/day=2026-10-01/<source>/<entity>/...
    ...
  answer_key/                      <- do NOT upload; sealed until you want to check yourself
    defects.md                     every defect that was injected, with counts
    defects_manifest.json          same, with example keys per defect
    truth/*.parquet                the clean world the dirty files were made from
```

## Load into Databricks Free Edition

1. In Catalog, create a schema (e.g. `workspace.retail`) and a **managed volume** in it
   (e.g. `raw`).
2. Upload `out/landing_staging` into the volume as `landing_staging`. The CLI keeps the
   folder structure:
   ```bash
   databricks fs cp -r out/landing_staging dbfs:/Volumes/workspace/retail/raw/landing_staging
   ```
   (The Catalog UI upload works too, but one folder at a time.)
3. Import `notebooks/drip.py` as a notebook. Run it with `step = history`, then
   `step = next` once per simulated day. It copies files into
   `/Volumes/workspace/retail/raw/landing/<source>/<entity>/`, which is what your
   ingestion should read.

Free Edition limits that matter here (checked 2026-11-10): serverless only, one 2X-Small
SQL warehouse, 5 concurrent job tasks, one active pipeline per type, Python/SQL only, and
a daily fair-use compute quota. If you go over it, compute stops until the next day; your
data is kept. The dataset is sized so a full rerun is cheap.

## Working from it

- `docs/source_system_docs.md` is what each source team *says* about their feed. It is
  incomplete and in places wrong, like real handover notes.
- `answer_key/` holds everything that was done to the data. Use `defects.md` to score
  your bronze/silver findings, and `truth/` to check silver/gold numbers against what
  really happened. Customer `person_id` in `truth/customers.parquet` is the identity
  resolution answer. The `campaign*`, `prospect_customers` and `engagement_events` tables
  hold the marketing truth: each campaign's audience, holdout and true effect.
- Possible gold marts, as starting points only: daily sales by channel/store, customer
  360/RFM, product and category performance, returns and refunds, web funnel conversion,
  inventory cover.

## Feeding a Databricks volume from a server

`pusher/` uploads `landing_staging/` to a Databricks volume, one delivery at a time (`history`, or `day YYYY-MM-DD`). It
runs in Docker, uses only the standard library and depends only on the landing layout. See `pusher/README.md` for the
run interface (command, environment, exit codes, log).

## Code

See `docs/walkthrough.md`.

## Licence

MIT. See `LICENSE`.
