"""Portable result-directory resolution shared by legacy and new outputs."""

import os
from pathlib import Path


_LEGACY_RESULTS_ROOT = Path("/home/seigyo/c_repo/c_repo/results/csv_results")
_LOCAL_RESULTS_ROOT = Path(__file__).resolve().parent / "results" / "csv_results"


def results_root() -> Path:
    configured = os.environ.get("VISUALIZER_RESULTS_ROOT")
    if configured:
        return Path(configured).expanduser()
    if _LEGACY_RESULTS_ROOT.exists() or _LEGACY_RESULTS_ROOT.parent.exists():
        return _LEGACY_RESULTS_ROOT
    return _LOCAL_RESULTS_ROOT
