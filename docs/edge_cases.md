# Edge cases: generator output

Scenarios the generator handles on purpose, and why. One entry per case; code comments carry only the ID.

- **GEN-01 Parquet timestamps are written in microseconds.** pandas holds timestamps in nanoseconds, and Parquet files
  written that way carry `TIMESTAMP(NANOS)`, which some Spark versions cannot read. `Output.parquet` therefore floors
  every timestamp column to microseconds and writes the file with the microsecond unit. The generator does produce
  sub-microsecond parts (for example from adding a fractional delta), so the floor loses at most one microsecond per
  value; Spark itself holds no finer precision. The change alters the bytes of every Parquet file on purpose; the rerun
  test compares two runs of the same code, so it needs no new baseline. The truth tables written by `generate.py` stay in
  nanoseconds and never leave datapig.
