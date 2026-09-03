# C-Visualizer: minimal-diff reliability, accuracy, and performance plan

## 0. Purpose

This plan improves the existing C-Visualizer value-flow pipeline without changing its basic design.

The required outcome is:

1. Keep the values that C-Visualizer already resolves correctly.
2. Stop correct constants and macros from being labelled unresolved only because the call is inside an `if` statement.
3. List every configured target call found by the AST, even when the call is not reachable from the selected process root.
4. Fix the silent-zero case where a successful run reports no target sites even though configured target calls exist.
5. Stop Python recursion failures in the preprocessing and inventory stages.
6. Avoid enumerating every complete root-to-target call path before resolving a target value.
7. Resolve cheap, deterministic values before doing any inter-function search or LLM work.
8. Search backward from the target value with bounded, fair breadth-first search when local resolution is not enough.
9. Never turn an incomplete or truncated search into a false exact result.
10. Distinguish a successfully traced runtime value from a value the analyzer failed to trace.
11. Put a useful source file, source line, and source expression on every output row.
12. Keep the implementation diff as small and local as possible.

This is an implementation plan only. It does not authorize reading the old regex implementation or proprietary source trees.

---

## 1. Hard constraints

### 1.1 Files and data that must not be read

- Do not open or inspect `forkproc_checker/build_index.py` unless the user gives explicit permission in a later message.
- Do not open or inspect company source code under `/home/chukyu`.
- Do not use proprietary process source as a development fixture.
- The wrapper argument mappings in this plan come from the existing C-Visualizer analysis files, not from the old regex implementation.

### 1.2 Minimal-diff rules

- Change the smallest responsible function. Do not rewrite a whole module to fix one decision.
- Reuse the existing AST indexes, `Query` types, `Fact`, `ResolvedSeed`, reachability sets, local reaching-definition logic, table resolver, macro resolver, async worker queue, and CSV writers.
- Do not add a second resolver beside `ValueFlowResolver`.
- Do not add a new dependency.
- Do not change public command-line arguments unless a safety requirement cannot be met through the existing constructor/environment seams.
- Preserve existing function signatures when practical. Add optional keyword arguments only when necessary.
- Append CSV columns; do not rename or reorder existing columns.
- Keep old compatibility output files at their current paths.
- Do not delete the existing route enumerator in the first implementation. Stop calling it from the normal value-flow path, retain it as commented/deprecated reference code, and remove it only in a later cleanup after production evidence proves it is unused.
- Do not leave two active algorithms that can both emit facts for the same seed.
- Edit small recursive walkers in place. Do not create a general traversal framework merely to replace four short recursive functions.
- Delete code only when it is unreachable, demonstrably wrong, and retaining it would confuse which result is authoritative.

### 1.3 Accuracy rules

- A search optimization may reduce stored path strings. It must not silently reduce the set of possible values.
- If a safety limit is reached before all relevant states are checked, emit the values already found as evidence plus an incomplete-search fact. The final semantic status for that target must be `UNRESOLVED`.
- Never choose the first value merely to produce one answer.
- Never flatten a runtime set into one exact value.
- Never promote an LLM-only candidate to exact.
- Never treat an undefined symbol as runtime merely because its name is known.
- Never bind a local handle to an open in another function only because the variable spelling is the same.
- A close before use invalidates an earlier handle open.
- Existing `EXACT` JSON indexes must continue to accept only one source-proven value with accepted reachability.

### 1.4 Explicit non-goals

- Do not attempt a general C compiler, symbolic executor, or whole-program alias analyzer.
- Do not infer every pointer target.
- Do not make LLM answers authoritative.
- Do not restore comment/dead-code matches merely to match regex counts.
- Do not enumerate and save every call path. One or a few source-to-target witness paths are enough.
- Do not remove the legacy resolver mode from `project_aware.py`.
- Do not broadly refactor `project_aware.py`.
- Do not tune against one proprietary process.
- Do not declare success only because unit tests pass; the new stress fixtures must also prove bounded work.

---

## 2. Current behavior that must be preserved

The implementation model must understand these existing seams before editing them.

### 2.1 Discovery flow

The current flow is:

1. `project_aware.py` loads and preprocesses project files.
2. It builds Tree-sitter trees and a complete call graph.
3. `identify_funs_to_trace()` creates a subset of configured functions seen by a preliminary scan.
4. `discovery_index.build_target_site_inventory()` scans parsed call expressions.
5. `ValueFlowResolver` builds its own function and call-site indexes.
6. Resolver records are converted by `valueflow_records_to_facts()`.
7. `write_discovery_index()` writes compatible JSON and evidence CSV files.

The problem is that step 4 currently filters the supposedly independent AST inventory through the subset produced by step 3. A miss in the preliminary scan can therefore hide a call from the final inventory.

### 2.2 Value-flow flow

Useful current behavior already exists and must be reused:

- `ValueFlowResolver._resolve_expression()` already prefers literal, table, macro/enum, parameter, local assignment, LLM, and external/unknown handling in that order.
- `_local_reaching_definitions()` already finds the latest local assignment and complete `if`/`else if`/`else` value sets.
- `_resolve_table_expression()` already represents a runtime table lookup as multiple `CONST_TABLE` facts and resolves a literal table index to one entry.
- `_binding_opens()` already limits ordinary candidates to `sites_by_caller[caller_id]` and removes opens before the last close.
- `resolve()` already memoizes query results and uses `in_flight` futures so concurrent seeds can share a subproblem safely.
- `run()` already uses a bounded `asyncio.Queue`, multiple workers, and stable seed-order output.
- `_compute_reachability()` already computes whether a function is reachable from a root. Therefore, value resolution does not need every full root path merely to prove that the function is reachable.
- `classify_records()` already groups all records for one target argument and distinguishes a single resolved value from a multi-value runtime set.
- `facts.csv` and `discovery_facts.csv` already contain source location fields.
- `paths.csv` already links a fact to its traced path using `fact_id`.

### 2.3 Current expensive behavior

`ValueFlowResolver.routes_for_seed()` recursively enumerates complete simple routes from every accepted root to the target. It stops only after 10,000 complete routes for one seed. `_resolve_seed_with_transfers()` calls this before it knows whether the target is a direct literal, macro, local assignment, or locally bound handle.

This causes three separate costs:

- CPU is spent constructing route combinations that carry no new value information.
- One semantic value is repeated under many route/correlation IDs.
- `_deduplicate_records()` keeps route-correlated duplicates, so output size also grows with the call-path combinations.

The performance change must remove the need for full route enumeration from the normal value-flow path. Lowering 10,000 to another number is not the fix.

### 2.4 Existing safety/experimental switches

The current resolver already has these switches. Preserve their current defaults and meanings unless a phase below explicitly says otherwise:

- `TRACER_VF_GRAMMAR_EXTENDED`
- `TRACER_VF_EXTERNAL_UNKNOWN`
- `TRACER_VF_MULTI_OPEN`
- `TRACER_VF_KEEP_PARTIAL_ROWS`
- `TRACER_VF_STRUCTURED_OUTPUT`
- `TRACER_VF_NO_FORK`
- `TRACER_VF_TRANSFER_TIMEOUT`

