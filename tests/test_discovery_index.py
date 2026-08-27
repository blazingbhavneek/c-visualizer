"""Discovery-index adapter tests (no live model, no network).

Cover:
* the exact build-index JSON shapes and record identities;
* forkproc grouping/dedup (literal and macro package targets);
* MFS file/queue grouping, raw-expression preservation, hex/decimal normalisation;
* unresolved/dynamic/external/unreachable facts excluded from exact JSON but
  present in evidence;
* multiple reaching values (branches) preserved;
* path normalisation and duplicate basenames (process scope boundary);
* deterministic output across repeated writes;
* atomic writes and preservation of existing visualizer files;
* legacy Combined answer conversion.
"""

import asyncio
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from call_graph.call_graph import CallGraphBuilder
from discovery_index import (
    STATUS_DYNAMIC,
    STATUS_EXACT,
    STATUS_EXTERNAL,
    STATUS_NO_TARGET,
    STATUS_UNREACHABLE,
    STATUS_UNRESOLVED,
    build_discovery_payloads,
    build_target_site_inventory,
    legacy_answers_to_facts,
    rel_to_source_root,
    resolve_source_root,
    valueflow_records_to_facts,
    write_discovery_index,
)
from helpers.Preprocess.preprocess import Preprocess
from helpers.extract_functions_from_c import get_local_function_definitions
from models import Combined, Stats, TokenCount, outputModel
from target_spec import load_target_spec
from value_flow.resolver import ValueFlowResolver

REPO = Path(__file__).resolve().parents[1]
SPEC = load_target_spec(REPO / "target_specs" / "build_index_targets.json")

DEFS_H = """\
#define JDS_FILE_FNO 1234
#define JDS_QUEUE_FNO 5678
#define FORK_PKG "dyn002"
#define MPF_MFS_READLOCK 1
#define MPF_MFS_WRITELOCK 2
#define MY_OPEN(fcb, fno) mpf_mfs_open_H(fcb, fno, 0, 0, MPF_MFS_WRITELOCK)
"""

# Ground truth for the value-flow run (no LLM):
#   main open(fno)            -> 1234 (local var -> macro), READ
#   main getrec               -> 1234 (handle link, first open)
#   wrapper open              -> 1234 (parameter from main), READ
#   main addque JDS_QUEUE_FNO -> 5678, ADDQUE
#   dynamic_queue addque field -> DYNAMIC hint (g_qdef.QNo)
#   cb_queue addque param     -> EXTERNAL (framework input)
#   orphan_queue addque       -> UNREACHABLE (never called)
#   fork "dyn002" literal     -> dyn002
#   fork FORK_PKG macro       -> dyn002
#   MY_OPEN(&g_fcb, 4321)     -> 4321, WRITE (macro-renamed open)
#   main open 9999            -> 9999, WRITE
#   close                     -> NO TARGET
#   branch opens 1111/2222    -> both reach the last getrec (two values)
MAIN_C = """\
#include "defs.h"

typedef struct { int value; } FCB;
typedef struct { int QNo; } QDef;

FCB g_fcb;
QDef g_qdef;
int g_q;
int mode;

void mpf_mfs_open_H(FCB *fcb, int fno, int a, int b, int lock);
void mpf_mfs_getrec(FCB *fcb, int cc, int rec);
void mpf_mfs_addque(void *cpu, int fno, void *data);
void mpf_mfs_close(FCB *fcb);
void pmf_forkproc_H(const char *pkg);

void register_q(void (*handler)(int));

void wrapper(int fno)
{
    mpf_mfs_open_H(&g_fcb, fno, 0, 0, MPF_MFS_READLOCK);
}

void orphan_queue(int fno)
{
    mpf_mfs_addque((void *)0, fno, &g_q);
}

void cb_queue(int fno)
{
    mpf_mfs_addque((void *)0, fno, &g_q);
}

void dynamic_queue(void)
{
    mpf_mfs_addque((void *)0, g_qdef.QNo, &g_q);
}

int main(void)
{
    int fno = JDS_FILE_FNO;
    mpf_mfs_open_H(&g_fcb, fno, 0, 0, MPF_MFS_READLOCK);
    mpf_mfs_getrec(&g_fcb, 0, 3);
    wrapper(JDS_FILE_FNO);
    mpf_mfs_addque((void *)0, JDS_QUEUE_FNO, &g_q);
    dynamic_queue();
    register_q(cb_queue);
    pmf_forkproc_H("dyn002");
    pmf_forkproc_H(FORK_PKG);
    MY_OPEN(&g_fcb, 4321);
    mpf_mfs_open_H(&g_fcb, 9999, 0, 0, MPF_MFS_WRITELOCK);
    mpf_mfs_close(&g_fcb);
    if (mode) {
        mpf_mfs_open_H(&g_fcb, 1111, 0, 0, MPF_MFS_READLOCK);
    } else {
        mpf_mfs_open_H(&g_fcb, 2222, 0, 0, MPF_MFS_READLOCK);
    }
    mpf_mfs_getrec(&g_fcb, 0, 4);
    return mode;
}
"""


