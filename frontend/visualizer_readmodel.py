"""Lazy, cacheable read model over the immutable ``graph.json`` snapshots.

The frontend used to download every complete snapshot (tens of MiB each,
roughly 98 % of it embedded ``source_files``) into the browser.  This module
is the server-side replacement: it derives small, immutable "derived records"
(one per ``(process, run)``) the first time a run is touched, persists them
next to the snapshot, and answers the dynamic API endpoints (catalog,
overview, process plane, function detail, source slice, library plane,
resource detail) from those records alone.

Rules this module enforces:

* Raw ``source_files`` content is never copied into a derived record except
  for the per-function embedded slices, which are bounded and small.
* Derived files are written atomically (temp file + ``os.replace``) and are
  keyed by ``(path, mtime, size, api_version)``; a stale derived file is
  rebuilt instead of served.
* Concurrent requests for the same run take a per-path lock so two clicks
  never parse the same 20 MiB graph twice.
* In-memory caches are bounded by both entry count and bytes (LRU + TTL).
* The immutable ``graph.json`` snapshots are never rewritten or deleted.

The overview/library/direction logic is a faithful port of
``frontend/src/graph/model.js`` so the server-derived ground plane and the
client-rendered process planes agree on producer/consumer arrows and library
boundaries.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Bump this when the derived wire format changes.  Existing plane/overview
# caches used a space-delimited resource key; the browser graph model uses a
# NUL delimiter, so those files must be rebuilt rather than reused.
API_VERSION = 2
SCHEMA_VERSION = 1

# --- direction semantics (mirror of src/graph/model.js) ---------------------

PRODUCER_OPERATIONS = {
    "WRITEF", "SAVEF", "WRITEQ", "SAVEQ", "ENQ",
    "CLEARF", "CLEARQ", "SIGNAL", "FORK", "KILL",
}
CONSUMER_OPERATIONS = {"READF", "READQ", "DEQ", "LOADF"}
API_DIRECTION = {
    "scf_evt_post": "out",
    "scf_var_evt": "out",
    "scf_timer_start": "out",
    "scf_evt_register": "in",
    "scf_tag_open": "both",
    "scf_sem_wait": "both",
    "scf_signal_hook": "in",
}
PROCESS_TARGET_KINDS = {"process", "event", "message"}

# Function metadata carried by the compact plane wire.  Everything else
# (source bodies, summaries) is fetched per function on demand.
PLANE_FUNCTION_KEYS = (
    "id", "kind", "name", "file", "file_name", "start_line", "end_line",
    "is_external", "is_library_api", "is_static", "summary_status",
    "call_count", "resource_interaction_count",
)
# Full per-function record for the detail endpoint (still without source).
DETAIL_FUNCTION_KEYS = PLANE_FUNCTION_KEYS + (
    "source_sha256", "summary", "summary_hint", "summary_error",
)

CATALOG_NAME = "catalog.json"
OVERVIEW_DIR = "overview"
PLANE_NAME = "plane.json"
FUNCTION_INDEX_NAME = "function-index.json"
SOURCE_INDEX_NAME = "source-index.json"

_MAX_DISPLAYED_TRACES = 12


class ApiError(Exception):
    """A request-level error with an HTTP status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


# --- small bounded LRU -------------------------------------------------------

class _BoundedLru:
    """LRU cache bounded by entry count and (approximate) byte size."""

    def __init__(self, max_entries: int, max_bytes: int, ttl_seconds: float) -> None:
        self._data: "OrderedDict[str, tuple[float, int, Any]]" = OrderedDict()
        self._bytes = 0
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._ttl = ttl_seconds

    def get(self, key: str) -> Any | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        stamp, size, value = entry
        if self._ttl and time.monotonic() - stamp > self._ttl:
            self.delete(key)
            return None
        self._data.move_to_end(key)
        return value

    def put(self, key: str, value: Any, size: int) -> None:
        existing = self._data.pop(key, None)
        if existing:
            self._bytes -= existing[1]
        self._data[key] = (time.monotonic(), size, value)
        self._bytes += size
        while len(self._data) > self._max_entries or self._bytes > self._max_bytes:
            if len(self._data) == 0:
                break
            _, evicted = self._data.popitem(last=False)
            self._bytes -= evicted[1]

    def delete(self, key: str) -> None:
        entry = self._data.pop(key, None)
        if entry:
            self._bytes -= entry[1]

    def __len__(self) -> int:
        return len(self._data)


# --- pure helpers (ports of src/graph/model.js) ------------------------------

def interaction_direction(interaction: dict) -> str:
    by_api = API_DIRECTION.get(interaction.get("target_api") or "")
    if by_api:
        return by_api
    operation = interaction.get("operation") or ""
    if operation in PRODUCER_OPERATIONS:
        return "out"
    if operation in CONSUMER_OPERATIONS:
        return "in"
    return "both"


def resource_key(kind: str | None, name: Any) -> str:
    # Keep this byte-for-byte compatible with src/graph/model.js.  Resource
    # ids are joined across snapshots, so a mismatch here silently removes
    # the process-plane -> overview-resource edge.
    return f"{kind}\u0000{name}"


def normalise_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").rstrip("/")


def path_inside(file: Any, root: Any) -> bool:
    child = normalise_path(file)
    parent = normalise_path(root)
    return bool(child and parent and (child == parent or child.startswith(parent + "/")))


def library_component_for_path(root: Any, file: Any) -> str | None:
    if not file or not root:
        return None
    root_norm = normalise_path(root)
    source = normalise_path(file)
    if not source or path_inside(source, root):
        return None
    root_parts = [part for part in root_norm.split("/") if part]
    source_parts = [part for part in source.split("/") if part]
    common = 0
    while (
        common < len(root_parts)
        and common < len(source_parts)
        and root_parts[common] == source_parts[common]
    ):
        common += 1
    for part in source_parts[common:]:
        if re.match(r"^lib", part, re.IGNORECASE):
            return part
    return None