Read environment values once during setup, as the current code does. Do not read them repeatedly in a hot loop. The backward-search replacement is a correctness/performance repair, not a second long-lived resolver mode, so do not add an old-search/new-search feature flag. The old route method remains in the source temporarily for rollback reference, but normal value-flow execution has one authoritative algorithm.

When editing comments in code that point to sections of an older `implementation_plan.md`, update only the comments next to changed code. Do not sweep the repository merely to renumber old comments.

---

## 3. Final status contract

Use these meanings consistently in `value_flow/status.py`, `facts.csv`, `discovery_facts.csv`, and the compatibility CSV.

| `resolution_status` | Meaning | Exact index allowed? |
| --- | --- | --- |
| `RESOLVED` | The source proves one concrete value for every live alternative considered. | Yes, if resource formatting, operation, scope, and reachability checks also pass. |
| `RUNTIME` | The backward trace completed, but runtime data selects among values or supplies the value. The genesis/boundary is known. | No. Keep as evidence. |
| `EXTERNAL` | The trace completed at a known boundary outside the analyzed process/source scope, such as an entry parameter or recognized input API. | No. Keep as evidence. |
| `UNRESOLVED` | The trace did not complete, a required source was missing, alternatives were only partly traced, syntax was unsupported, a handle remained ambiguous, or a safety limit was reached. | No. Keep as evidence. |
| `NO_TARGET` | The configured API has no value argument to resolve. | No value index entry. |

The simple rule is:

- `RUNTIME` means tracing succeeded and the value is dynamic.
- `UNRESOLVED` means tracing did not finish reliably.

### 3.1 Examples

- Direct `2818` at the target: `RESOLVED`.
- Macro `ChaOnlineELDNo` whose visible definition is `2818`: `RESOLVED`, even inside an `if`.
- Local variable assigned `2818` before the target: `RESOLVED`.
- Complete branch merge assigning `2818` or `2819`: `RUNTIME`, with two source-backed value rows and one shared `value_set_id`.
- Runtime table index over a completely known constant table: `RUNTIME`.
- Literal table index selecting one proven table entry: `RESOLVED`.
- Message field traced to a recognized receive/input assignment inside the process: `RUNTIME`.
- Formal entry parameter with no in-scope caller: `EXTERNAL`.
- Global read with no visible producer and no recognized boundary: `UNRESOLVED`, not automatically `RUNTIME`.
- Undefined macro/symbol: `UNRESOLVED`.
- Two complete caller branches and one missing caller branch: `UNRESOLVED` because the set is incomplete.
- Search state/depth limit reached: `UNRESOLVED` with `failure_reason=SEARCH_LIMIT_REACHED`.
- LLM candidate not independently confirmed by syntax: `UNRESOLVED`.

### 3.2 Relationship between evidence status and semantic status

`discovery_facts.csv` currently has both `status` and `resolution_status`. Keep both.

- `status=EXACT` is the narrow compatibility promotion gate for exact JSON indexes.
- `resolution_status` explains the value semantics.
- A complete multi-value set should use evidence `status=DYNAMIC` and semantic `resolution_status=RUNTIME`.
- A known runtime genesis with no finite numeric set should also use `status=DYNAMIC` and `resolution_status=RUNTIME`.
- External boundaries remain `status=EXTERNAL` and `resolution_status=EXTERNAL`.
- Incomplete search remains `status=UNRESOLVED` and `resolution_status=UNRESOLVED`.
- Reachability remains a separate field. Do not use value status to encode whether a call is reachable from a process root.

---

## 4. Output and provenance contract

Every fact row must tell the user two different things:

1. Target location: where the interesting API is called.
2. Source/genesis location: where the selected value was introduced or where the trace stopped.

### 4.1 Required location rules

| Fact kind | `source_file` / `source_line` / `source_expr` |
| --- | --- |
| Literal passed directly | Target expression location. |
| Literal local assignment | Assignment/initializer location. |
| Macro or enum | Definition location and symbol expression. |
| Constant table | Table definition/entry location. Put selector provenance in metadata. |
| Same-function handle | The open call's value source, not the read/write call. |
| Runtime local/message value | Earliest meaningful in-scope assignment or recognized input/read site. |
| External value | Entry parameter or recognized external API boundary. |
| Unresolved value | Last source location that was actually proven. If nothing was proven, use the target location and mark it as a fallback, not genesis. |
| No-target API | Target call location. |

### 4.2 Required provenance metadata

Reuse `Fact.metadata`; do not add many new top-level dataclass fields. Add these keys only where relevant:

- `source_role`: `GENESIS`, `BOUNDARY`, `LAST_PROVEN`, `TARGET_FALLBACK`, or `TABLE_VALUE`.
- `trace_complete`: boolean.
- `termination_reason`: for example `LITERAL`, `MACRO`, `ENUM`, `LOCAL_ASSIGNMENT`, `TABLE_SET`, `RUNTIME_INPUT`, `EXTERNAL_ENTRY`, `NO_TARGET`, `UNSUPPORTED_SYNTAX`, `HANDLE_AMBIGUOUS`, `RECURSIVE_STATE`, or `SEARCH_LIMIT_REACHED`.
- `search_truncated`: boolean, only when true.
- `search_states_expanded`: per-seed count.
- `search_max_frontier`: per-seed maximum.
- `path_mode`: `QUERY_PROVENANCE` or `WITNESS`.
- Existing guard, table, callback, correlation, and transfer metadata must remain.

For a runtime table lookup, keep the table as the main `source_*` location and store these selector fields in metadata when known:

- `selector_source_file`
- `selector_source_line`
- `selector_source_expr`

Do not pretend the selector and the table are one source.

### 4.3 Multiple genesis points

- Emit one fact row per distinct proven source/value.
- Give all rows for the same complete runtime set the same `value_set_id`.
- Deduplicate by semantic source and value, not by complete call-route identity.
- Keep one or a small bounded number of witness paths for each fact.
- Do not multiply fact rows merely because several root paths reach the same semantic source.

### 4.4 Compatibility CSV

Do not rename the existing `LEGACY_COLUMNS` in `value_flow/outputs.py`. Append these columns at the end:

1. `resolution_status`
2. `value_source->path`
3. `value_source->line_number`
4. `value_source->expression`
5. `resolution_reason`

Existing consumers reading the old column names continue to work. New consumers can jump directly to the genesis/boundary.

---

## 5. Implementation order

Implement in the order below. Each phase has its own test gate. Do not combine all phases into one large edit.

### Phase 0: freeze the current behavior with tests

#### Files

- `tests/test_value_flow.py`
- `tests/test_llm_transfer_value_flow.py`
- `tests/test_value_flow_status.py`
- `tests/test_discovery_index.py`
- `tests/test_valueflow_pipeline.py`
- `tests/test_valueflow_scheduler.py`
- `tests/test_preprocess.py`

#### Work

