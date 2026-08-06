"""Portable result-directory resolution shared by legacy and new outputs.

Layout under the results root::

    <process>.csv                 legacy machine feed (path is a contract)
    visualizer/                   frontend snapshots (path is a contract)
    <process>/                    everything else produced for one process
        summary.md
        facts.csv  paths.csv  run_stats.json  query_cache.json
        logs/
        targets/<target>/         one folder per traced function

Only ``process_results_dir`` and ``target_results_dir`` should build these
paths, so a layout change stays in one place.
"""

import os
import re
from pathlib import Path


_LOCAL_RESULTS_ROOT = Path(__file__).resolve().parent / "results" / "csv_results"


def results_root() -> Path:
    """
    Path of the results folder where outputs will be stored
    """
    configured = os.environ.get("VISUALIZER_RESULTS_ROOT")
    if configured:
        return Path(configured).expanduser()
    return _LOCAL_RESULTS_ROOT


def safe_name(value: str) -> str:
    """Filesystem-safe component for a process or function name."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "unnamed"


def process_results_dir(process_name: str) -> Path:
    """One folder holding every artefact produced for a single process."""
    return results_root() / safe_name(process_name)


def target_results_dir(process_name: str, target_function: str) -> Path:
    """One folder per traced function: its workbook and its diagrams together."""
    return process_results_dir(process_name) / "targets" / safe_name(target_function)
