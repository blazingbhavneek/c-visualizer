# Handoff: fix_plan.md implementation (roots, callbacks, cross-process, value-flow F1–F8)

Implementation of `fix_plan.md` for the c-visualizer discovery pipeline.
This document records what is done, what remains, and the exact steps to
finish. All commands run from `forkproc_checker/c-visualizer`.

## Environment / commands

- Run everything with `uv run python -m pytest ...` (plain `pytest` and the
  system `.venv` from `forkproc_checker/` do not have the right deps).
- Focused suite (the one that must stay green):

  ```bash
  uv run python -m pytest -q \
    tests/test_preprocess.py tests/test_root_discovery.py \
    tests/test_callback_resolution.py tests/test_cross_process.py \
    tests/test_value_flow.py tests/test_discovery_index.py \
    tests/test_visualizer_export.py tests/test_valueflow_pipeline.py \
    tests/test_valueflow_scheduler.py tests/test_aggregate_index.py \
    tests/test_no_target_pipeline.py tests/test_compare_discovery.py \
    tests/test_resolver_parity.py tests/test_phase4_value_flow.py
  ```

  Status at handoff: **97 passed**. This command supersedes the Phase-0
  baseline command (45 tests); this work added 42 new tests
  (12 root, 11 callback, 7 cross-process, 12 phase4).
- Pre-existing failures, NOT caused by this work (verified via `git stash`
  on a clean tree): `tests/test_wiki_graph.py` and
  `tests/test_function_summaries.py` — they read stale snapshots under
  `results/csv_results/visualizer` and/or need the LLM endpoint.
- Production run of one process (syntax-only, no LLM):

  ```bash
  uv run python project_aware.py --project /home/chukyu/t-dyn/src/dyn730 \
    --resolver valueflow --skip-function-summaries \
    --llm-base-url http://127.0.0.1:9/v1 --llm-api-key EMPTY
  ```

  Batch form used for the 7 acceptance processes:

  ```bash
  uv run python project_aware.py --projects \
    /home/chukyu/t-dyn/src/dyn730 /home/chukyu/t-dyn/src/dyn710 \
    /home/chukyu/t-cha/src/cha702 /home/chukyu/t-tmm/src/tmm200d \
    /home/chukyu/t-dif/src/dif901 /home/chukyu/t-dif/src/libdif \
    /home/chukyu/t-svm/src/svm000 \
    --resolver valueflow --skip-function-summaries \
    --llm-base-url http://127.0.0.1:9/v1 --llm-api-key EMPTY \
    --continue-on-error
  ```

- Corpus roots: `/home/chukyu/t-dyn`, `t-cha`, `t-dif`, `t-dxi`, `t-tmm`,
  `t-sim`, `t-svm`, `t-rep` (agent-6 scope `t-sim`/`t-svm`/`t-rep` is still
  unrun).
- Baseline artifacts: `results/fix_baseline/` (phase0 test output, phase1
  batch log).

## Done

### Phase 0 — baseline
Recorded. 45 focused tests passed before changes.

### Phase 1 — root discovery (complete, production-accepted)
- `helpers/Preprocess/preprocess.py`
  - `scan_root_candidates()` raw byte scanner (definitions, prototypes,
    calls, `#if 0` inactive definitions). Diagnostics only, never an
    authority for roots.
  - `validate_root_tree()` — accepted names with a real body count as roots;
    prototype-only does not.
  - Root-aware variant selection in `_clean_file_content()`: tries
    `normal` then `fallback_guarded` (guarded `_NO_PROTO`/`NOP` undefines
    only when the Makefile does not control them) whenever the initial tree
    errors OR an expected root is missing/malformed, even with a clean
    parse. Selects by (root score, error count); records
    `root_variant`, `root_validation`, `root_failure_reason`,
    `root_candidates`, `variants_tried` in per-file metadata.
- `makefile_resolver/makefile_resolver.py`
  - `return_project_mapping()` now returns a third member: canonical
    absolute SRCS paths.
  - Duplicate-basename sources no longer overwrite each other: the first
    owner keeps the plain key, later duplicates get `dirname/name`.
  - v6 pickle cache helpers `load_project_structure_cache()` /
    `save_project_structure_cache()`; old two-tuple caches are rejected and
    re-resolved (no stale root paths).
  - Makefile read is now `encoding="latin-1"` (byte-safe), was
    `errors="ignore"`.