1. Run the existing focused suite before editing production code:

   ```bash
   PYTHONPATH=. .venv/bin/pytest -q \
     tests/test_value_flow_status.py \
     tests/test_discovery_index.py \
     tests/test_value_flow.py \
     tests/test_llm_transfer_value_flow.py \
     tests/test_phase4_value_flow.py \
     tests/test_valueflow_pipeline.py \
     tests/test_valueflow_scheduler.py \
     tests/test_preprocess.py
   ```

2. Record the baseline pass count and failures in the implementation handoff. Do not change assertions merely because the new code produces a different answer.
3. Add small synthetic C fixtures for each behavior below before changing the implementation:
   - guarded direct macro;
   - complete two-branch macro assignment;
   - incomplete branch assignment with no `else`;
   - runtime and literal-index table lookup;
   - two functions that each declare a local variable named `fcb`;
   - open, close, then use;
   - configured target present while `functions_identified` is empty;
   - deep AST nesting that exceeds ordinary Python recursion depth if walked recursively;
   - diamond/fan-out call graph that has exponentially many complete paths but few semantic states;
   - one combinatorial caller branch plus one shallow branch that resolves immediately.
4. Use fake in-memory trees and fake LLM callbacks. Do not depend on proprietary source.
5. In performance fixtures, count state expansions and callback calls. Do not assert wall-clock milliseconds, because timing assertions are unstable.

#### Gate

- Existing tests pass before production edits.
- New characterization tests fail only for the intended missing behavior.

---

### Phase 1: remove recursion failures from whole-tree plumbing

This phase fixes stack safety without changing value semantics.

#### Files

- `project_aware.py`
- `helpers/Preprocess/preprocess.py`
- `makefile_resolver/extract_includes.py`
- `value_flow/resolver.py` only for provenance-path recursion
- `tests/test_preprocess.py`
- one focused pipeline test file if needed

#### Exact edits

1. Change `project_aware.extract_function_calls()` from nested recursive `traverse(node)` to an explicit stack:

   ```python
   stack = [tree.root_node]
   while stack:
       node = stack.pop()
       # existing call-expression logic unchanged
       stack.extend(reversed(node.children))
   ```

   Preserve source order by pushing reversed children.

2. In `helpers/Preprocess/preprocess.py`, make the same local iterative change in:
   - `extract_all_macros()`;
   - `extract_includes()`;
   - `Preprocess.remove_comments()`'s `collect_comments()` walk.

   Keep the existing collection and sorting logic unchanged.

3. In `makefile_resolver/extract_includes.py`, replace its nested recursive Tree-sitter traversal with a stack.

4. In `makefile_resolver.extract_includes()`, keep returning `None` for a failed preprocess in this minimal patch if other callers depend on it. At the caller in `resolve()`, change only:

   ```python
   raw_lines = extract_includes(current_path) or []
   ```

   This avoids `TypeError` without a wider return-type migration.

5. In `project_aware.identify_funs_to_trace()`, do not assume every `project_structure` key has a parsed tree:

   ```python
   if file_name.endswith(".h") or file_name not in trees:
       continue
   ```

   This safely skips `.def`, missing, or unsupported files while leaving them in the project map for diagnostics.

6. Convert the recursive helpers inside `_provenance_token_paths()` and `provenance_tokens()` to iterative stack/queue logic. Preserve:
   - cycle detection;
   - deterministic sorted-parent order;
   - `path_cap` output truncation;
   - exact path counts when cheaply computable.

7. Do not raise `sys.setrecursionlimit()`. A higher limit only moves the crash and can exhaust the C stack.

8. Do not convert every small bounded AST recursion in the repository. Only change the whole-tree or unbounded graph walks listed above unless a test proves another recursion failure.

#### Tests

- A deeply nested synthetic source file completes macro, include, comment, and call extraction without `RecursionError`.
- Failed preprocess produces an empty include list at the resolver loop and does not crash.
- A project-map entry absent from `trees` is skipped and the configured C file is still scanned.
- Existing extraction order is unchanged on a normal fixture.
- Provenance cycles terminate.
- Path output remains deterministic.

#### Gate

- No recursion-limit changes exist.
- Normal fixtures produce byte-for-byte identical extracted macro/include/call lists.
- The deep fixture completes.

---

### Phase 2: make AST inventory independent and visible

#### Files

- `discovery_index.py`
- `project_aware.py`
- `value_flow/outputs.py` only if shared atomic CSV helpers are reused
- `tests/test_discovery_index.py`
- `tests/test_valueflow_pipeline.py`

#### Exact edits

1. In `build_target_site_inventory()`, use the full target registry from `spec["targets"]` when it is present.

   Current wrong dependency:

   ```python
   for name, config in functions_identified.items():
   ```

   Required behavior:

   ```python
   configured_targets = (spec or {}).get("targets") or functions_identified
   for name, config in configured_targets.items():
       if discovery_args_for(config):
           discovery_targets[name] = config
   ```

   Keep `functions_identified` in the signature as a fallback for project-local fixtures and old callers. Do not break its callers.

2. The inventory must remain a pure AST scan:
   - no root reachability filter;
   - no value resolution;
   - no LLM;
   - no requirement that a target seed was produced.

3. In the value-flow branch of `project_aware.py`, build `valueflow_configs` from the full normalized `State()["FUNCTION_TYPES"]` registry. The resolver already creates seeds only for call sites that exist, so passing the full registry does not perform resolution for absent APIs.

4. Keep the small detected subset for the old resolver branch. Do not alter old resolver behavior.

5. Change the empty-detection early return:
   - old resolver: keep the current return when `functions_identified == {}`;
   - value-flow resolver: do not return; run with the full registry and let the resolver/inventory decide whether sites exist.

6. Add `target_sites.csv` to `build_discovery_payloads()` and `write_discovery_index()`.

   Use these columns in this order:

   1. `target_function`
   2. `target_site_file`
   3. `target_site_line`
   4. `arg_index`
   5. `target_expression`
   6. `operation`
   7. `aux_lock`
   8. `macro_name`
   9. `unmapped_args`
   10. `in_process`

7. Reuse `_csv_text()` and the existing atomic payload writer. Do not create another CSV-writing implementation.

8. Keep `_unreachable_facts()` as the mechanism that turns inventory sites with no resolver record into visible evidence rows.

9. Add a consistency diagnostic to `index_metadata.json`:
   - `inventory_sites_without_facts` count;
   - `facts_without_inventory_site` count.

   Do not fail the run merely because an unreachable site has no resolved record. It must be visible and counted.

10. A successful run with a non-empty `target_sites.csv` and zero facts must have an explicit diagnostic. It must never look like a clean zero-target project.

#### Tests

- `functions_identified={}` plus a full spec and one AST call yields one inventory row.
- A target absent from the preliminary subset but present in the full registry appears in `target_sites.csv`.
- An unreachable target appears in both `target_sites.csv` and `discovery_facts.csv` with an unreachable status.
- No-target APIs remain represented correctly.
- Macro-renamed targets retain the current argument-mapping behavior.
- Existing index JSON shapes are unchanged except for additive metadata and the new CSV file.

#### Gate

- Inventory count equals the number of configured AST call arguments in the synthetic fixture.
- Empty preliminary detection cannot hide a configured AST target in value-flow mode.

