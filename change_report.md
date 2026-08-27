# Change Report — `c-viz-diff.txt`

## 0. Correction from the first pass

The diff was first tried against branch `libs` and mostly failed to apply
(many hunks rejected). That attempt has been **fully reverted** — `libs` is
back at its original commit (`427ad01`), untouched.

The diff's actual base turned out to be `origin/main` at commit `ca343e1`
("synced to work pc"), which was **3 commits ahead of local `main`**
(`1ce864f`). Confirmed by comparing blob hashes named in the diff's `index`
lines against tree objects at each candidate commit — e.g. `process_groups.py`
base `75738bf`, `visualizer_export.py` base `5bcb7c9`, `usage.md` base
`9ea4686` all exist in `origin/main`'s tree but nowhere else locally. Local
`main` was fast-forwarded to `origin/main` (`1ce864f..ca343e1`, no local
commits lost — trivial fast-forward), and the diff applied against that.

## 1. Application method

`git apply --reject --whitespace=fix c-viz-diff.txt` on branch `main` at
`ca343e1`. Automated only — no manual edits to reconcile hunks.

## 2. Result: clean

Every text hunk applied. **Zero `.rej` files.** The only file the diff could
not update is:

- **`frontend/src/graph/model.js`** — the diff represents this file's change
  as `Binary files a/frontend/src/graph/model.js and
  frontend/src/graph/model.js differ` with no binary patch payload (git
  classified the file as binary content and the diff was generated without
  `--binary`, so there is no data to apply from). The file is unchanged, still
  at its pre-image blob `3bc733c`. Recovering this one file's change requires
  the actual target file from upstream — it cannot be reconstructed from
  this diff.

Nothing has been committed. All changes are unstaged/untracked in the working
tree on `main`.

## 3. What the diff contains

55 files touched, +118,940 / −1,516 lines in the raw diff (of which ~103,000
inserted lines, 87%, are one generated data file,
`analysis/step1_results/step1.json` — the diff is much smaller in actual
logic than the line count suggests). It bundles three feature efforts plus
one exploratory data dump:

1. **Value-flow tracing rewrite** — extends the existing `value_flow/`
   package (`resolver.py` +674 lines, `queries.py`) and rewires
   `project_aware.py` (`make_value_flow_calls`, `trace_variable`) with a
   CPU/LLM overlap scheduler (`speedup_plan.md`,
   `tests/test_valueflow_scheduler.py`). `plan.md`, the original design
   proposal, is **deleted** as superseded by the now-implemented resolver.

2. **Whole-repository "build-index" compatibility layer** — lets a
   c-visualizer batch run also emit build-index-shaped artifacts (new
   `aggregate_index.py`, `discovery_index.py`, `target_spec.py` +
   `target_specs/build_index_targets.json`) and diff them against the legacy
   regex-based reference pipeline (new `tools/compare_discovery.py`,
   `tools/analyze_index_comparison.py`). `process_groups.py` gains the
   `--source-root` plumbing this needs. `handoff.md` / `repair_handoff.md`
   record what was verified and two processes (`dyn811d`, `dyn830`) that
   still need a repair pass — see `repair_handoff.md` for the exact defects
   (`makefile_resolver/extract_includes.py:220` `None`-iterable bug,
   `project_aware.py:2293` `KeyError` on non-C dependencies). `analysis/step0*`
   and `analysis/step1*` (including the 103k-line `step1.json`) are the
   exploratory comparison run and its output.

3. **Frontend dynamic/lazy-loading rewrite** — replaces "download every
   process's full `graph.json` at startup" with a metadata-only catalog
   (`GET /api/runs`) + overview (`POST /api/overview`) + per-click fetches
   (`/api/process`, `/api/function`, `/api/library`). New read model
   `frontend/visualizer_readmodel.py` (~1,300 lines) backs new
   `frontend/server.py` endpoints; `GraphView.jsx` becomes the lazy bundle
   lifecycle owner (fetch-before-open, FIFO eviction, abort stale requests);
   `Inspector.jsx`, `App.jsx`, `api.js`, `EvidenceRail.jsx`, `wiki/serve.py`
   adjust to match. Documented in `frontend/dynamic_loading.md` and
   `frontend_dynamic_plan.md`; tested in `tests/test_visualizer_readmodel.py`.
   `frontend/src/graph/model.js` is the one file this rewrite touches that
   didn't apply (§2).

## 4. Files changed (relative to `origin/main` @ `ca343e1`)

**Modified (26 tracked files):** `README.md`, `call_graph/call_graph.py`,
`call_graph/gen_graph.py`, `client/llm.py`, `frontend/server.py`,
`frontend/src/App.jsx`, `frontend/src/api.js`,
`frontend/src/components/AnswerMarkdown.jsx`,
`frontend/src/components/EvidenceRail.jsx`,
`frontend/src/components/GraphView.jsx`,
`frontend/src/components/Inspector.jsx`, `frontend/src/graph/dag.js`,
`frontend/src/graph/layout.js`, `helpers/dict_to_csv.py`,
`makefile_resolver/extract_includes.py`, `models.py`, `process_groups.py`,
`project_aware.py`, `tests/test_process_groups.py`,
`tests/test_value_flow.py`, `tests/test_visualizer_export.py`, `usage.md`,
`value_flow/queries.py`, `value_flow/resolver.py`, `visualizer_export.py`,
`wiki/serve.py`.

**Deleted (1):** `plan.md`.

**Not applied (1):** `frontend/src/graph/model.js` (binary, see §2).

**New (23 untracked files/dirs):** `aggregate_index.py`, `analysis/`
(`step0.py`, `step0_dif900_fixed_report.md`, `step0_report.md`, `step1.py`,
`step1_results/{step1.json,step1.md,step1_sites.csv}`), `discovery_index.py`,
`frontend/dynamic_loading.md`, `frontend/visualizer_readmodel.py`,
`frontend_dynamic_plan.md`, `handoff.md`, `repair_handoff.md`,
`speedup_plan.md`, `target_spec.py`, `target_specs/build_index_targets.json`,
`tests/test_aggregate_index.py`, `tests/test_compare_discovery.py`,
`tests/test_discovery_index.py`, `tests/test_resolver_parity.py`,
`tests/test_target_compatibility.py`, `tests/test_valueflow_scheduler.py`,
`tests/test_visualizer_readmodel.py`, `tools/__init__.py`,
`tools/analyze_index_comparison.py`, `tools/compare_discovery.py`.

`git diff --stat` for the 26 tracked modifications: **2,686 insertions(+),
1,516 deletions(-)**.

## 5. Current state / next steps

- Branch `main` is fast-forwarded to `origin/main` (`ca343e1`) and now carries
  the diff's changes, uncommitted, in the working tree.
- Branch `libs` is untouched at `427ad01`.
- `c-viz-diff.txt` remains untracked at the repo root.
- Nothing has been committed or staged — review with `git diff` /
  `git status`, then decide whether to commit.
- Only open item: `frontend/src/graph/model.js` needs its target content
  sourced from wherever this diff was generated, since the diff itself can't
  supply it.