- `project_aware.py`
  - Path-keyed process-source membership (`_is_process_source`), basename
    fallback only when no SRCS paths exist.
  - `ROOT_DIAGNOSTICS` state: `root_state` OK / ROOT_PARSE_FAILURE /
    NO_PROCESS_ROOT, per-file diagnostics, raw candidates, parse-health
    counts. Exposed to the visualizer collector and to discovery metadata.
  - Silent `entry_function_name or "main"` removed from resolver input
    (display seams in collector/resolver keep the legacy default).
- `visualizer_export.py`: `root_diagnostics` in graph.json
  `process.root_diagnostics`.
- Tests: `tests/test_root_discovery.py` (12 tests, all plan 1.x unit cases).
- Production acceptance (verified in `results/fix_baseline/phase1_runs`):
  - dyn730, dyn710, cha702, svm000: `main` in entry_points, state OK.
  - `dyn730Main.c:230 -> dyn730Initialize` and `cha702Main.c:278 ->
    cha702AddEV` edges present in the latest graph.json.
  - tmm200d and dif901 keep all four PMF lifecycle roots.
  - libdif correctly NO_PROCESS_ROOT.

### Phase 2 — callbacks (code complete, production check pending rerun)
- `call_graph/call_graph.py`
  - Callback extraction rewritten: `args_node.named_children` with one-based
    positions (old code walked all children and used `idx / 2`, which
    mis-positioned and double-added plain identifiers).
  - `_unwrap_value_node()` handles cast, parenthesized, and
    `pointer_expression`/`unary_expression` (this grammar names `&x`
    `pointer_expression`, not `unary_expression`).
  - `_resolve_value_alias()`: object-like macro alias chains; function-like
    value aliases, `##`, `#`, `__VA_ARGS__` are recorded as diagnostics,
    never guessed.
  - `_callback_registrar()` + `_map_registrar_position()`: wrapper macros
    like `REGISTER(E, CB, D) pmf_addevent(E, CB, D)` apply the configured
    positions of the expanded API, mapping through the macro signature;
    ambiguous/reordered/pasting wrappers produce a diagnostic record with
    no edge.
  - Macros are now collected from `.c` files too (headers still win on
    name collisions).
  - `_get_expanded_macro_name()` fixed: bare tokens parse as
    `translation_unit > expression_statement`; bare calls parse as ERROR
    without a statement terminator (expansion parsing appends `;`).
    `_collapse_single_named()` does the unwrapping.
  - `CallSite.callback_records`: spelling, canonical, raw text, byte range,
    registrar, registrar line/file, diagnostic, node.
- `call_graph/data_classes.py`: `callback_records` field.
- `value_flow/resolver.py`
  - `_build_callback_edges()` uses canonical IDs as `callee_id`, keeps the
    raw node in `CallerEdge.callback_meta` (provenance), dedupes per site by
    canonical ID, `call_function` = canonical name.
  - `_compute_reachability()` now also maintains `direct_reachable` and
    `callback_only`; `reachability_kind()` classifies DIRECT_ROOT /
    CALLBACK.
- `json_data/function_callback_info.json`: added `SimAddSemCallback`
  (prototype verified in `/home/chukyu/t-sim/include/sim_util.h`, callback
  position 2) and `MmiAddEvent` (no checked-in prototype; position 2
  verified from corpus call sites in dyn780/700/761/cha702).
- Tests: `tests/test_callback_resolution.py` (11 tests covering plan 2.x
  fixtures 1–10 plus the registry check).
- PENDING: production rerun to verify the cha702 callback path
  (`cha702Main.c:278 -> cha702AddEV.c:55 pmf_addevent(..., cha702Event, ...)
  -> cha702Event.c:974` target row with `reachability=CALLBACK` and nonzero
  path) and one Xt/Motif or SimAddSemCallback case from the 52-row callback
  audit. The phase-1 batch ran BEFORE the callback fix.

### Phase 3 — cross-process (code complete, production check pending rerun)
- `discovery_index.py`
  - Schema v2. `NormalizedDiscoveryFact.reachability` (default UNKNOWN).
  - EVIDENCE_COLUMNS gain `reachability`, `evidence_process`,
    `owner_process`, `owner_kind`. Old CSVs without the columns read as
    UNKNOWN and are never treated as proven dead code.
  - `classify_reachability(resolver_state, *, in_process, caller_id)`:
    OUT_OF_PROCESS_SCOPE / DIRECT_ROOT / CALLBACK / ROOT_PARSE_FAILURE /
    NO_PROCESS_ROOT / UNREACHABLE_IN_PROCESS / UNKNOWN (missing
    resolver_state).
  - `valueflow_records_to_facts(..., resolver_state)` classifies every row;
    LOCAL_BACKWALK facts override to REACH_LOCAL_BACKWALK.
  - Exact promotion gate: `status == EXACT and in_process and reachability
    in {DIRECT_ROOT, CALLBACK}`; UNKNOWN (legacy) keeps historical
    promotion; LOCAL_BACKWALK promotes only when
    `root_diagnostics.root_state == "OK"`.
  - `_unreachable_facts` emits explicit reachability per row (root failures
    no longer blanket-UNREACHABLE).
