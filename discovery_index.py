"""Build-index-compatible discovery index adapter (pure, no LLM, no State).

This module turns c-visualizer's parsed call-site inventory plus resolver
evidence into the build-index-shaped discovery artifacts written under
``<results_root>/<process>/index/``:

    index_metadata.json
    discovery_facts.csv            evidence: every target call site + status
    forkproc_callers.json
    forkproc_targets_by_caller.json
    mfs_file_access.json
    mfs_queue_access.json
    mfs_dynamic_addque.json
    graph.json                     build-index domain graph (separate schema
                                   from the visualizer graph.json)

Design rules (see plan.md, section 4):

* the JSON shapes and record identities match build_index.py exactly, so the
  existing read-only comparison tooling can be reused;
* unresolved, ambiguous, external, and out-of-scope discoveries NEVER become
  exact JSON entries -- they stay in discovery_facts.csv with an explicit
  status, so a discovery difference is explainable, not just a count;
* multiple possible concrete values for one site are all preserved (one
  record per value), never collapsed to the last textual assignment;
* all paths are normalised to the shared source root (forward slashes);
* all files are written deterministically and atomically.

The module imports nothing resolver-specific: value-flow ``ResolvedSeed``
records and legacy ``Combined`` answers are converted through small adapters
into ``NormalizedDiscoveryFact`` first, so resolver-specific field names never
leak into the compatible schema.
"""

from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Iterable

from target_spec import (
    LOCK_MAP,
    OPEN_LOCK,
    discovery_args_for,
    lock_arg_for,
    operation_for,
    resource_for,
)
from value_flow.handles import strip_outer_parens
from value_flow.status import classify_records, from_discovery_status

DISCOVERY_SCHEMA_VERSION = 3

# build-index graph lock classification (mirrors build_graph.py exactly:
# copyfile and _D record operations intentionally produce no graph edge)
QUEUE_WRITE_LOCKS = {"ADDQUE"}
QUEUE_READ_LOCKS = {"DELQUE"}
FILE_READ_LOCKS = {"READ", "GETREC", "READREC", "COPYREC_FROM"}
FILE_WRITE_LOCKS = {"WRITE", "FWRITE", "CLEAR", "UPDATEREC", "WRITEREC", "COPYREC_TO"}

# dynamic queue FNO: struct-field / array-element expression (mirrors the
# build-index _MFS_*_DYNAMIC_RE shapes)
_DYNAMIC_QUEUE_RE = re.compile(r"^[A-Za-z_]\w*(?:->|\.)\w+")
_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")
_NUMBER = re.compile(
    r"^[+-]?(?:0[xX][0-9a-fA-F]+|0[bB][01]+|0[0-7]+|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)[uUlLfF]*$"
)

# Evidence CSV columns (plan.md section 4.3)
EVIDENCE_COLUMNS = [
    "target_function",
    "target_site_file",
    "target_site_line",
    "arg_index",
    "target_expression",
    "resolved_value",
    "origin_kind",
    "resolved_by",
    "link_method",
    "operation",
    "source_file",
    "source_line",
    "path_count",
    "resolver",
    "status",
    "reachability",
    "evidence_process",
    "owner_process",
    "owner_kind",
    "metadata",
    # Additive semantic fields. Existing ``status`` remains the exact-index
    # promotion gate for compatibility with downstream index consumers.
    "resolution_status",
    "source_expr",
    "value_set_id",
]

TARGET_SITE_COLUMNS = [
    "target_function",
    "target_site_file",
    "target_site_line",
    "arg_index",
    "target_expression",
    "operation",
    "aux_lock",
    "macro_name",
    "unmapped_args",
    "in_process",
]

# Discovery fact statuses.  EXACT rows may feed the exact JSON indexes; every
# other status is evidence-only.
STATUS_EXACT = "EXACT"
STATUS_UNRESOLVED = "UNRESOLVED"
STATUS_EXTERNAL = "EXTERNAL"
STATUS_DYNAMIC = "DYNAMIC"
STATUS_NO_TARGET = "NO_TARGET"
STATUS_UNREACHABLE = "UNREACHABLE"
STATUS_CYCLE = "CYCLE"
STATUS_ALIAS_INTERNAL = "ALIAS_INTERNAL"

# Reachability dimension, kept separate from value-resolution ``status``.
# Promotion to the exact JSON indexes requires status EXACT, in_process, and a
# root-proven reachability (DIRECT_ROOT or CALLBACK) -- never a cross-process
# or root-failure row.
REACH_DIRECT_ROOT = "DIRECT_ROOT"
REACH_CALLBACK = "CALLBACK"
REACH_CROSS_PROCESS_CALLER = "CROSS_PROCESS_CALLER"
REACH_OUT_OF_PROCESS_SCOPE = "OUT_OF_PROCESS_SCOPE"
REACH_ROOT_PARSE_FAILURE = "ROOT_PARSE_FAILURE"
REACH_NO_PROCESS_ROOT = "NO_PROCESS_ROOT"
REACH_UNREACHABLE_IN_PROCESS = "UNREACHABLE_IN_PROCESS"
REACH_LOCAL_BACKWALK = "LOCAL_BACKWALK"
REACH_UNKNOWN = "UNKNOWN"

# The only reachability values that promote an EXACT row into the exact
# process indexes.
ROOT_PROVEN_REACHABILITIES = frozenset({REACH_DIRECT_ROOT, REACH_CALLBACK})


# --------------------------------------------------------------------- paths


def resolve_source_root(process_root: str | Path, explicit: str | Path | None = None) -> Path:
    """Choose the root all comparable paths are relative to.

    An explicit root always wins.  Otherwise the chukyu layout is detected:
    a process rooted at ``<root>/t-*/src/<process>`` relativises to the chukyu
    root so paths match build-index records (``t-.../src/.../file.c``).  Any
    other layout falls back to the process root itself.
    """
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    process = Path(process_root).expanduser().resolve()
    if (
        process.parent.name == "src"
        and re.fullmatch(r"t-.+", process.parent.parent.name)
    ):
        return process.parent.parent.parent
    return process


def rel_to_source_root(path: str | Path, source_root: Path) -> str:
    """Forward-slash path relative to the source root.

    Files outside the source root (linked material the process pulled in from
    elsewhere) keep their absolute POSIX form; callers gate them out of the
    exact indexes by comparing against the process prefix instead.
    """
    if not path:
        return ""
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return str(path).replace("\\", "/")
    try:
        return resolved.relative_to(source_root).as_posix()
    except ValueError:
        return resolved.as_posix()


def process_relative_prefix(source_root: Path, process_root: Path) -> str:
    """The process root expressed in the same relative form as record paths.

    An empty prefix means "the process covers the whole source root".
    """
    prefix = rel_to_source_root(process_root, source_root).rstrip("/")
    return "" if prefix in ("", ".") else prefix


