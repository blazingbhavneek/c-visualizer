# Value-flow CPU/LLM overlap plan

## Objective

Reduce wall-clock time in the `--resolver valueflow` path by allowing CPU-side
valueflow work and blocking LLM work to make progress at the same time.

The implementation must be deliberately small. Preserve the current resolver
semantics, cache format, provenance, output files, target inventory, and
legacy resolver behavior. The first implementation should improve the overlap
after the complete structural inputs are available; it must not attempt a
speculative LLM answer from an incomplete call graph.

## Scope and non-goals

Change only these files in the first implementation:

- `value_flow/resolver.py`
- `project_aware.py`
- `tests/test_value_flow.py` or a new `tests/test_valueflow_scheduler.py`

Do not change these files for this speedup:

- `make_llm_calls_for_function` or the legacy branch in `project_aware.py`
- `helpers/Preprocess/preprocess.py`
- `parser/parser_files.py`
- anything under `call_graph/`
- `discovery_index.py`, `value_flow/outputs.py`, or output schemas
- LLM prompts, response models, cache schema, or CLI flags

Do not add a `ProcessPoolExecutor` around `ValueFlowResolver`. The resolver
mutates shared dictionaries (`results`, `in_flight`, `provenance`, query
labels, and caches), and Tree-sitter objects plus `State()` are not a safe
boundary for process-pool serialization. The existing `run_with_retry()`
already creates a child process for each blocking model call.

Do not make the constructor/indexer partially visible to resolution. A target
must not be resolved while its caller, parameter, handle, callback, or
reachability indexes are incomplete. That would make a missing index entry
look like an external value and change results.

## Current bottleneck to preserve as a correctness boundary

The current order is:

```text
Preprocess every source file
  -> build complete call graph
  -> identify targets and build discovery inventory
  -> ValueFlowResolver.__init__ builds all resolver indexes
  -> ValueFlowResolver.run() resolves seeds and calls the LLM
  -> write final outputs
```

The relevant locations are:

- `project_aware.py:2243`: whole-project preprocessing.
- `project_aware.py:2336`: complete call-graph construction.
- `project_aware.py:2484`: entry into valueflow.
- `value_flow/resolver.py:371-385`: synchronous resolver indexing.
- `value_flow/resolver.py:1546-1557`: current all-seed `asyncio.gather()`.
- `project_aware.py:1685-1718`: synchronous context extraction for an LLM
  prompt.
- `project_aware.py:1743`, `1768`, `1835`, and `1876`: blocking LLM calls
  currently run through the default `asyncio.to_thread()` executor.

The first change should not pretend that moving the resolver constructor to a
thread creates overlap: no LLM request can be safely submitted until the
indexes and reachable seeds exist. The useful minimal change is to make the
post-index resolution phase a bounded producer/consumer pipeline and keep
CPU context preparation out of the executor that waits for model processes.

## Design

### 1. Keep one coordinator for resolver state

`ValueFlowResolver` remains owned by one asyncio event loop. Its existing
`resolve()` method, query deduplication, `asyncio.Future` values in
`in_flight`, provenance updates, cache reads/writes, and result objects remain
in that coordinator.

Do not call `_resolve_seed()` directly from a `ThreadPoolExecutor`. It is an
async recursive state machine, not a pure function.

The coordinator may yield while a model request is pending. During that yield,
other seed tasks can perform their CPU-side work and submit their own LLM
requests. This is the intended overlap.

### 2. Replace unbounded seed gathering with a bounded queue

In `value_flow/resolver.py`, replace the body of `ValueFlowResolver.run()`
with a small bounded seed scheduler.

Required behavior:

1. Preserve the original seed order for final records.
2. Put seed indices and seeds into an `asyncio.Queue` with a finite size.
3. Start a bounded number of async seed workers. A reasonable initial value is
   `max(2, min(len(self.seeds), self.llm_concurrency * 2))`; do not add a new
   public setting in this change.
4. Each worker awaits the existing `_resolve_seed(seed)` and stores its rows in
   `rows_by_seed[index]`.
5. Call `self.progress` when a seed completes, as today. Completion order may
   be out of order for progress output.
6. After all workers finish, flatten `rows_by_seed` in original seed order,
   call `persist_cache()` once, and return
   `_deduplicate_records(records)` exactly as today.
7. Use a `try/finally` or explicit cancellation path so an exception cancels
   workers and does not leave queue tasks or unresolved tasks alive.

The queue is for bounded scheduling and live progress; it must not change the
valueflow algorithm. Keep the existing `resolve()` in-flight deduplication and
LLM semaphore. A shared subquery must still result in one computation and one
future, even when multiple seeds request it at the same time.

Do not emit final facts in completion order. The output order must remain
stable for tests, cache diagnostics, and human comparison.

### 3. Give CPU prompt preparation its own executor

