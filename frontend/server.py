#!/usr/bin/env python3
"""Serve the visualizer and read graph snapshots directly from results/.

No build step or third-party Python package is required:
    python frontend/server.py
    python frontend/server.py --results-root /path/to/results/csv_results
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
from process_groups import load_group_manifest, scan_graph_runs

# The chat endpoints are strictly additive: without the wiki package (or its
# model endpoints) every graph route below behaves exactly as it always has.
try:
    from wiki.serve import WikiHandlerMixin, WikiService
except ImportError as exc:  # pragma: no cover - depends on the environment
    WikiHandlerMixin, WikiService = None, None
    WIKI_IMPORT_ERROR = str(exc)
else:
    WIKI_IMPORT_ERROR = None


LEGACY_RESULTS_ROOT = Path("/home/seigyo/c_repo/c_repo/results/csv_results")
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

    def _graph_path(self, process_name: str, run_id: str) -> Path | None:
        if not process_name or not run_id:
            return None
        candidate = self.results_root / "visualizer" / process_name / "runs" / run_id / "graph.json"
        try:
            candidate.resolve().relative_to((self.results_root / "visualizer").resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def _load_graph(self, process_name: str, run_id: str):
        graph_path = self._graph_path(process_name, run_id)
        if graph_path is None:
            return None
        try:
            return json.loads(graph_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _runs(self):
        runs = []
        for run in scan_graph_runs(self.results_root):
            member = (str(run["process_name"]), str(run["run_id"]))
            if self.group_members is not None and member not in self.group_members:
                continue
            runs.append(
                {
                    key: run[key]
                    for key in (
                        "process_name",
                        "run_id",
                        "generated_at",
                        "function_count",
                        "resource_count",
                        "interaction_count",
                    )
                }
            )
        return runs

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/runs":
            self._send_json(
                {
                    "results_root": str(self.results_root),
                    "group": self.group_info,
                    "runs": self._runs(),
                }
            )
            return

        if parsed.path == "/api/groups":
            groups_path = self.results_root / "visualizer" / "groups.json"
            try:
                groups = json.loads(groups_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                groups = []
            self._send_json({"results_root": str(self.results_root), "groups": groups})
            return

        if parsed.path in {"/api/graph", "/api/source"}:
            query = parse_qs(parsed.query)
            process_name = query.get("process", [""])[0]
            run_id = query.get("run", [""])[0]
            graph = self._load_graph(process_name, run_id)
            if graph is None:
                self._send_json({"error": "Graph snapshot not found."}, HTTPStatus.NOT_FOUND)
                return
            if parsed.path == "/api/graph":
                self._send_json(graph)
                return

            function_id = query.get("function", [""])[0]
            function = next((item for item in graph.get("functions", []) if item.get("id") == function_id), None)
            if function and isinstance(function.get("source"), str):
                start = max(1, int(function.get("start_line", 1)))
                source_lines = function["source"].splitlines()
                snippet = "\n".join(
                    f"{number:>5}  {line}"
                    for number, line in enumerate(source_lines, start=start)
                )
                self._send_json(
                    {
                        "file": function.get("file"),
                        "start_line": start,
                        "end_line": start + max(0, len(source_lines) - 1),
                        "text": snippet,
                        "embedded": True,
                    }
                )
                return
            source_path = Path(function.get("file", "")) if function else None
            process_root = Path(graph.get("process", {}).get("root", ""))
            if not function or not source_path or not source_path.is_file():
                self._send_json({"error": "Source file not available."}, HTTPStatus.NOT_FOUND)
                return
            try:
                source_path.resolve().relative_to(process_root.resolve())
            except ValueError:
                self._send_json({"error": "Source is outside this process."}, HTTPStatus.FORBIDDEN)
                return
            text = source_path.read_text(encoding="latin-1", errors="replace")
            start = max(1, int(function.get("start_line", 1)))
            end = int(function.get("end_line", start))
            lines = text.splitlines()
            if end < start:
                end = min(len(lines), start + 80)
            snippet = "\n".join(f"{number:>5}  {lines[number - 1]}" for number in range(start, min(end, len(lines)) + 1))
            self._send_json({"file": str(source_path), "start_line": start, "end_line": end, "text": snippet})
            return

        return super().do_GET()


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
    if args.group:
        try:
            group_path, manifest = load_group_manifest(
                VisualizerHandler.results_root, args.group
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        VisualizerHandler.group_members = {
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
    handler = VisualizerHandler
    if WikiHandlerMixin is not None and not args.no_chat:
        # The mixin goes first so it can intercept the wiki routes and defer
        # everything else to the visualizer handler unchanged.
        handler = type("VisualizerChatHandler", (WikiHandlerMixin, VisualizerHandler), {})
        handler.wiki_service = WikiService(VisualizerHandler.results_root)

    server = ThreadingHTTPServer(("0.0.0.0", args.port), handler)
    print(f"Visualizer: http://10.160.152.38:{args.port}")
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
