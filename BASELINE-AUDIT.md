# Purchased ZIP versus this repository

Baseline inspected: `c-repo (1).zip` (file timestamps 2026-07-24).

## State before this audit

Eight purchased backend files had been modified:

| File | Material difference from the ZIP |
| --- | --- |
| `call_graph/call_graph.py` | Replaced repeated native Tree-sitter call walking with libclang-bounded source scanning; retained raw graph/registry in `State`. |
| `call_graph/gen_graph.py` | Portable result paths, safe filenames, no browser launch, and legacy Mermaid/PyVis output disabled unless `LEGACY_CALL_GRAPH_ARTIFACTS=1`. |
| `client/llm.py` | Switched from the ZIP's Ollama path to a forced OpenAI-compatible server at a different hard-coded address. This audit made the provider and address configurable. |
| `helpers/dict_to_csv.py` | Replaced the work-PC result path with portable result-root selection. |
| `models.py` | Added `SIGNAL` as a valid operation type. |
| `parser/parser_files.py` | Replaced a per-worker Tree-sitter function-slice parser with a balanced-brace scanner. |
| `project_aware.py` | Added local-project CLI mode, portable output paths, CSV resume fixes, return-value result handling, and the initial visualizer collector integration. |
| `state/load_data.py` | Fixed broken pickle writing and allowed project-specific JSON configuration directories. |

The following major items did not exist in the ZIP at all: `frontend/`,
`visualizer_export.py`, `output_paths.py`, the `test_scada/` fixture suite,
packaging/dependency files, Git history, result snapshots, and handoff/report
documents.

## Behavioral conclusion before the new implementation

- A successful reachable target trace happened to export the builder's whole
  `.c` function registry, including source functions unrelated to that target.
- It was not reliable whole-project persistence: graph construction/export was
  initiated from the per-target loop. No configured targets, or a configured
  target with no path from `main`, could leave no graph snapshot.
- Header-defined functions were skipped.
- Function source was not stored in the snapshot; the frontend reopened an
  absolute path from the analysis PC.
- Every exported function had `summary: null`. There was no llm-wiki `/ask`
  integration and no bottom-up summarization scheduler.

## Portability hazards and disposition

- **LLM address/provider:** fixed through `TRACER_LLM_*` settings; set
  `TRACER_LLM_PROVIDER=ollama` to reproduce the purchased behavior.
- **Stale absolute paths in project-structure pickles:** fixed. Cache entries are
  tied to the project root, Makefile, and source fingerprints and rebuild after
  a move/change.
- **Global environment mutation:** fixed for Makefile parsing; it no longer
  overwrites the process `HOME` or project variables.
- **`LIBS` source paths:** fixed. A `.c` file listed under `LIBS` is no longer
  rewritten as a library directory and silently lost.
- **Source viewing after copying results:** fixed through embedded source files
  and function slices, with the old filesystem behavior retained for legacy
  snapshots.
- **Machine-specific legacy batch paths:** still present below the explicit CLI
  mode for compatibility. Prefer `--project /absolute/process/path` on either
  PC.
- **Native dependencies:** do not copy `.venv` between machines. Recreate it
  from `requirements.txt`; the host also needs a C compiler and `unifdef`.
- **Duplicate basenames:** the legacy data model still uses filenames in several
  identities. Projects containing two compiled source files with the same
  basename remain a known ambiguity and require a larger identity migration.

## Result after this audit

The graph is now built and checkpointed before target tracing, all discovered
`.c`/`.h` definitions and isolated functions are registered, analyzed inputs
are embedded, and optional summaries run dependency-layer by dependency-layer
from leaves toward `main`. Recursive strongly connected components are handled
without deadlock. External/configured library calls are enriched through the
configured llm-wiki endpoint before each model summary.
