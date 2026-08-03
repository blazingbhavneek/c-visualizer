# Minimal usage

Run commands from the repository root with Bash.

## 1. Configuration

Edit this block once, then paste it into your terminal:

```bash
PROCESS_ROOT=/mnt/common/Code/c-repo/test_scada/processes
MODEL_BASE_URL=http://43.235.149.172:43029/v1
MODEL_NAME=nvidia/Gemma-4-31B-IT-NVFP4
MODEL_API_KEY=EMPTY
WIKI_URL=http://127.0.0.1:8000/llm-wiki/moove/api/ask
CONCURRENCY=8

export TRACER_LLM_PROVIDER=openai
export TRACER_LLM_BASE_URL="$MODEL_BASE_URL"
export TRACER_LLM_MODEL="$MODEL_NAME"
export TRACER_LLM_API_KEY="$MODEL_API_KEY"
export FUNCTION_SUMMARY_API_KEY="$MODEL_API_KEY"

SUMMARY_ARGS=(
  --summarize-functions
  --summary-model "$MODEL_NAME"
  --summary-base-url "$MODEL_BASE_URL"
  --wiki-url "$WIKI_URL"
  --summary-concurrency "$CONCURRENCY"
)
```

`WIKI_URL` must be the full llm-wiki ask endpoint. Change `moove` to the
database selected in llm-wiki.

For an offline test, replace `--wiki-url "$WIKI_URL"` in `SUMMARY_ARGS` with:

```bash
--wiki-placeholder
```

## 2. Run modes

### One process

```bash
.venv/bin/python project_aware.py \
  --project "$PROCESS_ROOT/proc_boiler" \
  "${SUMMARY_ARGS[@]}"
```

### Explicit list of processes

```bash
.venv/bin/python project_aware.py \
  --projects "$PROCESS_ROOT/proc_hvac" "$PROCESS_ROOT/proc_pipeline" \
  --group-name hvac-pipeline \
  --continue-on-error \
  "${SUMMARY_ARGS[@]}"
```

### Combine processes already run separately

```bash
.venv/bin/python project_aware.py \
  --combine-runs combined-three \
  --combine-processes proc_boiler proc_hvac proc_pipeline
```

Omit `--combine-processes ...` to combine every process that has a saved
snapshot.

### Recursively run every process under a folder

A process is discovered when its directory contains a `Makefile`.

```bash
.venv/bin/python project_aware.py \
  --process-folder "$PROCESS_ROOT" \
  --group-name all-processes \
  --continue-on-error \
  "${SUMMARY_ARGS[@]}"
```

## 3. Useful switches

- Full interaction tracing is the default. Do not add `--index-only` for a
  real interaction run.
- Add `--index-only` to build only the complete source/function graph and
  summaries, without target-variable tracing.
- Omit `"${SUMMARY_ARGS[@]}"` and add `--skip-function-summaries` to run
  without function-summary LLM calls.
- Set `FUNCTION_SUMMARY_CACHE=0` to force summary regeneration.
- Set `VISUALIZER_RESULTS_ROOT=/path/to/results` to change the output folder.

### Output folder per project

```bash
--output-root /work/g-svm
```

Everything that run writes goes below it — `results/csv_results/`,
`pickle_data/`, `logs/` — so two projects can be analyzed at the same time
without sharing a CSV or a snapshot folder. Without the flag the repository's
own `results/` is used, as before.

### Headers the Makefile does not name

Discovery looks for header folders (`include`, `inc`, `common`, `headers`, …,
or any folder with loose `.h` files and no Makefile of its own) up to two
levels above the process:

```bash
--include-levels 3          # search further up (0 = Makefile -I only)
--include-dir /work/shared-headers   # repeatable, searched first
```

They join the `#include` search path only; a header still enters the project
when something actually includes it.

### Concurrency

```bash
--trace-concurrency 8       # target paths traced at once (default 4)
```

Each one runs the LLM call in its own worker process, so raise it with the
memory on the machine in mind. Finished paths are recorded per path, so an
interrupted run resumes exactly where it stopped.

### Adding targets to a project already run

```bash
--targets /work/g-svm/targets-v2.json
```

Paths already traced are skipped and the new ones are appended to the same CSV;
the snapshot that comes out contains both the old and the new results.

## 4. Summaries on their own

Fill in the function summaries of results that already exist — no re-parse, no
source tree needed, only the results folder:

```bash
.venv/bin/python summarize_run.py \
  --results-root /work/g-svm/results/csv_results \
  --summary-model "$MODEL_NAME" --summary-base-url "$MODEL_BASE_URL" \
  --wiki-url "$WIKI_URL"
```

Only functions whose summary is still empty are sent to the model, and each
snapshot is rewritten in place, keeping its run id. Add `--process NAME`,
`--run RUN_ID`, `--all-runs` or `--graph path/to/graph.json` to narrow it, and
`--redo-all` to regenerate summaries that already exist.

## 5. Open a result

```bash
.venv/bin/python frontend/server.py --group all-processes
```

For a project with its own `--output-root`:

```bash
.venv/bin/python frontend/server.py --results-root /work/g-svm/results/csv_results
```

Open `http://127.0.0.1:8765`. In the graph view the top-left panel switches the
process plane between **tree** and **DAG** (the DAG draws a reused function once
with an edge per caller) and reveals functions that are never called anywhere.