def is_in_process(path: str, prefix: str) -> bool:
    if not prefix:
        return True
    return path == prefix or path.startswith(prefix + "/")


# ------------------------------------------------------------------- values


def _parse_c_int(text: str) -> int | None:
    """Parse a C integer literal (hex/binary/leading-zero octal/decimal,
    optional sign and u/l/f suffixes) to int, else None."""
    value = text.strip()
    sign = 1
    if value and value[0] in "+-":
        sign = -1 if value[0] == "-" else 1
        value = value[1:]
    value = re.sub(r"[uUlLfF]+$", "", value)
    if not value:
        return None
    try:
        if value.lower().startswith("0x"):
            return sign * int(value, 16)
        if value.lower().startswith("0b"):
            return sign * int(value, 2)
        if len(value) > 1 and value[0] == "0" and all(c in "01234567" for c in value[1:]):
            return sign * int(value, 8)
        return sign * int(value, 10)
    except (ValueError, TypeError):
        return None


def to_decimal(value: str | None) -> str | None:
    """Normalise a numeric literal to the decimal string build-index uses as
    FNO key.  None when the value is not a C integer literal."""
    text = strip_outer_parens(str(value or "").strip())
    if not _NUMBER.fullmatch(text):
        return None
    number = _parse_c_int(text)
    return str(number) if number is not None else None


def package_name(value: str | None) -> str | None:
    """The package name a forkproc argument denotes.

    build-index records the string literal's content (or the macro that
    expands to one); quoted and bare identifiers both denote a package.
    """
    text = str(value or "").strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    text = text.strip()
    if not text or not _IDENTIFIER.fullmatch(text):
        return None
    return text


def is_dynamic_queue_expression(expression: str | None) -> bool:
    """Struct-field / array-element FNO that cannot be resolved statically."""
    text = strip_outer_parens(str(expression or "").strip())
    return bool(_DYNAMIC_QUEUE_RE.match(text) or "[" in text)


def determine_confidence(fno_raw: str) -> str:
    """Confidence level from the raw FNO expression (build_graph-compatible)."""
    if not fno_raw:
        return "STATIC_EXACT"
    if fno_raw.isdigit():
        return "STATIC_EXACT"
    if "+" in fno_raw or (fno_raw.count("-") > 0 and not fno_raw.startswith("-")):
        return "STATIC_EXPANDED"
    return "STATIC_EXACT"


# --------------------------------------------------------------- inventory


@dataclass(frozen=True, slots=True)
class TargetSite:
    """One configured discovery argument of one exact target call in source.

    This is the shared target-call-site inventory: it is built once from the
    parsed trees (identical for both resolvers) and every resolver fact joins
    back to it for the raw expression, operation, and scope.
    """

    target_function: str
    site_file: str  # source-root-relative POSIX path
    site_line: int  # 1-based line of the call expression
    arg_index: int  # 1-based configured argument position
    arg_expression: str  # raw C text of that argument (full call if unmapped)
    operation: str  # canonical operation for this arg (OPEN_LOCK for opens)
    aux_lock: str = ""  # open family: raw text of the lock argument
    macro_name: str | None = None  # set when the call goes through a rename macro
    unmapped_args: bool = False  # macro may shift positions; expression unreliable
    in_process: bool = True  # site file lives under the selected process root


def _iter_call_expressions(root: Any, source: bytes) -> Iterable[tuple[str, Any, Any, int, int]]:
    """Yield (function_name, arguments_node, line, start_byte) per call."""
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "call_expression":
            function = node.child_by_field_name("function")
            if function is not None:
                name = source[function.start_byte : function.end_byte].decode(
                    "latin-1", errors="replace"
                )
                yield (
                    name,
                    node.child_by_field_name("arguments"),
                    node.start_point.row + 1,
                    node.start_byte,
                )
        stack.extend(reversed(node.children))


def _macro_expands_to(
    macro_name: str, target_name: str, macros: dict[str, tuple[str, str, str]]
) -> bool:
    macro = macros.get(macro_name)
    if not macro:
        return False
    replacement, _file, _signature = macro
    body = strip_outer_parens(replacement.strip())
    if _IDENTIFIER.fullmatch(body):
        return body == target_name
    return f"{target_name}(" in replacement or f"{target_name} (" in replacement


def _macro_args_for_call(
    macro_name: str,
    target_name: str,
    actual_arguments: list[str],
    macros: dict[str, tuple[str, str, str]],
) -> tuple[list[str], bool]:
    """Map a macro call's argument text onto the expanded function's positions.

    Mirrors ValueFlowResolver._macro_call_arguments: a pure rename keeps the
    call's own positions; argument-injecting expansions are substituted and
    re-parsed; token pasting / stringification / arity mismatch are rejected
    rather than read positionally.  Returns (argument_texts, reliable).
    """
    macro = macros.get(macro_name)
    if not macro:
        return actual_arguments, False
    replacement, _file, signature = macro
    body = strip_outer_parens(replacement.strip())

    if _IDENTIFIER.fullmatch(body) and body == target_name:
        return actual_arguments, True

    if "##" in replacement or re.search(r"#\s*[A-Za-z_]", replacement):
        return actual_arguments, False

    signature_match = re.match(r"\s*[A-Za-z_]\w*\s*\((.*)\)\s*$", signature, re.DOTALL)
    parameters = (
        [part.strip() for part in signature_match.group(1).split(",")]
        if signature_match and signature_match.group(1).strip()
        else []
    )
    if any(part.startswith("...") for part in parameters):
        return actual_arguments, False
    if parameters and len(parameters) != len(actual_arguments):
        return actual_arguments, False

    expanded = replacement
    for parameter, actual in zip(parameters, actual_arguments):
        expanded = re.sub(rf"\b{re.escape(parameter)}\b", actual, expanded)

    from tree_sitter import Language, Parser
    from tree_sitter_custom import language

    expanded_source = expanded.encode("latin-1", errors="replace")
    parser = Parser(Language(language()))
    tree = parser.parse(expanded_source)
    for name, arguments_node, _line, _byte in _iter_call_expressions(tree.root_node, expanded_source):
        if name != target_name or arguments_node is None:
            continue
        return [
            expanded_source[arg.start_byte : arg.end_byte].decode("latin-1", errors="replace")
            for arg in arguments_node.named_children
        ], True
    return actual_arguments, False