In `project_aware.py`, inside `make_value_flow_calls()`, create a dedicated,
bounded `ThreadPoolExecutor` for the synchronous prompt-context work. Use a
small derived limit, for example:

```python
context_workers = min(4, max(1, os.cpu_count() or 1))
```

Do not expose this as a CLI option yet. The first change should not create a
new tuning surface.

The executor is appropriate here because the main goal is to keep prompt
construction from blocking the event loop while model processes are running.
Tree-sitter parsing and the existing source slicing are partly native/I/O
work; a process pool is not safe for the resolver state.

Add a small async helper local to `make_value_flow_calls()` that invokes the
existing synchronous `context_for(site, get_upper=...)` through
`loop.run_in_executor(context_executor, ...)`. Use `functools.partial` if
needed to preserve the keyword-only argument. Do not rewrite `parseFiles` or
change its output.

Use this helper in exactly these three callbacks:

- `resolve_one_hop()`
- `resolve_return_use()`
- `resolve_handle_with_llm()`

The callbacks must continue to return the same models/strings and must still
return `None` when no path/context is available.

### 4. Give blocking model waits their own executor

Also in `make_value_flow_calls()`, create a dedicated LLM wait executor with
`max_workers=llm_concurrency` (or the same validated positive value passed to
the resolver).

Replace the four `asyncio.to_thread(run_with_retry, ...)` calls in the valueflow
callbacks with `loop.run_in_executor(llm_executor, ...)` using the existing
`run_with_retry` function and exactly the same arguments.

Do not change:

- retry count or timeout;
- child-process behavior in `run_with_retry`;
- prompt functions;
- model validation/parsing;
- endpoint probing;
- the meaning of `llm_concurrency`.

The existing `ValueFlowResolver._llm_gate` remains the correctness/backpressure
limit. The executor is a separate resource boundary so CPU context work does
not queue behind threads that are blocked in `process.join(timeout)`. It is
acceptable for the semaphore and executor size to enforce the same upper
bound.

Keep all stats aggregation on the asyncio coordinator. `record_stats()` must
only be called after the executor future has returned, as it is today; do not
mutate `token_totals` or `query_stats` from executor threads.

### 5. Shut executors down on success and failure

Wrap resolver execution and callback lifetime in `try/finally` so both
executors are shut down even if a resolver exception escapes.

Requirements:

- Do not shut down the executors before `await resolver.run()` completes.
- On normal completion, wait for submitted work to finish.
- On failure, cancel queued work where supported, then wait for already-running
  `run_with_retry` calls to exit. Do not terminate the existing child-process
  retry logic from a new code path.
- Preserve the original exception after cleanup.

If the implementation makes executor lifetime awkward because callbacks are
closures, keep the executors local to `make_value_flow_calls()` and place
cleanup around the smallest region that includes `await resolver.run()`.

### 6. Keep the LLM gate semantics explicit

`_await_llm()` currently wraps the injected callback with
`asyncio.Semaphore(self.llm_concurrency)`. Keep this gate in the first pass;
it protects all three LLM callback types and existing unit-test behavior.

The callback should now have this shape conceptually:

```text
await CPU executor: build context
await resolver LLM gate: invoke callback
    await dedicated LLM executor: run_with_retry()
return parsed answer to event loop
```

Do not hold a CPU semaphore while awaiting the model. Do not introduce a
second nested queue that can deadlock waiting for a CPU worker held by a model
future.

If profiling after this change proves that context generation occupies a
material portion of the LLM gate, make that a separate follow-up: split the
resolver callback contract into `prepare_prompt()` and `run_model()` so the
gate surrounds only `run_model()`. Do not make that contract change in the
minimal implementation unless tests demonstrate it is necessary.

## Exact implementation sequence

### Step 1: Add scheduler tests before changing behavior

Add focused CPU-only tests in `tests/test_valueflow_scheduler.py` or append
them to `tests/test_value_flow.py`.

Use fake async callbacks and `asyncio.Event`/small cooperative awaits. Do not
contact OpenAI, Ollama, vLLM, llm-wiki, or any external endpoint.

Required tests:

1. **Bounded LLM concurrency**

   Build a resolver with several unresolved target seeds and a fake one-hop
   callback that increments an active counter, yields, then decrements it.
   Run with `llm_concurrency=2` and assert the peak counter never exceeds 2.

2. **CPU progress while an LLM request is pending**

   Build at least two seeds: one that reaches the fake LLM callback and holds
   on an event, and one that resolves syntactically. Assert the syntactic
   seed can complete/progress before releasing the held LLM event. This test
   must be deterministic and must not use wall-clock sleeps as its proof.

3. **Shared-query deduplication remains intact**

   Create multiple seeds that reach the same reverse-tracing query. Assert the
   fake callback is invoked once and all consumers receive the same result.

4. **Failure does not deadlock the queue**

   Make the fake callback raise or return `None`. Assert `resolver.run()`
   completes, produces the same unresolved/external-style fact as before, and
   all scheduler tasks finish.

