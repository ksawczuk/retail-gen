"""The answer key: every defect the generator injects is recorded here with its size."""
import json
from collections import OrderedDict
from pathlib import Path

from .defects import REGISTRY

MAX_KEYS = 5000


class Manifest:
    """Accumulates defect records; the same defect id across many files adds up."""

    def __init__(self, registry=REGISTRY):
        self._registry = registry
        self._entries: "OrderedDict[str, dict]" = OrderedDict()
        self.files: dict = {}

    def record(self, defect_id, count, keys=None, **detail):
        """Add `count` affected rows (or files) to a catalogued defect, keeping up to MAX_KEYS
        example keys. `detail` fills the description's placeholders (first record wins)."""
        if defect_id not in self._registry:
            raise KeyError(f"defect {defect_id!r} is not declared in retailgen/defects.py")
        d = self._registry[defect_id]
        count = int(count)
        e = self._entries.get(defect_id)
        if e is None:
            e = {"defect_id": d.id, "source": d.source, "entity": d.entity,
                 "category": d.category, "description": d.describe(**detail), "systemic": d.systemic,
                 "count": 0, "keys": []}
            self._entries[defect_id] = e
        e["count"] += count
        if keys is not None:
            room = MAX_KEYS - len(e["keys"])
            if room > 0:
                e["keys"].extend(str(k) for k in list(keys)[:room])

    def count(self, defect_id) -> int:
        return self._entries[defect_id]["count"] if defect_id in self._entries else 0

    def unrecorded(self, skipped_sources=()) -> list:
        """Catalogued defects no emitter recorded: the catalogue and the code have drifted apart. Defects of a
        source the run skipped on purpose are not counted."""
        skipped = set(skipped_sources)
        return [i for i in self._registry if i not in self._entries and self._registry[i].source not in skipped]

    def incomplete_message(self, scale, seed, skipped_sources=()):
        """One line for a run that left declared defects unrecorded: scale, seed and counts, no defect ids."""
        missing, declared = len(self.unrecorded(skipped_sources)), len(self._registry)
        return (f"scale {scale}, seed {seed}: the run recorded {declared - missing} of {declared} declared "
                "defects, so its output is not complete and must be regenerated. Small scales cannot always "
                "record all of them: use a larger scale or another seed. The ids are in "
                "answer_key/unrecorded_defects.txt.")

    def write_unrecorded(self, folder: Path):
        """List the unrecorded ids, one per line, in the sealed answer-key folder."""
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / "unrecorded_defects.txt", "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(self.unrecorded()) + "\n")

    def note_file(self, rel_path, rows, kind):
        """Remember each written file and its row count, for the validator."""
        self.files[rel_path] = {"rows": int(rows), "kind": kind}

    def write(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        entries = list(self._entries.values())
        with open(folder / "defects_manifest.json", "w", encoding="utf-8", newline="\n") as f:
            json.dump({"defects": entries, "files": self.files}, f, ensure_ascii=False, indent=1)
        lines = ["# Injected defects (answer key)", "",
                 "Open only to check your own findings.", "",
                 "| defect_id | source | entity | category | systemic | count | description |",
                 "|---|---|---|---|---|---|---|"]
        for e in entries:
            lines.append(f"| `{e['defect_id']}` | {e['source']} | {e['entity']} | {e['category']} | "
                         f"{'yes' if e['systemic'] else ''} | {e['count']:,} | {e['description']} |")
        with open(folder / "defects.md", "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
