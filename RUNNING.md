# Running the visualizer with chat

## 1. Model endpoints

Chat needs three OpenAI-compatible endpoints. Embedding and rerank are local
vLLM; the chat model is remote.

```bash
export WIKI_EMBED_BASE_URL=http://localhost:8000
export WIKI_EMBED_MODEL=Qwen/Qwen3-Embedding-0.6B

export WIKI_RERANK_BASE_URL=http://localhost:8001
export WIKI_RERANK_MODEL=BAAI/bge-reranker-v2-m3

export WIKI_LLM_BASE_URL=216.193.128.133:42497/v1
export WIKI_LLM_MODEL=nvidia/Gemma-4-31B-IT-NVFP4
```

A base URL may be written with or without the scheme and with or without a
trailing `/v1`; all four forms normalise to the same thing.

To keep these out of your shell, put the same keys in `wiki.config.json` at the
repo root (without the `WIKI_` prefix, lowercased) — environment wins over the
file.

Check what is actually up before assuming:

```bash
python -c "
from wiki.embed import discover
for e in discover(['http://localhost:8000','http://localhost:8001'])['endpoints']:
    print(e)"
```

Nothing is mandatory. With no chat model, structural questions still work; with
no embedding endpoint, retrieval falls back to BM25. `/api/wiki/status` reports
exactly which lanes are live.

## 2. Development (two processes, hot reload)

```bash
# terminal 1 — API on :8765
python frontend/server.py --port 8765

# terminal 2 — UI on :5173, proxies /api to :8765
cd frontend && npm run dev
```

Open <http://127.0.0.1:5173>.

> A 500 from `/api/*` in dev almost always means `server.py` is not running —
> Vite's proxy returns 500 on connection refused, which looks like an app error
> and is not.

## 3. Single process (what you'd demo)

```bash
cd frontend && npm run build && cd ..
python frontend/server.py --port 8765
```

Open <http://127.0.0.1:8765>. `server.py` serves `frontend/dist/` when it
exists, so this is one process for UI and API both.

## 4. Without any model

```bash
python frontend/server.py --port 8765 --no-chat   # graph browsing only
python frontend/dev_mock_ask.py --port 8765       # canned chat, no model
```

`dev_mock_ask.py` replays a scripted research run built from real snapshot
data. Useful for frontend work and for checking the UI without burning GPU.

## 5. Checking it works

```bash
# lanes and index state — do this first
curl -s localhost:8765/api/wiki/status | python -m json.tool
```

Expect `ready: true`, `indexed_functions: 1115`, `dense: true`,
`reranker: true`. The index warms in a background thread at startup and takes
about 12s cold, 0.2s afterwards from `.wiki_cache/`.

```bash
# structural question — no model involved, answers in milliseconds
curl -s -N -X POST localhost:8765/api/ask/stream \
  -H 'Content-Type: application/json' \
  -d '{"question":"bo_shed_load を呼ぶのはどの関数ですか","lang":"ja"}'
```

Expect `run → route(structural) → compiling → answer`.

```bash
# research question — spawns subagents, ~25s
curl -s -N -X POST localhost:8765/api/ask/stream \
  -H 'Content-Type: application/json' \
  -d '{"question":"ボイラーのトリップが発生したとき、履歴はどのように保存されますか？","lang":"ja"}'
```

Expect `subagents_spawned`, several `read` / `follow_link`, then `answer`
carrying `cited`, `paths` and `resources`.

In the browser, the things worth confirming by eye:

- The UI comes up in Japanese; the EN toggle flips every string.
- Asking a question streams activity lines, then renders Markdown.
- The right rail fills with **出典 / 呼び出し経路 / デーモン資源**.
- A citation chip scrolls the rail to the matching card.
- **グラフで表示** switches to the graph, raises the right process plane, and
  dims everything except the cited functions.
- Chat → Graph → Chat keeps the camera position and open planes.

## 6. Tests

```bash
python -m unittest discover -s tests -q
```

`tests/test_value_flow.py` covers syntax-only resolution, callback reachability,
handle linking, reopen semantics, external origins, return-use caching, and all
three CSV outputs. `tests/test_wiki_graph.py` exercises the chat layer when
visualizer snapshots are present.

## 7. Value-flow resolver against a local model

Point the tracer at any OpenAI-compatible server and run the bundled fixture:

```bash
export TRACER_LLM_BASE_URL=http://127.0.0.1:8000/v1
export TRACER_LLM_MODEL=<model-id-the-server-reports>
export TRACER_LLM_API_KEY=EMPTY

VISUALIZER_RESULTS_ROOT=/tmp/vf \
  python project_aware.py --project test_scada \
    --resolver valueflow --skip-function-summaries
```

The first line of resolver output says whether the endpoint was reachable:

```
VALUE-FLOW LLM READY: http://127.0.0.1:8000/v1 model qwen2.5-coder-7b
VALUE-FLOW LLM DISABLED (syntax-only run): ... unreachable (APIConnectionError)
```

`DISABLED` is not fatal — the run finishes syntax-only. That probe exists
because a wrong URL or model id otherwise costs the full per-query timeout on
every ambiguous expression and looks like a hang.

On the fixture, 59 of 67 facts resolve with no model at all. The model is asked
only about the cases the AST cannot answer, which is what to check afterwards:

```bash
python - <<'PY'
import csv
rows = list(csv.DictReader(open('/tmp/vf/test_scada_value_facts.csv', encoding='utf-8-sig')))
for row in rows:
    if row['resolved_by'] == 'LLM' or row['origin_kind'] == 'EXTERNAL_DATA':
        print(row['function_name'], row['target_site_line'], row['origin_kind'],
              row['type'], row['value'])
PY
```

Expected once a model is answering: the three `vf_pick_file()` rows resolve to
`0x1002`, and the discarded `scf_file_access` return gets `READF` or `WRITEF`
instead of `UNRESOLVED`. `results/csv_results/stats/<process>_VALUEFLOW_STATS.json`
records `llm_query_count` and token totals for the run.

## 8. Ports in use here

| port | what |
|---|---|
| 8000 | vLLM — `Qwen/Qwen3-Embedding-0.6B` |
| 8001 | vLLM — `BAAI/bge-reranker-v2-m3` |
| 5173 | Vite dev server |
| 8765 | `server.py` (UI + API + chat) |