def is_library_function(root: Any, fn: dict | None) -> bool:
    if not fn or fn.get("is_external"):
        return False
    return library_component_for_path(root, fn.get("file")) is not None


def is_library_owned_interaction(root: Any, interaction: dict) -> bool:
    target_file = (interaction.get("source") or {}).get("path")
    origins = interaction.get("value_origins") or []
    if not target_file or not origins or not root:
        return False
    if path_inside(target_file, root):
        return False
    return all(
        origin.get("source_file") and not path_inside(origin["source_file"], root)
        for origin in origins
    )


def _plane_function(fn: dict) -> dict:
    return {key: fn.get(key) for key in PLANE_FUNCTION_KEYS}


def _detail_function(fn: dict) -> dict:
    return {key: fn.get(key) for key in DETAIL_FUNCTION_KEYS}


def _compact_interaction(interaction: dict, resources: dict[str, dict]) -> dict:
    """Plane-wire interaction: enough for ports, cross-plane edges and the
    library-ownership rule, without the argument evidence / full paths."""
    resource_id = interaction.get("resource_id")
    resource = resources.get(resource_id) or {}
    return {
        "id": interaction.get("id"),
        "function_id": interaction.get("function_id"),
        "resource_id": resource_id,
        "resource": {
            "kind": resource.get("kind"),
            "name": resource.get("name"),
            "resolved": resource.get("resolved"),
        },
        "resource_key": resource_key(resource.get("kind"), resource.get("name")),
        "target_api": interaction.get("target_api"),
        "operation": interaction.get("operation"),
        "launch_via": interaction.get("launch_via"),
        "direction": interaction_direction(interaction),
        "argument_binding": interaction.get("argument_binding"),
        "source": interaction.get("source"),
        "value_origins": [
            {"source_file": origin.get("source_file")}
            for origin in (interaction.get("value_origins") or [])
        ],
    }


# --- fast single-pass snapshot scanner ----------------------------------------
#
# Snapshots are ~98 % embedded ``source_files`` content.  A full
# ``json.loads`` of a 20 MiB graph therefore wastes most of its time (and
# memory) on content nobody wants.  Instead a character walk skips string
# *content* with ``str.find`` (C speed) and captures only the structural
# sections: top-level scalars, the ``process`` object, array element counts,
# and raw spans of the small arrays so they can be ``json.loads``-ed later.
# The ``source_files`` span is never parsed wholesale; only its per-file
# metadata fields are walked out of it.

_STRUCTURAL_ARRAYS = ("functions", "calls", "resources", "interactions", "traces")
_SOURCE_FILE_META_KEYS = ("path", "relative_path", "file_name", "language", "sha256")


