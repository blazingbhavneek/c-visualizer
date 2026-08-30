# c-visualizer analysis handoff

Read this before touching forkproc_checker/c-visualizer/analysis/.

## Purpose

We are comparing existing c-visualizer output with the existing legacy
forkproc_checker/index output. We want to measure discovery, value resolutions,
source correctness, and fixes that improve c-visualizer.

This is an existing-results analysis. Do not rerun the full c-visualizer
pipeline, project_aware.py, or build_index.py unless explicitly requested.

## Terminology

Use these definitions in every new report:

- **Site:** the exact absolute source file and line number containing the target
  call.
- **Resolution:** one concrete target value reported for one site.
- **Distinct value:** a value counted once globally, ignoring its site.
- **Direct CONST/MACRO:** the target argument itself is a literal, enum, or
  directly named macro, for example mpf_mfs_open(..., DifStatusNo, ...).
- **Indirect value-flow case:** the target argument is a variable, helper
  parameter, handle such as &fcb, field, array value, or another expression
  requiring source tracing.

Some older Step 1 tables call location + operation + argument position a site.
That is an operation-aware comparison key, not the user-facing site definition.
Always label it explicitly if used.

## Canonical inputs

    c-viz aggregate index:
    /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/results/csv_results/index

    c-viz discovery facts:
    /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/results/csv_results/index/discovery_facts.csv

    legacy aggregate index:
    /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/index

    legacy proof:
    /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/index/valueflow_proof.csv

    source:
    /home/chukyu

Prefer active headers under /home/chukyu. The legacy side may use archived
headers under /home/chukyu_exe; report that as stale provenance, not as current
source truth.

## Step 0: direct constants/macros

Canonical files:

- `step0.py`
- `step0_report.md`

`step0_report.md` is the gold, manually consolidated report. It contains the
direct comparison, the 322-record legacy-only classification, and the completed
225-record UNREACHABLE reachability audit from the long-running investigation.
Do not recreate these findings as separate `step0_no_cviz*`, `_unreach*`, or
historical Step 0 reports.

Current final-index comparison:

| Meaning | Count |
| --- | ---: |
| c-viz direct resolutions | 933 |
| legacy direct resolutions | 1,240 |
| same site/value records | 655 |
| c-viz-only records | 278 |
| legacy-only records | 585 |

The report also records that the 225 apparent same-location gaps are
`OPEN_LOCK` facts marked `UNREACHABLE`, not ordinary discovery misses. Its
completed verdict counts are:

| Verdict | Count |
| --- | ---: |
| DEAD_CODE | 85 |
| PARSE_CORRUPTION | 80 |
| CALLBACK_DISPATCH | 52 |
| CROSS_PROJECT_CALLERS_ONLY | 8 |
| **Total** | **225** |

## Step 1: indirect value-flow comparison

The runner is `step1.py`. Its report output is intentionally not checked in;
write fresh `step1.json`, `step1_sites.csv`, and `step1.md` to a new output
directory after the full pipeline completes.

No stale Step 1 result bundle is retained here. New counts must come from the
same post-pipeline snapshot for both Step 0 and Step 1.

## Long-form correctness audit — deferred

If a source-backed correctness audit is needed, start from the fresh Step 1
output and the full specification at
`/home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/resolution_check_handoff.md`.
Do not reuse deleted intermediate batches or stale counts. Never treat “more”
c-visualizer values as proof of correctness.

## File map

Completed reports/scripts:

- step0.py and step0_report.md: the single consolidated Step 0 deliverable.
- step1.py: indirect comparison runner; reports are generated after a fresh
  pipeline run in a chosen output directory.
- resolution_check_handoff.md at the c-viz root: optional full audit
  specification.

## Safe next-session checklist

1. Read this file and `resolution_check_handoff.md` when a correctness audit is
   needed.
2. After the full pipeline finishes, run Step 0 and Step 1 against the same
   fresh indexes.
3. Review fresh Step 1 output before starting any long-form source audit.
