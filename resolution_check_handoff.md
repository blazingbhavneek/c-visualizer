# Handoff: manually verify Step 1 resolution correctness

## Goal

Measure which pipeline gives the correct target value at each indirect target
call, and explain why.

This is a source-code correctness audit, not another pipeline run. Every
concrete value reported by c-visualizer or legacy must be checked against the
actual source path that reaches the target call.

The final analysis must answer:

- Where was c-visualizer correct?
- Where was legacy correct?
- Where were both correct?
- Where were both wrong or incomplete?
- Where did c-visualizer overapproximate?
- Where did c-visualizer miss a valid value?
- Which resolver or call-graph/value-flow weakness caused each error?
- What concrete fixes should be made to increase c-visualizer correctness?

## Definitions

Use these terms consistently:

- Site: the exact source file path and line number containing the target call.
- Resolution: one concrete target value claimed for one site.
- Distinct value: a value counted once globally, ignoring its site.
- Correct resolution: the value is possible on at least one real source path
  reaching that exact target call under the active source/configuration.
- Overapproximation: a pipeline reports a value that cannot reach that site.
- Underapproximation: a pipeline omits a value that can reach that site.
- Undecidable: the source/configuration evidence is insufficient to prove
  either side.

Do not treat more values as better automatically. A larger set is better only
when every additional value has a real source path to that site.

## Scope

Use the latest existing Step 1 artifacts:

- report:
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/analysis/step1_results/step1.md
- machine-readable comparison:
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/analysis/step1_results/step1.json
- per-site comparison:
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/analysis/step1_results/step1_sites.csv
- c-visualizer facts:
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/results/csv_results/index/discovery_facts.csv
- legacy proof:
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/index/valueflow_proof.csv
- source root:
  /home/chukyu

Do not run the full pipeline, project_aware.py, build_index.py, or any LLM
resolution pipeline.

The current Step 1 population is approximately:

- 2,312 c-visualizer sites;
- 1,121 legacy sites;
- 1,081 sites present in both;
- 1,231 c-visualizer-only sites;
- 40 legacy-only sites;
- 1,381 c-visualizer resolutions;
- 698 legacy resolutions.

The audit must regenerate these counts from the input files. Do not assume the
numbers are unchanged if a newer result directory is supplied.

For resolution correctness, audit the union of all unique site/value claims:

- each c-visualizer site/value claim;
- each legacy site/value claim;
- duplicate claims from multiple operation labels count once when they have the
  same exact file, line, and value.

## Work distribution

The coordinator should divide the resolution claims into independent batches.
Prefer batches of 50–100 site/value claims grouped by package or source
subtree, so each subagent can reuse the same headers and conventions.

**Status: the split has been done.** See `subagents/README.md` — the full
step1 population (2519 claim rows / 2352 unique sites) is partitioned into
6 disjoint batches (agent1.md … agent6.md, each with its own
agentN_claims.csv), grouped by source subtree. Launch the 6 agents yourself;
each appends its results below the `## Results` heading in its own prompt
file.

Every batch must contain:

- a stable batch identifier;
- the exact input row identifiers;
- absolute source paths;
- no overlapping site/value claims with another subagent.

The coordinator must maintain a manifest showing that every union claim was
assigned exactly once and every assigned claim received a verdict.

Do not divide only by c-viz-only and legacy-only. Shared claims are the most
important cases because they reveal which resolver is more precise.

## Required manual procedure for every site

For each site:

1. Open the exact source file and inspect enough surrounding code to understand
   the target call and enclosing function.
2. Confirm the target function, argument position, and target expression.
3. Confirm the code is active, not inside a comment or disabled preprocessor
   branch.
4. Find every relevant assignment, open, or initialization of the value or
   handle used by the target.
5. Trace callers backward to the recognized process root, wrapper, callback,
   function-pointer registration, or source boundary.
6. Enumerate the real possible values reaching this exact site.
7. Compare that source-backed set with the c-visualizer set and legacy set.
8. Record the shortest evidence chain proving each accepted value and rejecting
   each false value.

For handle/FCB arguments, follow the handle identity precisely. Do not assume
that every open in the same function belongs to every later handle use.

For variables and helper parameters, trace:

- direct assignments;
- function arguments and return values;
- branches and loops;
- arrays and indexed access;
- structure fields;
- macros and enum constants;
- wrapper argument mappings;
- callback/function-pointer registrations.

For conditional code, record whether a value is possible under the active
source configuration. Do not mix values from unrelated architectures or
inactive branches without labeling the configuration.

## Per-claim verdicts

Assign one verdict to every pipeline claim:

- CVIZ_CORRECT_ONLY — c-viz value is source-valid; legacy omitted it or gave
  no valid value.
- LEGACY_CORRECT_ONLY — legacy value is source-valid; c-viz omitted it or
  gave no valid value.
- BOTH_CORRECT_SAME — both report the same source-valid value.
- BOTH_CORRECT_DIFFERENT — both report different values, and both are valid
  under different real source paths/configurations.
- CVIZ_OVERAPPROXIMATION — c-viz reports a value not possible at the site.
- LEGACY_OVERAPPROXIMATION — legacy reports a value not possible at the site.
- CVIZ_UNDERAPPROXIMATION — c-viz misses one or more source-valid values.
- LEGACY_UNDERAPPROXIMATION — legacy misses one or more source-valid values.
- BOTH_WRONG — neither reported value is source-valid.
- BOTH_INCOMPLETE — both report some valid values but both miss others.
- UNDECIDED — evidence is insufficient.

