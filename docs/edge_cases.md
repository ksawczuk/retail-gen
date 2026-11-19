# Edge cases: generator output

Scenarios the generator handles on purpose, and why. One entry per case; code comments carry only the ID.

- **GEN-01 Parquet timestamps are written in microseconds.** pandas holds timestamps in nanoseconds, and Parquet files
  written that way carry `TIMESTAMP(NANOS)`, which some Spark versions cannot read. `Output.parquet` therefore floors
  every timestamp column to microseconds and writes the file with the microsecond unit. The generator does produce
  sub-microsecond parts (for example from adding a fractional delta), so the floor loses at most one microsecond per
  value; Spark itself holds no finer precision. The change alters the bytes of every Parquet file on purpose; the rerun
  test compares two runs of the same code, so it needs no new baseline. The truth tables written by `generate.py` are
  floored and written the same way, so landing and truth agree. A test at scale 0.01 checks that flooring creates no
  new ties: for each Parquet entity and timestamp column, the number of distinct (key, timestamp) pairs is the same
  before and after.

- **GEN-02 A small run still reaches every guarded POS step.** Two steps in the POS emitter ran only when a given store
  had a nightly file on a given increment day, so at a small scale some seeds never reached one and the end-of-run
  guard stopped the run (Bug 553). Each step now runs on the first day from its usual day that the store has a file,
  with a fallback if it has none. At the usual seed and scale the store has a file on the usual day, so each step runs
  there as before, no random draw moves, and the files are byte-identical (checked by hashing every file at scales
  0.01 and 0.05 before and after).
- **GEN-03 A run that fails the guard is not marked finished.** The guard message names the scale and seed and never a
  defect id; the ids go to `answer_key/unrecorded_defects.txt`. `generate.py` writes `run.json` last, after the guard,
  so a failed run has none, and `validate.py` refuses output without it. The slow small-scale regression test is in
  `tests/test_small_scale.py` and runs only with `RETAILGEN_SLOW=1`.