def build_target_site_inventory(
    *,
    trees: dict[str, tuple[Any, bytes]],
    functions_identified: dict[str, dict[str, Any]],
    spec: dict[str, Any] | None,
    project_structure: dict[str, str],
    source_root: Path,
    process_root: Path,
    macros: dict[str, tuple[str, str, str]] | None = None,
) -> list[TargetSite]:
    """Exact target call-site inventory, shared by both resolvers.

    Scans every parsed source file (headers skipped, as in
    identify_funs_to_trace) for exact Tree-sitter call expressions of
    configured targets, including calls reached through renaming macros.  No
    value resolution, reachability, or LLM work happens here.
    """
    targets = (spec or {}).get("targets") or functions_identified
    discovery_targets: dict[str, dict[str, Any]] = {}
    for name, config in targets.items():
        if discovery_args_for(config):
            discovery_targets[name] = config

    prefix = process_relative_prefix(source_root, process_root)
    macros = macros or {}
    sites: list[TargetSite] = []

    source_files = [
        (file_name, tree, source)
        for file_name, (tree, source) in sorted(trees.items())
        if not file_name.endswith(".h")
    ]

    def scan_file(item):
        file_name, tree, source = item
        return file_name, list(_iter_call_expressions(tree.root_node, source))

    scanned_files = []
    if source_files:
        with ThreadPoolExecutor(
            max_workers=min(8, len(source_files)),
            thread_name_prefix="discovery-call-scan",
        ) as executor:
            scanned_files = list(executor.map(scan_file, source_files))

    for file_name, call_expressions in scanned_files:
        source = trees[file_name][1]
        file_path = str(project_structure.get(file_name, ""))
        rel_path = rel_to_source_root(file_path or file_name, source_root)
        in_process = is_in_process(rel_path, prefix)

        for func_name, arguments_node, line, _start_byte in call_expressions:
            target_name: str | None = None
            macro_name: str | None = None
            entry = discovery_targets.get(func_name)
            if entry is not None:
                target_name = func_name
            else:
                for candidate in discovery_targets:
                    if func_name in macros and _macro_expands_to(func_name, candidate, macros):
                        target_name, macro_name = candidate, func_name
                        entry = discovery_targets[candidate]
                        break
            if target_name is None or entry is None:
                continue

            args_text: list[str] = []
            if arguments_node is not None:
                args_text = [
                    source[arg.start_byte : arg.end_byte].decode("latin-1", errors="replace")
                    for arg in arguments_node.named_children
                ]

            unmapped = False
            if macro_name is not None:
                args_text, reliable = _macro_args_for_call(
                    macro_name, target_name, args_text, macros
                )
                unmapped = not reliable

            lock_arg = lock_arg_for(entry)
            args_to_report = [int(i) for i in (entry.get("indices") or [])]
            if not args_to_report:
                handle_index = entry.get("handle_index")
                if handle_index:
                    args_to_report = [int(handle_index)]

            if unmapped:
                # Argument positions cannot be trusted; record the raw call so
                # the evidence stays auditable without a heuristic guess.
                call_text = func_name + "(" + ", ".join(args_text) + ")"
                for arg_index in args_to_report:
                    sites.append(
                        TargetSite(
                            target_function=target_name,
                            site_file=rel_path,
                            site_line=line,
                            arg_index=arg_index,
                            arg_expression=call_text,
                            operation=operation_for(entry, arg_index),
                            macro_name=macro_name,
                            unmapped_args=True,
                            in_process=in_process,
                        )
                    )
                continue

            for arg_index in args_to_report:
                expression = (
                    args_text[arg_index - 1].strip()
                    if 0 < arg_index <= len(args_text)
                    else ""
                )
                sites.append(
                    TargetSite(
                        target_function=target_name,
                        site_file=rel_path,
                        site_line=line,
                        arg_index=arg_index,
                        arg_expression=expression,
                        operation=operation_for(entry, arg_index),
                        aux_lock=(
                            args_text[lock_arg - 1].strip()
                            if lock_arg and 0 < lock_arg <= len(args_text)
                            else ""
                        ),
                        macro_name=macro_name,
                        unmapped_args=False,
                        in_process=in_process,
                    )
                )

    sites.sort(
        key=lambda site: (
            site.site_file,
            site.site_line,
            site.target_function,
            site.arg_index,
        )
    )
    return sites


# ------------------------------------------------------------- normalized


@dataclass(frozen=True, slots=True)
class NormalizedDiscoveryFact:
    """One resolved (or not) value for one target argument of one target call.

    The only record shape the exporter accepts.  ``status`` gates the exact
    JSON indexes: only EXACT rows may produce them.  ``source_expr`` is the
    raw expression the resolution stopped at (the open's FNO expression for
    handle-linked record targets) and feeds ``fno_raw`` in the exact indexes.
    """

    resolver: str
    target_function: str
    target_site_file: str
    target_site_line: int
    arg_index: int
    target_expression: str
    resource: str  # mfs_file | mfs_queue | forkproc | none
    value: str  # resolved value text ("" when unresolved)
    operation: str  # canonical build-index lock/operation ("" when unknown)
    source_file: str  # where the value came from (relative; "" when unknown)
    source_line: int
    source_expr: str  # raw expression at the value's source
    origin_kind: str  # CONST/MACRO/... or LLM_ANSWER/SYNTAX_DEFAULT (legacy)
    resolved_by: str  # SYNTAX | LLM
    link_method: str  # VARTRACE / LLM / LEGACY_PROXIMITY / MACRO_EXPANSION / ""
    path_count: int
    status: str
    in_process: bool = True
    # How the target's process roots relate to this site; see the
    # REACH_* constants.  Old rows without the column read as UNKNOWN and are
    # never treated as proven dead code.
    reachability: str = REACH_UNKNOWN
    metadata: dict[str, Any] = field(default_factory=dict)
    resolution_status: str = ""
    value_set_id: str = ""


def _classify_valueflow_fact(
    record: Any,
    resource: str,
    operation: str,
    target_expression: str,
    semantic_status: str,
) -> tuple[str, str]:
    """(status, value) for one value-flow record fact."""
    fact = record.fact
    value = str(fact.value)
    origin = str(fact.origin_kind)

    if resource == "none" or value == "NO TARGET":
        # close/launch-only APIs produce no discovery record; a handle target
        # that could not link an open is unresolved, not "no target".
        if resource == "none":
            return STATUS_NO_TARGET, ""
        return STATUS_UNRESOLVED, ""

    if origin == "LLM_CANDIDATE":
        return STATUS_UNRESOLVED, value

    if semantic_status == "UNRESOLVED":
        return STATUS_UNRESOLVED, value
    if semantic_status == "EXTERNAL":
        return STATUS_EXTERNAL, value
    if semantic_status == "RUNTIME":
        return STATUS_DYNAMIC, value

    if semantic_status == "RESOLVED" and origin in {
        "CONST",
        "MACRO",
        "CONST_TABLE",
        "BOUNDED_SET",
    }:
        if resource in {"mfs_file", "mfs_queue"}:
            if to_decimal(value) is not None and operation:
                return STATUS_EXACT, value
            return STATUS_UNRESOLVED, value
        if resource == "forkproc":
            if package_name(value) is not None:
                return STATUS_EXACT, value
            return STATUS_UNRESOLVED, value

    return STATUS_UNRESOLVED, value


