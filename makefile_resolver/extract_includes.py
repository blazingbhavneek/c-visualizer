import os
import re

# Function to extract #include directives
from collections import defaultdict, deque
from pathlib import Path
from pprint import pprint

from rich.console import Console
from tree_sitter import Language, Parser
from tree_sitter_custom import language

from helpers.Preprocess.preprocess import Preprocess

# parser.set_language(C_LANGUAGE)


class IncludeIndex:
    """Build once, query O(1)."""

    def __init__(self, include_dirs: list[Path]):
        # filename → list of full paths  (handles duplicates like two "util.h")
        self._by_name: dict[str, list[Path]] = defaultdict(list)
        # relative suffix → full path  ("driver/spi.h" → /abs/.../driver/spi.h)
        self._by_rel: dict[str, Path] = {}

        for d in include_dirs:
            if not d.is_dir():
                continue
            for f in d.rglob("*"):
                if f.suffix in {".c", ".h"} and f.is_file():
                    self._by_name[f.name].append(f)
                    # store relative path from the include dir
                    try:
                        rel = f.relative_to(d)
                        self._by_rel.setdefault(str(rel), f)
                    except ValueError:
                        pass

    def find(self, include_path: str, referencing_file: Path) -> Path | None:
        # 1 — relative to the referencing file
        candidate = referencing_file.parent / include_path
        if candidate.is_file():
            return candidate

        # 2 — exact relative path match  ("driver/spi.h")
        if include_path in self._by_rel:
            return self._by_rel[include_path]

        # 3 — filename-only match  ("spi.h")
        basename = Path(include_path).name
        hits = self._by_name.get(basename, [])
        if len(hits) == 1:
            return hits[0]
        # If multiple hits, prefer the one whose path ends with the include string
        for h in hits:
            if str(h).endswith(include_path):
                return h
        return hits[0] if hits else None


def extract_includes(file_path: Path):

    ans = Preprocess().preprocess(file_path=file_path)
    if not ans:
        return None
    tree = ans[0]
    code_bytes = ans[1]

    # tree = parser.parse(c)
    includes = []
    root_node = tree.root_node

    def traverse(node):
        if node.type == "preproc_include":
            includes.append(node.text.decode("latin-1", "ignore").strip())

        for child in node.children:
            traverse(child)

    traverse(root_node)
    return includes


"""
Resolve all #include dependencies transitively.

extract_includes() returns full lines like:
    ['#include <apl_in.h>', '#include "config.h"', '# include <dir/spi.h>']

We parse out the header path, search for it across include directories,
and build a combined dict of all reachable files.
"""

# ────────────────────── parsing helper ────────────────────────

# Handles all variations:
#   #include <file.h>
#   #include "file.h"
#   # include <dir/file.h>
#   #  include  "file.h"
INCLUDE_LINE_RE = re.compile(
    r"""
    ^\s*\#\s*include\s*   # leading ws, #, optional ws, include, optional ws
    [<"]                  # opening < or "
    (?P<path>.+?)         # the actual include path (non-greedy)
    [>"]                  # closing > or "
    """,
    re.VERBOSE,
)


def _parse_include_path(line: str) -> str | None:
    """
    Extract the header path from a raw #include line.

    '#include <driver/spi.h>'  →  'driver/spi.h'
    '#include "config.h"'      →  'config.h'
    'garbage'                  →  None
    """
    m = INCLUDE_LINE_RE.match(line.strip())
    if m:
        return m.group("path")
    return None


# ────────────────────── search helper ─────────────────────────


def _find_include(
    include_path: str,
    referencing_file: Path,
    include_dirs: list[Path],
) -> Path | None:
    """
    Locate a header on disk.

    Search order:
      1. Relative to the directory of the file containing the #include
      2. Each directory in include_dirs (-I list), in order
    """
    # 1 — relative to the referencing file
    candidate = referencing_file.parent / include_path
    if candidate.is_file():
        return candidate

    # 2 — walk the -I include directories
    include_dirs.append(Path("/home/seigyo/c_repo/c_repo/src/moove_header"))
    for path in include_dirs:
        c_and_h_files = [
            file
            for file in path.rglob("*")
            if file.suffix in {".c", ".h"} and include_path in str(file)
        ]
        if len(c_and_h_files) > 0:
            return c_and_h_files[0]

    return None


# ────────────────────── public entry point ────────────────────


def resolve(
    files: dict[str, Path] | None = None,
    include_dirs: list[Path] | None = None,
) -> tuple[dict[str, Path], dict[str, list[str]]]:
    """
    Resolve every reachable #include starting from *files*.

    Parameters
    ----------
    files : dict[str, Path]
        Initial project files.  ``{"main.c": Path("/abs/main.c"), …}``
    include_dirs : list[Path], optional
        Extra search directories (equivalent to ``-I``).

    Returns
    -------
    combined : dict[str, Path]
        Every file in the project (initial + discovered).
        Header keys match the #include path verbatim.
    dependency_map : dict[str, list[str]]
        ``{file_key: [keys of files it directly includes]}``
    """
    # print(f"DEBUG: include_dirs received = {include_dirs}, type = {type(include_dirs)}")

    include_dirs.append(Path("/home/seigyo/c_repo/c_repo/src/moove_header"))
    # pprint(include_dirs)
    index = IncludeIndex(include_dirs=include_dirs)
    # ── bookkeeping ──────────────────────────────────────────
    combined: dict[str, Path] = {}
    path_to_key: dict[Path, str] = {}  # resolved abs path → key
    dependency_map: dict[str, list[str]] = {}
    visited: set[Path] = set()
    queue: deque[tuple[str, Path]] = deque()

    # ── seed with the initial file list ──────────────────────
    for name, file_path in files.items():
        abs_path = file_path
        combined[name] = abs_path
        path_to_key[abs_path] = name
        queue.append((name, abs_path))

    # ── BFS until every reachable file is processed ──────────
    while queue:
        current_key, current_path = queue.popleft()
        # print(type(current_key),type(current_path))
        if current_path in visited:
            continue
        visited.add(current_path)
        # print(current_path)
        if not current_path.is_file():
            continue

        # ---- get raw include lines from user's function ------
        raw_lines: list[str] = extract_includes(current_path)
        deps: list[str] = []

        for line in raw_lines:
            # ---- parse the header path out of the line -------
            inc_path = _parse_include_path(line)
            if inc_path is None:
                continue

            # ---- try to find it on disk ----------------------
            # found = _find_include(inc_path, current_path, include_dirs)
            found = index.find(inc_path, current_path)
            if found is None:
                # system header or missing — skip
                continue

            abs_found = found

            if abs_found in path_to_key:
                # already tracked — just record dependency
                deps.append(path_to_key[abs_found])
            else:
                # ---- new file discovered ----
                key = inc_path  # verbatim #include path

                # collision guard: same include string but different
                # physical file (e.g. two local "util.h" in diff dirs)
                if key in combined and combined[key] != abs_found:
                    key = str(abs_found)

                combined[key] = abs_found
                path_to_key[abs_found] = key
                deps.append(key)
                queue.append((key, abs_found))

        dependency_map[current_key] = deps

    return combined, dependency_map
