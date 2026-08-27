#!/usr/bin/env python3
"""Compare indirect target-argument resolution from existing artifacts.

Step 1 is the complement of ``analysis/step0.py``:

* Step 0 handles a literal or a single macro passed directly to the target.
* Step 1 handles variables, helper parameters, handles/FCBs, expressions, and
  other arguments that require value-flow/backwalking.

The script is read-only.  It never runs either analysis pipeline.  It compares
the c-visualizer ``discovery_facts.csv`` with the legacy build-index
``valueflow_proof.csv`` and writes a JSON report, a per-site CSV, and a plain
English Markdown report.

Example::

    .venv/bin/python analysis/step1.py \
      --cvisualizer-index results/csv_results/index \
      --legacy-index ../index \
      --source-root /home/chukyu \
      --output-dir /tmp/cvisualizer-step1
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


FILE_OPERATIONS = {
    "READ",
    "WRITE",
    "FWRITE",
    "CLEAR",
    "GETREC",
    "GETREC_D",
    "READREC",
    "UPDATEREC",
    "UPDATEREC_D",
    "WRITEREC",
    "COPYFILE_FROM",
    "COPYFILE_TO",
    "COPYREC_FROM",
    "COPYREC_TO",
    "OPEN_LOCK",
}
QUEUE_OPERATIONS = {"ADDQUE", "DELQUE"}
RESOURCE_BY_OPERATION = {
    **{operation: "mfs_file" for operation in FILE_OPERATIONS},
    **{operation: "mfs_queue" for operation in QUEUE_OPERATIONS},
    "FORKPROC": "forkproc",
}

INTEGER_LITERAL = re.compile(r"[+-]?\d+")
STRING_LITERAL = re.compile(r'"(?:[^"\\]|\\.)*"')
IDENTIFIER = re.compile(r"[A-Za-z_]\w*")


# These are source-backed notes for the representative examples printed in
# the report.  They deliberately say when a larger c-visualizer set is an
# overapproximation; "more values" is not automatically an improvement.
SOURCE_REVIEW_NOTES: dict[tuple[str, int], str] = {
    (
        "/home/chukyu/t-dif/src/dif000/dif000Main.c",
        428,
    ): (
        "Both results are supported. `fcb` is opened with `DifStatusNo` at "
        "line 417, and the target call at line 428 uses that same handle. "
        "The legacy macro table maps `DifStatusNo` to 2022."
    ),
    (
        "/home/chukyu/t-dif/src/dif000/dif000Main.c",
        637,
    ): (
        "Both results are supported. `fcb` is opened with `DifBackUpNo` at "
        "line 626, and the target call at line 637 uses that handle. "
        "The legacy macro table maps `DifBackUpNo` to 2045."
    ),
    (
        "/home/chukyu/t-dif/src/dif000/dif000Main.c",
        664,
    ): (
        "Both results are supported. After the first handle is closed, the "
        "same `fcb` is reopened with `DifStatusNo` at line 653; line 664 "
        "then reads through it. The 2022 result is source-consistent."
    ),
    (
        "/home/chukyu/t-svm/src/svm000/svm000FileInt.c",
        895,
    ): (
        "The legacy result is the source-backed one. `fcb_kansimng` is opened "
        "with `SvmKansiMngNo` at line 799, and `SvmKansiMngNo` is 2622 in "
        "`/home/chukyu/t-svm/include/svm/SvmFile.h:172`. The c-visualizer "
        "values 2621-2629 are an overapproximation caused by matching other "
        "file numbers used in the same function; they are not nine real "
        "possibilities for this handle."
    ),
    (
        "/home/chukyu/t-svm/src/svm000/svm000FileInt.c",
        906,
    ): (
        "The legacy result is the source-backed one. `fcb_kansilist` is "
        "opened with `SvmKansiListNo` at line 807, and that macro is 2623 "
        "in `/home/chukyu/t-svm/include/svm/SvmFile.h:173`. The c-visualizer "
        "nine-value set is the same handle-matching overapproximation."
    ),
    (
        "/home/chukyu/t-svm/src/svm000/svm000FileInt.c",
        909,
    ): (
        "The legacy result is the source-backed one. `fcb_jkrcls` is opened "
        "with `SvmJKRclsKnrNo` at line 837, and that macro is 2625 in "
        "`/home/chukyu/t-svm/include/svm/SvmFile.h:175`. The c-visualizer "
        "values 2621-2629 are therefore too broad here."
    ),
    (
        "/home/chukyu/t-dyn/src/dyn010/dyn010Main.c",
        195,
    ): (
        "The legacy linkage is better supported. The same `fcb` is opened "
        "with `DynReCtlMainteFNO` at line 181, immediately before this write. "
        "The c-visualizer value 1081 is not supported by that handle-open "
        "path. The legacy table maps the macro to 1077, although this source "
        "tree also contains a newer 3973 file-number table, so the numeric "
        "value must be interpreted with the pipeline's table version."
    ),
    (
        "/home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c",
        158,
    ): (
        "The legacy result is supported for this branch. Lines 146-149 show "
        "that `fcb` is opened with `DynReSchSetTkFNO` before line 158; the "
        "source header identifies that file as 3910. The c-visualizer 3911 "
        "does not match the macro used by this open."
    ),
    (
        "/home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c",
        216,
    ): (
        "Neither single value is a complete answer. At lines 185-191, "
        "`iFnoInd` is selected from `DynAdvCtlStaITkFNO` or "
        "`DynAdvCtlStaIndFNO`, and line 208 opens `fcb_AdvInd` with that "
        "variable. Legacy 3914 captures the old taiko macro-table entry, "
        "while c-visualizer 0 means it did not resolve the variable; the "
        "source requires both conditional possibilities (current header "
        "values are 3983 and 3946)."
    ),
    (
        "/home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c",
        78,
    ): (
        "c-visualizer is right here. `PROC_NAME` is defined as `\"dyn600\"` "
        "at `/home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:33`, so the call "
        "at line 78 has a direct source definition. The legacy index has no "
        "row for this call."
    ),
    (
        "/home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c",
        174,
    ): (
        "c-visualizer is right here for the same reason: `PROC_NAME` is "
        "defined as `\"dyn600\"` at line 33. Legacy missed this direct "
        "macro use entirely."
    ),
    (
        "/home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c",
        222,
    ): (
        "c-visualizer is right here for the same reason: `PROC_NAME` is "
        "defined as `\"dyn600\"` at line 33. Legacy missed this direct "
        "macro use entirely."
    ),
    (
        "/home/chukyu/t-cha/src/cha001/cha001ClrCaseMan.c",
        106,
    ): (
        "The legacy result is source-backed. `sCaseManFcb` is opened with "
        "`ChaCaseManageNo` at line 97, then read at line 106. "
        "`ChaCaseManageNo` is 2836, so c-visualizer missed the deterministic "
        "handle-to-open connection."
    ),
    (
        "/home/chukyu/t-cha/src/cha001/cha001ClrCaseMan.c",
        147,
    ): (
        "The legacy result is source-backed. The same `sCaseManFcb` opened "
        "with `ChaCaseManageNo` at line 97 is written at line 147, so 2836 "
        "is the correct propagated value and c-visualizer missed it."
    ),
    (
        "/home/chukyu/t-cha/src/cha001/cha001Main.c",
        171,
    ): (
        "The legacy result is source-backed. Lines 164-166 open `recman_fcb` "
        "with `ChaRecManageNo`, and line 171 immediately reads through that "
        "handle. `ChaRecManageNo` is 2839; c-visualizer did not propagate "
        "the open into this target call."
    ),
}


def read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def normalize_path(value: Any, source_root: Path | None) -> str:
    text = str(value or "").replace("\\", "/")
    if not text:
        return ""
    path = Path(text)
    if path.is_absolute() and source_root is not None:
        try:
            return path.resolve().relative_to(source_root.resolve()).as_posix()
        except ValueError:
            return path.resolve().as_posix()
    return re.sub(r"^\./+", "", text)


def absolute_path(value: str, source_root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else source_root / value


def resource_for_operation(operation: str) -> str:
    return RESOURCE_BY_OPERATION.get(operation, "")


def direct_literal(expression: str) -> bool:
    expression = expression.strip()
    return bool(
        INTEGER_LITERAL.fullmatch(expression)
        or STRING_LITERAL.fullmatch(expression)
    )


def concrete_value(value: Any, resource: str) -> str | None:
    """Return only a final comparable value, not a symbolic/external answer."""

    text = str(value or "").strip()
    if not text or text in {"None", "null", "UNRESOLVED"}:
        return None
    if resource in {"mfs_file", "mfs_queue"}:
        return text if INTEGER_LITERAL.fullmatch(text) else None
    if resource == "forkproc":
        if len(text) >= 2 and text[0] == text[-1] == '"':
            return text[1:-1]
        # Forkproc targets are normally logical process names.  Do not treat
        # an expression, pointer, or external placeholder as a target value.
        if IDENTIFIER.fullmatch(text) or re.fullmatch(r"[A-Za-z0-9_.-]+", text):
            return text
    return None


class SourceClassifier:
    """Classify the recorded source line enough to remove dead/comment code."""

    def __init__(self, source_root: Path):
        self.source_root = source_root
        self.cache: dict[str, tuple[list[str], list[str], list[bool]] | None] = {}

    def classify(self, relative_path: str, line_number: int) -> str:
        if relative_path in self.cache:
            scanned = self.cache[relative_path]
            if scanned is None:
                return "MISSING_SOURCE"
            _, cleaned, disabled = scanned
            if line_number < 1 or line_number > len(cleaned):
                return "MISSING_SOURCE"
            if disabled[line_number - 1]:
                return "IF0_DISABLED"
            return "COMMENT_OR_BLANK" if not cleaned[line_number - 1] else "ACTIVE_CODE"

        path = absolute_path(relative_path, self.source_root)
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            self.cache[relative_path] = None
            return "MISSING_SOURCE"
        if line_number < 1 or line_number > len(lines):
            return "MISSING_SOURCE"

        in_block_comment = False
        disabled_stack: list[bool] = []
        cleaned: list[str] = []
        disabled: list[bool] = []
        for line in lines:
            output: list[str] = []
            index = 0
            quote: str | None = None
            escaped = False
            while index < len(line):
                char = line[index]
                next_char = line[index + 1] if index + 1 < len(line) else ""
                if in_block_comment:
                    if char == "*" and next_char == "/":
                        in_block_comment = False
                        index += 2
                    else:
                        index += 1
                    continue
                if quote:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == quote:
                        quote = None
                    output.append(char)
                    index += 1
                    continue
                if char in {'"', "'"}:
                    quote = char
                    output.append(char)
                    index += 1
                    continue
                if char == "/" and next_char == "*":
                    in_block_comment = True
                    index += 2
                    continue
                if char == "/" and next_char == "/":
                    break
                output.append(char)
                index += 1

            clean = "".join(output).strip()
            if clean.startswith("#if"):
                expression = clean[3:].strip()
                disabled_stack.append(expression == "0" or expression.startswith("0 "))
            elif clean.startswith("#else") and disabled_stack:
                disabled_stack[-1] = not disabled_stack[-1]
            elif clean.startswith("#elif") and disabled_stack:
                disabled_stack[-1] = False
            elif clean.startswith("#endif") and disabled_stack:
                disabled_stack.pop()
            cleaned.append(clean)
            disabled.append(any(disabled_stack))

        self.cache[relative_path] = (lines, cleaned, disabled)
        if disabled[line_number - 1]:
            return "IF0_DISABLED"
        if not cleaned[line_number - 1]:
            return "COMMENT_OR_BLANK"
        return "ACTIVE_CODE"


class SourceLines:
    def __init__(self, source_root: Path):
        self.source_root = source_root
        self.cache: dict[Path, list[str] | None] = {}

    def line(self, value: Any, line_number: Any) -> str:
        path = absolute_path(normalize_path(value, None), self.source_root)
        if path not in self.cache:
            try:
                self.cache[path] = path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
            except OSError:
                self.cache[path] = None
        lines = self.cache[path]
        number = int_value(line_number)
        if not lines or number < 1 or number > len(lines):
            return ""
        return lines[number - 1]


@dataclass(frozen=True, order=True)
class Site:
    resource: str
    file: str
    line: int
    target_function: str
    arg_index: int
    operation: str

    def as_tuple(self) -> tuple[str, str, int, str, int, str]:
        return (
            self.resource,
            self.file,
            self.line,
            self.target_function,
            self.arg_index,
            self.operation,
        )

    def absolute_file(self, source_root: Path) -> str:
        return str(absolute_path(self.file, source_root))


@dataclass
class CVisualizerSite:
    site: Site
    expressions: set[str] = field(default_factory=set)
    statuses: Counter[str] = field(default_factory=Counter)
    resolved_by: Counter[str] = field(default_factory=Counter)
    link_methods: Counter[str] = field(default_factory=Counter)
    values: set[str] = field(default_factory=set)
    syntax_values: set[str] = field(default_factory=set)
    rows: list[dict[str, str]] = field(default_factory=list)
    directness: str = "UNKNOWN_ARGUMENT"


@dataclass
class LegacySite:
    site: Site
    raw_expressions: set[str] = field(default_factory=set)
    statuses: Counter[str] = field(default_factory=Counter)
    resolved_by: Counter[str] = field(default_factory=Counter)
    link_methods: Counter[str] = field(default_factory=Counter)
    values: set[str] = field(default_factory=set)
    llm_backwalk: bool = False
    rows: list[dict[str, str]] = field(default_factory=list)
    directness: str = "UNKNOWN_ARGUMENT"


def row_directness(
    expression: str,
    macro_names: set[str] | None,
    proof_line: str | None,
) -> str:
    expression = expression.strip()
    if not expression:
        return "UNKNOWN_ARGUMENT"
    if direct_literal(expression):
        return "DIRECT_CONST"
    if IDENTIFIER.fullmatch(expression):
        if macro_names and expression in macro_names:
            return "DIRECT_MACRO"
        if proof_line and re.search(
            rf"#\s*define\s+{re.escape(expression)}(?:\s|\(|$)", proof_line
        ):
            return "DIRECT_MACRO"
        return "INDIRECT"
    return "INDIRECT"


def macro_names(directory: Path) -> set[str]:
    payload = read_json(directory / "mfs_fno_macros.json", {})
    names: set[str] = set()
    if isinstance(payload, dict):
        for values in payload.values():
            if isinstance(values, list):
                names.update(str(value) for value in values)
    return names


def cvisualizer_row_directness(
    row: dict[str, str], source_lines: SourceLines, known_macros: set[str]
) -> str:
    proof_line = source_lines.line(row.get("source_file", ""), row.get("source_line", ""))
    return row_directness(row.get("target_expression", ""), known_macros, proof_line)


def legacy_operation(row: dict[str, str]) -> str | None:
    """Translate legacy operation labels to the c-visualizer labels."""

    function = row.get("target_function", "")
    operation = row.get("operation", "")
    if function.startswith("pmf_forkproc"):
        return "FORKPROC"
    if function in {"mpf_mfs_addque", "mpf_mfs_addque_H"}:
        return "ADDQUE"
    if function in {"mpf_mfs_delque", "mpf_mfs_delque_H"}:
        return "DELQUE"

    if function in {"mpf_mfs_open", "mpf_mfs_open_H", "mpf_mfs_openm", "mpf_mfs_openm_H"}:
        if operation in {"READ", "WRITE", "FWRITE"}:
            return operation
        if operation == "OPENMF":
            return "OPEN_LOCK"
        return None

    if "copyfile" in function:
        return operation if operation in {"COPYFILE_FROM", "COPYFILE_TO"} else None
    if "copyrec" in function:
        return operation if operation in {"COPYREC_FROM", "COPYREC_TO"} else None
    if "clear" in function:
        return "CLEAR" if operation in {"CLEAR", "CLEARF"} else None
    if function.endswith("getrec_D"):
        return "GETREC_D" if operation in {"GETREC", "RECF"} else None
    if "getrec" in function:
        return "GETREC" if operation in {"GETREC", "RECF"} else None
    if function.endswith("updaterec_D"):
        return "UPDATEREC_D" if operation in {"UPDATEREC", "RECF"} else None
    if "updaterec" in function:
        return "UPDATEREC" if operation in {"UPDATEREC", "RECF"} else None
    if "readrec" in function:
        return "READREC" if operation in {"READREC", "RECF"} else None
    if "writerec" in function:
        return "WRITEREC" if operation in {"WRITEREC", "RECF"} else None
    return operation if operation in RESOURCE_BY_OPERATION else None


def make_cvisualizer_site(row: dict[str, str], source_root: Path) -> Site | None:
    operation = row.get("operation", "")
    resource = resource_for_operation(operation)
    if not resource:
        return None
    return Site(
        resource=resource,
        file=normalize_path(row.get("target_site_file", ""), source_root),
        line=int_value(row.get("target_site_line")),
        target_function=row.get("target_function", ""),
        arg_index=int_value(row.get("arg_index")),
        operation=operation,
    )


def make_legacy_site(row: dict[str, str], source_root: Path) -> Site | None:
    operation = legacy_operation(row)
    if not operation:
        return None
    resource = resource_for_operation(operation)
    if not resource:
        return None
    return Site(
        resource=resource,
        file=normalize_path(row.get("target_file", ""), source_root),
        line=int_value(row.get("target_line")),
        target_function=row.get("target_function", ""),
        arg_index=int_value(row.get("argument_index")),
        operation=operation,
    )


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [{str(key): str(value or "") for key, value in row.items()} for row in csv.DictReader(handle)]


def load_cvisualizer(
    directory: Path,
    source_root: Path,
) -> tuple[dict[Site, CVisualizerSite], Counter[str], set[str]]:
    rows = read_csv_rows(directory / "discovery_facts.csv")
    known_macros = macro_names(directory)
    source_lines = SourceLines(source_root)
    grouped: dict[Site, CVisualizerSite] = {}
    skipped = Counter()
    for row in rows:
        site = make_cvisualizer_site(row, source_root)
        if site is None:
            skipped["no_comparable_resource_operation"] += 1
            continue
        item = grouped.setdefault(site, CVisualizerSite(site))
        item.rows.append(row)
        expression = row.get("target_expression", "").strip()
        if expression:
            item.expressions.add(expression)
        item.statuses[row.get("status", "")] += 1
        if row.get("resolved_by"):
            item.resolved_by[row["resolved_by"]] += 1
        if row.get("link_method"):
            item.link_methods[row["link_method"]] += 1
        value = concrete_value(row.get("resolved_value"), site.resource)
        if row.get("status") == "EXACT" and value is not None:
            item.values.add(value)
            if row.get("resolved_by") != "LLM":
                item.syntax_values.add(value)

    # The direct/indirect decision is made per evidence row, not merely from
    # the origin_kind.  &fcb, file_no, and helper variables therefore remain
    # Step 1 even when a macro value was eventually found behind them.
    for item in grouped.values():
        directness = {
            cvisualizer_row_directness(row, source_lines, known_macros)
            for row in item.rows
            if row.get("target_expression", "").strip()
        }
        if not directness:
            item.directness = "UNKNOWN_ARGUMENT"
            skipped["unknown_argument"] += 1
        elif directness <= {"DIRECT_CONST", "DIRECT_MACRO"}:
            item.directness = "DIRECT_CONST_MACRO"
            skipped["direct_const_macro"] += 1
        else:
            item.directness = "INDIRECT"
            skipped["indirect_or_mixed"] += 1
    return grouped, skipped, known_macros


def load_legacy(
    directory: Path,
    source_root: Path,
) -> tuple[dict[Site, LegacySite], Counter[str], set[str]]:
    rows = read_csv_rows(directory / "valueflow_proof.csv")
    known_macros = macro_names(directory)
    grouped: dict[Site, LegacySite] = {}
    skipped = Counter()
    for row in rows:
        site = make_legacy_site(row, source_root)
        if site is None:
            skipped["unsupported_legacy_operation"] += 1
            continue
        item = grouped.setdefault(site, LegacySite(site))
        item.rows.append(row)
        raw = row.get("raw_expression", "").strip()
        if raw:
            item.raw_expressions.add(raw)
        item.statuses[row.get("status", "")] += 1
        if row.get("resolved_by"):
            item.resolved_by[row["resolved_by"]] += 1
        if row.get("link_method"):
            item.link_methods[row["link_method"]] += 1
        if row.get("resolved_by") == "LLM" or row.get("link_method", "").startswith("LLM"):
            item.llm_backwalk = True
        value = concrete_value(row.get("resolved_value"), site.resource)
        if row.get("status") not in {
            "UNRESOLVED",
            "NO_ROOT",
            "UNREACHABLE",
            "EXTERNAL",
        } and value is not None:
            item.values.add(value)

    for item in grouped.values():
        directness = {
            row_directness(raw, known_macros, None)
            for raw in item.raw_expressions
        }
        if not directness:
            item.directness = "UNKNOWN_ARGUMENT"
            skipped["unknown_argument"] += 1
        elif directness <= {"DIRECT_CONST", "DIRECT_MACRO"}:
            item.directness = "DIRECT_CONST_MACRO"
            skipped["direct_const_macro"] += 1
        else:
            item.directness = "INDIRECT"
            skipped["indirect_or_mixed"] += 1
    return grouped, skipped, known_macros


def site_category(cvisualizer: CVisualizerSite | None, legacy: LegacySite | None) -> str:
    cvalues = cvisualizer.values if cvisualizer else set()
    lvalues = legacy.values if legacy else set()
    if cvalues and lvalues:
        if cvalues == lvalues:
            return "equal"
        if cvalues > lvalues:
            return "cvisualizer_superset"
        if cvalues < lvalues:
            return "cvisualizer_subset"
        if cvalues & lvalues:
            return "partial_overlap"
        return "disjoint"
    if cvalues:
        return "cvisualizer_resolved_only"
    if lvalues:
        return "legacy_resolved_only"
    return "both_unresolved"


def physical_site_key(site: Site) -> tuple[str, str, int, str, int]:
    """Identify a call location without making the operation label part of it."""

    return site.resource, site.file, site.line, site.target_function, site.arg_index


def active_indirect_sites(
    grouped: dict[Site, CVisualizerSite | LegacySite],
    source_classifier: SourceClassifier,
) -> tuple[dict[Site, CVisualizerSite | LegacySite], Counter[str]]:
    eligible: dict[Site, CVisualizerSite | LegacySite] = {}
    excluded = Counter()
    for site, item in grouped.items():
        if item.directness != "INDIRECT":
            excluded[item.directness] += 1
            continue
        source_class = source_classifier.classify(site.file, site.line)
        if source_class != "ACTIVE_CODE":
            excluded[source_class] += 1
            continue
        eligible[site] = item
    return eligible, excluded


def counter_dict(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def site_dict(
    site: Site,
    source_root: Path,
    cvisualizer: CVisualizerSite | None,
    legacy: LegacySite | None,
) -> dict[str, Any]:
    category = site_category(cvisualizer, legacy)
    return {
        "resource": site.resource,
        "file": site.file,
        "absolute_file": site.absolute_file(source_root),
        "line": site.line,
        "target_function": site.target_function,
        "arg_index": site.arg_index,
        "operation": site.operation,
        "category": category,
        "cvisualizer": {
            "expressions": sorted(cvisualizer.expressions) if cvisualizer else [],
            "values": sorted(cvisualizer.values) if cvisualizer else [],
            "syntax_values": sorted(cvisualizer.syntax_values) if cvisualizer else [],
            "statuses": counter_dict(cvisualizer.statuses) if cvisualizer else {},
            "resolved_by": counter_dict(cvisualizer.resolved_by) if cvisualizer else {},
            "link_methods": counter_dict(cvisualizer.link_methods) if cvisualizer else {},
            "fact_rows": len(cvisualizer.rows) if cvisualizer else 0,
        },
        "legacy": {
            "raw_expressions": sorted(legacy.raw_expressions) if legacy else [],
            "values": sorted(legacy.values) if legacy else [],
            "statuses": counter_dict(legacy.statuses) if legacy else {},
            "resolved_by": counter_dict(legacy.resolved_by) if legacy else {},
            "link_methods": counter_dict(legacy.link_methods) if legacy else {},
            "llm_backwalk": legacy.llm_backwalk if legacy else False,
            "proof_rows": len(legacy.rows) if legacy else 0,
            "provenance": sorted(
                {row.get("provenance", "") for row in legacy.rows if row.get("provenance")}
            )
            if legacy
            else [],
        },
    }


def comparison_report(
    cvisualizer: dict[Site, CVisualizerSite],
    legacy: dict[Site, LegacySite],
    source_root: Path,
) -> dict[str, Any]:
    classifier = SourceClassifier(source_root)
    c_active, c_excluded = active_indirect_sites(cvisualizer, classifier)
    l_active, l_excluded = active_indirect_sites(legacy, classifier)
    c_sites = set(c_active)
    l_sites = set(l_active)
    common = c_sites & l_sites
    categories = Counter(
        site_category(c_active.get(site), l_active.get(site)) for site in common
    )
    llm_common = {
        site for site in common if isinstance(l_active[site], LegacySite) and l_active[site].llm_backwalk
    }
    llm_categories = Counter(
        site_category(c_active.get(site), l_active.get(site)) for site in llm_common
    )

    c_physical_operations: dict[tuple[str, str, int, str, int], set[str]] = defaultdict(set)
    l_physical_operations: dict[tuple[str, str, int, str, int], set[str]] = defaultdict(set)
    for site in c_active:
        c_physical_operations[physical_site_key(site)].add(site.operation)
    for site in l_active:
        l_physical_operations[physical_site_key(site)].add(site.operation)
    c_physical = set(c_physical_operations)
    l_physical = set(l_physical_operations)
    physical_common = c_physical & l_physical

    def value_breakdown(site_set: set[Site]) -> dict[str, int]:
        c_items = [c_active[site] for site in site_set if site in c_active]
        l_items = [l_active[site] for site in site_set if site in l_active]
        c_values = {value for item in c_items for value in item.values}
        l_values = {value for item in l_items for value in item.values}
        return {
            "sites": len(site_set),
            "cvisualizer_value_entries": sum(len(item.values) for item in c_items),
            "legacy_value_entries": sum(len(item.values) for item in l_items),
            "cvisualizer_sites_with_values": sum(bool(item.values) for item in c_items),
            "legacy_sites_with_values": sum(bool(item.values) for item in l_items),
            "cvisualizer_distinct_values": len(c_values),
            "legacy_distinct_values": len(l_values),
        }

    value_breakdowns = {
        "common_operation_sites": value_breakdown(common),
        "cvisualizer_only_operation_sites": value_breakdown(c_sites - l_sites),
        "legacy_only_operation_sites": value_breakdown(l_sites - c_sites),
    }

    c_values = {value for item in c_active.values() for value in item.values}
    c_syntax_values = {value for item in c_active.values() for value in item.syntax_values}
    l_values = {value for item in l_active.values() for value in item.values}
    all_sites = common | (c_sites - l_sites) | (l_sites - c_sites)
    site_rows = [
        site_dict(site, source_root, c_active.get(site), l_active.get(site))
        for site in sorted(all_sites)
    ]

    examples: dict[str, list[dict[str, Any]]] = {}
    for category in [
        "equal",
        "cvisualizer_superset",
        "cvisualizer_subset",
        "partial_overlap",
        "disjoint",
        "cvisualizer_resolved_only",
        "legacy_resolved_only",
        "both_unresolved",
    ]:
        examples[category] = [
            row for row in site_rows if row["category"] == category
        ][:5]

    statuses_c = Counter()
    for item in c_active.values():
        statuses_c.update(item.statuses)
    statuses_l = Counter()
    for item in l_active.values():
        statuses_l.update(item.statuses)

    return {
        "schema_version": 1,
        "definition": {
            "step": "indirect_value_flow",
            "direct_cases_excluded": "literal or single macro passed directly",
            "active_source_only": True,
            "legacy_input": "valueflow_proof.csv",
            "cvisualizer_input": "discovery_facts.csv",
            "site_key": "resource + file + line + target function + argument index + canonical operation",
        },
        "inputs": {
            "cvisualizer_index": "",
            "source_root": str(source_root),
        },
        "populations": {
            "cvisualizer": {
                "indirect_active_sites": len(c_sites),
                "indirect_active_values": sum(len(item.values) for item in c_active.values()),
                "deterministic_syntax_values": len(c_syntax_values),
                "distinct_values": len(c_values),
                "status_counts_by_fact_row": counter_dict(statuses_c),
                "excluded_sites": counter_dict(c_excluded),
            },
            "legacy": {
                "indirect_active_sites": len(l_sites),
                "indirect_active_values": sum(len(item.values) for item in l_active.values()),
                "distinct_values": len(l_values),
                "llm_backwalk_sites": sum(
                    1 for item in l_active.values() if item.llm_backwalk
                ),
                "status_counts_by_proof_row": counter_dict(statuses_l),
                "excluded_sites": counter_dict(l_excluded),
            },
        },
        "site_discovery": {
            "common_indirect_active_sites": len(common),
            "cvisualizer_only_indirect_active_sites": len(c_sites - l_sites),
            "legacy_only_indirect_active_sites": len(l_sites - c_sites),
            "cvisualizer_site_coverage_of_legacy": (
                len(common) / len(l_sites) if l_sites else 0.0
            ),
        },
        "physical_site_discovery": {
            "common_locations_ignoring_operation_label": len(physical_common),
            "cvisualizer_only_locations_ignoring_operation_label": len(c_physical - l_physical),
            "legacy_only_locations_ignoring_operation_label": len(l_physical - c_physical),
            "same_location_with_different_operation_labels": sum(
                c_physical_operations[site] != l_physical_operations[site]
                for site in physical_common
            ),
        },
        "value_breakdowns": value_breakdowns,
        "value_equivalence_on_common_sites": {
            "sites": len(common),
            "categories": counter_dict(categories),
            "legacy_llm_backwalk_sites": len(llm_common),
            "legacy_llm_backwalk_categories": counter_dict(llm_categories),
        },
        "sites": site_rows,
        "examples": examples,
    }


def markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return "_none_"
    return "\n".join(
        [
            "| " + " | ".join(rows[0]) + " |",
            "| " + " | ".join("---" for _ in rows[0]) + " |",
            *["| " + " | ".join(row) + " |" for row in rows[1:]],
        ]
    )


def format_values(values: Iterable[str]) -> str:
    values = sorted(values)
    return ", ".join(f"`{value}`" for value in values) if values else "none"


def render_markdown(report: dict[str, Any]) -> str:
    populations = report["populations"]
    c = populations["cvisualizer"]
    l = populations["legacy"]
    discovery = report["site_discovery"]
    physical = report["physical_site_discovery"]
    value_breakdowns = report["value_breakdowns"]
    comparison = report["value_equivalence_on_common_sites"]
    categories = comparison["categories"]
    lines = [
        "# Step 1 — Indirect value-flow comparison",
        "",
        "This report compares only active target calls whose argument is not a literal or a single directly passed macro. These are the cases that require value-flow tracing, helper-parameter backwalking, handle/FCB matching, or LLM assistance.",
        "",
        "## What the words mean",
        "",
        "- A **site** is one target call location, operation, and argument position.",
        "- An **indirect site** has an argument such as `file_no`, `&fcb`, a helper parameter, or an expression instead of a direct literal/macro.",
        "- A **value** is a concrete numeric file/queue number or a concrete fork-process name.",
        "- **c-visualizer-only site** means c-visualizer discovered the active indirect call but the legacy proof file has no matching site.",
        "- **legacy-only site** means the legacy proof file has the active indirect call but c-visualizer has no matching site.",
        "- The value comparison uses sets: if one site can have several possible values, all values are compared together.",
        "",
        "## What each number means",
        "",
        markdown_table(
            [
                ["What the number means", "c-visualizer", "legacy"],
                [
                    "Active indirect comparison sites (location + operation)",
                    f"{c['indirect_active_sites']:,}",
                    f"{l['indirect_active_sites']:,}",
                ],
                [
                    "Concrete value possibilities found across those locations",
                    f"{c['indirect_active_values']:,}",
                    f"{l['indirect_active_values']:,}",
                ],
                [
                    "Unique concrete values, ignoring where they were found",
                    f"{c['distinct_values']:,}",
                    f"{l['distinct_values']:,}",
                ],
                [
                    "Legacy indirect sites with LLM-assisted proof",
                    "not applicable",
                    f"{l['llm_backwalk_sites']:,}",
                ],
            ]
        ),
        "",
        "These rows count different things and must not be added together. Direct constants/macros are deliberately absent here; they belong to Step 0.",
        "",
        "### 1. Active indirect comparison sites",
        "",
        f"c-visualizer counted **{c['indirect_active_sites']:,} comparison sites** where the target argument is indirect—for example `&fcb`, `file_no`, a helper parameter, or another expression. Legacy has **{l['indirect_active_sites']:,}**. A comparison site includes the operation label, so the same physical call can appear separately when the tools describe its operation differently.",
        "",
        "### 2. Concrete value possibilities",
        "",
        f"c-visualizer found **{c['indirect_active_values']:,} value-at-location entries**; legacy found **{l['indirect_active_values']:,}**. A single location can contribute several entries. For example, `/home/chukyu/t-svm/src/svm000/svm000FileInt.c:895` contributes nine c-visualizer possibilities (`2621` through `2629`) but one legacy possibility (`2622`).",
        "",
        "This is why the value count can be larger than the location count. It measures how many possible values were attached to source locations, not how many unique numbers exist.",
        "",
        "### 3. Unique values across the whole comparison",
        "",
        f"After removing repeated values from different locations, c-visualizer has **{c['distinct_values']:,} unique values** and legacy has **{l['distinct_values']:,}**. For example, if `2622` appears at 100 different locations, it still counts as one unique value here. This number says nothing by itself about which tool is correct.",
        "",
        "### 4. Legacy LLM-assisted proof",
        "",
        f"The legacy proof marks **{l['llm_backwalk_sites']:,} indirect sites** as having LLM involvement. In plain English: at 724 source call locations, the legacy pipeline used or recorded an LLM-assisted backwalk while trying to determine the argument’s value. This is a count of locations—not 724 LLM calls and not 724 successfully resolved values. For example, `/home/chukyu/t-dyn/src/dyn010/dyn010Main.c:195` has two legacy proof rows for the same call, but it counts as one LLM-assisted site. The c-visualizer cell says `not applicable` because this row describes a legacy-specific proof flag.",
        "",
        "## Why the numbers differ",
        "",
        "### Why does c-visualizer have more comparison sites?",
        "",
        f"There are **{discovery['cvisualizer_only_indirect_active_sites']:,} c-visualizer-only operation-aware sites**. Of these, **{sum(1 for row in report['sites'] if row['cvisualizer']['expressions'] and not row['legacy']['raw_expressions'] and 'UNREACHABLE' in row['cvisualizer']['statuses']):,}** are marked `UNREACHABLE`. That means c-visualizer found the target call in active source code, but did not find a path to it from a recognized entry point. These are discovered call locations, not successful value resolutions. Legacy also has **{report['populations']['legacy']['excluded_sites'].get('UNKNOWN_ARGUMENT', 0):,}** proof locations with no original argument expression; those are excluded because we cannot tell whether their argument was indirect.",
        "",
        "For example, `/home/chukyu/t-dif/src/libdif/difSVRep.c:198` calls `pmf_forkprocbs_H(cpuname)`. c-visualizer records this active target call as `UNREACHABLE`; the legacy proof file has no corresponding row. This increases c-visualizer’s discovery count even though no value was resolved.",
        "",
        f"There is also an operation-label issue. Ignoring the operation name, the tools share **{physical['common_locations_ignoring_operation_label']:,} physical call locations**; c-visualizer has **{physical['cvisualizer_only_locations_ignoring_operation_label']:,} physical locations** legacy does not have, and legacy has **{physical['legacy_only_locations_ignoring_operation_label']:,}**. **{physical['same_location_with_different_operation_labels']:,} shared physical locations** use different operation labels. For example, `/home/chukyu/t-cha/src/cha101d/cha101dSVSave.c:133` is labeled `OPEN_LOCK` by c-visualizer and `READ` by legacy. It is one source call, not two calls.",
        "",
        "### Why does legacy have more concrete value entries?",
        "",
        "The total can be reconstructed like this:",
        "",
        markdown_table(
            [
                ["Operation-aware site group", "c-visualizer values", "legacy values"],
                [
                    "Sites present in both",
                    f"{value_breakdowns['common_operation_sites']['cvisualizer_value_entries']:,}",
                    f"{value_breakdowns['common_operation_sites']['legacy_value_entries']:,}",
                ],
                [
                    "c-visualizer-only sites",
                    f"{value_breakdowns['cvisualizer_only_operation_sites']['cvisualizer_value_entries']:,}",
                    "0",
                ],
                [
                    "legacy-only sites",
                    "0",
                    f"{value_breakdowns['legacy_only_operation_sites']['legacy_value_entries']:,}",
                ],
                [
                    "Total",
                    f"{c['indirect_active_values']:,}",
                    f"{l['indirect_active_values']:,}",
                ],
            ]
        ),
        "",
        f"On shared sites, legacy has a concrete value at **{value_breakdowns['common_operation_sites']['legacy_sites_with_values']:,} sites**, while c-visualizer has one at **{value_breakdowns['common_operation_sites']['cvisualizer_sites_with_values']:,} sites**. This is why legacy’s total is larger despite having fewer sites overall. Legacy contributes **{comparison['categories'].get('legacy_resolved_only', 0):,} shared sites** where it has a value and c-visualizer currently has none. c-visualizer contributes **{comparison['categories'].get('cvisualizer_resolved_only', 0):,} shared sites** in the opposite direction, plus its c-visualizer-only sites.",
        "",
        "A concrete legacy example is `/home/chukyu/t-cha/src/cha001/cha001ClrCaseMan.c:106`: the indirect argument is `&sCaseManFcb`. Legacy backwalking reaches `ChaCaseManageNo` and records `2836`; the current c-visualizer facts have no concrete value for that site. Conversely, at `/home/chukyu/t-svm/src/svm000/svm000FileInt.c:895`, c-visualizer produces nine possible values while legacy produces one.",
        "",
        "### Why does legacy have more unique values?",
        "",
        f"Legacy has **{l['distinct_values']:,} different concrete values** across its entries, while c-visualizer has **{c['distinct_values']:,}**. On the shared operation-aware sites, legacy contains **{value_breakdowns['common_operation_sites']['legacy_distinct_values']:,} unique values** and c-visualizer contains **{value_breakdowns['common_operation_sites']['cvisualizer_distinct_values']:,}**. The shared value sets overlap on **{len({value for row in report['sites'] if row['cvisualizer']['expressions'] and row['legacy']['raw_expressions'] for value in row['cvisualizer']['values']} & {value for row in report['sites'] if row['cvisualizer']['expressions'] and row['legacy']['raw_expressions'] for value in row['legacy']['values']}):,} values**; the rest come from different resolutions or from sites only one tool recorded.",
        "",
        "For example, `/home/chukyu/t-dyn/src/dyn010/dyn010Main.c:195` is the same indirect `&fcb` call in both outputs, but c-visualizer gives `1081` and legacy gives `1077`. A difference like this increases the unique-value count on both sides, but it is a disagreement that needs source inspection—it does not prove either value is correct.",
        "",
        "## Did both tools discover the same indirect calls?",
        "",
        markdown_table(
            [
                ["Plain-English measure", "Count"],
                ["Present in both active indirect populations", f"{discovery['common_indirect_active_sites']:,}"],
                ["Found only by c-visualizer", f"{discovery['cvisualizer_only_indirect_active_sites']:,}"],
                ["Found only by legacy", f"{discovery['legacy_only_indirect_active_sites']:,}"],
            ]
        ),
        "",
        f"The common-site comparison has **{discovery['common_indirect_active_sites']:,} sites**. The c-visualizer site coverage of the legacy indirect population is **{discovery['cvisualizer_site_coverage_of_legacy']:.1%}**; this is a discovery measure, not a correctness score.",
        "",
        "## Did they resolve the same values at the same sites?",
        "",
        markdown_table(
            [
                ["What happened at a shared site", "Sites"],
                ["Both produced exactly the same value set", f"{categories.get('equal', 0):,}"],
                ["c-visualizer produced a strict superset", f"{categories.get('cvisualizer_superset', 0):,}"],
                ["Legacy produced a strict superset", f"{categories.get('cvisualizer_subset', 0):,}"],
                ["Both overlap but disagree", f"{categories.get('partial_overlap', 0):,}"],
                ["Both resolved, but values are disjoint", f"{categories.get('disjoint', 0):,}"],
                ["Only c-visualizer produced a concrete value", f"{categories.get('cvisualizer_resolved_only', 0):,}"],
                ["Only legacy produced a concrete value", f"{categories.get('legacy_resolved_only', 0):,}"],
                ["Neither produced a concrete value", f"{categories.get('both_unresolved', 0):,}"],
            ]
        ),
        "",
        "A c-visualizer superset means it found every legacy value plus additional possible values at that same call site. That is the main category to inspect for the hypothesis that source-tree path enumeration finds more legitimate possibilities. It is not automatically proof that every extra value is correct.",
        "",
        "## Legacy LLM-backwalk subset",
        "",
        f"Among the **{comparison['legacy_llm_backwalk_sites']:,} shared sites** where the legacy proof records LLM involvement, the value-set categories are:",
        "",
        markdown_table(
            [["Category", "Sites"]]
            + [[category.replace("_", " "), f"{count:,}"] for category, count in comparison["legacy_llm_backwalk_categories"].items()]
        ),
        "",
        f"c-visualizer has **{c['deterministic_syntax_values']:,} distinct indirect values** whose fact was resolved without `resolved_by=LLM`. The report also retains all exact values separately, so LLM-assisted c-visualizer rows are not silently mixed into that deterministic count.",
        "",
        "## Examples",
        "",
    ]

    for category, title in [
        ("equal", "Same values"),
        ("cvisualizer_superset", "c-visualizer found more values"),
        ("cvisualizer_subset", "Legacy found more values"),
        ("partial_overlap", "Partial disagreement"),
        ("disjoint", "Both resolved different values"),
        ("cvisualizer_resolved_only", "Only c-visualizer resolved a value"),
        ("legacy_resolved_only", "Only legacy resolved a value"),
    ]:
        examples = report["examples"].get(category, [])
        if not examples:
            continue
        lines.extend([f"### {title}", ""])
        for example in examples[:3]:
            lines.extend(
                [
                    f"- `{example['absolute_file']}:{example['line']}` — `{example['target_function']}` / `{example['operation']}` / argument `{example['arg_index']}`.",
                    f"  - c-visualizer expression(s): {format_values(example['cvisualizer']['expressions'])}; values: {format_values(example['cvisualizer']['values'])}.",
                    f"  - legacy raw expression(s): {format_values(example['legacy']['raw_expressions'])}; values: {format_values(example['legacy']['values'])}; statuses: {format_values(example['legacy']['statuses'].keys())}.",
                ]
            )
            review_note = SOURCE_REVIEW_NOTES.get(
                (example["absolute_file"], int(example["line"]))
            )
            if review_note:
                lines.append(f"  - Source review: {review_note}")
        lines.append("")

    lines.extend(
        [
            "## What these examples show",
            "",
            "This small sample does not mean that one tool always wins. It shows three different behaviors:",
            "",
            "- The three `dif000` examples agree, and the source confirms both results by following the handle back to the matching `mpf_mfs_open` call.",
            "- The SVM examples are a warning: c-visualizer reported nine candidates, but the source opens each named handle with one specific macro. Legacy is correct there; c-visualizer was too broad.",
            "- In `dyn010` and `dyn232d`, legacy follows the handle to the specific open call while c-visualizer selects an unsupported number. In `dyn234d`, the source has two conditional possibilities, so legacy is only partially right and c-visualizer is incomplete.",
            "- The `dyn600` fork-process examples are genuine c-visualizer wins: the source defines `PROC_NAME` as `\"dyn600\"`, while legacy has no record.",
            "- The CHA examples are genuine legacy wins in this comparison: the source directly opens the same handle with `ChaCaseManageNo` or `ChaRecManageNo`, but c-visualizer did not carry that value from the open to the later read/write call.",
            "",
            "The main lesson is that a larger set is useful only when every value can be tied to a real source path. A source-backed single value is better than an unproven list of nearby values.",
            "",
        ]
    )

    lines.extend(
        [
            "## Excluded source lines",
            "",
            "Commented, blank, `#if 0`-disabled, and missing-source locations are excluded from the active Step 1 denominator. Their counts are retained in the JSON report under `populations.cvisualizer.excluded_sites` and `populations.legacy.excluded_sites`.",
            "",
            "## Limitations",
            "",
            "- This comparison measures equivalence and discovery; it does not by itself prove which extra value is correct.",
            "- A source-backed review of representative c-visualizer-superset, legacy-superset, and disjoint cases is still required.",
            "- Legacy rows without an original argument expression are not called indirect; they are classified as unknown and excluded rather than being used as a misleading denominator.",
            "",
        ]
    )
    return "\n".join(lines)


def write_site_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "category",
        "resource",
        "absolute_file",
        "line",
        "target_function",
        "arg_index",
        "operation",
        "cvisualizer_expressions",
        "cvisualizer_values",
        "cvisualizer_syntax_values",
        "cvisualizer_statuses",
        "legacy_raw_expressions",
        "legacy_values",
        "legacy_statuses",
        "legacy_llm_backwalk",
        "legacy_provenance",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "category": row["category"],
                    "resource": row["resource"],
                    "absolute_file": row["absolute_file"],
                    "line": row["line"],
                    "target_function": row["target_function"],
                    "arg_index": row["arg_index"],
                    "operation": row["operation"],
                    "cvisualizer_expressions": "; ".join(row["cvisualizer"]["expressions"]),
                    "cvisualizer_values": "; ".join(row["cvisualizer"]["values"]),
                    "cvisualizer_syntax_values": "; ".join(row["cvisualizer"]["syntax_values"]),
                    "cvisualizer_statuses": json.dumps(row["cvisualizer"]["statuses"], sort_keys=True),
                    "legacy_raw_expressions": "; ".join(row["legacy"]["raw_expressions"]),
                    "legacy_values": "; ".join(row["legacy"]["values"]),
                    "legacy_statuses": json.dumps(row["legacy"]["statuses"], sort_keys=True),
                    "legacy_llm_backwalk": row["legacy"]["llm_backwalk"],
                    "legacy_provenance": " || ".join(row["legacy"]["provenance"]),
                }
            )


def build_report(
    cvisualizer_index: Path,
    legacy_index: Path,
    source_root: Path,
) -> dict[str, Any]:
    cvisualizer, _, _ = load_cvisualizer(cvisualizer_index, source_root)
    legacy, _, _ = load_legacy(legacy_index, source_root)
    report = comparison_report(cvisualizer, legacy, source_root)
    report["inputs"] = {
        "cvisualizer_index": str(cvisualizer_index),
        "cvisualizer_facts": str(cvisualizer_index / "discovery_facts.csv"),
        "legacy_index": str(legacy_index),
        "legacy_proof": str(legacy_index / "valueflow_proof.csv"),
        "source_root": str(source_root),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cvisualizer-index", type=Path, required=True)
    parser.add_argument("--legacy-index", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    cvisualizer_index = args.cvisualizer_index.expanduser().resolve()
    legacy_index = args.legacy_index.expanduser().resolve()
    source_root = args.source_root.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    report = build_report(cvisualizer_index, legacy_index, source_root)
    (output_dir / "step1.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_site_csv(output_dir / "step1_sites.csv", report["sites"])
    (output_dir / "step1.md").write_text(
        render_markdown(report), encoding="utf-8"
    )

    categories = report["value_equivalence_on_common_sites"]["categories"]
    print("Step 1 indirect comparison (existing artifacts only; no pipeline run)")
    print(
        "  active indirect sites: "
        f"c-visualizer={report['populations']['cvisualizer']['indirect_active_sites']} "
        f"legacy={report['populations']['legacy']['indirect_active_sites']}"
    )
    print(
        "  common sites: "
        f"{report['site_discovery']['common_indirect_active_sites']} "
        f"c-viz-only={report['site_discovery']['cvisualizer_only_indirect_active_sites']} "
        f"legacy-only={report['site_discovery']['legacy_only_indirect_active_sites']}"
    )
    print(f"  value categories: {json.dumps(categories, sort_keys=True)}")
    print(f"  report: {output_dir / 'step1.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
