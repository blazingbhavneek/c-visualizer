#!/usr/bin/env python3
"""Serve the visualizer and read graph snapshots lazily via a read model.

No build step or third-party Python package is required:
    python frontend/server.py
    python frontend/server.py --results-root /path/to/results/csv_results

Dynamic API (compact, lazy):
    GET  /api/runs                          metadata-only catalog
    POST /api/overview                      {selection: [[process, run], ...]}
    GET  /api/process?process=&run=         one process's structural bundle
    GET  /api/function?process=&run=&function=
    GET  /api/source?process=&run=&function=
    GET  /api/library?component=&selection= (selection = overview selection key)
    GET  /api/resource?selection=&kind=&name=

`/api/graph` remains as a deprecated raw-snapshot endpoint for debugging and
backward compatibility; the React client no longer calls it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from process_groups import load_group_manifest

try:
    # Running as a script (`python frontend/server.py`) puts this directory on
    # sys.path; imported as `frontend.server` it must be a package import.
    from visualizer_readmodel import ApiError, ReadModel
except ModuleNotFoundError:  # pragma: no cover - depends on import style
    from frontend.visualizer_readmodel import ApiError, ReadModel

# The chat endpoints are strictly additive: without the wiki package (or its
# model endpoints) every graph route below behaves exactly as it always has.
try:
    from wiki.serve import WikiHandlerMixin, WikiService
except ImportError as exc:  # pragma: no cover - depends on the environment
    WikiHandlerMixin, WikiService = None, None
    WIKI_IMPORT_ERROR = str(exc)
else:
    WIKI_IMPORT_ERROR = None


LEGACY_RESULTS_ROOT = Path("/home/seigyo/c_repo/bhavneek/c-visualizer/results/csv_results")
FRONTEND_ROOT = Path(__file__).resolve().parent


def static_root() -> Path:
    """Serve the built React bundle when it exists.

    During development run `npm run dev`, which proxies /api back here; the
    built `dist/` is only needed to serve the whole app from this one process.
    """
    dist = FRONTEND_ROOT / "dist"
    return dist if (dist / "index.html").is_file() else FRONTEND_ROOT


def default_results_root() -> Path:
    configured = os.environ.get("VISUALIZER_RESULTS_ROOT")
    if configured:
        return Path(configured).expanduser()
    if LEGACY_RESULTS_ROOT.exists():
        return LEGACY_RESULTS_ROOT
    return FRONTEND_ROOT.parent / "results" / "csv_results"


class VisualizerHandler(SimpleHTTPRequestHandler):
    results_root: Path
    group_members: set[tuple[str, str]] | None = None
    group_info: dict | None = None
    read_model: ReadModel | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(static_root()), **kwargs)

    def end_headers(self):
        # This frontend is served directly from the working tree.  Do not let a
        # browser retain an earlier JavaScript bundle after the renderer changes.
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def _send_json(self, payload, status=HTTPStatus.OK):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return body if isinstance(body, dict) else {}

    def _query(self) -> dict[str, str]:
        parsed = urlparse(self.path)
        return {key: values[0] for key, values in parse_qs(parsed.query).items()}

    def _graph_path(self, process_name: str, run_id: str) -> Path | None:
        if not process_name or not run_id:
            return None
        candidate = self.results_root / "visualizer" / process_name / "runs" / run_id / "graph.json"
        try:
            candidate.resolve().relative_to((self.results_root / "visualizer").resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def _model(self) -> ReadModel:
        """Read model for this handler's (results_root, group) selection."""
        model = type(self).read_model
        if (
            model is None
            or model.results_root != self.results_root
            or model.group_members is not self.group_members
        ):
            model = ReadModel(self.results_root, self.group_members)
            type(self).read_model = model
        return model

    def _runs(self):
        """Metadata-only run catalog (kept as a method for existing tests)."""
        return self._model().runs()

    # ------------------------------------------------------------------ routes

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/runs":
            self._send_json(
                {
                    "results_root": str(self.results_root),
                    "group": self.group_info,
                    "runs": self._runs(),
                }
            )
            return

        if path == "/api/groups":
            groups_path = self.results_root / "visualizer" / "groups.json"
            try:
                groups = json.loads(groups_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                groups = []
            self._send_json({"results_root": str(self.results_root), "groups": groups})
            return

        if path == "/api/overview":
            query = self._query()
            selection = query.get("selection")
            if selection:
                # GET form: selection=process:run,process:run
                pairs = [pair.split(":", 1) for pair in selection.split(",") if pair]
            else:
                body = self._read_body()
                pairs = body.get("selection")
            self._api(lambda: self._model().overview(pairs))
            return

        if path == "/api/process":
            query = self._query()
            self._api(
                lambda: self._model().process(query.get("process", ""), query.get("run", ""))
            )
            return

        if path == "/api/function":
            query = self._query()
            self._api(
                lambda: self._model().function_detail(
                    query.get("process", ""), query.get("run", ""), query.get("function", "")
                )
            )
            return

        if path == "/api/source":
            query = self._query()
            try:
                payload, status = self._model().source(
                    query.get("process", ""), query.get("run", ""), query.get("function", "")
                )
            except ApiError as exc:
                self._send_json({"error": exc.message}, HTTPStatus(exc.status))
                return
            self._send_json(payload, HTTPStatus(status))
            return

        if path == "/api/library":
            query = self._query()
            self._api(
                lambda: self._model().library(
                    query.get("component", ""), query.get("selection", "")
                )
            )
            return

        if path == "/api/resource":
            query = self._query()
            self._api(
                lambda: self._model().resource_detail(
                    query.get("selection", ""), query.get("kind", ""), query.get("name", "")
                )
            )
            return

        if path == "/api/graph":
            # Deprecated: returns the complete raw snapshot (source_files and
            # all).  Kept for debugging and older clients only; the React app
            # uses the compact /api/overview + /api/process path instead.
            query = self._query()
            self._api(lambda: self._load_raw_graph(query.get("process", ""), query.get("run", "")))
            return

        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/overview":
            body = self._read_body()
            self._api(lambda: self._model().overview(body.get("selection")))
            return
        self._send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)

    def _api(self, thunk):
        """Run a read-model call with uniform error mapping."""
        try:
            self._send_json(thunk())
        except ApiError as exc:
            self._send_json({"error": exc.message}, HTTPStatus(exc.status))
        except Exception as exc:  # pragma: no cover - defensive
            self._send_json({"error": f"Internal error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _load_raw_graph(self, process_name: str, run_id: str):
        if self.group_members is not None and (process_name, run_id) not in self.group_members:
            raise ApiError(400, "Run is not a member of the active process group.")
        graph_path = self._graph_path(process_name, run_id)
        if graph_path is None:
            raise ApiError(404, "Graph snapshot not found.")
        return json.loads(graph_path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Serve the process visualizer.")
    parser.add_argument("--results-root", type=Path, default=default_results_root())
    parser.add_argument(
        "--group",
        help="Show one saved process group by name, name@run-id, or group.json path.",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--no-chat",
        action="store_true",
        help="Serve graphs only, without the question-answering endpoints.",
    )
    args = parser.parse_args()

    VisualizerHandler.results_root = args.results_root.resolve()
    group_members: set[tuple[str, str]] | None = None
    if args.group:
        try:
            group_path, manifest = load_group_manifest(
                VisualizerHandler.results_root, args.group
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        group_members = {
            (str(process["process_name"]), str(process["run_id"]))
            for process in manifest["processes"]
        }
        VisualizerHandler.group_info = {
            "name": manifest.get("name"),
            "run_id": manifest.get("run_id"),
            "generated_at": manifest.get("generated_at"),
            "manifest": str(group_path),
            "totals": manifest.get("totals", {}),
        }
    VisualizerHandler.group_members = group_members
    handler = VisualizerHandler
    if WikiHandlerMixin is not None and not args.no_chat:
        # The mixin goes first so it can intercept the wiki routes and defer
        # everything else to the visualizer handler unchanged.
        handler = type("VisualizerChatHandler", (WikiHandlerMixin, VisualizerHandler), {})
        handler.wiki_service = WikiService(VisualizerHandler.results_root)

    server = ThreadingHTTPServer(("0.0.0.0", args.port), handler)
    print(f"Visualizer: http://localhost:{args.port}")
    if handler is VisualizerHandler:
        reason = WIKI_IMPORT_ERROR or "disabled with --no-chat"
        print(f"Chat endpoints off ({reason}). Graph browsing is unaffected.")
    else:
        settings = handler.wiki_service.settings
        print(
            "Chat: /api/ask/stream  "
            f"[embed={settings.embed_model or 'off'} "
            f"rerank={settings.rerank_model or 'off'} "
            f"llm={settings.llm_model or 'off'}]"
        )
    print(f"Reading snapshots from: {VisualizerHandler.results_root / 'visualizer'}")
    if VisualizerHandler.group_info:
        print(
            "Process group: "
            f"{VisualizerHandler.group_info['name']}@{VisualizerHandler.group_info['run_id']}"
        )
    if static_root() == FRONTEND_ROOT:
        print("No frontend/dist build found - run `npm run build`, or use `npm run dev` on :5173.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nVisualizer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
