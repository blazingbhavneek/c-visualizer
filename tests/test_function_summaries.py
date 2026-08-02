import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from function_summaries import (
    FunctionSummarizer,
    HttpWikiClient,
    PlaceholderWikiClient,
    SummaryConfig,
    dependency_layers,
    summarize_collector,
)


class RecordingSummaryClient:
    def __init__(self):
        self.names = []
        self.prompts = {}
        self.active = 0
        self.max_active = 0

    async def summarize(self, *, system, prompt):
        name = prompt.split("Function: ", 1)[1].splitlines()[0]
        self.names.append(name)
        self.prompts[name] = prompt
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return f"Summary for {name}."


class RecordingWikiClient:
    def __init__(self):
        self.questions = []

    async def ask(self, question):
        self.questions.append(question)
        return "printf writes formatted output to stdout."


def function(function_id, name):
    source = f"int {name}(void) {{ return 0; }}"
    return {
        "id": function_id,
        "name": name,
        "file": "/project/code.c",
        "start_line": 1,
        "end_line": 1,
        "is_external": False,
        "source": source,
        "source_sha256": name,
        "summary": None,
        "summary_status": "pending",
    }


class DependencyLayerTests(unittest.TestCase):
    def test_layers_are_leaf_first_and_keep_cycles_together(self):
        dependencies = {
            "main": {"middle", "cycle_a"},
            "middle": {"leaf"},
            "leaf": set(),
            "cycle_a": {"cycle_b"},
            "cycle_b": {"cycle_a"},
        }
        layers = dependency_layers(set(dependencies), dependencies)
        layer_for = {
            item: layer_index
            for layer_index, layer in enumerate(layers)
            for component in layer
            for item in component
        }
        component_for = {
            item: tuple(component)
            for layer in layers
            for component in layer
            for item in component
        }
        self.assertLess(layer_for["leaf"], layer_for["middle"])
        self.assertLess(layer_for["middle"], layer_for["main"])
        self.assertEqual(component_for["cycle_a"], component_for["cycle_b"])
        self.assertLess(layer_for["cycle_a"], layer_for["main"])

    def test_wiki_sse_parser_uses_answer_event(self):
        stream = (
            'data: {"type":"search","query":"printf"}\n\n'
            'data: {"type":"answer","text":"API manual answer","cited":[]}\n\n'
        )
        self.assertEqual(
            HttpWikiClient._parse_response(stream, "text/event-stream"),
            "API manual answer",
        )

    def test_llm_wiki_dist_json_contract_and_cold_start_retry(self):
        class Response:
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return (
                    b'{"question":"q","answer":"Manual facts",'
                    b'"cited_node_ids":[],"steps":2}'
                )

        cold_start = HTTPError(
            "http://wiki/llm-wiki/moove/api/ask",
            502,
            "not ready",
            {},
            io.BytesIO(
                b'{"detail":"LLM request failed: database starting",'
                b'"retryable":true,"code":"llm_unavailable"}'
            ),
        )
        client = HttpWikiClient(
            "http://wiki/llm-wiki/moove/api/ask", timeout_seconds=2
        )
        with patch(
            "function_summaries.urllib.request.urlopen",
            side_effect=[cold_start, Response()],
        ) as urlopen, patch("function_summaries.time.sleep"):
            answer = client._ask_sync("Explain special_api")

        self.assertEqual(answer, "Manual facts")
        self.assertEqual(urlopen.call_count, 2)
        request = urlopen.call_args_list[-1].args[0]
        self.assertEqual(
            request.full_url, "http://wiki/llm-wiki/moove/api/ask"
        )
        self.assertEqual(
            request.data,
            b'{"question": "Explain special_api"}',
        )


