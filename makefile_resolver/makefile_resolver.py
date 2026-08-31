import os
import re
import shlex
from pathlib import Path
from pprint import pprint
from typing import Dict, List, Tuple, Union

from pick import pick
from rich.console import Console

from helpers.time_it import time_it
from makefile_resolver.extract_includes import resolve

console = Console()

class MakefileContext:
    def __init__(self, project_root_makefile: Union[str, Path]):
        self.vars: Dict[str, str] = dict(os.environ)
        self.root_makefile_path = Path(project_root_makefile)
        self.root_dir = self.root_makefile_path.parent
        self.parsed_files = set()
        self.unresolved_log: List[Tuple[str, str, str]] = []

    def resolve_string(self, raw_str: str) -> str:
        """Resolve Makefile-style variables like $(HOME) or ${HOME}."""
        if not raw_str:
            return ""

        var_pattern = re.compile(r"\$[({]([a-zA-Z0-9_]+)[)}]")
        resolved = str(raw_str)

        # Resolve nested variables, capped to avoid infinite recursion.
        for _ in range(10):
            matches = list(var_pattern.finditer(resolved))
            if not matches:
                break

            for match in reversed(matches):
                var_name = match.group(1)
                var_value = self.vars.get(var_name, "")
                resolved = (
                    resolved[: match.start()]
                    + var_value
                    + resolved[match.end() :]
                )

        return resolved.strip()

    def _process_path(
        self,
        tag: str,
        raw_token: str,
        is_lib: bool = False,
    ) -> Path | None:
        """Resolve one Makefile token into an existing absolute Path."""
        expanded = self.resolve_string(raw_token).replace("'", "").strip()

        # Convert lib archive paths/names into their likely source directory path.
        if is_lib:
            expanded = str(Path(expanded).parent / Path(expanded).stem).strip(".")

        if not expanded:
            return None

        path = Path(expanded)
        resolved_path = path if path.is_absolute() else self.root_dir / path
        resolved_path = resolved_path.resolve()

        if is_lib and resolved_path.suffix in {".a", ".so", ".lib", ".sl", ".o", "."}:
            resolved_path = resolved_path.parent

        # Some SRCS entries omit .c or point to object-like names.
        if tag == "SRCS" and resolved_path.suffix != ".c":
            resolved_path = resolved_path.parent / f"{resolved_path.stem}.c"

        if not resolved_path.exists():
            self.unresolved_log.append((tag, raw_token, str(resolved_path)))
            return None

        return resolved_path

    def parse_file(self, filepath: Union[str, Path]):
        """Parse a Makefile and recursively parse included Makefiles."""
        file_path = Path(filepath)

        if file_path in self.parsed_files or not file_path.exists():
            return

        self.parsed_files.add(file_path)

        with open(file_path, "r", encoding="latin-1") as f:
            content = f.read().replace("\\\n", " ")
            lines = content.splitlines()

        for line in lines:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            assign_match = re.match(r"^([a-zA-Z0-9_]+)\s*(\+=|\?=|:=|=)\s*(.*)", line)
            if assign_match:
                key, operator, value = assign_match.groups()

                if operator == "+=":
                    self.vars[key] = f"{self.vars.get(key, '')} {value}".strip()
                elif operator == "?=":
                    if key not in self.vars:
                        self.vars[key] = value
                else:
                    self.vars[key] = value

                continue

            include_match = re.match(r"^include\s+(.+)", line)
            if include_match:
                include_path_raw = self.resolve_string(include_match.group(1))
                include_path = self._process_path(
                    "INCLUDE_DIRECTIVE",
                    include_path_raw,
                )

                if include_path:
                    self.parse_file(include_path)

    def get_final_info(self):
        """Return resolved source files, include dirs, library dirs, and unresolved paths."""

        def resolve_tag_list(
            keys: List[str],
            prefix_to_strip: str = "",
            is_lib: bool = False,
        ) -> list[Path]:
            results = []

            for key in keys:
                raw_value = self.vars.get(key, "")
                expanded_line = self.resolve_string(raw_value)

                for token in expanded_line.split():
                    clean_token = token

                    if prefix_to_strip and token.lower().startswith(
                        prefix_to_strip.lower()
                    ):
                        clean_token = token[len(prefix_to_strip) :]

                    path = self._process_path(
                        key,
                        clean_token,
                        is_lib=is_lib,
                    )

                    if path:
                        results.append(path)

            # Deduplicate while preserving order.
            return list(dict.fromkeys(results))

        return {
            # Many project Makefiles define HOME relative to their own build setup,
            # so this keeps the old fallback behavior.
            "HOME": self._process_path("HOME", "../.."),
            "SRCS": resolve_tag_list(["SRCS"]),
            "INCLUDES": resolve_tag_list(["INCLUDE"], prefix_to_strip="-I"),
            "LIB_DIRS": resolve_tag_list(["LIBS"], is_lib=True),
            "UNRESOLVED": self.unresolved_log,
        }

    def get_preprocessor_flags(self) -> dict[str, tuple[str, ...]]:
        """Extract the C preprocessor macro state from build flags.

        This intentionally reads only compile-related variables.  Linker
        flags and arbitrary Makefile assignments must not become ``unifdef``
        arguments.  Values are returned without the leading ``-D``/``-U`` so
        the preprocessing layer owns command-line construction.
        """
        flag_variables = (
            "CPPFLAGS",
            "CFLAGS",
            "CCFLAGS",
            "CDEFS",
            "DEFS",
            "DEFINES",
        )
        tokens: list[str] = []
        for variable in flag_variables:
            raw = self.resolve_string(self.vars.get(variable, ""))
            if not raw:
                continue
            try:
                tokens.extend(shlex.split(raw))
            except ValueError:
                # A malformed Makefile token should not prevent source
                # discovery; the normal unifdef fallback remains available.
                tokens.extend(raw.split())

        defines: list[str] = []
        undefines: list[str] = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token in {"-D", "-U"} and index + 1 < len(tokens):
                value = tokens[index + 1]
                index += 2
                (defines if token == "-D" else undefines).append(value)
                continue
            if token.startswith("-D") and len(token) > 2:
                defines.append(token[2:])
            elif token.startswith("-U") and len(token) > 2:
                undefines.append(token[2:])
            index += 1

        return {
            "defines": tuple(dict.fromkeys(defines)),
            "undefines": tuple(dict.fromkeys(undefines)),
        }