---

### Phase 3: fix guard demotion and unify status decisions

#### Files

- `value_flow/status.py`
- `discovery_index.py`
- `tests/test_value_flow_status.py`
- `tests/test_discovery_index.py`

#### Exact edits

1. Keep `classify_records()` as the owner of whole-site semantic classification. It sees every alternative and is the correct place to decide single value versus runtime set.

2. Pass `semantic.status` into `_classify_valueflow_fact()` instead of calculating it and then ignoring it.

3. Remove the rule that demotes `CONST`/`MACRO` solely because `fact.metadata["guards"]` is non-empty.

4. Do not remove guard metadata. Guards still explain when a branch executes and remain useful for alternative correlation.

5. Implement classification in this order:

   1. `resource == "none"` or `NO TARGET` -> `NO_TARGET` behavior unchanged.
   2. `origin_kind == "LLM_CANDIDATE"` -> `UNRESOLVED` regardless of suggested value.
   3. semantic `UNRESOLVED` -> evidence `UNRESOLVED`.
   4. semantic `EXTERNAL` -> evidence `EXTERNAL`.
   5. semantic `RUNTIME` -> evidence `DYNAMIC`.
   6. semantic `RESOLVED` plus a source-grounded constant/macro/enum/single table value -> run existing resource validation and then return `EXACT`.
   7. Failed numeric/package/operation validation -> `UNRESOLVED`.

6. Keep the existing exact-format checks:
   - file/queue values require `to_decimal(value)` and a valid operation;
   - forkproc values require `package_name(value)`;
   - exact index promotion still requires accepted reachability and in-process scope.

7. Update `_fact_kind()` only as needed for the final contract:
   - source-backed literal `CONST`, `MACRO`, single `CONST_TABLE`, and `BOUNDED_SET` facts count as resolved alternatives;
   - multiple distinct resolved alternatives become `RUNTIME` at group level;
   - a new explicit runtime-genesis origin, if introduced in Phase 6, maps to `RUNTIME`;
   - any mixture containing an incomplete fact remains `UNRESOLVED`.

8. Do not promote all table facts to exact. Only a one-value complete group can be `RESOLVED`; a multi-value complete group is `RUNTIME`.

#### Tests

- Unguarded macro -> `RESOLVED` / `EXACT`.
- The same macro with arbitrary runtime guard metadata -> identical `RESOLVED` / `EXACT`.
- Empty guard list behaves the same.
- Two guarded branch values -> shared runtime set, not two exact index entries.
- One resolved branch plus one unresolved branch -> `UNRESOLVED`.
- LLM candidate plus a guard stays unresolved.
- External and no-target behavior is unchanged.

#### Gate

- A guard affects path/branch evidence but never changes a single proven constant's value status.
- Multi-value and partial results do not enter exact JSON indexes.

---

### Phase 4: deterministic resolution before inter-function search

This is the first performance change. It should remove most unnecessary route work with a small refactor.

#### Files

- `value_flow/resolver.py`
- `tests/test_value_flow.py`
- `tests/test_llm_transfer_value_flow.py`

#### Exact edits

1. Extract the current non-transfer body of `_resolve_seed()` into a small private helper, for example:

   ```python
   async def _resolve_seed_from_queries(self, seed: Seed) -> list[ResolvedSeed]:
       ...existing non-transfer query code...
   ```

   Move code; do not duplicate it.

2. Keep `_resolve_seed()` as the dispatcher:

   ```python
   async def _resolve_seed(self, seed):
       if self._seed_has_no_value(seed):
           return await self._resolve_seed_from_queries(seed)
       if self._locally_provable(seed.site):
           return await self._resolve_seed_from_queries(seed)
       if self.transfer_resolver is not None:
           return await self._resolve_seed_with_transfers(seed)
       return await self._resolve_seed_from_queries(seed)
   ```

   Use existing configuration fields to implement `_seed_has_no_value`; do not introduce a new registry field.

3. Extend `_locally_provable()` only enough to cover the deterministic cases the resolver can already resolve:
   - literal;
   - visible macro;
   - visible enum;
   - local string initializer;
   - complete local reaching assignments;
   - complete branch-merge constants;
   - table expression for which `_resolve_table_expression()` returns a complete source-backed set;
   - exactly one same-function handle open whose configured value arguments are locally provable.

4. Reuse `_resolve_table_expression()` for the table proof. Do not create a second table parser.

5. Reuse `_local_reaching_definitions()` for assignments and branch merges. Do not add regex assignment matching.

6. Reuse `_binding_opens()` for same-function handles. Do not add proximity fallback.

7. The proof helper must return false for:
   - formal parameters;
   - unrecognized calls;
   - unresolved fields/pointers;
   - incomplete branch chains;
   - multiple handle opens not proven mutually exclusive;
   - unsupported macro argument mapping.

8. The query helper may be used with a transfer callback installed only after `_locally_provable()` says the selected value cannot escape to a caller or LLM. Add a test that the transfer callback count remains zero.

9. No-target APIs must be emitted directly. They must never call `routes_for_seed()`.

10. Add counters to the resolver:
    - `fast_path_seed_count`;
    - `search_seed_count`.

    Add them to `run_stats.json` later in Phase 8.

#### Tests

- Monkeypatch `routes_for_seed()` to raise. Literal, macro, enum, local assignment, complete branch set, table set, same-function handle, and no-target tests must still pass.
- The fake transfer callback is never called for these cases.
- Direct macro source location remains the macro definition.
- Branch merge emits all values and becomes `RUNTIME`.
- Runtime table emits all table values and becomes `RUNTIME`.
- Literal table index emits one `RESOLVED` value.
- Incomplete branch chain does not take the fast path.
- Ambiguous handle does not take the fast path.

#### Gate

- All locally provable seeds complete without route enumeration.
- Their values, source locations, and semantic statuses equal the existing query resolver's output.

---

### Phase 5: replace complete-route enumeration with bounded backward state search

This is the main algorithm change. Keep it inside `ValueFlowResolver` and reuse the current transfer machinery.

#### Files

- `value_flow/resolver.py`
- `value_flow/transfers.py` only if one small state dataclass clearly belongs there
- `tests/test_llm_transfer_value_flow.py`
- `tests/test_valueflow_scheduler.py`

#### 5.1 Search direction

Start from the target/effective value site and move only when the selected value still depends on a caller.

Do not start from `main` and do not build every `main -> target` combination.

At each state:

1. Resolve literal/macro/formula leaves with `_settle_transfer_arm()`.
2. Evaluate source-backed guards with `_evaluate_arm_guards()`.
3. Ask `request_local_transfer()` only if a non-terminal expression remains.
4. If all bindings are terminal, emit the arm and stop expanding that branch.
5. If an expression still contains formal-parameter placeholders, expand only the caller edges that can supply those parameters.
6. Substitute the actual caller arguments with `_substitute_arm()`.
7. Enqueue the resulting caller states.
8. If the branch reaches a root formal parameter, mark it `EXTERNAL`.
9. If it reaches a recognized in-scope runtime input, mark it `RUNTIME`.
10. If it reaches unsupported or incomplete syntax, mark it `UNRESOLVED`.

