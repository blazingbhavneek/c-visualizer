"""Serving layer: route a question, stream the result as SSE.

The handler mixin here is what `frontend/server.py` gains when the wiki
package is importable.  It is deliberately additive — every existing endpoint
behaves exactly as before, and if this import fails the visualizer still
serves graphs.

Routing is: try `structural` first (no model, milliseconds, correct by
construction), fall back to the research agent.  See `structural.py` for why
that order rather than sending everything to the agent.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from http import HTTPStatus
from pathlib import Path
from typing import Any

from . import structural
from .agent import Researcher, Stopped
from .config import Settings
from .corpus import SnapshotError, load_corpus, newest_runs
from .embed import build_clients
from .index import RetrievalIndex
from .llm import ChatClient


class WikiService:
    """Holds the built index for a run selection, rebuilding when it changes.

    Building costs one embedding pass over the corpus (~12s cold, ~0.2s from
    cache), so it is kept per run selection rather than per request.
    """

    def __init__(self, results_root: Path, settings: Settings | None = None) -> None:
        self.results_root = Path(results_root)
        self.settings = settings or Settings.load()
        self.embedder, self.reranker = build_clients(self.settings)
        self.chat = ChatClient(self.settings)

        self._lock = threading.Lock()
        self._key: str | None = None
        self._corpus = None
        self._index: RetrievalIndex | None = None
        self.indexing = False
        self.error: str | None = None
        self._cancelled: set[str] = set()

        # Warm the default selection in the background.  Building costs one
        # embedding pass, and paying it on the first question would both delay
        # that answer and leave the UI reporting "not ready" until someone
        # asked something — which reads as broken rather than as cold.
        self.indexing = True
        threading.Thread(target=self._warm, daemon=True).start()

    def _warm(self) -> None:
        try:
            self.acquire(None)
        except Exception as exc:
            with self._lock:
                self.error = f"initial index build failed: {exc}"
                self.indexing = False

    def _runs_key(self, runs: dict[str, str]) -> str:
        return json.dumps(dict(sorted((runs or {}).items())), sort_keys=True)

    def acquire(self, runs: dict[str, str] | None):
        """Corpus + index for a run selection, building on first use."""
        selection = dict(runs or {})
        if not selection:
            selection = newest_runs(self.results_root)

        key = self._runs_key(selection)
        with self._lock:
            if key == self._key and self._index is not None:
                return self._corpus, self._index
            self.indexing = True

        try:
            corpus = load_corpus(self.results_root, selection)
            index = RetrievalIndex(corpus, self.settings, self.embedder, self.reranker).build()
        except SnapshotError as exc:
            with self._lock:
                self.indexing = False
                self.error = str(exc)
            raise
        finally:
            with self._lock:
                self.indexing = False

        with self._lock:
            self._key, self._corpus, self._index = key, corpus, index
            self.error = index.error
        return corpus, index

    def status(self) -> dict[str, Any]:
        with self._lock:
            index = self._index
            indexing = self.indexing
            error = self.error
        payload = {
            "ready": index is not None and index.ready,
            "indexing": indexing,
            "indexed_functions": len(index.corpus.functions) if index else 0,
            "error": error,
            "mock": False,
            **self.settings.describe(),
        }
        if index is not None:
            payload["index"] = index.stats()
        return payload

    def cancel(self, run_id: str) -> None:
        with self._lock:
            self._cancelled.add(run_id)

    def _stop_event(self, run_id: str) -> threading.Event:
        event = threading.Event()

        def watch() -> None:
            while not event.is_set():
                with self._lock:
                    if run_id in self._cancelled:
                        event.set()
                        return
                time.sleep(0.25)

        threading.Thread(target=watch, daemon=True).start()
        return event

    # ------------------------------------------------------------ answering

    def answer(self, body: dict[str, Any], emit) -> None:
        """Route one question and emit the whole event stream."""
        question = str(body.get("question") or "").strip()
        lang = str(body.get("lang") or "ja")
        mode = str(body.get("mode") or "deep")
        run_id = f"run:{uuid.uuid4().hex[:12]}"

        emit("run", {"run_id": run_id, "started_at": time.time()})
        if not question:
            emit("error", {"message": "empty question"})
            return

        try:
            corpus, index = self.acquire(body.get("runs"))
        except SnapshotError as exc:
            emit("error", {"message": f"could not load snapshots: {exc}"})
            return

        started = time.time()

        # 1. Structural first: exact, instant, and free.
        try:
            hit = structural.answer(corpus, question, lang=lang)
        except Exception as exc:  # a router bug must not lose the question
            hit = None
            emit("route", {"decision": "deep", "reason": f"structural router failed: {exc}"})

        if hit is not None:
            emit("route", {"decision": "structural", "reason": hit.intent})
            emit("compiling", {})
            payload = dict(hit.payload)
            payload.setdefault("stats", {})
            payload["stats"].update(
                {"elapsed_ms": int((time.time() - started) * 1000), "intent": hit.intent, "subagents": 0}
            )
            emit("answer", payload)
            return

        if not self.chat.available:
            emit(
                "error",
                {
                    "message": (
                        "この質問には調査エージェントが必要ですが、チャットモデルが設定されていません。"
                        if lang.startswith("ja")
                        else "This question needs the research agent, but no chat model is configured."
                    ),
                    "code": "no_llm",
                },
            )
            return

        # 2. Otherwise research it.
        stop = self._stop_event(run_id)
        researcher = Researcher(corpus, index, self.chat, self.settings)
        try:
            payload = researcher.ask(
                question,
                lang=lang,
                emit=lambda event: emit(event.get("type", "progress"), event),
                stop=stop,
            )
        except Stopped:
            emit("cancelled", {"run_id": run_id})
            return
        except Exception as exc:
            emit("error", {"message": f"research failed: {exc}", "trace": traceback.format_exc()[-800:]})
            return
        finally:
            with self._lock:
                self._cancelled.discard(run_id)

        payload.setdefault("stats", {})
        payload["stats"]["mode"] = mode
        emit("answer", payload)


class WikiHandlerMixin:
    """Adds the chat endpoints to `VisualizerHandler`.

    Mixed in ahead of the base handler so `do_GET` can intercept the wiki
    routes and delegate everything else unchanged.
    """

    wiki_service: WikiService | None = None

    def _wiki_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _sse(self, event: str, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str)
        self.wfile.write(f"event: {event}\ndata: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler naming
        path = self.path.split("?")[0]
        service = type(self).wiki_service

        if path == "/api/ask/cancel":
            body = self._wiki_body()
            if service is not None:
                service.cancel(str(body.get("run_id") or ""))
            self._send_json({"cancelled": body.get("run_id")})
            return

        if path == "/api/wiki/index/build":
            if service is None:
                self._send_json({"error": "wiki service unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            body = self._wiki_body()
            threading.Thread(
                target=lambda: _safe(service.acquire, body.get("runs")), daemon=True
            ).start()
            self._send_json({"building": True})
            return

        if path != "/api/ask/stream":
            self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
            return

        if service is None:
            self._send_json({"error": "wiki service unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        # Close, not keep-alive.  An SSE response has no Content-Length, so on
        # HTTP/1.1 a keep-alive connection stays open after the terminal event
        # and the client blocks until its own timeout — a correct answer that
        # looks like a hang.
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True

        try:
            service.answer(self._wiki_body(), self._sse)
        except (BrokenPipeError, ConnectionResetError):
            return  # the browser navigated away mid-stream

    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] == "/api/wiki/status":
            service = type(self).wiki_service
            if service is None:
                self._send_json({"ready": False, "error": "wiki service unavailable"})
                return
            self._send_json(service.status())
            return
        return super().do_GET()


def _safe(function, *args) -> None:
    try:
        function(*args)
    except Exception:
        pass
