# C repository analyzer and code-graph visualizer

This project resolves the C files selected by a process Makefile, builds a
static call graph for every discovered function, traces configured daemon/API
arguments, and writes self-contained snapshots for the React visualizer.

## Run a complete index

An index-only run does not call the legacy target-variable LLM:

```bash
.venv/bin/python project_aware.py \
  --project test_scada/processes/proc_waterworks \
  --index-only --skip-function-summaries
```

The snapshot is written under
`results/csv_results/visualizer/<process>/runs/<timestamp>/graph.json`. It
contains every resolved source/Makefile input, exact function source slices,
all static call edges, the `main` entry ID, and functions that are not reachable
from `main`. The frontend renders the latter on its unreached shelf.

## One process, many processes, and saved pipeline groups

The analyzer has four explicit process-selection modes:

```bash
# 1. One process
.venv/bin/python project_aware.py --project /src/process-a

# 2. An explicit list, run sequentially and pinned into one group
.venv/bin/python project_aware.py \
  --projects /src/process-a /src/process-b /src/process-c \
  --group-name production-line

# 3. Combine snapshots made by separate earlier commands
.venv/bin/python project_aware.py \
  --combine-runs production-line \
  --combine-processes process-a process-b process-c

# 4. Recursively discover every directory containing a Makefile, then run it
.venv/bin/python project_aware.py \
  --process-folder /src/all-processes \
  --group-name production-line --continue-on-error
```

List and folder modes run one process at a time so the analyzer's global state
is reset between processes. They then write an immutable group manifest under
`visualizer/groups/<group>/runs/<timestamp>/group.json`, referencing the exact
snapshot produced for each process. Existing-run combination chooses the newest
snapshot with interaction evidence by default; use `--run-selection latest` to
choose strictly by time. Omitting `--combine-processes` combines every process
that currently has a snapshot.

The manifest keeps function IDs in their owning process and separately joins
shared daemon resources on `(kind, name)`. This lets the frontend show
producer/consumer edges across process planes without corrupting the individual
call trees. To display only that pinned system:

```bash
.venv/bin/python frontend/server.py --group production-line
```

`--index-only` is useful for checking complete source/function coverage, but it
intentionally stops before target-variable tracing and therefore will not add
daemon-resource interactions. Omit it for the real multi-process interaction
run. Function summaries and llm-wiki lookup are orthogonal and may be enabled
for any single, list, or folder run.

## Enable bottom-up function summaries

```bash
.venv/bin/python project_aware.py \
  --project /path/to/process \
  --summarize-functions \
  --summary-model your-model \
  --summary-base-url http://llm-host:port/v1 \
  --wiki-url http://llm-wiki-host:8000/llm-wiki/moove/api/ask \
  --summary-concurrency 8
```

The analyzer summarizes leaf functions concurrently, checkpoints their
results, and then advances toward callers and `main`, supplying direct-callee
summaries as context. Recursive functions are scheduled as one strongly
connected group. Calls to external or configured special-library APIs trigger
the llm-wiki request before the summary call. Successful summaries use
`summary_status: "ready"`; service failures leave the already-written graph
usable and record `summary_error`.

Equivalent environment variables are:

- `FUNCTION_SUMMARIES=1`
- `FUNCTION_SUMMARY_MODEL`, `FUNCTION_SUMMARY_BASE_URL`,
  `FUNCTION_SUMMARY_API_KEY`
- `LLM_WIKI_ASK_URL`, `LLM_WIKI_API_KEY`
- `LLM_WIKI_PLACEHOLDER=1` for an explicit offline/no-knowledge stand-in
- `FUNCTION_SUMMARY_CONCURRENCY`, `FUNCTION_SUMMARY_TIMEOUT`

Summaries are content-addressed and reused from
`visualizer/<process>/function-summary-cache.json`. Set
`FUNCTION_SUMMARY_CACHE=0` to force regeneration.

The bundled server in `../llm-wiki-dist/llm-wiki-dist` selects its database in
the URL. With its documented defaults, the full endpoint is
`http://127.0.0.1:8000/llm-wiki/<database>/api/ask` (for example, `moove`). The
client posts `{"question": "..."}`, reads the returned `answer`, and retries
the server's temporary retryable `502`/`503` response while a cold database is
being prepared. `/api/ask/stream` is also accepted when explicitly configured.

For an offline integration test, add `--wiki-placeholder`. This keeps the same
leaf-to-root scheduling and records `wiki_status: "placeholder"`, but clearly
supplies no manual facts. Do not enable it in a real documentation run.
Summary mode requires one of `--wiki-url` or `--wiki-placeholder`, so a real run
cannot silently skip the required manual/API lookup.

## Moving between this machine and the work PC

The legacy target-variable LLM is separately configurable:

- `TRACER_LLM_PROVIDER=openai` (also accepts `vllm`) with
  `TRACER_LLM_BASE_URL`, `TRACER_LLM_API_KEY`, and `TRACER_LLM_MODEL`.
- `TRACER_LLM_PROVIDER=ollama` with `TRACER_OLLAMA_HOST` and
  `TRACER_LLM_MODEL` restores the purchased ZIP's local-Ollama behavior.

Project-structure caches include their absolute project root, Makefile
fingerprint, and source-file fingerprints. A copied or stale cache is rebuilt
instead of reusing paths from the other PC.

## Visualizer

```bash
cd frontend
npm run build
cd ..
.venv/bin/python frontend/server.py
```

Open `http://127.0.0.1:8765`.