The already-computed `reachable` set proves that the starting function has at least one root path. A full root path is needed only as a display witness, not as a prerequisite for resolving a local constant.

#### 5.2 State shape

Add one small private dataclass near the existing resolver dataclasses, for example `BackwardState`:

- `current_function_id`
- `selected_site_id`
- `arm`
- `suffix_edges`: the value-carrying caller edges already traversed toward the target
- `depth`
- `branch_id`: the first caller edge chosen below the target, used for fairness

Do not put whole AST nodes or source buffers in the state. Store stable IDs and look them up through existing indexes.

#### 5.3 Semantic deduplication key

Before enqueueing, normalize a key containing:

- current function ID;
- selected call-site ID;
- ordered `(target_arg, binding_kind, normalized_binding_text)` tuples;
- normalized remaining guards;
- handle root when doing handle search.

Do not include:

- complete route ID;
- correlation ID derived only from route identity;
- display path labels.

Two routes that reach the same semantic state should be processed once. Store an additional witness predecessor/path for display instead of duplicating the computation.

Keep branch correlations that represent different value alternatives. Remove only correlation caused solely by different call-path spelling.

#### 5.4 Fair breadth-first scheduling

Use breadth-first order by caller depth. Within one depth, use round-robin order across `branch_id` groups.

Required properties:

- Every shallow branch gets a chance before one combinatorial branch consumes deeper work.
- A branch that resolves at depth 1 is not skipped because another branch produces thousands of depth-2 states.
- Caller edges are sorted by `(site_id, caller_id)` before enqueueing, so output is deterministic.
- `seen` is checked before enqueueing.
- A state is counted when first accepted for processing, not once per duplicate route.

One acceptable data structure is:

```text
depth -> ordered map(branch_id -> deque[BackwardState])
```

For the current minimum depth, pop at most one state from each active branch, then repeat while that depth still has states. Move to the next depth only after the current depth is empty.

#### 5.5 Early branch exit

Stop expanding one branch as soon as all selected bindings are one of:

- `EXACT`
- `EXTERNAL`
- explicit runtime genesis
- `UNKNOWN`

`UNKNOWN` is terminal only for computation; it produces `UNRESOLVED`, not success.

Do not continue walking toward a root after a value is exact and all remaining guards are settled or safely retained as execution conditions.

#### 5.6 Handle backwalk

Replace the route-dependent handle opening search with the same backward-state idea:

1. Start with `(consumer function, normalized handle, consumer byte offset)`.
2. Call `_binding_opens()` in that exact function before the use.
3. If exactly one valid opening exists, use it as the effective value site and stop the handle search branch.
4. If the handle is a formal parameter, expand each ordinary reverse caller edge, substitute the caller's actual handle argument, and continue BFS.
5. A synthetic callback edge is an external boundary unless callback metadata proves a concrete binding.
6. If multiple opens are all source-proven mutually exclusive branches, keep all as a runtime set.
7. If multiple opens cannot be correlated safely, emit `HANDLE_AMBIGUOUS`.
8. Do not search another function for a plain local variable of the same name.
9. Continue respecting the last close before the use.

Reuse `_binding_opens()`, `_handle_candidates()`, `normalise_handle()`, function parameter lists, and reverse caller indexes.

#### 5.7 Safety budget

Add a small internal search budget. Use deterministic count limits, not a wall-clock timeout.

Recommended constructor defaults:

- `search_state_cap=5000` unique states per seed;
- `search_depth_cap=256` caller hops per seed;
- cooperative event-loop yield every 64 expanded states.

Allow environment overrides only through:

- `TRACER_VF_SEARCH_STATE_CAP`
- `TRACER_VF_SEARCH_DEPTH_CAP`

Read and validate these once in `ValueFlowResolver.__init__()`. Values below 1 fall back to 1. Do not add CLI flags in this patch.

When a limit is reached:

1. Stop adding new states for that seed.
2. Keep already proven facts as evidence.
3. Add one unresolved fact with:
   - `origin_kind="UNRESOLVED"`;
   - `termination_reason="SEARCH_LIMIT_REACHED"`;
   - `trace_complete=false`;
   - `search_truncated=true`;
   - expanded/frontier/depth counters.
4. Ensure `classify_records()` sees the unresolved fact in the same target-argument group, making the group `UNRESOLVED`.
5. Add a human-readable transfer diagnostic.
6. Increment a run-stat counter.

Never return only the early exact values with `RESOLVED` after truncation. That would silently hide unvisited alternatives.

#### 5.8 Concurrency safety

- Keep the existing seed worker queue.
- Keep all search structures for one seed local to that seed coroutine.
- Continue sharing only the existing immutable indexes and memoized query/transfer caches.
- Continue using `_query_lock` and `in_flight` for shared query results.
- Do not mutate another seed's frontier.
- Do not use threads for AST traversal.
- Call `await asyncio.sleep(0)` after each configured batch of CPU-only state expansions so another seed can run.
- Keep the LLM semaphore as the only LLM concurrency gate.
- Keep final record ordering by original seed index.

#### 5.9 Witness paths

During `_compute_reachability()`, retain one deterministic predecessor edge for each reachable function. This is a small addition to the existing BFS.

For a terminal fact:

1. Reconstruct one root-to-current reachability prefix from the predecessor map.
2. Append the value-carrying `suffix_edges` from current to target.
3. Render with the existing `_route_labels()` logic or a tiny reused helper.
4. Mark `path_mode="WITNESS"`.

Do not enumerate alternative root prefixes. The fact represents a semantic source, not every execution route.

#### 5.10 Integration approach

- Refactor `_walk_route_backward_transfers()` into a state-processing helper instead of copying all of its transfer logic.
- Reuse `_initial_route_arms()`, `_settle_transfer_arm()`, `request_local_transfer()`, `_evaluate_arm_guards()`, `_substitute_arm()`, `_mark_external_or_unknown()`, and `_resolved_transfer_seed()`.
- Change `_resolve_seed_with_transfers()` to invoke the new backward search directly.
- Stop calling `routes_for_seed()` from normal value-flow resolution.
- Retain `routes_for_seed()` in the first patch with a clear comment that it is no longer used by the value-flow execution path and is kept temporarily for rollback/reference tests.
- Do not use the old enumerator as an automatic fallback after a search limit. That would recreate the failure this phase fixes.

#### Tests

1. Diamond graph: many complete root paths collapse to one semantic state and one fact.
2. Different caller values: distinct values remain distinct and become a complete runtime set.
3. Same value from many callers: one semantic fact plus bounded witness paths, not one fact per route.
4. Local terminal after one transfer: no ancestor callers are explored.
5. Fairness fixture: one exploding branch plus one shallow literal branch; the shallow value is found before the budget ends.
6. Cap fixture: search emits evidence plus `SEARCH_LIMIT_REACHED`, and final status is `UNRESOLVED`.
7. Depth cap fixture behaves the same.
8. Recursive call graph terminates through the semantic `seen` set.
9. Callback edge produces external/boundary behavior unchanged.
10. Two concurrently resolving seeds share cached subqueries and do not duplicate LLM calls.
11. Output order is stable across at least three runs.
12. Monkeypatch `routes_for_seed()` to raise; nonlocal value-flow tests still pass, proving it is unused.