def _write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="latin-1")
    return path


def build_valueflow_env(
    project_structure: dict[str, Path],
    *,
    callbacks: dict | None = None,
    main_file: str = "main.c",
):
    """Resolver + parsed trees for one fixture, syntax-only (no LLM).

    ``project_structure`` maps project file names to paths of files that
    already exist on disk (any layout).
    """
    trees = Preprocess().preprocess(project_structure=project_structure)
    file_functions = {
        name: get_local_function_definitions(code_bytes=source)
        for name, (_, source) in trees.items()
    }
    builder = CallGraphBuilder(
        project_structure=project_structure,
        trees=trees,
        function_pointer_args=callbacks or {},
        file_functions=file_functions,
    )
    graph = builder.build()
    file_macros = {}
    for name, path in project_structure.items():
        text = path.read_text(encoding="latin-1")
        macros = {}
        for line in text.splitlines():
            parts = line.strip().split(maxsplit=2)
            if len(parts) == 3 and parts[:1] == ["#define"]:
                macros[parts[1]] = parts[2]
        file_macros[name] = macros
    resolver = ValueFlowResolver(
        graph=graph,
        registry=builder.node_registry,
        trees=trees,
        project_structure={key: str(value) for key, value in project_structure.items()},
        main_file_name=main_file,
        function_configs=dict(SPEC["targets"]),
        macros=builder.macros,
        file_macros=file_macros,
        path_cap=100,
    )
    return resolver, trees, builder


def run_valueflow_pipeline(
    root: Path,
    files: dict[str, str],
    *,
    callbacks: dict | None = None,
    process_root: Path | None = None,
    source_root: Path | None = None,
    main_file: str = "main.c",
):
    """Inventory + value-flow facts + payloads for one flat-layout fixture."""
    project_structure = {name: _write(root, name, text) for name, text in files.items()}
    resolver, trees, builder = build_valueflow_env(
        project_structure, callbacks=callbacks, main_file=main_file
    )
    records = asyncio.run(resolver.run())
    process_root = process_root or root
    source_root = source_root or resolve_source_root(process_root)
    return _pipeline_from_env(
        records, trees, builder, project_structure, process_root, source_root
    )


def _pipeline_from_env(
    records,
    trees,
    builder,
    project_structure: dict[str, Path],
    process_root: Path,
    source_root: Path,
):
    sites = build_target_site_inventory(
        trees=trees,
        functions_identified=dict(SPEC["targets"]),
        spec=SPEC,
        project_structure={k: str(v) for k, v in project_structure.items()},
        source_root=source_root,
        process_root=process_root,
        macros=builder.macros,
    )
    facts = valueflow_records_to_facts(
        records, sites, SPEC, source_root, process_root
    )
    payloads = build_discovery_payloads(
        process_name=process_root.name,
        source_root=source_root,
        process_root=process_root,
        target_sites=sites,
        facts=facts,
        resolver="valueflow",
        run_id="test-run",
        target_registry_version=SPEC["version"],
        target_registry_digest=SPEC["digest"],
    )
    return {
        "records": records,
        "sites": sites,
        "facts": facts,
        "payloads": payloads,
        "project_structure": {k: str(v) for k, v in project_structure.items()},
    }


