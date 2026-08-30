#!/usr/bin/env python3
"""Step 0: compare only direct CONST/MACRO target arguments.

This script is deliberately read-only.  It consumes the existing c-visualizer
aggregate index, c-visualizer discovery facts, the existing legacy index, and
the source tree used for proof locations.  It does not run either analysis
pipeline.

Step 0 includes only a target argument that is directly:

* an integer or string literal; or
* a single macro/enum name whose value is proved directly by syntax.

It excludes values obtained through helper parameters, variables, FCB/handle
matching, proximity matching, or LLM/data-flow propagation.  Those belong in
the later Step 1 analysis.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
}
QUEUE_OPERATIONS = {"ADDQUE", "DELQUE"}


@dataclass(frozen=True, order=True)
class Record:
    resource: str
    file: str
    line: int
    operation: str
    value: str

    @property
    def site(self) -> tuple[str, str, int, str]:
        return self.resource, self.file, self.line, self.operation


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


def canonical_value(value: Any, resource: str) -> str:
    text = str(value or "")
    if resource == "forkproc" and len(text) >= 2:
        if text[0] == text[-1] == '"':
            return text[1:-1]
    return text


def resource_for_operation(operation: str) -> str:
    if operation == "FORKPROC":
        return "forkproc"
    if operation in QUEUE_OPERATIONS:
        return "mfs_queue"
    if operation in FILE_OPERATIONS:
        return "mfs_file"
    return ""


def make_record(
    resource: str,
    file: Any,
    line: Any,
    operation: Any,
    value: Any,
    source_root: Path | None,
) -> Record:
    return Record(
        resource=resource,
        file=normalize_path(file, source_root),
        line=int_value(line),
        operation=str(operation or ""),
        value=canonical_value(value, resource),
    )


def load_exact_index(directory: Path, source_root: Path | None) -> set[Record]:
    records: set[Record] = set()
    for filename, resource in (
        ("mfs_file_access.json", "mfs_file"),
        ("mfs_queue_access.json", "mfs_queue"),
    ):
        payload = read_json(directory / filename, {})
        if not isinstance(payload, dict):
            continue
        for value, entries in payload.items():
            for entry in entries or []:
                records.add(
                    make_record(
                        resource,
                        entry.get("file"),
                        entry.get("line"),
                        entry.get("lock"),
                        value,
                        source_root,
                    )
                )

    payload = read_json(directory / "forkproc_targets_by_caller.json", {})
    if isinstance(payload, dict):
        for caller, entries in payload.items():
            for entry in entries or []:
                records.add(
                    make_record(
                        "forkproc",
                        caller,
                        entry.get("line"),
                        "FORKPROC",
                        entry.get("target"),
                        source_root,
                    )
                )
    return records


INTEGER_LITERAL = re.compile(r"[+-]?\d+")
STRING_LITERAL = re.compile(r'"(?:[^"\\]|\\.)*"')
IDENTIFIER = re.compile(r"[A-Za-z_]\w*")


def absolute_source_path(value: Any, source_root: Path) -> Path:
    path = Path(str(value or "").replace("\\", "/"))
    if path.is_absolute():
        return path
    return source_root / path


class SourceClassifier:
    """Small source-only classifier for obvious disabled/comment-only lines."""

    def __init__(self, source_root: Path):
        self.source_root = source_root
        self.cache: dict[str, tuple[list[str], list[str], list[bool]] | None] = {}

    def _scan(self, relative_path: str) -> tuple[list[str], list[str], list[bool]] | None:
        if relative_path in self.cache:
            return self.cache[relative_path]
        path = self.source_root / relative_path
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            self.cache[relative_path] = None
            return None

        in_block_comment = False
        code_lines: list[str] = []
        disabled_lines: list[bool] = []
        conditional_stack: list[bool] = []

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
            directive = clean
            if directive.startswith("#if"):
                expression = directive[3:].strip()
                conditional_stack.append(
                    expression == "0" or expression.startswith("0 ")
                )
            elif directive.startswith("#else") and conditional_stack:
                conditional_stack[-1] = not conditional_stack[-1]
            elif directive.startswith("#elif") and conditional_stack:
                conditional_stack[-1] = False
            elif directive.startswith("#endif") and conditional_stack:
                conditional_stack.pop()

            code_lines.append(clean)
            disabled_lines.append(any(conditional_stack))

        result = (lines, code_lines, disabled_lines)
        self.cache[relative_path] = result
        return result

    def classify(self, record: Record) -> str:
        scanned = self._scan(record.file)
        if scanned is None:
            return "MISSING_SOURCE"
        _, code_lines, disabled_lines = scanned
        if record.line <= 0 or record.line > len(code_lines):
            return "MISSING_SOURCE"
        if disabled_lines[record.line - 1]:
            return "IF0_DISABLED"
        if not code_lines[record.line - 1]:
            return "COMMENT_OR_BLANK"
        return "ACTIVE_CODE"


class SourceLines:
    def __init__(self, source_root: Path):
        self.source_root = source_root
        self.cache: dict[Path, list[str] | None] = {}

    def get(self, value: Any) -> list[str] | None:
        path = absolute_source_path(value, self.source_root)
        if path in self.cache:
            return self.cache[path]
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = None
        self.cache[path] = lines
        return lines

    def line(self, value: Any, line_number: Any) -> str:
        lines = self.get(value)
        try:
            line = int(line_number)
        except (TypeError, ValueError):
            return ""
        if not lines or line < 1 or line > len(lines):
            return ""
        return lines[line - 1]


class SourceDefinitions:
    """Index source-defined macros and enum constants used by Step 0.

    The resolver represents an enum constant as ``origin_kind=CONST``.  It is
    still a direct constant when the enum name is the target argument itself;
    it must not be pushed into Step 1 merely because it is not spelled
    ``#define``.  The legacy macro table is also incomplete for queue macros,
    so the legacy side uses this source index as a fallback.
    """

    SOURCE_SUFFIXES = {".c", ".h", ".cc", ".hh", ".cpp", ".hpp", ".inc"}

    def __init__(self, source_root: Path):
        self.source_root = source_root
        self._loaded: dict[Path, tuple[set[str], set[str]]] = {}
        self._all_loaded = False
        self.macro_names: set[str] = set()
        self.enum_names: set[str] = set()

    @staticmethod
    def _strip_comments(text: str) -> str:
        text = re.sub(
            r"/\*.*?\*/",
            lambda match: "\n" * match.group(0).count("\n"),
            text,
            flags=re.DOTALL,
        )
        return re.sub(r"//[^\n]*", "", text)

    @classmethod
    def _enum_names(cls, text: str) -> set[str]:
        """Return names from simple C enum bodies.

        This intentionally extracts names only; value evaluation remains the
        resolver's job.  Enum bodies in this source tree are ordinary comma-
        separated enumerators, including the leading-comma style used by the
        Dyn headers.
        """

        clean = cls._strip_comments(text)
        names: set[str] = set()
        for match in re.finditer(r"\benum(?:\s+[A-Za-z_]\w*)?\s*\{", clean):
            depth = 1
            index = match.end()
            while index < len(clean) and depth:
                if clean[index] == "{":
                    depth += 1
                elif clean[index] == "}":
                    depth -= 1
                index += 1
            if depth:
                continue
            body = clean[match.end() : index - 1]
            for item in body.split(","):
                enumerator = re.match(r"\s*([A-Za-z_]\w*)\b", item)
                if enumerator:
                    names.add(enumerator.group(1))
        return names

    def _load(self, value: Any) -> tuple[set[str], set[str]]:
        path = absolute_source_path(value, self.source_root).resolve()
        if path in self._loaded:
            return self._loaded[path]
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            result = (set(), set())
            self._loaded[path] = result
            return result

        macros = {
            match.group(1)
            for match in re.finditer(
                r"^\s*#\s*define\s+([A-Za-z_]\w*)\b", text, flags=re.MULTILINE
            )
        }
        enums = self._enum_names(text)
        result = (macros, enums)
        self._loaded[path] = result
        return result

    def load_file(self, value: Any) -> None:
        macros, enums = self._load(value)
        self.macro_names.update(macros)
        self.enum_names.update(enums)

    def load_all(self) -> None:
        if self._all_loaded:
            return
        for path in self.source_root.rglob("*"):
            if path.is_file() and path.suffix.lower() in self.SOURCE_SUFFIXES:
                self.load_file(path)
        self._all_loaded = True

    def is_enum_in_file(self, symbol: str, proof_file: Any) -> bool:
        _, enums = self._load(proof_file)
        return symbol in enums

    def is_macro_in_source(self, symbol: str) -> bool:
        self.load_all()
        return symbol in self.macro_names


def is_direct_literal(expression: str) -> bool:
    expression = expression.strip()
    return bool(INTEGER_LITERAL.fullmatch(expression) or STRING_LITERAL.fullmatch(expression))


def is_direct_symbol(
    expression: str,
    proof_line: str,
    proof_file: Any,
    definitions: SourceDefinitions,
) -> bool:
    """Require the target expression itself to be a proven symbol.

    This rejects examples such as ``file_no``, ``filenum``, ``fno``, and
    ``&fcb`` where c-visualizer eventually found a macro value elsewhere in
    the value flow.  The proof line for those rows defines a different macro.

    Enum constants are accepted here as direct constants.  Their proof line
    is an enumerator such as ``DynReCtlMainteFNO`` rather than a ``#define``.
    """
    expression = expression.strip()
    if not IDENTIFIER.fullmatch(expression):
        return False
    if re.search(
        rf"#\s*define\s+{re.escape(expression)}(?:\s|\(|$)",
        proof_line,
    ):
        return True
    return definitions.is_enum_in_file(expression, proof_file)


def is_direct_cvisualizer_row(
    row: dict[str, str],
    source_lines: SourceLines,
    definitions: SourceDefinitions,
) -> bool:
    if not (
        row.get("status") == "EXACT"
        and row.get("resolved_by") == "SYNTAX"
        and row.get("origin_kind") in {"CONST", "MACRO"}
    ):
        return False
    expression = row.get("target_expression", "").strip()
    if is_direct_literal(expression):
        return True
    return is_direct_symbol(
        expression,
        source_lines.line(row.get("source_file", ""), row.get("source_line", "")),
        row.get("source_file", ""),
        definitions,
    )


def source_contains_token(source_lines: SourceLines, file: str, line: int, token: str) -> bool:
    lines = source_lines.get(file)
    if not lines or line < 1 or line > len(lines):
        return False
    token_pattern = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])"
    )
    # build_index.py records the line where a multiline target call starts,
    # while the target macro argument may be on a following line. Scan only
    # that logical statement, stopping at its semicolon or opening brace so a
    # nearby unrelated use cannot be attributed to this record.
    for index in range(line - 1, min(len(lines), line + 31)):
        text = lines[index]
        if token_pattern.search(text):
            return True
        if re.search(r"[;{}]", text):
            return False
    return False


def index_macro_names(directory: Path) -> set[str]:
    payload = read_json(directory / "mfs_fno_macros.json", {})
    names: set[str] = set()
    if isinstance(payload, dict):
        for values in payload.values():
            if isinstance(values, list):
                names.update(str(value) for value in values)
    return names


def load_direct_legacy_records(
    directory: Path,
    source_root: Path,
    source_lines: SourceLines,
    definitions: SourceDefinitions,
) -> tuple[set[Record], list[dict[str, Any]]]:
    """Load legacy rows whose raw argument is on the target source line.

    The legacy MFS index also repeats an opened FNO on later FCB operations
    such as READREC/WRITEREC.  Those rows are not direct target arguments, so
    they are excluded here unless the raw expression is actually present on
    the recorded target line.

    The legacy forkproc builder emits only literal/macro calls into
    ``forkproc_targets_by_caller.json``, so those records are direct by the
    builder's own classification.
    """
    records: set[Record] = set()
    details: list[dict[str, Any]] = []
    known_macros = index_macro_names(directory)
    definitions.load_all()

    for filename, resource in (
        ("mfs_file_access.json", "mfs_file"),
        ("mfs_queue_access.json", "mfs_queue"),
    ):
        payload = read_json(directory / filename, {})
        if not isinstance(payload, dict):
            continue
        for value, entries in payload.items():
            for entry in entries or []:
                raw = str(entry.get("fno_raw", "")).strip()
                if not (INTEGER_LITERAL.fullmatch(raw) or IDENTIFIER.fullmatch(raw)):
                    continue
                if IDENTIFIER.fullmatch(raw) and not (
                    raw in known_macros
                    or raw in definitions.macro_names
                    or raw in definitions.enum_names
                ):
                    # An identifier such as file_no or fcb is a propagated
                    # variable, not a direct macro argument.
                    continue
                file = normalize_path(entry.get("file"), source_root)
                line = int(entry.get("line") or 0)
                if not source_contains_token(source_lines, file, line, raw):
                    continue
                record = make_record(
                    resource,
                    entry.get("file"),
                    line,
                    entry.get("lock"),
                    value,
                    source_root,
                )
                records.add(record)
                details.append(
                    {
                        "record": record,
                        "raw": raw,
                        "kind": "CONST"
                        if INTEGER_LITERAL.fullmatch(raw)
                        else "MACRO/ENUM",
                    }
                )

    payload = read_json(directory / "forkproc_targets_by_caller.json", {})
    if isinstance(payload, dict):
        for caller, entries in payload.items():
            for entry in entries or []:
                record = make_record(
                    "forkproc",
                    caller,
                    entry.get("line"),
                    "FORKPROC",
                    entry.get("target"),
                    source_root,
                )
                records.add(record)
                details.append(
                    {"record": record, "raw": entry.get("target", ""), "kind": "CONST/MACRO"}
                )

    return records, details


def read_facts(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [{str(k): str(v or "") for k, v in row.items()} for row in csv.DictReader(handle)]


def direct_cvisualizer_records(
    facts: list[dict[str, str]],
    aggregate: set[Record],
    source_root: Path,
    definitions: SourceDefinitions,
) -> tuple[set[Record], set[Record], dict[Record, list[dict[str, str]]], int]:
    source_lines = SourceLines(source_root)
    evidence_records: set[Record] = set()
    aggregate_records: set[Record] = set()
    evidence_by_record: dict[Record, list[dict[str, str]]] = defaultdict(list)
    direct_rows = 0

    for row in facts:
        if not is_direct_cvisualizer_row(row, source_lines, definitions):
            continue
        resource = resource_for_operation(row.get("operation", ""))
        if not resource:
            continue
        record = make_record(
            resource,
            row.get("target_site_file"),
            row.get("target_site_line"),
            row.get("operation"),
            row.get("resolved_value"),
            source_root,
        )
        direct_rows += 1
        evidence_records.add(record)
        evidence_by_record[record].append(row)
        if record in aggregate:
            aggregate_records.add(record)

    return aggregate_records, evidence_records, evidence_by_record, direct_rows


def site_count(records: set[Record]) -> int:
    return len({record.site for record in records})


def pct(part: int, whole: int) -> str:
    return f"{part / whole:.1%}" if whole else "n/a"


def path_for_record(record: Record, source_root: Path) -> str:
    return f"{absolute_source_path(record.file, source_root)}:{record.line}"


def fact_statuses(
    facts: list[dict[str, str]],
    source_root: Path,
) -> dict[tuple[str, str, int, str], list[dict[str, str]]]:
    output: dict[tuple[str, str, int, str], list[dict[str, str]]] = defaultdict(list)
    for row in facts:
        resource = resource_for_operation(row.get("operation", ""))
        if not resource:
            continue
        key = (
            resource,
            normalize_path(row.get("target_site_file"), source_root),
            int(row.get("target_site_line") or 0),
            row.get("operation", ""),
        )
        output[key].append(row)
    return output


def example_record(records: set[Record], preferred: tuple[str, ...]) -> Record | None:
    if not records:
        return None
    return sorted(
        records,
        key=lambda record: (
            next(
                (index for index, fragment in enumerate(preferred) if fragment in record.file),
                len(preferred),
            ),
            record,
        ),
    )[0]


def source_classification(
    records: set[Record], source_root: Path
) -> dict[str, dict[str, int]]:
    classifier = SourceClassifier(source_root)
    counts: Counter[str] = Counter(classifier.classify(record) for record in records)
    sites: dict[str, set[tuple[str, str, int, str]]] = defaultdict(set)
    for record in records:
        sites[classifier.classify(record)].add(record.site)
    return {
        label: {"records": counts[label], "sites": len(sites[label])}
        for label in sorted(counts)
    }


def legacy_gap_classification(
    records: set[Record],
    cvisualizer_evidence: set[Record],
    facts_by_site: dict[tuple[str, str, int, str], list[dict[str, str]]],
    source_lines: SourceLines,
    definitions: SourceDefinitions,
) -> dict[str, int]:
    """Explain legacy records absent from c-viz's final aggregate index."""

    counts: Counter[str] = Counter()
    for record in sorted(records):
        if record in cvisualizer_evidence:
            counts["FOUND_IN_CVIZ_EVIDENCE_NOT_PROMOTED"] += 1
            continue
        rows = facts_by_site.get(record.site, [])
        direct_exact = [
            row
            for row in rows
            if is_direct_cvisualizer_row(row, source_lines, definitions)
        ]
        if direct_exact:
            counts["CVIZ_EXACT_DIFFERENT_VALUE"] += 1
            continue
        if not rows:
            counts["NO_CVIZ_FACT_AT_SITE"] += 1
            continue
        statuses = {row.get("status", "") or "UNKNOWN" for row in rows}
        reachabilities = {row.get("reachability", "") or "" for row in rows}
        if reachabilities & {"CROSS_PROCESS_CALLER", "OUT_OF_PROCESS_SCOPE"}:
            # The site belongs to another process or library scope; it is not
            # an in-process unreachable result and must not be counted as one.
            counts["CVIZ_CROSS_PROCESS"] += 1
        elif "UNREACHABLE" in statuses:
            counts["CVIZ_UNREACHABLE"] += 1
        elif "UNRESOLVED" in statuses:
            counts["CVIZ_UNRESOLVED"] += 1
        elif "EXTERNAL" in statuses:
            counts["CVIZ_EXTERNAL"] += 1
        elif "DYNAMIC" in statuses:
            counts["CVIZ_DYNAMIC"] += 1
        else:
            counts["CVIZ_OTHER_STATUS"] += 1
    return dict(sorted(counts.items()))