For a claim that is valid on one path but not another, distinguish:

- PATH_VALID — the path exists in the source and is in scope;
- CONFIG_VALID — valid only under a named preprocessor or architecture
  configuration;
- DEAD_PATH — syntactically present but disabled or unreachable in the
  relevant source configuration.

## Required evidence

Every verdict must include:

- absolute source file and line;
- exact target call;
- enclosing function;
- target argument expression;
- c-visualizer claimed value/status, if present;
- legacy claimed value/status, if present;
- source-backed expected value set;
- source lines proving the expected value(s);
- caller/root or branch path used;
- verdict and confidence;
- concise reason for accepting or rejecting each pipeline claim.

Example evidence:

  /home/chukyu/t-dif/src/dif000/dif000Main.c:428
  Target: mpf_mfs_getrec(&fcb, ...), argument 1.
  Source path: mpf_mfs_openm(&fcb, ..., DifStatusNo, ...) at line 417.
  Header: DifStatusNo = 2022 at /home/chukyu/t-dif/include/dif/Dif.h.
  Expected values: {2022}.
  c-visualizer: {2022} — correct.
  Legacy: {2022} — correct.
  Verdict: BOTH_CORRECT_SAME.
  Confidence: high.

## Error categories to record

Use one or more cause tags in addition to the verdict:

- HANDLE_IDENTITY_LOST
- HANDLE_ALIASING_TOO_BROAD
- HANDLE_BINDING_NOT_PROPAGATED
- MISSING_ASSIGNMENT_EDGE
- MISSING_CALLER_EDGE
- MISSING_CALLBACK_EDGE
- MISSED_WRAPPER_MAPPING
- MISSED_MACRO_OR_ENUM
- STALE_HEADER_OR_SOURCE
- WRONG_INCLUDE_PROVENANCE
- BRANCH_MERGE_ERROR
- LOOP_OR_ARRAY_MODEL_ERROR
- FUNCTION_POINTER_UNRESOLVED
- UNREACHABLE_ROOT_MODEL
- TARGET_SCOPE_EXCLUSION
- LEGACY_REGEX_MISS
- LEGACY_LLM_BACKWALK_ERROR
- PREPROCESSOR_CONFIGURATION
- INSUFFICIENT_EVIDENCE

The coordinator should aggregate these cause tags to produce concrete c-viz
tuning priorities, not just a list of disagreements.

## Required outputs

The coordinator must write:

/home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/analysis/resolution_check_report.md

Also write:

- analysis/resolution_check_claims.csv
- analysis/resolution_check_summary.json

Recommended CSV columns:

claim_id,site_file,site_line,target_function,argument_index,operation,argument_expression,cviz_value,legacy_value,source_expected_values,cviz_verdict,legacy_verdict,correct_pipeline,confidence,cause_tags,source_evidence,caller_or_path,notes

The CSV must contain one row per unique pipeline claim or, if using one row per
site, separate normalized columns containing all values and a complete
source-backed expected set. Do not hide multiple values in an unexplained
free-form paragraph.

The Markdown report must include:

1. Plain-English definitions of site, resolution, and distinct value.
2. The audited population and a reconciliation to the input artifacts.
3. Counts of:
   - total sites by pipeline;
   - common, c-viz-only, and legacy-only sites;
   - total resolutions by pipeline;
   - same site/value resolutions;
   - c-viz-only and legacy-only resolutions;
   - distinct values by pipeline and their overlap.
4. Correctness counts:
   - c-viz correct;
   - legacy correct;
   - both correct;
   - both wrong/incomplete;
   - undecided.
5. Separate precision and coverage measures:
   - precision = accepted reported values / all reported values;
   - coverage = accepted values / all source-backed expected values.
6. Counts by cause tag.
7. At least ten detailed examples where c-viz is correct and legacy is not.
8. At least ten detailed examples where legacy is correct and c-viz is not.
9. At least ten examples where both are correct.
10. At least ten c-viz overapproximation examples, if that category occurs.
11. Concrete recommended c-viz fixes, ranked by impact and implementation risk.

Examples must use absolute paths so they can be manually inspected.

## Important interpretation rules

- A c-viz EXACT status is not proof of source correctness.
- A legacy OK_MACRO or OK_CONST status is not proof that the selected header is
  the active one.
- UNREACHABLE means no path was found from c-viz’s recognized root; it does
  not prove the source call is dead.
- EXTERNAL and UNRESOLVED are not concrete resolutions.
- Do not count direct literal/macro cases; those belong to Step 0.
- Do not use archived /home/chukyu_exe headers as current-source evidence.
- Do not call a value correct merely because it appears somewhere in the same
  function.
- Do not call a value wrong merely because the other pipeline chose a
  different value.
- If both values are possible on distinct real paths, mark both correct and
  document the paths.
- If a value is valid only in disabled code, mark it invalid for the active
  source audit and record PREPROCESSOR_CONFIGURATION.

## Final tuning deliverable

End the report with a prioritized table:

| Priority | c-viz issue | Evidence count | Example paths | Proposed fix | Risk |
|---|---|---:|---|---|---|

The final conclusion must state whether c-viz is:

- more precise than legacy;
- more complete but less precise;
- less complete and less precise; or
- not yet decidable.

The conclusion must be based on manually verified source evidence, not raw
record counts.