class FunctionSummarizerTests(unittest.IsolatedAsyncioTestCase):
    async def test_summarizes_dependencies_before_callers_and_uses_wiki(self):
        functions = {
            "main": function("main", "main"),
            "middle": function("middle", "middle"),
            "leaf": function("leaf", "leaf"),
            "sibling": function("sibling", "sibling"),
            "printf": {
                "id": "printf",
                "name": "printf",
                "is_external": True,
                "summary": None,
                "summary_status": "library",
            },
        }
        calls = {
            "1": {"source": "main", "target": "middle"},
            "2": {"source": "main", "target": "sibling"},
            "3": {"source": "middle", "target": "leaf"},
            "4": {"source": "leaf", "target": "printf"},
        }
        summary_client = RecordingSummaryClient()
        wiki_client = RecordingWikiClient()
        with tempfile.TemporaryDirectory() as temp_dir:
            summarizer = FunctionSummarizer(
                functions=functions,
                calls=calls,
                summary_client=summary_client,
                wiki_client=wiki_client,
                config=SummaryConfig(
                    enabled=True,
                    model="test-model",
                    concurrency=2,
                    use_cache=False,
                ),
                cache_path=Path(temp_dir) / "cache.json",
            )
            report = await summarizer.run()

        self.assertEqual(report["ready"], 4)
        self.assertLess(summary_client.names.index("leaf"), summary_client.names.index("middle"))
        self.assertLess(summary_client.names.index("middle"), summary_client.names.index("main"))
        self.assertIn("Summary for leaf.", summary_client.prompts["middle"])
        self.assertIn("Summary for middle.", summary_client.prompts["main"])
        self.assertEqual(len(wiki_client.questions), 1)
        self.assertIn("printf", wiki_client.questions[0])
        self.assertIn("printf writes formatted output", summary_client.prompts["leaf"])
        self.assertEqual(summary_client.max_active, 2)
        self.assertTrue(all(item["summary_status"] == "ready" for key, item in functions.items() if key != "printf"))

    async def test_configured_library_definition_is_a_wiki_enriched_leaf_boundary(self):
        functions = {
            "leaf": function("leaf", "leaf"),
            "special": {
                **function("special", "special_api"),
                "is_library_api": True,
                "summary_status": "library",
            },
        }
        calls = {"1": {"source": "leaf", "target": "special"}}
        summary_client = RecordingSummaryClient()
        wiki_client = RecordingWikiClient()
        summarizer = FunctionSummarizer(
            functions=functions,
            calls=calls,
            summary_client=summary_client,
            wiki_client=wiki_client,
            config=SummaryConfig(
                enabled=True,
                model="test-model",
                concurrency=2,
                use_cache=False,
            ),
        )
        report = await summarizer.run()

        self.assertEqual(report["functions"], 1)
        self.assertEqual(summary_client.names, ["leaf"])
        self.assertIn("special_api", wiki_client.questions[0])
        self.assertEqual(functions["special"]["summary_status"], "library")

    async def test_offline_placeholder_is_recorded_without_claiming_manual_facts(self):
        functions = {
            "leaf": function("leaf", "leaf"),
            "special": {
                "id": "special",
                "name": "special_api",
                "is_external": True,
                "summary": None,
                "summary_status": "library",
            },
        }
        summary_client = RecordingSummaryClient()
        summarizer = FunctionSummarizer(
            functions=functions,
            calls={"1": {"source": "leaf", "target": "special"}},
            summary_client=summary_client,
            wiki_client=PlaceholderWikiClient(),
            config=SummaryConfig(
                enabled=True,
                model="test-model",
                concurrency=1,
                use_cache=False,
            ),
        )
        await summarizer.run()

        self.assertEqual(functions["leaf"]["wiki_status"], "placeholder")
        self.assertIn(
            "OFFLINE LLM-WIKI PLACEHOLDER", summary_client.prompts["leaf"]
        )

    async def test_summary_config_selects_placeholder_for_offline_run(self):
        class Collector:
            def __init__(self, root):
                self.results_root = root
                self.process_name = "offline"
                self.functions = {
                    "leaf": function("leaf", "leaf"),
                    "special": {
                        "id": "special",
                        "name": "special_api",
                        "is_external": True,
                        "summary": None,
                        "summary_status": "library",
                    },
                }
                self.calls = {"1": {"source": "leaf", "target": "special"}}
                self.checkpoints = 0

            def write(self):
                self.checkpoints += 1

        with tempfile.TemporaryDirectory() as temp_dir:
            collector = Collector(Path(temp_dir))
            await summarize_collector(
                collector,
                SummaryConfig(
                    enabled=True,
                    model="test-model",
                    wiki_placeholder=True,
                    use_cache=False,
                ),
                summary_client=RecordingSummaryClient(),
            )

        self.assertEqual(collector.functions["leaf"]["wiki_status"], "placeholder")
        self.assertGreaterEqual(collector.checkpoints, 1)

    async def test_summary_pass_does_not_silently_skip_required_wiki(self):
        class Collector:
            results_root = Path("/tmp")
            process_name = "missing-wiki"
            functions = {}
            calls = {}

        with self.assertRaisesRegex(ValueError, "--wiki-url"):
            await summarize_collector(
                Collector(),
                SummaryConfig(enabled=True, model="test-model", use_cache=False),
                summary_client=RecordingSummaryClient(),
            )


if __name__ == "__main__":
    unittest.main()
