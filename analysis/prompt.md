# Handoff for numbered analysis reports

Use this file when refreshing an existing analysis or adding the next numbered analysis. Keep every Python script used for report `N-*.md` under `analysis/scripts/` with the same `N-` prefix.

## Refreshing `1-sites.md`

Run from `forkproc_checker/c-visualizer`:

```bash
.venv/bin/python analysis/scripts/1-compare-sites.py \
  --results-dir results_backup/csv_results6 \
  --legacy-index ../index_baseline \
  --source-root /home/chukyu \
  --write-report analysis/1-sites.md \
  --json-output analysis/1-sites-data.json
```

Then verify that the checked-in generated block is current:

```bash
.venv/bin/python analysis/scripts/1-compare-sites.py \
  --results-dir results_backup/csv_results6 \
  --legacy-index ../index_baseline \
  --source-root /home/chukyu \
  --check-report analysis/1-sites.md
```

For a newer completed run, change only `--results-dir` unless the baseline or source snapshot also changed. Do not point the script at an actively running directory: it requires the aggregate `index/discovery_facts.csv`, aggregate compatibility JSON files, and every successful process's `index/target_sites.csv` and `run_stats.json`.

The script fills only the small numeric checkpoint delimited by:

```text
<!-- BEGIN GENERATED: 1-site-comparison -->
<!-- END GENERATED: 1-site-comparison -->
```

That block contains only the machine-recomputed coverage table. Python must not write the explanation, storyline, examples, discrepancy discussion, or conclusion.

`--json-output` saves the detailed audit evidence: every legacy-only site, every shared unresolved site, every value-set disagreement, and the new-only function breakdown. The analysis agent must read that JSON and write the report prose itself. Start with the theory of how the two resolvers work, then walk the reader through discovery, resolution, and value disagreements in that order. Explain what each number means before presenting it. Keep the Markdown readable and narrative-led; use only small tables where they genuinely help, and do not turn the report into a data dump.

The same rule applies to future reports: the numbered Python script may calculate or check tables, but the agent writing `N-*.md` owns all prose and must explain why the new pipeline is better for this codebase.

## Refreshing `2-value-provenance.md`

This report is currently based on the provisional Dxi-only run
`results_backup/csv_results7`. Run from `forkproc_checker/c-visualizer`:

```bash
.venv/bin/python analysis/scripts/2-value-provenance.py \
  --results-dir results_backup/csv_results7 \
  --legacy-index ../index_baseline \
  --write-report analysis/2-value-provenance.md \
  --json-output analysis/2-value-provenance-data.json
```

Then check the generated block:

```bash
.venv/bin/python analysis/scripts/2-value-provenance.py \
  --results-dir results_backup/csv_results7 \
  --legacy-index ../index_baseline \
  --check-report analysis/2-value-provenance.md
```

When the main results run is complete, change only `--results-dir` and rerun
the report. The script checks the selected source-proven examples and runtime
warning examples against the aggregate `discovery_facts.csv`. It selects rows
by stable `(file, line)` location and must not hardcode the values or depend on
CSV row order. The agent must re-read the source examples after changing runs,
because a newer run can change both the values and the resolution status.

The script writes only the numeric checkpoint, example-value table, and
runtime-warning table between:

```text
<!-- BEGIN GENERATED: 2-value-provenance -->
<!-- END GENERATED: 2-value-provenance -->
```

The agent owns the narrative. Explain the sequence: legacy joins values by
file-scope handle, C-visualizer follows the actual path, runtime tables keep
source-backed sets, external inputs remain boundaries, and over-wide runtime
sets are still tracked as work rather than called exact wins. Keep the three
known warning sites (`DxiSndHdr.c:567`, `DxiSndHdr.c:622`, and
`DxiItcReq2.c:575`) source-reviewed and separate from the accuracy wins.

## Definitions that must stay stable

- Site identity is `(normalized source path, source line)`. The script rejects a run if two non-close target functions share one such location.
- Deduplicate sites across process snapshots. A shared-library call seen from many processes is one site.
- Exclude targets whose registry resource is `none` (`mpf_mfs_close` and `mpf_mfs_closeall` in registry 1.2).
- A broad resolved site has at least one status other than `UNRESOLVED` or `NO_TARGET`.
- An exact site has at least one `EXACT` row.
- A direct exact site has an exact row whose `source_expr` equals its `target_expression`; all other exact sites are traced.
- Compare legacy/new discovery at path and line because legacy does not preserve the callee name.
- Compare values as sets of `(operation, value)` per site. Keep `equal`, `new strict subset`, `legacy strict subset`, `partial overlap`, and `disjoint` separate.
- Treat the aggregate JSON export separately from all exact evidence. The export has an additional in-process/root-proven promotion gate.
- For the main value-density metric, both sides exclude handle-dependent record operations (`READREC`, `WRITEREC`, `GETREC`, and `UPDATEREC` families). The new side uses all remaining target functions and all discovered non-handle sites; its numerator uses fact rows with `resolution_status=RESOLVED` or `RUNTIME`.
- Classify legacy-only source lines only as obvious `#if 0`, `#ifdef NOP`, comments, missing source, or unclassified inventory omissions. Do not infer that every missing site is dead.

## Manual checks after regeneration

The prose outside the generated block is intentionally written by the analysis agent. Recheck and update it when counts or inputs change:

1. Confirm failed processes and whether legacy has sites beneath their source roots.
2. Read `../build_index.log` when available. Keep its first-pass counters (raw file, queue, and fork hits) separate from the final deduplicated site and record counts.
3. Explain `target_number->status = RUNTIME` separately from `UNRESOLVED`: count its raw rows and unique source locations, then explain that the old index either drops runtime variables or flattens possible values into static records.
4. Compare unique runtime values and `(operation, value)` pairs on the same runtime-site population. The audit JSON records both the all-runtime totals and the shared-runtime totals.
5. Use the main value-density comparison defined for this report: exclude handle-dependent record functions from both sides because legacy's file-scope handle binding multiplies values unsoundly. Count legacy non-handle values over legacy non-handle sites. Count new `RESOLVED`/`RUNTIME` values over all new non-handle sites, including new-only sites; they are not automatically `UNRESOLVED`.
6. Keep the final JSON export ratio and the legacy handle ratio as diagnostics only. Explain that the new export omits runtime evidence, while the legacy handle family inflates its apparent density through approximation. Report the percentage increase of new non-handle density over legacy non-handle density.
7. Explain that legacy can look richer because its file-scope handle matching approximates values. Do not call the ratio an accuracy score. State that the new pipeline can still have analysis errors, but keeps uncertain cases as `UNRESOLVED`, `DYNAMIC`, `EXTERNAL`, or `UNREACHABLE` instead of silently presenting guesses as exact.
8. Inspect any legacy-only line classified as `not emitted by inventory` or `missing source` before claiming live-code completeness.
9. Recheck the two value examples (`TmmSysInit.c:632` and `dyn441AtComProc.c:162`) in the JSON audit and source.
10. Recheck example rows in the aggregate facts before retaining their status/value text.
11. Reword “What changed from the old analysis” when using a run newer than `csv_results6`.

## Adding later analyses

For report `2-*.md`, use only `analysis/scripts/2-*.py`; for report `3-*.md`, use `analysis/scripts/3-*.py`, and so on. Each report should have generated markers, a command in this handoff, stable definitions, and explicit manual-review boundaries. Reuse shared repository code only when it already provides the needed semantics; do not silently depend on deleted ad-hoc scripts.
