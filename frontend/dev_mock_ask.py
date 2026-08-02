#!/usr/bin/env python3
"""Canned SSE replay for the chat contract in coordinate.md §3.

The frontend is built against this, not against the real agent: it needs no
model endpoint, no API key and no retrieval index, but it emits the exact
event sequence and payload shapes the real backend will emit, with realistic
timing.  Every id, path, source snippet and resource in the replay is read out
of a real ``graph.json`` snapshot, so the UI is exercised with real data.

    python frontend/dev_mock_ask.py --port 8765

It subclasses the production handler, so /api/runs, /api/graph and /api/source
behave exactly as they do in `server.py` and one process serves everything.

Deliberately stdlib-only and deliberately dumb: it does not understand the
question.  It picks the snapshot region with the richest trace evidence and
replays that.  Its job is to make the UI's streaming, markdown, citation and
reveal-in-graph paths reachable, not to be correct.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
import uuid
from urllib.parse import quote
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path

from server import VisualizerHandler, default_results_root, static_root

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from wiki import graphops as G
from wiki.corpus import Corpus
from wiki.present import build_answer, citation


# --------------------------------------------------------------------- replay

# Progress events are emitted with these gaps so the activity log visibly
# streams rather than appearing all at once.  Tuned to feel like the real
# agent: search is quick, subagents take a while, compiling is the long tail.
STEP_DELAY = 0.45
ANSWER_DELAY = 0.9


class Replay:
    """One canned research run, assembled from a real snapshot.

    Evidence is built with `wiki.graphops` and `wiki.present` — the same code
    the real agent uses — so the frontend is developed against the true payload
    shape rather than an approximation of it.  A hand-rolled copy here already
    drifted once: it read the callback label's trailing range as the callback's
    own and emitted `main -> bo_on_trip -> bo_on_trip -> ...`.
    """

    def __init__(self, snapshot: dict, question: str, lang: str, mode: str):
        self.question = question
        self.lang = lang
        self.mode = mode
        self.process_name = snapshot["process"]["name"]
        self.corpus = Corpus()
        self.corpus.add_snapshot(snapshot)
        self.snapshot = snapshot

    def paths(self, limit: int = 3):
        found = []
        for trace in self.corpus.traces:
            path = G.resolve_trace(self.corpus, trace)
            if path is not None:
                found.append(path)
            if len(found) >= limit:
                break
        return found

    def cited(self, paths, limit: int = 6) -> list[dict]:
        seen: dict[str, dict] = {}
        for path in paths:
            for step in path.steps:
                function = self.corpus.function(step.function_id) if step.function_id else None
                if function and function.id not in seen:
                    seen[function.id] = citation(function, self.process_name)
        return list(seen.values())[:limit]

    def resources(self, limit: int = 4) -> list[str]:
        keys = []
        for interaction in self.corpus.interactions:
            if interaction.resource_key not in keys:
                keys.append(interaction.resource_key)
            if len(keys) >= limit:
                break
        return keys

    def answer_text(self, cited, paths, resource_keys) -> str:
        """Markdown exercising every renderer the answer body needs."""
        japanese = self.lang != "en"
        link = lambda item: f"[{item['file_name']}:{item['start_line']}-{item['end_line']}]" \
                            f"(cg://function/{item['id']})"
        body = [
            ("## 概要\n\n" if japanese else "## Overview\n\n"),
            (
                f"`{self.process_name}` では、次の経路でデーモン API に到達します。\n\n"
                if japanese
                else f"In `{self.process_name}` the daemon API is reached as follows.\n\n"
            ),
        ]
        if cited:
            body.append(
                f"起点は {link(cited[0])} の `{cited[0]['name']}` です。\n\n"
                if japanese
                else f"The entry point is `{cited[0]['name']}` at {link(cited[0])}.\n\n"
            )
        if paths:
            body.append("### 呼び出し経路\n\n" if japanese else "### Invocation paths\n\n")
            for position, path in enumerate(paths, start=1):
                body.append(f"{position}. [{path.label}](cg://path/{path.id})\n")
            body.append("\n")
        if resource_keys:
            body.append("### デーモン資源\n\n" if japanese else "### Daemon resources\n\n")
            body.append("| 資源 | 種別 |\n|---|---|\n" if japanese else "| Resource | Kind |\n|---|---|\n")
            for key in resource_keys:
                resource = self.corpus.resource(key)
                if resource:
                    body.append(
                        f"| [{resource.name}](cg://resource/{quote(key)}) | `{resource.kind}` |\n"
                    )
            body.append("\n")
        body.append(
            "```c\n/* コールバック経由のホップは通常の呼び出しとは別に扱われる */\n"
            "scf_evt_register(3000, bo_on_trip);\n```\n\n"
            if japanese
            else "```c\n/* callback hops are not plain calls */\n"
            "scf_evt_register(3000, bo_on_trip);\n```\n\n"
        )
        body.append(
            "> これはモック応答です。実際のエージェントはまだ接続されていません。\n"
            if japanese
            else "> This is a mock answer. The real agent is not wired up yet.\n"
        )
        return "".join(body)

    # -- the event stream --------------------------------------------------

    def events(self):
        run_id = f"run:{uuid.uuid4().hex[:12]}"
        yield "run", {"run_id": run_id, "started_at": time.time()}

        paths = self.paths()
        cited = self.cited(paths)
        resources = self.resources()

        yield "search", {"query": self.question[:80], "phase": "main"}
        yield "candidates", {
            "items": [
                {
                    "handle": f"F{position + 1}",
                    "name": item["name"],
                    "file": item["file_name"],
                    "process": item["process"],
                    "kind": "function",
                }
                for position, item in enumerate(cited)
            ]
        }
        yield "route", {"decision": self.mode, "reason": "mock replay"}

        if self.mode == "fast" or not cited:
            yield "compiling", {}
            yield "answer", self._answer(cited, paths, resources, subagents=0, elapsed_ms=1200)
            return

        starts = cited[:3]
        yield "subagents_spawned", {
            "starts": [
                {"handle": f"F{position + 1}", "name": item["name"], "file": item["file_name"], "process": item["process"]}
                for position, item in enumerate(starts)
            ]
        }

        for position, start in enumerate(starts, start=1):
            yield "subagent_start", {
                "agent": position,
                "node": {"handle": f"F{position}", "name": start["name"], "file": start["file_name"], "process": start["process"]},
                "sub_question": f"{start['name']} の役割",
            }
            yield "read", {
                "agent": position,
                "handle": f"F{position}",
                "name": start["name"],
                "file": start["file_name"],
                "start_line": start["start_line"],
                "end_line": start["end_line"],
            }
            yield "follow_link", {
                "agent": position,
                "handle": f"F{position}",
                "name": start["name"],
                "direction": "callees" if position % 2 else "callers",
            }
            if position == 1 and resources:
                yield "follow_link", {
                    "agent": position,
                    "handle": f"F{position}",
                    "name": start["name"],
                    "direction": "resources",
                }
            yield "subagent_done", {"agent": position, "cited": [f"F{position}"]}

        yield "compiling", {}
        yield "answer", self._answer(
            cited, paths, resources, subagents=len(starts), elapsed_ms=18400
        )

    def _answer(self, cited, paths, resource_keys, *, subagents: int, elapsed_ms: int) -> dict:
        """Assembled by `wiki.present.build_answer`, exactly as the agent does."""
        return build_answer(
            self.answer_text(cited, paths, resource_keys),
            corpus=self.corpus,
            cited_ids=[item["id"] for item in cited],
            paths=paths,
            resource_keys=resource_keys,
            process=self.process_name,
            stats={"elapsed_ms": elapsed_ms, "subagents": subagents, "mock": True},
        )


# --------------------------------------------------------------------- server

_cancelled: set[str] = set()
_cancelled_lock = threading.Lock()


class MockAskHandler(VisualizerHandler):
    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _pick_snapshot(self, runs: dict) -> dict | None:
        """Prefer a caller-selected run that actually carries trace evidence."""
        candidates = list((runs or {}).items())
        if not candidates:
            candidates = [
                (run["process_name"], run["run_id"])
                for run in self._runs()
            ]
        best = None
        for process_name, run_id in candidates:
            graph = self._load_graph(str(process_name), str(run_id))
            if not graph:
                continue
            score = (len(graph.get("traces", [])), len(graph.get("interactions", [])))
            if best is None or score > best[0]:
                best = (score, graph)
        return best[1] if best else None

    def do_POST(self):
        if self.path == "/api/ask/cancel":
            body = self._read_body()
            run_id = str(body.get("run_id") or "")
            with _cancelled_lock:
                _cancelled.add(run_id)
            self._send_json({"cancelled": run_id})
            return

        if self.path != "/api/ask/stream":
            self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
            return

        body = self._read_body()
        question = str(body.get("question") or "").strip() or "(empty question)"
        snapshot = self._pick_snapshot(body.get("runs") or {})

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        if snapshot is None:
            self._emit("error", {"message": "No graph snapshot available to mock against."})
            return

        replay = Replay(
            snapshot,
            question,
            lang=str(body.get("lang") or "ja"),
            mode=str(body.get("mode") or "deep"),
        )

        run_id = None
        try:
            for event, payload in replay.events():
                if event == "run":
                    run_id = payload["run_id"]
                with _cancelled_lock:
                    stopped = run_id is not None and run_id in _cancelled
                if stopped:
                    self._emit("cancelled", {"run_id": run_id})
                    return
                self._emit(event, payload)
                time.sleep(ANSWER_DELAY if event == "compiling" else STEP_DELAY)
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            if run_id:
                with _cancelled_lock:
                    _cancelled.discard(run_id)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/wiki/status":
            self._send_json(
                {
                    "ready": True,
                    "indexing": False,
                    "indexed_functions": 0,
                    "embed_model": "(mock)",
                    "rerank_model": "(mock)",
                    "llm_model": "(mock)",
                    "mock": True,
                    "error": None,
                }
            )
            return
        return super().do_GET()

    def _emit(self, event: str, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False)
        self.wfile.write(f"event: {event}\ndata: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def log_message(self, fmt, *args):
        if "/api/ask" in (self.path or ""):
            super().log_message(fmt, *args)


def main():
    parser = argparse.ArgumentParser(description="Mock chat backend for frontend development.")
    parser.add_argument("--results-root", type=Path, default=default_results_root())
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    MockAskHandler.results_root = args.results_root.resolve()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), MockAskHandler)
    print(f"Mock chat API: http://127.0.0.1:{args.port}")
    print(f"Reading snapshots from: {MockAskHandler.results_root / 'visualizer'}")
    print("POST /api/ask/stream replays a canned research run. No model is called.")
    if static_root() == Path(__file__).resolve().parent:
        print("No frontend/dist build - use `npm run dev` on :5173, which proxies here.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nMock stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