#### Gate

- Search work grows with unique value-flow states, not the number of complete root paths.
- The stress fixture stays below the configured state cap.
- Truncation can never produce `RESOLVED` or exact-index promotion.
- All pre-existing transfer correctness tests pass.

---

### Phase 6: represent runtime genesis and unresolved failure honestly

#### Files

- `value_flow/resolver.py`
- `value_flow/status.py`
- `value_flow/outputs.py`
- `discovery_index.py`
- `tests/test_value_flow_status.py`
- `tests/test_discovery_index.py`

#### Exact edits

1. Introduce one explicit origin for successfully traced dynamic in-scope data, for example `RUNTIME_DATA`.

2. Produce `RUNTIME_DATA` only when the backwalk reaches a meaningful terminal source such as:
   - recognized input/receive API output;
   - source-backed runtime selector whose producer is known;
   - local assignment from a runtime field where the read site is known and the trace has no missing branch.

3. Do not produce `RUNTIME_DATA` for:
   - unsupported pointer expressions;
   - undefined symbols;
   - partial caller coverage;
   - missing AST/source;
   - ambiguous handles;
   - recursion/search truncation.

4. Keep `EXTERNAL_ENTRY` and `EXTERNAL_DATA` for known outside boundaries. Do not merge `EXTERNAL` into `RUNTIME`; users need to know whether the producer is outside the process.

5. Update `_fact_kind()` so `RUNTIME_DATA` maps directly to semantic `RUNTIME`.

6. For all fact constructors, set `source_role`, `trace_complete`, and `termination_reason` consistently. Prefer a small helper that merges provenance metadata rather than repeating dictionaries in many branches.

7. Fix `_fact_from_transfer_binding()` so falling back to `seed.site.file_path` is marked `source_role=TARGET_FALLBACK`. Do not present it as a proven genesis.

8. On unresolved output, preserve the last proven source site if one exists. Put the specific failure in metadata and the compatibility `resolution_reason` field.

9. Ensure all rows have non-empty source location fields:
   - use actual definition/assignment/boundary whenever proven;
   - otherwise use target file/line/expression as a clearly marked fallback;
   - never invent a line number.

10. Keep one row per source when there are several genesis points. Reuse `value_set_id` from `classify_records()`.

11. Update output comments: `paths.csv` stores retained source-to-target proof/witness paths, not every possible root route.

12. Append the compatibility CSV columns listed in Section 4.4. Populate them from the representative fact without changing old columns.

#### Tests

- Known runtime input -> `RUNTIME`, correct genesis line, `trace_complete=true`.
- Root parameter -> `EXTERNAL`, boundary line/expression.
- Unsupported pointer -> `UNRESOLVED`, last proven or target fallback, failure reason.
- Undefined symbol -> `UNRESOLVED`.
- Complete finite branch/table set -> `RUNTIME` with shared `value_set_id`.
- Partial set -> `UNRESOLVED`.
- Search limit -> `UNRESOLVED` even when one value was found first.
- Literal and macro rows contain target/definition source locations.
- Compatibility CSV retains all old headers in the same order and appends the five new headers.

#### Gate

- Every fact CSV row has target and source location fields.
- `RUNTIME` is used only for completed dynamic traces.
- Analyzer failures remain visibly `UNRESOLVED`.

---

### Phase 7: handle scope and branch-set accuracy

The analysis report describes false file-scope handle ambiguity, but the current `_binding_opens()` already looks in `sites_by_caller[caller_id]`. Therefore, test first and change production code only if the current version still reproduces the bug.

#### Files

- `value_flow/resolver.py` only if the regression test fails
- `tests/test_value_flow.py`
- `tests/test_llm_transfer_value_flow.py`

#### Exact work

1. Add a fixture with two functions, each declaring local `fcb`, opening it once, and using it once.
2. Assert each use binds only to the open in its own function.
3. If the test already passes, make no handle-scope production change. Record the report item as already fixed/stale.
4. If it fails, patch the exact stage that loses caller identity. The binding key must include function/caller identity plus normalized handle, not file plus variable spelling.
5. Keep file-static and global/field behavior separate:
   - automatic local -> same function only;
   - file-static -> same translation unit;
   - global/struct field -> reachable candidate functions, with ambiguity preserved.
6. Add open-close-use fixture. An open before the last matching close cannot bind a later use.
7. For several mutually exclusive local opens, reuse the existing multi-open/arm machinery to retain all source-proven alternatives.
8. Promote those alternatives to `RUNTIME` only if every live branch is represented and tracing completed.
9. If branch correlation is incomplete, keep `HANDLE_AMBIGUOUS` / `UNRESOLVED`.
10. Do not enable nearest-open or first-open fallback.
11. Do not let an LLM candidate settle ambiguity without syntax confirmation.

#### Branch assignments

The Phase 4 fast path should automatically fix complete branch-merged constants because `_local_reaching_definitions()` already returns every arm. Add explicit tests here to prevent regression:

- `if/else` with two macros -> two-value `RUNTIME` set;
- `if/else if/else` with three macros -> three-value set;
- missing `else` -> unresolved unless an earlier reaching value is also proven;
- one branch with unsupported expression -> whole group unresolved;
- guards remain attached as evidence but do not demote each source constant.

#### Gate

- Same-named locals in different functions cannot collide.
- Use-after-close cannot resolve from a stale open.
- Complete alternatives remain complete; incomplete alternatives remain unresolved.

---

### Phase 8: register six semantic queue wrappers without hiding their nature

These mappings are already stated in C-Visualizer analysis material:

| Wrapper | Queue-number argument | Canonical operation |
| --- | ---: | --- |
| `Dac_EnqSem` | 2 | `ADDQUE` |
| `Dac_EnqSem2` | 2 | `ADDQUE` |
| `SimEnqueSem` | 3 | `ADDQUE` |
| `MsgEnqSem` | 2 | `ADDQUE` |
| `DxiEnqEvent` | 2 | `ADDQUE` |
| `DxiEnqEvent2` | 2 | `ADDQUE` |

#### Files

- `target_specs/build_index_targets.json`
- target-spec loader/validation only if unknown metadata is currently rejected
- `tests/test_target_compatibility.py`
- `tests/test_discovery_index.py`
- `tests/test_value_flow.py`

#### Exact edits

1. Add one normal target entry per wrapper with:
   - `type="QUEUEF"`;
   - `launch="FORK"`;
   - the argument index in the table above;
   - `get_upper=true`;
   - no dependent functions;
   - discovery resource `mfs_queue`;
   - matching argument operation `ADDQUE`.

2. Add additive metadata:
   - `semantic_wrapper=true`;
   - `canonical_target="mpf_mfs_addque"`.

3. Preserve the wrapper name as `target_function` and put the canonical operation in metadata. This lets users see the actual caller-level site while understanding its meaning.

