"""Question answering over the visualizer's graph snapshots.

The tracer writes versioned `graph.json` snapshots (see `visualizer_export.py`).
This package reads them — never writes them — and layers retrieval and a
multi-agent research loop on top, so the frontend can ask questions in prose
instead of only browsing the 3D graph.

Nothing here is imported by the analyzer.  A broken or absent model endpoint
degrades this package to structural, no-LLM answers; it can never affect a
tracer run.
"""

from __future__ import annotations

__all__ = ["corpus", "graphops"]
