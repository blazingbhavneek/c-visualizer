from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable

from value_flow.handles import strip_outer_parens

RESOLVED = "RESOLVED"
RUNTIME = "RUNTIME"
EXTERNAL = "EXTERNAL"
UNRESOLVED = "UNRESOLVED"
NO_TARGET = "NO_TARGET"

_NUMBER = re.compile(
    r"^[+-]?(?:0[xX][0-9a-fA-F]+|0[bB][01]+|0[0-7]+|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)[uUlLfF]*$"
)
_STRING_OR_CHAR = re.compile(
    r"^(?:u8|u|U|L)?(?:\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])+')$", re.DOTALL
)


@dataclass(frozen=True, slots=True)
class ResolutionInfo:
    status: str
    value_set_id: str = ""


def _is_literal(value: str) -> bool:
    text = strip_outer_parens(str(value).strip())
    return bool(
        _NUMBER.fullmatch(text)
        or _STRING_OR_CHAR.fullmatch(text)
        or text in {"NULL", "true", "false", "nullptr"}
    )


def _group_key(record: Any) -> tuple[str, int]:
    seed = getattr(record, "seed", None)
    site = getattr(seed, "site", None)
    site_id = str(getattr(site, "site_id", "") or "")
    if not site_id:
        site_id = ":".join(
            (
                str(getattr(site, "file_path", "") or ""),
                str(getattr(site, "line", "") or ""),
                str(getattr(seed, "target_function", "") or ""),
            )
        )
    return site_id, int(getattr(record, "arg_index", 0) or 0)


def _fact_kind(fact: Any) -> str:
    value = str(getattr(fact, "value", "") or "")
    origin = str(getattr(fact, "origin_kind", "") or "")
    if value == "NO TARGET":
        return NO_TARGET
    if origin in {"CONST", "MACRO", "CONST_TABLE", "BOUNDED_SET"}:
        return RESOLVED if _is_literal(value) else UNRESOLVED
    if origin == "RUNTIME_DATA":
        return RUNTIME
    if origin in {"EXTERNAL_ENTRY", "EXTERNAL_DATA"}:
        return EXTERNAL
    return UNRESOLVED


def classify_records(records: Iterable[Any]) -> dict[int, ResolutionInfo]:
    """Classify target values after all alternatives for a site are known."""
    materialized = list(records)
    groups: dict[tuple[str, int], list[Any]] = {}
    for record in materialized:
        groups.setdefault(_group_key(record), []).append(record)

    result: dict[int, ResolutionInfo] = {}
    for key, group in groups.items():
        kinds = {_fact_kind(record.fact) for record in group}
        values = {str(record.fact.value) for record in group}
        if kinds == {NO_TARGET}:
            status = NO_TARGET
        elif kinds == {EXTERNAL}:
            status = EXTERNAL
        elif kinds == {RESOLVED}:
            status = RUNTIME if len(values) > 1 else RESOLVED
        elif kinds and kinds <= {RESOLVED, RUNTIME} and RUNTIME in kinds:
            status = RUNTIME
        else:
            # A partial mixture is not a complete runtime set.
            status = UNRESOLVED

        value_set_id = ""
        if status == RUNTIME:
            existing = {
                str((record.fact.metadata or {}).get("set_id") or "")
                for record in group
            } - {""}
            if len(existing) == 1:
                value_set_id = next(iter(existing))
            else:
                digest = hashlib.sha1(
                    f"{key[0]}\0{key[1]}".encode("utf-8", errors="replace")
                ).hexdigest()[:16]
                value_set_id = f"set:{digest}"

        info = ResolutionInfo(status=status, value_set_id=value_set_id)
        for record in group:
            result[id(record)] = info
    return result


def from_discovery_status(status: str) -> str:
    """Populate the additive field for legacy discovery-adapter rows."""
    if status == "EXACT":
        return RESOLVED
    if status == "EXTERNAL":
        return EXTERNAL
    if status == "DYNAMIC":
        return RUNTIME
    if status == "NO_TARGET":
        return NO_TARGET
    return UNRESOLVED
