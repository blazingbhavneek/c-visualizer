"""Versioned target specifications and build-index compatibility validation.

A target spec is a JSON document whose ``targets`` mapping uses the same entry
shape the c-visualizer pipeline has always consumed from
``json_data/mpf_data.json`` (``type``, ``launch``, ``indices``, ``get_upper``,
``dependent_functions``, optional ``handle_index``) plus an optional
comparison-only ``discovery`` block that maps each configured argument to the
build-index operation/lock vocabulary.  The c-visualizer resolvers ignore the
``discovery`` block; only the discovery-index adapter consumes it, so a spec
without the block still runs (with no exact build-index mapping).

The canonical comparison spec for the 39 build-index targets lives in
``target_specs/build_index_targets.json``.  It is a compatibility copy of the
outer repository's registry plus six reviewed wrappers (version 1.2); the
nested repository must stay runnable on its own, so nothing here imports that
Python package.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SPEC_SCHEMA = "c-visualizer/target-spec"
SPEC_SCHEMA_VERSION = 1

# lock macro -> build-index lock vocabulary (mirrors build_index._LOCK_MAP and
# valueflow.merge.LOCK_NAME)
LOCK_MAP = {
    "MPF_MFS_READLOCK": "READ",
    "MPF_MFS_WRITELOCK": "WRITE",
    "MPF_MFS_FWRITELOCK": "FWRITE",
}

# Sentinel operation for open-family FNO arguments: the concrete lock comes
# from the call site's lock argument (see discovery.lock_arg), not from the
# registry default.
OPEN_LOCK = "OPEN_LOCK"

# The authoritative build-index registry plus reviewed semantic wrappers, as
# (name, family) pairs. Family drives the structural
# validation below; the exact argument positions are checked per family.
EXPECTED_TARGETS: dict[str, str] = {
    # opens: FNO at index 2 (_H) / 3 (non _H); lock macro at lock_arg
    "mpf_mfs_openm_H": "open",
    "mpf_mfs_open_H": "open",
    "mpf_mfs_openm": "open",
    "mpf_mfs_open": "open",
    # clear
    "mpf_mfs_clearfile": "clear",
    "mpf_mfs_clearcc": "clear",
    # copy
    "mpf_mfs_copyfile": "copyfile",
    "mpf_mfs_copyfile_H": "copyfile",
    "mpf_mfs_copyrec": "copyrec",
    "mpf_mfs_copyrec_H": "copyrec",
    # record (handle argument 1, linked to the full open family)
    "mpf_mfs_getrec": "record",
    "mpf_mfs_getrec_D": "record",
    "mpf_mfs_getrecm": "record",
    "mpf_mfs_updaterec": "record",
    "mpf_mfs_updaterec_D": "record",
    "mpf_mfs_updaterecm": "record",
    "mpf_mfs_readrec": "record",
    "mpf_mfs_readrecm": "record",
    "mpf_mfs_readrecn": "record",
    "mpf_mfs_writerec": "record",
    "mpf_mfs_writerecm": "record",
    "mpf_mfs_writerecn": "record",
    # queue
    "mpf_mfs_addque_H": "queue",
    "mpf_mfs_addque": "queue",
    "mpf_mfs_delque_H": "queue",
    "mpf_mfs_delque": "queue",
    "Dac_EnqSem": "queue",
    "Dac_EnqSem2": "queue",
    "SimEnqueSem": "queue",
    "MsgEnqSem": "queue",
    "DxiEnqEvent": "queue",
    "DxiEnqEvent2": "queue",
    # forkproc
    "pmf_forkproc_H": "fork",
    "pmf_forkproc_setonsub_H": "fork",
    "pmf_forkprocdup_H": "fork",
    "pmf_forkprocbs_H": "fork",
    "pmf_forkprocbs_setonsub_H": "fork",
    # close (invalidates handle bindings; produces no discovery record)
    "mpf_mfs_close": "close",
    "mpf_mfs_closeall": "close",
}

OPEN_FAMILY = [
    "mpf_mfs_open_H",
    "mpf_mfs_openm_H",
    "mpf_mfs_open",
    "mpf_mfs_openm",
]

CLOSE_FAMILY = ["mpf_mfs_close", "mpf_mfs_closeall"]

# (name, fno_arg, lock_arg) for the open family, from the registry.
OPEN_POSITIONS = {
    "mpf_mfs_openm_H": (2, 4),
    "mpf_mfs_open_H": (2, 5),
    "mpf_mfs_openm": (3, 5),
    "mpf_mfs_open": (3, 6),
}

# (name, source_arg, destination_arg) for the copy family, from the registry.
COPY_POSITIONS = {
    "mpf_mfs_copyfile": (2, 6),
    "mpf_mfs_copyfile_H": (2, 6),
    "mpf_mfs_copyrec": (2, 8),
    "mpf_mfs_copyrec_H": (2, 8),
}

# (name, fno_arg, operation) for the queue family, from the registry.
QUEUE_POSITIONS = {
    "mpf_mfs_addque_H": (1, "ADDQUE"),
    "mpf_mfs_addque": (2, "ADDQUE"),
    "mpf_mfs_delque_H": (1, "DELQUE"),
    "mpf_mfs_delque": (2, "DELQUE"),
    "Dac_EnqSem": (2, "ADDQUE"),
    "Dac_EnqSem2": (2, "ADDQUE"),
    "SimEnqueSem": (3, "ADDQUE"),
    "MsgEnqSem": (2, "ADDQUE"),
    "DxiEnqEvent": (2, "ADDQUE"),
    "DxiEnqEvent2": (2, "ADDQUE"),
}

# Record API -> canonical build-index operation, from the registry.
RECORD_OPERATIONS = {
    "mpf_mfs_getrec": "GETREC",
    "mpf_mfs_getrec_D": "GETREC_D",
    "mpf_mfs_getrecm": "GETREC",
    "mpf_mfs_updaterec": "UPDATEREC",
    "mpf_mfs_updaterec_D": "UPDATEREC_D",
    "mpf_mfs_updaterecm": "UPDATEREC",
    "mpf_mfs_readrec": "READREC",
    "mpf_mfs_readrecm": "READREC",
    "mpf_mfs_readrecn": "READREC",
    "mpf_mfs_writerec": "WRITEREC",
    "mpf_mfs_writerecm": "WRITEREC",
    "mpf_mfs_writerecn": "WRITEREC",
}


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """JSON object hook that fails early on duplicate target names."""
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key in target spec: {key!r}")
        seen.add(key)
    return dict(pairs)


def load_target_spec(path: str | Path) -> dict[str, Any]:
    """Load and structurally parse one target spec file.

    Returns the payload with an added ``digest`` (sha256 over the canonical
    targets mapping) so runs can record exactly which registry they used.
    Raises ValueError on duplicate keys or a missing ``targets`` mapping.
    """
    payload = json.loads(
        Path(path).read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("targets"), dict):
        raise ValueError(f"target spec must be a JSON object with a 'targets' mapping: {path}")
    payload["digest"] = spec_digest(payload)
    return payload


def spec_digest(payload: dict[str, Any]) -> str:
    """Stable sha256 digest of the targets mapping (key-sorted canonical form)."""
    canonical = json.dumps(
        payload.get("targets", {}), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_target_spec(payload: dict[str, Any]) -> list[str]:
    """Validate a spec against the build-index registry contract.

    Returns a list of human-readable problems (empty list = valid).  A target
    file typo must fail early and must never silently reduce the detected
    target set, so callers treat a non-empty list as fatal for comparison
    runs.
    """
    errors: list[str] = []
    targets = payload.get("targets")
    if not isinstance(targets, dict):
        return ["spec has no 'targets' mapping"]

    names = set(targets)
    expected = set(EXPECTED_TARGETS)
    for missing in sorted(expected - names):
        errors.append(f"missing target: {missing}")
    for extra in sorted(names - expected):
        errors.append(f"unexpected target: {extra}")

    for name, family in sorted(EXPECTED_TARGETS.items()):
        entry = targets.get(name)
        if not isinstance(entry, dict):
            continue  # already reported as missing
        label = f"{name}:"

        # indices: positive 1-based integers
        indices = entry.get("indices", [])
        if not isinstance(indices, list) or any(
            not isinstance(i, int) or isinstance(i, bool) or i < 1 for i in indices
        ):
            errors.append(f"{label} indices must be positive 1-based integers: {indices!r}")

        # dependent functions must exist in the same file
        for dependency in entry.get("dependent_functions") or []:
            if dependency not in names:
                errors.append(f"{label} dependent function not in spec: {dependency}")
        for closer in entry.get("close_functions") or []:
            if closer not in names:
                errors.append(f"{label} close function not in spec: {closer}")

        discovery = entry.get("discovery") or {}
        arg_ops = {
            str(k): v for k, v in (discovery.get("arg_operations") or {}).items()
        }

        if family == "open":
            fno_arg, lock_arg = OPEN_POSITIONS[name]
            if indices != [fno_arg]:
                errors.append(f"{label} FNO argument must be [{fno_arg}], got {indices!r}")
            if discovery.get("lock_arg") != lock_arg:
                errors.append(f"{label} lock argument must be {lock_arg}")
            if arg_ops.get(str(fno_arg)) != OPEN_LOCK:
                errors.append(f"{label} FNO argument operation must be {OPEN_LOCK}")
            if entry.get("handle_index") != 1:
                errors.append(f"{label} handle_index must be 1")
        elif family == "clear":
            if indices != [1]:
                errors.append(f"{label} FNO argument must be [1], got {indices!r}")
            if arg_ops.get("1") != "CLEAR":
                errors.append(f"{label} operation must be CLEAR")
        elif family in ("copyfile", "copyrec"):
            source_arg, dest_arg = COPY_POSITIONS[name]
            if sorted(indices) != sorted((source_arg, dest_arg)):
                errors.append(f"{label} arguments must be {sorted((source_arg, dest_arg))}")
            if arg_ops.get(str(source_arg)) != (
                "COPYFILE_FROM" if family == "copyfile" else "COPYREC_FROM"
            ) or arg_ops.get(str(dest_arg)) != (
                "COPYFILE_TO" if family == "copyfile" else "COPYREC_TO"
            ):
                errors.append(f"{label} copy operations must be *_FROM/*_TO")
        elif family == "record":
            if indices:
                errors.append(f"{label} record API carries no FNO argument (handle only)")
            if entry.get("handle_index") != 1:
                errors.append(f"{label} handle_index must be 1")
            if sorted(entry.get("dependent_functions") or []) != sorted(OPEN_FAMILY):
                errors.append(
                    f"{label} dependent_functions must be the full open family {OPEN_FAMILY}"
                )
            if sorted(entry.get("close_functions") or []) != sorted(CLOSE_FAMILY):
                errors.append(f"{label} close_functions must be {CLOSE_FAMILY}")
            if arg_ops.get("1") != RECORD_OPERATIONS[name]:
                errors.append(f"{label} handle operation must be {RECORD_OPERATIONS[name]}")
        elif family == "queue":
            fno_arg, operation = QUEUE_POSITIONS[name]
            if indices != [fno_arg]:
                errors.append(f"{label} FNO argument must be [{fno_arg}], got {indices!r}")
            if arg_ops.get(str(fno_arg)) != operation:
                errors.append(f"{label} operation must be {operation}")
        elif family == "fork":
            if indices != [1]:
                errors.append(f"{label} package argument must be [1], got {indices!r}")
            if arg_ops.get("1") != "FORKPROC":
                errors.append(f"{label} operation must be FORKPROC")
        elif family == "close":
            if indices:
                errors.append(f"{label} close APIs carry no discovery argument")
            if entry.get("handle_index") != 1:
                errors.append(f"{label} handle_index must be 1")

    return errors


def discovery_args_for(entry: dict[str, Any]) -> list[int]:
    """The configured argument positions that produce discovery records.

    Direct FNO/package targets contribute their ``indices``.  Handle targets
    (record APIs) contribute their single handle argument.  Targets without
    discovery metadata (fixture APIs) or close/launch-only targets contribute
    nothing.
    """
    discovery = entry.get("discovery") or {}
    arg_ops = discovery.get("arg_operations") or {}
    if not arg_ops:
        return []
    indices = list(entry.get("indices") or [])
    if not indices:
        handle_index = entry.get("handle_index")
        if handle_index and str(handle_index) in arg_ops:
            return [int(handle_index)]
    return [int(i) for i in indices if str(i) in arg_ops]


def operation_for(entry: dict[str, Any], arg_index: int) -> str:
    """Canonical build-index operation for one configured argument, '' if none."""
    discovery = entry.get("discovery") or {}
    return str((discovery.get("arg_operations") or {}).get(str(arg_index), ""))


def resource_for(entry: dict[str, Any]) -> str:
    """build-index resource family for a target: mfs_file | mfs_queue | forkproc | none."""
    discovery = entry.get("discovery") or {}
    return str(discovery.get("resource", "none"))


def lock_arg_for(entry: dict[str, Any]) -> int | None:
    discovery = entry.get("discovery") or {}
    value = discovery.get("lock_arg")
    return int(value) if value is not None else None
