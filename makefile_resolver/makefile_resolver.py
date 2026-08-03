import os
import re
from pathlib import Path
from pprint import pprint
from typing import Dict, List, Tuple, Union

from pick import pick
from rich.console import Console

from helpers.time_it import time_it
from makefile_resolver.extract_includes import resolve

console = Console()

# Folders that hold headers for a whole package rather than for one process.
_HEADER_DIR_NAMES = {
    "include",
    "includes",
    "inc",
    "header",
    "headers",
    "common",
    "public",
    "api",
}
_SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "results",
    "logs",
    "pickle_data",
}


def discover_include_dirs(project_path: Path, levels: int = 2) -> list[Path]:
    """Header folders beside or above a process that its Makefile never names.

    A delivered package usually looks like ``pkg/{include,common}`` next to
    ``pkg/g-svm/src``: the headers with all the answers are one or two levels
    up, and the process Makefile either does not mention them or names them
    through a variable that only exists on the build machine.  Those folders
    are added to the ``#include`` *search path* only - never to the file list -
    so a header still enters the project exactly when something includes it.
    """

    project_path = Path(project_path).expanduser().resolve()
    found: list[Path] = []
    base = project_path
    for _ in range(max(0, levels)):
        parent = base.parent
        if parent == base:
            break
        try:
            children = sorted(parent.iterdir())
        except OSError:
            break
        for child in children:
            if child == project_path or child.name.startswith("."):
                continue
            if child.name in _SKIP_DIR_NAMES:
                continue
            try:
                if not child.is_dir():
                    continue
                if child.name.lower() in _HEADER_DIR_NAMES:
                    found.append(child.resolve())
                elif not (child / "Makefile").is_file() and next(
                    child.glob("*.h"), None
                ):
                    # Loose headers in a sibling folder count, but a sibling
                    # that builds something of its own is another process, not
                    # a header pool.
                    found.append(child.resolve())
            except OSError:
                # Unreadable neighbours (permissions, dead mounts) are simply
                # not part of the search path.
                continue
        base = parent
    return list(dict.fromkeys(found))


