"""Reusable answers for target calls that live inside library code.

Most of the path explosion comes from the prefix, not the answer.  When a
target API is called from a library folder (``libdio``, ``libapl``, …) every
process that uses that library multiplies out its own routes to reach the same
few call sites, and each route is sent to the model separately even though the
resolved value is identical.

So the library is traced **once, on its own**, rooted at its own functions
instead of at ``main``.  Each resolved answer is stored under the library-side
path that produced it - the *suffix* a process path ends with.  A later process
run that walks into the same suffix reuses the answer and makes no LLM call.

Only answers that the library run could resolve **without a caller** are
stored.  If a value comes from the library function's own parameter, the model
reports ``UNRESOLVED`` there, nothing is cached, and the process run behaves
exactly as it does today.  That is what keeps a cached fact independent of who
calls it.
"""

from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Iterable

FACTS_FILENAME = "library_facts.json"

# Path labels are joined with "->" but a label may itself contain "->" in
# " (macro expansion)-> " / " (accepts callback)-> ", which is always preceded
# by ")". Split only on the separators that are not.
_LABEL_SEPARATOR = re.compile(r"(?<!\))->")
_FIRST_BLOCK = re.compile(r"^\[([^\[\]]*)\]")
_KEY_JOINER = "\x1f"

_SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "results",
    "logs",
    "pickle_data",
}


def split_path_str(path_str: str) -> list[str]:
    """The labels of a stored ``path_str`` back as a list."""
    return [label for label in _LABEL_SEPARATOR.split(path_str or "") if label]


def _entry_label(label: str) -> str:
    """Drop the call line from a path's first node.

    A library run roots at ``[dio_file.c]DioGetPtr[24:56]``; the same function
    inside a process path carries the line it was called from,
    ``[dio_file.c:88]DioGetPtr[24:56]``.  Every node after it is identical in
    both, because those labels only describe library-internal calls.
    """
    match = _FIRST_BLOCK.match(label)
    if not match:
        return label
    block = match.group(1)
    if ":" not in block:
        return label
    return f"[{block.split(':')[0]}]{label[match.end():]}"


def fact_key(labels: Iterable[str]) -> str:
    labels = list(labels)
    if not labels:
        return ""
    return _KEY_JOINER.join([_entry_label(labels[0]), *labels[1:]])


def discover_libraries(root: Path | str, prefix: str = "lib") -> list[Path]:
    """Folders under *root* whose name starts with *prefix* and hold C sources."""
    root = Path(root).expanduser().resolve()
    found: list[Path] = []
    for current, directories, _ in os.walk(root):
        directories[:] = [
            name
            for name in sorted(directories)
            if name not in _SKIP_DIR_NAMES and not name.startswith(".")
        ]
        matched = []
        for name in directories:
            if not name.lower().startswith(prefix.lower()):
                continue
            candidate = Path(current) / name
            if next(candidate.rglob("*.c"), None) is None:
                continue
            found.append(candidate)
            matched.append(name)
        # A library is indexed as one unit; do not descend into it looking for
        # more libraries.
        directories[:] = [name for name in directories if name not in matched]
    return found


class LibraryFactStore:
    """Resolved library answers, keyed by the path suffix that produced them."""

    version = 1

    def __init__(
        self,
        facts: dict[str, dict] | None = None,
        libraries: dict[str, str] | None = None,
    ) -> None:
        self.facts: dict[str, dict] = facts or {}
        # name -> folder. Kept so a later process run can tell which of its own
        # functions are library code, which is what lets the visualizer keep
        # library and process code apart.
        self.libraries: dict[str, str] = libraries or {}
        self.hits = 0

    # ------------------------------------------------------------- load/save
    @classmethod
    def load(cls, path: Path | str) -> "LibraryFactStore":
        path = Path(path)
        if not path.is_file():
            return cls()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        if payload.get("version") != cls.version:
            return cls()
        return cls(payload.get("facts") or {}, payload.get("libraries") or {})

    def save(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(
                    {
                        "version": self.version,
                        "libraries": self.libraries,
                        "facts": self.facts,
                    },
                    stream,
                    ensure_ascii=False,
                    indent=2,
                )
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return path

    # ---------------------------------------------------------------- lookup
    def lookup(self, labels: list[str], api: str) -> dict | None:
        """The shortest cached suffix of *labels* resolving *api*, if any.

        Shortest first on purpose: a shorter suffix means the library resolved
        the value from less context, so it holds for more callers.
        """
        for size in range(2, len(labels) + 1):
            fact = self.facts.get(fact_key(labels[-size:]))
            if fact and fact.get("function_name") == api:
                self.hits += 1
                return fact
        return None

    # ---------------------------------------------------------------- record
    @staticmethod
    def _values(raw: str) -> list[int | str] | None:
        values: list[int | str] = []
        for item in (raw or "").split(","):
            item = item.strip()
            if not item or item == "UNRESOLVED":
                # The library could not resolve it without a caller; a process
                # run has to do the real work.
                return None
            values.append(int(item) if item.lstrip("-").isdigit() else item)
        return values or None

    def add_from_csv(
        self,
        csv_path: Path | str,
        library_name: str | None = None,
        library_root: Path | str | None = None,
    ) -> int:
        """Harvest one library run's CSV into reusable facts."""
        csv_path = Path(csv_path)
        if library_name and library_root:
            self.libraries[library_name] = str(Path(library_root).resolve())
        if not csv_path.is_file():
            return 0
        added = 0
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                api = row.get("function_name") or ""
                values = self._values(row.get("target_number->ans", ""))
                if not api or values is None:
                    continue
                labels = split_path_str(row.get("target_number->path_str", ""))
                if len(labels) < 2:
                    continue
                call_number = row.get("call_number")
                if call_number in {None, "", "NA", "None", "nan"}:
                    call_number = -1
                self.facts[fact_key(labels)] = {
                    "function_name": api,
                    "ans": values,
                    "call_number": call_number,
                    "type": row.get("type") or "NO DATA",
                    "library": library_name or row.get("process_name") or "",
                    "path_str": row.get("target_number->path_str", ""),
                }
                added += 1
        return added
