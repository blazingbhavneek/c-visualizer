"""Corpus, trace-label and structural-answer invariants.

These run against the real snapshots in `results/csv_results` rather than a
hand-written fixture: the properties asserted here are properties *of the
exporter's output*, and a fixture would drift from it silently.  Without a
snapshot the whole module skips.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from wiki import graphops as G
from wiki import structural
from wiki.corpus import load_corpus, newest_runs

RESULTS_ROOT = REPO_ROOT / "results" / "csv_results"


class WikiGraphTestCase(unittest.TestCase):
    """One corpus load shared by every test; ~1100 functions, so not per-test."""

    corpus = None

    @classmethod
    def setUpClass(cls):
        if not (RESULTS_ROOT / "visualizer").is_dir():
            raise unittest.SkipTest("no visualizer snapshots present")
        runs = newest_runs(RESULTS_ROOT)
        if not runs:
            raise unittest.SkipTest("no visualizer runs present")
        cls.corpus = load_corpus(RESULTS_ROOT, runs)


class TestCorpusJoin(WikiGraphTestCase):
    def test_shared_library_functions_merge_across_processes(self):
        """`scf_stubs.c` is linked into every process and hashes to one id.

        The exporter keys a function id on its definition path, so the shared
        daemon stubs collapse to a single id seen by many processes.  Code that
        assumes one id means one process silently invents call edges.
        """
        stub = self.corpus.resolve_name("scf_hist_save")
        self.assertIsNotNone(stub)
        self.assertGreater(len(stub.processes), 1)

        scoped = self.corpus.incoming(stub.id, stub.processes[0])
        everywhere = self.corpus.incoming(stub.id)
        self.assertLess(len(scoped), len(everywhere), "per-process edges must not be merged")

    def test_every_call_edge_stays_inside_one_process(self):
        for call in self.corpus.calls:
            snapshot = self.corpus.processes[call.process]
            self.assertIn(call.source, snapshot.function_ids)
            self.assertIn(call.target, snapshot.function_ids)

    def test_resources_join_on_kind_and_name(self):
        shared = [item for item in self.corpus.resources.values() if len(item.processes) > 1]
        self.assertTrue(shared, "expected at least one cross-process daemon resource")
        for resource in self.corpus.resources.values():
            self.assertEqual(resource.key, f"{resource.kind} {resource.name}")


class TestInteractionAttribution(WikiGraphTestCase):
    def test_interactions_are_not_all_credited_to_main(self):
        """The exporter attributes every interaction to `main`.

        Its call-site match usually misses and falls back to `call_function`,
        so all 240 rows land on the six `main`s and "what does bo_hist_audit
        touch" answers "nothing".  `Corpus._attribute` recovers the real caller
        from the interaction's own path.
        """
        attributed = {
            interaction.function_id
            for interaction in self.corpus.interactions
            if interaction.function_id
        }
        self.assertGreater(len(attributed), 20, "attribution collapsed back onto main")

        origins = {
            interaction.origin_function_id
            for interaction in self.corpus.interactions
            if interaction.origin_function_id
        }
        self.assertGreater(len(attributed), len(origins))

    def test_a_direct_api_caller_gets_its_own_resources(self):
        target = self.corpus.resolve_name("bo_hist_audit", "proc_boiler")
        if target is None:
            self.skipTest("fixture function not present")
        self.assertTrue(
            G.resources_for_function(self.corpus, target.id),
            "bo_hist_audit calls scf_hist_save, so it must carry a resource",
        )

    def test_macro_chains_credit_the_writer_not_the_macro(self):
        """In `... -> bo_on_scan -> RAISE_ALARM -> scf_alarmq_enq` the code that
        writes the queue is `bo_on_scan`; `RAISE_ALARM` is an external macro."""
        macro = self.corpus.resolve_name("RAISE_ALARM")
        if macro is None:
            self.skipTest("fixture macro not present")
        credited = {
            interaction.function_id
            for interaction in self.corpus.interactions
            if interaction.function_id
        }
        self.assertNotIn(macro.id, credited)

    def test_every_interaction_path_parses(self):
        from wiki.labels import parse_path, split_path

        broken = [
            interaction.path
            for interaction in self.corpus.interactions
            if interaction.path
            and len(parse_path(interaction.path)) != len(split_path(interaction.path))
        ]
        self.assertEqual(broken, [], f"unparseable interaction path: {broken[:2]}")


class TestTraceLabelGrammar(WikiGraphTestCase):
    def test_every_trace_label_parses(self):
        unparsed = [
            label
            for trace in self.corpus.traces
            for label in trace.labels
            if G.parse_trace_label(label) is None
        ]
        self.assertEqual(unparsed, [], f"unhandled label form: {unparsed[:3]}")

    def test_every_trace_step_resolves_to_a_function(self):
        missing = []
        for trace in self.corpus.traces:
            path = G.resolve_trace(self.corpus, trace)
            if path is None:
                continue
            missing.extend(step.name for step in path.steps if step.function_id is None)
        self.assertEqual(missing, [], f"unresolved trace steps: {missing[:5]}")

    def test_callback_label_range_belongs_to_the_api_not_the_callback(self):
        """The subtle one.

        In `[scf_stubs.c:332]scf_evt_register (accepts callback)-> bo_on_trip[39:39]`
        the trailing `[39:39]` is `scf_evt_register`'s definition range.
        `bo_on_trip` is defined at `[748:771]` and appears as its own next
        label.  Reading the range as the callback's both mis-attributes the
        line numbers and double-counts the hop.
        """
        parsed = G.parse_trace_label(
            "[scf_stubs.c:332]scf_evt_register (accepts callback)-> bo_on_trip[39:39]"
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.name, "scf_evt_register")
        self.assertEqual((parsed.def_start, parsed.def_end), (39, 39))
        self.assertEqual(parsed.target, "bo_on_trip")
        self.assertEqual(parsed.relation, "callback")
        self.assertEqual(parsed.call_line, 332)

    def test_macro_label_has_no_file_or_range(self):
        parsed = G.parse_trace_label("[413]RAISE_ALARM (macro expansion)-> scf_alarmq_enq")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.name, "RAISE_ALARM")
        self.assertIsNone(parsed.file_name)
        self.assertEqual(parsed.target, "scf_alarmq_enq")
        self.assertEqual(parsed.relation, "macro")
        self.assertEqual(parsed.call_line, 413)

    def test_indirection_hops_are_typed(self):
        """A callback or macro hop must never be reported as a plain call."""
        kinds: set[str] = set()
        for trace in self.corpus.traces:
            path = G.resolve_trace(self.corpus, trace)
            if path:
                kinds.update(step.kind for step in path.steps)
        self.assertTrue({"callback", "registers_callback"} <= kinds)
        self.assertTrue({"macro_expansion", "expands_macro"} <= kinds)


class TestTraversal(WikiGraphTestCase):
    def _boiler_pair(self):
        entry = self.corpus.processes["proc_boiler"].entry_function_id
        target = self.corpus.resolve_name("bo_shed_load", "proc_boiler")
        if entry is None or target is None:
            self.skipTest("fixture process not present")
        return entry, target

    def test_call_paths_are_shortest_first(self):
        entry, target = self._boiler_pair()
        paths = G.call_paths(self.corpus, entry, target.id, process="proc_boiler")
        self.assertTrue(paths)
        lengths = [len(path.steps) for path in paths]
        self.assertEqual(lengths, sorted(lengths))

    def test_call_paths_do_not_revisit_a_function(self):
        entry, target = self._boiler_pair()
        for path in G.call_paths(self.corpus, entry, target.id, process="proc_boiler"):
            ids = path.function_ids
            self.assertEqual(len(ids), len(set(ids)))


class TestStructuralRouter(WikiGraphTestCase):
    def test_ambiguous_main_resolves_within_the_asked_process(self):
        """Regression: six processes define `main`.

        Resolving by name alone picked `proc_waterworks`, so a question about a
        `proc_boiler` function searched between unrelated processes and
        reported a confident "no path exists".
        """
        self.assertGreater(len(self.corpus.by_name("main")), 1)

        answer = structural.answer(
            self.corpus, "main から bo_shed_load へはどう到達しますか", lang="ja"
        )
        self.assertIsNotNone(answer)
        self.assertEqual(answer.intent, "reach")
        self.assertTrue(answer.payload["paths"], "expected a path once main is scoped")
        for path in answer.payload["paths"]:
            self.assertEqual(path["process"], "proc_boiler")

    def test_structural_intents(self):
        cases = [
            ("bo_shed_load を呼ぶのはどの関数ですか", "callers"),
            ("who calls scf_hist_save", "callers"),
            ("bo_on_trip は何を呼んでいますか", "callees"),
            ("event 3001 に書き込むのはどれですか", "resource_writers"),
            ("who reads event 3001", "resource_readers"),
            ("bo_on_trip とは何ですか", "define"),
        ]
        for question, intent in cases:
            with self.subTest(question=question):
                answer = structural.answer(self.corpus, question, lang="ja")
                self.assertIsNotNone(answer, f"expected a structural hit for {question!r}")
                self.assertEqual(answer.intent, intent)
                self.assertTrue(answer.payload["cited"])

    def test_research_questions_fall_through_to_the_agent(self):
        for question in (
            "ボイラーの燃焼効率はどのように計算されますか",
            "このシステムの全体構成を説明して",
            "why was the trip logic written this way",
        ):
            with self.subTest(question=question):
                self.assertIsNone(structural.answer(self.corpus, question, lang="ja"))

    def test_unreached_target_is_reported_as_uncalled_not_unrouted(self):
        """"No path from main" and "nothing calls this" are different findings."""
        target = self.corpus.resolve_name("analyze_flue_gas_composition", "proc_boiler")
        if target is None:
            self.skipTest("fixture function not present")
        self.assertEqual(G.callers(self.corpus, target.id), [])

        answer = structural.answer(
            self.corpus, "how does main reach analyze_flue_gas_composition", lang="en"
        )
        self.assertIsNotNone(answer)
        self.assertIn("no recorded caller", answer.payload["text"].lower())


class TestAnswerPayload(WikiGraphTestCase):
    def test_payload_matches_the_frontend_contract(self):
        payload = structural.answer(
            self.corpus, "bo_shed_load を呼ぶのはどの関数ですか", lang="ja"
        ).payload

        self.assertLessEqual({"text", "cited", "paths", "resources", "stats"}, set(payload))
        for citation in payload["cited"]:
            self.assertLessEqual(
                {
                    "id", "name", "process", "file", "file_name",
                    "start_line", "end_line", "summary", "source",
                },
                set(citation),
            )
        for path in payload["paths"]:
            self.assertLessEqual({"id", "label", "process", "origin", "steps"}, set(path))
            for step in path["steps"]:
                self.assertLessEqual(
                    {"function_id", "name", "file_name", "line", "kind", "via"}, set(step)
                )

    def test_paths_are_folded_into_citations(self):
        """Every function on a clickable path must appear in the rail."""
        payload = structural.answer(
            self.corpus, "main から bo_shed_load へはどう到達しますか", lang="ja"
        ).payload
        cited = {item["id"] for item in payload["cited"]}
        for path in payload["paths"]:
            for step in path["steps"]:
                if step["function_id"]:
                    self.assertIn(step["function_id"], cited)

    def test_citation_source_is_line_numbered_from_the_definition(self):
        payload = structural.answer(self.corpus, "bo_on_trip とは何ですか", lang="ja").payload
        citation = next(item for item in payload["cited"] if item["name"] == "bo_on_trip")
        first = citation["source"].splitlines()[0]
        self.assertTrue(first.strip().startswith(str(citation["start_line"])))


if __name__ == "__main__":
    unittest.main()
