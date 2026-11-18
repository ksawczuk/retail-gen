"""Lists the files one push run sends, from the landing_staging layout only.

Called by the entry point after the mode is parsed; hands the pusher an ordered list of items.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from pusher.errors import InputError

FORBIDDEN_NAMES = ("answer_key", "out")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.=-]+$")


@dataclass(frozen=True)
class PushItem:
    """One file to send: where it is, which source and entity it belongs to, and its size."""

    local_path: Path
    source: str
    entity: str
    file_name: str
    size: int

    @property
    def relative_name(self):
        """The <source>/<entity>/<file> name used in the log and in the volume."""
        return f"{self.source}/{self.entity}/{self.file_name}"


class FilePlanner:
    """Walks one delivery's folder under the landing root and returns the files to send."""

    def __init__(self, landing_root):
        """Keep the landing root, refusing one that sits inside a forbidden folder."""
        self._root = Path(landing_root)
        # The answer key and the generator's out folder must never be on the path
        if any(part.lower() in FORBIDDEN_NAMES for part in self._root.parts):
            raise InputError("the landing folder must not be inside a forbidden folder")

    def plan(self, mode):
        """Return the sorted items for a mode; raises InputError if the folder is missing or holds no files."""
        # Find the delivery folder
        base = self._root / mode.relative_dir()
        if not base.is_dir():
            raise InputError(f"no such delivery folder: {mode.relative_dir()}")
        root_real = self._root.resolve()
        # Collect every file that follows <source>/<entity>/<file>
        items = []
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            item = self._item_for(path, base, root_real)
            if item is not None:
                items.append(item)
        if not items:
            raise InputError(f"no files to send in {mode.relative_dir()}")
        return items

    def _item_for(self, path, base, root_real):
        """Return the item for one file, or None if it does not follow the layout."""
        parts = path.relative_to(base).parts
        # Skip anything that is not exactly source/entity/file or has an unsafe name
        if len(parts) != 3 or not all(_SAFE_NAME.match(part) for part in parts):
            return None
        # Refuse forbidden names and links that leave the landing root
        if any(part.lower() in FORBIDDEN_NAMES for part in parts):
            raise InputError(f"forbidden name in the landing folder: {parts[0]}/{parts[1]}")
        if root_real not in path.resolve().parents:
            raise InputError(f"a file resolves outside the landing folder: {path.name}")
        return PushItem(path, parts[0], parts[1], parts[2], path.stat().st_size)