class MakefileContext:
    def __init__(self, project_root_makefile: Union[str, Path]):
        self.vars: Dict[str, str] = dict(
            os.environ
        )  # might have any conflicts so we can make a dict and trasfer it here.
        self.root_makefile_path = Path(project_root_makefile)
        self.root_dir = self.root_makefile_path.parent
        self.parsed_files = set()
        self.unresolved_log: List[Tuple[str, str, str]] = []

    def resolve_string(self, raw_str: str) -> str:
        if not raw_str:
            return ""
        var_pattern = re.compile(r"\$[({]([a-zA-Z0-9_]+)[)}]")
        resolved = str(raw_str)
        # Recursive resolution for nested macros
        for _ in range(10):
            matches = list(var_pattern.finditer(resolved))
            if not matches:
                break
            for match in reversed(matches):
                var_name = match.group(1)
                var_value = self.vars.get(var_name, "")
                resolved = (
                    resolved[: match.start()] + var_value + resolved[match.end() :]
                )
        return resolved.strip()

    def _process_path(
        self, tag: str, raw_token: str, is_lib: bool = False
    ) -> Path | None:
        """Fully resolves a single token into an absolute Path."""
        # 1. Expand macro (e.g., $(HOME)/include -> /abs/path/include)
        # print('tag',tag,'raw_token ',raw_token)
        expanded = self.resolve_string(raw_token).replace("'", "").strip()
        if is_lib:
            expanded = str(Path(expanded).parent) + f"/{Path(expanded).stem}"
            expanded = expanded.strip(".")

        if not expanded:
            return None

        # if is_lib:
        #     expanded = expanded.replace('.a','').strip()
        p = Path(expanded)
        # print(p)
        # 2. If it's absolute, Path handles it. If relative, join to root_dir.
        final_path = p if p.is_absolute() else (self.root_dir / p)
        resolved_path = final_path.resolve()
        # 3. For LIBS: If it's a file (libapl.a), return the directory containing it
        if is_lib and resolved_path.suffix in [".a", ".so", ".lib", ".sl", ".o", "."]:
            resolved_path = resolved_path.parent
        if tag == "SRCS" and resolved_path.suffix != ".c":
            resolved_path = resolved_path.parent / f"{resolved_path.stem}.c"

        # 4. Debugging log for missing paths
        if not resolved_path.exists():
            # print(resolved_path)
            self.unresolved_log.append((tag, raw_token, str(resolved_path)))
            return None

        return resolved_path

    def parse_file(self, filepath: Union[str, Path]):
        file_path_obj = Path(filepath)
        if file_path_obj in self.parsed_files or not file_path_obj.exists():
            return
        self.parsed_files.add(file_path_obj)

        with open(file_path_obj, "r", errors="ignore") as f:
            content = f.read().replace("\\\n", " ")
            lines = content.splitlines()

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Variable Assignment
            assign_match = re.match(r"^([a-zA-Z0-9_]+)\s*(\??:?|\+?)=\s*(.*)", line)
            if assign_match:
                key, operator, val = assign_match.groups()
                # if key=='HOME':
                #     print(key,operator,val,'ooo')
                if operator == "+=":
                    self.vars[key] = f"{self.vars.get(key, '')} {val}".strip()
                elif operator == "?=":
                    if key not in self.vars:
                        self.vars[key] = val
                else:
                    self.vars[key] = val

            # Include Directives (Recursive)
            include_match = re.match(r"^include\s+(.+)", line)
            if include_match:
                inc_path_str = self.resolve_string(include_match.group(1))
                # print("Inc_path_str", inc_path_str)
                inc_path = self._process_path("INCLUDE_DIRECTIVE", inc_path_str)
                if inc_path:
                    self.parse_file(inc_path)

    def get_final_info(self):
        # A. Helper to process a whole tag (e.g. INCLUDE) that might contain multiple tokens
        def resolve_tag_list(
            keys: List[str], prefix_to_strip: str = "", is_lib: bool = False
        ) -> list:
            results = []
            for key in keys:
                raw_val = self.vars.get(key, "")
                expanded_line = self.resolve_string(raw_val)
                for token in expanded_line.split():
                    clean_token = token
                    # print(clean_token)
                    if prefix_to_strip and token.lower().startswith(
                        prefix_to_strip.lower()
                    ):
                        clean_token = token[len(prefix_to_strip) :]
                    # print(clean_token)
                    p = self._process_path(key, clean_token, is_lib=is_lib)
                    if p:
                        results.append(p)
            return list(dict.fromkeys(results))  # Deduplicate

        return {
            # "HOME": self._process_path("HOME", self.vars.get("HOME", "")),
            "HOME": self._process_path(
                self.vars.get("HOME", ""), "../.."
            ),  # this is because in some makefiles the HOME is set to according to some other env that we don't have.
            "SRCS": resolve_tag_list(["SRCS"]),
            "INCLUDES": resolve_tag_list(["INCLUDE"], prefix_to_strip="-I"),
            "LIB_DIRS": resolve_tag_list(["LIBS"], is_lib=True),
            "UNRESOLVED": self.unresolved_log,
        }


