"""Tests for the lazy visualizer read model (frontend/visualizer_readmodel.py).

Covers the Phase 1 guarantees: metadata-only catalog, group membership
validation, path safety, omission of source_files / function source bodies
from the compact endpoints, and the overview/plane agreement on direction and
library boundaries.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "frontend"))

from visualizer_readmodel import (  # noqa: E402
    ApiError,
    ReadModel,
    extract_run_data,
    interaction_direction,
    scan_graph_meta,
)

ROOT = "/fake/tool/A"
LIB = "/fake/shared/libfoo"


def _fn(fid, name, file, start=1, end=10, source=None, **extra):
    fn = {
        "id": fid,
        "kind": "function",
        "name": name,
        "file": file,
        "file_name": Path(file).name if file else None,
        "start_line": start,
        "end_line": end,
        "is_external": False,
        "is_library_api": False,
        "is_static": False,
        "summary_status": "pending",
        "summary": None,
        "source": source,
        "source_sha256": None,
        "call_count": 0,
        "resource_interaction_count": 0,
        "summary_hint": None,
    }
    fn.update(extra)
    return fn


def _interaction(iid, function_id, resource_id, api, operation, source_path, value_origins=None):
    return {
        "id": iid,
        "function_id": function_id,
        "resource_id": resource_id,
        "target_api": api,
        "operation": operation,
        "launch_via": "FORK" if api == "mpf_mfs_open" else None,
        "call_number": None,
        "argument_binding": {"argument_index": 1, "value": "X"},
        "path": "p",
        "source": {"path": source_path, "line_number": "3"},
        "function_source": {"path": source_path, "line_number": "1"},
        "value_origins": value_origins or [],
    }


def make_results(tmp_path: Path) -> Path:
    viz = tmp_path / "visualizer"
    root_a = tmp_path / "src" / "A"
    root_b = tmp_path / "src" / "B"
    root_a.mkdir(parents=True)
    root_b.mkdir(parents=True)
    libdir = tmp_path / "src" / "shared" / "libfoo"
    libdir.mkdir(parents=True)
    main_a = root_a / "main.c"
    main_a.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    main_b = root_b / "main.c"
    main_b.write_text("int main(void) { return 0; }\n", encoding="utf-8")

    def write(name, run, root, funcs, calls, resources, interactions, traces=None, extra=None):
        directory = viz / name / "runs" / run
        directory.mkdir(parents=True)
        graph = {
            "schema_version": 1,
            "generated_at": "2026-01-01T00:00:00Z",
            "run_id": run,
            "process": {
                "id": f"process:{name}",
                "name": name,
                "root": str(root),
                "main_file": "main.c",
                "entry_function": funcs[0]["name"] if funcs else None,
                "entry_function_id": funcs[0]["id"] if funcs else None,
            },
            "functions": funcs,
            "calls": calls,
            "source_files": [
                {
                    "id": "sf1",
                    "path": str(root / "main.c"),
                    "relative_path": "main.c",
                    "file_name": "main.c",
                    "language": "c",
                    "sha256": "h1",
                    "content": "BULK " * 10000,
                }
            ],
            "resources": resources,
            "interactions": interactions,
            "traces": traces or [],
        }
        if extra:
            graph.update(extra)
        (directory / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
        return directory

    a = write(
        "A",
        "r1",
        root_a,
        [
            _fn("function:main", "main", str(main_a), source="int main(void){}"),
            _fn("function:f1", "f1", str(main_a), start=11, end=20, summary_status="ok", summary="does f1"),
            _fn("function:lf", "libf", str(libdir / "foo.c")),
        ],
        [
            {"id": "call:1", "source": "function:main", "target": "function:f1", "line": 3, "kind": "direct", "via": None},
            {"id": "call:2", "source": "function:f1", "target": "function:lf", "line": 12, "kind": "direct", "via": None},
        ],
        [{"id": "resource:q", "kind": "file", "name": "QUEUE_A", "resolved": True}],
        [
            _interaction("interaction:1", "function:f1", "resource:q", "mpf_mfs_write", "WRITEF", str(main_a)),
            _interaction("interaction:2", "function:f1", "resource:ev", "pmf_sendevent", "EVENT", str(main_a)),
        ],
        traces=[
            {"id": "trace:1", "target_api": "mpf_mfs_write", "labels": ["[main.c]f1[11:20]", "[5]mpf_mfs_write"], "display_path": "f1 -> write"}
        ],
    )
    write(
        "B",
        "r1",
        root_b,
        [_fn("function:bmain", "bmain", str(main_b))],
        [],
        [
            {"id": "resource:q", "kind": "file", "name": "QUEUE_A", "resolved": True},
            {"id": "resource:ev", "kind": "event", "name": "A", "resolved": True},
        ],
        [
            _interaction("interaction:3", "function:bmain", "resource:q", "mpf_mfs_read", "READF", str(main_b)),
            _interaction("interaction:4", "function:bmain", "resource:ev", "pmf_sendevent", "EVENT", str(main_b)),
        ],
    )
    # Unsupported schema version run.
    write(
        "C",
        "r9",
        root_a,
        [_fn("function:c", "c", str(main_a))],
        [],
        [],
        [],
        extra={"schema_version": 99},
    )
    return viz


@pytest.fixture()
def results(tmp_path):
    make_results(tmp_path)
    return tmp_path


def test_catalog_is_metadata_only(results):
    model = ReadModel(results)
    runs = model.runs()
    names = {run["process_name"] for run in runs}
    assert names == {"A", "B", "C"}
    a_run = next(run for run in runs if run["process_name"] == "A")
    assert a_run["function_count"] == 3
    assert a_run["interaction_count"] == 2
    assert a_run["schema_version"] == 1
    # No graph payload leaks into the catalog response.
    serialized = json.dumps(runs)
    assert "BULK" not in serialized
    assert "source_files" not in serialized
    # The catalog is persisted as a bounded metadata index.
    assert (results / "visualizer" / "catalog.json").is_file()


def test_overview_joins_resources_by_kind_name(results):
    model = ReadModel(results)
    overview = model.overview([["A", "r1"], ["B", "r1"]])
    by_name = {node["name"]: node for node in overview["processes"] if node["type"] == "process"}
    assert by_name["A"]["functionCount"] == 2  # library function excluded
    assert by_name["A"]["interactionCount"] == 2
    resource = next(node for node in overview["resources"] if node["name"] == "QUEUE_A")
    assert resource["processes"] == ["A", "B"]
    assert resource["shared"] is True
    # Producer/consumer arrows: WRITEF out from A, READF in from B.
    edges = {(edge["processName"], edge["resourceKey"]): edge for edge in overview["edges"]}
    assert edges[("A", "file\x00QUEUE_A")]["direction"] == "out"
    assert edges[("B", "file\x00QUEUE_A")]["direction"] == "in"
    # The event addressed to process A aliases the process node.
    alias_edge = edges[("B", "event\x00A")]
    assert alias_edge["targetId"] == "process:A"
    assert overview["resource_aliases"] == {"event\x00A": "process:A"}
    # No structural data for the planes leaks into the overview.
    serialized = json.dumps(overview)
    for forbidden in ("source_files", '"source":', "calls", "traces"):
        assert forbidden not in serialized, forbidden


def test_overview_excludes_unsupported_runs(results):
    model = ReadModel(results)
    overview = model.overview([["A", "r1"], ["C", "r9"]])
    names = {node["name"] for node in overview["processes"]}
    assert "C" not in names
    assert overview["unsupported"] == [
        {"process_name": "C", "run_id": "r9", "schema_version": 99}
    ]


def test_overview_aggregates_library_nodes(results):
    model = ReadModel(results)
    overview = model.overview([["A", "r1"], ["B", "r1"]])
    library = [node for node in overview["processes"] if node["type"] == "library"]
    assert [node["name"] for node in library] == ["libfoo"]
    assert library[0]["functionCount"] == 2  # library functions + synthetic root

    snapshot = model.library("libfoo", overview["selection_key"])
    assert snapshot["process"]["kind"] == "library"
    names = [fn["name"] for fn in snapshot["functions"]]
    assert "libfoo (library)" in names and "libf" in names
    assert all("source" not in fn for fn in snapshot["functions"])


def test_process_plane_omits_source(results):
    model = ReadModel(results)
    plane = model.process("A", "r1")
    assert "source_files" not in plane
    assert all("source" not in fn for fn in plane["functions"])
    serialized = json.dumps(plane)
    assert "BULK" not in serialized
    # Plane keeps the structure the client's prepareProcess() needs.
    assert plane["process"]["entry_function_id"] == "function:main"
    assert plane["functions"][0]["name"] == "main"
    assert len(plane["calls"]) == 2
    # Interactions are compact but carry direction + library-ownership inputs.
    interaction = plane["interactions"][0]
    assert interaction["direction"] == "out"
    assert interaction["resource_key"] == "file\x00QUEUE_A"
    assert interaction["source"]["path"]


def test_function_detail_is_bounded(results):
    model = ReadModel(results)
    detail = model.function_detail("A", "r1", "function:f1")
    assert detail["function"]["name"] == "f1"
    assert detail["function"]["summary"] == "does f1"
    assert "source" not in detail["function"]
    assert detail["source_available"] is True
    assert [call["id"] for call in detail["outgoing"]] == ["call:2"]
    assert [call["id"] for call in detail["incoming"]] == ["call:1"]
    assert "function:main" in detail["neighbors"]
    assert "function:lf" in detail["neighbors"]
    assert len(detail["interactions"]) == 2
    assert detail["trace_total"] == 1
    assert len(detail["traces"]) == 1
    with pytest.raises(ApiError) as excinfo:
        model.function_detail("A", "r1", "function:missing")
    assert excinfo.value.status == 404


def test_source_embedded_and_filesystem_fallback(results):
    model = ReadModel(results)
    payload, status = model.source("A", "r1", "function:main")
    assert status == 200
    assert payload["embedded"] is True
    assert "int main" in payload["text"]
    assert "BULK" not in payload["text"]

    # f1 has no embedded slice: falls back to the process-root filesystem read.
    payload, status = model.source("A", "r1", "function:f1")
    assert status == 200
    assert payload["embedded"] is False
    assert payload["start_line"] == 11

    # Library function outside the process root is rejected with 403 when the
    # file exists, 404 when it does not.
    lib_fn_file = Path(results) / "src" / "shared" / "libfoo" / "foo.c"
    try:
        model.source("A", "r1", "function:lf")
        raised = None
    except ApiError as exc:
        raised = exc
    if lib_fn_file.is_file():
        assert raised.status == 403
    else:
        assert raised.status == 404
    lib_fn_file.write_text("int libf(void){}\n", encoding="utf-8")
    with pytest.raises(ApiError) as excinfo:
        model.source("A", "r1", "function:lf")
    assert excinfo.value.status == 403

    with pytest.raises(ApiError) as excinfo:
        model.source("A", "r1", "function:missing")
    assert excinfo.value.status == 404


def test_group_membership_is_enforced(results):
    model = ReadModel(results, group_members={("A", "r1")})
    assert [run["process_name"] for run in model.runs()] == ["A"]
    model.process("A", "r1")
    for call in (
        lambda: model.process("B", "r1"),
        lambda: model.function_detail("B", "r1", "function:bmain"),
        lambda: model.source("B", "r1", "function:bmain"),
        lambda: model.overview([["A", "r1"], ["B", "r1"]]),
    ):
        with pytest.raises(ApiError) as excinfo:
            call()
        assert excinfo.value.status == 400


def test_path_traversal_and_unknown_runs_are_rejected(results):
    model = ReadModel(results)
    for call in (
        lambda: model.process("../..", "r1"),
        lambda: model.process("A", "../.."),
        lambda: model.process("A", "r1/../../B/r1"),
        lambda: model.process("missing", "r1"),
        lambda: model.process("A", "missing"),
    ):
        with pytest.raises(ApiError) as excinfo:
            call()
        assert excinfo.value.status in (400, 404)


def test_resource_detail(results):
    model = ReadModel(results)
    overview = model.overview([["A", "r1"], ["B", "r1"]])
    detail = model.resource_detail(overview["selection_key"], "file", "QUEUE_A")
    assert detail["resource"]["processes"] == ["A", "B"]
    assert detail["operation_counts"] == {"WRITEF": 1, "READF": 1}
    aliased = model.resource_detail(overview["selection_key"], "event", "A")
    assert aliased["alias"] == "process:A"


def test_direction_semantics_match_frontend():
    assert interaction_direction({"target_api": "scf_evt_post", "operation": "READF"}) == "out"
    assert interaction_direction({"target_api": "scf_sem_wait", "operation": "WRITEF"}) == "both"
    assert interaction_direction({"target_api": None, "operation": "WRITEF"}) == "out"
    assert interaction_direction({"target_api": None, "operation": "READF"}) == "in"
    assert interaction_direction({"target_api": None, "operation": "OPENMF"}) == "both"


def test_derived_record_is_reused_across_instances(results):
    first = ReadModel(results)
    first.process("A", "r1")
    derived_dir = results / "visualizer" / "A" / "runs" / "r1"
    assert (derived_dir / "plane.json").is_file()
    assert (derived_dir / "function-index.json").is_file()

    second = ReadModel(results)
    detail = second.function_detail("A", "r1", "function:f1")
    assert detail["function"]["summary"] == "does f1"
    plane = json.loads((derived_dir / "plane.json").read_text(encoding="utf-8"))
    assert "BULK" not in json.dumps(plane)


def test_scanner_and_extractor_agree_with_json(results):
    graph_path = results / "visualizer" / "A" / "runs" / "r1" / "graph.json"
    text = graph_path.read_text(encoding="utf-8")
    graph = json.loads(text)
    meta = scan_graph_meta(text)
    assert meta["function_count"] == len(graph["functions"])
    assert meta["interaction_count"] == len(graph["interactions"])
    data = extract_run_data(text)
    assert {fn["id"] for fn in data["full_functions"]} == {fn["id"] for fn in graph["functions"]}
    assert all("source" not in fn for fn in data["full_functions"])
    assert data["embedded_source"]["function:main"]["text"] == "int main(void){}"
    assert data["embedded_source"]["function:main"]["start_line"] == 1
    assert not any("BULK" in json.dumps(part) for part in (data["calls"], data["resources"]))
