"""The answer key: every defect the generator injects is recorded here with its size."""
import json
from collections import OrderedDict
from pathlib import Path

from .defects import REGISTRY

MAX_KEYS = 5000


class Manifest:
    """Accumulates defect records; the same defect id across many files adds up."""

    def __init__(self):
        self._entries: "OrderedDict[str, dict]" = OrderedDict()
        self.files: dict = {}

    def record(self, defect_id, count, keys=None, **detail):
        """Add `count` affected rows (or files) to a catalogued defect, keeping up to MAX_KEYS
        example keys. `detail` fills the description's placeholders (first record wins)."""
        if defect_id not in REGISTRY:
            raise KeyError(f"defect {defect_id!r} is not declared in retailgen/defects.py")
        d = REGISTRY[defect_id]
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

    def unrecorded(self) -> list:
        """Catalogued defects no emitter recorded: the catalogue and the code have drifted apart."""
        return [i for i in REGISTRY if i not in self._entries]

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