def _csv_rows(payload: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(payload)))


def _line_of(c_source: str, needle: str) -> int:
    for number, line in enumerate(c_source.splitlines(), 1):
        if needle in line:
            return number
    raise AssertionError(f"needle not found: {needle}")


class DiscoveryAdapterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def chukyu_fixture(self) -> tuple[Path, Path, dict[str, str], dict[str, Path]]:
        """Process under a chukyu-like layout plus one out-of-scope library file."""
        source_root = self.root / "chukyu"
        process_root = source_root / "t-abc" / "src" / "procv"
        lib_root = source_root / "t-abc" / "src" / "libx"
        files = {
            "main.c": MAIN_C,
            "defs.h": DEFS_H,
            "libfile.c": (
                "void pmf_forkproc_H(const char *pkg);\n"
                "void lib_forks(void) { pmf_forkproc_H(\"libpkg\"); }\n"
            ),
        }
        paths = {
            "main.c": process_root / "main.c",
            "defs.h": process_root / "defs.h",
            "libfile.c": lib_root / "libfile.c",
        }
        for name, text in files.items():
            paths[name].parent.mkdir(parents=True, exist_ok=True)
            paths[name].write_text(text, encoding="latin-1")
        return source_root, process_root, files, paths

    def chukyu_env(self, callbacks: dict | None = None):
        source_root, process_root, files, paths = self.chukyu_fixture()
        resolver, trees, builder = build_valueflow_env(
            paths, callbacks=callbacks
        )
        records = asyncio.run(resolver.run())
        return _pipeline_from_env(
            records, trees, builder, paths, process_root, source_root
        )

    def test_inventory_covers_all_configured_call_sites(self):
        env = self.chukyu_env()
        sites = env["sites"]
        by_target = {}
        for site in sites:
            by_target.setdefault(site.target_function, []).append(site)

        self.assertEqual(len(by_target["mpf_mfs_open_H"]), 6)  # 5 direct + MY_OPEN
        self.assertEqual(len(by_target["mpf_mfs_getrec"]), 2)
        self.assertEqual(len(by_target["mpf_mfs_addque"]), 4)  # main + 3 helpers
        self.assertEqual(len(by_target["pmf_forkproc_H"]), 3)  # 2 in main + 1 in lib
        self.assertNotIn("mpf_mfs_close", by_target)  # close is not a discovery target

        # paths are source-root relative with forward slashes
        self.assertEqual(by_target["mpf_mfs_addque"][0].site_file, "t-abc/src/procv/main.c")
        lib_sites = [s for s in by_target["pmf_forkproc_H"] if not s.in_process]
        self.assertEqual(len(lib_sites), 1)
        self.assertEqual(lib_sites[0].site_file, "t-abc/src/libx/libfile.c")

        # the macro-renamed open keeps its lock argument and remapped FNO
        macro_site = next(s for s in by_target["mpf_mfs_open_H"] if s.macro_name)
        self.assertEqual(macro_site.arg_expression, "4321")
        self.assertEqual(macro_site.aux_lock, "MPF_MFS_WRITELOCK")

    def test_exact_json_shapes_match_build_index(self):
        env = self.chukyu_env()
        payloads = env["payloads"]
        main_rel = "t-abc/src/procv/main.c"

        fork_callers = json.loads(payloads["forkproc_callers.json"])
        self.assertEqual(fork_callers, {"dyn002": [main_rel]})
        # the out-of-scope library fork never enters the exact index
        self.assertNotIn("libpkg", fork_callers)

        fork_by_caller = json.loads(payloads["forkproc_targets_by_caller.json"])
        lines = {entry["line"] for entry in fork_by_caller[main_rel]}
        self.assertEqual(
            lines,
            {
                _line_of(MAIN_C, 'pmf_forkproc_H("dyn002")'),
                _line_of(MAIN_C, "pmf_forkproc_H(FORK_PKG)"),
            },
        )
        self.assertTrue(all(entry["target"] == "dyn002" for entry in fork_by_caller[main_rel]))

        file_access = json.loads(payloads["mfs_file_access.json"])
        self.assertTrue(all(key.isdigit() for key in file_access))
        # one record per (site, value): branches keep both values
        fno_1234 = file_access["1234"]
        self.assertEqual(len(fno_1234), 3)
        self.assertEqual(
            {(r["lock"], r["fno_raw"]) for r in fno_1234},
            {("READ", "JDS_FILE_FNO"), ("GETREC", "JDS_FILE_FNO")},
        )
        self.assertEqual(len(file_access["1111"]), 2)
        self.assertEqual(len(file_access["2222"]), 2)
        self.assertEqual(
            {(r["lock"], r["fno_raw"]) for r in file_access["1111"]},
            {("READ", "1111"), ("GETREC", "1111")},
        )
        self.assertEqual(file_access["4321"][0]["lock"], "WRITE")
        self.assertEqual(file_access["9999"][0]["lock"], "WRITE")
        self.assertEqual(file_access["9999"][0]["fno_raw"], "9999")
        for entries in file_access.values():
            for entry in entries:
                self.assertEqual(
                    set(entry), {"file", "line", "lock", "fno_raw"},
                    "record shape must match build_index exactly",
                )

        queue_access = json.loads(payloads["mfs_queue_access.json"])
        self.assertEqual(queue_access, {
            "5678": [
                {
                    "file": main_rel,
                    "line": _line_of(MAIN_C, "JDS_QUEUE_FNO"),
                    "lock": "ADDQUE",
                    "fno_raw": "JDS_QUEUE_FNO",
                }
            ]
        })

        dynamic = json.loads(payloads["mfs_dynamic_addque.json"])
        self.assertEqual(
            dynamic,
            {
                main_rel: [
                    {
                        "line": _line_of(MAIN_C, "g_qdef.QNo"),
                        "expr": "g_qdef.QNo",
                        "lock": "ADDQUE",
                    }
                ]
            },
        )

    def test_evidence_keeps_every_status_and_excludes_unresolved_from_json(self):
        env = self.chukyu_env(callbacks={"register_q": {"func_argument": [1]}})
        rows = _csv_rows(env["payloads"]["discovery_facts.csv"])
        statuses = {row["status"] for row in rows}
        self.assertIn(STATUS_EXACT, statuses)
        self.assertIn(STATUS_DYNAMIC, statuses)
        self.assertIn(STATUS_EXTERNAL, statuses)
        self.assertIn(STATUS_UNREACHABLE, statuses)
        self.assertIn(STATUS_NO_TARGET, statuses)

        # every inventory site appears in the evidence exactly per (value)
        site_keys = {
            (row["target_function"], row["target_site_file"], int(row["target_site_line"]), int(row["arg_index"]))
            for row in rows
        }
        inventory_keys = {
            (s.target_function, s.site_file, s.site_line, s.arg_index)
            for s in env["sites"]
        }
        self.assertTrue(inventory_keys <= site_keys, "inventory must be a subset of evidence")

        # the dynamic and external queue facts are NOT in the exact queue index
        queue_access = json.loads(env["payloads"]["mfs_queue_access.json"])
        self.assertEqual(set(queue_access), {"5678"})

        # the unreachable orphan_queue call is evidence-only
        orphan_rows = [r for r in rows if r["status"] == STATUS_UNREACHABLE]
        self.assertTrue(
            any(r["target_expression"] == "fno" for r in orphan_rows), orphan_rows
        )

        # close is recorded as NO TARGET, never as an FNO
        close_rows = [r for r in rows if r["target_function"] == "mpf_mfs_close"]
        self.assertTrue(close_rows)
        self.assertTrue(all(r["status"] == STATUS_NO_TARGET for r in close_rows))

    def test_duplicate_basenames_stay_distinct_and_scope_is_enforced(self):
        source_root = self.root / "chukyu"
        process_root = source_root / "t-abc" / "src" / "procv"
        files = {
            "a/mod.c": (
                "void mpf_mfs_open_H(void *fcb, int fno, int a, int b, int lock);\n"
                "void in_proc(void) { mpf_mfs_open_H(0, 111, 0, 0, MPF_MFS_READLOCK); }\n"
                "int main(void) { in_proc(); return 0; }\n"
            ),
            "b/mod.c": (
                "void mpf_mfs_open_H(void *fcb, int fno, int a, int b, int lock);\n"
                "void in_lib(void) { mpf_mfs_open_H(0, 222, 0, 0, MPF_MFS_READLOCK); }\n"
            ),
        }
        # write with duplicate basename under different dirs
        _write(source_root, "t-abc/src/procv/a/mod.c", files["a/mod.c"])
        _write(source_root, "t-abc/src/libx/b/mod.c", files["b/mod.c"])
        (process_root / "Makefile").write_text("SRCS = main.c\n", encoding="utf-8")

        process_file = process_root / "a" / "mod.c"
        lib_file = source_root / "t-abc" / "src" / "libx" / "b" / "mod.c"

        # value-flow runs on the process's own compilation unit (flat key, as
        # the real pipeline compiles each process from its own Makefile)
        flat_structure = {"mod.c": process_file}
        flat_trees = Preprocess().preprocess(project_structure=flat_structure)
        flat_ff = {
            name: get_local_function_definitions(code_bytes=source)
            for name, (_, source) in flat_trees.items()
        }
        flat_builder = CallGraphBuilder(
            project_structure=flat_structure,
            trees=flat_trees,
            file_functions=flat_ff,
        )
        flat_graph = flat_builder.build()
        resolver = ValueFlowResolver(
            graph=flat_graph,
            registry=flat_builder.node_registry,
            trees=flat_trees,
            project_structure={k: str(v) for k, v in flat_structure.items()},
            main_file_name="mod.c",
            function_configs=dict(SPEC["targets"]),
            macros=flat_builder.macros,
        )
        records = asyncio.run(resolver.run())

        # the shared inventory sees every file, with root-relative paths
        project_structure = {
            "a/mod.c": str(process_file),
            "b/mod.c": str(lib_file),
        }
        trees = Preprocess().preprocess(project_structure=project_structure)
        file_functions = {
            name: get_local_function_definitions(code_bytes=source)
            for name, (_, source) in trees.items()
        }
        builder = CallGraphBuilder(
            project_structure=project_structure,
            trees=trees,
            file_functions=file_functions,
        )
        graph = builder.build()
        sites = build_target_site_inventory(
            trees=trees,
            functions_identified=dict(SPEC["targets"]),
            spec=SPEC,
            project_structure={k: str(v) for k, v in project_structure.items()},
            source_root=source_root,
            process_root=process_root,
            macros=builder.macros,
        )
        facts = valueflow_records_to_facts(records, sites, SPEC, source_root, process_root)
        payloads = build_discovery_payloads(
            process_name="procv",
            source_root=source_root,
            process_root=process_root,
            target_sites=sites,
            facts=facts,
            resolver="valueflow",
            target_registry_version=SPEC["version"],
            target_registry_digest=SPEC["digest"],
        )

        # distinct root-relative paths despite identical basenames
        site_files = {s.site_file for s in sites}
        self.assertIn("t-abc/src/procv/a/mod.c", site_files)
        self.assertIn("t-abc/src/libx/b/mod.c", site_files)

        file_access = json.loads(payloads["mfs_file_access.json"])
        self.assertIn("111", file_access)
        self.assertNotIn("222", file_access)  # library call is out of process scope
        rows = _csv_rows(payloads["discovery_facts.csv"])
        lib_rows = [r for r in rows if r["target_site_file"].startswith("t-abc/src/libx/")]
        self.assertTrue(lib_rows, "out-of-scope sites remain in the evidence")

    def test_deterministic_output_and_atomic_preservation(self):
        env = self.chukyu_env()
        source_root = self.root / "chukyu"
        process_root = source_root / "t-abc" / "src" / "procv"

        index_dir = self.root / "results" / "procv" / "index"
        visualizer_graph = self.root / "results" / "visualizer" / "procv" / "runs" / "r1" / "graph.json"
        visualizer_graph.parent.mkdir(parents=True)
        original_visualizer = '{"schema_version": 1, "functions": []}'
        visualizer_graph.write_text(original_visualizer, encoding="utf-8")
        sibling_csv = self.root / "results" / "procv" / "facts.csv"
        sibling_csv.parent.mkdir(parents=True, exist_ok=True)
        original_sibling = "process_name,function_name\nx,y\n"
        sibling_csv.write_text(original_sibling, encoding="utf-8")

        write_discovery_index(
            output_dir=index_dir,
            process_name="procv",
            source_root=source_root,
            process_root=process_root,
            target_registry_version=SPEC["version"],
            target_registry_digest=SPEC["digest"],
            target_sites=env["sites"],
            facts=env["facts"],
            resolver="valueflow",
            run_id="test-run",
        )
        first = {p.name: p.read_text(encoding="utf-8") for p in index_dir.iterdir()}

        write_discovery_index(
            output_dir=index_dir,
            process_name="procv",
            source_root=source_root,
            process_root=process_root,
            target_registry_version=SPEC["version"],
            target_registry_digest=SPEC["digest"],
            target_sites=env["sites"],
            facts=env["facts"],
            resolver="valueflow",
            run_id="test-run",
        )
        second = {p.name: p.read_text(encoding="utf-8") for p in index_dir.iterdir()}

        # every artifact except the timestamped metadata is byte-identical
        for name, text in first.items():
            if name == "index_metadata.json":
                continue
            self.assertEqual(text, second[name], f"{name} not deterministic")
        meta_first = json.loads(first["index_metadata.json"])
        meta_second = json.loads(second["index_metadata.json"])
        for key in meta_first:
            if key != "generated_at":
                self.assertEqual(meta_first[key], meta_second[key])

        # pre-existing visualizer artifacts are untouched
        self.assertEqual(visualizer_graph.read_text(encoding="utf-8"), original_visualizer)
        self.assertEqual(sibling_csv.read_text(encoding="utf-8"), original_sibling)
        # no temp files left behind
        self.assertFalse(list(index_dir.glob(".*.tmp")))

        # metadata records the comparison contract
        self.assertEqual(meta_first["resolver"], "valueflow")
        self.assertEqual(meta_first["target_registry"]["version"], SPEC["version"])
        self.assertEqual(meta_first["target_registry"]["digest"], SPEC["digest"])
        self.assertEqual(meta_first["source_scope"], "per-process")

    def test_graph_matches_build_index_domain_meanings(self):
        env = self.chukyu_env()
        graph = json.loads(env["payloads"]["graph.json"])
        node_ids = {n["id"] for n in graph["nodes"]}
        self.assertIn("proc:procv", node_ids)
        self.assertIn("queue:5678", node_ids)
        self.assertIn("file:1234", node_ids)
        edge_types = {e["type"] for e in graph["edges"]}
        self.assertTrue({"READ_FILE", "WRITE_FILE", "ADDQUE", "FORKPROC"} <= edge_types)
        fork_edges = [e for e in graph["edges"] if e["type"] == "FORKPROC"]
        self.assertEqual(fork_edges[0]["target"], "proc:dyn002")
        self.assertEqual(fork_edges[0]["source"], "proc:procv")
        dynamic_edges = [e for e in graph["edges"] if e["confidence"] == "DYNAMIC_HINT"]
        self.assertEqual(len(dynamic_edges), 1)
        self.assertEqual(dynamic_edges[0]["target"], "queue:DYNAMIC")
        # one edge per call site line; the out-of-scope library fork has none
        self.assertEqual(len(fork_edges), 2)
        self.assertEqual(
            {e["line"] for e in fork_edges},
            {
                _line_of(MAIN_C, 'pmf_forkproc_H("dyn002")'),
                _line_of(MAIN_C, "pmf_forkproc_H(FORK_PKG)"),
            },
        )
        self.assertEqual(graph["meta"]["stats"]["total_nodes"], len(graph["nodes"]))
        self.assertEqual(graph["meta"]["stats"]["total_edges"], len(graph["edges"]))

    def test_hex_fno_normalises_to_decimal_key(self):
        root = self.root / "proj"
        project_structure = {
            "main.c": _write(
                root,
                "main.c",
                (
                    "void mpf_mfs_open_H(void *fcb, int fno, int a, int b, int lock);\n"
                    "int main(void) { mpf_mfs_open_H(0, 0x1003, 0, 0, MPF_MFS_READLOCK); return 0; }\n"
                ),
            ),
            "defs.h": _write(root, "defs.h", "#define MPF_MFS_READLOCK 1\n"),
        }
        resolver, trees, builder = build_valueflow_env(project_structure)
        records = asyncio.run(resolver.run())
        sites = build_target_site_inventory(
            trees=trees,
            functions_identified=dict(SPEC["targets"]),
            spec=SPEC,
            project_structure={k: str(v) for k, v in project_structure.items()},
            source_root=root,
            process_root=root,
            macros=builder.macros,
        )
        facts = valueflow_records_to_facts(records, sites, SPEC, root, root)
        payloads = build_discovery_payloads(
            process_name="proj",
            source_root=root,
            process_root=root,
            target_sites=sites,
            facts=facts,
            resolver="valueflow",
            target_registry_version=SPEC["version"],
            target_registry_digest=SPEC["digest"],
        )
        file_access = json.loads(payloads["mfs_file_access.json"])
        self.assertIn("4099", file_access)  # 0x1003
        self.assertEqual(file_access["4099"][0]["fno_raw"], "0x1003")


