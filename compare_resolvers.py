"""Count what the legacy path enumerator would have spent against value-flow.

Legacy issues one LLM request per enumerated main-to-target path (two when the
target has a dependent open-family function).  That count is knowable without
paying for the calls, so this reports it next to the value-flow run's actual
model usage taken from its stats file.

    python compare_resolvers.py --project test_scada
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from call_graph.call_graph import orchestrate
from helpers.extract_functions_from_c import get_local_function_definitions
from helpers.Preprocess.preprocess import Preprocess, extract_all_macros, extract_includes
from makefile_resolver.makefile_resolver import return_project_mapping
from output_paths import results_root
from process_groups import load_project_state
from project_aware import identify_funs_to_trace
from state.state import State
from tools.tools import set_tool_def


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    arguments = parser.parse_args()

    project_path = arguments.project.resolve()
    json_dir = next(
        (
            candidate / "json_data"
            for candidate in (project_path, *project_path.parents)
            if (candidate / "json_data").is_dir()
        ),
        Path(__file__).resolve().parent / "json_data",
    )
    set_tool_def()
    state = load_project_state(json_dir)
    state.set("PROJECT_NAME", project_path.name)

    structure, main_files = return_project_mapping(show=False, project_path=project_path)
    structure = dict(sorted(structure.items(), key=lambda item: str(item[0])))
    state.set("PROJECT_STRUCTURE", structure)
    # preprocess() needs real Paths; trace_variable also stringifies only after.
    trees = Preprocess().preprocess(project_structure=structure)
    state.set("TREES", trees)
    structure = {key: str(value) for key, value in structure.items()}

    file_functions: dict[str, dict] = {}
    macros: dict[str, dict] = {}
    includes: dict[str, list] = {}
    main_file_name = None
    for name in list(structure):
        macros[name] = extract_all_macros(structure[name])
        includes[name] = extract_includes(structure[name])
        if name.endswith(".h"):
            continue
        functions = get_local_function_definitions(code_bytes=trees[name][1])
        if "main" in functions and any(name == item for item in main_files or []):
            main_file_name = name
        file_functions[name] = functions
    state.set("FILE_FUNCTIONS", file_functions)
    state.set("MACROS", macros)
    state.set("FILE_INCLUDES", includes)

    identified = identify_funs_to_trace(project_structure=structure, trees=trees) or {}

    rows = []
    for function, config in identified.items():
        dependents = [
            name for name in config.get("dependent_functions") or [] if name in identified
        ]
        traced = orchestrate(
            project_strcuture=structure,
            trees=trees,
            required_func=function,
            main_file_name=main_file_name,
            function_pointer_args=state.get("FUNCTION_POINTER_ARGS"),
            file_functions=file_functions,
            return_whole_tree=False,
        )
        paths = traced[1] if traced else []
        unique = {"->".join(item[0][0]) for item in paths}
        invocations = {
            (
                str(getattr(item[1].get("target_name_src"), "path", "?")),
                str(getattr(item[1].get("target_name_src"), "line_number", "?")),
            )
            for item in paths
        }
        # Legacy sends one request per path, plus a second for the dependent
        # open-family lookup when one is configured.
        per_path = 2 if dependents and dependents[0] != function else 1
        rows.append(
            {
                "function": function,
                "paths": len(paths),
                "unique_paths": len(unique),
                "invocations": len(invocations),
                "legacy_llm_calls": len(paths) * per_path,
            }
        )

    stats_path = results_root() / "stats" / f"{project_path.name}_VALUEFLOW_STATS.json"
    actual = json.loads(stats_path.read_text()) if stats_path.is_file() else {}

    print(f"\n{'function':22} {'paths':>7} {'unique':>7} {'invoc':>7} {'legacy LLM':>11}")
    print("-" * 60)
    for row in sorted(rows, key=lambda item: -item["legacy_llm_calls"]):
        print(
            f"{row['function']:22} {row['paths']:>7} {row['unique_paths']:>7} "
            f"{row['invocations']:>7} {row['legacy_llm_calls']:>11}"
        )
    print("-" * 60)
    legacy_total = sum(row["legacy_llm_calls"] for row in rows)
    print(f"{'TOTAL':22} {sum(r['paths'] for r in rows):>7} "
          f"{sum(r['unique_paths'] for r in rows):>7} "
          f"{sum(r['invocations'] for r in rows):>7} {legacy_total:>11}")

    if actual:
        used = actual.get("llm_query_count", 0)
        print(
            f"\nvalue-flow actual model calls: {used}"
            f"   (seeds {actual.get('seed_count')}, facts {actual.get('fact_count')},"
            f" queries answered {actual.get('answered_query_count')})"
        )
        print(f"value-flow tokens: {actual.get('Tokens')}")
        if used:
            print(f"reduction: {legacy_total} -> {used}  ({legacy_total / used:.0f}x fewer calls)")
        else:
            print(f"reduction: {legacy_total} -> 0 model calls (all resolved syntactically)")
    else:
        print(f"\nNo value-flow stats at {stats_path}; run the valueflow resolver first.")


if __name__ == "__main__":
    main()
