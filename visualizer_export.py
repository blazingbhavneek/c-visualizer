"""Additive exporter for the process/function/resource visualizer.

The existing CSV, Mermaid and PyVis outputs deliberately remain the source of
record.  This module only writes a separate, versioned JSON snapshot that the
frontend can read without scraping those presentation formats.
"""

from __future__ import annotations

import hashlib
import csv
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

from output_paths import process_results_dir, results_root


def get_visualizer_results_root() -> Path:
    """Use the tracer's existing results root unless explicitly overridden."""
    return results_root()


def _stable_id(prefix: str, *parts: object) -> str:
    value = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha1(value.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _resource_kind(operation: str) -> str:
    operation = (operation or "").upper()
    if operation in {"QUEUEF"}:
        return "queue"
    if operation.endswith("F") or operation in {"OPENF", "CLOSEF"}:
        return "file"
    if operation.endswith("Q") or operation in {"ENQ", "DEQ", "ENQFORK", "ENQSEM"}:
        return "queue"
    if operation == "EVENT":
        return "event"
    if operation == "SEMAPHORE":
        return "semaphore"
    if operation in {"FORK", "FORKP", "FORKF", "KILL"}:
        return "process"
    if operation == "MESSAGE":
        return "message"
    return "daemon_resource"


def build_complete_call_graph(
    project_structure: dict[str, str],
    trees: dict[str, Any],
    function_pointer_args: dict[str, Any] | None = None,
    file_functions: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict, dict, dict, dict]:
    """Build the original analyzer graph once, before target-path filtering.
    """
    from call_graph.call_graph import CallGraphBuilder, build_call_trees
    from state.state import State

    state = State()
    graph = state.get("CALL_GRAPH")
    registry = state.get("FUNCTION_REGISTRY")
    tree_objects = state.get("TREE_OBJECTS")
    macros = state.get("BUILDER_MACROS")
    if graph is not None and registry is not None and tree_objects is not None:
        return graph, registry, tree_objects, macros or {}

    builder = CallGraphBuilder(
        project_structure=project_structure,
        trees=trees,
        function_pointer_args=function_pointer_args,
        file_functions=file_functions,
    )
    graph = builder.build()
    registry = builder.node_registry
    tree_objects = build_call_trees(graph, registry)
    macros = builder.macros

# sample output
# graph
            # '[svmyeq.c]svmyeq': [CallSite(callee=FunctionNode(name='memset',
            #                                                    file_name='svm001.c',
            #                                                    file_path='/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/gs-svm/src/svm001/svm001.c',
            #                                                    is_external=True,
            #                                                    is_static=False,
            #                                                    macro_expansion=None,
            #                                                    start_line=-1,
            #                                                    end_line=-1),
            #                                line_number=34,
            #                                callbacks=[],
            #                                start_byte=1532,
            #                                end_byte=1577),
            #                       CallSite(callee=FunctionNode(name='mdm_addrec',
            #                                                    file_name='svm001.c',
            #                                                    file_path='/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/gs-svm/src/svm001/svm001.c',
            #                                                    is_external=True,
            #                                                    is_static=False,
            #                                                    macro_expansion=None,
            #                                                    start_line=-1,
            #                                                    end_line=-1),
            #                                line_number=49,
            #                                callbacks=[],
            #                                start_byte=1962,
            #                                end_byte=1999),
            #                       CallSite(callee=FunctionNode(name='svm_errmsg',
            #                                                    file_name='svm_errmsg.c',
            #                                                    file_path='/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/gs-svm/src/svm001/svm001_svminit.c',
            #                                                    is_external=False,
            #                                                    is_static=False,
            #                                                    macro_expansion=None,
            #                                                    start_line=16,
            #                                                    end_line=114),
            #                                line_number=56,
            #                                callbacks=[],
            #                                start_byte=2228,
            #                                end_byte=2248),
# registry
#  'vprintf': FunctionNode(name='vprintf',
#                          file_name='svm500_110704log.c',
#                          file_path='/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/gs-svm/src/libsvm4/svm500_110704log.c',
#                          is_external=True,
#                          is_static=False,
#                          macro_expansion=None,
#                          start_line=-1,
#                          end_line=-1),
#  'vsprintf': FunctionNode(name='vsprintf',
#                           file_name='svm_printf6one.c',
#                           file_path='/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/gs-svm/src/libsvm/svm_printf6one.c',
#                           is_external=True,
#                           is_static=False,
#                           macro_expansion=None,
#                           start_line=-1,
#                           end_line=-1)}
# macros
#  'tst_f3_ctl': ('TST_F3_CTL',
#                 '/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/include/FILE/tst_f3_ctl.h',
#                 'tst_f3_ctl'),
#  'tst_init_ch': ('TST_INIT_CH',
#                  '/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/include/FILE/tst_init_ch.h',
#                  'tst_init_ch'),
#  'tst_siken': ('TST_SIKEN',
#                '/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/include/FILE/tst_siken.h',
#                'tst_siken'),
#  'usr_print': ('usr_fname = __FILE__; \\\n'
#                '\t\t\t\tusr_lineno = __LINE__; \\\n'
#                '\t\t\t\tusr_print_in\t\t\t                           ',
#                '/home/seigyo/c_repo/bhavneek/c-visualizer/SoudenKeisei/SoudenKeisei/modern/include/usr/usr_in.h',
#                'usr_print')}

    # TODO: Get the shape of tree_objects 

    state.set("CALL_GRAPH", graph)
    state.set("FUNCTION_REGISTRY", registry)
    state.set("TREE_OBJECTS", tree_objects)
    state.set("BUILDER_MACROS", macros)

    return graph, registry, tree_objects, macros


def build_complete_file_functions(
    trees: dict[str, Any],
    file_functions: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Add definition ranges using the already-parsed Tree-sitter trees.

    The legacy setup fills ``file_functions`` with libclang for source files.
    Headers are intentionally absent there, so the old visualizer checkpoint
    reparsed every missing header with libclang.  The call graph has already
    parsed all of those files with Tree-sitter; reuse those trees instead of
    starting another parser for thousands of headers.
    """
    complete = {name: dict(definitions) for name, definitions in file_functions.items()}
    for file_name, (tree, source_bytes) in trees.items():
        if file_name not in complete:
            complete[file_name] = _tree_function_definitions(tree, source_bytes)
    return complete


def _tree_function_definitions(tree: Any, source_bytes: bytes) -> dict[str, dict[str, Any]]:
    """Extract the visualizer's range metadata without reparsing a file."""

    def function_name(node: Any) -> str | None:
        if node.type == "identifier":
            return node.text.decode("latin-1", errors="replace")
        for child in node.children:
            if child.type in {
                "function_declarator",
                "pointer_declarator",
                "parenthesized_declarator",
                "identifier",
            }:
                name = function_name(child)
                if name:
                    return name
        return None

    definitions: dict[str, dict[str, Any]] = {}
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "function_definition":
            declarator = node.child_by_field_name("declarator")
            name = function_name(declarator) if declarator is not None else None
            if name:
                definitions[name] = {
                    "name": name,
                    "return_type": "",
                    "line": node.start_point.row + 1,
                    "start_line": node.start_point.row + 1,
                    "end_line": node.end_point.row + 1,
                }
        stack.extend(reversed(node.children))
    return definitions


class VisualizerCollector:
    """Collect one tracer run in memory and write one non-destructive snapshot."""

    schema_version = 1

    def __init__(
        self,
        *,
        process_name: str,
        process_root: Path | str,
        project_structure: dict[str, str],
        file_functions: dict[str, dict[str, Any]],
        main_file_name: str | None,
        entry_function_name: str | None = None,
        entry_points: list[tuple[str, str]] | None = None,
        root_diagnostics: dict[str, Any] | None = None,
        library_functions: set[str] | list[str] | None = None,
        run_id: str | None = None,
        results_root: Path | None = None,
    ) -> None:
        self.process_name = process_name
        self.process_root = str(Path(process_root))
        self.project_structure = {name: str(path) for name, path in project_structure.items()}
        self.file_functions = file_functions
        self.main_file_name = main_file_name
        self.entry_function_name = entry_function_name or "main"
        self.entry_points = list(dict.fromkeys(
            entry_points
            or ([(main_file_name, self.entry_function_name)] if main_file_name else [])
        ))
        self.root_diagnostics = root_diagnostics
        self.library_functions = set(library_functions or [])
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.results_root = results_root or get_visualizer_results_root()
        self.generated_at = datetime.now(timezone.utc).isoformat()

        self.functions: dict[str, dict[str, Any]] = {}
        self.calls: dict[str, dict[str, Any]] = {}
        self.resources: dict[str, dict[str, Any]] = {}
        self.interactions: dict[str, dict[str, Any]] = {}
        self.traces: dict[str, dict[str, Any]] = {}
        self._ids_by_name: dict[str, set[str]] = {}
        self._fact_origins: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
        self._run_dir: Path | None = None
        self._manifest_recorded = False
        self.source_files = self._capture_source_files()

    def _capture_source_files(self) -> list[dict[str, Any]]:
        """Embed analyzed inputs so a snapshot remains useful on another PC."""
        inputs: dict[str, Path] = {
            str(Path(path).resolve()): Path(path) for path in self.project_structure.values()
        }
        makefile = Path(self.process_root) / "Makefile"
        if makefile.is_file():
            inputs[str(makefile.resolve())] = makefile

        process_root = Path(self.process_root).resolve()
        items = sorted(inputs.items())
        workers = min(4, max(1, len(items)))
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="visualizer-sources"
        ) as executor:
            source_files = executor.map(
                partial(self._capture_source_file, process_root), items
            )
            return [source_file for source_file in source_files if source_file is not None]

    @staticmethod
    def _capture_source_file(
        process_root: Path, item: tuple[str, Path]
    ) -> dict[str, Any] | None:
        resolved_path, path = item
        try:
            content = path.read_text(encoding="latin-1", errors="replace")
        except OSError:
            return None
        try:
            relative_path = str(Path(resolved_path).relative_to(process_root))
        except ValueError:
            relative_path = None
        return {
            "id": _stable_id("source", resolved_path),
            "path": resolved_path,
            "relative_path": relative_path,
            "file_name": path.name,
            "language": "make" if path.name.lower() == "makefile" else path.suffix.lstrip("."),
            "sha256": hashlib.sha256(content.encode("latin-1", errors="replace")).hexdigest(),
            "content": content,
        }

    def _source_for_node(self, node: Any) -> tuple[str | None, str | None]:
        if getattr(node, "is_external", False):
            return None, None
        definition_path = self._definition_path(node)
        start, end = self._definition_range(node)
        source_file = next(
            (item for item in self.source_files if item["path"] == str(Path(definition_path).resolve())),
            None,
        ) if definition_path else None
        if source_file is None or start < 1 or end < start:
            return None, None
        lines = source_file["content"].splitlines()
        source = "\n".join(lines[start - 1 : min(end, len(lines))])
        digest = hashlib.sha256(source.encode("latin-1", errors="replace")).hexdigest()
        return source, digest

    def _definition_range(self, node: Any) -> tuple[int, int]:
        start = int(getattr(node, "start_line", -1) or -1)
        end = int(getattr(node, "end_line", -1) or -1)
        if start >= 1 and end >= start:
            return start, end
        definition = self.file_functions.get(
            getattr(node, "file_name", ""), {}
        ).get(getattr(node, "name", ""), {})
        return (
            int(definition.get("start_line", -1) or -1),
            int(definition.get("end_line", -1) or -1),
        )

    def _definition_path(self, node: Any) -> str | None:
        """Prefer the definition file preserved by FunctionNode/file_functions."""
        file_name = getattr(node, "file_name", "")
        if file_name in self.project_structure:
            return self.project_structure[file_name]

        for candidate, definitions in self.file_functions.items():
            if candidate == file_name and getattr(node, "name", "") in definitions:
                return self.project_structure.get(candidate)

        file_path = getattr(node, "file_path", None)
        return str(file_path) if file_path else None

    def _function_id(self, node: Any) -> str:
        name = getattr(node, "name", "unknown")
        if getattr(node, "is_external", False):
            return _stable_id("external", name)

        definition_path = self._definition_path(node) or "unknown-source"
        start, end = self._definition_range(node)
        return _stable_id(
            "function",
            definition_path,
            name,
            start,
            end,
        )

    def _add_function(self, node: Any) -> str:
        function_id = self._function_id(node)
        if function_id in self.functions:
            return function_id

        name = getattr(node, "name", "unknown")
        definition_path = self._definition_path(node)
        is_external = bool(getattr(node, "is_external", False))
        is_library_api = name in self.library_functions
        start, end = self._definition_range(node)
        source, source_sha256 = self._source_for_node(node)
        self.functions[function_id] = {
            "id": function_id,
            "kind": "external_function" if is_external else "function",
            "name": name,
            "file": definition_path,
            "file_name": getattr(node, "file_name", None),
            "start_line": start,
            "end_line": end,
            "is_external": is_external,
            "is_library_api": is_library_api,
            "is_static": bool(getattr(node, "is_static", False)),
            "summary_status": (
                "library" if is_external or is_library_api else "pending"
            ),
            "summary": None,
            "source": source,
            "source_sha256": source_sha256,
        }
        self._ids_by_name.setdefault(name, set()).add(function_id)
        return function_id

    def _add_call(
        self,
        source: str,
        target: str,
        *,
        line: int | None,
        kind: str,
        via: str | None = None,
    ) -> None:
        call_id = _stable_id("call", source, target, line, kind, via or "")
        self.calls[call_id] = {
            "id": call_id,
            "source": source,
            "target": target,
            "line": line,
            "kind": kind,
            "via": via,
        }

    def capture_call_graph(
        self,
        *,
        graph: dict[str, list[Any]] | None,
        registry: dict[str, Any] | None,
        target_function: str | None = None,
        trace_paths: list[list[str]] | None = None,
    ) -> None:
        """Capture the raw call graph once, then append target-specific traces."""
        graph = graph or {}
        registry = registry or {}

        for node in registry.values():
            self._add_function(node)

        for caller_key, call_sites in graph.items():
            caller = registry.get(caller_key)
            if caller is None:
                continue
            source = self._add_function(caller)
            for call_site in call_sites:
                callee = call_site.callee
                target = self._add_function(callee)
                if callee.name == "indirect_call":
                    kind = "indirect"
                elif callee.macro_expansion:
                    kind = "macro_call"
                elif callee.is_external:
                    kind = "external_call"
                else:
                    kind = "direct"
                self._add_call(source, target, line=call_site.line_number, kind=kind)

                if callee.macro_expansion:
                    expanded = self._add_function(callee.macro_expansion)
                    self._add_call(
                        target,
                        expanded,
                        line=call_site.line_number,
                        kind="macro_expansion",
                    )

                for callback in call_site.callbacks:
                    callback_id = self._add_function(callback)
                    self._add_call(
                        source,
                        callback_id,
                        line=call_site.line_number,
                        kind="callback",
                        via=target,
                    )

        for labels in trace_paths or []:
            if not target_function:
                continue
            trace_id = _stable_id("trace", target_function, "\n".join(labels))
            self.traces[trace_id] = {
                "id": trace_id,
                "target_api": target_function,
                "labels": labels,
                "display_path": " -> ".join(labels),
            }

    def _caller_for_interaction(self, api_name: str, source: dict[str, Any]) -> str | None:
        source_path = str(source.get("path", ""))
        source_line = str(source.get("line_number", ""))
        candidates = []
        for call in self.calls.values():
            target = self.functions.get(call["target"], {})
            if target.get("name") != api_name:
                continue
            caller = self.functions.get(call["source"], {})
            same_file = not source_path or caller.get("file") == source_path
            same_line = not source_line or str(call.get("line")) == source_line
            if same_file and same_line:
                return call["source"]
            if same_file:
                candidates.append(call["source"])
        return candidates[0] if candidates else None

    def _load_fact_origins(self) -> None:
        """Load value-flow origins when this run has a facts.csv artifact."""
        facts_path = process_results_dir(self.process_name) / "facts.csv"
        if not facts_path.is_file():
            return
        try:
            with facts_path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    key = (
                        row.get("function_name", ""),
                        row.get("target_site_file", ""),
                        str(row.get("target_site_line", "")),
                        str(row.get("arg_index", "")),
                    )
                    self._fact_origins.setdefault(key, []).append(
                        {
                            "source_file": row.get("source_file", ""),
                            "source_line": row.get("source_line", ""),
                            "source_expr": row.get("source_expr", ""),
                            "origin_kind": row.get("origin_kind", ""),
                        }
                    )
        except (OSError, csv.Error):
            self._fact_origins = {}

    def record_combined(self, combined: dict[str, Any], argument_indices: list[int] | None) -> None:
        """Record one existing Combined result as function-to-resource evidence."""
        combined = _json_safe(combined)
        target = combined.get("target_number") or {}
        values = target.get("ans") or ["NO TARGET"]
        operation = combined.get("type", "NO DATA")
        target_api = combined.get("function_name", "unknown_api")
        source = combined.get("target_name_src") or {}
        caller_id = self._caller_for_interaction(target_api, source)

        # A trace may end in an external API not present in the raw graph.
        if caller_id is None:
            call_function = combined.get("call_function", "unknown")
            candidates = self._ids_by_name.get(call_function, set())
            caller_id = next(iter(candidates), None)

        bindings = []
        for position, value in enumerate(values):
            argument_index = (
                argument_indices[position]
                if argument_indices and position < len(argument_indices)
                else position + 1
            )
            bindings.append({"argument_index": argument_index, "value": value})

        for binding in bindings:
            value = binding["value"]
            resource_kind = _resource_kind(operation)
            resource_id = _stable_id("resource", resource_kind, value)
            self.resources.setdefault(
                resource_id,
                {
                    "id": resource_id,
                    "kind": resource_kind,
                    "name": str(value),
                    "resolved": value not in {"UNRESOLVED", "NO TARGET"},
                },
            )
            interaction_id = _stable_id(
                "interaction",
                caller_id or "unknown",
                resource_id,
                target_api,
                operation,
                binding["argument_index"],
                target.get("path_str", ""),
            )
            origin_key = (
                target_api,
                str(source.get("path", "")),
                str(source.get("line_number", "")),
                str(binding["argument_index"]),
            )
            self.interactions[interaction_id] = {
                "id": interaction_id,
                "function_id": caller_id,
                "resource_id": resource_id,
                "target_api": target_api,
                "operation": operation,
                "launch_via": combined.get("launch_via"),
                "call_number": combined.get("call_number"),
                "argument_binding": binding,
                "path": target.get("path_str"),
                "source": source,
                "function_source": combined.get("function_name_src"),
                "value_origins": self._fact_origins.get(origin_key, []),
            }

    def rehydrate_interactions(
        self,
        csv_path: Path | str,
        argument_indices_by_api: dict[str, list[int]],
    ) -> int:
        """Reload durable tracer rows when resume logic skips completed paths.

        Target tracing keeps its resumable source of record in the per-process
        CSV.  A new visualizer snapshot has a fresh in-memory collector, so
        skipped paths must be replayed into it or a resumed run silently loses
        resources and interactions.
        """
        csv_path = Path(csv_path)
        if not csv_path.is_file():
            return 0

        self._load_fact_origins()
        initial_count = len(self.interactions)
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                process_name = row.get("process_name", "")
                if process_name and process_name != self.process_name:
                    continue

                target_api = row.get("function_name", "")
                if not target_api:
                    continue
                argument_indices = list(argument_indices_by_api.get(target_api, []))
                raw_values = row.get("target_number->ans", "")
                if len(argument_indices) > 1:
                    values = raw_values.split(", ", len(argument_indices) - 1)
                else:
                    values = [raw_values or "NO TARGET"]

                call_number = row.get("call_number")
                if call_number in {None, "", "NA", "None", "nan"}:
                    call_number = None

                self.record_combined(
                    {
                        "call_number": call_number,
                        "target_number": {
                            "path_str": row.get("target_number->path_str", ""),
                            "ans": values,
                        },
                        "process_name": process_name or self.process_name,
                        "launch_via": row.get("launch_via") or "NO DATA",
                        "call_function": row.get("call_function") or "unknown",
                        "function_name": target_api,
                        "type": row.get("type") or "NO DATA",
                        "function_name_src": {
                            "path": row.get("function_name_src->path", ""),
                            "line_number": row.get("function_name_src->line_number", ""),
                        },
                        "target_name_src": {
                            "path": row.get("target_name_src->path", ""),
                            "line_number": row.get("target_name_src->line_number", ""),
                        },
                    },
                    argument_indices,
                )
        return len(self.interactions) - initial_count

    def _function_summary_fallbacks(self) -> None:
        outgoing = Counter(call["source"] for call in self.calls.values())
        interaction_count = Counter(
            interaction["function_id"]
            for interaction in self.interactions.values()
            if interaction.get("function_id")
        )
        for function_id, function in self.functions.items():
            function["call_count"] = outgoing.get(function_id, 0)
            function["resource_interaction_count"] = interaction_count.get(function_id, 0)
            if function["summary"] is None and not function["is_external"]:
                function["summary_hint"] = (
                    f"Static analysis: {outgoing.get(function_id, 0)} outgoing call(s), "
                    f"{interaction_count.get(function_id, 0)} daemon-resource interaction(s)."
                )

    def write(self) -> Path:
        """Checkpoint this run; repeated writes update only this run's snapshot."""
        self._function_summary_fallbacks()
        process_id = _stable_id("process", self.process_name, self.process_root)
        entry_records = []
        for file_name, function_name in self.entry_points:
            for function_id, function in self.functions.items():
                if (
                    function["name"] == function_name
                    and not function["is_external"]
                    and (
                        function.get("file_name") == file_name
                        or function.get("file")
                        == str(self.project_structure.get(file_name, ""))
                    )
                ):
                    entry_records.append(
                        {
                            "file": file_name,
                            "function": function_name,
                            "id": function_id,
                        }
                    )
                    break

        primary_entry = entry_records[0] if entry_records else None

        snapshot = {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "run_id": self.run_id,
            "process": {
                "id": process_id,
                "name": self.process_name,
                "root": self.process_root,
                "main_file": primary_entry["file"] if primary_entry else self.main_file_name,
                "entry_function": primary_entry["function"] if primary_entry else None,
                "entry_function_id": primary_entry["id"] if primary_entry else None,
                "entry_points": entry_records,
                "root_diagnostics": self.root_diagnostics or {},
            },
            "functions": sorted(self.functions.values(), key=lambda item: (item["name"], item["id"])),
            "calls": sorted(self.calls.values(), key=lambda item: item["id"]),
            "source_files": self.source_files,
            "resources": sorted(self.resources.values(), key=lambda item: (item["kind"], item["name"])),
            "interactions": sorted(self.interactions.values(), key=lambda item: item["id"]),
            "traces": sorted(self.traces.values(), key=lambda item: item["id"]),
        }

        if self._run_dir is None:
            run_dir = self.results_root / "visualizer" / self.process_name / "runs" / self.run_id
            # A different run in the same second remains non-destructive.
            suffix = 1
            while run_dir.exists():
                suffix += 1
                run_dir = run_dir.with_name(f"{self.run_id}_{suffix}")
            run_dir.mkdir(parents=True, exist_ok=False)
            self._run_dir = run_dir
        run_dir = self._run_dir
        snapshot["run_id"] = run_dir.name
        graph_path = run_dir / "graph.json"
        self._atomic_write_json(graph_path, snapshot)

        manifest_path = self.results_root / "visualizer" / "runs.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest: list[dict[str, str]] = []
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                # Snapshot directories remain intact even if this convenience
                # index was malformed by a prior interrupted run.
                manifest = []
        record = {
            "process_name": self.process_name,
            "run_id": run_dir.name,
            "graph": str(graph_path),
            "generated_at": snapshot["generated_at"],
        }
        existing_index = next(
            (
                index
                for index, item in enumerate(manifest)
                if item.get("process_name") == self.process_name
                and item.get("run_id") == run_dir.name
            ),
            None,
        )
        if existing_index is None:
            manifest.append(record)
        else:
            manifest[existing_index] = record
        self._atomic_write_json(manifest_path, manifest)
        self._manifest_recorded = True
        return graph_path

    @staticmethod
    def _atomic_write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