def _make_site_index(sites: list[TargetSite]) -> dict[tuple, list[TargetSite]]:
    index: dict[tuple, list[TargetSite]] = {}
    for site in sites:
        index.setdefault(
            (site.target_function, site.site_file, site.site_line, site.arg_index), []
        ).append(site)
        index.setdefault(
            (site.target_function, site.site_file, site.site_line, -1), []
        ).append(site)
    return index


def _join_site(
    site_index: dict[tuple, list[TargetSite]],
    target: str,
    file: str,
    line: int,
    arg_index: int,
) -> TargetSite | None:
    sites = site_index.get((target, file, line, arg_index))
    if sites:
        return sites[0]
    # Handle queries with an ambiguous (0) arg index still refer to the
    # target's discovery argument at that position.
    by_position = site_index.get((target, file, line, -1))
    if by_position and len(by_position) == 1:
        return by_position[0]
    return None


def classify_reachability(
    resolver_state: dict[str, Any] | None,
    *,
    in_process: bool,
    caller_id: str | None = None,
) -> str:
    """Reachability dimension for one evidence row.

    A missing ``resolver_state`` means incomplete diagnostic data (legacy
    rows, tests without resolver state): the row stays UNKNOWN, which is
    never a proven dead-code result.  Cross-process rows never masquerade as
    in-process unreachable rows; root failures are explicit instead of a
    blanket unreachable claim.
    """
    if not resolver_state:
        return REACH_UNKNOWN
    if not in_process:
        return REACH_OUT_OF_PROCESS_SCOPE
    direct_reachable = set(resolver_state.get("direct_reachable") or ())
    reachable = set(resolver_state.get("reachable") or ())
    if caller_id:
        if caller_id in direct_reachable:
            return REACH_DIRECT_ROOT
        if caller_id in reachable:
            return REACH_CALLBACK
    root_state = str(resolver_state.get("root_state") or "")
    if root_state == REACH_ROOT_PARSE_FAILURE:
        return REACH_ROOT_PARSE_FAILURE
    if root_state == REACH_NO_PROCESS_ROOT:
        return REACH_NO_PROCESS_ROOT
    return REACH_UNREACHABLE_IN_PROCESS


def _unreachable_facts(
    sites: list[TargetSite],
    covered: set[tuple],
    resolver: str,
    targets: dict[str, Any],
    resolver_state: dict[str, Any] | None = None,
) -> list[NormalizedDiscoveryFact]:
    """Inventory sites with no resolver evidence become explicit rows.

    A target call with an unresolved argument is still a discovered target
    call; it must remain visible instead of silently disappearing from the
    output.
    """
    resolver_state = resolver_state or {}
    rows: list[NormalizedDiscoveryFact] = []
    for site in sites:
        key = (site.target_function, site.site_file, site.site_line, site.arg_index)
        if key in covered:
            continue
        rows.append(
            NormalizedDiscoveryFact(
                resolver=resolver,
                target_function=site.target_function,
                target_site_file=site.site_file,
                target_site_line=site.site_line,
                arg_index=site.arg_index,
                target_expression=site.arg_expression,
                resource=resource_for(targets.get(site.target_function) or {}),
                value="",
                operation=site.operation,
                source_file=site.site_file,
                source_line=site.site_line,
                source_expr=site.arg_expression,
                origin_kind="",
                resolved_by="",
                link_method="",
                path_count=0,
                status=STATUS_UNREACHABLE,
                in_process=site.in_process,
                reachability=classify_reachability(
                    resolver_state,
                    in_process=site.in_process,
                ),
                metadata={
                    "source_role": "TARGET_FALLBACK",
                    "trace_complete": False,
                    "termination_reason": "UNREACHABLE_TARGET",
                },
                resolution_status="UNRESOLVED",
            )
        )
    return rows


def _dedupe_facts(facts: list[NormalizedDiscoveryFact]) -> list[NormalizedDiscoveryFact]:
    """Merge identical rows across paths, summing path counts.

    Two different source sites producing the same value are two discoveries
    and stay separate: the site identity is part of the dedupe key.
    """
    merged: dict[tuple, NormalizedDiscoveryFact] = {}
    for fact in facts:
        key = (
            fact.resolver,
            fact.target_function,
            fact.target_site_file,
            fact.target_site_line,
            fact.arg_index,
            fact.resource,
            fact.value,
            fact.operation,
            fact.source_file,
            fact.source_line,
            fact.source_expr,
            fact.origin_kind,
            fact.status,
        )
        existing = merged.get(key)
        if existing is None:
            merged[key] = fact
        else:
            merged[key] = replace(existing, path_count=existing.path_count + fact.path_count)
    return sorted(
        merged.values(),
        key=lambda f: (
            f.target_site_file,
            f.target_site_line,
            f.arg_index,
            f.target_function,
            f.source_file,
            f.source_line,
            f.value,
            f.status,
        ),
    )


def valueflow_records_to_facts(
    records: list[Any],
    sites: list[TargetSite],
    spec: dict[str, Any] | None,
    source_root: Path,
    process_root: Path,
    resolver_state: dict[str, Any] | None = None,
) -> list[NormalizedDiscoveryFact]:
    """Convert value-flow ResolvedSeed records into normalized facts.

    ``records`` are the in-memory resolver results (never the flattened
    legacy CSV).  Facts join back to the shared site inventory for the raw
    target expression and operation.  ``resolver_state`` carries root state
    and reachability sets so every row gets an explicit reachability class.
    """
    resolver_state = resolver_state or {}
    targets = (spec or {}).get("targets") or {}
    site_index = _make_site_index(sites)
    facts: list[NormalizedDiscoveryFact] = []
    covered: set[tuple] = set()
    resolution_info = classify_records(records)

    for record in records:
        site_ref = record.seed.site
        rel_file = rel_to_source_root(site_ref.file_path, source_root)
        target = str(record.seed.target_function)
        entry = targets.get(target) or {}
        resource = resource_for(entry)
        site = _join_site(site_index, target, rel_file, int(site_ref.line), int(record.arg_index))
        if site is not None:
            covered.add((target, rel_file, int(site_ref.line), site.arg_index))
        operation = site.operation if site else ""
        if operation == OPEN_LOCK:
            lock_text = strip_outer_parens((site.aux_lock if site else "").strip())
            operation = LOCK_MAP.get(lock_text, "")

        fact = record.fact
        semantic = resolution_info[id(record)]
        status, value = _classify_valueflow_fact(
            record,
            resource,
            operation,
            site.arg_expression if site else "",
            semantic.status,
        )
        in_process = site.in_process if site is not None else True
        caller_id = getattr(getattr(record, "seed", None), "site", None)
        caller_id = getattr(caller_id, "caller_id", None)
        row_reachability = classify_reachability(
            resolver_state,
            in_process=in_process,
            caller_id=caller_id,
        )
        if str(getattr(record.fact, "link_method", "") or "") == "LOCAL_BACKWALK":
            # Same-function backwalk proves a source-valid value, not root
            # reachability; keep it a separate, explicitly labeled row.
            row_reachability = REACH_LOCAL_BACKWALK
        metadata = dict(getattr(fact, "metadata", {}) or {})
        caller_name = str(getattr(site_ref, "caller_id", "") or "")
        if "]" in caller_name:
            caller_name = caller_name.rsplit("]", 1)[-1]
        metadata["enclosing_function"] = caller_name
        if entry.get("semantic_wrapper"):
            metadata["site_role"] = "WRAPPER_CALL"
            metadata["canonical_target"] = entry.get("canonical_target", "")
            metadata["canonical_operation"] = operation
        facts.append(
            NormalizedDiscoveryFact(
                resolver="valueflow",
                target_function=target,
                target_site_file=rel_file,
                target_site_line=int(site_ref.line),
                arg_index=int(site.arg_index) if site is not None else int(record.arg_index),
                target_expression=site.arg_expression if site else str(fact.source_expr or ""),
                resource=resource,
                value=value,
                operation=operation,
                source_file=rel_to_source_root(fact.source_file, source_root),
                source_line=int(fact.source_line),
                source_expr=str(fact.source_expr or ""),
                origin_kind=str(fact.origin_kind),
                resolved_by=str(fact.resolved_by),
                link_method=str(fact.link_method or ""),
                path_count=int(getattr(record, "path_count", 0) or 0),
                status=status,
                in_process=in_process,
                reachability=row_reachability,
                metadata=metadata,
                resolution_status=semantic.status,
                value_set_id=semantic.value_set_id,
            )
        )

    facts.extend(_unreachable_facts(sites, covered, "valueflow", targets, resolver_state))
    facts = _dedupe_facts(facts)
    return _mark_internal_wrapper_aliases(facts, targets)


