# Databricks notebook source
# MAGIC %md
# MAGIC # Drip feed
# MAGIC Copies files from `landing_staging` (everything you uploaded) into `landing` (what your
# MAGIC pipelines read), one delivery at a time, so ingestion sees files arrive the way they
# MAGIC would from real source systems.
# MAGIC
# MAGIC * `step = history` delivers the initial load (2025-01 .. 2026-09).
# MAGIC * `step = next` delivers the next undelivered increment day (2026-10-01, -02, ...).
# MAGIC * `step = 2026-10-07` delivers that specific day.
# MAGIC * `step = status` just reports what has been delivered.
# MAGIC
# MAGIC Layout in `landing`: `<source>/<entity>/<file>`, e.g. `oms/orders/orders_20261001.parquet`.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "retail")
dbutils.widgets.text("volume", "raw")
dbutils.widgets.text("step", "status")

base = f"/Volumes/{dbutils.widgets.get('catalog')}/{dbutils.widgets.get('schema')}/{dbutils.widgets.get('volume')}"
staging = f"{base}/landing_staging"
landing = f"{base}/landing"
log_path = f"{base}/_drip_log.txt"
step = dbutils.widgets.get("step").strip()

# COMMAND ----------

def delivered():
    try:
        return [l for l in dbutils.fs.head(log_path, 1_000_000).splitlines() if l]
    except Exception:
        return []


def walk(path):
    for f in dbutils.fs.ls(path):
        if f.isDir():
            yield from walk(f.path)
        else:
            yield f.path


def deliver(src_root, label):
    n = 0
    for p in walk(src_root):
        rel = p.split(src_root.rstrip("/") + "/", 1)[1]      # <source>/<entity>/<file>
        dbutils.fs.cp(p, f"{landing}/{rel}")
        n += 1
    dbutils.fs.put(log_path, "\n".join(delivered() + [label]) + "\n", overwrite=True)
    print(f"delivered {label}: {n} files")


days = sorted(f.name.rstrip("/").split("=", 1)[1] for f in dbutils.fs.ls(f"{staging}/increments"))
done = delivered()

if step == "status":
    print("delivered:", done or "nothing yet")
    print("remaining days:", [d for d in days if d not in done])
elif step == "history":
    if "history" in done:
        print("history already delivered")
    else:
        deliver(f"{staging}/history", "history")
else:
    if "history" not in done:
        raise ValueError("deliver step=history first")
    day = next((d for d in days if d not in done), None) if step == "next" else step
    if day is None:
        print("all increment days delivered")
    elif day in done:
        print(f"{day} already delivered")
    elif day not in days:
        raise ValueError(f"no staged increment for {day}")
    else:
        deliver(f"{staging}/increments/day={day}", day)