4. Increment the target-spec version and allow its digest to change through the existing digest function. Do not hand-edit a digest.

5. Do not copy hard-coded wrapper logic into `project_aware.py` or the resolver. The registry is the single owner.

6. Raw AST inventory must keep both locations when both exist:
   - the caller-level wrapper call is a `WRAPPER_CALL`;
   - the `mpf_mfs_addque` call inside the wrapper body is a `WRAPPER_IMPLEMENTATION`.

   They are two real source sites, so both belong in `target_sites.csv` and evidence output.

7. Do not let those two levels create two authoritative access records for one runtime queue operation. Keep this logic in the discovery adapter, not in parsing or value resolution:
   - attach the enclosing caller function name to normalized fact metadata;
   - group source-proven wrapper-call facts by wrapper, operation, and resolved value;
   - identify canonical inner facts whose enclosing function is that wrapper;
   - mark an inner fact `alias_internal=true` and keep it evidence-only only when a complete caller-level wrapper fact covers the same operation and value;
   - keep the inner fact authoritative when caller-level coverage is absent, unresolved, external, or truncated;
   - never suppress a value that appears only at the inner site;
   - never suppress anything merely to make counts match.

8. The exact JSON access indexes must receive at most one authoritative record for a covered wrapper operation/value. `target_sites.csv` and `discovery_facts.csv` still show both source sites and their roles.

9. Implement the evidence-only alias state additively. Either use a clear non-exact evidence status such as `ALIAS_INTERNAL`, or keep the existing non-exact status and add `alias_internal=true`; whichever choice requires fewer downstream changes. `resolution_status` may remain `RESOLVED` because the value itself is proven—the row is excluded only because it is the internal half of an already represented semantic operation.

10. Do not infer new wrappers by naming convention. Only the six reviewed mappings are in scope.

#### Tests

- Each wrapper is discovered at the configured argument position.
- Direct literal/macro wrapper values use the deterministic fast path.
- Runtime wrapper parameter values use backward search.
- Wrapper metadata names `mpf_mfs_addque` as canonical.
- Ordinary `mpf_mfs_addque` behavior is unchanged.
- A covered wrapper call plus its inner implementation yields two evidence sites but only one authoritative exact access record for that operation/value.
- If wrapper caller coverage is incomplete, the inner source-proven fact is not suppressed.
- Target-spec schema/digest tests pass.

#### Gate

- All six wrappers are visible and resolve under the same proof rules as ordinary queue calls.
- No wrapper value is guessed.

---

### Phase 9: counters, diagnostics, and final output wiring

#### Files

- `value_flow/resolver.py`
- `project_aware.py`
- `value_flow/outputs.py`
- `discovery_index.py`
- relevant output tests

#### Add these `run_stats.json` fields

- `fast_path_seed_count`
- `search_seed_count`
- `search_state_count`
- `search_deduplicated_state_count`
- `search_limit_seed_count`
- `search_max_frontier`
- `search_max_depth`
- `witness_path_count`

Keep all existing run-stat fields.

#### Diagnostics

- Replace the old normal-path `route limit 10000 reached` message with explicit backward-search diagnostics.
- Diagnostic text must include target site ID, limit type, configured limit, states expanded, maximum frontier, and deepest level.
- Include inventory/fact mismatch counts in index metadata.
- Keep failed-run partial evidence writing.
- Do not turn diagnostics into exceptions unless an existing correctness invariant is violated.

#### Summary output

Add a small performance section to the existing per-process `summary.md` using the counters above. Do not create a new report format.

#### Gate

- A user can tell whether a run used only fast paths, performed search, or stopped at a safety limit.
- A green zero-target run is distinguishable from a target-containing run with zero resolver facts.

---

## 6. Detailed backward-search pseudocode

The implementation may use different private names, but it must preserve these decisions.

```python
async def _search_seed_backward(seed, start_site, indices, operation):
    initial_arms = _initial_arms_without_full_route(seed, start_site, indices)
    frontier = FairBreadthFirstFrontier()
    seen = set()
    terminal_arms = []
    incomplete = False

    for arm in initial_arms:
        frontier.add(
            BackwardState(
                current_function_id=start_site.caller_id,
                selected_site_id=start_site.site_id,
                arm=arm,
                suffix_edges=(),
                depth=0,
                branch_id="local",
            )
        )

    while frontier:
        state = frontier.pop_fair_bfs()

        key = semantic_state_key(state)
        if key in seen:
            remember_extra_witness(key, state)
            continue
        seen.add(key)

        if len(seen) > search_state_cap or state.depth > search_depth_cap:
            incomplete = True
            break

        site = sites[state.selected_site_id]
        function = functions[state.current_function_id]
        arms = settle_and_transfer_locally(state.arm, site, function)

        for arm in arms:
            if guard_is_impossible(arm):
                continue

            if all_bindings_terminal(arm) and no_unsettled_parameter_guard(arm):
                terminal_arms.append((arm, state))
                continue

            caller_edges = relevant_reverse_callers(function, arm)

            if not caller_edges:
                terminal_arms.append(mark_boundary_or_unknown(arm, function))
                continue

            for edge in sorted(caller_edges, key=edge_sort_key):
                child = substitute_arm(arm, edge)
                if child is None:
                    terminal_arms.append(mark_unknown(arm, "SUBSTITUTION_FAILED"))
                    continue

                frontier.add(
                    BackwardState(
                        current_function_id=edge.caller_id,
                        selected_site_id=edge.site_id,
                        arm=child,
                        suffix_edges=(edge, *state.suffix_edges),
                        depth=state.depth + 1,
                        branch_id=(state.branch_id if state.depth else edge.site_id),
                    )
                )

        if len(seen) % 64 == 0:
            await asyncio.sleep(0)

    rows = materialize_semantic_terminal_arms(terminal_arms)

    if incomplete:
        rows.append(search_limit_unresolved_row(seed, counters))

    return rows
```

Important differences from the current route enumerator:

- No complete routes are built first.
- Local terminal values stop their branch immediately.
- States are deduplicated before expensive work.
- Search is breadth-first and fair across the first caller branches.
- A root prefix is reconstructed only for output.
- Truncation is visible and prevents false completion.

---

## 7. Deduplication rules

Current record deduplication includes `correlation_id`, which keeps semantically identical route results separate. Do not simply remove correlation everywhere; some correlations represent real mutually exclusive value alternatives.

Use two levels:

### 7.1 Computation deduplication

The semantic state key in Phase 5 prevents repeated work. Route ID is excluded.

### 7.2 Output deduplication

Merge records only when all of these match:

- target site ID;
- argument index;
- value;
- origin kind;
- source file;
- source line;
- source expression/source site ID;
- operation;
- semantic alternative/set identity.

When merging:

- retain distinct witness paths up to the existing `path_cap`;
- increment a separate metadata count such as `equivalent_route_count` if known;
- combine `paths_truncated` with logical OR;
- do not merge different source lines that happen to produce the same value;
- do not merge an external fact with an unresolved fact;
- do not merge different branch-set IDs.

If it is unclear whether two arms are semantically the same, keep both evidence rows. Safety is more important than smaller output.

