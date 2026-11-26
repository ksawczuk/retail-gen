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

- **GEN-04 Each guaranteed store is placed without removing the other.** The store generator guarantees at least one
  QC store and one US store. The US guarantee picks the first slot from 1 up that does not hold the only QC store, so at
  the smallest scale (6 stores) the two never cancel and the run no longer stops in the store generator (Bug 677). A
  slot differs from the old choice only where the old choice removed the only QC store, which stopped the run, so no run
  that finished before changes (checked by hashing every file at scales 0.01 and 0.05 before and after). The seed list
  test is `tests/test_store_slots.py`.


- **GEN-22 A planted problem is recorded only for rows that are written (Bug 579).** One emitter recorded a planted
  problem before later steps (a removed span of rows, rows delivered after the window) could drop the rows it was
  planted on, so the manifest could count a row that never reached the files. The record now comes after routing and
  keeps only the planted rows that are written. A written row that was not planted is not counted, so it cannot hide
  behind a matching total. No random draw moves, so the landing files are byte-identical; only that manifest entry
  changes. The test is `tests/test_inventory_manifest_written_rows.py`.

### Pusher

- **PSH-01 `next` records a day only after a clean push.** A day goes into the state file only when every file was
  sent or skipped; with any failed file the run exits 1 and records nothing, so the next run pushes the same day again
  (files already in the volume with the same size are skipped). A dry run records nothing either. The state file is
  written to a temporary file, flushed and synced to disk, then renamed over the old one, so a crash or power cut
  leaves the old or the new list, never an empty or partial one.
- **PSH-02 Only the newest pushed day can be unmarked.** The pushed days must stay an unbroken run from the first
  increment day, because the daily load in bronze refuses a day whose earlier days are not complete. Removing an older
  day while a later one stays recorded would leave a gap that `next` fills out of order, so `unmark` refuses it and
  names the day to unmark first. `unmark` changes only the state file; removing the day's files from the volume is a
  separate runbook step.
- **PSH-03 The increment days come from the data, and the state path has no default.** `next` reads the days from the
  `increments/day=` folders, so the feed ends wherever the generated data ends with no date in the code. The state
  path must be given: a default would let a run whose state folder was not mounted start again at the first day. A
  missing state folder, a state inside the landing folder, or a file that is not an unbroken run of increment days stops
  the run with exit 2.
- **PSH-04 One run at a time.** `next` and `unmark` hold a lock file beside the state while they run, created
  exclusively, so the daily timer and a manual run cannot both change the state. A second run exits 2 and names the lock.
  A lock left by a killed run is removed by hand, once no pusher is running; the run does not guess whether a lock is
  stale.