def build_report(cvisualizer_index: Path, legacy_index: Path, source_root: Path) -> dict[str, Any]:
    aggregate = load_exact_index(cvisualizer_index, source_root)
    facts = read_facts(cvisualizer_index / "discovery_facts.csv")
    definitions = SourceDefinitions(source_root)
    direct_cviz, direct_cviz_evidence, evidence_by_record, direct_fact_rows = direct_cvisualizer_records(
        facts, aggregate, source_root, definitions
    )

    source_lines = SourceLines(source_root)
    direct_legacy, legacy_details = load_direct_legacy_records(
        legacy_index, source_root, source_lines, definitions
    )

    shared = direct_cviz & direct_legacy
    cvisualizer_only = direct_cviz - direct_legacy
    legacy_only = direct_legacy - direct_cviz
    legacy_source = source_classification(legacy_only, source_root)
    facts_by_site = fact_statuses(facts, source_root)
    legacy_gap = legacy_gap_classification(
        legacy_only,
        direct_cviz_evidence,
        facts_by_site,
        source_lines,
        definitions,
    )
    no_fact_records = {
        record
        for record in legacy_only
        if record not in direct_cviz_evidence
        and not facts_by_site.get(record.site)
    }

    return {
        "counts": {
            "cvisualizer_direct_fact_rows": direct_fact_rows,
            "cvisualizer_direct_evidence_records": len(direct_cviz_evidence),
            "cvisualizer_direct_index_records": len(direct_cviz),
            "cvisualizer_direct_index_sites": site_count(direct_cviz),
            "legacy_direct_records": len(direct_legacy),
            "legacy_direct_sites": site_count(direct_legacy),
            "shared_records": len(shared),
            "shared_sites": site_count(shared),
            "cvisualizer_only_records": len(cvisualizer_only),
            "cvisualizer_only_sites": site_count(cvisualizer_only),
            "legacy_only_records": len(legacy_only),
            "legacy_only_sites": site_count(legacy_only),
            "cvisualizer_direct_not_promoted": len(direct_cviz_evidence - direct_cviz),
        },
        "by_resource": {
            resource: {
                "cvisualizer": len({record for record in direct_cviz if record.resource == resource}),
                "legacy": len({record for record in direct_legacy if record.resource == resource}),
                "shared": len({record for record in shared if record.resource == resource}),
                "cvisualizer_only": len(
                    {record for record in cvisualizer_only if record.resource == resource}
                ),
                "legacy_only": len({record for record in legacy_only if record.resource == resource}),
            }
            for resource in ("mfs_file", "mfs_queue", "forkproc")
        },
        "legacy_source": legacy_source,
        "legacy_gap": legacy_gap,
        "legacy_no_fact_source": source_classification(no_fact_records, source_root),
        "examples": {
            "shared": example_record(
                shared,
                ("t-dif/src/dif001/dif001Main.c", "t-rep/src/msg200d/", "t-cha/src/"),
            ),
            "cvisualizer_tool": example_record(
                {record for record in cvisualizer_only if "/tool/" in record.file},
                ("t-rep/tool/msgreq/", "t-dif/tool/diftool/", "t-cha/tool/"),
            ),
            "cvisualizer_external_header": example_record(
                {record for record in cvisualizer_only if "t-tmm/src/tmm910/tmm910_main.c" in record.file},
                (),
            ),
            "legacy_unreachable": next(
                (
                    record
                    for record in sorted(legacy_only)
                    if record.file == "t-dif/src/dif900/dif900IntBackUp.c" and record.line == 70
                ),
                None,
            ),
            "legacy_disabled": next(
                (
                    record
                    for record in sorted(legacy_only)
                    if record.file == "t-cha/src/cha101d/cha101dTMSave.c" and record.line == 188
                ),
                None,
            ),
        },
        "evidence_by_record": evidence_by_record,
        "facts_by_site": facts_by_site,
    }