def _get_project_include_dirs(
    project_path: Path,
    info: dict[str, list[Path] | Path | None],
) -> list[Path]:
    """Return the include roots used while resolving this Makefile project."""
    include_dirs = list(info.get("INCLUDES", []))
    include_dirs.append(project_path.parent)
    include_dirs.append(project_path.parent.parent)

    # Add shared include roots if present in parent folders.
    shared_include = next(
        (
            parent / "include"
            for parent in project_path.parents
            if (parent / "include").is_dir()
        ),
        None,
    )

    if shared_include:
        include_dirs.append(shared_include)

        modern_include = shared_include.parent / "modern" / "include"
        if modern_include.is_dir():
            include_dirs.append(modern_include)

        include_dirs.append(shared_include.parent)

    return list(dict.fromkeys(path.resolve() for path in include_dirs))


def load_project_structure_cache(path: Path | str):
    """Load a v6 ``(structure, main_files, srcs_paths)`` cache.

    Returns ``None`` when the cache is missing, unreadable, or predates the
    path-keyed SRCS entry so callers re-resolve instead of trusting stale
    root paths.
    """
    import pickle

    path = Path(path)
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            cached = pickle.load(f)
    except (OSError, pickle.UnpicklingError):
        return None
    if isinstance(cached, tuple) and len(cached) == 3:
        return cached
    return None


def save_project_structure_cache(
    path: Path | str,
    structure: dict,
    main_files: list[str],
    srcs_paths: list[str],
) -> None:
    import pickle

    path = Path(path)
    path.parent.mkdir(exist_ok=True, parents=True)
    with open(path, "wb") as f:
        pickle.dump((structure, main_files, list(srcs_paths)), f)


