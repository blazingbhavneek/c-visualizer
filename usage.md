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

## 4. Open a result

```bash
.venv/bin/python frontend/server.py --group all-processes
```

Open `http://127.0.0.1:8765`.
