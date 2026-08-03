import csv
import json
import tempfile
import unittest
from pathlib import Path

from library_facts import (
    LibraryFactStore,
    discover_libraries,
    fact_key,
    split_path_str,
)


CSV_COLUMNS = [
    "call_number",
    "target_number->path_str",
    "target_number->ans",
    "process_name",
    "launch_via",
    "call_function",
    "function_name",
    "type",
    "function_name_src->path",
    "function_name_src->line_number",
    "target_name_src->path",
    "target_name_src->line_number",
]


def write_library_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})


def library_row(path_str: str, ans: str, api: str = "mpf_mfs_open", **overrides) -> dict:
    row = {
        "call_number": "NA",
        "target_number->path_str": path_str,
        "target_number->ans": ans,
        "process_name": "libdio",
        "launch_via": "FORK",
        "call_function": "main",
        "function_name": api,
        "type": "OPENF",
    }
    row.update(overrides)
    return row


class LibraryFactStoreTests(unittest.TestCase):
    def test_a_process_path_reuses_the_library_answer_whatever_reached_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "libdio.csv"
            write_library_csv(
                csv_path,
                [
                    library_row(
                        "[dio.c]DioGetPtr[24:56]->[dio.c:31]mpf_mfs_open[10:40]",
                        "1007",
                    )
                ],
            )
            store = LibraryFactStore()
            self.assertEqual(store.add_from_csv(csv_path, "libdio"), 1)

            # The library rooted at DioGetPtr; a process reaches it from its own
            # code, so the same node carries a call line there.
            process_path = [
                "[main.c]main[1:80]",
                "[handler.c:12]handle_input[5:60]",
                "[dio.c:88]DioGetPtr[24:56]",
                "[dio.c:31]mpf_mfs_open[10:40]",
            ]
            fact = store.lookup(process_path, "mpf_mfs_open")
            self.assertIsNotNone(fact)
            self.assertEqual(fact["ans"], [1007])
            self.assertEqual(fact["type"], "OPENF")

            # A different route into the same library call reuses it too.
            other_route = [
                "[main.c]main[1:80]",
                "[timer.c:44]on_timer[3:22]",
                "[dio.c:91]DioGetPtr[24:56]",
                "[dio.c:31]mpf_mfs_open[10:40]",
            ]
            self.assertIsNotNone(store.lookup(other_route, "mpf_mfs_open"))

    def test_unresolved_library_answers_are_never_cached(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "libdio.csv"
            write_library_csv(
                csv_path,
                [
                    # The value comes from DioGetPtr's own parameter, so the
                    # library run could not resolve it without a caller.
                    library_row(
                        "[dio.c]DioGetPtr[24:56]->[dio.c:31]mpf_mfs_open[10:40]",
                        "UNRESOLVED",
                    ),
                    library_row(
                        "[dio.c]DioOpenTrace[60:75]->[dio.c:66]mpf_mfs_open[10:40]",
                        "2003, UNRESOLVED",
                    ),
                ],
            )
            store = LibraryFactStore()
            self.assertEqual(store.add_from_csv(csv_path, "libdio"), 0)
            self.assertEqual(store.facts, {})

    def test_lookup_matches_the_shortest_suffix_and_the_right_api(self):
        store = LibraryFactStore()
        store.facts = {
            fact_key(["[dio.c]DioGetPtr[24:56]", "[dio.c:31]mpf_mfs_open[10:40]"]): {
                "function_name": "mpf_mfs_open",
                "ans": [1007],
                "call_number": -1,
                "type": "OPENF",
            },
            fact_key(
                [
                    "[dio.c]DioRead[80:99]",
                    "[dio.c:88]DioGetPtr[24:56]",
                    "[dio.c:31]mpf_mfs_open[10:40]",
                ]
            ): {
                "function_name": "mpf_mfs_open",
                "ans": [9999],
                "call_number": -1,
                "type": "OPENF",
            },
        }
        path = [
            "[main.c]main[1:80]",
            "[dio.c:70]DioRead[80:99]",
            "[dio.c:88]DioGetPtr[24:56]",
            "[dio.c:31]mpf_mfs_open[10:40]",
        ]
        # Both suffixes match; the shorter one needed less context to resolve,
        # so it is the one that generalises.
        self.assertEqual(store.lookup(path, "mpf_mfs_open")["ans"], [1007])
        # A different API never borrows another API's answer.
        self.assertIsNone(store.lookup(path, "mpf_mfs_getrec"))

    def test_labels_containing_arrows_survive_the_round_trip(self):
        path_str = (
            "[dio.c]DioGetPtr[24:56]"
            "->[dio.c:31]MFS_OPEN (macro expansion)-> mpf_mfs_open[10:40]"
        )
        labels = split_path_str(path_str)
        self.assertEqual(len(labels), 2)
        self.assertTrue(labels[1].endswith("(macro expansion)-> mpf_mfs_open[10:40]"))

    def test_saved_facts_survive_a_reload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "library_facts.json"
            store = LibraryFactStore()
            store.facts = {
                fact_key(["[dio.c]DioGetPtr[24:56]", "[dio.c:31]mpf_mfs_open[10:40]"]): {
                    "function_name": "mpf_mfs_open",
                    "ans": [1007],
                    "call_number": -1,
                    "type": "OPENF",
                }
            }
            store.save(path)
            reloaded = LibraryFactStore.load(path)
            self.assertEqual(reloaded.facts, store.facts)
            self.assertEqual(LibraryFactStore.load(Path(temp_dir) / "missing.json").facts, {})


class SnapshotLibraryMarkingTests(unittest.TestCase):
    def test_a_process_snapshot_tags_which_functions_came_from_a_library(self):
        from call_graph.data_classes import FunctionNode
        from state.state import State
        from visualizer_export import VisualizerCollector

        State().reset()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / "libdio").mkdir()
            (root / "src/main.c").write_text("int main(void){return 0;}\n", encoding="latin-1")
            (root / "libdio/dio.c").write_text("void DioGetPtr(void){}\n", encoding="latin-1")

            collector = VisualizerCollector(
                process_name="dio100d",
                process_root=root / "src",
                project_structure={
                    "main.c": str(root / "src/main.c"),
                    "dio.c": str(root / "libdio/dio.c"),
                },
                file_functions={},
                main_file_name="main.c",
                run_id="test",
                results_root=root / "results",
                library_roots={"libdio": str(root / "libdio")},
            )
            main = FunctionNode("main", "main.c", str(root / "src/main.c"))
            dio = FunctionNode("DioGetPtr", "dio.c", str(root / "libdio/dio.c"))
            registry = {node.unique_id: node for node in (main, dio)}
            collector.capture_call_graph(graph={}, registry=registry)

            by_name = {item["name"]: item for item in collector.functions.values()}
            self.assertIsNone(by_name["main"]["library"])
            self.assertEqual(by_name["DioGetPtr"]["library"], "libdio")

            graph_path = collector.write()
            snapshot = json.loads(graph_path.read_text(encoding="utf-8"))
            self.assertEqual(snapshot["process"]["kind"], "process")
        State().reset()

    def test_a_library_snapshot_says_so(self):
        from state.state import State
        from visualizer_export import VisualizerCollector

        State().reset()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            collector = VisualizerCollector(
                process_name="libdio",
                process_root=root,
                project_structure={},
                file_functions={},
                main_file_name=None,
                run_id="test",
                results_root=root / "results",
                is_library=True,
            )
            snapshot = json.loads(collector.write().read_text(encoding="utf-8"))
            self.assertEqual(snapshot["process"]["kind"], "library")
        State().reset()


class DiscoverLibrariesTests(unittest.TestCase):
    def test_lib_folders_with_sources_are_found_and_processes_are_not(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "src"
            for relative in ("dio100d", "dio110d", "libdio/src", "libDioTrace", "libdocs", "build/libjunk"):
                (root / relative).mkdir(parents=True)
            (root / "dio100d/main.c").write_text("", encoding="utf-8")
            (root / "libdio/src/dio.c").write_text("", encoding="utf-8")
            (root / "libDioTrace/trace.c").write_text("", encoding="utf-8")
            (root / "libdocs/readme.md").write_text("", encoding="utf-8")
            (root / "build/libjunk/x.c").write_text("", encoding="utf-8")

            found = {path.name for path in discover_libraries(root)}
            self.assertEqual(found, {"libdio", "libDioTrace"})


if __name__ == "__main__":
    unittest.main()