class SourceRootTests(unittest.TestCase):
    def test_chukyu_layout_detects_chukyu_root(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            process_root = base / "chukyu" / "t-dxi" / "src" / "dxi200d"
            process_root.mkdir(parents=True)
            self.assertEqual(resolve_source_root(process_root), base / "chukyu")

    def test_non_chukyu_layout_falls_back_to_process_root(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            process_root = base / "proj"
            process_root.mkdir()
            self.assertEqual(resolve_source_root(process_root), process_root)

    def test_explicit_root_wins(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            process_root = base / "chukyu" / "t-dxi" / "src" / "dxi200d"
            process_root.mkdir(parents=True)
            other = base / "other"
            other.mkdir()
            self.assertEqual(resolve_source_root(process_root, other), other)

    def test_rel_keeps_absolute_for_outside_files(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "root"
            root.mkdir()
            outside = base / "elsewhere"
            outside.mkdir()
            self.assertEqual(rel_to_source_root(outside, root), str(outside.resolve()).replace("\\", "/"))


class LegacyConversionTests(unittest.TestCase):
    def _combined(self, function: str, path: Path, line: str, ans, ftype="RECF"):
        return Combined.model_validate(
            {
                "process_name": "procv",
                "launch_via": "FORK",
                "call_function": "main",
                "function_name": function,
                "type": ftype,
                "call_number": -1,
                "function_name_src": {"path": str(path), "line_number": "10"},
                "target_name_src": {"path": str(path), "line_number": line},
                "target_number": {"path_str": "p", "ans": ans},
            }
        )

    def _stats(self, iterations: int = 1):
        return Stats.model_validate(
            {
                "Iterations": iterations,
                "Random_tool_calls": 0,
                "Other_tool_errors": 0,
                "Incorrect_details": [],
                "Tokens": {"Input_tokens": 5, "Output_tokens": 5, "Total_tokens": 10},
            }
        )

    def test_legacy_answers_map_to_normalized_facts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(root, "main.c", MAIN_C)
            _write(root, "defs.h", DEFS_H)
            main_path = root / "main.c"
            project_structure = {"main.c": main_path}
            trees = Preprocess().preprocess(project_structure=project_structure)

            sites = build_target_site_inventory(
                trees=trees,
                functions_identified=dict(SPEC["targets"]),
                spec=SPEC,
                project_structure={k: str(v) for k, v in project_structure.items()},
                source_root=root,
                process_root=root,
            )
            answers = {
                "mpf_mfs_open_H": [
                    (
                        self._combined(
                            "mpf_mfs_open_H", main_path, str(_line_of(MAIN_C, "int fno = JDS_FILE_FNO;") + 1), [1234], "OPENMF"
                        ),
                        self._stats(),
                    ),
                    # two branches -> two separate legacy answers, one value each
                    (
                        self._combined(
                            "mpf_mfs_open_H", main_path, str(_line_of(MAIN_C, "1111")), [1111], "OPENMF"
                        ),
                        self._stats(),
                    ),
                    (
                        self._combined(
                            "mpf_mfs_open_H", main_path, str(_line_of(MAIN_C, "2222")), [2222], "OPENMF"
                        ),
                        self._stats(),
                    ),
                ],
                "mpf_mfs_getrec": [
                    (
                        self._combined("mpf_mfs_getrec", main_path, str(_line_of(MAIN_C, "mpf_mfs_getrec(&g_fcb, 0, 3);")), [1234]),
                        self._stats(),
                    )
                ],
                "pmf_forkproc_H": [
                    (
                        self._combined("pmf_forkproc_H", main_path, str(_line_of(MAIN_C, 'pmf_forkproc_H("dyn002")')), ["dyn002"], "FORKF"),
                        self._stats(),
                    ),
                    (
                        self._combined("mpf_mfs_getrec", main_path, str(_line_of(MAIN_C, "mpf_mfs_getrec(&g_fcb, 0, 3);")), ["UNRESOLVED"]),
                        self._stats(),
                    ),
                ],
                "mpf_mfs_close": [
                    (
                        self._combined("mpf_mfs_close", main_path, str(_line_of(MAIN_C, "mpf_mfs_close(&g_fcb);")), ["NO TARGET"], "CLOSEF"),
                        self._stats(iterations=0),
                    )
                ],
            }
            facts = legacy_answers_to_facts(answers, sites, SPEC, root, root)

            by_status = {}
            for fact in facts:
                by_status.setdefault(fact.status, []).append(fact)

            exact = by_status[STATUS_EXACT]
            # open 1234 + branch 1111 + branch 2222 + getrec 1234 + fork dyn002
            self.assertEqual(len(exact), 5)
            open_fact = next(f for f in exact if f.target_function == "mpf_mfs_open_H" and f.value == "1234")
            self.assertEqual(open_fact.operation, "READ")  # lock resolved from the site
            self.assertEqual(open_fact.target_expression, "fno")
            getrec_fact = next(f for f in exact if f.target_function == "mpf_mfs_getrec")
            self.assertEqual(getrec_fact.operation, "GETREC")
            self.assertEqual(getrec_fact.link_method, "LLM")
            fork_fact = next(f for f in exact if f.target_function == "pmf_forkproc_H")
            self.assertEqual(fork_fact.resource, "forkproc")
            self.assertEqual(fork_fact.resolved_by, "LLM")

            self.assertIn(STATUS_UNRESOLVED, by_status)
            close_facts = [f for f in facts if f.target_function == "mpf_mfs_close"]
            self.assertTrue(all(f.status == STATUS_NO_TARGET for f in close_facts))
            self.assertTrue(all(f.resolved_by == "SYNTAX" for f in close_facts))

            payloads = build_discovery_payloads(
                process_name="procv",
                source_root=root,
                process_root=root,
                target_sites=sites,
                facts=facts,
                resolver="legacy",
                target_registry_version=SPEC["version"],
                target_registry_digest=SPEC["digest"],
            )
            file_access = json.loads(payloads["mfs_file_access.json"])
            self.assertEqual(len(file_access["1234"]), 2)  # open + getrec
            self.assertEqual(len(file_access["1111"]), 1)
            self.assertEqual(len(file_access["2222"]), 1)
            # sites with no legacy answer (wrapper open, MY_OPEN, 9999, second getrec)
            # remain visible as UNREACHABLE rows
            rows = _csv_rows(payloads["discovery_facts.csv"])
            self.assertTrue(any(r["status"] == STATUS_UNREACHABLE for r in rows))


if __name__ == "__main__":
    unittest.main()