- `aggregate_index.py`
  - `_load_process_manifest()` from index metadata (canonical absolute
    process roots; `lib*` = library; executable = has accepted roots).
  - `_owner_for_path()` longest-prefix ownership, order-independent.
  - `_owner_resolution_statuses()` reads the owner's own facts:
    `resolved` (EXACT + root-proven), `present`, absent.
  - `classify_cross_process_rows()` upgrades OUT_OF_PROCESS_SCOPE rows to
    CROSS_PROCESS_CALLER when a manifest owner exists; writes
    `cross_process_callers.csv` (target_site_file, target_site_line,
    target_function, observed_from_process, owner_process, owner_kind,
    owner_resolution_status, owner_reachability); aggregate metadata gains
    `cross_process_caller_rows`, `out_of_process_scope_rows`,
    `unresolved_owner_rows`.
  - Cross-process rows never enter the exact JSON indexes (per-process gate
    + aggregate union of per-process exact indexes; `_record_key` dedupe by
    physical site/operation/value already dedupes owner rows).
- `analysis/step0.py`: `CVIZ_CROSS_PROCESS` gap category, reported
  separately from `CVIZ_UNREACHABLE`.
- `analysis/step1.py`: `CVisualizerSite.cross_process` flag; report
  excludes cross-process sites from the UNREACHABLE count and counts them
  separately.
- Tests: `tests/test_cross_process.py` (7 tests: owned-resolved,
  present-unresolved, ownerless library, in-process orphan, longest-prefix
  ownership, owner-status CSV incl. old-schema tolerance, exact-promotion
  gate).
- PENDING: production rerun checks (t-dif libdif rows difGetF1Data.c:55/:66,
  t-cha libCha/ChaGetJisseki.c rows, t-svm svm000SendInt.c:288/:311 not
  inflating observers, dif901InitDllData staying ordinary unreachable).

### Phase 4 — F1–F8 (partial)

#### F1 local backwalk — DONE (code + 5 tests)
- `value_flow/resolver.py`
  - `Seed.local_backwalk` flag.
  - `_enumerate_seeds()`: unreachable enclosing functions now get a seed
    when `_locally_provable(site)` succeeds, labeled
    `launch_via="LOCAL_BACKWALK"`.
  - `_locally_provable()` / `_locally_provable_checked()` /
    `_locally_provable_argument()` / `_expression_locally_provable()`:
    literals, visible macros, local reaching definitions (recursive), and
    handles bound to exactly one same-function open (same normalized
    handle; opens closed before the target are filtered by
    `_binding_opens`). No cross-function edges, no proximity, no LLM.
  - `_resolve_seed()` tags facts with `link_method="LOCAL_BACKWALK"`
    (via `dataclasses.replace`; Fact is frozen).
- `discovery_index.py`: LOCAL_BACKWALK link_method rows get
  `reachability=LOCAL_BACKWALK`; promotion only when root state OK.
- Negative tests included (different-FCB open, closed-FCB) — both stay
  valueless.

#### F5 nested else-if arms — DONE (code + 5 tests)
- `value_flow/resolver.py`
  - `_local_reaching_definitions()` replaces the two-arm shortcut with a
    chain-root walk (`_contains`, stable node-id comparison — tree-sitter
    node wrappers are NOT identity-stable) plus the recursive
    `_collect_branch_values()` collector.
  - `else if` arms are `else_clause`-wrapped `if_statement` nodes; the
    collector normalizes `else_clause` and recurses through if links.
  - Missing else or an arm without an assignment keeps the conservative
    bail-out (returns []).
- Tests: 3-arm, 4-arm, appended-arm, missing-else conservative,
  plain if/else unchanged — all in `tests/test_phase4_value_flow.py`.

#### F3 macro/enum/non-UTF-8 — PARTIAL (implementation added)
Macros now come from active include-chain definitions, including `.c`
file-local definitions; enum lookup remains byte-preserving. Missing include
selection is exposed through `resolver.include_diagnostics`, and active
macro/enum identifiers resolve before external fallback. Remaining work is
the production-header audit and fixtures using:
1. `t-dyn/include/Dyn/DynReEneFileDef.h`, `t-dif/include/Dif.h` + `DifP.h`,
   `t-dxi/include/dxi_const.h`, `t-tmm/include/TmmFileNo.h`,
   `t-cha/include/ChaDef.h`. Keep the working contrast
   `libDynRe/DynReEneLib.c:78` as a regression test.

