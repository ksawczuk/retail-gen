"""File output: lays files out the way they will sit in the Databricks volume.

All text is written with LF line endings regardless of OS.
"""
import gzip
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


def to_jsonable(v):
    """Convert numpy/pandas scalars to plain JSON values; NaN/NaT become null."""
    if v is None:
        return None
    if isinstance(v, dict):
        return {k: to_jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [to_jsonable(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isnan(f) else f
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


class Output:
    """Writes history and increment files under one root and logs each to the manifest."""

    def __init__(self, root: Path, manifest):
        self.root = Path(root)
        self.manifest = manifest

    def rel(self, day, source, entity, filename) -> str:
        if day is None:
            return f"history/{source}/{entity}/{filename}"
        return f"increments/day={pd.Timestamp(day):%Y-%m-%d}/{source}/{entity}/{filename}"

    def _path(self, rel) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def csv(self, df, day, source, entity, filename, encoding="utf-8", bom=False, bad_lines=None):
        """Write a CSV. `bad_lines` is a list of (row_position, raw_text) for malformed rows
        spliced in before that data row."""
        rel = self.rel(day, source, entity, filename)
        parts = [df.iloc[:0].to_csv(index=False, lineterminator="\n")]
        cuts = sorted(bad_lines or [], key=lambda x: x[0])
        start = 0
        for pos, raw in cuts:
            pos = min(max(pos, 0), len(df))
            parts.append(df.iloc[start:pos].to_csv(index=False, header=False, lineterminator="\n"))
            parts.append(raw.rstrip("\n") + "\n")
            start = pos
        parts.append(df.iloc[start:].to_csv(index=False, header=False, lineterminator="\n"))
        data = "".join(parts).encode(encoding, errors="replace")
        if bom:
            data = b"\xef\xbb\xbf" + data
        self._path(rel).write_bytes(data)
        self.manifest.note_file(rel, len(df) + len(cuts), "csv")
        return rel

    def jsonl(self, records, day, source, entity, filename, gz=False, bad_lines=None):
        """Write JSON Lines. `bad_lines` is a list of (position, raw_text) corrupt lines."""
        rel = self.rel(day, source, entity, filename)
        lines = [json.dumps(to_jsonable(r), ensure_ascii=False) for r in records]
        for pos, raw in sorted(bad_lines or [], key=lambda x: x[0], reverse=True):
            lines.insert(min(pos, len(lines)), raw)
        data = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
        p = self._path(rel)
        if gz:
            p.write_bytes(gzip.compress(data, compresslevel=6, mtime=0))
        else:
            p.write_bytes(data)
        self.manifest.note_file(rel, len(lines), "jsonl.gz" if gz else "jsonl")
        return rel

    def json_array(self, records, day, source, entity, filename):
        """Write one pretty-printed JSON array (needs multiLine when read by Spark)."""
        rel = self.rel(day, source, entity, filename)
        text = json.dumps(to_jsonable(list(records)), ensure_ascii=False, indent=2) + "\n"
        self._path(rel).write_bytes(text.encode("utf-8"))
        self.manifest.note_file(rel, len(records), "json")
        return rel

    def parquet(self, df, day, source, entity, filename):
        """Write one Parquet file with timestamps in microseconds (sub-microsecond parts are floored).
        Called by the OMS and inventory emitters for each history and increment file."""
        rel = self.rel(day, source, entity, filename)
        # Floor every timestamp column to microseconds, then write with the strict microsecond unit (GEN-01)
        df = df.copy()
        for column in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[column]):
                df[column] = df[column].dt.floor("us")
        df.to_parquet(self._path(rel), index=False, engine="pyarrow", coerce_timestamps="us")
        self.manifest.note_file(rel, len(df), "parquet")
        return rel

    def empty(self, day, source, entity, filename):
        rel = self.rel(day, source, entity, filename)
        self._path(rel).write_bytes(b"")
        self.manifest.note_file(rel, 0, "empty")
        return rel

    def duplicate(self, src_rel, new_filename):
        """Re-deliver an already-written file under a new name in the same folder."""
        src = self.root / src_rel
        rel = str(Path(src_rel).parent.as_posix()) + "/" + new_filename
        self._path(rel).write_bytes(src.read_bytes())
        info = self.manifest.files[src_rel]
        self.manifest.note_file(rel, info["rows"], info["kind"])
        return rel
