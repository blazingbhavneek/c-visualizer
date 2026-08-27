"""CPU-only tests for the bounded valueflow seed scheduler.

These tests use fake async LLM callbacks and cooperative asyncio events only.
They never contact OpenAI, Ollama, vLLM, llm-wiki, or any external endpoint.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from call_graph.call_graph import CallGraphBuilder
from helpers.Preprocess.preprocess import Preprocess
from helpers.extract_functions_from_c import get_local_function_definitions
from value_flow.queries import OneHopAnswer
from value_flow.resolver import ValueFlowResolver


class ValueFlowSchedulerTests(unittest.TestCase):
    def build_resolver(
        self,
        root: Path,
        files: dict[str, str],
        configs: dict,
        *,
        callbacks: dict | None = None,
        one_hop=None,
        return_use=None,
        path_cap: int = 100,
        cache_path: Path | None = None,
        llm_concurrency: int = 1,
        main_file_name: str = "main.c",
        entry_function_name: str = "main",
        entry_points: list[tuple[str, str]] | None = None,
    ) -> ValueFlowResolver:
        project_structure = {}
        for name, source in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="latin-1")
            project_structure[name] = path
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
        for name, source in files.items():
            macros = {}
            for line in source.splitlines():
                parts = line.strip().split(maxsplit=2)
                if len(parts) == 3 and parts[:1] == ["#define"]:
                    macros[parts[1]] = parts[2]
            file_macros[name] = macros
        return ValueFlowResolver(
            graph=graph,
            registry=builder.node_registry,
            trees=trees,
            project_structure={
                key: str(value) for key, value in project_structure.items()
            },
            main_file_name=main_file_name,
            entry_function_name=entry_function_name,
            entry_points=entry_points,
            function_configs=configs,
            macros=builder.macros,
            file_macros=file_macros,
            one_hop_resolver=one_hop,
            return_use_resolver=return_use,
            path_cap=path_cap,
            cache_path=cache_path,
            llm_concurrency=llm_concurrency,
        )

    def test_bounded_llm_concurrency_is_never_exceeded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            active = 0
            peak = 0

            async def one_hop(site, index, expression):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                for _ in range(5):
                    await asyncio.sleep(0)
                active -= 1
                return None

            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "main.c": (
                        "void target(int value);\n"
                        "int main(void) {\n"
                        "  int a; int b; int c; int d; int e;\n"
                        "  target(a); target(b); target(c); target(d); target(e);\n"
                        "  return 0;\n"
                        "}\n"
                    )
                },
                {
                    "target": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    }
                },
                one_hop=one_hop,
                llm_concurrency=2,
            )

            records = asyncio.run(resolver.run())

            self.assertEqual(len(resolver.seeds), 5)
            self.assertGreaterEqual(peak, 2)
            self.assertLessEqual(peak, 2)
            self.assertEqual(len(records), 5)

    def test_cpu_seed_progresses_while_llm_request_is_pending(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            hold = asyncio.Event()
            active = 0
            completed: list[int] = []

            async def one_hop(site, index, expression):
                nonlocal active
                active += 1
                try:
                    await hold.wait()
                finally:
                    active -= 1
                return None

            def progress(seed, rows, seconds):
                completed.append(seed.site.line)

            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "main.c": (
                        "void target(int value);\n"
                        "int main(void) {\n"
                        "  int a;\n"
                        "  target(a);\n"
                        "  target(9);\n"
                        "  return 0;\n"
                        "}\n"
                    )
                },
                {
                    "target": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    }
                },
                one_hop=one_hop,
                llm_concurrency=2,
            )
            resolver.progress = progress
            llm_line = resolver.seeds[0].site.line
            syntax_line = resolver.seeds[1].site.line

            async def scenario():
                nonlocal active
                run_task = asyncio.create_task(resolver.run())
                try:
                    # Yield (no wall-clock waits) until the held LLM callback
                    # is active, then keep yielding until the purely
                    # syntactic seed reports progress.  The held seed cannot
                    # complete before `hold` is set, so any progress at this
                    # point must be the syntax-only seed.
                    while not active:
                        await asyncio.sleep(0)
                    while syntax_line not in completed:
                        await asyncio.sleep(0)
                    self.assertNotIn(llm_line, completed)
                    hold.set()
                    return await run_task
                finally:
                    hold.set()

            records = asyncio.run(scenario())

            self.assertEqual(sorted(completed), [llm_line, syntax_line])
            self.assertEqual(
                {record.fact.value for record in records}, {"9", "a"}
            )

    def test_shared_query_still_resolves_once_for_multiple_seeds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            calls: list[str] = []

            async def one_hop(site, index, expression):
                calls.append(expression)
                return OneHopAnswer(kind="VALUE", value="999")

            # Both target seeds trace the same wrapper parameter, so they
            # share one ParamQuery -> one ArgQuery in main -> one LLM answer.
            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "main.c": (
                        "void target1(int value);\n"
                        "void target2(int value);\n"
                        "void wrapper(int value) { target1(value); target2(value); }\n"
                        "int main(void) { int who; wrapper(who); return 0; }\n"
                    )
                },
                {
                    "target1": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    },
                    "target2": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    },
                },
                one_hop=one_hop,
                llm_concurrency=2,
            )

            records = asyncio.run(resolver.run())

            self.assertEqual(calls, ["who"])
            self.assertEqual(
                {record.fact.value for record in records}, {"999"}
            )
            self.assertTrue(
                all(record.fact.resolved_by == "LLM" for record in records)
            )

    def test_callback_failure_does_not_deadlock_the_scheduler(self):
        source = {
            "main.c": (
                "void target(int value);\n"
                "int main(void) {\n"
                "  int a; int b;\n"
                "  target(a); target(b);\n"
                "  return 0;\n"
                "}\n"
            )
        }
        configs = {
            "target": {
                "type": "READF",
                "indices": [1],
                "dependent_functions": [],
            }
        }

        def raising_callback(site, index, expression):
            raise RuntimeError("model exploded")

        def none_callback(site, index, expression):
            return None

        for label, callback in (
            ("raises", raising_callback),
            ("returns_none", none_callback),
        ):
            with self.subTest(callback=label), tempfile.TemporaryDirectory() as temp_dir:
                resolver = self.build_resolver(
                    Path(temp_dir),
                    source,
                    configs,
                    one_hop=callback,
                    llm_concurrency=2,
                )

                async def scenario():
                    records = await resolver.run()
                    pending = [
                        task
                        for task in asyncio.all_tasks()
                        if task is not asyncio.current_task() and not task.done()
                    ]
                    self.assertEqual(pending, [])
                    return records

                records = asyncio.run(scenario())

                self.assertEqual(len(records), 2)
                self.assertEqual(
                    {record.fact.origin_kind for record in records},
                    {"EXTERNAL_DATA"},
                )

    def test_unexpected_worker_failures_propagate_without_deadlock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "main.c": (
                        "void target(int value);\n"
                        "int main(void) {\n"
                        "  int a; int b; int c; int d;\n"
                        "  target(a); target(b); target(c); target(d);\n"
                        "  return 0;\n"
                        "}\n"
                    )
                },
                {
                    "target": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    }
                },
                llm_concurrency=2,
            )

            async def fail_seed(seed):
                raise RuntimeError("synthetic resolver failure")

            resolver._resolve_seed = fail_seed

            async def scenario():
                with self.assertRaisesRegex(
                    RuntimeError, "synthetic resolver failure"
                ):
                    await asyncio.wait_for(resolver.run(), timeout=1.0)

                pending = [
                    task
                    for task in asyncio.all_tasks()
                    if task is not asyncio.current_task() and not task.done()
                ]
                self.assertEqual(pending, [])

            asyncio.run(scenario())

    def test_result_order_follows_original_seed_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            hold = asyncio.Event()
            completed: list[int] = []
            persist_state: dict[str, object] = {}

            async def one_hop(site, index, expression):
                await hold.wait()
                return None

            def progress(seed, rows, seconds):
                completed.append(seed.site.line)

            resolver = self.build_resolver(
                Path(temp_dir),
                {
                    "main.c": (
                        "void target(int value);\n"
                        "int main(void) {\n"
                        "  int a;\n"
                        "  target(a);\n"
                        "  target(9);\n"
                        "  return 0;\n"
                        "}\n"
                    )
                },
                {
                    "target": {
                        "type": "READF",
                        "indices": [1],
                        "dependent_functions": [],
                    }
                },
                one_hop=one_hop,
                llm_concurrency=2,
            )
            resolver.progress = progress
            original_order = [seed.site.line for seed in resolver.seeds]
            self.assertEqual(original_order[0] < original_order[1], True)
            resolver.persist_cache = lambda: persist_state.setdefault(
                "completed", len(completed)
            )

            async def scenario():
                run_task = asyncio.create_task(resolver.run())
                try:
                    while not completed:
                        await asyncio.sleep(0)
                    first = list(completed)
                    hold.set()
                    records = await run_task
                    return first, records
                finally:
                    hold.set()

            first, records = asyncio.run(scenario())

            # The literal seed (line 5) finished first, yet records must be
            # ordered by original seed order, not completion order.
            self.assertEqual(first, [original_order[1]])
            self.assertEqual(
                [record.seed.site.line for record in records], original_order
            )
            # The cache is persisted exactly once, only after the last seed
            # finished.
            self.assertEqual(persist_state.get("completed"), len(resolver.seeds))


if __name__ == "__main__":
    unittest.main()