def get_project_preprocessor_flags(
    project_path: Path,
) -> dict[str, tuple[str, ...]]:
    """Read compile macro flags without resolving the complete file graph."""
    project_path = Path(project_path)
    makefile_input = project_path / "Makefile"
    if not makefile_input.is_file():
        return {"defines": (), "undefines": ()}

    project_root = makefile_input.parent.parent
    os.environ["MODERNLIB"] = str(project_root)
    os.environ["HOMELIB"] = str(project_root)
    os.environ["MODERN"] = str(project_root)
    os.environ["ORDERLIB"] = str(project_root)

    context = MakefileContext(makefile_input)
    context.parse_file(makefile_input)
    info = context.get_final_info()
    flags = context.get_preprocessor_flags()
    flags["include_dirs"] = tuple(
        str(path) for path in _get_project_include_dirs(project_path, info)
    )
    return flags


@time_it(message="")
def return_project_mapping(
    show: bool = False,
    project_path: Path | None = None,
) -> tuple[dict[str, Path], list[str]]:
    if project_path is None:
        raise ValueError("project_path is required in CLI mode")

    project_path = Path(project_path)
    makefile_input = project_path / "Makefile"

    # Environment expected by existing Makefile variables.
    project_root = makefile_input.parent.parent
    os.environ["MODERNLIB"] = str(project_root)
    os.environ["HOMELIB"] = str(project_root)
    os.environ["MODERN"] = str(project_root)
    os.environ["ORDERLIB"] = str(project_root)

    ctx = MakefileContext(makefile_input)
    ctx.parse_file(makefile_input)

    info = ctx.get_final_info()
    console.print(info)

    def get_c_and_h_files(directory: Path | str) -> dict[str, Path]:
        """Collect all .c and .h files under a directory."""
        path = Path(directory)

        return {
            file.name: file
            for file in path.rglob("*")
            if file.suffix in {".c", ".h"}
        }

    def get_local_library_files() -> dict[str, Path]:
        """Find local library source folders referenced by the Makefile."""
        library_names = set()

        for key in ("LIBS", "LDLIBS", "LIBRARIES"):
            library_names.update(
                re.findall(
                    r"lib([^/\s]+?)\.(?:a|so|lib|sl)\b",
                    ctx.vars.get(key, ""),
                )
            )

        library_files = {}
        source_root = project_path.parent

        for library_name in library_names:
            for directory in source_root.rglob(f"lib{library_name}"):
                if directory.is_dir():
                    library_files.update(get_c_and_h_files(directory))

        return library_files

    files: dict[str, Path] = {}
    potential_main_files: list[str] = []
    # Canonical absolute paths of every Makefile SRCS source; the
    # path-keyed identity used for executable-root membership.
    srcs_paths: list[str] = []

    def _merge_files(target: dict[str, Path], new_files: dict[str, Path]) -> None:
        """Merge files without letting two same-basename sources overwrite
        each other.  The first owner keeps the plain basename key; later
        duplicates get a directory-qualified key so both stay parseable.
        """
        for name, path in new_files.items():
            existing = target.get(name)
            if existing is None or existing == path:
                target[name] = path
            else:
                target[f"{path.parent.name}/{name}"] = path

    # Build source/header set from resolved Makefile info.
    for key in info:
        if key in ("UNRESOLVED", "HOME"):
            continue

        if key == "SRCS":
            for path in info[key]:
                files[path.name] = path
                potential_main_files.append(path.name)
                srcs_paths.append(str(path.resolve()))
            continue

        for path in info[key]:
            if path == project_path.parent:
                continue

            if path.is_dir() and path != makefile_input.parent:
                _merge_files(files, get_c_and_h_files(path))
            elif path.is_file():
                _merge_files(files, {path.name: path})

    # Fallback if Makefile parsing did not produce source files.
    if not files:
        files = get_c_and_h_files(project_path)
        potential_main_files = [
            name for name in files
            if name.endswith(".c")
        ]

    # Include local library files after project files.
    _merge_files(files, get_local_library_files())

    include_dirs = _get_project_include_dirs(project_path, info)

    combined_dependency, file_wise_dependency = resolve(
        files=files,
        include_dirs=include_dirs,
    )

    if show:
        console.print(file_wise_dependency)
        console.print(combined_dependency)

    return combined_dependency, potential_main_files, srcs_paths


if __name__ == "__main__":
    # Mock System Env
    a = return_project_mapping(show=True)
    console.print(a)
