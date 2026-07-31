"""Additive exporter for the process/function/resource visualizer.

The existing CSV, Mermaid and PyVis outputs deliberately remain the source of
record.  This module only writes a separate, versioned JSON snapshot that the
frontend can read without scraping those presentation formats.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from output_paths import results_root


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
    if operation.endswith("F") or operation in {"OPENF", "CLOSEF"}:
        return "file"
    if operation.endswith("Q") or operation in {"ENQ", "DEQ", "ENQFORK", "ENQSEM"}:
        return "queue"
    if operation == "EVENT":
        return "event"
    if operation == "SEMAPHORE":
        return "semaphore"
    if operation in {"FORK", "FORKP", "KILL"}:
        return "process"
    if operation == "MESSAGE":
        return "message"
    return "daemon_resource"


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
        run_id: str | None = None,
        results_root: Path | None = None,
    ) -> None:
        self.process_name = process_name
        self.process_root = str(Path(process_root))
        self.project_structure = {name: str(path) for name, path in project_structure.items()}
        self.file_functions = file_functions
        self.main_file_name = main_file_name
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.results_root = results_root or get_visualizer_results_root()

        self.functions: dict[str, dict[str, Any]] = {}
        self.calls: dict[str, dict[str, Any]] = {}
        self.resources: dict[str, dict[str, Any]] = {}
        self.interactions: dict[str, dict[str, Any]] = {}
        self.traces: dict[str, dict[str, Any]] = {}
        self._ids_by_name: dict[str, set[str]] = {}

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
        return _stable_id(
            "function",
            definition_path,
            name,
            getattr(node, "start_line", -1),
            getattr(node, "end_line", -1),
        )

    def _add_function(self, node: Any) -> str:
        function_id = self._function_id(node)
        if function_id in self.functions:
            return function_id

        name = getattr(node, "name", "unknown")
        definition_path = self._definition_path(node)
        is_external = bool(getattr(node, "is_external", False))
        self.functions[function_id] = {
            "id": function_id,
            "kind": "external_function" if is_external else "function",
            "name": name,
            "file": definition_path,
            "file_name": getattr(node, "file_name", None),
            "start_line": getattr(node, "start_line", -1),
            "end_line": getattr(node, "end_line", -1),
            "is_external": is_external,
            "is_static": bool(getattr(node, "is_static", False)),
            "summary_status": "pending" if not is_external else "library",
            "summary": None,
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
        target_function: str,
        trace_paths: list[list[str]],
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

        for labels in trace_paths:
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
            }

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
        """Write a new run directory; no existing tracer output is replaced."""
        self._function_summary_fallbacks()
        process_id = _stable_id("process", self.process_name, self.process_root)
        main_id = None
        for function_id, function in self.functions.items():
            if function["name"] == "main" and not function["is_external"]:
                main_id = function_id
                break

        snapshot = {
            "schema_version": self.schema_version,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "process": {
                "id": process_id,
                "name": self.process_name,
                "root": self.process_root,
                "main_file": self.main_file_name,
                "entry_function_id": main_id,
            },
            "functions": sorted(self.functions.values(), key=lambda item: (item["name"], item["id"])),
            "calls": sorted(self.calls.values(), key=lambda item: item["id"]),
            "resources": sorted(self.resources.values(), key=lambda item: (item["kind"], item["name"])),
            "interactions": sorted(self.interactions.values(), key=lambda item: item["id"]),
            "traces": sorted(self.traces.values(), key=lambda item: item["id"]),
        }

        run_dir = self.results_root / "visualizer" / self.process_name / "runs" / self.run_id
        # A second export in the same second remains non-destructive.
        suffix = 1
        while run_dir.exists():
            suffix += 1
            run_dir = run_dir.with_name(f"{self.run_id}_{suffix}")
        run_dir.mkdir(parents=True, exist_ok=False)
        snapshot["run_id"] = run_dir.name
        (run_dir / "graph.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )

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
        manifest.append(
            {
                "process_name": self.process_name,
                "run_id": run_dir.name,
                "graph": str(run_dir / "graph.json"),
                "generated_at": snapshot["generated_at"],
            }
        )
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return run_dir / "graph.json"