---

## 8. Test matrix

Every row below needs a synthetic regression test.

| Case | Expected status | Search? | LLM? | Important assertion |
| --- | --- | --- | --- | --- |
| Direct number | `RESOLVED` | No | No | Source is target line. |
| Direct string fork target | `RESOLVED` | No | No | Package validation unchanged. |
| Visible macro | `RESOLVED` | No | No | Source is macro definition. |
| Visible enum | `RESOLVED` | No | No | Source is enum definition. |
| Guarded macro | `RESOLVED` | No | No | Guard stays metadata only. |
| Local assignment | `RESOLVED` | No | No | Source is assignment. |
| Complete 2-arm assignment | `RUNTIME` | No | No | Two values, one set ID. |
| Incomplete branch | `UNRESOLVED` | Maybe | Optional | No false complete set. |
| Literal table index | `RESOLVED` | No | No | One table entry. |
| Runtime table index | `RUNTIME` | No | No | Complete table set. |
| Same-function handle/open | `RESOLVED` | No | No | Open value source used. |
| Same handle name in two functions | separate results | No | No | No cross-function collision. |
| Open-close-use | `UNRESOLVED` | No/limited | No | Stale open rejected. |
| Parameter from one caller literal | `RESOLVED` | Yes | Only if local transfer needs it | One value. |
| Parameter from callers with two values | `RUNTIME` | Yes | Bounded | Both values kept. |
| Root parameter | `EXTERNAL` | Yes | No | Boundary recorded. |
| Recognized runtime input | `RUNTIME` | Yes | Optional | Genesis recorded. |
| Undefined symbol | `UNRESOLVED` | Limited | Optional | Never runtime/exact. |
| Function pointer unsupported | `UNRESOLVED` | Limited | Optional | Failure reason. |
| Recursive call graph | complete or `UNRESOLVED` | Bounded | Bounded | No recursion error. |
| Exponential route diamond | correct semantic set | Bounded | Bounded | States, not routes, determine work. |
| State cap reached | `UNRESOLVED` | Bounded | Bounded | Exact promotion blocked. |
| Exploding branch plus shallow branch | `UNRESOLVED` if capped | Bounded | Bounded | Shallow evidence still found. |
| Unreachable AST target | unreachable evidence | No seed required | No | Present in inventory. |
| Empty preliminary detection | normal inventory | As needed | As needed | No silent zero. |
| Wrapper direct macro | `RESOLVED` | No | No | Correct wrapper arg. |
| Deep AST | normal result | No recursion crash | No | Iterative walker. |

---

## 9. Verification commands

Run from `forkproc_checker/c-visualizer`.

### 9.1 Focused tests after each phase

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/test_value_flow_status.py \
  tests/test_discovery_index.py \
  tests/test_value_flow.py \
  tests/test_llm_transfer_value_flow.py \
  tests/test_phase4_value_flow.py \
  tests/test_valueflow_pipeline.py \
  tests/test_valueflow_scheduler.py \
  tests/test_preprocess.py \
  tests/test_target_compatibility.py
```

### 9.2 Full repository gate

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

### 9.3 Static checks

Use the repository's existing formatter/linter commands if configured. Do not introduce a formatter or reformat unrelated files.

### 9.4 Required deterministic checks

- Run the diamond/fan-out stress test three times.
- Compare fact values, statuses, set IDs, and row ordering.
- Confirm state counts are stable.
- Confirm `routes_for_seed()` is not called.
- Confirm no test changes Python's recursion limit.

---

## 10. Acceptance criteria

The work is complete only when all of these are true.

### Correctness

- Existing source-proven exact values remain exact.
- A single source-proven constant or macro is exact regardless of execution guards.
- Complete multi-value alternatives are `RUNTIME`, never flattened.
- Partial alternatives are `UNRESOLVED`.
- LLM-only candidates remain unresolved.
- Undefined symbols remain unresolved.
- Local handle scope and close ordering are respected.
- Search truncation prevents exact promotion.

### Discovery

- The full configured target registry drives AST inventory in value-flow mode.
- `target_sites.csv` lists every configured AST target argument.
- Inventory does not depend on root reachability or preliminary detection.
- Untraced targets are visible as evidence.
- A target-containing successful run cannot silently report a clean zero.
- All six reviewed queue wrappers are registered at the documented argument indexes.

### Performance and safety

- Deterministic targets do not enumerate routes and do not call the LLM.
- Nonlocal resolution starts at the target and expands backward only while the value depends on callers.
- Work is deduplicated by semantic state.
- Search is breadth-first and fair across shallow caller branches.
- Per-seed state and depth caps always terminate the search.
- CPU-only search yields periodically to other async seed workers.
- Whole-tree plumbing does not depend on Python recursion depth.

### Output

- Every fact has target location and source/last-proven location.
- Runtime and external genesis/boundary are clearly different.
- Paths are retained as proof/witness paths without full enumeration.
- Existing CSV columns and file locations remain compatible.
- New compatibility fields are appended only.
- Run stats show fast-path, search, deduplication, and truncation counts.

### Diff size

- No new dependency.
- No broad module rewrite.
- No change to the old resolver implementation beyond shared crash-safe plumbing needed by both modes.
- No removal of the old route enumerator in the first patch.
- No unrelated cleanup or formatting.

---

## 11. Stop conditions and rollback points

Stop implementation and investigate before continuing if any of these happens:

- A previously exact, source-proven fixture becomes runtime or unresolved.
- A previously retained alternative disappears.
- A capped search returns `RESOLVED`.
- LLM call count increases for a deterministic fixture.
- Inventory count decreases for the same parsed fixture.
- Existing compatibility CSV columns move or disappear.
- Same-named local handles begin sharing opens across functions.
- Search output changes across identical runs.
- The implementation requires reading prohibited legacy or proprietary files.

Each phase is independently reversible:

- Phase 1 changes only traversal mechanics and two defensive guards.
- Phase 2 changes inventory/config selection and adds one CSV.
- Phase 3 changes classification policy.
- Phase 4 adds the deterministic dispatch fast path.
- Phase 5 changes only the nonlocal transfer search path while retaining the old route method for rollback reference.
- Phase 6 adds semantic/provenance output behavior.
- Phase 7 is test-first and may require no production edit.
- Phase 8 is registry-only plus metadata handling.
- Phase 9 is additive telemetry/output wiring.

Do not proceed to the next phase until the focused gate for the current phase passes.

---

## 12. Final implementation handoff requirements

The implementation model must report:

1. Exact files changed.
2. Which phases were completed.
3. Tests added for every fixed failure.
4. Focused and full-suite results.
5. Before/after state-expansion and LLM-call counts for synthetic stress fixtures.
6. Any behavior intentionally left unresolved.
7. Whether the handle-scope report reproduced; if it did not, explicitly say no production handle-scope change was made.
8. Whether any safety cap was hit during verification.
9. Confirmation that neither `forkproc_checker/build_index.py` nor `/home/chukyu` was read.

Stop when the acceptance criteria pass. Do not add further refactors, configuration systems, dashboards, or cleanup in the same change.