def _mark_internal_wrapper_aliases(
    facts: list[NormalizedDiscoveryFact], targets: dict[str, Any]
) -> list[NormalizedDiscoveryFact]:
    """Keep wrapper implementation sites as evidence without double promotion."""
    wrappers = {
        name: str(entry.get("canonical_target") or "")
        for name, entry in targets.items()
        if entry.get("semantic_wrapper") and entry.get("canonical_target")
    }
    covered = {
        (name, canonical, fact.operation, fact.value)
        for fact in facts
        for name, canonical in wrappers.items()
        if fact.target_function == name
        and fact.status == STATUS_EXACT
        and fact.resolution_status == "RESOLVED"
    }
    output: list[NormalizedDiscoveryFact] = []
    for fact in facts:
        enclosing = str((fact.metadata or {}).get("enclosing_function") or "")
        canonical = wrappers.get(enclosing)
        if not canonical or fact.target_function != canonical:
            output.append(fact)
            continue
        metadata = {**(fact.metadata or {}), "site_role": "WRAPPER_IMPLEMENTATION"}
        key = (enclosing, canonical, fact.operation, fact.value)
        if key in covered and fact.status == STATUS_EXACT:
            metadata["alias_internal"] = True
            output.append(replace(fact, status=STATUS_ALIAS_INTERNAL, metadata=metadata))
        else:
            output.append(replace(fact, metadata=metadata))
    return output


def legacy_answers_to_facts(
    answers: dict[str, list[tuple[Any, Any]]],
    sites: list[TargetSite],
    spec: dict[str, Any] | None,
    source_root: Path,
    process_root: Path,
) -> list[NormalizedDiscoveryFact]:
    """Convert in-memory legacy Combined answers into normalized facts.

    Uses the in-memory records (never the flattened legacy CSV): each answer
    carries the per-index resolved values and the exact target call site
    (path + line), which joins to the shared inventory for the raw argument
    expression.  Handle targets (record APIs) received the linked open's FNO
    value(s) as their answer, so those values map to the handle argument.
    """
    targets = (spec or {}).get("targets") or {}
    site_index = _make_site_index(sites)
    facts: list[NormalizedDiscoveryFact] = []
    covered: set[tuple] = set()

    for function, pairs in answers.items():
        entry = targets.get(function) or {}
        resource = resource_for(entry)
        config_indices = [int(i) for i in (entry.get("indices") or [])]
        discovery_args = [int(i) for i in discovery_args_for(entry)]
        handle_target = not config_indices and bool(discovery_args)

        for pair in pairs:
            if not pair:
                continue
            combined = pair[0]
            stats = pair[1] if len(pair) > 1 else None
            if combined is None or not hasattr(combined, "target_name_src"):
                continue  # e.g. the "not a valid function name" placeholder
            src = combined.target_name_src
            if src is None:
                continue
            rel_file = rel_to_source_root(str(src.path), source_root)
            try:
                line = int(str(src.line_number))
            except (TypeError, ValueError):
                continue

            target_number = combined.target_number
            raw_values = list(target_number.ans) if target_number is not None else []
            if not raw_values:
                raw_values = ["UNRESOLVED"]
            no_llm = raw_values == ["NO TARGET"]

            if no_llm:
                resolved_by = "SYNTAX"
            elif isinstance(stats, dict):
                iterations = int(stats.get("Iterations", 0) or 0)
                tokens = stats.get("Tokens") or {}
                total = int(tokens.get("Total_tokens", 0) or 0)
                resolved_by = "SYNTAX" if iterations == 0 and total == 0 else "LLM"
            elif stats is None:
                resolved_by = "LLM"
            else:
                iterations = int(getattr(stats, "Iterations", 0) or 0)
                tokens = getattr(stats, "Tokens", None)
                total = int(getattr(tokens, "Total_tokens", 0) or 0) if tokens else 0
                resolved_by = "SYNTAX" if iterations == 0 and total == 0 else "LLM"

            if handle_target:
                mapping = [(discovery_args[0], v) for v in raw_values]
            else:
                mapping = [
                    (config_indices[pos], value)
                    for pos, value in enumerate(raw_values)
                    if pos < len(config_indices)
                ]

            for arg_index, value in mapping:
                if arg_index not in discovery_args:
                    continue
                site = _join_site(site_index, function, rel_file, line, arg_index)
                covered.add((function, rel_file, line, arg_index))
                operation = site.operation if site else ""
                if operation == OPEN_LOCK:
                    lock_text = strip_outer_parens((site.aux_lock if site else "").strip())
                    operation = LOCK_MAP.get(lock_text, "")

                text = str(value)
                if text in {"", "UNRESOLVED", "NO TARGET", "None"}:
                    status = STATUS_NO_TARGET if no_llm else STATUS_UNRESOLVED
                    resolved = ""
                else:
                    resolved = text
                    if resource in {"mfs_file", "mfs_queue"}:
                        status = (
                            STATUS_EXACT
                            if to_decimal(text) is not None and operation
                            else STATUS_UNRESOLVED
                        )
                    elif resource == "forkproc":
                        status = (
                            STATUS_EXACT if package_name(text) is not None else STATUS_UNRESOLVED
                        )
                    else:
                        status = STATUS_UNRESOLVED

                facts.append(
                    NormalizedDiscoveryFact(
                        resolver="legacy",
                        target_function=function,
                        target_site_file=rel_file,
                        target_site_line=line,
                        arg_index=arg_index,
                        target_expression=site.arg_expression if site else "",
                        resource=resource,
                        value=resolved,
                        operation=operation,
                        source_file="",
                        source_line=0,
                        source_expr="",
                        origin_kind="SYNTAX_DEFAULT" if no_llm else "LLM_ANSWER",
                        resolved_by=resolved_by,
                        link_method="LLM" if handle_target and not no_llm else "",
                        path_count=1,
                        status=status,
                        in_process=site.in_process if site is not None else True,
                        metadata={},
                    )
                )

    facts.extend(_unreachable_facts(sites, covered, "legacy", targets))
    return _dedupe_facts(facts)