@time_it(message="")
def return_project_mapping(
    show: bool = False,
    project_path: Path | None = None,
    include_levels: int = 2,
    extra_include_dirs: list[Path] | None = None,
) -> tuple[dict[str, Path], list[str]]:  # mapping and potential main files names
    os.environ["VERSION_MNG"] = "/home/seigyo/c_repo/c_repo/src"
    os.environ["PROJECT"] = "/home/seigyo/c_repo/c_repo/src"
    print(project_path)
    # os.environ['HOMELIB'] = '/home/seigyo/c_repo/c_repo/src/src_analysis'

    if not project_path:
        apl_paths = "/home/seigyo/c_repo/c_repo/src/src_analysis/src"
        rbt_paths = "/home/seigyo/c_repo/c_repo/src/src_rbt/src"
        # region PATH HANDLING OF FOLDERS
        select_path, select_index = pick(
            ["apl", "rbt"], "Select the folder", indicator="==>>", default_index=0
        )
        if select_index == 0:
            # os.environ['ORDERINC'] = '/home/seigyo/c_repo/c_repo/src/moove_header'
            # apl folder
            # os.environ['ORDERINC'] = 'home/seigyo/c_repo/c_repo/src/src_analysis'
            folders = [d.name for d in Path(apl_paths).iterdir() if d.is_dir()]
            folders.remove("libapl")
            select_folders, folder_index = pick(
                folders, "Select the apl folder", indicator="==>>", default_index=0
            )
            folder_path = Path(apl_paths) / f"{select_folders}"
        else:
            folders = [d.name for d in Path(rbt_paths).iterdir() if d.is_dir()]
            folders.remove("libRbt")
            select_folders, folder_index = pick(
                folders, "Select the apl folder", indicator="==>>", default_index=0
            )
            folder_path = Path(rbt_paths) / f"{select_folders}"
    else:
        folder_path = project_path

    # endregion
    apl_path = "/home/seigyo/c_repo/c_repo/src/src_analysis/src"
    rbt_path = "/home/seigyo/c_repo/c_repo/src/src_rbt/src"
    src_wh = "/home/seigyo/c_repo/c_repo/src/src_wh/wh-dio/src"
    # if apl_path in str(project_path):
    #     # set env variables for apl projects.
    #     os.environ['MODERNLIB']
    makefile_input = folder_path / "Makefile"
    # os.environ['ORDERLIB']
    os.environ["HOME"] = "../.."
    os.environ["MODERNLIB"] = str(makefile_input.parent.parent)  # /src
    os.environ["HOMELIB"] = str(makefile_input.parent.parent)
    os.environ["MODERN"] = str(makefile_input.parent.parent)
    os.environ["ORDERLIB"] = str(makefile_input.parent.parent)

    ctx = MakefileContext(makefile_input)

    ctx.parse_file(makefile_input)

    info = ctx.get_final_info()
    console.print(info)

    # FROM THIS INFO EXTRACT ALL THE .C AND .H FILES..
    def get_c_and_h_files(directory):
        path = Path(directory)

        # Using rglob to get all .c and .h files recursively
        c_and_h_files = {
            file.name: file for file in path.rglob("*") if file.suffix in {".c", ".h"}
        }

        return c_and_h_files

    files: dict[str, Path] = {}
    potential_main_files: list[str] = []
    for key in info:
        if key in ("UNRESOLVED", "HOME"):
            continue
        if key == "SRCS":
            for p in info[key]:
                files[p.name] = p
                potential_main_files.append(p.name)
        else:
            for p in info[key]:
                if p == project_path.parent:
                    continue
                if p.is_dir() and p != makefile_input.parent:
                    files.update(get_c_and_h_files(p))  # dict.update merges dicts
                elif p.is_file() and p != makefile_input.parent:
                    files[p.name] = p
    # console.print(files)
    # Makefile -I dirs first, then whatever discovery found: a header named by
    # the Makefile still wins when two folders hold the same file name.
    search_dirs = [
        *info.get("INCLUDES", []),
        *(Path(p).expanduser().resolve() for p in (extra_include_dirs or [])),
        *discover_include_dirs(folder_path, include_levels),
    ]
    search_dirs = list(dict.fromkeys(search_dirs))
    if show:
        console.print("INCLUDE SEARCH PATH", search_dirs)
    combined_dependency, file_wise_dependency = resolve(
        files=files, include_dirs=search_dirs
    )
    if show:
        console.print(file_wise_dependency)
        console.print(combined_dependency)
    return combined_dependency, potential_main_files


if __name__ == "__main__":
    # Mock System Env
    a = return_project_mapping(show=True)
    console.print(a)
