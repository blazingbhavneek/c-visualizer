"""Build the `answer` payload defined in `coordinate.md` §3.4.

Both answer paths — the structural traversal in `structural.py` and the
research agent in `agent.py` — emit the same shape, so the frontend has one
renderer and no way to tell which produced a given answer.  Keeping that
construction here rather than in either producer is what makes that true.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence
from urllib.parse import quote

from .corpus import Corpus, FunctionRef
from .graphops import Path, interaction_direction


def numbered_source(function: FunctionRef, max_chars: int = 12_000) -> str | None:
    """Line-numbered source, matching what `/api/source` returns.

    The rail renders this verbatim in a `<pre>`, so the numbering has to be
    identical to the endpoint's or the two views of the same function would
    disagree about line numbers.
    """
    if not function.has_source:
        return None
    start = max(1, function.start_line)
    lines = (function.source or "").splitlines()
    text = "\n".join(f"{number:>5}  {line}" for number, line in enumerate(lines, start=start))
    if len(text) > max_chars:
        text = text[:max_chars] + "\n      … (truncated)"
    return text


def citation(function: FunctionRef, process: str | None = None) -> dict[str, Any]:
    """One `cited[]` entry.

    `process` is a single string because that is what the rail shows, but a
    function defined in the shared `scf_stubs.c` genuinely belongs to every
    process that links it.  The caller passes the process the answer is
    talking about; `processes` carries the full truth alongside.
    """
    chosen = process if process and process in function.processes else (
        function.processes[0] if function.processes else None
    )
    return {
        "id": function.id,
        "name": function.name,
        "process": chosen,
        "processes": list(function.processes),
        "file": function.file,
        "file_name": function.file_name,
        "start_line": function.start_line,
        "end_line": function.end_line,
        "is_external": function.is_external,
        "summary": function.summary,
        "signature": function.signature(),
        "source": numbered_source(function),
    }


def resource_payload(corpus: Corpus, resource_key: str) -> dict[str, Any] | None:
    """One `resources[]` entry, with the functions on each side."""
    resource = corpus.resource(resource_key)
    if resource is None:
        return None

    functions: dict[str, dict[str, Any]] = {}
    operations: list[str] = []
    directions: set[str] = set()
    for interaction in corpus.interactions_on(resource_key):
        if interaction.operation and interaction.operation not in operations:
            operations.append(interaction.operation)
        directions.add(interaction_direction(interaction))
        function = corpus.function(interaction.function_id) if interaction.function_id else None
        if function is not None:
            functions.setdefault(
                function.id,
                {
                    "id": function.id,
                    "name": function.name,
                    "process": interaction.process,
                    "operation": interaction.operation,
                },
            )

    direction = "both" if len(directions) > 1 else next(iter(directions), "both")
    return {
        "key": resource.key,
        "kind": resource.kind,
        "name": resource.name,
        "resolved": resource.resolved,
        "direction": direction,
        "processes": list(resource.processes),
        "functions": list(functions.values()),
        "operations": operations,
    }


def function_link(function: FunctionRef) -> str:
    """A `cg://` citation chip the frontend renders inline in the prose."""
    if function.start_line > 0:
        label = f"{function.file_name}:{function.start_line}-{function.end_line}"
    else:
        label = function.file_name or function.name
    return f"[{label}](cg://function/{function.id})"


def resource_link(resource_key: str, label: str | None = None) -> str:
    return f"[{label or resource_key}](cg://resource/{quote(resource_key)})"


def path_link(path: Path, label: str | None = None) -> str:
    return f"[{label or path.label}](cg://path/{path.id})"


def build_answer(
    text: str,
    *,
    corpus: Corpus,
    cited_ids: Sequence[str] = (),
    paths: Sequence[Path] = (),
    resource_keys: Sequence[str] = (),
    process: str | None = None,
    stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the terminal `answer` event.

    Functions named by the paths are folded into `cited` automatically: a path
    the user can click is useless if its steps are not in the rail, and every
    producer would otherwise have to remember to do this itself.
    """
    ordered: list[str] = []
    seen: set[str] = set()

    for function_id in list(cited_ids) + [
        step.function_id for path in paths for step in path.steps if step.function_id
    ]:
        if function_id and function_id not in seen and corpus.function(function_id):
            seen.add(function_id)
            ordered.append(function_id)

    cited = []
    for function_id in ordered:
        function = corpus.function(function_id)
        if function is not None:
            cited.append(citation(function, process))

    resources = []
    for key in dict.fromkeys(resource_keys):
        payload = resource_payload(corpus, key)
        if payload is not None:
            resources.append(payload)

    return {
        "text": text,
        "cited": cited,
        "paths": [path.as_dict() for path in paths],
        "resources": resources,
        "stats": stats or {},
    }