# ------------------------------------------------------------------ export


def build_discovery_payloads(
    *,
    process_name: str,
    source_root: Path,
    process_root: Path,
    target_sites: list[TargetSite],
    facts: list[NormalizedDiscoveryFact],
    resolver: str,
    run_id: str | None = None,
    target_registry_version: str = "",
    target_registry_digest: str = "",
    file_function_counts: dict[str, int] | None = None,
    preprocessor_config: dict[str, Any] | None = None,
    root_diagnostics: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Assemble every artifact of one discovery index (pure, no I/O).

    Returns {file_name: text} so the writer and the tests share one code
    path.  Deterministic ordering is applied here; writers only persist.
    """
    prefix = process_relative_prefix(source_root, process_root)

    # Exact promotion needs a proven value, an in-process site, and a
    # root-proven reachability.  Cross-process and root-failure rows stay
    # evidence-only.  LOCAL_BACKWALK rows promote only when the run's root
    # diagnostics show no unresolved root failure.  UNKNOWN (legacy rows and
    # legacy resolver output) keeps its historical promotion behavior so old
    # results read unchanged.
    local_backwalk_allowed = str(
        (root_diagnostics or {}).get("root_state") or ""
    ) == "OK"
    promotable = ROOT_PROVEN_REACHABILITIES | {REACH_UNKNOWN}
    if local_backwalk_allowed:
        promotable = promotable | {REACH_LOCAL_BACKWALK}
    exact = [
        f
        for f in facts
        if f.status == STATUS_EXACT and f.in_process and f.reachability in promotable
    ]
    dynamic = [f for f in facts if f.status == STATUS_DYNAMIC and f.in_process]

    target_site_rows = [
        {
            "target_function": site.target_function,
            "target_site_file": site.site_file,
            "target_site_line": site.site_line,
            "arg_index": site.arg_index,
            "target_expression": site.arg_expression,
            "operation": site.operation,
            "aux_lock": site.aux_lock,
            "macro_name": site.macro_name or "",
            "unmapped_args": site.unmapped_args,
            "in_process": site.in_process,
        }
        for site in sorted(
            target_sites,
            key=lambda item: (
                item.site_file,
                item.site_line,
                item.arg_index,
                item.target_function,
            ),
        )
    ]

    # --- forkproc ----------------------------------------------------------
    forkproc_callers: dict[str, set[str]] = {}
    forkproc_targets: dict[str, set[tuple[int, str]]] = {}
    for fact in exact:
        if fact.resource != "forkproc":
            continue
        pkg = package_name(fact.value)
        if pkg is None:
            continue
        forkproc_callers.setdefault(pkg, set()).add(fact.target_site_file)
        forkproc_targets.setdefault(fact.target_site_file, set()).add(
            (int(fact.target_site_line), pkg)
        )
    forkproc_callers_json = {
        pkg: sorted(callers) for pkg, callers in sorted(forkproc_callers.items())
    }
    forkproc_targets_json = {
        caller: [{"line": line, "target": target} for line, target in sorted(entries)]
        for caller, entries in sorted(forkproc_targets.items())
    }

    # --- mfs file / queue ----------------------------------------------------
    def _access_index(resource: str) -> dict[str, list[dict]]:
        index: dict[str, dict[tuple, dict]] = {}
        for fact in exact:
            if fact.resource != resource:
                continue
            fno = to_decimal(fact.value)
            if fno is None or not fact.operation:
                continue
            fno_raw = fact.source_expr.strip() if fact.source_expr else fact.target_expression.strip()
            key = (
                fact.target_site_file,
                int(fact.target_site_line),
                fact.operation,
                fno_raw,
            )
            per_fno = index.setdefault(fno, {})
            per_fno[key] = {
                "file": fact.target_site_file,
                "line": int(fact.target_site_line),
                "lock": fact.operation,
                "fno_raw": fno_raw,
            }
        return {
            fno: [per_fno[k] for k in sorted(per_fno)]
            for fno, per_fno in sorted(index.items(), key=lambda item: _fno_sort_key(item[0]))
        }

    mfs_file_access = _access_index("mfs_file")
    mfs_queue_access = _access_index("mfs_queue")

    # --- dynamic addque hints ------------------------------------------------
    dynamic_index: dict[str, dict[tuple, dict]] = {}
    for fact in dynamic:
        if fact.resource != "mfs_queue":
            continue
        per_file = dynamic_index.setdefault(fact.target_site_file, {})
        per_file[
            (int(fact.target_site_line), fact.target_expression, fact.operation)
        ] = {
            "line": int(fact.target_site_line),
            "expr": fact.target_expression,
            "lock": fact.operation,
        }
    mfs_dynamic_addque = {
        caller: [per_file[k] for k in sorted(per_file)]
        for caller, per_file in sorted(dynamic_index.items())
    }

    # --- evidence CSV ---------------------------------------------------------
    evidence_rows = [
        {
            "target_function": f.target_function,
            "target_site_file": f.target_site_file,
            "target_site_line": f.target_site_line,
            "arg_index": f.arg_index,
            "target_expression": f.target_expression,
            "resolved_value": f.value,
            "origin_kind": f.origin_kind,
            "resolved_by": f.resolved_by,
            "link_method": f.link_method,
            "operation": f.operation,
            "source_file": f.source_file,
            "source_line": f.source_line,
            "path_count": f.path_count,
            "resolver": f.resolver,
            "status": f.status,
            "reachability": f.reachability,
            "evidence_process": process_name,
            "owner_process": "",
            "owner_kind": "",
            "metadata": json.dumps(f.metadata or {}, ensure_ascii=False, sort_keys=True),
            "resolution_status": (
                f.resolution_status or from_discovery_status(f.status)
            ),
            "source_expr": f.source_expr,
            "value_set_id": (
                f.value_set_id or str((f.metadata or {}).get("set_id") or "")
            ),
        }
        for f in facts
    ]

    # --- graph ----------------------------------------------------------------
    graph = _build_domain_graph(
        process_name=process_name,
        prefix=prefix,
        run_id=run_id or "",
        exact=exact,
        dynamic=dynamic,
        file_function_counts=file_function_counts,
    )

    # --- metadata ---------------------------------------------------------------
    status_counts: dict[str, int] = {}
    resolution_status_counts: dict[str, int] = {}
    reachability_counts: dict[str, int] = {}
    for fact in facts:
        status_counts[fact.status] = status_counts.get(fact.status, 0) + 1
        resolution_status = (
            fact.resolution_status or from_discovery_status(fact.status)
        )
        resolution_status_counts[resolution_status] = (
            resolution_status_counts.get(resolution_status, 0) + 1
        )
        reachability_counts[fact.reachability] = (
            reachability_counts.get(fact.reachability, 0) + 1
        )
    inventory_keys = {
        (site.target_function, site.site_file, site.site_line, site.arg_index)
        for site in target_sites
    }
    fact_keys = {
        (
            fact.target_function,
            fact.target_site_file,
            fact.target_site_line,
            fact.arg_index,
        )
        for fact in facts
    }
    inventory_sites_without_facts = len(inventory_keys - fact_keys)
    facts_without_inventory_site = len(fact_keys - inventory_keys)
    diagnostics: list[str] = []
    if target_sites and not facts:
        diagnostics.append(
            "Configured target sites were found, but resolver produced zero facts."
        )

    metadata = {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "pipeline": "c-visualizer",
        "resolver": resolver,
        "process_name": process_name,
        "process_root": str(process_root),
        "source_root": str(source_root),
        "source_scope": "per-process",
        "target_registry": {
            "version": target_registry_version,
            "digest": target_registry_digest,
        },
        "preprocessor": preprocessor_config or {},
        "root_diagnostics": root_diagnostics or {},
        "run_id": run_id or "",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "target_sites": len(target_sites),
            "target_sites_in_process": sum(1 for s in target_sites if s.in_process),
            "facts": len(facts),
            "inventory_sites_without_facts": inventory_sites_without_facts,
            "facts_without_inventory_site": facts_without_inventory_site,
            "evidence_statuses": dict(sorted(status_counts.items())),
            "resolution_statuses": dict(sorted(resolution_status_counts.items())),
            "reachability": dict(sorted(reachability_counts.items())),
            "forkproc_callers": len(forkproc_callers_json),
            "mfs_file_access_entries": sum(len(v) for v in mfs_file_access.values()),
            "mfs_queue_access_entries": sum(len(v) for v in mfs_queue_access.values()),
            "mfs_dynamic_addque_entries": sum(len(v) for v in mfs_dynamic_addque.values()),
        },
        "notes": [
            "MFS_FILE/MFS_QUEUE graph nodes are derived from accessed FNOs only; "
            "teigi mfs_file_defs are not available inside c-visualizer.",
            "Records for call sites outside the process root are evidence-only "
            "(out-of-scope); they never enter the exact JSON indexes.",
        ],
        "diagnostics": diagnostics,
    }

    return {
        "index_metadata.json": json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        "target_sites.csv": _csv_text(TARGET_SITE_COLUMNS, target_site_rows),
        "discovery_facts.csv": _csv_text(EVIDENCE_COLUMNS, evidence_rows),
        "forkproc_callers.json": _compact_json(forkproc_callers_json),
        "forkproc_targets_by_caller.json": _compact_json(forkproc_targets_json),
        "mfs_file_access.json": _compact_json(mfs_file_access),
        "mfs_queue_access.json": _compact_json(mfs_queue_access),
        "mfs_dynamic_addque.json": _compact_json(mfs_dynamic_addque),
        "graph.json": _compact_json(graph),
    }


def _fno_sort_key(fno: str) -> tuple:
    return (0, int(fno)) if fno.isdigit() else (1, fno)


def _compact_json(payload: Any) -> str:
    # build-index writes compact JSON; keep the same form so diffs stay clean.
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _csv_text(fieldnames: list[str], rows: list[dict]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


# ------------------------------------------------------------------- graph


def _build_domain_graph(
    *,
    process_name: str,
    prefix: str,
    run_id: str,
    exact: list[NormalizedDiscoveryFact],
    dynamic: list[NormalizedDiscoveryFact],
    file_function_counts: dict[str, int] | None,
) -> dict[str, Any]:
    """Build the build-index domain graph for one process.

    Node/edge meanings follow build_graph.py exactly (PROCESS, MFS_QUEUE,
    MFS_FILE, SOURCE_FILE nodes; ADDQUE, DELQUE, READ_FILE, WRITE_FILE,
    FORKPROC edges plus DYNAMIC_HINT ADDQUE edges).  Only call sites inside
    the selected process produce edges: the process is the ownership
    boundary, and a library-rooted call is not an independent process target.
    """
    nodes: list[dict] = []
    node_ids: set[str] = set()
    edges: list[dict] = []
    proc_id = f"proc:{process_name}"

    package = ""
    parts = prefix.split("/")
    if len(parts) >= 3 and re.fullmatch(r"t-.+", parts[0]) and parts[1] == "src":
        package = parts[0]

    nodes.append(
        {
            "id": proc_id,
            "type": "PROCESS",
            "name": process_name,
            "package": package,
            "desc": "",
            "src_path": prefix,
        }
    )
    node_ids.add(proc_id)

    def ensure_node(node_id: str, node: dict) -> None:
        if node_id in node_ids:
            return
        node_ids.add(node_id)
        nodes.append(node)

    in_process_exact = [f for f in exact if is_in_process(f.target_site_file, prefix)]

    queue_fnos = sorted(
        {n for n in (to_decimal(f.value) for f in in_process_exact if f.resource == "mfs_queue") if n},
        key=_fno_sort_key,
    )
    file_fnos = sorted(
        {n for n in (to_decimal(f.value) for f in in_process_exact if f.resource == "mfs_file") if n},
        key=_fno_sort_key,
    )

    pkg_counts: dict[str, int] = {}
    for f in in_process_exact:
        if "/" in f.target_site_file:
            head = f.target_site_file.split("/")[0]
            pkg_counts[head] = pkg_counts.get(head, 0) + 1

    for fno in queue_fnos:
        ensure_node(
            f"queue:{fno}",
            {
                "id": f"queue:{fno}",
                "type": "MFS_QUEUE",
                "fno": int(fno),
                "macros": [],
                "package": max(pkg_counts, key=pkg_counts.get) if pkg_counts else "",
                "collision": False,
            },
        )
    for fno in file_fnos:
        ensure_node(
            f"file:{fno}",
            {
                "id": f"file:{fno}",
                "type": "MFS_FILE",
                "fno": int(fno),
                "name": "",
                "sub_cnt": 0,
                "package": package,
                "comment": "",
                "collision": False,
            },
        )

    for rel_path, count in sorted((file_function_counts or {}).items()):
        if count <= 0 or not is_in_process(rel_path, prefix):
            continue
        ensure_node(
            f"src:{rel_path}",
            {
                "id": f"src:{rel_path}",
                "type": "SOURCE_FILE",
                "path": rel_path,
                "package": rel_path.split("/")[0] if "/" in rel_path else "",
                "func_count": count,
            },
        )

    for fact in in_process_exact:
        if fact.resource == "forkproc":
            pkg_name = package_name(fact.value)
            if pkg_name is None:
                continue
            pkg = fact.target_site_file.split("/")[0] if "/" in fact.target_site_file else ""
            edges.append(
                {
                    "source": proc_id,
                    "target": f"proc:{pkg_name}",
                    "type": "FORKPROC",
                    "source_path": fact.target_site_file,
                    "line": fact.target_site_line,
                    "raw_expr": f"pmf_forkproc_H({pkg_name})",
                    "confidence": "STATIC_EXACT",
                    "package": pkg,
                }
            )
            continue

        fno = to_decimal(fact.value)
        if fno is None:
            continue
        raw = fact.source_expr.strip() if fact.source_expr else fact.target_expression.strip()
        confidence = determine_confidence(raw)
        pkg = fact.target_site_file.split("/")[0] if "/" in fact.target_site_file else ""
        if fact.resource == "mfs_queue":
            queue_id = f"queue:{fno}"
            if fact.operation in QUEUE_WRITE_LOCKS:
                edges.append(
                    {
                        "source": proc_id,
                        "target": queue_id,
                        "type": "ADDQUE",
                        "source_path": fact.target_site_file,
                        "line": fact.target_site_line,
                        "raw_expr": raw,
                        "confidence": confidence,
                        "package": pkg,
                    }
                )
            elif fact.operation in QUEUE_READ_LOCKS:
                edges.append(
                    {
                        "source": queue_id,
                        "target": proc_id,
                        "type": "DELQUE",
                        "source_path": fact.target_site_file,
                        "line": fact.target_site_line,
                        "raw_expr": raw,
                        "confidence": confidence,
                        "package": pkg,
                    }
                )
        elif fact.resource == "mfs_file":
            file_id = f"file:{fno}"
            if fact.operation in FILE_WRITE_LOCKS:
                edges.append(
                    {
                        "source": proc_id,
                        "target": file_id,
                        "type": "WRITE_FILE",
                        "source_path": fact.target_site_file,
                        "line": fact.target_site_line,
                        "raw_expr": raw,
                        "confidence": confidence,
                        "package": pkg,
                    }
                )
            elif fact.operation in FILE_READ_LOCKS:
                edges.append(
                    {
                        "source": proc_id,
                        "target": file_id,
                        "type": "READ_FILE",
                        "source_path": fact.target_site_file,
                        "line": fact.target_site_line,
                        "raw_expr": raw,
                        "confidence": confidence,
                        "package": pkg,
                    }
                )

    for fact in dynamic:
        if fact.resource != "mfs_queue":
            continue
        pkg = fact.target_site_file.split("/")[0] if "/" in fact.target_site_file else ""
        edges.append(
            {
                "source": proc_id,
                "target": "queue:DYNAMIC",
                "type": "ADDQUE",
                "source_path": fact.target_site_file,
                "line": fact.target_site_line,
                "raw_expr": fact.target_expression,
                "confidence": "DYNAMIC_HINT",
                "package": pkg,
            }
        )

    node_type_counts: dict[str, int] = {}
    for node in nodes:
        node_type_counts[node["type"]] = node_type_counts.get(node["type"], 0) + 1
    edge_type_counts: dict[str, int] = {}
    confidence_counts: dict[str, int] = {}
    for edge in edges:
        edge_type_counts[edge["type"]] = edge_type_counts.get(edge["type"], 0) + 1
        confidence_counts[edge["confidence"]] = (
            confidence_counts.get(edge["confidence"], 0) + 1
        )

    return {
        "meta": {
            "producer": "c-visualizer",
            "process": process_name,
            "run_id": run_id,
            "node_types": ["PROCESS", "MFS_QUEUE", "MFS_FILE", "SOURCE_FILE"],
            "edge_types": ["ADDQUE", "DELQUE", "READ_FILE", "WRITE_FILE", "FORKPROC"],
            "confidence_levels": [
                "STATIC_EXACT",
                "STATIC_EXPANDED",
                "DYNAMIC_HINT",
                "COMMENTED_OUT",
                "CONFIG_DEPENDENT",
                "UNRESOLVED",
            ],
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "node_counts": dict(sorted(node_type_counts.items())),
                "edge_counts": dict(sorted(edge_type_counts.items())),
                "confidence_counts": dict(sorted(confidence_counts.items())),
                "packages": sorted({n.get("package", "") for n in nodes if n.get("package")}),
            },
        },
        "nodes": nodes,
        "edges": edges,
    }


# --------------------------------------------------------------- writer


def write_discovery_index(
    *,
    output_dir: str | Path,
    process_name: str,
    source_root: str | Path,
    process_root: str | Path,
    target_registry_version: str,
    target_sites: list[TargetSite],
    facts: list[NormalizedDiscoveryFact],
    resolver: str,
    run_id: str | None = None,
    target_registry_digest: str = "",
    file_function_counts: dict[str, int] | None = None,
    preprocessor_config: dict[str, Any] | None = None,
    root_diagnostics: dict[str, Any] | None = None,
) -> Path:
    """Write the compatible discovery index atomically under ``output_dir``.

    Pure I/O around build_discovery_payloads: no LLM, no State, no visualizer
    graph.  Existing files (visualizer snapshots, legacy CSVs) are never
    touched -- only this directory's own files are replaced.
    """
    source_root = Path(source_root).expanduser().resolve()
    process_root = Path(process_root).expanduser().resolve()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    payloads = build_discovery_payloads(
        process_name=process_name,
        source_root=source_root,
        process_root=process_root,
        target_sites=target_sites,
        facts=facts,
        resolver=resolver,
        run_id=run_id,
        target_registry_version=target_registry_version,
        target_registry_digest=target_registry_digest,
        file_function_counts=file_function_counts,
        preprocessor_config=preprocessor_config,
        root_diagnostics=root_diagnostics,
    )

    for name, text in payloads.items():
        _atomic_write_text(output_dir / name, text)
    return output_dir


def _atomic_write_text(path: Path, text: str) -> None:
    """Temporary file + atomic replace, matching the repo's CSV/JSON writers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(temporary_name, path)
    except Exception:
        try:
            Path(temporary_name).unlink()
        except OSError:
            pass
        raise