#### F8 string constants into forkproc — IMPLEMENTED
- Conservative literal transfer for local char buffers: direct literal
  assignment, `strcpy(dest, "literal")`, `strncpy(dest, "literal", const)`,
  branch-union of literal writes. `memset` only as initialization, never a
  process name. No sprintf/config inference.
- Emit BOUNDED_SET/EXTERNAL as appropriate; keep raw expression, buffer
  name, write sites, string set on the fact metadata.
- Production targets: `t-dyn/src/dyn600/dyn600MainProc.c:1262` expect
  {ECS-A, ECS-B} from :1227/:1233; `t-dxi/src/libdxiinside/dxi_dblcirreq.c:100`
  expect {dxi500d, dxi501d, dxi502d}.
- Note: `package_name()` in discovery_index already strips quotes, so a
  resolved `"literal"` fact promotes cleanly for forkproc.

#### F2 bounded constant tables — IMPLEMENTED
- New abstract value kind `BOUNDED_SET`; one fact per possible value with
  `origin_kind=CONST_TABLE`, `link_method=TABLE_LOOKUP`, plus metadata
  (table file/line, index expression, bound). Downstream must count them as
  one set, not N exact paths (see `_classify_valueflow_fact` — CONST_TABLE
  remains UNRESOLVED so exact indexes stay conservative).
- Declarative wrapper rules (keep in a config seam, e.g. a new
  `json_data/` registry loaded like `function_callback_info.json`):
  `DynREGetSchfno`, `DynREGetSchKKfno`, `DynREGetSchKKLCfno`,
  `DynREGetPfmfno`, `ChaGetFileInfo`, `Dxi_UpTbnFileOpen` + `DnTbn`
  equivalents, tmm000_deamon.c static table.
- Rules describe: returns-table-element vs writes-pointer-arg, table
  symbol, index argument, output argument.
- Unknown/unbounded index stays EXTERNAL/DYNAMIC.
- Tests: 16-entry DynReScheFno loop, ChaGetFileInfo TM/SV, 2-entry
  Dxi_UpTbn, 2 active tmm000 names, unbounded negative.