5. **Deterministic result order**

   Make later seeds finish first. Assert returned records are still ordered by
   original seed order before normal deduplication.

Do not weaken existing assertions to make the scheduler tests pass. Existing
syntax-only tests are part of the contract.

### Step 2: Implement the bounded `run()` scheduler

Change only `ValueFlowResolver.run()` and, if useful, add one private helper
near it. Keep `_resolve_seed()` unchanged initially.

Run the resolver unit tests after this step. If behavior changes before adding
executors, stop and fix the scheduler rather than combining debugging of both
changes.

### Step 3: Add the two executors in `make_value_flow_calls()`

Add imports for `ThreadPoolExecutor` and `functools.partial` only if needed.
Create the executors after `llm_concurrency` has been validated and before
callbacks can be invoked.

Refactor only the three valueflow callbacks listed above. Keep the prompt
arguments and response parsing textually equivalent wherever possible.

Use `loop.run_in_executor()` rather than `asyncio.to_thread()` so the CPU and
LLM waits cannot consume the same default executor.

After this step, run the CPU-only pipeline tests before attempting any live
LLM test.

### Step 4: Add cleanup and preserve stats/output behavior

Ensure executor cleanup runs for:

- syntax-only runs where no LLM callback is installed;
- LLM-ready runs with zero seeds;
- normal successful runs;
- callback failure;
- resolver failure during indexing or resolution.

Do not write partial `facts.csv`, `paths.csv`, `run_stats.json`, or discovery
indexes from worker threads. The existing final output barrier remains. Live
progress is provided by the existing `progress` callback and console output.

### Step 5: Add only minimal diagnostics if needed

If timing verification needs instrumentation, prefer local timing variables or
test monkeypatches. Do not change the public run-stat schema in this speedup.
The existing `wall_seconds`, `llm_query_count`, and token totals must retain
their current meanings.

## Verification checklist

Run these commands from the repository root:

```bash
python -m compileall project_aware.py value_flow tests
python -m pytest tests/test_value_flow.py tests/test_valueflow_scheduler.py
python -m pytest tests/test_valueflow_pipeline.py tests/test_no_target_pipeline.py tests/test_resolver_parity.py
```

If the new test file is not created, omit it from the command. Then run the
full CPU-only suite:

```bash
python -m pytest
```

The test environment must not require a live model. If a test reaches
`llm_endpoint_status()`, patch it or configure the test exactly as existing
tests do so the fake callback is used and no network call occurs.

For the syntax-only pipeline fixture, verify all of the following remain true:

- one literal target still produces one exact fact;
- macro/enum/parameter resolution still avoids the LLM callback;
- handle binding still uses exact variable matching;
- unresolved and ambiguous handles are not converted into nearby-open guesses;
- `facts.csv`, `paths.csv`, the legacy compatibility CSV, discovery index, and
  visualizer interaction output are still written;
- `run_stats.json` still reports zero LLM queries for syntax-only input.

For the scheduler tests, verify:

- no task is left pending after `resolver.run()`;
- peak active model calls never exceeds `valueflow_concurrency`;
- a pending model call does not prevent another seed's CPU-only result;
- final record ordering is deterministic;
- cache persistence happens only after all seeds complete.

Do not use a live GPU or external endpoint as the acceptance test for this
change. A live run may be used manually after all CPU-only tests pass.

## Manual speed check after tests pass

Use a project containing both syntax-resolvable and LLM-fallback targets. Run
the same fixture twice with the same cache configuration and compare:

- time until the first LLM request starts;
- whether CPU-only seed progress appears while model requests are pending;
- peak concurrent LLM calls;
- total `wall_seconds`;
- fact/path counts and cache contents.

The first run may still spend time building the complete tree and call graph;
that is an intentional correctness boundary for this minimal change. The
expected improvement is that once valueflow starts, CPU resolution, prompt
construction, and blocking LLM waits overlap rather than occupying one shared
executor/event-loop path.

## Optional follow-up, explicitly outside this implementation

Only if profiling shows that preprocessing and complete call-graph creation
dominate the total runtime should a second design be started. That design
would require incremental file/tree emission, a readiness model for caller
and handle dependency closures, and changes to `helpers/Preprocess` and
`call_graph`. It must not submit speculative LLM answers from incomplete
indexes. Do not begin that refactor as part of this speedup task.

## Stop conditions for the implementer

Stop and report instead of expanding scope if any of the following occurs:

- a change appears necessary in the legacy resolver;
- a change requires modifying prompts or answer schemas;
- Tree-sitter objects need to cross a process-pool boundary;
- output ordering or discovery-index identity changes;
- CPU-only tests require a network, GPU, or live model;
- executor cleanup cannot be made exception-safe without changing the public
  pipeline contract.

The completed implementation should be a small diff in the two runtime files
plus focused tests, with no behavior change for syntax-only results or the
legacy path.
