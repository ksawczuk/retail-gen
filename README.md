# databricks-retail-data

A synthetic, **deliberately dirty** first-party retail dataset for working through a
Databricks medallion build: ingestion → bronze → cleansing → silver → gold.

The company is *Larchwood Supply Co.*, a fictional Canadian retailer with nine source systems:
CRM, PIM, store ops, e-commerce OMS, POS, promotions, web analytics, inventory and FX. There
are ~21 months of history (2025-01-01 → 2026-09-30), then 30 daily increments
(2026-10-01 → 2026-10-30).

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

## Generate

Uses the `analysis` conda env (numpy, pandas, pyarrow):

```bash
~/miniforge3/envs/analysis/python.exe generate.py
~/miniforge3/envs/analysis/python.exe validate.py out
```

`--scale 0.1` gives a ~10% copy for quick experiments. `--seed` changes the random world
(the same seed always gives the same files). `--no-truth` skips writing the truth tables.

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
  resolution answer.
- Possible gold marts, as starting points only: daily sales by channel/store, customer
  360/RFM, product and category performance, returns and refunds, web funnel conversion,
  inventory cover.

## Code

See `docs/walkthrough.md`.