#### F4 wrapper output writes — IMPLEMENTED
- Declarative write-effect metadata (e.g. `ChaGetFileInfo`: writes
  arguments 3 and 4, error return -1, output = bounded TM/SV set — ties
  into F2's rule format).
- Local dataflow: track initializer `iOpenFileNo = 0`; recognize the call
  writing `&iOpenFileNo` and the `if (ret == -1) return` guard; on the
  success path kill `0`, replace with the bounded output set. If the return
  is unchecked or the rule incomplete, keep `0` as a possible value.
- Production targets: `t-cha/src/libChaLrg/ChaLrgCom.c:458,470,477`,
  `:657,663`, `:996,1008,1015`, `:1127,1133` — expect no `0` values.
- Counterexample test: error path without return keeps the initializer.

#### F6 pointer-parameter handles — IMPLEMENTED
- In `_resolve_parameter()`/`_resolve_handle()`: for a pointer parameter
  (e.g. `set_fcb`), enumerate in-tree callers via `reverse_callers`, map
  the actual argument (`&local_fcb`, pointer variables, compatible casts)
  back to its open; one result per caller/value; distinguish address-passed
  mutable pointer vs by-value scalar; no proximity fallback.
- Annotate each caller with whether it is root-reachable (missing root must
  not look like an external parameter).
- Production targets: `tmm910_gnqmnt.c:636` (callers
  tmm910_gnqset.c:284,314; open :84 FNO 2716), ChaReadRecm/ChaReadTm/
  ChaReadSv/ChaWriteRecn in `t-cha/src/libChaCom/ChaCase.c`,
  DxiEnqEvent/DxiEnqEvent2/Dxi_DnTbnFileCtrl/Dxi_FcbG users.
- Tests: multiple callers with distinct values; a caller passing a
  different FCB must not inherit the first caller's value.

#### F7 file-static FCBs — IMPLEMENTED
- Translation-unit index for file-scope `static` FCB variables:
  declaration identity, per-function opens/closes/writes, sibling uses,
  aliasing parameters. Bind an open in A to a use in B only on identical
  variable identity with no proven close/rebind in between. Keep separate
  from global lookup (same-named statics in other files must not collide).
- Production target: `t-dyn/src/libDynRe/DynReEneOutStaFunc.c:131,143`
  (`SFcbRE` opened in DynReEneOutStaGet with DynReOutStaFNO=3937, used by
  a sibling).
- Fixture: two translation units with same-named statics; only the correct
  file's open binds.

#### Phase 4 regression invariants (add explicit tests)
Reopen identity (`dxiG150d_main.c:1042` must not include the pre-reopen
FNO), branch union (`DynRePfmCSVOut.c:188` keeps both values), local branch
union (`dyn432dAdvCtrl.c:108,116,269`), cross-module header constant
(`DynReITCLock.c:83` stays 2022), type-branch values (`dxiG_cirmng.c:146`
keeps 2552 and 2554), disabled source stays inactive, runtime/config values
stay EXTERNAL/DYNAMIC.

## Phase 5 — rerun and report (NOT STARTED)

1. Rerun the full process pipeline (the `--projects` batch above, plus the
   remaining processes if the corpus run is wanted whole).
2. Rebuild per-process indexes and the aggregate
   (`aggregate_index.build_aggregate_index(...)` / existing batch runner).
3. Rerun `analysis/step0.py` and `analysis/step1.py`.
4. Reclassify the prior 225 apparent gaps: parser/root failures become
   recovered or ROOT_PARSE_FAILURE; callback cases recovered or explicit
   callback diagnostics; cross-project cases become cross-process
   evidence; genuinely dead cases stay ordinary UNREACHABLE_IN_PROCESS.
5. Add F1–F8 audit classifications to the report; never collapse
   BOUNDED_SET / LOCAL_BACKWALK / callback / root-failure / cross-process
   rows into generic UNREACHABLE.
6. Run the agent-6 scope (`/home/chukyu/t-sim`, `t-svm`, `t-rep`) or record
   it explicitly as pending in the report.
7. Compare physical site identity, not just counts.
8. Save a before/after summary: root counts/failures, callback edges and
   callback-reached targets, cross-process rows and owner resolutions,
   local-backwalk values, bounded-table values, wrapper write effects,
   pointer-parameter and file-static bindings, string-flow forkproc
   values, exact rows by process, remaining UNREACHABLE_IN_PROCESS rows.
   Baseline for comparison: `results/fix_baseline/phase1_runs/batch.log`
   plus the pre-change `results/csv_results/*` index dirs.

## Explicit acceptance still to verify after the rerun

- cha702: target row at `cha702Event.c:974` reached with
  `reachability=CALLBACK`, registrar provenance in the row metadata, and
  the registration visible in graph.json.
- One Xt/Motif or SimAddSemCallback production case from the 52-row
  callback audit.
- `t-dif/src/libdif/difGetF1Data.c:55` and `:66` classified separately from
  ordinary unreachable rows; `t-cha/src/libCha/ChaGetJisseki.c` rows
  cross-process when observed outside the owner;
  `t-svm/src/svm000/svm000SendInt.c:288` and `:311` do not inflate the
  observing process's exact counts; `dif901InitDllData` stays ordinary
  dead/unreachable.
- F1 production targets: `t-dyn/src/dyn730/dyn730Init.c:478,487`,
  `t-dif/src/dif901/dif901IntDll.c:200`,
  `t-tmm/tool/opmtool/tmmtool.c:69,76`,
  `t-cha/src/cha100d/cha100dMain.c:229`,
  `t-dyn/src/dyn710/dyn710Init.c:292` — recovered values tagged
  LOCAL_BACKWALK, no unrelated handle gains a value.
- F5 production targets: `t-dxi/src/dxi110d/dxi110d_parent.c:1582-1591`
  with target sites :1687/:1695 expect {2512, 2519, 2525};
  `t-dxi/src/libdxiinside/dxi_initmng.c:72,80` same set;
  `t-dxi/src/libdxiinside/dxi_cirmng.c:898,904` expect {2502, 2517, 2523}.

## Gotchas learned (do not re-learn)

- tree-sitter grammar here: `&x` is `pointer_expression` (not
  `unary_expression`); `else if` alternative is an `else_clause` wrapping
  the inner if; bare tokens parse as `translation_unit > expression_statement`;
  bare calls parse as ERROR without an appended `;`.
- py-tree-sitter `Node` objects are recreated per access: compare `.id`,
  never `is`.
- `Fact` is a frozen dataclass — use `dataclasses.replace`.
- `FunctionInfo` has no `.name`; use `.node.name` / `.function_id`.
- Evidence CSV `target_site_file` is source-root-relative in chukyu layout
  (source root = `/home/chukyu`); aggregate classification joins on
  `source_root / target_site_file`.
- Do not add LLM fallbacks for roots/callbacks before syntax + macro
  resolution are exhausted (plan stop condition).
- Do not broaden accepted root names or apply global macro undefines.