def record_label(record: Record | None, source_root: Path) -> str:
    if record is None:
        return "not found"
    return f"`{path_for_record(record, source_root)}` — `{record.operation}`, value `{record.value}`"


def evidence_description(
    record: Record | None,
    report: dict[str, Any],
    source_root: Path,
) -> str:
    if record is None:
        return "not found"
    rows = report["evidence_by_record"].get(record, [])
    if not rows:
        return "no c-visualizer evidence row"
    row = rows[0]
    proof = absolute_source_path(row.get("source_file", ""), source_root)
    proof_line = row.get("source_line", "0")
    return (
        f"target expression `{row.get('target_expression', '')}`; proof at "
        f"`{proof}:{proof_line}`"
    )


def facts_for_record(record: Record | None, report: dict[str, Any]) -> list[dict[str, str]]:
    if record is None:
        return []
    return report["facts_by_site"].get(record.site, [])


def markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return "_none_"
    header = "| " + " | ".join(rows[0]) + " |"
    separator = "| " + " | ".join("---" for _ in rows[0]) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n".join([header, separator, *body])


def render_markdown(report: dict[str, Any], paths: dict[str, str], source_root: Path) -> str:
    counts = report["counts"]
    by_resource = report["by_resource"]
    legacy_source = report["legacy_source"]
    legacy_gap = report["legacy_gap"]
    legacy_no_fact_source = report["legacy_no_fact_source"]
    shared = report["examples"]["shared"]
    tool = report["examples"]["cvisualizer_tool"]
    external = report["examples"]["cvisualizer_external_header"]
    unreachable = report["examples"]["legacy_unreachable"]
    disabled = report["examples"]["legacy_disabled"]

    lines = [
        "# Step 0 — Direct CONST/MACRO comparison",
        "",
        "This report compares only target calls where the target argument itself is a literal or a directly named macro. It uses the existing c-visualizer and legacy outputs; it does not run either pipeline.",
        "",
        "## What is included",
        "",
        "- A **constant** is a number or string written directly in the target argument, such as `1055` or `\"cha001\"`.",
        "- A **direct macro/constant** is a macro name or enum constant written directly in the target argument, such as `DifDefineNo` or `DynReCtlMainteFNO`, with a syntax proof for its value.",
        "- A **record** means one source location, operation, and resolved value in an index.",
        "- A **shared record** is present in both indexes with the same file, line, operation, and value.",
        "- A **c-viz-only record** is in the c-visualizer index but not the legacy index.",
        "- A **legacy-only record** is in the legacy index but not the c-visualizer index.",
        "",
        "## What is deliberately excluded",
        "",
        "This step does not count values that arrive through a helper parameter or variable, such as `file_no`, `filenum`, or `fno`. It also excludes `&fcb`/handle matching, proximity matching, LLM results, and other data-flow propagation. Those are Step 1 cases.",
        "",
        "For example, c-visualizer may eventually resolve `file_no` to four macros, but the target argument is still the variable `file_no`; it is not a direct CONST/MACRO target argument.",
        "",
        "The c-visualizer evidence file contains every discovered target fact. The final aggregate JSON index contains only exact facts that are in the relevant process scope. Therefore a value can be present in c-visualizer evidence but absent from its final JSON index.",
        "",
        "## The direct comparison",
        "",
        markdown_table(
            [
                ["What the number means", "Records", "Source locations"],
                [
                    "c-visualizer direct values in final aggregate index",
                    f"{counts['cvisualizer_direct_index_records']:,}",
                    f"{counts['cvisualizer_direct_index_sites']:,}",
                ],
                [
                    "legacy direct values",
                    f"{counts['legacy_direct_records']:,}",
                    f"{counts['legacy_direct_sites']:,}",
                ],
                [
                    "same value in both indexes",
                    f"{counts['shared_records']:,}",
                    f"{counts['shared_sites']:,}",
                ],
                [
                    "found only by c-visualizer",
                    f"{counts['cvisualizer_only_records']:,}",
                    f"{counts['cvisualizer_only_sites']:,}",
                ],
                [
                    "found only by legacy",
                    f"{counts['legacy_only_records']:,}",
                    f"{counts['legacy_only_sites']:,}",
                ],
            ]
        ),
        "",
        f"The final c-visualizer index has **{counts['cvisualizer_direct_index_records']:,} direct records**. The legacy index has **{counts['legacy_direct_records']:,} direct records**. They share **{counts['shared_records']:,} records**. c-visualizer has **{counts['cvisualizer_only_records']:,} additional records**, while legacy has **{counts['legacy_only_records']:,} records that c-visualizer does not have**.",
        "",
        f"The c-visualizer evidence file contains **{counts['cvisualizer_direct_fact_rows']:,} direct exact rows** before aggregate-index filtering. **{counts['cvisualizer_direct_not_promoted']:,}** of those were not promoted into the final aggregate index, so the comparison above uses the final index rather than mixing evidence rows with index rows.",
        "",
        "## Why legacy still has more final-index records",
        "",
        f"The raw difference is **{counts['legacy_direct_records'] - counts['cvisualizer_direct_index_records']:,} records** ({counts['legacy_direct_records']:,} legacy versus {counts['cvisualizer_direct_index_records']:,} c-visualizer). This is a net difference, not the number of calls c-visualizer missed: c-visualizer also has **{counts['cvisualizer_only_records']:,} records** that legacy does not have.",
        "",
        "The following breakdown explains every legacy-only record in the final-index comparison:",
        "",
        markdown_table(
            [
                ["What happened to the legacy record", "Records"],
                *[
                    [
                        {
                            "FOUND_IN_CVIZ_EVIDENCE_NOT_PROMOTED": "c-viz found the same value in evidence, but scope rules kept it out of the final JSON index",
                            "CVIZ_EXACT_DIFFERENT_VALUE": "c-viz found the same direct call with a different exact value",
                            "NO_CVIZ_FACT_AT_SITE": "no c-viz fact exists at that source location",
                            "CVIZ_CROSS_PROCESS": "the target site belongs to another process or library scope (cross-process evidence, not in-process unreachable)",
                            "CVIZ_UNREACHABLE": "c-viz found the call but could not prove reachability",
                            "CVIZ_UNRESOLVED": "c-viz found the call but did not resolve its value",
                            "CVIZ_EXTERNAL": "c-viz classified the value as external data",
                            "CVIZ_DYNAMIC": "c-viz classified the value as dynamic",
                            "CVIZ_OTHER_STATUS": "another c-viz status",
                        }.get(label, label),
                        f"{value:,}",
                    ]
                    for label, value in legacy_gap.items()
                ],
            ]
        ),
        "",
        "The most important distinction is between `FOUND_IN_CVIZ_EVIDENCE_NOT_PROMOTED` and `NO_CVIZ_FACT_AT_SITE`: the first is an index-scope difference, while the second is a genuine discovery gap that needs investigation. Enum constants are now included in the direct count, so they are no longer incorrectly pushed into Step 1.",
        "",
        f"Of the **{legacy_gap.get('NO_CVIZ_FACT_AT_SITE', 0):,}** locations with no c-viz fact, **{legacy_no_fact_source.get('IF0_DISABLED', {}).get('records', 0):,}** are inside `#if 0` disabled code and **{legacy_no_fact_source.get('ACTIVE_CODE', {}).get('records', 0):,}** are active-looking source locations. The active-looking portion is the real discovery gap to investigate; it is not automatically evidence of a resolver-value bug.",
        "",
        "## Counts by target type",
        "",
        markdown_table(
            [
                ["Target type", "c-visualizer", "legacy", "shared", "c-viz-only", "legacy-only"],
                *[
                    [
                        {"mfs_file": "MFS file operations", "mfs_queue": "MFS queue operations", "forkproc": "forkproc calls"}[resource],
                        f"{values['cvisualizer']:,}",
                        f"{values['legacy']:,}",
                        f"{values['shared']:,}",
                        f"{values['cvisualizer_only']:,}",
                        f"{values['legacy_only']:,}",
                    ]
                    for resource, values in by_resource.items()
                ],
            ]
        ),
        "",
        "## Examples you can open directly",
        "",
    ]

    if shared:
        lines.extend(
            [
                "### Same direct macro in both indexes",
                "",
                f"Target call: **{record_label(shared, source_root)}**.",
                "",
                f"c-visualizer proof: {evidence_description(shared, report, source_root)}. The macro definition is `/home/chukyu/t-dif/include/DifP.h:75`, where `DifDefineNo` is `2021`. This is the expected agreement case.",
                "",
            ]
        )

    if tool:
        lines.extend(
            [
                "### c-viz-only direct constant in a `tool/` file",
                "",
                f"Target call: **{record_label(tool, source_root)}**.",
                "",
                f"c-visualizer proof: {evidence_description(tool, report, source_root)}. The argument is the literal `1055`. The legacy `build_index.py` source collector scans `t-*/src`, so it does not scan this `t-*/tool` file.",
                "",
                "This is a genuine direct-constant discovery difference, not a propagated value.",
                "",
            ]
        )

    if external:
        lines.extend(
            [
                "### c-viz-only direct macro from an external header",
                "",
                f"Target call: **{record_label(external, source_root)}**.",
                "",
                f"c-visualizer proof: {evidence_description(external, report, source_root)}. The macro `FfeMntInfoFileNo` resolves to `3652` at `/home/chukyu_exe/include/ffe/FfeMntInfo.h:25`. The target argument itself is the macro, so this is still Step 0.",
                "",
                "The old index has no matching record for this direct call. This example shows c-viz resolving a direct macro whose definition is outside the ordinary `t-*/src` scan.",
                "",
            ]
        )

    if unreachable:
        statuses = facts_for_record(unreachable, report)
        status_text = ", ".join(sorted({row.get("status", "") for row in statuses if row.get("status")})) or "no c-viz fact"
        lines.extend(
            [
                "### Legacy-only direct macro where c-viz missed the target site",
                "",
                f"Target call: **{record_label(unreachable, source_root)}**. The macro definition is `/home/chukyu/t-dif/include/DifP.h:96`, where `DifBackUpNo` is `2045`.",
                "",
                f"c-visualizer has a fact for this direct target but its status is `{status_text}`. Therefore it does not promote a value into the final index. This does **not** prove that the source call is unreachable.",
                "",
                "The source call is inside `Dif900InitBackUp()`, which is called by `pmf_main_H()` at `/home/chukyu/t-dif/src/dif900/dif900Main.c:208`. The existing c-viz per-process output also traces that same function from `pmf_main_H` to its `mpf_mfs_open` at `/home/chukyu/t-dif/src/dif900/dif900IntBackUp.c:75` and `mpf_mfs_getrec` at line 86. The correct interpretation is: **the function is reachable, but c-viz failed to establish reachability for this particular `mpf_mfs_clearfile` target record**.",
                "",
            ]
        )

    if disabled:
        lines.extend(
            [
                "### Legacy-only direct macro inside disabled code",
                "",
                f"Target call: **{record_label(disabled, source_root)}**. This call is inside a `#if 0` block beginning at `/home/chukyu/t-cha/src/cha101d/cha101dTMSave.c:168`; the call itself is at line 188. The macro is `ChaOnlWorkTMNo`, defined at `/home/chukyu/t-cha/include/ChaDef.h:76`.",
                "",
                "The old index records the value, but the preprocessor disables this code. This is one concrete reason legacy-only records cannot all be treated as live targets.",
                "",
            ]
        )

    lines.extend(
        [
            "## Legacy-only records that are visibly not live",
            "",
            "The source check classified the legacy-only direct records as follows:",
            "",
            markdown_table(
                [
                    ["What this means", "Records", "Source locations"],
                    *[
                        [
                            "Inside `#if 0` (disabled code)"
                            if label == "IF0_DISABLED"
                            else "Commented-out or blank source line"
                            if label == "COMMENT_OR_BLANK"
                            else "Active-looking source code"
                            if label == "ACTIVE_CODE"
                            else label,
                            f"{values['records']:,}",
                            f"{values['sites']:,}",
                        ]
                        for label, values in legacy_source.items()
                    ],
                ]
                or [["No source classification available", "0", "0"]]
            ),
            "",
            f"At least **{sum(values['records'] for label, values in legacy_source.items() if label in {'IF0_DISABLED', 'COMMENT_OR_BLANK'}):,} legacy-only direct records** are visibly disabled or commented. The remaining legacy-only records are active-looking source records; they need separate target-level reachability or discovery analysis and must not be dismissed as no-op automatically. A c-viz `UNREACHABLE` status by itself is not proof that the surrounding function is unreachable.",
            "",
            "## Bottom line",
            "",
            "This is the clean baseline comparison for direct constants and direct macros. Step 0 shows which simple values both tools agree on, which direct values c-viz adds, and which direct values legacy has that c-viz has not promoted. Propagated values such as the `file_no` example are intentionally excluded and belong in Step 1.",
            "",
            "## Reproduction from existing outputs",
            "",
            "This command reads existing files and writes only the Markdown report; it does not run the analysis pipeline:",
            "",
            "```bash",
            f"python analysis/step0.py --cvisualizer-index {paths['cvisualizer']} \\",
            f"  --legacy-index {paths['legacy']} --source-root {paths['source']} \\",
            "  --output analysis/step0_report.md",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    script_dir = Path(__file__).resolve().parent
    cvisualizer_default = script_dir.parent / "results/csv_results/index"
    legacy_default = script_dir.parent.parent / "index"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cvisualizer-index", type=Path, default=cvisualizer_default)
    parser.add_argument("--legacy-index", type=Path, default=legacy_default)
    parser.add_argument("--source-root", type=Path, default=Path("/home/chukyu"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    cvisualizer_index = args.cvisualizer_index.expanduser().resolve()
    legacy_index = args.legacy_index.expanduser().resolve()
    source_root = args.source_root.expanduser().resolve()
    report = build_report(cvisualizer_index, legacy_index, source_root)
    rendered = render_markdown(
        report,
        {
            "cvisualizer": str(args.cvisualizer_index),
            "legacy": str(args.legacy_index),
            "source": str(args.source_root),
        },
        source_root,
    )
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
