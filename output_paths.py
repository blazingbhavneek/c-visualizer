"""Portable result-directory resolution shared by legacy and new outputs."""

import os
from pathlib import Path


_LEGACY_RESULTS_ROOT = Path("/home/seigyo/c_repo/c_repo/results/csv_results")
_REPO_ROOT = Path(__file__).resolve().parent
_LOCAL_RESULTS_ROOT = _REPO_ROOT / "results" / "csv_results"

# Set once per invocation from --output-root. Everything a run writes (results,
# project-structure pickles, logs) hangs off it, so two projects can be analyzed
# side by side without sharing a CSV, a stats file or a snapshot directory.
_OUTPUT_ROOT: Path | None = None


def set_output_root(path: Path | str | None) -> Path | None:
    """Point every output of this run at one folder. `None` restores defaults."""
    global _OUTPUT_ROOT
    _OUTPUT_ROOT = Path(path).expanduser().resolve() if path else None
    return _OUTPUT_ROOT


def output_root() -> Path | None:
    return _OUTPUT_ROOT


def results_root() -> Path:
    if _OUTPUT_ROOT is not None:
        return _OUTPUT_ROOT / "results" / "csv_results"
    configured = os.environ.get("VISUALIZER_RESULTS_ROOT")
    if configured:
        return Path(configured).expanduser()
    if _LEGACY_RESULTS_ROOT.exists() or _LEGACY_RESULTS_ROOT.parent.exists():
        return _LEGACY_RESULTS_ROOT
    return _LOCAL_RESULTS_ROOT


def pickle_root() -> Path:
    """Where resolved project structures are cached between runs."""
    if _OUTPUT_ROOT is not None:
        return _OUTPUT_ROOT / "pickle_data"
    configured = os.environ.get("PROJECT_STRUCTURE_CACHE_ROOT")
    if configured:
        return Path(configured).expanduser()
    return _REPO_ROOT / "pickle_data"


def logs_root() -> Path:
    if _OUTPUT_ROOT is not None:
        return _OUTPUT_ROOT / "logs"
    return _REPO_ROOT / "logs"