class _JsonWalker:
    """Single-pass, string-aware JSON value skipper over one text buffer."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.n = len(text)

    def skip_ws(self, pos: int) -> int:
        text, n = self.text, self.n
        while pos < n and text[pos] in " \t\r\n":
            pos += 1
        return pos

    def skip_string(self, pos: int) -> int:
        # text[pos] == '"'
        text, n = self.text, self.n
        end = pos + 1
        while True:
            quote = text.find('"', end)
            if quote < 0:
                raise ValueError("unterminated string")
            backslash = quote - 1
            if backslash >= end and text[backslash] == "\\":
                run = backslash
                while run - 1 >= end and text[run - 1] == "\\":
                    run -= 1
                if (backslash - run + 1) % 2 == 1:
                    end = quote + 1
                    continue
            return quote + 1

    def skip_value(self, pos: int) -> int:
        text, n = self.text, self.n
        c = text[pos]
        if c == '"':
            return self.skip_string(pos)
        if c in "{[":
            depth = 0
            j = pos
            while j < n:
                ch = text[j]
                if ch == '"':
                    j = self.skip_string(j)
                    continue
                if ch in "{[":
                    depth += 1
                elif ch in "}]":
                    depth -= 1
                    if depth == 0:
                        return j + 1
                j += 1
            raise ValueError("unterminated container")
        # literal or number
        j = pos
        while j < n and text[j] not in ",}]\n\t ":
            j += 1
        return j


def scan_graph_sections(text: str) -> dict | None:
    """One pass over a snapshot: scalars, ``process``, counts and array spans."""
    walker = _JsonWalker(text)
    text, n = walker.text, walker.n
    i = walker.skip_ws(0)
    if i >= n or text[i] != "{":
        return None
    i += 1
    scalars: dict[str, Any] = {}
    counts: dict[str, int] = {}
    spans: dict[str, tuple[int, int]] = {}
    process_text: str | None = None
    while True:
        i = walker.skip_ws(i)
        if i >= n or text[i] == "}":
            break
        if text[i] != '"':
            raise ValueError("expected key")
        key_end = walker.skip_string(i)
        key = json.loads(text[i:key_end])
        i = walker.skip_ws(key_end)
        if i >= n or text[i] != ":":
            raise ValueError("expected colon")
        i = walker.skip_ws(i + 1)
        c = text[i]
        if c == "[":
            array_start = i
            if key in _STRUCTURAL_ARRAYS:
                count = 0
                i = walker.skip_ws(i + 1)
                if text[i] != "]":
                    while True:
                        i = walker.skip_value(walker.skip_ws(i))
                        count += 1
                        i = walker.skip_ws(i)
                        if text[i] == ",":
                            i += 1
                            continue
                        if text[i] == "]":
                            i += 1
                            break
                        raise ValueError("expected , or ]")
                else:
                    i += 1
                counts[key] = count
            else:
                i = walker.skip_value(i)
            if key in _STRUCTURAL_ARRAYS or key == "source_files":
                spans[key] = (array_start, i)
        elif c == "{":
            end = walker.skip_value(i)
            if key == "process":
                process_text = text[i:end]
            i = end
        else:
            end = walker.skip_value(i)
            try:
                scalars[key] = json.loads(text[i:end])
            except json.JSONDecodeError:
                scalars[key] = text[i:end].strip()
            i = end
        i = walker.skip_ws(i)
        if i >= n:
            raise ValueError("truncated object")
        if text[i] == ",":
            i += 1
            continue
        if text[i] == "}":
            break
        raise ValueError("expected , or }")
    try:
        process = json.loads(process_text) if process_text else {}
    except json.JSONDecodeError:
        process = {}
    if not isinstance(process, dict):
        process = {}
    schema_version = scalars.get("schema_version")
    return {
        "schema_version": schema_version if isinstance(schema_version, int) else None,
        "generated_at": scalars.get("generated_at"),
        "run_id": scalars.get("run_id"),
        "process_name": process.get("name"),
        "process": process,
        "counts": {key: counts.get(key, 0) for key in _STRUCTURAL_ARRAYS},
        "spans": spans,
    }


def scan_graph_meta(text: str) -> dict | None:
    """Catalog metadata only: scalars, process name and array counts."""
    data = scan_graph_sections(text)
    if data is None:
        return None
    counts = data["counts"]
    return {
        "schema_version": data["schema_version"],
        "generated_at": data["generated_at"],
        "run_id": data["run_id"],
        "process_name": data["process_name"],
        "process": data["process"],
        "function_count": counts["functions"],
        "resource_count": counts["resources"],
        "interaction_count": counts["interactions"],
    }


def _load_span(sections: dict, text: str, name: str) -> list:
    span = sections["spans"].get(name)
    if not span:
        return []
    value = json.loads(text[span[0]:span[1]])
    return value if isinstance(value, list) else []


def _source_file_meta(sections: dict, text: str) -> list[dict]:
    """Per-file metadata from the ``source_files`` array, content untouched."""
    span = sections["spans"].get("source_files")
    if not span:
        return []
    walker = _JsonWalker(text)
    text, n = walker.text, walker.n
    i = walker.skip_ws(span[0] + 1)
    items: list[dict] = []
    if i >= n or text[i] == "]":
        return items
    while i < n and text[i] != "]":
        i = walker.skip_ws(i)
        if text[i] != "{":
            i = walker.skip_value(i)
            continue
        item: dict[str, Any] = {}
        i = walker.skip_ws(i + 1)
        while i < n and text[i] != "}":
            i = walker.skip_ws(i)
            if text[i] == ",":
                i += 1
                continue
            if text[i] != '"':
                raise ValueError("expected key in source_files item")
            key_end = walker.skip_string(i)
            key = json.loads(text[i:key_end])
            i = walker.skip_ws(key_end)
            if i >= n or text[i] != ":":
                raise ValueError("expected colon")
            i = walker.skip_ws(i + 1)
            value_start = i
            i = walker.skip_value(i)
            if key in _SOURCE_FILE_META_KEYS:
                try:
                    item[key] = json.loads(text[value_start:i])
                except json.JSONDecodeError:
                    item[key] = text[value_start:i].strip()
            i = walker.skip_ws(i)
            if i < n and text[i] == ",":
                i += 1
        i += 1
        items.append(item)
        i = walker.skip_ws(i)
        if i < n and text[i] == ",":
            i += 1
    return items


def extract_run_data(text: str) -> dict:
    """Compact structural record from one snapshot, without bulk source files."""
    sections = scan_graph_sections(text)
    if sections is None:
        raise ValueError("not a graph snapshot object")
    embedded: dict[str, dict] = {}
    full_functions: list[dict] = []
    for fn in _load_span(sections, text, "functions"):
        if not isinstance(fn, dict):
            continue
        source = fn.get("source")
        if isinstance(source, str) and source:
            embedded[str(fn.get("id"))] = {
                "file": fn.get("file"),
                "start_line": fn.get("start_line"),
                "end_line": fn.get("end_line"),
                "text": source,
            }
        full_functions.append({key: value for key, value in fn.items() if key != "source"})
    return {
        "schema_version": sections["schema_version"],
        "generated_at": sections["generated_at"],
        "run_id": sections["run_id"],
        "process": sections["process"],
        "full_functions": full_functions,
        "calls": _load_span(sections, text, "calls"),
        "resources": _load_span(sections, text, "resources"),
        "interactions": _load_span(sections, text, "interactions"),
        "traces": _load_span(sections, text, "traces"),
        "embedded_source": embedded,
    }


def source_file_meta(text: str) -> list[dict]:
    """Lazy per-file metadata walk over the ``source_files`` array only."""
    sections = scan_graph_sections(text)
    if sections is None:
        return []
    return _source_file_meta(sections, text)

# --- the read model -----------------------------------------------------------

@dataclass(frozen=True)
class RunRef:
    process_name: str
    run_id: str
    graph_path: Path


class ReadModel:
    """Answers the dynamic API from derived records with bounded caches."""

    def __init__(
        self,
        results_root: Path,
        group_members: set[tuple[str, str]] | None = None,
    ) -> None:
        self.results_root = Path(results_root).expanduser().resolve()
        self.visualizer_root = self.results_root / "visualizer"
        self.group_members = group_members
        self._catalog_lock = threading.Lock()
        self._run_locks: dict[Path, threading.Lock] = {}
        self._run_locks_guard = threading.Lock()
        self._catalog: list[dict] | None = None
        self._catalog_by_key: dict[tuple[str, str], dict] = {}
        self._record_cache = _BoundedLru(max_entries=64, max_bytes=64 * 2**20, ttl_seconds=1800)
        self._overview_cache = _BoundedLru(max_entries=8, max_bytes=16 * 2**20, ttl_seconds=1800)

    # -- catalog ---------------------------------------------------------------

    def _graph_files(self) -> dict[Path, tuple[float, int]]:
        stats: dict[Path, tuple[float, int]] = {}
        if not self.visualizer_root.is_dir():
            return stats
        for path in self.visualizer_root.glob("*/runs/*/graph.json"):
            try:
                stat = path.stat()
            except OSError:
                continue
            stats[path] = (stat.st_mtime, stat.st_size)
        return stats

    def _catalog_cache_path(self) -> Path:
        return self.visualizer_root / CATALOG_NAME

    def _persist_json(self, path: Path, payload: Any) -> None:
        """Atomically write a derived file; ignore read-only result trees."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}-{threading.get_ident()}")
            temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(temp, path)
        except OSError:
            # Read-only snapshot tree: the in-memory cache still works.
            pass

    @staticmethod
    def _read_json(path: Path) -> Any | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def catalog(self) -> list[dict]:
        if self._catalog is not None:
            return self._catalog
        with self._catalog_lock:
            if self._catalog is not None:
                return self._catalog
            files = self._graph_files()
            cache_path = self._catalog_cache_path()
            cached = self._read_json(cache_path)
            valid = (
                isinstance(cached, dict)
                and cached.get("api_version") == API_VERSION
                and {
                    str(Path(run["graph_path"])): (run["mtime"], run["size"])
                    for run in cached.get("runs", [])
                }
                == {
                    str(path.relative_to(self.visualizer_root)): stat
                    for path, stat in files.items()
                }
            )
            if valid:
                runs = cached["runs"]
            else:
                runs = []
                for path, stat in sorted(files.items()):
                    try:
                        meta = scan_graph_meta(path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        continue
                    if meta is None:
                        continue
                    run_id = str(meta.get("run_id") or path.parent.name)
                    process_name = str(meta.get("process_name") or path.parents[2].name)
                    runs.append(
                        {
                            "process_name": process_name,
                            "run_id": run_id,
                            "generated_at": meta.get("generated_at"),
                            "schema_version": meta.get("schema_version"),
                            "function_count": meta.get("function_count", 0),
                            "resource_count": meta.get("resource_count", 0),
                            "interaction_count": meta.get("interaction_count", 0),
                            "graph_path": str(path.relative_to(self.visualizer_root)),
                            "mtime": stat[0],
                            "size": stat[1],
                        }
                    )
            runs.sort(
                key=lambda run: (
                    str(run["process_name"]),
                    str(run.get("generated_at") or ""),
                    str(run["run_id"]),
                ),
                reverse=True,
            )
            self._catalog = runs
            self._catalog_by_key = {
                (str(run["process_name"]), str(run["run_id"])): run for run in runs
            }
            if not valid:
                self._persist_json(
                    cache_path,
                    {
                        "api_version": API_VERSION,
                        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "runs": runs,
                    },
                )
            return self._catalog

    def runs(self) -> list[dict]:
        runs = []
        for run in self.catalog():
            member = (run["process_name"], run["run_id"])
            if self.group_members is not None and member not in self.group_members:
                continue
            runs.append(
                {
                    "process_name": run["process_name"],
                    "run_id": run["run_id"],
                    "generated_at": run.get("generated_at"),
                    "schema_version": run.get("schema_version"),
                    "function_count": run["function_count"],
                    "resource_count": run["resource_count"],
                    "interaction_count": run["interaction_count"],
                }
            )
        return runs

    def _lookup_run(self, process_name: str, run_id: str) -> dict:
        if not process_name or not run_id:
            raise ApiError(400, "Both process and run are required.")
        self.catalog()  # ensure the catalog (and key index) is built
        entry = self._catalog_by_key.get((process_name, run_id))
        if entry is None:
            raise ApiError(404, "Graph snapshot not found.")
        if self.group_members is not None and (process_name, run_id) not in self.group_members:
            raise ApiError(400, "Run is not a member of the active process group.")
        return entry

    # -- derived per-run records -------------------------------------------------

    def _lock_for(self, path: Path) -> threading.Lock:
        with self._run_locks_guard:
            lock = self._run_locks.get(path)
            if lock is None:
                lock = threading.Lock()
                self._run_locks[path] = lock
            return lock

    def _derived_dir(self, entry: dict) -> Path:
        return self.visualizer_root / Path(entry["graph_path"]).parent

    def _build_record(self, entry: dict) -> dict:
        graph_path = self.visualizer_root / entry["graph_path"]
        stat = graph_path.stat()
        text = graph_path.read_text(encoding="utf-8")
        try:
            data = extract_run_data(text)
        except (ValueError, json.JSONDecodeError):
            # Irregular JSON the scanner does not tolerate: fall back to a full
            # parse (still only for this one run).
            graph = json.loads(text)
            process = graph.get("process") if isinstance(graph.get("process"), dict) else {}
            embedded = {
                str(fn.get("id")): {
                    "file": fn.get("file"),
                    "start_line": fn.get("start_line"),
                    "end_line": fn.get("end_line"),
                    "text": fn.get("source"),
                }
                for fn in graph.get("functions", [])
                if isinstance(fn, dict) and isinstance(fn.get("source"), str) and fn.get("source")
            }
            data = {
                "schema_version": graph.get("schema_version"),
                "generated_at": graph.get("generated_at"),
                "run_id": graph.get("run_id"),
                "process": process,
                "full_functions": [
                    {key: value for key, value in fn.items() if key != "source"}
                    for fn in graph.get("functions", [])
                    if isinstance(fn, dict)
                ],
                "calls": graph.get("calls", []),
                "resources": graph.get("resources", []),
                "interactions": graph.get("interactions", []),
                "traces": graph.get("traces", []),
                "embedded_source": embedded,
            }

        process = data["process"]
        full_functions = data["full_functions"]
        functions = [_plane_function(fn) for fn in full_functions]
        function_by_id = {str(fn.get("id")): fn for fn in full_functions}
        resources = [resource for resource in data["resources"] if isinstance(resource, dict)]
        resources_by_id = {str(resource.get("id")): resource for resource in resources}
        calls = [call for call in data["calls"] if isinstance(call, dict)]
        interactions = [item for item in data["interactions"] if isinstance(item, dict)]
        traces = [item for item in data["traces"] if isinstance(item, dict)]
        embedded = data["embedded_source"]

        plane = {
            "api_version": API_VERSION,
            "built_from": {"path": str(graph_path), "mtime": stat.st_mtime, "size": stat.st_size},
            "schema_version": data["schema_version"],
            "generated_at": data["generated_at"],
            "run_id": data["run_id"] or entry["run_id"],
            "process": process,
            "functions": full_functions,
            "calls": calls,
            "resources": resources,
            "interactions": [
                _compact_interaction(interaction, resources_by_id) for interaction in interactions
            ],
            "full_interactions": interactions,
            "traces": traces,
        }
        function_index = {
            "api_version": API_VERSION,
            "built_from": plane["built_from"],
            "functions": {
                str(fn.get("id")): {
                    "file": fn.get("file"),
                    "file_name": fn.get("file_name"),
                    "start_line": fn.get("start_line"),
                    "end_line": fn.get("end_line"),
                    "is_external": bool(fn.get("is_external")),
                    "has_embedded_source": str(fn.get("id")) in embedded,
                    "source_sha256": fn.get("source_sha256"),
                }
                for fn in full_functions
            },
            "embedded_source": embedded,
        }

        derived_dir = self._derived_dir(entry)
        self._persist_json(derived_dir / PLANE_NAME, plane)
        self._persist_json(derived_dir / FUNCTION_INDEX_NAME, function_index)

        record = {
            "process_name": entry["process_name"],
            "run_id": entry["run_id"],
            "graph_path": graph_path,
            "stat": stat,
            "schema_version": data["schema_version"],
            "generated_at": data["generated_at"],
            "process": process,
            "functions": functions,
            "function_by_id": function_by_id,
            "calls": calls,
            "resources": resources,
            "resources_by_id": resources_by_id,
            "full_interactions": interactions,
            "traces": traces,
            "embedded_source": embedded,
        }
        self._record_cache.put(
            (entry["process_name"], entry["run_id"]),
            record,
            # Size estimate for the LRU: the record differs from the plane
            # record only by lookup maps of the same objects.
            len(json.dumps(plane, ensure_ascii=False).encode("utf-8")),
        )
        return record

    @staticmethod
    def _fresh(built_from: Any, stat: os.stat_result, graph_path: Path) -> bool:
        return (
            isinstance(built_from, dict)
            and built_from.get("path") == str(graph_path)
            and built_from.get("mtime") == stat.st_mtime
            and built_from.get("size") == stat.st_size
        )

    def run_record(self, process_name: str, run_id: str) -> dict:
        entry = self._lookup_run(process_name, run_id)
        cache_key = (process_name, run_id)
        cached = self._record_cache.get(cache_key)
        if cached is not None:
            return cached
        graph_path = self.visualizer_root / entry["graph_path"]
        lock = self._lock_for(graph_path)
        with lock:
            cached = self._record_cache.get(cache_key)
            if cached is not None:
                return cached
            try:
                stat = graph_path.stat()
            except OSError:
                raise ApiError(404, "Graph snapshot not found.") from None
            if (stat.st_mtime, stat.st_size) != (entry["mtime"], entry["size"]):
                # Snapshot changed on disk; refresh catalog metadata first.
                self.invalidate_catalog()
                entry = self._lookup_run(process_name, run_id)
                graph_path = self.visualizer_root / entry["graph_path"]
                try:
                    stat = graph_path.stat()
                except OSError:
                    raise ApiError(404, "Graph snapshot not found.") from None
            plane = self._read_json(graph_path.parent / PLANE_NAME)
            function_index = self._read_json(graph_path.parent / FUNCTION_INDEX_NAME)
            if (
                isinstance(plane, dict)
                and plane.get("api_version") == API_VERSION
                and self._fresh(plane.get("built_from"), stat, graph_path)
                and isinstance(function_index, dict)
                and function_index.get("api_version") == API_VERSION
                and self._fresh(function_index.get("built_from"), stat, graph_path)
            ):
                record = {
                    "process_name": process_name,
                    "run_id": run_id,
                    "graph_path": graph_path,
                    "stat": stat,
                    "schema_version": plane.get("schema_version"),
                    "generated_at": plane.get("generated_at"),
                    "process": plane.get("process") or {},
                    "functions": [
                        _plane_function(fn) for fn in plane.get("functions", [])
                    ],
                    "function_by_id": {
                        str(fn.get("id")): fn for fn in plane.get("functions", [])
                    },
                    "calls": plane.get("calls", []),
                    "resources": plane.get("resources", []),
                    "resources_by_id": {
                        str(resource.get("id")): resource
                        for resource in plane.get("resources", [])
                    },
                    "full_interactions": plane.get("full_interactions", []),
                    "traces": plane.get("traces", []),
                    "embedded_source": function_index.get("embedded_source", {}),
                }
                self._record_cache.put(
                    cache_key,
                    record,
                    (graph_path.parent / PLANE_NAME).stat().st_size,
                )
                return record
            return self._build_record(entry)

    def invalidate_catalog(self) -> None:
        with self._catalog_lock:
            self._catalog = None
            self._catalog_by_key = {}
        self._record_cache = _BoundedLru(64, 64 * 2**20, 1800)
        self._overview_cache = _BoundedLru(8, 16 * 2**20, 1800)

    # -- selection + overview ---------------------------------------------------

    @staticmethod
    def normalize_selection(selection: Any) -> list[tuple[str, str]]:
        if not isinstance(selection, list) or not selection:
            raise ApiError(400, "A non-empty run selection is required.")
        pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in selection:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ApiError(400, "Selection entries must be [process, run] pairs.")
            process_name, run_id = str(item[0]), str(item[1])
            if not process_name or not run_id:
                raise ApiError(400, "Selection entries must be [process, run] pairs.")
            if (process_name, run_id) in seen:
                continue
            seen.add((process_name, run_id))
            pairs.append((process_name, run_id))
        pairs.sort()
        return pairs

    @staticmethod
    def selection_key(pairs: list[tuple[str, str]]) -> str:
        digest = hashlib.sha256(
            json.dumps([list(pair) for pair in pairs], ensure_ascii=False).encode("utf-8")
        )
        return digest.hexdigest()[:32]

    def _selection_records(
        self, pairs: list[tuple[str, str]]
    ) -> tuple[list[dict], list[dict]]:
        records: list[dict] = []
        unsupported: list[dict] = []
        for process_name, run_id in pairs:
            entry = self._lookup_run(process_name, run_id)
            if entry.get("schema_version") != SCHEMA_VERSION:
                unsupported.append(
                    {
                        "process_name": process_name,
                        "run_id": run_id,
                        "schema_version": entry.get("schema_version"),
                    }
                )
                continue
            records.append(self.run_record(process_name, run_id))
        return records, unsupported

    def _library_groups(self, records: list[dict]) -> dict[str, dict]:
        """Port of buildLibraryIndexes aggregation (functions/calls/interactions)."""
        groups: dict[str, dict] = {}

        def ensure(name: str) -> dict:
            if name not in groups:
                groups[name] = {
                    "name": name,
                    "functions": OrderedDict(),
                    "calls": OrderedDict(),
                    "interactions": OrderedDict(),
                    "resources": OrderedDict(),
                    "entries": set(),
                }
            return groups[name]

        for record in records:
            root = record["process"].get("root")
            for meta in record["functions"]:
                fn = record["function_by_id"].get(str(meta.get("id"))) or meta
                if not is_library_function(root, fn):
                    continue
                component = library_component_for_path(root, fn.get("file"))
                if not component:
                    continue
                ensure(component)["functions"][str(fn.get("id"))] = {
                    **fn,
                    "library_component": component,
                }

        for record in records:
            root = record["process"].get("root")
            for call in record["calls"]:
                source = record["function_by_id"].get(str(call.get("source")))
                target = record["function_by_id"].get(str(call.get("target")))
                source_component = (
                    library_component_for_path(root, source.get("file")) if source else None
                )
                target_component = (
                    library_component_for_path(root, target.get("file")) if target else None
                )
                if source_component and source_component == target_component:
                    ensure(source_component)["calls"][str(call.get("id"))] = call
                elif target_component:
                    ensure(target_component)["entries"].add(str(call.get("target")))

            for interaction in record["full_interactions"]:
                if not is_library_owned_interaction(root, interaction):
                    continue
                component = library_component_for_path(
                    root, (interaction.get("source") or {}).get("path")
                )
                if not component:
                    continue
                group = ensure(component)
                binding = interaction.get("argument_binding") or {}
                key = "\u0000".join(
                    str(value)
                    for value in (
                        interaction.get("function_id"),
                        interaction.get("resource_id"),
                        interaction.get("target_api"),
                        interaction.get("operation"),
                        binding.get("argument_index"),
                        (interaction.get("source") or {}).get("path"),
                        (interaction.get("source") or {}).get("line_number"),
                    )
                )
                if key in group["interactions"]:
                    existing = group["interactions"][key]
                    names = set(existing.get("observed_processes") or [])
                    names.add(record["process_name"])
                    existing["observed_processes"] = sorted(names)
                else:
                    group["interactions"][key] = {
                        **interaction,
                        "id": f"library-interaction:{component}:{len(group['interactions'])}",
                        "library_component": component,
                        "observed_processes": [record["process_name"]],
                    }
                resource_id = interaction.get("resource_id")
                resource = record["resources_by_id"].get(str(resource_id))
                if resource:
                    group["resources"][str(resource_id)] = resource

        return {name: group for name, group in groups.items() if group["functions"]}

    def _library_snapshot(self, component: str, group: dict) -> dict:
        root_id = f"library-root:{component}"
        incoming = {str(call.get("target")) for call in group["calls"].values()}
        entries = group["entries"] or {
            fn_id for fn_id in group["functions"] if fn_id not in incoming
        }
        root = {
            "id": root_id,
            "kind": "library_root",
            "name": f"{component} (library)",
            "file": None,
            "file_name": None,
            "start_line": -1,
            "end_line": -1,
            "is_external": False,
            "is_library_api": False,
            "is_static": False,
            "summary_status": "library",
            "summary": None,
            "is_library_root": True,
        }
        calls = [dict(call) for call in group["calls"].values()]
        for target_id in sorted(entries):
            if target_id not in group["functions"]:
                continue
            calls.append(
                {
                    "id": f"library-entry:{component}:{target_id}",
                    "source": root_id,
                    "target": target_id,
                    "line": None,
                    "kind": "library_entry",
                    "via": None,
                }
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "process": {
                "id": f"library:{component}",
                "kind": "library",
                "name": component,
                "root": None,
                "main_file": None,
                "entry_function_id": root_id,
            },
            "functions": [root, *group["functions"].values()],
            "calls": calls,
            "interactions": list(group["interactions"].values()),
            "resources": list(group["resources"].values()),
            "traces": [],
        }

    def _overview_from_records(
        self, records: list[dict], unsupported: list[dict], key: str, pairs: list[tuple[str, str]]
    ) -> dict:
        process_nodes: list[dict] = []
        resource_nodes: dict[str, dict] = {}
        edges: list[dict] = []
        resource_alias: dict[str, str] = {}
        process_names = {record["process_name"] for record in records}

        records = sorted(records, key=lambda record: record["process_name"])

        for record in records:
            process_name = record["process_name"]
            root = record["process"].get("root")
            internal = [fn for fn in record["functions"] if not is_library_function(root, fn)]
            interactions = [
                interaction
                for interaction in record["full_interactions"]
                if not is_library_owned_interaction(root, interaction)
            ]
            process_nodes.append(
                {
                    "id": f"process:{process_name}",
                    "type": "process",
                    "name": process_name,
                    "processName": process_name,
                    "run_id": record["run_id"],
                    "generated_at": record.get("generated_at"),
                    "functionCount": len(internal),
                    "resourceCount": len(record["resources"]),
                    "interactionCount": len(interactions),
                }
            )

            aggregated: dict[str, dict] = {}
            for interaction in interactions:
                resource = record["resources_by_id"].get(str(interaction.get("resource_id")))
                if not resource:
                    continue
                key_name = resource_key(resource.get("kind"), resource.get("name"))

                alias = None
                if resource.get("kind") in PROCESS_TARGET_KINDS and str(resource.get("name")) in process_names:
                    alias = f"process:{resource.get('name')}"
                if alias == f"process:{process_name}":
                    continue
                if alias:
                    resource_alias[key_name] = alias
                else:
                    if key_name not in resource_nodes:
                        resource_nodes[key_name] = {
                            "id": f"resource:{key_name}",
                            "type": "resource",
                            "key": key_name,
                            "kind": resource.get("kind"),
                            "name": resource.get("name"),
                            "resolved": bool(resource.get("resolved")),
                            "processes": set(),
                        }
                    node = resource_nodes[key_name]
                    node["processes"].add(process_name)
                    if not resource.get("resolved"):
                        node["resolved"] = False

                direction = interaction_direction(interaction)
                edge = aggregated.get(key_name)
                if edge is None:
                    edge = aggregated[key_name] = {
                        "id": f"edge:{process_name}:{key_name}",
                        "processName": process_name,
                        "resourceKey": key_name,
                        "targetId": alias or f"resource:{key_name}",
                        "direction": direction,
                        "count": 0,
                        "operations": set(),
                        "apis": set(),
                    }
                elif edge["direction"] != direction:
                    edge["direction"] = "both"
                edge["count"] += 1
                if interaction.get("operation"):
                    edge["operations"].add(interaction["operation"])
                if interaction.get("target_api"):
                    edge["apis"].add(interaction["target_api"])
            edges.extend(aggregated.values())

        resources = []
        for node in resource_nodes.values():
            node["processes"] = sorted(node["processes"])
            node["shared"] = len(node["processes"]) > 1
            resources.append(node)
        for edge in edges:
            edge["operations"] = sorted(edge["operations"])
            edge["apis"] = sorted(edge["apis"])

        # Library process nodes, aggregated across the selection.
        library_nodes: list[dict] = []
        library_groups = self._library_groups(records)
        for component in sorted(library_groups):
            group = library_groups[component]
            library_nodes.append(
                {
                    "id": f"process:{component}",
                    "type": "library",
                    "name": component,
                    "processName": component,
                    "run_id": None,
                    "generated_at": None,
                    "functionCount": len(group["functions"]) + 1,
                    "resourceCount": len(group["resources"]),
                    "interactionCount": len(group["interactions"]),
                }
            )

        return {
            "api_version": API_VERSION,
            "selection_key": key,
            "selection": [list(pair) for pair in pairs],
            "built_from": {
                f"{record['process_name']}\u0000{record['run_id']}": [
                    record["stat"].st_mtime,
                    record["stat"].st_size,
                ]
                for record in records
            },
            "processes": process_nodes + library_nodes,
            "resources": resources,
            "edges": edges,
            "resource_aliases": resource_alias,
            "unsupported": unsupported,
        }

    def _overview_cache_valid(self, payload: dict, pairs: list[tuple[str, str]]) -> bool:
        if payload.get("selection") != [list(pair) for pair in pairs]:
            return False
        built_from = payload.get("built_from")
        if not isinstance(built_from, dict):
            return False
        self.catalog()
        for pair in pairs:
            entry = self._catalog_by_key.get(pair)
            recorded = built_from.get(f"{pair[0]}\u0000{pair[1]}")
            if entry is None or not isinstance(recorded, list) or recorded != [entry["mtime"], entry["size"]]:
                return False
        return True

    def overview(self, selection: Any) -> dict:
        pairs = self.normalize_selection(selection)
        key = self.selection_key(pairs)
        cached = self._overview_cache.get(key)
        if cached is not None:
            return cached
        cache_path = self.visualizer_root / OVERVIEW_DIR / f"{key}.json"
        from_disk = self._read_json(cache_path)
        if isinstance(from_disk, dict) and from_disk.get("api_version") == API_VERSION and self._overview_cache_valid(from_disk, pairs):
            return self._overview_cache_put(key, from_disk)
        records, unsupported = self._selection_records(pairs)
        payload = self._overview_from_records(records, unsupported, key, pairs)
        self._persist_json(cache_path, payload)
        return self._overview_cache_put(key, payload)

    def _overview_cache_put(self, key: str, payload: dict) -> dict:
        size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        self._overview_cache.put(key, payload, size)
        return payload

    def overview_by_key(self, key: str) -> dict:
        if not key or not re.fullmatch(r"[a-f0-9]{32}", key):
            raise ApiError(400, "Unknown selection key.")
        cached = self._overview_cache.get(key)
        if cached is not None:
            return cached
        from_disk = self._read_json(self.visualizer_root / OVERVIEW_DIR / f"{key}.json")
        if not isinstance(from_disk, dict) or from_disk.get("api_version") != API_VERSION:
            raise ApiError(404, "Overview for this selection is not cached; request it first.")
        return self._overview_cache_put(key, from_disk)

    # -- endpoints ---------------------------------------------------------------

    def process(self, process_name: str, run_id: str) -> dict:
        record = self.run_record(process_name, run_id)
        process = record["process"]
        return {
            "api_version": API_VERSION,
            "process": {
                "name": record["process_name"],
                "run_id": record["run_id"],
                "root": process.get("root"),
                "main_file": process.get("main_file"),
                "entry_function": process.get("entry_function"),
                "entry_function_id": process.get("entry_function_id"),
            },
            "functions": record["functions"],
            "calls": record["calls"],
            "resources": record["resources"],
            "interactions": [
                _compact_interaction(interaction, record["resources_by_id"])
                for interaction in record["full_interactions"]
            ],
        }

    def function_detail(self, process_name: str, run_id: str, function_id: str) -> dict:
        record = self.run_record(process_name, run_id)
        fn = record["function_by_id"].get(function_id)
        if fn is None:
            raise ApiError(404, "Function not found in this run.")
        name = str(fn.get("name") or "")
        outgoing = [call for call in record["calls"] if str(call.get("source")) == function_id]
        incoming = [call for call in record["calls"] if str(call.get("target")) == function_id]

        neighbors: dict[str, dict] = {function_id: fn}
        for call in outgoing + incoming:
            for role in ("source", "target", "via"):
                neighbor_id = call.get(role)
                if neighbor_id and neighbor_id in record["function_by_id"] and neighbor_id not in neighbors:
                    neighbors[neighbor_id] = record["function_by_id"][neighbor_id]

        interactions = [
            interaction
            for interaction in record["full_interactions"]
            if str(interaction.get("function_id")) == function_id
        ]
        resources = {
            str(interaction.get("resource_id")): record["resources_by_id"].get(
                str(interaction.get("resource_id"))
            )
            for interaction in interactions
        }
        resources = {
            resource_id: resource
            for resource_id, resource in resources.items()
            if resource is not None
        }

        matching = [
            trace
            for trace in record["traces"]
            if any(name in str(label) for label in (trace.get("labels") or []))
        ]
        return {
            "api_version": API_VERSION,
            "process_name": process_name,
            "run_id": run_id,
            "function": _detail_function(fn),
            "source_available": bool(record["embedded_source"].get(function_id) or (
                fn.get("file") and (fn.get("start_line") or 0) > 0
            )),
            "outgoing": outgoing,
            "incoming": incoming,
            "neighbors": neighbors,
            "interactions": interactions,
            "resources": resources,
            "traces": matching[:_MAX_DISPLAYED_TRACES],
            "trace_total": len(matching),
        }

    def _numbered_snippet(self, lines: list[str], start: int, end: int) -> str:
        end = min(end, len(lines))
        return "\n".join(f"{number:>5}  {lines[number - 1]}" for number in range(start, end + 1))

    def _source_index(self, record: dict) -> list[dict]:
        """``source-index.json``, materialised lazily on first source request."""
        graph_path: Path = record["graph_path"]
        stat = record["stat"]
        path = graph_path.parent / SOURCE_INDEX_NAME
        from_disk = self._read_json(path)
        if (
            isinstance(from_disk, dict)
            and from_disk.get("api_version") == API_VERSION
            and self._fresh(from_disk.get("built_from"), stat, graph_path)
        ):
            return from_disk.get("files", [])
        lock = self._lock_for(graph_path)
        with lock:
            from_disk = self._read_json(path)
            if (
                isinstance(from_disk, dict)
                and from_disk.get("api_version") == API_VERSION
                and self._fresh(from_disk.get("built_from"), stat, graph_path)
            ):
                return from_disk.get("files", [])
            files = source_file_meta(graph_path.read_text(encoding="utf-8"))
            self._persist_json(
                path,
                {
                    "api_version": API_VERSION,
                    "built_from": {"path": str(graph_path), "mtime": stat.st_mtime, "size": stat.st_size},
                    "files": files,
                },
            )
            return files

    def source(self, process_name: str, run_id: str, function_id: str) -> tuple[dict, int]:
        record = self.run_record(process_name, run_id)
        fn = record["function_by_id"].get(function_id)
        if fn is None:
            raise ApiError(404, "Function not found in this run.")
        self._source_index(record)  # keep the derived layout complete on demand

        embedded = record["embedded_source"].get(function_id)
        if embedded and embedded.get("text"):
            start = max(1, int(fn.get("start_line") or 1))
            source_lines = embedded["text"].splitlines()
            end = start + max(0, len(source_lines) - 1)
            return (
                {
                    "file": fn.get("file"),
                    "start_line": start,
                    "end_line": end,
                    "text": self._numbered_snippet(source_lines, start, end),
                    "embedded": True,
                },
                200,
            )

        process_root = record["process"].get("root")
        source_path = Path(str(fn.get("file") or "")) if fn.get("file") else None
        if not source_path or not source_path.is_file():
            raise ApiError(404, "Source file not available.")
        if process_root:
            try:
                source_path.resolve().relative_to(Path(process_root).resolve())
            except ValueError:
                raise ApiError(403, "Source is outside this process.") from None
        text = source_path.read_text(encoding="latin-1", errors="replace")
        start = max(1, int(fn.get("start_line") or 1))
        end = int(fn.get("end_line") or start)
        lines = text.splitlines()
        if end < start:
            end = min(len(lines), start + 80)
        end = min(end, len(lines))
        return (
            {
                "file": str(source_path),
                "start_line": start,
                "end_line": end,
                "text": self._numbered_snippet(lines, start, end),
                "embedded": False,
            },
            200,
        )

    def library(self, component: str, selection_key: str) -> dict:
        if not component:
            raise ApiError(400, "component is required.")
        overview = self.overview_by_key(selection_key)
        records = [
            self.run_record(process_name, run_id)
            for process_name, run_id in overview["selection"]
        ]
        groups = self._library_groups(records)
        group = groups.get(component)
        if group is None:
            raise ApiError(404, "Library component not found in this selection.")
        return self._library_snapshot(component, group)

    def resource_detail(self, selection_key: str, kind: str, name: str) -> dict:
        if not kind or not name:
            raise ApiError(400, "kind and name are required.")
        overview = self.overview_by_key(selection_key)
        key = resource_key(kind, name)
        node = next(
            (resource for resource in overview["resources"] if resource["key"] == key), None
        )
        alias = overview["resource_aliases"].get(key)
        matching_edges = [edge for edge in overview["edges"] if edge["resourceKey"] == key]
        operation_counts: dict[str, int] = {}
        for edge in matching_edges:
            for operation in edge["operations"]:
                operation_counts[operation] = operation_counts.get(operation, 0) + edge["count"]
        return {
            "api_version": API_VERSION,
            "key": key,
            "kind": kind,
            "name": name,
            "alias": alias,
            "resource": node,
            "edges": matching_edges,
            "operation_counts": operation_counts,
        }
