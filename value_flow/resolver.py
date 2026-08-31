from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from call_graph.data_classes import CallSite, FunctionNode
from value_flow.handles import node_text, normalise_handle, strip_outer_parens
from value_flow.queries import (
    ArgQuery,
    Fact,
    HandleQuery,
    OneHopAnswer,
    ParamQuery,
    Query,
    ReturnUseQuery,
)
from value_flow.transfers import (
    Binding,
    EffectiveValueSite,
    EvidenceSpan,
    FormulaError,
    RouteArm,
    RouteGuide,
    TransferRequest,
    evaluate_formula,
    make_transfer_cache_key,
    placeholder_indices,
    substitute_placeholders,
    validate_formula,
)
from value_flow.value_rules import merge_value_rules
from models import TransferAnswerModel

_NUMBER = re.compile(
    r"^[+-]?(?:0[xX][0-9a-fA-F]+|0[bB][01]+|0[0-7]+|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)[uUlLfF]*$"
)
_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")
# _IDENTIFIER is anchored with ^...$ and only usable with fullmatch(); this is
# a separate scan pattern for finding identifiers inside a larger text.
_IDENT_SCAN = re.compile(r"[A-Za-z_]\w*")
_STRING_OR_CHAR = re.compile(
    r"^(?:u8|u|U|L)?(?:\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])+')$", re.DOTALL
)

# Bump this whenever resolution semantics change.  Existing caches may contain
# facts produced by the old proximity fallback or by an LLM being treated as
# an exact source, so those facts must not be reused after this change.
RESOLVER_VERSION = "valueflow-route-transfers-v2"


@dataclass(slots=True)
class Expression:
    """One piece of C code that can supply a value to a function argument.

    Example: in `open(&fcb, FILE_NO)`, the second Expression is `FILE_NO`.
    It keeps both the readable text and the Tree-sitter node/location where the
    text was found.
    """

    # Exact C text, such as `FILE_NO`, `42`, `value`, or `input->file_no`.
    text: str
    # The Tree-sitter node for this text. It can be None for generated macro text.
    node: Any | None
    # Short project file key and full disk path containing this expression.
    file_name: str
    file_path: str
    # 1-based source line, used in CSV output and LLM context.
    line: int


@dataclass(slots=True)
class FunctionInfo:
    """Indexed information about one function definition in the project.

    This is what lets ParamQuery turn `value` inside `worker(int value)` into
    argument 1 at every call to `worker(...)`.
    """

    # Stable call-graph ID, normally `[file.c]function_name`.
    function_id: str
    # Existing call-graph record for the function (name, file, line range).
    node: FunctionNode
    # Tree-sitter function_definition node and its original source bytes.
    ast_node: Any | None
    source: bytes
    # Formal parameter names in declaration order: `int a, int b` -> [a, b].
    parameters: list[str]
    # Tree-sitter nodes for those parameters, used to report parameter lines.
    parameter_nodes: list[Any]


@dataclass(slots=True)
class IndexedSite:
    """One exact function call in the source code, enriched for value tracing.

    Example: two `pmf_setsem(...)` calls on the same line are still different
    IndexedSite objects because `start_byte` and `site_id` are different.
    """

    # Stable ID for this exact call: source file plus its starting byte offset.
    site_id: str
    # Function containing the call, and the function/macro ultimately called.
    caller_id: str
    callee_id: str
    callee_name: str
    # File and line where this call is written.
    file_name: str
    file_path: str
    line: int
    # Exact byte range of the call in the source file.
    start_byte: int
    end_byte: int
    # Tree-sitter call_expression node, original source bytes, and parsed args.
    ast_node: Any | None
    source: bytes
    # Arguments positioned for the expanded callee. These are used while
    # tracing formal parameters through the call graph.
    arguments: list[Expression]
    # Arguments exactly as written at the source call. Configured wrapper
    # macros resolve their target indices against these arguments.
    target_arguments: list[Expression]
    # Original, smaller CallSite from the call-graph builder.
    raw_call_site: CallSite
    # Set when source calls a macro which expands to the real callee.
    macro_name: str | None = None
    # True when the macro may add/reorder arguments. In that case, argument 1
    # in the source macro call may not be argument 1 in the expanded function.
    # Do not trust `arguments[index]`; use the macro/LLM fallback instead.
    macro_args_unmapped: bool = False
    # False when start_byte/end_byte fell back to a list ordinal because
    # neither the call site nor its AST node carried a real byte offset.
    # Callers must not present that ordinal as a byte range.
    byte_range_known: bool = True

    def argument(self, index: int) -> Expression | None:
        if index < 1 or index > len(self.arguments):
            return None
        return self.arguments[index - 1]

    def target_argument(self, index: int) -> Expression | None:
        if index < 1 or index > len(self.target_arguments):
            return None
        return self.target_arguments[index - 1]

    @property
    def is_configured_macro_target(self) -> bool:
        return bool(self.macro_name and self.macro_name == self.callee_name)


@dataclass(frozen=True, slots=True)
class CallerEdge:
    """One caller -> callee link used when tracing a parameter backward."""

    # IDs of the calling and called functions, plus the exact call that links them.
    caller_id: str
    callee_id: str
    site_id: str
    # True for a callback edge made from registration metadata, not normal C syntax.
    synthetic_callback: bool = False
    # Event/fork information carried by a callback edge for output metadata.
    launch_via: str = ""
    call_function: str = ""
    # Callback registration provenance: spelling, canonical target, registrar,
    # raw argument text, and byte range from the registration call.
    callback_meta: dict | None = None


@dataclass(slots=True)
class Seed:
    """One configured target API call that the resolver must trace.

    A target function can have many seeds: each written call such as
    `pmf_setsem("svm300d", 0)` is a separate seed.
    """

    # The exact call and its JSON target configuration (indices, type, opens).
    site: IndexedSite
    target_function: str
    config: dict[str, Any]
    # Extra process/event information used by the legacy CSV and visualizer.
    launch_via: str = "FORK"
    call_function: str = "main"
    function_source_file: str = ""
    function_source_line: str = "-1 (Main function)"
    # True when the enclosing function is not root-reachable but every
    # configured argument is mechanically provable inside that same
    # function.  The seed resolves with LOCAL_BACKWALK provenance; it proves
    # a source-valid value if the function executes, not that it executes.
    local_backwalk: bool = False


@dataclass(slots=True)
class ResolvedSeed:
    """One source value found for one argument of one target call.

    This is the main result object. One Seed can create several ResolvedSeed
    objects when an argument has several possible values or several paths.
    """

    # Which target call and which configured target argument this result belongs to.
    seed: Seed
    arg_index: int
    # The resolved argument value and the source file/line that supplied it.
    fact: Fact
    # READF/WRITEF/etc. and the old call-number field used by output consumers.
    operation: str
    call_number: str | None
    # All readable source -> target paths for this one fact. path_count can be
    # larger because paths are capped by the command-line path_cap setting.
    paths: list[list[str]] = field(default_factory=list)
    path_count: int = 0
    paths_truncated: bool = False
    query_token: str = ""
    seconds: float = 0.0
    # First path in the old call-graph label format, kept for older callers.
    legacy_labels: list[str] = field(default_factory=list)
    # Every path in the old call-graph label format. The compatibility CSV uses
    # this list so different paths are written as different rows.
    legacy_paths: list[list[str]] = field(default_factory=list)


# Optional callbacks supplied by project_aware.py. They call the LLM only when
# normal syntax tracing cannot answer a small question.
OneHopResolver = Callable[
    [IndexedSite, int, str], OneHopAnswer | None | Awaitable[OneHopAnswer | None]
]
ReturnUseResolver = Callable[[IndexedSite, str], str | None | Awaitable[str | None]]
HandleFallbackResolver = Callable[
    [IndexedSite, int, tuple[str, ...]],
    list[OneHopAnswer] | None | Awaitable[list[OneHopAnswer] | None],
]
TransferResolver = Callable[
    [TransferRequest], Any | Awaitable[Any]
]


def _walk(node: Any | None) -> Iterable[Any]:
    """Yield this Tree-sitter node and every child node below it."""
    if node is None:
        return
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _extract_declarator_identifier(node: Any | None, source: bytes) -> str | None:
    """Find the variable/function name inside a C declarator AST node.

    C declarations have nested shapes (`int *name`, `int name[4]`), so callers
    use this helper instead of assuming the name is always one direct child.
    """
    if node is None:
        return None
    if node.type == "identifier":
        return node_text(node, source)
    declarator = node.child_by_field_name("declarator")
    if declarator is not None:
        found = _extract_declarator_identifier(declarator, source)
        if found:
            return found
    for child in node.children:
        if child.type in {
            "identifier",
            "pointer_declarator",
            "array_declarator",
            "function_declarator",
            "parenthesized_declarator",
        }:
            found = _extract_declarator_identifier(child, source)
            if found:
                return found
    return None


class ValueFlowResolver:
    """Resolve configured target arguments by walking value-carrying edges backward.

    This class has two phases:

    * Build an index of functions and concrete call sites from the project.
    * Start at each configured target call and trace only the value needed by
      that call back through assignments, parameters, opens, and callers.

    It deliberately does not enumerate every path from main() to a target.
    """

    def __init__(
        self,
        *,
        graph: dict[str, list[CallSite]],
        registry: dict[str, FunctionNode],
        trees: dict[str, tuple[Any, bytes]],
        project_structure: dict[str, str],
        main_file_name: str,
        include_roots: Iterable[str | Path] | None = None,
        entry_function_name: str = "main",
        entry_points: list[tuple[str, str]] | None = None,
        function_configs: dict[str, dict[str, Any]],
        macros: dict[str, tuple[str, str, str]] | None = None,
        file_macros: dict[str, dict[str, str]] | None = None,
        one_hop_resolver: OneHopResolver | None = None,
        return_use_resolver: ReturnUseResolver | None = None,
        handle_llm_resolver: HandleFallbackResolver | None = None,
        transfer_resolver: TransferResolver | None = None,
        transfer_callback: TransferResolver | None = None,
        transfer_model_id: str = "default",
        transfer_prompt_version: str = "valueflow-transfer-v1",
        value_rules: dict[str, dict[str, Any]] | None = None,
        cache_path: Path | None = None,
        path_cap: int = 100,
        llm_concurrency: int = 1,
        progress: Callable[[Seed, list["ResolvedSeed"], float], None] | None = None,
    ) -> None:
        self.graph = graph
        self.registry = registry
        self.trees = trees
        self.project_structure = {
            key: str(value) for key, value in project_structure.items()
        }
        self.include_roots = tuple(
            Path(root).resolve() for root in (include_roots or ()) if root
        )
        self._include_key_index: dict[str, tuple[str, ...]] = {}
        self._include_path_index: dict[Path, tuple[str, ...]] = {}
        self._include_basename_index: dict[str, tuple[str, ...]] = {}
        self._project_paths: dict[str, Path] = {}
        self._build_include_lookup_indexes()
        self.main_file_name = main_file_name
        self.entry_function_name = entry_function_name or "main"
        raw_entry_points = entry_points or (
            [(main_file_name, self.entry_function_name)]
            if main_file_name
            else []
        )
        self.entry_points = list(dict.fromkeys(
            (str(file_name), str(function_name))
            for file_name, function_name in raw_entry_points
            if file_name and function_name
        ))
        self.function_configs = function_configs
        # Named table/wrapper semantics belong only to the explicit legacy
        # compatibility engine. Production valueflow always supplies the
        # transfer callback (including the disabled/offline callback), so it
        # must not load those rules as a semantic input.
        self.transfer_resolver = transfer_resolver or transfer_callback
        self.value_rules = (
            merge_value_rules(value_rules) if self.transfer_resolver is None else {}
        )
        self.builder_macros = macros or {}
        self.file_macros = file_macros or {}
        # The project map can contain several historical copies of a header.
        # Resolve constants through the include graph of the source file that
        # uses them instead of merging every copy into one global namespace.
        print("VALUEFLOW: indexing include graph")
        self.include_graph = self._build_include_graph()
        self.include_diagnostics = self._collect_include_diagnostics()
        self._visible_enum_cache: dict[
            str, tuple[dict[str, tuple[str, str, int]], set[str]]
        ] = {}
        print("VALUEFLOW: indexing enum constants")
        self.enum_values, self.enum_ambiguities = self._build_enum_index()
        self.one_hop_resolver = one_hop_resolver
        self.return_use_resolver = return_use_resolver
        self.handle_llm_resolver = handle_llm_resolver
        self.transfer_model_id = transfer_model_id
        self.transfer_prompt_version = transfer_prompt_version
        self.cache_path = cache_path
        self.path_cap = max(1, path_cap)
        self.llm_concurrency = max(1, llm_concurrency)
        self.progress = progress

        # INDEXES: these are built once from the incoming call graph/AST.  They
        # let later resolution answer "who called this parameter?" and "which
        # earlier call opened this handle?" without rescanning the project.
        self.functions: dict[str, FunctionInfo] = {}
        # File-scope static objects are translation-unit scoped.  Keeping this
        # index separate prevents same-named statics in another source file
        # from satisfying a handle query.
        self.file_static_vars: dict[str, set[str]] = defaultdict(set)
        self.sites: dict[str, IndexedSite] = {}
        self.sites_by_caller: dict[str, list[IndexedSite]] = defaultdict(list)
        self.reverse_callers: dict[str, list[CallerEdge]] = defaultdict(list)
        self.forward_edges: dict[str, list[CallerEdge]] = defaultdict(list)
        self.reachable: set[str] = set()
        # Functions reached without any synthetic callback edge; their union
        # with the callback-only set is ``reachable``.
        self.direct_reachable: set[str] = set()
        self.callback_only: set[str] = set()
        self.seeds: list[Seed] = []

        # RESOLUTION STATE: query token -> answer.  Caching a query saves work,
        # but provenance still retains every path that reused the answer.
        self.results: dict[str, list[Fact]] = {}
        self.in_flight: dict[str, asyncio.Future[list[Fact]]] = {}
        self.provenance: dict[str, set[str]] = defaultdict(set)
        self.query_labels: dict[str, str] = {}
        # Per-query wall time, inclusive of the sub-queries it triggered. Not
        # persisted with the cache: a resumed query costs nothing to re-serve.
        self.timings: dict[str, dict[str, Any]] = {}
        self._query_lock: asyncio.Lock | None = None
        self._llm_gate: asyncio.Semaphore | None = None
        self._handle_dependencies: dict[str, tuple[str, ...]] = {}
        self._launch_cache: dict[str, tuple[str, str, str, str]] = {}
        self._callback_metadata_cache: dict[str, dict[str, Any]] = {}
        self._operation_cache: dict[str, str] = {}
        self._call_number_cache: dict[tuple[str, tuple[str, ...]], str | None] = {}
        self.transfer_cache: dict[str, dict[str, Any]] = {}
        self.transfer_diagnostics: list[str] = []
        self.transfer_rejections: dict[str, int] = defaultdict(int)
        self.transfer_cache_hits = 0
        self.transfer_cache_misses = 0
        self.transfer_request_count = 0
        self._function_slice_cache: dict[str, tuple[str, int]] = {}
        self._route_cache: dict[tuple[str, bool], list[Any]] = {}
        self._visible_names_cache: dict[str, set[str]] = {}
        self._constants_cache: dict[str, dict[str, str]] = {}
        # Part 5 flags: default off, so an unset environment reproduces
        # today's behaviour exactly. See implementation_plan.md Part 5.1.
        self.allow_opaque_formula = os.environ.get("TRACER_VF_GRAMMAR_EXTENDED") == "1"
        self.external_unknown = os.environ.get("TRACER_VF_EXTERNAL_UNKNOWN") == "1"
        self.multi_open = os.environ.get("TRACER_VF_MULTI_OPEN") == "1"
        fingerprint = hashlib.sha256()
        fingerprint.update(RESOLVER_VERSION.encode("utf-8"))
        fingerprint.update(
            json.dumps(self.file_macros, sort_keys=True, default=str).encode(
                "utf-8"
            )
        )
        fingerprint.update(
            json.dumps(self.enum_values, sort_keys=True, default=str).encode(
                "utf-8"
            )
        )
        fingerprint.update(
            json.dumps([str(root) for root in self.include_roots]).encode("utf-8")
        )
        for file_name, (_, source) in sorted(self.trees.items()):
            fingerprint.update(file_name.encode("utf-8", errors="replace"))
            fingerprint.update(b"\0")
            fingerprint.update(source)
            fingerprint.update(b"\0")
        fingerprint.update(
            json.dumps(self.function_configs, sort_keys=True, default=str).encode(
                "utf-8"
            )
        )
        self.cache_fingerprint = fingerprint.hexdigest()

        # Resolver setup order.  Read these methods in this order when
        # debugging why a target was or was not traced.
        print("VALUEFLOW: indexing function definitions")
        self._build_function_index()   # function definitions + parameter names
        self._build_file_static_index()
        print(f"VALUEFLOW: indexed {len(self.functions)} functions")
        print("VALUEFLOW: indexing call sites")
        self._build_call_index()
        print(f"VALUEFLOW: indexed {len(self.sites)} call sites")
        print("VALUEFLOW: indexing callbacks and reachability")
        self._build_callback_edges()
        self._compute_reachability()
        print(f"VALUEFLOW: {len(self.reachable)} reachable functions")
        self._enumerate_seeds()
        print(f"VALUEFLOW: found {len(self.seeds)} target invocations")
        self._load_cache()

    # ------------------------------------------------------------------ index
    def _build_function_index(self) -> None:
        definitions_by_file: dict[str, list[Any]] = defaultdict(list)
        for file_name, (tree, _) in self.trees.items():
            definitions_by_file[file_name] = [
                node
                for node in _walk(tree.root_node)
                if node.type == "function_definition"
            ]

        for function_id, function_node in self.registry.items():
            source = self.trees.get(function_node.file_name, (None, b""))[1]
            candidates = []
            for candidate in definitions_by_file.get(function_node.file_name, []):
                name = _extract_declarator_identifier(
                    candidate.child_by_field_name("declarator"), source
                )
                if name == function_node.name:
                    candidates.append(candidate)

            ast_node = None
            if len(candidates) == 1:
                ast_node = candidates[0]
            elif candidates:
                # Several same-named definitions in one file (e.g. a static and
                # an extern sharing a name): pick the one whose byte range
                # contains the registry's recorded start line, so they don't
                # all bind to the first candidate found.
                start = function_node.start_line
                if start > 0:
                    for candidate in candidates:
                        first = candidate.start_point[0] + 1
                        last = candidate.end_point[0] + 1
                        if first <= start <= last:
                            ast_node = candidate
                            break
                ast_node = ast_node or candidates[0]
            parameters: list[str] = []
            parameter_nodes: list[Any] = []
            if ast_node is not None:
                declarator = ast_node.child_by_field_name("declarator")
                parameter_list = next(
                    (
                        node
                        for node in _walk(declarator)
                        if node.type == "parameter_list"
                    ),
                    None,
                )
                if parameter_list is not None:
                    for parameter in parameter_list.named_children:
                        if parameter.type == "variadic_parameter":
                            continue
                        name = _extract_declarator_identifier(parameter, source)
                        parameters.append(name or f"param_{len(parameters) + 1}")
                        parameter_nodes.append(parameter)
            self.functions[function_id] = FunctionInfo(
                function_id=function_id,
                node=function_node,
                ast_node=ast_node,
                source=source,
                parameters=parameters,
                parameter_nodes=parameter_nodes,
            )

        missing = [fid for fid, info in self.functions.items() if info.ast_node is None]
        if missing:
            print(
                f"VALUEFLOW: WARNING {len(missing)} function(s) have no AST node; "
                f"their parameters are empty and every transfer through them will "
                f"fail. First 10: {missing[:10]}"
            )

    def _build_file_static_index(self) -> None:
        """Index file-scope static object identities by source file.

        A static FCB may be opened in one function and consumed in a sibling
        function.  The file key is part of identity; basename lookup is never
        used here.
        """
        for file_name, (tree, source) in self.trees.items():
            for node in tree.root_node.named_children:
                if node.type != "declaration":
                    continue
                text = node_text(node, source)
                if not re.search(r"\bstatic\b", text):
                    continue
                for child in node.named_children:
                    if child.type != "init_declarator":
                        continue
                    declarator = child.child_by_field_name("declarator")
                    name = _extract_declarator_identifier(declarator, source)
                    if name:
                        self.file_static_vars[file_name].add(name)

    def _function_infos_named(self, name: str) -> list[FunctionInfo]:
        return sorted(
            (info for info in self.functions.values() if info.node.name == name),
            key=lambda info: (info.node.file_name, info.node.start_line, info.function_id),
        )

    def _site_ast(self, caller_id: str, call_site: CallSite) -> Any | None:
        info = self.functions.get(caller_id)
        if info is None or info.ast_node is None:
            return None
        if call_site.start_byte >= 0:
            candidate = info.ast_node.descendant_for_byte_range(
                call_site.start_byte, max(call_site.start_byte + 1, call_site.end_byte)
            )
            while candidate is not None and candidate.type != "call_expression":
                candidate = candidate.parent
            if candidate is not None:
                return candidate
        # Compatibility for old/crafted CallSite instances without byte offsets.
        for candidate in _walk(info.ast_node):
            if (
                candidate.type != "call_expression"
                or candidate.start_point.row + 1 != call_site.line_number
            ):
                continue
            function = candidate.child_by_field_name("function")
            if (
                function is not None
                and node_text(function, info.source) == call_site.callee.name
            ):
                return candidate
        return None

    def _expressions_for_call(
        self, ast_node: Any | None, source: bytes, file_name: str, file_path: str
    ) -> list[Expression]:
        if ast_node is None:
            return []
        arguments = ast_node.child_by_field_name("arguments")
        if arguments is None:
            return []
        return [
            Expression(
                text=node_text(argument, source),
                node=argument,
                file_name=file_name,
                file_path=file_path,
                line=argument.start_point.row + 1,
            )
            for argument in arguments.named_children
        ]

    def _macro_call_arguments(
        self,
        macro_name: str,
        target_name: str,
        actual_arguments: list[Expression],
        file_name: str,
        file_path: str,
        line: int,
    ) -> tuple[list[Expression], bool]:
        """Map a macro call's arguments onto the expanded function's positions.

        Returns ``(arguments, reliable)``. When ``reliable`` is False the
        positions are NOT those of the expanded function -- a macro that
        injects arguments, as in ``FOO(a,b) -> bar(FILE,a,b)``, shifts every
        index. Trusting them would silently report the wrong argument, so the
        caller must route that site somewhere that can reason about the
        expansion instead of reading a position.
        """
        macro = self.builder_macros.get(macro_name)
        if not macro:
            return actual_arguments, False
        replacement, _, signature = macro
        body = strip_outer_parens(replacement.strip())

        # A pure rename (``#define Foo FooFunc``) forwards every argument
        # untouched, so the call site's own positions are already correct.
        if _IDENTIFIER.fullmatch(body) and body == target_name:
            return actual_arguments, True

        # Token pasting and stringification cannot be modelled by textual
        # substitution; do not pretend otherwise.
        if "##" in replacement or re.search(r"#\s*[A-Za-z_]", replacement):
            return actual_arguments, False

        signature_match = re.match(
            r"\s*[A-Za-z_]\w*\s*\((.*)\)\s*$", signature, re.DOTALL
        )
        parameters = (
            [part.strip() for part in signature_match.group(1).split(",")]
            if signature_match and signature_match.group(1).strip()
            else []
        )
        # Variadic macros and arity mismatches make positional substitution
        # meaningless. zip() would silently truncate, so reject them here.
        if any(part.startswith("...") for part in parameters):
            return actual_arguments, False
        if parameters and len(parameters) != len(actual_arguments):
            return actual_arguments, False
        expanded = replacement
        for parameter, actual in zip(parameters, actual_arguments):
            expanded = re.sub(rf"\b{re.escape(parameter)}\b", actual.text, expanded)
        # Reuse the repository's Tree-sitter language through an existing tree's parser type.
        from tree_sitter import Language, Parser
        from tree_sitter_custom import language

        parser = Parser(Language(language()))
        expanded_source = expanded.encode("latin-1", errors="replace")
        tree = parser.parse(expanded_source)
        for candidate in _walk(tree.root_node):
            if candidate.type != "call_expression":
                continue
            function = candidate.child_by_field_name("function")
            if function is None or node_text(function, expanded_source) != target_name:
                continue
            arguments = candidate.child_by_field_name("arguments")
            if arguments is None:
                # An empty argument list is not a usable mapping; marking it
                # reliable causes every site.argument(i) lookup to fail with
                # no model call. Route it through the macro-unmapped path.
                return [], False
            return [
                Expression(
                    text=node_text(argument, expanded_source),
                    node=None,
                    file_name=file_name,
                    file_path=file_path,
                    line=line,
                )
                for argument in arguments.named_children
            ], True
        return actual_arguments, False

    def _build_call_index(self) -> None:
        # Convert the call graph's CallSite entries into IndexedSite entries.
        # IndexedSite adds AST arguments, source bytes, a stable byte-based ID,
        # and macro-expansion information needed during reverse tracing.
        for caller_id, call_sites in self.graph.items():
            caller = self.registry.get(caller_id)
            if caller is None:
                continue
            source = self.trees.get(caller.file_name, (None, b""))[1]
            file_path = self.project_structure.get(
                caller.file_name, caller.file_path or ""
            )
            for ordinal, call_site in enumerate(call_sites):
                ast_node = self._site_ast(caller_id, call_site)
                byte_range_known = True
                if call_site.start_byte >= 0:
                    start_byte = call_site.start_byte
                elif ast_node is not None:
                    start_byte = ast_node.start_byte
                else:
                    # Neither the call site nor its AST node carries a real
                    # byte offset. `ordinal` (a list index) keeps site_id
                    # stable/identity-preserving, but it must not be presented
                    # to callers as an actual byte range.
                    start_byte = ordinal
                    byte_range_known = False
                    self.transfer_rejections["site_without_bytes"] += 1
                site_id = f"{caller.file_name}:{start_byte}"
                source_arguments = self._expressions_for_call(
                    ast_node, source, caller.file_name, file_path
                )
                arguments = source_arguments
                callee = call_site.callee
                callee_id = callee.unique_id
                raw_callee_name = callee.name
                callee_name = raw_callee_name
                macro_name = None
                macro_args_unmapped = False
                if callee.macro_expansion is not None:
                    macro_name = raw_callee_name
                    callee_id = callee.macro_expansion.unique_id
                    expanded_callee_name = callee.macro_expansion.name
                    arguments, reliable = self._macro_call_arguments(
                        macro_name,
                        expanded_callee_name,
                        arguments,
                        caller.file_name,
                        file_path,
                        call_site.line_number,
                    )
                    macro_args_unmapped = not reliable
                    # Keep a configured wrapper macro as the target identity,
                    # while retaining the expanded function as the graph edge.
                    # This lets targets such as mpf_mfs_clearfile resolve under
                    # their registry name even though the call graph follows
                    # their mpf_mfs_clearcc expansion.
                    callee_name = (
                        raw_callee_name
                        if raw_callee_name in self.function_configs
                        else expanded_callee_name
                    )
                site = IndexedSite(
                    site_id=site_id,
                    caller_id=caller_id,
                    callee_id=callee_id,
                    callee_name=callee_name,
                    file_name=caller.file_name,
                    file_path=file_path,
                    line=call_site.line_number,
                    start_byte=start_byte,
                    end_byte=call_site.end_byte,
                    ast_node=ast_node,
                    source=source,
                    arguments=arguments,
                    target_arguments=(
                        source_arguments
                        if raw_callee_name in self.function_configs
                        else arguments
                    ),
                    raw_call_site=call_site,
                    macro_name=macro_name,
                    macro_args_unmapped=macro_args_unmapped,
                    byte_range_known=byte_range_known,
                )
                self.sites[site_id] = site
                self.sites_by_caller[caller_id].append(site)
                edge = CallerEdge(caller_id, callee_id, site_id)
                self.reverse_callers[callee_id].append(edge)
                self.forward_edges[caller_id].append(edge)
        for sites in self.sites_by_caller.values():
            sites.sort(key=lambda item: (item.start_byte, item.site_id))

    def _build_callback_edges(self) -> None:
        for site in self.sites.values():
            raw = site.raw_call_site
            config = self.function_configs.get(raw.callee.name, {})
            launch_via = config.get("launch", "NO DATA")

            records = getattr(raw, "callback_records", None) or []
            if records:
                edges: list[tuple[str, str, dict | None]] = []
                for record in records:
                    canonical = str(record.get("canonical") or "")
                    node = record.get("node")
                    if not canonical or node is None:
                        continue
                    # Deduplicate by canonical function identity: one edge per
                    # registered handler, however many times it is spelled.
                    key = node.unique_id
                    if any(existing[0] == key for existing in edges):
                        continue
                    edges.append(
                        (
                            key,
                            canonical,
                            {
                                "spelling": str(record.get("spelling") or ""),
                                "canonical": canonical,
                                "registrar": str(record.get("registrar") or ""),
                                "registrar_file": str(
                                    record.get("registrar_file") or site.file_name
                                ),
                                "registrar_line": int(record.get("registrar_line") or site.line),
                                "raw_text": str(record.get("raw_text") or ""),
                                "start_byte": int(record.get("start_byte") or -1),
                                "end_byte": int(record.get("end_byte") or -1),
                                "diagnostic": str(record.get("diagnostic") or ""),
                                "raw_node_id": raw.callee.unique_id,
                            },
                        )
                    )
            else:
                edges = []
                callbacks: dict[str, FunctionNode] = {}
                for callback in raw.callbacks:
                    callbacks.setdefault(callback.unique_id, callback)
                for callback_id, callback in callbacks.items():
                    edges.append((callback_id, callback.name, None))

            for callback_id, canonical, meta in edges:
                synthetic_id = f"{site.site_id}#callback:{callback_id}"
                edge = CallerEdge(
                    caller_id=site.caller_id,
                    callee_id=callback_id,
                    site_id=synthetic_id,
                    synthetic_callback=True,
                    launch_via=launch_via,
                    # Use the expanded (canonical) handler for launch/config
                    # metadata lookups, not the macro spelling.
                    call_function=canonical,
                    callback_meta=meta,
                )
                self.reverse_callers[callback_id].append(edge)
                self.forward_edges[site.caller_id].append(edge)

    def _compute_reachability(self) -> None:
        # Middleware may invoke lifecycle callbacks without an application-
        # visible caller.  Start from every lifecycle root, then follow direct
        # and synthetic callback edges from their union.
        entry_ids = [
            f"[{file_name}]{function_name}"
            for file_name, function_name in self.entry_points
            if f"[{file_name}]{function_name}" in self.registry
        ]
        if not entry_ids:
            self.reachable = set()
            self.direct_reachable = set()
            self.callback_only = set()
            return
        queue = deque(entry_ids)
        self.reachable.update(entry_ids)
        direct_queue = deque(entry_ids)
        self.direct_reachable.update(entry_ids)
        while queue:
            current = queue.popleft()
            for edge in self.forward_edges.get(current, []):
                if edge.callee_id not in self.reachable:
                    self.reachable.add(edge.callee_id)
                    queue.append(edge.callee_id)
        while direct_queue:
            current = direct_queue.popleft()
            for edge in self.forward_edges.get(current, []):
                if edge.synthetic_callback:
                    continue
                if edge.callee_id not in self.direct_reachable:
                    self.direct_reachable.add(edge.callee_id)
                    direct_queue.append(edge.callee_id)
        # CALLBACK means the function is reached at all, but only through a
        # registration edge; DIRECT_ROOT wins when both kinds of path exist.
        self.callback_only = self.reachable - self.direct_reachable

    def reachability_kind(self, function_id: str) -> str:
        """Classify one function against the recognized roots."""
        if function_id in self.direct_reachable:
            return "DIRECT_ROOT"
        if function_id in self.reachable:
            return "CALLBACK"
        return ""

    def callback_metadata(self, function_id: str) -> dict[str, Any]:
        """Return registrar provenance for the first callback path to a function."""
        if function_id in self._callback_metadata_cache:
            return self._callback_metadata_cache[function_id]
        if function_id not in self.callback_only:
            self._callback_metadata_cache[function_id] = {}
            return {}
        roots = [
            f"[{file_name}]{function_name}"
            for file_name, function_name in self.entry_points
            if f"[{file_name}]{function_name}" in self.registry
        ]
        queue = deque((root, {}) for root in roots)
        visited = set(roots)
        while queue:
            current, callback = queue.popleft()
            for edge in sorted(
                self.forward_edges.get(current, []), key=lambda item: item.site_id
            ):
                next_callback = callback
                if edge.synthetic_callback and not next_callback:
                    next_callback = dict(edge.callback_meta or {})
                    next_callback["reachability"] = "CALLBACK"
                    next_callback["canonical_function"] = edge.call_function
                if edge.callee_id == function_id:
                    self._callback_metadata_cache[function_id] = next_callback
                    return next_callback
                if edge.callee_id not in visited:
                    visited.add(edge.callee_id)
                    queue.append((edge.callee_id, next_callback))
        self._callback_metadata_cache[function_id] = {}
        return {}

    def _launch_metadata(self, function_id: str) -> tuple[str, str, str, str]:
        if function_id in self._launch_cache:
            return self._launch_cache[function_id]
        metadata = self._launch_metadata_uncached(function_id)
        self._launch_cache[function_id] = metadata
        return metadata

    def _launch_metadata_uncached(self, function_id: str) -> tuple[str, str, str, str]:
        roots = [
            (
                f"[{file_name}]{function_name}",
                (
                    "FORK",
                    function_name,
                    self.project_structure.get(file_name, ""),
                    "-1 (Entry function)",
                ),
            )
            for file_name, function_name in self.entry_points
        ]
        for entry_id, metadata in roots:
            if function_id == entry_id:
                return metadata
        queue = deque(roots)
        visited = {entry_id for entry_id, _ in roots}
        while queue:
            current, metadata = queue.popleft()
            for edge in sorted(
                self.forward_edges.get(current, []), key=lambda item: item.site_id
            ):
                next_metadata = metadata
                if edge.synthetic_callback:
                    callback = self.registry.get(edge.callee_id)
                    next_metadata = (
                        edge.launch_via or "NO DATA",
                        edge.call_function
                        or (callback.name if callback else "unknown"),
                        (
                            self.project_structure.get(callback.file_name, "")
                            if callback
                            else ""
                        ),
                        str(callback.start_line if callback else -1),
                    )
                if edge.callee_id == function_id:
                    return next_metadata
                if edge.callee_id not in visited:
                    visited.add(edge.callee_id)
                    queue.append((edge.callee_id, next_metadata))
        if roots:
            return roots[0][1]
        return "FORK", self.entry_function_name, "", "-1 (Entry function)"

    def _enumerate_seeds(self) -> None:
        # A seed means one concrete configured target invocation, not merely a
        # target function name. Two calls to mdm_open produce two separate seeds.
        for site in sorted(self.sites.values(), key=lambda item: item.site_id):
            if site.caller_id not in self.reachable:
                # Local-backwalk fallback: an unreachable enclosing function
                # still yields a source-valid value when the binding is
                # proven inside that same function.  The transfer engine is
                # allowed to ask the model about the local function; the old
                # compatibility engine keeps its stricter syntactic gate.
                if site.callee_name not in self.function_configs:
                    continue
                if self.transfer_resolver is None and not self._locally_provable(site):
                    continue
                caller = self.functions.get(site.caller_id)
                self.seeds.append(
                    Seed(
                        site=site,
                        target_function=site.callee_name,
                        config=self.function_configs[site.callee_name],
                        launch_via="LOCAL_BACKWALK",
                        call_function=(caller.node.name if caller else site.caller_id),
                        function_source_file=site.file_path,
                        function_source_line="-1 (Local backwalk)",
                        local_backwalk=True,
                    )
                )
                continue
            config = self.function_configs.get(site.callee_name)
            if config is None:
                continue
            launch, call_function, source_file, source_line = self._launch_metadata(
                site.caller_id
            )
            # Explicit launch on no-target process/event APIs remains compatible
            # with the legacy special case.
            if not config.get("indices") and config.get("launch"):
                launch = config.get("launch", launch)
            self.seeds.append(
                Seed(
                    site=site,
                    target_function=site.callee_name,
                    config=config,
                    launch_via=launch,
                    call_function=call_function,
                    function_source_file=source_file,
                    function_source_line=source_line,
                )
            )

    # --------------------------------------------------------------- cache I/O
    def _load_cache(self) -> None:
        if self.cache_path is None or not self.cache_path.is_file():
            return
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != 3:
                return
            # Transfer entries are self-validating: make_transfer_cache_key
            # already digests the function slice, the selected site source,
            # the prompt version and the model id. A change to an unrelated
            # file cannot produce a false hit, so these survive a project
            # fingerprint change.
            self.transfer_cache = {
                str(key): value
                for key, value in (payload.get("transfer_cache") or {}).items()
                if isinstance(value, dict)
            }
            if payload.get("fingerprint") != self.cache_fingerprint:
                return
            self.results = {
                token: [Fact.from_dict(fact) for fact in facts]
                for token, facts in payload.get("results", {}).items()
            }
            self.provenance = defaultdict(
                set,
                {
                    token: set(parents)
                    for token, parents in payload.get("provenance", {}).items()
                },
            )
            self.query_labels.update(payload.get("query_labels", {}))
        except (OSError, ValueError, TypeError):
            # A partial/old cache is never allowed to break a trace.
            self.results = {}
            self.provenance = defaultdict(set)

    def persist_cache(self) -> None:
        if self.cache_path is None:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 3,
            "fingerprint": self.cache_fingerprint,
            "results": {
                token: [fact.to_dict() for fact in facts]
                for token, facts in sorted(self.results.items())
            },
            "provenance": {
                token: sorted(parents)
                for token, parents in sorted(self.provenance.items())
            },
            "query_labels": dict(sorted(self.query_labels.items())),
            "transfer_cache": dict(sorted(self.transfer_cache.items())),
        }
        temporary = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.cache_path)

    # -------------------------------------------------------------- resolution
    async def resolve(
        self, query: Query, stack: frozenset[str] = frozenset()
    ) -> list[Fact]:
        # Every reverse-tracing step is a Query. Its token is stable enough to
        # cache and to share when several target paths reach the same subproblem.
        token = query.token()
        self._label_query(query)
        if token in stack:
            return [self._cycle_fact(query)]
        if token in self.results:
            return self.results[token]
        if self._query_lock is None:
            self._query_lock = asyncio.Lock()
        owner = False
        async with self._query_lock:
            if token in self.results:
                return self.results[token]
            future = self.in_flight.get(token)
            if future is None:
                future = asyncio.get_running_loop().create_future()
                self.in_flight[token] = future
                owner = True
        if not owner:
            return await asyncio.shield(future)
        started = time.perf_counter()
        try:
            facts = await self._resolve_uncached(query, stack | {token})
            facts = self._deduplicate_facts(facts)
            self.results[token] = facts
            self.timings[token] = {
                "seconds": time.perf_counter() - started,
                "used_llm": any(fact.resolved_by == "LLM" for fact in facts),
                "fact_count": len(facts),
            }
            if not future.done():
                future.set_result(facts)
            return facts
        except Exception as exc:
            if not future.done():
                future.set_exception(exc)
            raise
        finally:
            self.in_flight.pop(token, None)

    async def _resolve_uncached(
        self, query: Query, stack: frozenset[str]
    ) -> list[Fact]:
        # Dispatch one reverse-tracing question to the matching resolver.
        # ArgQuery and ParamQuery form the normal caller/callee value walk.
        # HandleQuery and ReturnUseQuery are special resource-operation cases.
        if isinstance(query, ArgQuery):
            return await self._resolve_argument(query, stack)
        if isinstance(query, ParamQuery):
            return await self._resolve_parameter(query, stack)
        if isinstance(query, HandleQuery):
            return await self._resolve_handle(query, stack)
        if isinstance(query, ReturnUseQuery):
            operation = await self._resolve_return_use(query)
            site = self.sites[query.call_site_id]
            return [
                Fact(
                    value=operation,
                    origin_kind="CONST" if operation != "UNRESOLVED" else "UNRESOLVED",
                    source_file=site.file_path,
                    source_line=site.line,
                    source_expr=site.callee_name,
                    origin_query=query.token(),
                    resolved_by="LLM" if self.return_use_resolver else "SYNTAX",
                )
            ]
        raise TypeError(f"Unsupported value-flow query: {query!r}")

    async def _resolve_argument(
        self, query: ArgQuery, stack: frozenset[str]
    ) -> list[Fact]:
        # Start at the exact target/caller invocation and select its Nth actual
        # argument. Argument numbers are 1-based because JSON target configs are.
        site = self.sites.get(query.call_site_id)
        if site is None:
            return [self._unresolved_fact(query, "missing call site")]
        if query.target and site.is_configured_macro_target:
            expression = site.target_argument(query.arg_index)
        else:
            if site.macro_args_unmapped:
                return await self._resolve_across_macro(query, site)
            expression = site.argument(query.arg_index)
        if expression is None:
            return [self._unresolved_fact(query, f"missing argument {query.arg_index}")]
        return await self._resolve_expression(expression, site, query, stack, set())

    async def _resolve_across_macro(
        self, query: ArgQuery, site: IndexedSite
    ) -> list[Fact]:
        """Resolve an argument whose position could not be mapped by expansion.

        The model is given the macro definition alongside the call, which is how
        the original tracer handled this. When no model is available the fact is
        reported as unfollowable rather than guessed, because the alternative --
        reading the unexpanded position -- yields a confident wrong answer.
        """
        call_text = (
            node_text(site.ast_node, site.source)
            if site.ast_node is not None
            else (site.macro_name or "")
        )
        answer = await self._call_one_hop(site, query, call_text)
        if answer is not None and answer.kind == "VALUE" and answer.value is not None:
            return [
                Fact(
                    value=str(answer.value),
                    origin_kind="LLM_CANDIDATE",
                    source_file=site.file_path,
                    source_line=site.line,
                    source_expr=answer.source_expr or call_text,
                    origin_query=query.token(),
                    source_site_id=query.token(),
                    resolved_by="LLM",
                    link_method="MACRO_EXPANSION",
                )
            ]
        return [
            Fact(
                value=f"unmapped macro argument via {site.macro_name}",
                origin_kind="UNKNOWN_INDIRECT",
                source_file=site.file_path,
                source_line=site.line,
                source_expr=call_text,
                origin_query=query.token(),
                source_site_id=query.token(),
                link_method="MACRO_EXPANSION",
            )
        ]

    async def _resolve_expression(
        self,
        expression: Expression,
        site: IndexedSite,
        query: Query,
        stack: frozenset[str],
        local_stack: set[str],
    ) -> list[Fact]:
        # Resolution priority, from cheapest/most certain to least certain:
        # literal -> macro -> parameter/caller -> local assignment -> LLM ->
        # explicit external/unknown fact.  Each return is a possible source.
        raw = expression.text.strip()
        value = strip_outer_parens(raw)
        if self._literal(value):
            return [self._source_fact(value, "CONST", expression, query)]

        table_facts = self._resolve_table_expression(expression, site, query)
        if table_facts is not None:
            return table_facts

        macro = self._resolve_macro(value, expression.file_name)
        if macro is not None:
            resolved, macro_file, macro_line = macro
            visible_enum_values, _ = self._visible_enum_index(expression.file_name)
            return [
                Fact(
                    value=resolved,
                    origin_kind=(
                        "CONST" if value in visible_enum_values else "MACRO"
                    ),
                    source_file=macro_file or expression.file_path,
                    source_line=macro_line or expression.line,
                    source_expr=value,
                    origin_query=query.token(),
                    source_site_id=f"{macro_file}:{macro_line}:{value}",
                )
            ]

        if _IDENTIFIER.fullmatch(value):
            wrapper_facts = self._wrapper_output_facts(site, value, query)
            if wrapper_facts is not None:
                return wrapper_facts

            string_facts = self._local_string_facts(site, value, query)
            if string_facts is not None:
                return string_facts

            function = self.functions.get(site.caller_id)
            if function and value in function.parameters:
                param_index = function.parameters.index(value) + 1
                if self._parameter_fast_path_safe(function, value, site.start_byte):
                    child = ParamQuery(site.caller_id, param_index)
                    self._add_provenance(child, query)
                    return await self.resolve(child, stack)
            if value not in local_stack:
                definitions = self._local_reaching_definitions(site, value)
                if definitions:
                    resolved: list[Fact] = []
                    for definition in definitions:
                        resolved.extend(
                            await self._resolve_expression(
                                definition,
                                site,
                                query,
                                stack,
                                local_stack | {value},
                            )
                        )
                    if resolved:
                        return resolved

        llm_answer = await self._call_one_hop(site, query, raw)
        if llm_answer is not None:
            if llm_answer.kind == "PARAM" and llm_answer.param_index:
                child = ParamQuery(site.caller_id, llm_answer.param_index)
                self._add_provenance(child, query)
                return await self.resolve(child, stack)
            if llm_answer.kind == "VALUE" and llm_answer.value is not None:
                return [
                    Fact(
                        value=str(llm_answer.value),
                        origin_kind="LLM_CANDIDATE",
                        source_file=expression.file_path,
                        source_line=expression.line,
                        source_expr=llm_answer.source_expr or raw,
                        origin_query=query.token(),
                        source_site_id=query.token(),
                        resolved_by="LLM",
                    )
                ]
            if llm_answer.kind == "EXTERNAL":
                return [
                    Fact(
                        value=llm_answer.value or raw,
                        origin_kind="EXTERNAL_DATA",
                        source_file=expression.file_path,
                        source_line=expression.line,
                        source_expr=llm_answer.source_expr or raw,
                        origin_query=query.token(),
                        source_site_id=query.token(),
                        resolved_by="LLM",
                    )
                ]

        # A call through a pointer is unfollowable; plain field/variable reads
        # are ordinary external data.
        kind = "UNKNOWN_INDIRECT" if "(*" in raw else "EXTERNAL_DATA"
        return [
            Fact(
                value=raw,
                origin_kind=kind,
                source_file=expression.file_path,
                source_line=expression.line,
                source_expr=raw,
                origin_query=query.token(),
                source_site_id=query.token(),
                resolved_by="LLM" if self.one_hop_resolver else "SYNTAX",
            )
        ]

    # ---------------------------------------------------------- bounded values
    def _resolve_table_expression(
        self, expression: Expression, site: IndexedSite, query: Query
    ) -> list[Fact] | None:
        """Resolve a call proven to return a finite constant-table set.

        This handles both configured production wrappers and ordinary fixture
        functions such as ``return table[index]``.  It intentionally refuses
        mutable tables, computed values, and incomplete initializers.
        """
        node = expression.node
        if node is None or node.type != "call_expression":
            return None
        function_node = node.child_by_field_name("function")
        if function_node is None or function_node.type != "identifier":
            return None
        name = node_text(function_node, site.source)
        rule = self.value_rules.get(name)
        infos = self._function_infos_named(name)
        if not infos:
            return None

        selected: list[tuple[str, str, int, str, str, int, str]] | None = None
        for info in infos:
            selected = self._table_values_for_function(info, rule or {})
            if selected:
                break
        if not selected:
            return None

        set_id = hashlib.sha1(
            f"{site.site_id}:{name}:{selected[0][4]}".encode("utf-8", errors="replace")
        ).hexdigest()[:16]
        return [
            Fact(
                value=value,
                origin_kind="CONST_TABLE",
                source_file=table_file,
                source_line=table_line,
                source_expr=source_expr,
                origin_query=query.token(),
                source_site_id=f"{table_file}:{table_line}:{table_symbol}",
                link_method="TABLE_LOOKUP",
                metadata={
                    "table_file": table_file,
                    "table_line": table_line,
                    "table_symbol": table_symbol,
                    "index_expression": index_expression,
                    "bound": bound,
                    "set_id": set_id,
                    "wrapper": name,
                },
            )
            for value, table_file, table_line, source_expr, table_symbol, bound,
            index_expression in selected
        ]

    def _table_values_for_function(
        self, info: FunctionInfo, rule: dict[str, Any]
    ) -> list[tuple[str, str, int, str, str, int, str]] | None:
        kind = str(rule.get("kind") or "return_table")
        matches: list[tuple[Any, Any, str]] = []
        for candidate in _walk(info.ast_node):
            if candidate.type != "subscript_expression":
                continue
            parent = candidate.parent
            in_return = False
            while parent is not None and parent.id != info.ast_node.id:
                if parent.type == "return_statement":
                    in_return = True
                    break
                parent = parent.parent
            if kind == "return_table" and not in_return:
                continue
            if kind == "writes_table" and in_return:
                continue
            named = list(candidate.named_children)
            if len(named) < 2:
                continue
            table_symbol = node_text(named[0], info.source).strip()
            index_expression = node_text(named[1], info.source).strip()
            matches.append((candidate, named[0], table_symbol + "[" + index_expression + "]"))
        if not matches:
            return None

        output_args = {int(item) for item in (rule.get("output_args") or [])}
        parameters = info.parameters
        selected_match = None
        for candidate, _table_node, _raw in matches:
            if kind == "writes_table":
                assignment = candidate.parent
                while assignment is not None and assignment.type != "assignment_expression":
                    assignment = assignment.parent
                if assignment is None:
                    continue
                left_text = node_text(
                    assignment.child_by_field_name("left"), info.source
                ).strip()
                output_index = next(
                    (
                        index
                        for index, parameter in enumerate(parameters, start=1)
                        if re.search(rf"\b{re.escape(parameter)}\b", left_text)
                    ),
                    None,
                )
                if output_index is None or (output_args and output_index not in output_args):
                    continue
            selected_match = candidate
            break
        if selected_match is None:
            return None

        named = list(selected_match.named_children)
        table_symbol = node_text(named[0], info.source).strip()
        index_expression = node_text(named[1], info.source).strip()
        values = self._constant_table_values(info.node.file_name, table_symbol)
        if not values:
            return None
        return [
            (
                value,
                table_file,
                table_line,
                source_expr,
                table_symbol,
                len(values),
                index_expression,
            )
            for value, table_file, table_line, source_expr in values
        ]

    def _constant_table_values(
        self, file_name: str, symbol: str
    ) -> list[tuple[str, str, int, str]] | None:
        """Read literal/macro/enum elements from one visible const array."""
        for visible_file in self._visible_files(file_name):
            tree, source = self.trees.get(visible_file, (None, b""))
            if tree is None:
                continue
            for declaration in _walk(tree.root_node):
                if declaration.type != "declaration":
                    continue
                declaration_text = node_text(declaration, source)
                if not re.search(r"\b(?:static\s+)?const\b", declaration_text):
                    continue
                for init in declaration.named_children:
                    if init.type != "init_declarator":
                        continue
                    declarator = init.child_by_field_name("declarator")
                    if _extract_declarator_identifier(declarator, source) != symbol:
                        continue
                    value_node = init.child_by_field_name("value")
                    if value_node is None or value_node.type != "initializer_list":
                        continue
                    elements: list[Any] = []
                    for element in value_node.named_children:
                        if element.type == "initializer_pair":
                            element = element.child_by_field_name("value") or element
                        elements.append(element)
                    values: list[tuple[str, str, int, str]] = []
                    for element in elements:
                        raw = strip_outer_parens(node_text(element, source).strip())
                        resolved = self._resolve_macro(raw, visible_file)
                        if resolved is not None:
                            value = resolved[0]
                        elif self._literal(raw):
                            value = raw
                        else:
                            values = []
                            break
                        values.append(
                            (
                                value,
                                self.project_structure.get(visible_file, visible_file),
                                element.start_point.row + 1,
                                raw,
                            )
                        )
                    if values:
                        return values
        return None

    def _wrapper_output_facts(
        self, site: IndexedSite, name: str, query: Query
    ) -> list[Fact] | None:
        """Replace an initializer only after a checked wrapper write."""
        function = self.functions.get(site.caller_id)
        if function is None:
            return None
        for candidate in self.sites_by_caller.get(site.caller_id, []):
            if candidate.start_byte >= site.start_byte:
                break
            rule = self.value_rules.get(candidate.callee_name)
            if not rule or str(rule.get("kind")) != "writes_table":
                continue
            output_values = self._wrapper_output_values(candidate, name, rule)
            if not output_values or not self._wrapper_success_guard(candidate, site):
                continue
            set_id = hashlib.sha1(
                f"{candidate.site_id}:{name}".encode("utf-8", errors="replace")
            ).hexdigest()[:16]
            bounded = len(output_values) > 1
            return [
                Fact(
                    value=value,
                    origin_kind="BOUNDED_SET" if bounded else "CONST_TABLE",
                    source_file=table_file,
                    source_line=table_line,
                    source_expr=source_expr,
                    origin_query=query.token(),
                    source_site_id=f"{table_file}:{table_line}:{table_symbol}",
                    link_method="WRAPPER_WRITE",
                    metadata={
                        "wrapper": candidate.callee_name,
                        "output_variable": name,
                        "write_site": candidate.site_id,
                        "table_file": table_file,
                        "table_line": table_line,
                        "table_symbol": table_symbol,
                        "set_id": set_id,
                    },
                )
                for value, table_file, table_line, source_expr, table_symbol in output_values
            ]
        return None

    def _wrapper_output_values(
        self, candidate: IndexedSite, name: str, rule: dict[str, Any]
    ) -> list[tuple[str, str, int, str, str]] | None:
        node = candidate.ast_node
        if node is None:
            return None
        arguments = list(candidate.arguments)
        infos = self._function_infos_named(candidate.callee_name)
        for info in infos:
            for subscript in _walk(info.ast_node):
                if subscript.type != "subscript_expression":
                    continue
                assignment = subscript.parent
                while assignment is not None and assignment.type != "assignment_expression":
                    assignment = assignment.parent
                if assignment is None:
                    continue
                left = node_text(assignment.child_by_field_name("left"), info.source)
                if not any(
                    re.search(rf"\b{re.escape(parameter)}\b", left)
                    for parameter in info.parameters
                ):
                    continue
                parameter_index = next(
                    index
                    for index, parameter in enumerate(info.parameters, start=1)
                    if re.search(rf"\b{re.escape(parameter)}\b", left)
                )
                if parameter_index > len(arguments):
                    continue
                actual = normalise_handle(arguments[parameter_index - 1].text)
                if actual != normalise_handle(name):
                    continue
                named = list(subscript.named_children)
                if len(named) < 2:
                    continue
                table_symbol = node_text(named[0], info.source).strip()
                values = self._constant_table_values(info.node.file_name, table_symbol)
                if not values:
                    continue
                return [
                    (value, table_file, table_line, source_expr, table_symbol)
                    for value, table_file, table_line, source_expr in values
                ]
        return None

    def _wrapper_success_guard(self, candidate: IndexedSite, use_site: IndexedSite) -> bool:
        node = candidate.ast_node
        if node is None:
            return False
        parent = node.parent
        while parent is not None and parent.start_byte < use_site.start_byte:
            if parent.type == "if_statement":
                condition = parent.child_by_field_name("condition")
                consequence = parent.child_by_field_name("consequence")
                if condition is not None and self._contains(condition, node):
                    if consequence is not None and any(
                        item.type == "return_statement" for item in _walk(consequence)
                    ):
                        return True
            parent = parent.parent

        # Common form: rc = wrapper(...); if (rc == -1) return;
        call_parent = node.parent
        variable = ""
        if call_parent is not None and call_parent.type == "assignment_expression":
            left = call_parent.child_by_field_name("left")
            variable = node_text(left, candidate.source).strip() if left else ""
        elif call_parent is not None and call_parent.type == "init_declarator":
            declarator = call_parent.child_by_field_name("declarator")
            variable = _extract_declarator_identifier(declarator, candidate.source) or ""
        if variable:
            if _IDENTIFIER.fullmatch(variable):
                function = self.functions.get(candidate.caller_id)
                if function is None:
                    return False
                for statement in _walk(function.ast_node):
                    if statement.type != "if_statement" or statement.start_byte <= node.end_byte:
                        continue
                    if statement.end_byte > use_site.start_byte:
                        continue
                    condition = statement.child_by_field_name("condition")
                    consequence = statement.child_by_field_name("consequence")
                    if (
                        condition is not None
                        and re.search(rf"\b{re.escape(variable)}\b", node_text(condition, function.source))
                        and re.search(r"==\s*-?1\b", node_text(condition, function.source))
                        and consequence is not None
                        and any(item.type == "return_statement" for item in _walk(consequence))
                    ):
                        return True
        return False

    def _local_string_facts(
        self, site: IndexedSite, name: str, query: Query
    ) -> list[Fact] | None:
        function = self.functions.get(site.caller_id)
        if function is None or not _IDENTIFIER.fullmatch(name):
            return None
        writes: list[tuple[int, str, str]] = []
        for node in _walk(function.ast_node):
            if node.start_byte >= site.start_byte:
                continue
            if node.type in {"assignment_expression", "init_declarator"}:
                left = node.child_by_field_name("left") or node.child_by_field_name("declarator")
                right = node.child_by_field_name("right") or node.child_by_field_name("value")
                if left is not None and right is not None:
                    left_name = _extract_declarator_identifier(left, function.source)
                    if left_name == name:
                        raw = strip_outer_parens(node_text(right, function.source).strip())
                        if _STRING_OR_CHAR.fullmatch(raw) and raw.startswith(('"', 'u8"', 'u"', 'U"', 'L"')):
                            writes.append((node.start_byte, raw, node_text(node, function.source)))
            if node.type != "call_expression":
                continue
            called = node.child_by_field_name("function")
            arguments = node.child_by_field_name("arguments")
            if called is None or arguments is None or called.type != "identifier":
                continue
            called_name = node_text(called, function.source)
            if called_name not in {"strcpy", "strncpy"}:
                continue
            args = list(arguments.named_children)
            if len(args) < 2:
                continue
            destination = normalise_handle(node_text(args[0], function.source))
            if destination != name:
                continue
            raw = strip_outer_parens(node_text(args[1], function.source).strip())
            if not _STRING_OR_CHAR.fullmatch(raw) or not raw.startswith(('"', 'u8"', 'u"', 'U"', 'L"')):
                continue
            if called_name == "strncpy" and len(args) >= 3:
                bound = strip_outer_parens(node_text(args[2], function.source).strip())
                bound_value = self._parse_c_integer_literal(bound)
                literal_body = re.sub(r"^(?:u8|u|U|L)?\"|\"$", "", raw)
                # A bound no larger than literal content may omit the NUL;
                # unknown bounds are not source-safe for a process name.
                if bound_value is None or bound_value <= len(literal_body):
                    continue
            writes.append((node.start_byte, raw, node_text(node, function.source)))
        if not writes:
            return None
        unique: list[str] = []
        for _offset, raw, _text in sorted(writes):
            if raw not in unique:
                unique.append(raw)
        bounded = len(unique) > 1
        set_id = hashlib.sha1(
            f"{site.site_id}:{name}:strings".encode("utf-8", errors="replace")
        ).hexdigest()[:16]
        return [
            Fact(
                value=raw,
                origin_kind="BOUNDED_SET" if bounded else "CONST",
                source_file=function.node.file_path or site.file_path,
                source_line=(
                    function.source[:next(offset for offset, raw_value, _ in writes if raw_value == raw)].count(b"\n")
                    + 1
                ),
                source_expr=raw,
                origin_query=query.token(),
                source_site_id=f"{site.file_name}:{writes[0][0]}:{name}",
                link_method="STRING_LITERAL",
                metadata={
                    "buffer": name,
                    "write_sites": [
                        {"line": function.source[:offset].count(b"\n") + 1, "expression": text}
                        for offset, _raw, text in writes
                    ],
                    "strings": unique,
                    "set_id": set_id,
                },
            )
            for raw in unique
        ]

    async def _resolve_parameter(
        self, query: ParamQuery, stack: frozenset[str]
    ) -> list[Fact]:
        # The value used by `void f(int x)` may come from every reachable call
        # to f(...). Turn the formal parameter back into each actual argument.
        info = self.functions.get(query.function_id)
        callers = [
            edge
            for edge in self.reverse_callers.get(query.function_id, [])
            if not edge.synthetic_callback
        ]
        if not callers:
            name = (
                info.parameters[query.param_index - 1]
                if info and query.param_index <= len(info.parameters)
                else f"param_{query.param_index}"
            )
            parameter_node = (
                info.parameter_nodes[query.param_index - 1]
                if info and query.param_index <= len(info.parameter_nodes)
                else None
            )
            return [
                Fact(
                    value=name,
                    origin_kind="EXTERNAL_ENTRY",
                    source_file=(
                        self.project_structure.get(
                            info.node.file_name, info.node.file_path or ""
                        )
                        if info
                        else ""
                    ),
                    source_line=(
                        parameter_node.start_point.row + 1
                        if parameter_node is not None
                        else (info.node.start_line if info else -1)
                    ),
                    source_expr=name,
                    origin_query=query.token(),
                    source_site_id=query.token(),
                )
            ]
        facts: list[Fact] = []
        for edge in sorted(callers, key=lambda item: item.site_id):
            child = ArgQuery(edge.site_id, query.param_index)
            self._add_provenance(child, query)
            caller_facts = await self.resolve(child, stack)
            for fact in caller_facts:
                facts.append(
                    replace(
                        fact,
                        link_method=fact.link_method or "PARAM_CALLER",
                        metadata={
                            **(fact.metadata or {}),
                            "parameter_caller": edge.caller_id,
                            "caller_reachable": edge.caller_id in self.reachable,
                        },
                    )
                )
        return facts

    async def _await_llm(self, callback: Callable, *arguments: Any) -> Any:
        """Invoke an injected resolver under the shared LLM concurrency cap.

        Seeds fan out with ``asyncio.gather``, so without this gate a large
        process could open one request per pending query at once.
        """
        if callback is None:
            return None
        if self._llm_gate is None:
            self._llm_gate = asyncio.Semaphore(self.llm_concurrency)
        async with self._llm_gate:
            try:
                result = callback(*arguments)
                if inspect.isawaitable(result):
                    result = await result
                return result
            except Exception as exc:
                # A transport/model failure must degrade this one query to the
                # syntactic answer, never abort the whole process run.
                self.transfer_rejections["llm_exception"] += 1
                print(f"Value-flow LLM query failed, continuing without it: {exc}")
                return None

    async def _call_one_hop(
        self, site: IndexedSite, query: Query, expression: str
    ) -> OneHopAnswer | None:
        return await self._await_llm(
            self.one_hop_resolver, site, getattr(query, "arg_index", -1), expression
        )

    # --------------------------------------------------------------- handles
    def _handle_candidates(
        self, site: IndexedSite, dependencies: tuple[str, ...]
    ) -> list[int]:
        explicit = site and self.function_configs.get(site.callee_name, {}).get(
            "handle_index"
        )
        if explicit:
            return [int(explicit)]
        opens = [
            candidate
            for candidate in self.sites_by_caller.get(site.caller_id, [])
            if candidate.callee_name in dependencies
            and candidate.start_byte < site.start_byte
        ]
        matches: set[int] = set()
        site_arguments = (
            site.target_arguments
            if site.is_configured_macro_target
            else site.arguments
        )
        for index, argument in enumerate(site_arguments, start=1):
            root = normalise_handle(argument.text)
            if not root:
                continue
            for opening in opens:
                if any(
                    normalise_handle(candidate.text) == root
                    for candidate in (
                        opening.target_arguments
                        if opening.is_configured_macro_target
                        else opening.arguments
                    )
                ):
                    matches.add(index)
        return sorted(matches)

    def handle_query_for_seed(self, seed: Seed) -> HandleQuery | None:
        # A target with dependent_functions (read/close) does not resolve its
        # own argument as a value. Instead, find the earlier configured open
        # that owns the same handle and resolve the open's value argument.
        dependencies = tuple(
            name
            for name in seed.config.get("dependent_functions", [])
            if name in self.function_configs and name != seed.target_function
        )
        if not dependencies:
            return None
        candidates = self._handle_candidates(seed.site, dependencies)
        # Index 0 deliberately represents an ambiguous handle.  Keeping it as
        # a query lets the resolver emit a visible HANDLE_AMBIGUOUS fact if
        # exact binding and the optional LLM candidate both fail.
        query = HandleQuery(
            seed.site.site_id,
            candidates[0] if len(candidates) == 1 else 0,
            target=True,
        )
        self._handle_dependencies[query.token()] = dependencies
        return query

    async def _resolve_handle(
        self, query: HandleQuery, stack: frozenset[str]
    ) -> list[Fact]:
        # Handle resolution order: same-function variable binding -> parameter
        # binding through callers -> global/field binding -> LLM candidate.
        # A nearby open with a different handle is never proof of ownership.
        site = self.sites.get(query.call_site_id)
        dependencies = self._handle_dependencies.get(query.token(), ())
        if site is None or not dependencies:
            return [self._unresolved_fact(query, "HANDLE_AMBIGUOUS")]
        argument = (
            site.target_argument(query.arg_index)
            if query.target and site.is_configured_macro_target
            else site.argument(query.arg_index)
        )
        root = normalise_handle(argument.text) if argument is not None else ""
        bindings = (
            self._binding_opens(site.caller_id, root, site.start_byte, dependencies)
            if root
            else []
        )
        if bindings:
            facts: list[Fact] = []
            for opening in bindings:
                indices = list(
                    self.function_configs.get(opening.callee_name, {}).get("indices")
                    or []
                )
                for index in indices:
                    child = ArgQuery(opening.site_id, int(index), target=True)
                    self._add_provenance(child, query)
                    for fact in await self.resolve(child, stack):
                        facts.append(
                            Fact(**{**fact.to_dict(), "link_method": "VARTRACE"})
                        )
            if facts:
                return facts

        function = self.functions.get(site.caller_id)
        if argument is not None and function and root in function.parameters:
            parameter_index = function.parameters.index(root) + 1
            facts: list[Fact] = []
            for edge in sorted(
                self.reverse_callers.get(site.caller_id, []),
                key=lambda item: item.site_id,
            ):
                if edge.synthetic_callback:
                    continue
                child = HandleQuery(edge.site_id, parameter_index)
                self._handle_dependencies[child.token()] = dependencies
                self._add_provenance(child, query)
                caller_facts = await self.resolve(child, stack)
                for fact in caller_facts:
                    facts.append(
                        replace(
                            fact,
                            link_method=fact.link_method or "PARAM_CALLER",
                            metadata={
                                **(fact.metadata or {}),
                                "parameter_caller": edge.caller_id,
                                "caller_reachable": edge.caller_id in self.reachable,
                            },
                        )
                    )
            if facts:
                return facts

        # A global or struct field may be opened in another reachable function.
        global_bindings: list[IndexedSite] = []
        is_local = bool(function and self._is_local_variable(function, root))
        static_scope = bool(
            function and root in self.file_static_vars.get(function.node.file_name, set())
        )
        if root and ("->" in root or "." in root or not is_local or static_scope):
            candidate_callers = self.reachable
            if static_scope and function is not None:
                candidate_callers = {
                    caller_id
                    for caller_id, info in self.functions.items()
                    if info.node.file_name == function.node.file_name
                }
            for caller_id in candidate_callers:
                global_bindings.extend(
                    self._binding_opens(caller_id, root, 1 << 62, dependencies)
                )
        if global_bindings:
            facts = []
            for opening in sorted(
                {item.site_id: item for item in global_bindings}.values(),
                key=lambda item: item.site_id,
            ):
                for index in (
                    self.function_configs.get(opening.callee_name, {}).get("indices")
                    or []
                ):
                    child = ArgQuery(opening.site_id, int(index), target=True)
                    self._add_provenance(child, query)
                    for fact in await self.resolve(child, stack):
                        facts.append(
                            Fact(**{**fact.to_dict(), "link_method": "VARTRACE"})
                        )
            return facts
        fallback = await self._await_llm(
            self.handle_llm_resolver, site, query.arg_index, dependencies
        )
        facts = [
            Fact(
                value=str(answer.value),
                origin_kind="LLM_CANDIDATE",
                source_file=site.file_path,
                source_line=site.line,
                source_expr=answer.source_expr
                or (argument.text if argument else "HANDLE_AMBIGUOUS"),
                origin_query=query.token(),
                source_site_id=query.token(),
                resolved_by="LLM",
                link_method="LLM",
            )
            for answer in (fallback or [])
            if answer.kind == "VALUE" and answer.value is not None
        ]
        if facts:
            return facts

        # Do not use the historical nearest-open fallback here.  It can bind a
        # consumer to an unrelated handle and manufacture several false exact
        # values (the SVM records that motivated this fix were an example).
        return facts or [self._unresolved_fact(query, "HANDLE_AMBIGUOUS")]

    def _binding_opens(
        self, caller_id: str, root: str, before_byte: int, dependencies: tuple[str, ...]
    ) -> list[IndexedSite]:
        candidates = [
            site
            for site in self.sites_by_caller.get(caller_id, [])
            if site.callee_name in dependencies
            and site.start_byte < before_byte
            and any(
                normalise_handle(argument.text) == root
                for argument in (
                    site.target_arguments
                    if site.is_configured_macro_target
                    else site.arguments
                )
            )
        ]
        if not candidates:
            return []
        close_sites = [
            site
            for site in self.sites_by_caller.get(caller_id, [])
            if self.function_configs.get(site.callee_name, {}).get("type") == "CLOSEF"
            and site.start_byte < before_byte
            and any(
                normalise_handle(argument.text) == root
                for argument in (
                    site.target_arguments
                    if site.is_configured_macro_target
                    else site.arguments
                )
            )
        ]
        if close_sites:
            last_close = max(item.start_byte for item in close_sites)
            candidates = [item for item in candidates if item.start_byte > last_close]
        return candidates

    def _locally_provable(self, site: IndexedSite) -> bool:
        """Local-backwalk proof: every configured argument of this target
        call resolves mechanically inside its own function.

        Only literals, visible macros, local reaching definitions
        (recursively), and handles bound to a same-function open qualify.
        Cross-function edges, proximity, and the LLM are deliberately not
        used, so the result proves a source-valid value for the enclosing
        function, never that the function executes.
        """
        seen: set[int] = set()
        return self._locally_provable_checked(site, seen)

    def _locally_provable_checked(
        self, site: IndexedSite, seen: set[int]
    ) -> bool:
        if id(site) in seen:
            return False
        seen.add(id(site))
        config = self.function_configs.get(site.callee_name, {})
        dependencies = tuple(
            name
            for name in config.get("dependent_functions", [])
            if name in self.function_configs and name != site.callee_name
        )
        if dependencies:
            candidates = self._handle_candidates(site, dependencies)
            if len(candidates) != 1:
                return False
            root = normalise_handle(site.argument(candidates[0]).text)
            bindings = self._binding_opens(
                site.caller_id, root, site.start_byte, dependencies
            )
            if len(bindings) != 1:
                return False
            opening = bindings[0]
            indices = self.function_configs.get(opening.callee_name, {}).get(
                "indices"
            ) or []
            if not indices:
                return False
            return all(
                self._locally_provable_argument(opening, int(index), seen)
                for index in indices
            )
        indices = config.get("indices") or []
        if not indices:
            return False
        return all(
            self._locally_provable_argument(site, int(index), seen)
            for index in indices
        )

    def _locally_provable_argument(
        self, site: IndexedSite, index: int, seen: set[int]
    ) -> bool:
        argument = (
            site.target_argument(index)
            if site.is_configured_macro_target
            else site.argument(index)
        )
        if argument is None:
            return False
        return self._expression_locally_provable(site, argument.text, seen)

    def _expression_locally_provable(
        self, site: IndexedSite, text: str, seen: set[int]
    ) -> bool:
        value = strip_outer_parens(text.strip())
        if not value:
            return False
        if self._literal(value):
            return True
        if self._resolve_macro(value, site.file_name) is not None:
            return True
        if not _IDENTIFIER.fullmatch(value):
            return False
        key = (site.site_id, value)
        if key in seen:
            return False
        seen.add(key)
        definitions = self._local_reaching_definitions(site, value)
        if not definitions:
            return False
        return all(
            self._expression_locally_provable(site, definition.text, seen)
            for definition in definitions
        )

    def _is_local_variable(self, function: FunctionInfo, name: str) -> bool:
        if not _IDENTIFIER.fullmatch(name) or function.ast_node is None:
            return False
        for node in _walk(function.ast_node):
            if node.type not in {"init_declarator", "declaration"}:
                continue
            declarator = node.child_by_field_name("declarator")
            if (
                declarator is not None
                and _extract_declarator_identifier(declarator, function.source) == name
            ):
                return True
            if any(
                _extract_declarator_identifier(child, function.source) == name
                for child in node.named_children
            ):
                return True
        return False

    # ------------------------------------------------------- return/call number
    async def _resolve_return_use(self, query: ReturnUseQuery) -> str:
        if query.call_site_id in self._operation_cache:
            return self._operation_cache[query.call_site_id]
        site = self.sites[query.call_site_id]
        # Syntax first: a definite local answer costs nothing, so the LLM is
        # only asked about call sites the AST cannot classify on its own.
        operation = self._syntactic_return_use(site)
        if operation not in {"READF", "WRITEF"}:
            operation = await self._await_llm(
                self.return_use_resolver, site, site.callee_name
            )
        operation = operation if operation in {"READF", "WRITEF"} else "UNRESOLVED"
        self._operation_cache[query.call_site_id] = operation
        return operation

    def _syntactic_return_use(self, site: IndexedSite) -> str | None:
        node = site.ast_node
        if node is None:
            return None
        parent = node.parent
        while parent is not None and parent.type in {
            "parenthesized_expression",
            "cast_expression",
        }:
            parent = parent.parent
        if parent is None:
            return None
        text = node_text(parent, site.source)
        if parent.type == "assignment_expression":
            left = parent.child_by_field_name("left")
            right = parent.child_by_field_name("right")
            if (
                left is not None
                and right is not None
                and node.start_byte >= left.start_byte
                and node.end_byte <= left.end_byte
            ):
                return "WRITEF"
            if right is not None:
                target = (
                    node_text(left, site.source).strip() if left is not None else ""
                )
                if _IDENTIFIER.fullmatch(target):
                    return self._classify_later_pointer_use(
                        site, target, parent.end_byte
                    )
        if parent.type == "init_declarator":
            declarator = parent.child_by_field_name("declarator")
            target = _extract_declarator_identifier(declarator, site.source)
            if target:
                return self._classify_later_pointer_use(site, target, parent.end_byte)
        if parent.type in {
            "field_expression",
            "subscript_expression",
            "pointer_expression",
        }:
            grandparent = parent.parent
            if grandparent is not None and grandparent.type == "assignment_expression":
                left = grandparent.child_by_field_name("left")
                if (
                    left is not None
                    and parent.start_byte >= left.start_byte
                    and parent.end_byte <= left.end_byte
                ):
                    return "WRITEF"
        # Anything else (bare statement, condition, nested expression) is not
        # something the AST can classify confidently; leave it to the LLM.
        return None

    def _classify_later_pointer_use(
        self, site: IndexedSite, target: str, after_byte: int
    ) -> str:
        function = self.functions.get(site.caller_id)
        if function and function.ast_node is not None:
            for later in _walk(function.ast_node):
                if later.start_byte <= after_byte:
                    continue
                later_text = node_text(later, site.source)
                if later.type == "assignment_expression" and re.search(
                    rf"(?:\*\s*{re.escape(target)}\b|\b{re.escape(target)}\s*->)",
                    later_text,
                ):
                    return "WRITEF"
        return "READF"

    async def call_number_for(
        self, function_id: str, preferred_functions: Iterable[str] = ()
    ) -> str | None:
        preferred_tuple = tuple(dict.fromkeys(preferred_functions))
        cache_key = (function_id, preferred_tuple)
        if cache_key in self._call_number_cache:
            return self._call_number_cache[cache_key]
        event_names = {
            name
            for name in self.function_configs
            if name
            in {
                "scf_evt_post",
                "scf_var_evt",
                "pmf_addevent",
                "pmf_addvarevt",
                "pmd_addvarevt",
            }
            or "addevent" in name.lower()
            or "addvarevt" in name.lower()
            or name.lower().endswith("evt_post")
            or name.lower().endswith("var_evt")
        }
        answer: str | None = None
        preferred = [function_id]
        preferred.extend(
            item
            for item in preferred_tuple
            if item != function_id and item in self.reachable
        )
        for current in dict.fromkeys(preferred):
            answer = await self._call_number_in_function(current, event_names)
            if answer is not None:
                break

        queue = deque([function_id])
        visited = {function_id}
        while queue and answer is None:
            current = queue.popleft()
            for edge in sorted(
                self.reverse_callers.get(current, []), key=lambda item: item.site_id
            ):
                if edge.caller_id in self.reachable and edge.caller_id not in visited:
                    visited.add(edge.caller_id)
                    answer = await self._call_number_in_function(
                        edge.caller_id, event_names
                    )
                    if answer is not None:
                        break
                    queue.append(edge.caller_id)
        self._call_number_cache[cache_key] = answer
        return answer

    async def _call_number_in_function(
        self, function_id: str, event_names: set[str]
    ) -> str | None:
        event_sites = [
            site
            for site in self.sites_by_caller.get(function_id, [])
            if site.callee_name in event_names
        ]
        if not event_sites:
            return None
        facts = await self.resolve(
            ArgQuery(sorted(event_sites, key=lambda item: item.site_id)[0].site_id, 1)
        )
        concrete = next(
            (fact.value for fact in facts if fact.origin_kind in {"CONST", "MACRO"}),
            None,
        )
        return concrete or (facts[0].value if facts else None)

    # ------------------------------------------------------------ public run
    async def run(self) -> list[ResolvedSeed]:
        """Resolve every seed through a bounded async producer/consumer pipeline.

        A small pool of worker tasks pulls ``(index, seed)`` items off a
        bounded queue and awaits the existing ``_resolve_seed()`` state
        machine.  The workers only ever run on this coordinator's event loop,
        so shared resolution state (``results``, ``in_flight``, provenance,
        caches) is untouched by threads or processes.  While one worker is
        yielded away inside a pending model request, the other workers keep
        doing CPU-side tracing; ``_llm_gate`` still caps concurrent model
        calls at ``llm_concurrency``.

        Final records are flattened in original seed order, never completion
        order, so output/cache/diagnostic ordering is unchanged.
        """
        if not self.seeds:
            self.persist_cache()
            return []

        limit = max(2, min(len(self.seeds), self.llm_concurrency * 2))
        queue: asyncio.Queue[tuple[int, Seed] | None] = asyncio.Queue(maxsize=limit)
        rows_by_seed: dict[int, list[ResolvedSeed]] = {}
        first_error: BaseException | None = None

        async def producer() -> None:
            for index, seed in enumerate(self.seeds):
                await queue.put((index, seed))
            # One sentinel per worker so idle workers terminate after the
            # last real seed has been consumed.
            for _ in range(limit):
                await queue.put(None)

        async def worker() -> None:
            nonlocal first_error
            while True:
                item = await queue.get()
                if item is None:
                    return
                if first_error is not None:
                    # A sibling seed failed: keep draining the queue so the
                    # producer can finish, but do no further resolution work.
                    continue
                index, seed = item
                started = time.perf_counter()
                try:
                    rows = await self._resolve_seed(seed)
                except BaseException as exc:
                    if first_error is None:
                        first_error = exc
                    raise
                rows_by_seed[index] = rows
                if self.progress is not None:
                    self.progress(seed, rows, time.perf_counter() - started)

        producer_task = asyncio.create_task(producer())
        workers = [asyncio.create_task(worker()) for _ in range(limit)]
        try:
            # Await the producer and workers together.  Waiting for the
            # producer first can deadlock if every worker fails while the
            # producer is still trying to enqueue work: there would be no
            # consumers left to drain the bounded queue, so the exception
            # cleanup below would never be reached.
            await asyncio.gather(producer_task, *workers)
        except BaseException:
            # A seed failure (or cancellation of run() itself) cancels the
            # remaining scheduler work instead of leaving it behind.
            for task in [producer_task, *workers]:
                if not task.done():
                    task.cancel()
            await asyncio.gather(producer_task, *workers, return_exceptions=True)
            raise

        records = [
            record
            for index in range(len(self.seeds))
            for record in rows_by_seed[index]
        ]
        self.persist_cache()
        return self._deduplicate_records(records)

    async def _resolve_seed(self, seed: Seed) -> list[ResolvedSeed]:
        if self.transfer_resolver is not None:
            return await self._resolve_seed_with_transfers(seed)

        # One seed is one target call site. It can yield several rows when its
        # configured argument has several possible source values/paths.
        operation = seed.config.get("type") or "NO DATA"
        if operation == "WRITEF/READF":
            operation_facts = await self.resolve(ReturnUseQuery(seed.site.site_id))
            operation = operation_facts[0].value if operation_facts else "UNRESOLVED"
        handle_query = self.handle_query_for_seed(seed)
        queries: list[tuple[int, Query]] = []
        if handle_query is not None:
            # A handle query already discovers the concrete bound open call and
            # resolves that open's configured value argument(s).  Scheduling it
            # once per configured open-family member created duplicate records
            # whenever several alternatives shared this consumer.
            queries.append((handle_query.arg_index, handle_query))
        else:
            queries.extend(
                (
                    int(index),
                    ArgQuery(seed.site.site_id, int(index), target=True),
                )
                for index in seed.config.get("indices") or []
            )
        if not queries:
            no_target_query = ArgQuery(seed.site.site_id, 0, target=True)
            self._label_query(no_target_query)
            fact = Fact(
                value="NO TARGET",
                origin_kind="CONST",
                source_file=seed.site.file_path,
                source_line=seed.site.line,
                source_expr=seed.target_function,
                origin_query=no_target_query.token(),
            )
            call_number = await self.call_number_for(seed.site.caller_id)
            return [
                self._resolved_seed(
                    seed, 0, fact, operation, call_number, no_target_query
                )
            ]
        rows: list[ResolvedSeed] = []
        seen_queries: dict[str, list[Fact]] = {}
        for arg_index, query in queries:
            if query.token() not in seen_queries:
                seen_queries[query.token()] = await self.resolve(query)
            for fact in seen_queries[query.token()]:
                if (
                    seed.local_backwalk
                    and str(fact.origin_kind) != "UNRESOLVED"
                ):
                    fact = replace(fact, link_method="LOCAL_BACKWALK")
                callback_meta = self.callback_metadata(seed.site.caller_id)
                if callback_meta and str(fact.origin_kind) != "UNRESOLVED":
                    fact = replace(
                        fact,
                        metadata={**(fact.metadata or {}), **callback_meta},
                    )
                call_number = await self.call_number_for(
                    seed.site.caller_id,
                    self._provenance_functions(fact, query),
                )
                rows.append(
                    self._resolved_seed(
                        seed, arg_index, fact, operation, call_number, query
                    )
                )
        return rows

    # ------------------------------------------------------ route transfers
    def routes_for_seed(self, seed: Seed) -> list[RouteGuide]:
        """Return deterministic root-valid routes for one exact target seed.

        The reverse caller index already contains the exact byte-based site for
        every ordinary edge and the synthetic site for callback edges.  Walking
        that index keeps route identity independent from display labels and,
        importantly, never unions unrelated callers of a formal parameter.
        """
        cache_key = (seed.site.site_id, seed.local_backwalk)
        cached_routes = self._route_cache.get(cache_key)
        if cached_routes is not None:
            return cached_routes
        target_caller = seed.site.caller_id
        roots = {
            f"[{file_name}]{function_name}"
            for file_name, function_name in self.entry_points
            if f"[{file_name}]{function_name}" in self.registry
        }
        if seed.local_backwalk and target_caller not in self.reachable:
            digest = hashlib.sha256(
                f"local\0{seed.site.site_id}".encode("utf-8", errors="replace")
            ).hexdigest()[:20]
            routes = [
                RouteGuide(
                    route_id=f"route:{digest}",
                    root_function_id=target_caller,
                    edges=(),
                    target_site_id=seed.site.site_id,
                    reachability="LOCAL_BACKWALK",
                )
            ]
            self._route_cache[cache_key] = routes
            return routes
        if target_caller not in self.reachable or not roots:
            self._route_cache[cache_key] = []
            return []

        found: list[tuple[str, tuple[CallerEdge, ...]]] = []
        safety_limit = 10000

        def walk(current: str, reverse_edges: tuple[CallerEdge, ...], visited: frozenset[str]) -> None:
            if len(found) >= safety_limit:
                return
            if current in roots:
                found.append((current, tuple(reversed(reverse_edges))))
                return
            for edge in sorted(
                self.reverse_callers.get(current, []),
                key=lambda item: (item.site_id, item.caller_id),
            ):
                if edge.caller_id not in self.reachable:
                    continue
                if edge.caller_id in visited or edge.site_id in {
                    item.site_id for item in reverse_edges
                }:
                    continue
                walk(edge.caller_id, reverse_edges + (edge,), visited | {edge.caller_id})

        walk(target_caller, (), frozenset({target_caller}))
        if len(found) >= safety_limit:
            self.transfer_diagnostics.append(
                f"route limit {safety_limit} reached for {seed.site.site_id}"
            )
        routes: list[RouteGuide] = []
        for root, edges in found:
            parts = [root, *(edge.site_id for edge in edges), seed.site.site_id]
            digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:20]
            reachability = (
                "CALLBACK" if any(edge.synthetic_callback for edge in edges) else "DIRECT_ROOT"
            )
            routes.append(
                RouteGuide(
                    route_id=f"route:{digest}",
                    root_function_id=root,
                    edges=edges,
                    target_site_id=seed.site.site_id,
                    reachability=reachability,
                )
            )
        routes = sorted(routes, key=lambda item: item.route_id)
        self._route_cache[cache_key] = routes
        return routes

    def initial_route_arm(
        self,
        *,
        route: RouteGuide,
        site: IndexedSite,
        indices: Iterable[int],
    ) -> RouteArm:
        """Build one correlated bundle from exact source arguments."""
        bindings: list[Binding] = []
        sources: dict[int, dict[str, Any]] = {}
        for raw_index in indices:
            index = int(raw_index)
            expression = (
                site.target_argument(index)
                if site.is_configured_macro_target
                else site.argument(index)
            )
            if expression is None:
                bindings.append(Binding(index, "UNKNOWN", "missing argument"))
                continue
            bindings.append(Binding(index, "EXPRESSION", expression.text.strip()))
            sources[index] = self._expression_source(expression)
        correlation = hashlib.sha256(
            f"{route.route_id}\0initial".encode("utf-8")
        ).hexdigest()[:20]
        return RouteArm(
            route_id=route.route_id,
            correlation_id=f"corr:{correlation}",
            bindings=bindings,
            source_by_arg=sources,
        )

    def _expression_source(self, expression: Expression) -> dict[str, Any]:
        return {
            "file": expression.file_path,
            "line": expression.line,
            "expr": expression.text.strip(),
            "source_site_id": f"{expression.file_name}:{expression.line}:{expression.text.strip()}",
            "origin_kind": "CONST",
        }

    def _transfer_visible_names(self, file_name: str) -> set[str]:
        cached = self._visible_names_cache.get(file_name)
        if cached is not None:
            return cached
        names = set(self.file_macros.get(file_name, {}))
        try:
            enum_values, _ = self._visible_enum_index(file_name)
            names.update(enum_values)
        except Exception:
            pass
        self._visible_names_cache[file_name] = names
        return names

    def _constant_from_text(self, text: str, file_name: str) -> tuple[str, str] | None:
        value = strip_outer_parens(text.strip())
        if self._literal(value):
            # The transfer evaluator only promises exact integer/string
            # values.  Preserve the original spelling at the output boundary.
            if (
                self._parse_c_integer_literal(value) is not None
                or _STRING_OR_CHAR.fullmatch(value)
                or value in {"NULL", "true", "false", "nullptr"}
            ):
                return value, "CONST"
        macro = self._resolve_macro(value, file_name)
        if macro is not None:
            visible_enum_values, _ = self._visible_enum_index(file_name)
            return macro[0], "CONST" if value in visible_enum_values else "MACRO"
        return None

    def _constant_resolver(self, file_name: str) -> Callable[[str], Any | None]:
        def resolve(name: str) -> Any | None:
            direct = self._constant_from_text(name, file_name)
            if direct is None:
                return None
            value, _ = direct
            parsed = self._parse_c_integer_literal(value)
            return parsed if parsed is not None else value

        return resolve

    def _settle_transfer_arm(self, arm: RouteArm, site: IndexedSite) -> RouteArm:
        """Settle only deterministic leaves; never interpret local C syntax."""
        bindings: list[Binding] = []
        for binding in arm.bindings:
            if binding.kind != "EXPRESSION":
                bindings.append(binding)
                continue
            direct = self._constant_from_text(binding.text, site.file_name)
            if direct is not None:
                value, origin_kind = direct
                bindings.append(Binding(binding.target_arg, "EXACT", value))
                source = dict(arm.source_by_arg.get(binding.target_arg) or {})
                source["origin_kind"] = origin_kind
                macro = self._resolve_macro(
                    strip_outer_parens(binding.text.strip()), site.file_name
                )
                if macro is not None and origin_kind in {"MACRO", "CONST"}:
                    source.update(
                        {
                            "file": macro[1] or source.get("file") or site.file_path,
                            "line": macro[2] if macro[2] > 0 else source.get("line", site.line),
                            "expr": strip_outer_parens(binding.text.strip()),
                            "source_site_id": f"{macro[1]}:{macro[2]}:{binding.text.strip()}",
                        }
                    )
                else:
                    for evidence in arm.evidence:
                        evidence_source = self.trees.get(evidence.file, (None, b""))[1]
                        snippet = evidence_source[evidence.start_byte:evidence.end_byte].decode(
                            "latin-1", errors="replace"
                        )
                        if value in snippet:
                            source.update(
                                {
                                    "file": self.project_structure.get(evidence.file, evidence.file),
                                    "line": evidence_source[:evidence.start_byte].count(b"\n") + 1,
                                    "expr": value,
                                    "source_site_id": f"{evidence.file}:{evidence.start_byte}:{evidence.end_byte}",
                                }
                            )
                            break
                arm.source_by_arg[binding.target_arg] = source
                continue
            try:
                ok, value = evaluate_formula(
                    binding.text,
                    resolve_constant=self._constant_resolver(site.file_name),
                )
            except (FormulaError, ValueError, TypeError):
                ok, value = False, None
            if ok and (isinstance(value, (int, str)) and not isinstance(value, bool)):
                bindings.append(Binding(binding.target_arg, "EXACT", str(value)))
                source = dict(arm.source_by_arg.get(binding.target_arg) or {})
                source.setdefault("origin_kind", "CONST")
                arm.source_by_arg[binding.target_arg] = source
            else:
                bindings.append(binding)
        arm.bindings = bindings
        return arm

    @staticmethod
    def _terminal(binding: Binding) -> bool:
        return binding.kind in {"EXACT", "EXTERNAL", "UNKNOWN"}

    def _function_slice(self, function: FunctionInfo) -> tuple[str, int]:
        """Return (source text, file offset) for one function.

        FunctionInfo.source is the whole file, because reaching-definition
        analysis indexes it with absolute Tree-sitter offsets. The model needs
        only the function, so slice here rather than shipping the file.
        """
        cached = self._function_slice_cache.get(function.function_id)
        if cached is not None:
            return cached
        node = function.ast_node
        if node is None:
            # No AST node: fall back to today's behaviour rather than send
            # nothing. See the _build_function_index warning (Fix 0.3).
            result = function.source.decode("latin-1", errors="replace"), 0
        else:
            result = (
                function.source[node.start_byte:node.end_byte].decode(
                    "latin-1", errors="replace"
                ),
                node.start_byte,
            )
        self._function_slice_cache[function.function_id] = result
        return result

    def _evidence_texts(self, evidence: list[EvidenceSpan]) -> tuple[str, ...]:
        texts: list[str] = []
        for span in evidence:
            file_name = self._resolve_project_file(span.file)
            if file_name is None:
                continue
            source = self.trees[file_name][1]
            texts.append(source[span.start_byte:span.end_byte].decode("latin-1", errors="replace"))
        return tuple(texts)

    def _resolve_project_file(self, value: str) -> str | None:
        candidate = str(value).replace("\\", "/")
        if candidate in self.trees:
            return candidate
        try:
            path = Path(candidate).resolve()
        except OSError:
            path = Path(candidate)
        for file_name, project_path in self._project_paths.items():
            if project_path == path:
                return file_name
        matches = [name for name in self.trees if Path(name).name == Path(candidate).name]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            return None
        # Several files share this basename. Prefer the longest matching path
        # suffix; a tie leaves the ambiguity unresolved.
        parts = tuple(Path(candidate).parts)
        best, best_score = None, 0
        for name in matches:
            other = tuple(Path(name).parts)
            score = 0
            while (
                score < min(len(parts), len(other))
                and parts[-1 - score] == other[-1 - score]
            ):
                score += 1
            if score > best_score:
                best, best_score = name, score
            elif score == best_score:
                best = None
        return best

    def _repair_span(self, evidence, source: bytes, fn_start: int, fn_end: int, *, same_file: bool) -> tuple[int, int] | None:
        """Return a usable (start, end) byte span, or None.

        Models reliably get byte arithmetic wrong. The common failures are a
        degenerate span (start == end), an inverted span, and offsets given
        relative to the function body rather than the file. Each is repairable
        from source, so none of them should cost a whole answer.
        """
        limit = len(source)
        start = max(0, min(int(evidence.start_byte), limit))
        end = max(0, min(int(evidence.end_byte), limit))

        # 1. An exact snippet beats any offset the model computed.
        snippet = (evidence.snippet or "").strip()
        if snippet:
            raw = snippet.encode("latin-1", errors="replace")
            found = source.find(raw, fn_start, fn_end) if same_file and fn_end else -1
            if found < 0:
                found = source.find(raw)
            if found >= 0:
                return found, found + len(raw)

        # 2. Offsets given relative to the function body.
        if same_file and fn_end and end > start and end <= (fn_end - fn_start):
            shifted_start, shifted_end = fn_start + start, fn_start + end
            if shifted_end <= fn_end:
                return shifted_start, shifted_end

        # 3. A well-formed absolute span.
        if end > start:
            return start, end

        # 4. Degenerate or inverted: widen to the line containing the anchor.
        #    This is the reported start_byte == end_byte case.  Offsets of 0/0
        #    carry no anchor at all -- the prompt tells the model to send that
        #    when it is unsure -- so do not invent a span at the top of the
        #    file, whose text belongs to some unrelated function and would then
        #    count as evidence for the literal-coverage check.
        if not start and not end:
            return None
        anchor = start if start else end
        if not (0 <= anchor < limit):
            return None
        line_start = source.rfind(b"\n", 0, anchor) + 1
        line_end = source.find(b"\n", anchor)
        line_end = limit if line_end < 0 else line_end
        return (line_start, line_end) if line_end > line_start else None

    def _validate_transfer_answer(
        self,
        raw_answer: Any,
        *,
        request: TransferRequest,
        current_function: FunctionInfo,
        pending: tuple[int, ...],
    ) -> list[tuple[Any, list[EvidenceSpan]]] | None:
        try:
            if isinstance(raw_answer, tuple):
                raw_answer = raw_answer[0]
            answer = (
                raw_answer
                if isinstance(raw_answer, TransferAnswerModel)
                else TransferAnswerModel.model_validate(raw_answer)
            )
        except (TypeError, ValueError):
            self.transfer_rejections["schema_invalid"] += 1
            return None
        valid: list[tuple[TransferAnswerModel, list[EvidenceSpan]]] = []
        pending_set = set(pending)
        for model_arm in answer.arms:
            bindings = model_arm.bindings
            indices = [item.target_arg for item in bindings]
            if len(indices) != len(set(indices)) or not set(indices) <= pending_set:
                self.transfer_rejections["pending_mismatch"] += 1
                continue
            if not indices:
                continue
            spans: list[EvidenceSpan] = []
            current_span = False
            function_node = current_function.ast_node
            fn_start = function_node.start_byte if function_node is not None else 0
            fn_end = function_node.end_byte if function_node is not None else 0
            for evidence in model_arm.evidence:
                file_name = self._resolve_project_file(evidence.file)
                if file_name is None:
                    self.transfer_rejections["file_unresolved"] += 1
                    continue
                source = self.trees[file_name][1]
                span = self._repair_span(
                    evidence,
                    source,
                    fn_start,
                    fn_end,
                    same_file=file_name == current_function.node.file_name,
                )
                if span is None:
                    self.transfer_rejections["span_unrepairable"] += 1
                    continue
                start, end = span
                spans.append(EvidenceSpan(file_name, start, end))
                if (
                    file_name == current_function.node.file_name
                    and function_node is not None
                    and start < fn_end
                    and end > fn_start
                ):
                    current_span = True
            if not spans or not current_span:
                self.transfer_rejections["no_current_span"] += 1
                continue
            evidence_texts = self._evidence_texts(spans)
            visible = self._transfer_visible_names(
                current_function.node.file_name
            ) | {"NULL", "nullptr"}
            guard = model_arm.guard
            try:
                validate_formula(
                    guard,
                    parameter_count=len(current_function.parameters),
                    visible_names=visible,
                    evidence_texts=evidence_texts,
                    allow_boolean_literals=True,
                )
            except (FormulaError, ValueError, TypeError):
                # A guard only ever narrows an answer. If it cannot be
                # expressed in the formula grammar, drop the guard and keep
                # the bindings rather than discarding a correct transfer.
                self.transfer_rejections["guard_formula"] += 1
                guard = "true"
            try:
                for binding in bindings:
                    if binding.kind == "EXPRESSION":
                        validate_formula(
                            binding.expression,
                            parameter_count=len(current_function.parameters),
                            visible_names=visible,
                            evidence_texts=evidence_texts,
                            allow_opaque=self.allow_opaque_formula,
                        )
                    elif binding.kind == "EXTERNAL":
                        # EXTERNAL is a source expression, never a disguised
                        # numeric answer. A literal here would bypass the
                        # formula/evidence checks and leak an ungrounded model
                        # number into facts.
                        if self._literal(strip_outer_parens(binding.expression.strip())):
                            raise FormulaError(
                                "external binding cannot be a literal"
                            )
                        if any(
                            index > len(current_function.parameters)
                            for index in placeholder_indices(binding.expression)
                        ):
                            raise FormulaError("invalid external parameter placeholder")
            except (FormulaError, ValueError, TypeError):
                self.transfer_rejections["binding_formula"] += 1
                continue
            if guard != model_arm.guard:
                model_arm = model_arm.model_copy(update={"guard": guard})
            valid.append((model_arm, spans))
        return valid or None

    async def request_local_transfer(
        self,
        *,
        route: RouteGuide,
        current_function: FunctionInfo,
        selected_site: IndexedSite,
        arm: RouteArm,
    ) -> list[RouteArm] | None:
        pending = tuple(
            binding.target_arg for binding in arm.bindings if binding.kind == "EXPRESSION"
        )
        if not pending:
            return [arm]
        request_bindings = tuple(
            binding for binding in arm.bindings if binding.target_arg in pending
        )
        function_text, function_base = self._function_slice(current_function)
        # Derived only from the function text and its file, both immutable for
        # the run.  This is built before the cache lookup because it feeds the
        # cache key, so memoise it or every cache hit re-resolves 200 macros.
        constants = self._constants_cache.get(current_function.function_id)
        if constants is None:
            names = set(_IDENT_SCAN.findall(function_text)) & self._transfer_visible_names(
                current_function.node.file_name
            )
            constants = {}
            for name in sorted(names)[:200]:      # bounded: this goes in the prompt
                resolved = self._constant_from_text(name, current_function.node.file_name)
                if resolved is not None:
                    constants[name] = resolved[0]
            self._constants_cache[current_function.function_id] = constants
        macro_context = json.dumps(
            {
                "name": selected_site.macro_name,
                "unmapped": selected_site.macro_args_unmapped,
                "expanded_arguments": [item.text for item in selected_site.arguments],
                "source_arguments": [item.text for item in selected_site.target_arguments],
                "constants": constants,
            },
            sort_keys=True,
        )
        macro_digest = hashlib.sha256(macro_context.encode("utf-8")).hexdigest()
        key = make_transfer_cache_key(
            prompt_version=self.transfer_prompt_version,
            model_id=self.transfer_model_id,
            function_id=current_function.function_id,
            function_source=function_text,
            selected_site_id=selected_site.site_id,
            selected_site_source=selected_site.source[selected_site.start_byte:selected_site.end_byte],
            bindings=request_bindings,
            guards=tuple(arm.guards),
            macro_digest=macro_digest,
        )
        cached = self.transfer_cache.get(key)
        request: TransferRequest | None = None
        if cached is not None:
            self.transfer_cache_hits += 1
            raw_answer = cached.get("answer")
        else:
            self.transfer_cache_misses += 1
            if self.transfer_resolver is None:
                return None
            call_text = node_text(selected_site.ast_node, selected_site.source) if selected_site.ast_node is not None else selected_site.callee_name
            request = TransferRequest(
                route=route,
                function_id=current_function.function_id,
                function_name=current_function.node.name,
                function_file=current_function.node.file_name,
                function_source=function_text,
                function_start_byte=function_base,
                parameters=tuple(current_function.parameters),
                selected_site_id=selected_site.site_id,
                selected_call_text=call_text,
                selected_call_start_byte=(
                    selected_site.start_byte if selected_site.byte_range_known else -1
                ),
                selected_call_end_byte=(
                    selected_site.end_byte if selected_site.byte_range_known else -1
                ),
                bindings=request_bindings,
                guards=tuple(arm.guards),
                macro_context=macro_context,
            )
            self.transfer_request_count += 1
            raw_answer = await self._await_llm(self.transfer_resolver, request)
        if raw_answer is None:
            self.transfer_rejections["llm_returned_none"] += 1
            return None
        validated = self._validate_transfer_answer(
            raw_answer,
            request=request,
            current_function=current_function,
            pending=pending,
        )
        if not validated:
            self.transfer_rejections["all_arms_rejected"] += 1
            return None
        # Cache only a source-validated structured response.  Invalid model
        # output must not poison the next run or turn a later correction into
        # a cache hit.
        if cached is None:
            self.transfer_cache[key] = {
                "answer": {
                    "arms": [
                        {
                            "bindings": [item.model_dump() for item in model_arm.bindings],
                            "guard": model_arm.guard,
                            "evidence": [item.model_dump() for item in model_arm.evidence],
                        }
                        for model_arm, _spans in validated
                    ]
                },
                "version": self.transfer_prompt_version,
            }
        output: list[RouteArm] = []
        for ordinal, (model_arm, validated_spans) in enumerate(validated):
            # Each returned arm is correlated: all requested target arguments
            # are copied into the same child arm.
            child_id = hashlib.sha256(
                f"{arm.correlation_id}\0{key}\0{ordinal}".encode("utf-8")
            ).hexdigest()[:20]
            model_bindings = {
                item.target_arg: Binding(item.target_arg, item.kind, item.expression)
                for item in model_arm.bindings
            }
            # An arm may answer only some of the requested arguments.  An
            # unanswered one may be carried to the caller only when its text is
            # a formula over formal parameters, which _substitute_arm can still
            # rewrite.  A bare local name means nothing in the caller, and a
            # same-named local there would resolve it to the wrong value.
            child_bindings: list[Binding] = []
            for binding in arm.bindings:
                answered = model_bindings.get(binding.target_arg)
                if answered is not None:
                    child_bindings.append(answered)
                elif binding.target_arg not in pending or placeholder_indices(binding.text):
                    child_bindings.append(binding)
                else:
                    child_bindings.append(
                        Binding(binding.target_arg, "UNKNOWN", binding.text)
                    )
            child = RouteArm(
                route_id=arm.route_id,
                correlation_id=f"corr:{child_id}",
                bindings=child_bindings,
                guards=[*arm.guards, model_arm.guard]
                if model_arm.guard.strip().lower() != "true"
                else list(arm.guards),
                evidence=[*arm.evidence, *[
                    EvidenceSpan(item.file, item.start_byte, item.end_byte)
                    for item in validated_spans
                ]],
                transfer_chain=[
                    *arm.transfer_chain,
                    f"{current_function.function_id}:{selected_site.site_id} "
                    + ", ".join(
                        f"{item.target_arg}={item.expression}"
                        for item in model_arm.bindings
                    ),
                ],
                source_by_arg={key: dict(value) for key, value in arm.source_by_arg.items()},
            )
            for binding in model_arm.bindings:
                if binding.kind == "EXPRESSION":
                    source = next(
                        (
                            span for span in child.evidence
                            if span.file == current_function.node.file_name
                            and binding.expression.strip() in self.trees[span.file][1][span.start_byte:span.end_byte].decode("latin-1", errors="replace")
                        ),
                        None,
                    )
                    if source is not None:
                        child.source_by_arg[binding.target_arg] = {
                            "file": self.project_structure.get(source.file, source.file),
                            "line": self.trees[source.file][1][:source.start_byte].count(b"\n") + 1,
                            "expr": binding.expression,
                            "source_site_id": f"{source.file}:{source.start_byte}:{source.end_byte}",
                            "origin_kind": "CONST",
                        }
            output.append(child)
        return output

    def _evaluate_arm_guards(self, arm: RouteArm, file_name: str) -> RouteArm | None:
        remaining: list[str] = []
        resolver = self._constant_resolver(file_name)
        for guard in arm.guards:
            try:
                ok, value = evaluate_formula(guard, resolve_constant=resolver)
            except (FormulaError, ValueError, TypeError):
                ok, value = False, None
            if ok and isinstance(value, int):
                if value == 0:
                    return None
                continue
            remaining.append(guard)
        arm.guards = remaining
        return arm

    def _substitute_arm(self, arm: RouteArm, edge: CallerEdge) -> RouteArm | None:
        site = self.sites.get(edge.site_id)
        if site is None:
            return None
        indexes = {
            index
            for binding in arm.bindings
            if binding.kind == "EXPRESSION"
            for index in placeholder_indices(binding.text)
        }
        indexes.update(
            index
            for guard in arm.guards
            for index in placeholder_indices(guard)
        )
        if site.macro_args_unmapped and indexes:
            # Positions through this macro are untrustworthy, but only matters
            # if this arm actually reads an argument position.
            return None
        actuals: dict[int, str] = {}
        for index in indexes:
            expression = site.argument(index)
            if expression is None:
                return None
            actuals[index] = expression.text.strip()
        bindings: list[Binding] = []
        sources = {key: dict(value) for key, value in arm.source_by_arg.items()}
        for binding in arm.bindings:
            if binding.kind != "EXPRESSION":
                bindings.append(binding)
                continue
            substituted = substitute_placeholders(binding.text, actuals)
            bindings.append(Binding(binding.target_arg, binding.kind, substituted))
            if substituted != binding.text:
                first = next((site.argument(index) for index in indexes if site.argument(index) is not None), None)
                if first is not None:
                    sources[binding.target_arg] = self._expression_source(first)
        return RouteArm(
            route_id=arm.route_id,
            correlation_id=arm.correlation_id,
            bindings=bindings,
            guards=[substitute_placeholders(guard, actuals) for guard in arm.guards],
            evidence=list(arm.evidence),
            transfer_chain=list(arm.transfer_chain),
            source_by_arg=sources,
        )

    def _mark_external_or_unknown(
        self,
        arm: RouteArm,
        external: bool,
        parameter_names: tuple[str, ...] = (),
    ) -> RouteArm:
        def external_text(text: str) -> str:
            if not external:
                return text
            return strip_outer_parens(
                substitute_placeholders(
                    text,
                    {index: name for index, name in enumerate(parameter_names, start=1)},
                )
            )

        updated: list[Binding] = []
        for binding in arm.bindings:
            if binding.kind == "EXPRESSION":
                formal_name = strip_outer_parens(binding.text.strip())
                converted = Binding(
                    binding.target_arg,
                    "EXTERNAL"
                    if external
                    and (
                        placeholder_indices(binding.text)
                        or formal_name in parameter_names
                    )
                    else "UNKNOWN",
                    external_text(binding.text),
                )
                updated.append(converted)
                if converted.kind == "EXTERNAL":
                    arm.source_by_arg.setdefault(binding.target_arg, {})["origin_kind"] = "EXTERNAL_ENTRY"
            else:
                updated.append(binding)
        arm.bindings = updated
        return arm

    def _route_labels(self, route: RouteGuide, target_site: IndexedSite | None = None) -> list[str]:
        labels: list[str] = []
        root = self.registry.get(route.root_function_id)
        if root is not None:
            labels.append(root.label)
        for edge in route.edges:
            node = self.registry.get(edge.callee_id)
            if node is None:
                continue
            if edge.synthetic_callback:
                line = (edge.callback_meta or {}).get("registrar_line")
                labels.append(node.label_with_line(line=int(line) if line else None))
            else:
                site = self.sites.get(edge.site_id)
                labels.append(node.label_with_line(line=site.line if site else None))
        if target_site is not None:
            node = self.registry.get(target_site.callee_id) or target_site.raw_call_site.callee
            labels.append(node.label_with_line(line=target_site.line))
        return labels

    def _fact_from_transfer_binding(
        self,
        *,
        seed: Seed,
        route: RouteGuide,
        arm: RouteArm,
        binding: Binding,
        operation: str,
        link_method: str = "",
        target_site: IndexedSite | None = None,
    ) -> Fact:
        source = arm.source_by_arg.get(binding.target_arg) or {}
        if binding.kind == "EXACT":
            value = binding.text
            origin = str(source.get("origin_kind") or "CONST")
        elif binding.kind == "EXTERNAL":
            value = binding.text or "EXTERNAL"
            origin = str(source.get("origin_kind") or ("EXTERNAL_ENTRY" if "$" in value else "EXTERNAL_DATA"))
        else:
            sentinel = binding.text in {
                "RECURSIVE", "UNRESOLVED", "missing argument", "HANDLE_AMBIGUOUS",
            }
            if self.external_unknown and not sentinel and binding.text.strip():
                # An expression we could not trace further is still an
                # answer: the legacy engine reports it as EXTERNAL_DATA
                # rather than discarding it (P17).
                value = binding.text
                origin = "UNKNOWN_INDIRECT" if "(*" in binding.text else "EXTERNAL_DATA"
            else:
                value = "UNRESOLVED"
                origin = "RECURSIVE" if binding.text == "RECURSIVE" else "UNRESOLVED"
        metadata = {
            "route_id": route.route_id,
            "correlation_id": arm.correlation_id,
            "guards": list(arm.guards),
            "evidence": [
                {"file": item.file, "start_byte": item.start_byte, "end_byte": item.end_byte}
                for item in arm.evidence
            ],
            "transfer_chain": list(arm.transfer_chain),
            "reachability": route.reachability,
        }
        if binding.kind == "UNKNOWN" and binding.text not in {
            "RECURSIVE", "UNRESOLVED", "missing argument", "HANDLE_AMBIGUOUS",
        }:
            metadata["unresolved_expr"] = binding.text
        for edge in route.edges:
            if edge.synthetic_callback and edge.callback_meta:
                metadata.update(edge.callback_meta)
        source_file = str(source.get("file") or seed.site.file_path)
        source_line = int(source.get("line") or seed.site.line)
        source_expr = str(source.get("expr") or binding.text)
        return Fact(
            value=value,
            origin_kind=origin,
            source_file=source_file,
            source_line=source_line,
            source_expr=source_expr,
            origin_query=json.dumps(["TRANSFER", route.route_id, arm.correlation_id, binding.target_arg], separators=(",", ":")),
            source_site_id=str(source.get("source_site_id") or route.target_site_id),
            resolved_by="LLM" if arm.transfer_chain else "SYNTAX",
            link_method=link_method or ("LLM_TRANSFER" if arm.transfer_chain else ""),
            metadata=metadata,
        )

    def _resolved_transfer_seed(
        self,
        seed: Seed,
        route: RouteGuide,
        arm: RouteArm,
        indices: tuple[int, ...],
        operation: str,
        target_site: IndexedSite | None = None,
        link_method: str = "",
    ) -> list[ResolvedSeed]:
        labels = self._route_labels(route, target_site or seed.site)
        rows: list[ResolvedSeed] = []
        for index in indices:
            binding = next((item for item in arm.bindings if item.target_arg == index), None)
            if binding is None:
                continue
            fact = self._fact_from_transfer_binding(
                seed=seed,
                route=route,
                arm=arm,
                binding=binding,
                operation=operation,
                target_site=target_site,
                link_method=("LOCAL_BACKWALK" if seed.local_backwalk else link_method),
            )
            token = fact.origin_query
            self.query_labels[token] = " -> ".join(labels)
            rows.append(
                ResolvedSeed(
                    seed=seed,
                    arg_index=index,
                    fact=fact,
                    operation=operation,
                    call_number=None,
                    paths=[labels],
                    path_count=1,
                    query_token=token,
                    seconds=0.0,
                    legacy_labels=labels,
                    legacy_paths=[labels],
                )
            )
        return rows

    async def _walk_route_backward_transfers(
        self,
        *,
        seed: Seed,
        route: RouteGuide,
        start_site: IndexedSite,
        indices: tuple[int, ...],
        operation: str,
        output_target_site: IndexedSite | None = None,
        link_method: str = "",
    ) -> list[ResolvedSeed]:
        current_function = self.functions.get(start_site.caller_id)
        if current_function is None:
            return []
        arms = [self.initial_route_arm(route=route, site=start_site, indices=indices)]
        remaining_edges = list(reversed(route.edges))
        selected_site = start_site
        active: set[tuple[str, str, tuple[tuple[int, str, str], ...]]] = set()
        terminal: list[RouteArm] = []
        while arms:
            next_arms: list[RouteArm] = []
            for arm in arms:
                arm = self._settle_transfer_arm(arm, selected_site)
                guarded = self._evaluate_arm_guards(arm, selected_site.file_name)
                if guarded is None:
                    continue
                arm = guarded
                pending = tuple(item for item in arm.bindings if not self._terminal(item))
                if not pending:
                    # A constant branch value can still have a guard over the
                    # current function's parameters. Carry that guard through
                    # the selected caller edge before deciding whether the
                    # arm is feasible.
                    if arm.guards and any(
                        placeholder_indices(guard) for guard in arm.guards
                    ) and remaining_edges:
                        edge = remaining_edges[0]
                        if edge.synthetic_callback:
                            terminal.append(
                                self._mark_external_or_unknown(
                                    arm,
                                    external=True,
                                    parameter_names=tuple(current_function.parameters),
                                )
                            )
                        else:
                            substituted = self._substitute_arm(arm, edge)
                            if substituted is not None:
                                next_arms.append(substituted)
                            else:
                                terminal.append(arm)
                        continue
                    terminal.append(arm)
                    continue
                if (
                    not remaining_edges
                    and current_function.function_id == route.root_function_id
                    and all(
                        strip_outer_parens(item.text.strip())
                        in current_function.parameters
                        for item in pending
                    )
                ):
                    # A formal parameter of the selected entry point is an
                    # external entry value.  This is a structural boundary,
                    # not a semantic guess, so it needs no model request.
                    terminal.append(
                        self._mark_external_or_unknown(
                            arm,
                            external=True,
                            parameter_names=tuple(current_function.parameters),
                        )
                    )
                    continue
                state_key = (
                    current_function.function_id,
                    selected_site.site_id,
                    tuple((item.target_arg, item.kind, item.text) for item in pending),
                )
                if state_key in active:
                    arm.bindings = [
                        Binding(item.target_arg, "UNKNOWN", "RECURSIVE")
                        if item.kind == "EXPRESSION" else item
                        for item in arm.bindings
                    ]
                    terminal.append(arm)
                    continue
                active.add(state_key)
                transferred = await self.request_local_transfer(
                    route=route,
                    current_function=current_function,
                    selected_site=selected_site,
                    arm=arm,
                )
                if not transferred:
                    arm.bindings = [
                        Binding(item.target_arg, "UNKNOWN", "UNRESOLVED")
                        if item.kind == "EXPRESSION" else item
                        for item in arm.bindings
                    ]
                    terminal.append(arm)
                    active.discard(state_key)
                    continue
                for child in transferred:
                    child = self._settle_transfer_arm(child, selected_site)
                    child = self._evaluate_arm_guards(child, selected_site.file_name)
                    if child is None:
                        continue
                    if all(self._terminal(item) for item in child.bindings):
                        if child.guards and any(
                            placeholder_indices(guard) for guard in child.guards
                        ) and remaining_edges:
                            edge = remaining_edges[0]
                            if edge.synthetic_callback:
                                terminal.append(
                                    self._mark_external_or_unknown(
                                        child,
                                        external=True,
                                        parameter_names=tuple(current_function.parameters),
                                    )
                                )
                            else:
                                substituted = self._substitute_arm(child, edge)
                                if substituted is not None:
                                    next_arms.append(substituted)
                                else:
                                    terminal.append(child)
                        else:
                            terminal.append(child)
                        continue
                    if not remaining_edges:
                        terminal.append(
                            self._mark_external_or_unknown(
                                child,
                                external=True,
                                parameter_names=tuple(current_function.parameters),
                            )
                        )
                        continue
                    edge = remaining_edges[0]
                    if edge.synthetic_callback:
                        terminal.append(
                            self._mark_external_or_unknown(
                                child,
                                external=True,
                                parameter_names=tuple(current_function.parameters),
                            )
                        )
                        continue
                    substituted = self._substitute_arm(child, edge)
                    if substituted is None:
                        terminal.append(
                            self._mark_external_or_unknown(
                                child,
                                external=True,
                                parameter_names=tuple(current_function.parameters),
                            )
                        )
                        continue
                    next_arms.append(substituted)
                active.discard(state_key)
            if not next_arms:
                break
            edge = remaining_edges.pop(0)
            if edge.synthetic_callback:
                terminal.extend(
                    self._mark_external_or_unknown(
                        arm,
                        external=True,
                        parameter_names=tuple(current_function.parameters),
                    )
                    for arm in next_arms
                )
                break
            selected_site = self.sites.get(edge.site_id)  # type: ignore[assignment]
            current_function = self.functions.get(edge.caller_id)
            if selected_site is None or current_function is None:
                terminal.extend(self._mark_external_or_unknown(arm, external=False) for arm in next_arms)
                break
            arms = next_arms
        return [
            row
            for arm in terminal
            for row in self._resolved_transfer_seed(
                seed,
                route,
                arm,
                indices,
                operation,
                target_site=output_target_site,
                link_method=link_method,
            )
        ]

    def _opening_for_route(
        self, seed: Seed, route: RouteGuide, dependencies: tuple[str, ...]
    ) -> IndexedSite | None:
        argument_index = int(seed.config.get("handle_index") or 1)
        current_id = seed.site.caller_id
        before = seed.site.start_byte
        argument = (
            seed.site.target_argument(argument_index)
            if seed.site.is_configured_macro_target
            else seed.site.argument(argument_index)
        )
        root = normalise_handle(argument.text) if argument is not None else ""
        edge_index = len(route.edges) - 1
        while root:
            bindings = self._binding_opens(current_id, root, before, dependencies)
            if len(bindings) == 1:
                return bindings[0]
            function = self.functions.get(current_id)
            if function is None or root not in function.parameters or edge_index < 0:
                return None
            edge = route.edges[edge_index]
            if edge.synthetic_callback:
                return None
            site = self.sites.get(edge.site_id)
            if site is None:
                return None
            parameter_index = function.parameters.index(root) + 1
            actual = site.argument(parameter_index)
            if actual is None:
                return None
            root = normalise_handle(actual.text)
            current_id = edge.caller_id
            before = site.start_byte
            edge_index -= 1
        return None

    def _openings_for_route(
        self, seed: Seed, route: RouteGuide, dependencies: tuple[str, ...]
    ) -> list[IndexedSite]:
        """Every candidate open, where _opening_for_route requires exactly one.

        A handle written by two branches has two legitimate origins; the
        engine already represents alternatives as separate correlated arms
        (P13, flagged behind TRACER_VF_MULTI_OPEN).
        """
        argument_index = int(seed.config.get("handle_index") or 1)
        current_id = seed.site.caller_id
        before = seed.site.start_byte
        argument = (
            seed.site.target_argument(argument_index)
            if seed.site.is_configured_macro_target
            else seed.site.argument(argument_index)
        )
        root = normalise_handle(argument.text) if argument is not None else ""
        edge_index = len(route.edges) - 1
        while root:
            bindings = self._binding_opens(current_id, root, before, dependencies)
            if bindings:
                return bindings
            function = self.functions.get(current_id)
            if function is None or root not in function.parameters or edge_index < 0:
                return []
            edge = route.edges[edge_index]
            if edge.synthetic_callback:
                return []
            site = self.sites.get(edge.site_id)
            if site is None:
                return []
            parameter_index = function.parameters.index(root) + 1
            actual = site.argument(parameter_index)
            if actual is None:
                return []
            root = normalise_handle(actual.text)
            current_id = edge.caller_id
            before = site.start_byte
            edge_index -= 1
        return []

    def effective_value_sites_for_seed(self, seed: Seed) -> list[EffectiveValueSite]:
        """Return source call sites for configured values, never resolved values."""
        dependencies = tuple(
            name for name in seed.config.get("dependent_functions", [])
            if name in self.function_configs and name != seed.target_function
        )
        if not dependencies:
            return [
                EffectiveValueSite(
                    site_id=seed.site.site_id,
                    value_indices=tuple(int(item) for item in seed.config.get("indices") or ()),
                    link_method="",
                )
            ]
        selected: dict[str, EffectiveValueSite] = {}
        for route in self.routes_for_seed(seed):
            opening = self._opening_for_route(seed, route, dependencies)
            if opening is None:
                continue
            config = self.function_configs.get(opening.callee_name, {})
            indices = tuple(int(item) for item in config.get("indices") or ())
            if indices:
                selected[opening.site_id] = EffectiveValueSite(
                    site_id=opening.site_id,
                    value_indices=indices,
                    link_method="VARTRACE",
                )
        return [selected[key] for key in sorted(selected)]

    def _route_for_opening(
        self, consumer_route: RouteGuide, opening: IndexedSite
    ) -> RouteGuide | None:
        """Trim a consumer route at the owning open while retaining its identity."""
        if opening.caller_id == consumer_route.root_function_id:
            prefix: tuple[CallerEdge, ...] = ()
        else:
            endpoint = next(
                (
                    index + 1
                    for index, edge in enumerate(consumer_route.edges)
                    if edge.callee_id == opening.caller_id
                ),
                None,
            )
            if endpoint is None:
                return None
            prefix = consumer_route.edges[:endpoint]
        parts = [
            consumer_route.root_function_id,
            *(edge.site_id for edge in prefix),
            opening.site_id,
        ]
        digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:20]
        return RouteGuide(
            route_id=f"route:{digest}",
            root_function_id=consumer_route.root_function_id,
            edges=prefix,
            target_site_id=opening.site_id,
            reachability=(
                "CALLBACK" if any(edge.synthetic_callback for edge in prefix) else consumer_route.reachability
            ),
        )

    async def _resolve_seed_with_transfers(self, seed: Seed) -> list[ResolvedSeed]:
        operation = seed.config.get("type") or "NO DATA"
        if operation == "WRITEF/READF":
            operation_facts = await self.resolve(ReturnUseQuery(seed.site.site_id))
            operation = operation_facts[0].value if operation_facts else "UNRESOLVED"
        dependencies = tuple(
            name for name in seed.config.get("dependent_functions", [])
            if name in self.function_configs and name != seed.target_function
        )
        configured_indices = tuple(int(item) for item in seed.config.get("indices") or ())
        if not dependencies and not configured_indices:
            rows: list[ResolvedSeed] = []
            for route in self.routes_for_seed(seed):
                labels = self._route_labels(route, seed.site)
                metadata = {
                    "route_id": route.route_id,
                    "correlation_id": f"corr:{route.route_id[6:]}",
                    "reachability": route.reachability,
                }
                fact = Fact(
                    value="NO TARGET",
                    origin_kind="CONST",
                    source_file=seed.site.file_path,
                    source_line=seed.site.line,
                    source_expr=seed.target_function,
                    origin_query=json.dumps(["TRANSFER", route.route_id, "NO_TARGET"]),
                    source_site_id=seed.site.site_id,
                    metadata=metadata,
                )
                rows.append(
                    ResolvedSeed(
                        seed=seed,
                        arg_index=0,
                        fact=fact,
                        operation=operation,
                        call_number=None,
                        paths=[labels],
                        path_count=1,
                        legacy_labels=labels,
                        legacy_paths=[labels],
                        query_token=fact.origin_query,
                    )
                )
            return rows
        effective: list[
            tuple[IndexedSite, tuple[int, ...], str, IndexedSite | None, RouteGuide]
        ] = []
        if dependencies:
            for consumer_route in self.routes_for_seed(seed):
                openings = (
                    self._openings_for_route(seed, consumer_route, dependencies)
                    if self.multi_open
                    else (
                        [self._opening_for_route(seed, consumer_route, dependencies)]
                    )
                )
                for opening in openings:
                    effective_route = (
                        self._route_for_opening(consumer_route, opening)
                        if opening is not None
                        else None
                    )
                    if opening is not None and effective_route is not None:
                        config = self.function_configs.get(opening.callee_name, {})
                        indices = tuple(int(item) for item in config.get("indices") or ())
                        if not indices:
                            continue
                        effective.append(
                            (
                                opening,
                                indices,
                                "VARTRACE",
                                seed.site,
                                effective_route,
                            )
                        )
        else:
            effective = [
                (seed.site, configured_indices, "", seed.site, route)
                for route in self.routes_for_seed(seed)
            ]
        if not effective and dependencies:
            routes = self.routes_for_seed(seed)
            rows: list[ResolvedSeed] = []
            for route in routes:
                index = int(seed.config.get("handle_index") or 1)
                arm = RouteArm(
                    route_id=route.route_id,
                    correlation_id=f"corr:{route.route_id[6:]}",
                    bindings=[Binding(index, "UNKNOWN", "HANDLE_AMBIGUOUS")],
                )
                rows.extend(self._resolved_transfer_seed(seed, route, arm, (index,), operation, target_site=seed.site))
            return rows
        rows = []
        for opening, indices, link_method, output_site, route in effective:
            rows.extend(
                await self._walk_route_backward_transfers(
                    seed=seed,
                    route=route,
                    start_site=opening,
                    indices=indices,
                    operation=operation,
                    output_target_site=output_site,
                    link_method=link_method,
                )
            )
        for row in rows:
            row.call_number = await self.call_number_for(seed.site.caller_id)
        return rows

    def _resolved_seed(
        self,
        seed: Seed,
        arg_index: int,
        fact: Fact,
        operation: str,
        call_number: str | None,
        query: Query,
    ) -> ResolvedSeed:
        paths, path_count, truncated = self.paths_for_fact(fact, query)
        token = query.token()
        legacy_paths = self.legacy_paths_for_fact(fact, token)
        chain = self.provenance_tokens(fact, token) or [token]
        return ResolvedSeed(
            seed=seed,
            arg_index=arg_index,
            fact=fact,
            operation=operation,
            call_number=call_number,
            paths=paths,
            path_count=path_count,
            paths_truncated=truncated,
            query_token=token,
            seconds=sum(
                self.timings.get(step, {}).get("seconds", 0.0) for step in chain
            ),
            legacy_labels=legacy_paths[0] if legacy_paths else [],
            legacy_paths=legacy_paths,
        )

    # ------------------------------------------------------------- provenance
    def _add_provenance(self, child: Query, parent: Query) -> None:
        # Store source -> target direction: child answers a question needed by
        # parent. Later this becomes the source-to-target path CSV/log output.
        self._label_query(child)
        self._label_query(parent)
        self.provenance[child.token()].add(parent.token())

    def _label_query(self, query: Query) -> None:
        token = query.token()
        if token in self.query_labels:
            return
        if isinstance(query, (ArgQuery, HandleQuery)):
            site = self.sites.get(query.call_site_id)
            kind = "handle" if isinstance(query, HandleQuery) else "arg"
            self.query_labels[token] = (
                f"[{site.file_name}:{site.line}]{self.registry.get(site.caller_id, FunctionNode(site.caller_id, '')).name}"
                f"->{site.callee_name} {kind} {query.arg_index}"
                if site
                else token
            )
        elif isinstance(query, ParamQuery):
            info = self.functions.get(query.function_id)
            name = (
                info.parameters[query.param_index - 1]
                if info and query.param_index <= len(info.parameters)
                else "?"
            )
            self.query_labels[token] = (
                f"{query.function_id}.param{query.param_index}({name})"
            )
        else:
            site = self.sites.get(query.call_site_id)
            self.query_labels[token] = (
                f"[{site.file_name}:{site.line}]{site.callee_name} return"
                if site
                else token
            )

    def paths_for_fact(
        self, fact: Fact, target: Query
    ) -> tuple[list[list[str]], int, bool]:
        token_paths, count, truncated = self._provenance_token_paths(
            fact, target.token()
        )
        return (
            [
                [self.query_labels.get(token, token) for token in path]
                for path in token_paths
            ],
            count,
            truncated,
        )

    def _provenance_token_paths(
        self, fact: Fact, destination: str
    ) -> tuple[list[list[str]], int, bool]:
        # Starting at the query that found the source fact, walk forward through
        # recorded dependencies until reaching the original target query.
        origin = fact.origin_query
        paths: list[list[str]] = []
        memo: dict[str, int] = {}

        def count_paths(current: str, visiting: frozenset[str]) -> int:
            if current == destination:
                return 1
            if current in memo:
                return memo[current]
            if current in visiting:
                return 0
            total = sum(
                count_paths(parent, visiting | {current})
                for parent in self.provenance.get(current, set())
            )
            memo[current] = total
            return total

        count = count_paths(origin, frozenset())

        def collect(current: str, path: list[str], seen: set[str]) -> None:
            if len(paths) >= self.path_cap:
                return
            if current == destination:
                paths.append(path)
                return
            for parent in sorted(self.provenance.get(current, set())):
                if parent in seen:
                    continue
                if count_paths(parent, frozenset()) == 0:
                    continue
                collect(parent, path + [parent], seen | {parent})
                if len(paths) >= self.path_cap:
                    break

        collect(origin, [origin], {origin})
        if count == 0:
            count = 1
            paths = [[destination]]
        return paths, count, count > len(paths)

    def provenance_tokens(self, fact: Fact, destination: str) -> list[str]:
        """Query tokens on one value-carrying chain, ordered source -> target."""

        def find(current: str, seen: frozenset[str]) -> list[str] | None:
            if current == destination:
                return [current]
            for parent in sorted(self.provenance.get(current, set())):
                if parent in seen:
                    continue
                suffix = find(parent, seen | {parent})
                if suffix:
                    return [current, *suffix]
            return None

        return find(fact.origin_query, frozenset({fact.origin_query})) or []

    def legacy_path_labels(self, fact: Fact, destination: str) -> list[str]:
        """Render one value chain using the call-graph label grammar.

        The value-flow query labels are their own grammar and the wiki/chat
        layer cannot parse them, so the legacy compatibility feed must carry
        ``[file:line]name`` labels produced by FunctionNode, exactly as the
        path enumerator did.
        """
        paths = self.legacy_paths_for_fact(fact, destination)
        return paths[0] if paths else []

    def legacy_paths_for_fact(self, fact: Fact, destination: str) -> list[list[str]]:
        """Render every materialized value-flow path as call-graph labels."""
        token_paths, _, _ = self._provenance_token_paths(fact, destination)
        return [self._legacy_labels_for_tokens(tokens) for tokens in token_paths]

    def _legacy_labels_for_tokens(self, tokens: Iterable[str]) -> list[str]:
        labels: list[str] = []
        for token in tokens:
            try:
                parts = json.loads(token)
            except (TypeError, ValueError):
                continue
            if parts[0] not in {"ARG", "HANDLE", "RETURN_USE"}:
                continue
            site = self.sites.get(parts[1])
            if site is None:
                continue
            caller = self.registry.get(site.caller_id)
            if caller is not None and not labels:
                labels.append(caller.label)
            callee = self.registry.get(site.callee_id) or site.raw_call_site.callee
            labels.append(callee.label_with_line(line=site.line))
        return labels

    def _provenance_functions(self, fact: Fact, target: Query) -> list[str]:
        """Return target-to-source functions on one value-carrying path."""
        tokens = self.provenance_tokens(fact, target.token())
        functions: list[str] = []
        for token in reversed(tokens):
            try:
                parts = json.loads(token)
            except (TypeError, ValueError):
                continue
            if parts[0] == "PARAM":
                function_id = parts[1]
            elif parts[0] in {"ARG", "HANDLE", "RETURN_USE"}:
                site = self.sites.get(parts[1])
                function_id = site.caller_id if site else None
            else:
                function_id = None
            if function_id and function_id not in functions:
                functions.append(function_id)
        return functions

    # --------------------------------------------------------------- constants
    def _build_include_lookup_indexes(self) -> None:
        """Build O(1) lookup tables used while resolving include edges.

        The old include resolver scanned every project file for every include
        spelling, which became quadratic on large projects with archived
        headers. These indexes preserve the old uniqueness rules while
        avoiding repeated full-tree scans.
        """
        by_key: dict[str, list[str]] = defaultdict(list)
        by_path: dict[Path, list[str]] = defaultdict(list)
        by_basename: dict[str, list[str]] = defaultdict(list)

        for file_name in self.trees:
            normalized = str(file_name).replace("\\", "/").lstrip("./")
            by_key[normalized].append(file_name)

            project_path = Path(
                self.project_structure.get(file_name, file_name)
            ).resolve()
            self._project_paths[file_name] = project_path
            by_path[project_path].append(file_name)
            by_basename[Path(str(file_name)).name].append(file_name)

        self._include_key_index = {
            key: tuple(names) for key, names in by_key.items()
        }
        self._include_path_index = {
            path: tuple(names) for path, names in by_path.items()
        }
        self._include_basename_index = {
            basename: tuple(names) for basename, names in by_basename.items()
        }

    def _build_include_graph(self) -> dict[str, tuple[str, ...]]:
        """Build a best-effort source-to-header include graph from the AST.

        The project map may contain both the current source tree and archived
        headers with the same basename.  Exact include-key/path matching keeps
        an include such as ``<Dyn/DynReEneFileDef.h>`` attached to the active
        ``Dyn/DynReEneFileDef.h`` entry instead of the unrelated archive.
        """
        items = list(self.trees.items())
        workers = min(4, max(1, len(items)))
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="valueflow-include"
        ) as executor:
            return dict(executor.map(self._build_include_graph_entry, items))

    def _collect_include_diagnostics(self) -> list[dict[str, str]]:
        diagnostics: list[dict[str, str]] = []
        for file_name, (tree, source) in sorted(self.trees.items()):
            for node in _walk(tree.root_node):
                if node.type != "preproc_include":
                    continue
                path_node = node.child_by_field_name("path")
                if path_node is None:
                    continue
                requested = node_text(path_node, source).strip().strip('<">')
                if requested and self._resolve_include(file_name, requested) is None:
                    diagnostics.append(
                        {
                            "file": file_name,
                            "line": str(node.start_point.row + 1),
                            "requested": requested,
                            "reason": "include_not_selected_or_not_found",
                        }
                    )
        return diagnostics

    def _build_include_graph_entry(
        self, item: tuple[str, tuple[Any, bytes]]
    ) -> tuple[str, tuple[str, ...]]:
        file_name, (tree, source) = item
        included: list[str] = []
        for node in _walk(tree.root_node):
            if node.type != "preproc_include":
                continue
            path_node = node.child_by_field_name("path")
            if path_node is None:
                continue
            raw = node_text(path_node, source).strip().strip('<">')
            target = self._resolve_include(file_name, raw)
            if target is not None and target not in included:
                included.append(target)
        return file_name, tuple(included)

    def _resolve_include(self, source_file: str, requested: str) -> str | None:
        requested = requested.replace("\\", "/").strip()
        if not requested:
            return None
        normalized = requested.lstrip("./")

        # The project map keys preserve include spellings in the normal case.
        exact = self._include_key_index.get(normalized, ())
        if len(exact) == 1:
            return exact[0]

        source_path = self._project_paths.get(
            source_file,
            Path(self.project_structure.get(source_file, source_file)).resolve(),
        )
        requested_path = (source_path.parent / requested).resolve()
        by_path = self._include_path_index.get(requested_path, ())
        if len(by_path) == 1:
            return by_path[0]

        # Makefile -I roots are the authoritative way to resolve angled
        # project includes when the project map key omitted its directory.
        for root in self.include_roots:
            include_path = (root / requested).resolve()
            by_root_path = self._include_path_index.get(include_path, ())
            if len(by_root_path) == 1:
                return by_root_path[0]

        # A basename fallback is safe only when the project has one such file.
        # If there are multiple copies, leaving the edge unresolved is safer
        # than importing the wrong header into the visibility set.
        by_basename = self._include_basename_index.get(Path(requested).name, ())
        return by_basename[0] if len(by_basename) == 1 else None

    def _visible_files(self, file_name: str) -> tuple[str, ...]:
        """Return a file and its transitive includes in deterministic order."""
        queue = deque([file_name])
        visited: set[str] = set()
        ordered: list[str] = []
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            ordered.append(current)
            queue.extend(self.include_graph.get(current, ()))
        return tuple(ordered)

    def _build_enum_index(
        self,
    ) -> tuple[dict[str, tuple[str, str, int]], set[str]]:
        """Index integer enum constants from the parsed source tree.

        ``extract_all_macros`` cannot see enum values, which previously sent
        names such as ``DynReSchSetTkFNO`` to the LLM.  Enum values are syntax
        facts, so evaluate the small integer-expression subset used by C enum
        declarations while the AST is already available.

        A name with conflicting definitions is deliberately omitted.  A
        wrong exact value is more harmful than an unresolved value.
        """
        candidates: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
        per_file_candidates: dict[
            str, dict[str, list[tuple[str, str, int]]]
        ] = defaultdict(lambda: defaultdict(list))
        items = sorted(self.trees.items())
        workers = min(4, max(1, len(items)))
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="valueflow-enum"
        ) as executor:
            file_results = executor.map(self._enum_candidates_for_file, items)
            for file_name, file_candidates in file_results:
                for name, entries in file_candidates.items():
                    candidates[name].extend(entries)
                    per_file_candidates[file_name][name].extend(entries)

        values: dict[str, tuple[str, str, int]] = {}
        ambiguities: set[str] = set()
        for name, entries in candidates.items():
            distinct_values = {entry[0] for entry in entries}
            if len(distinct_values) > 1:
                ambiguities.add(name)
                continue
            values[name] = sorted(entries, key=lambda entry: (entry[1], entry[2]))[0]
        self.enum_values_by_file: dict[str, dict[str, tuple[str, str, int]]] = {}
        self.enum_ambiguities_by_file: dict[str, set[str]] = {}
        for file_name, file_candidates in per_file_candidates.items():
            file_values: dict[str, tuple[str, str, int]] = {}
            file_ambiguities: set[str] = set()
            for name, entries in file_candidates.items():
                if len({entry[0] for entry in entries}) > 1:
                    file_ambiguities.add(name)
                else:
                    file_values[name] = sorted(
                        entries, key=lambda entry: (entry[1], entry[2])
                    )[0]
            self.enum_values_by_file[file_name] = file_values
            self.enum_ambiguities_by_file[file_name] = file_ambiguities
        return values, ambiguities

    def _enum_candidates_for_file(
        self, item: tuple[str, tuple[Any, bytes]]
    ) -> tuple[str, dict[str, list[tuple[str, str, int]]]]:
        file_name, (tree, source) = item
        file_path = self.project_structure.get(file_name, file_name)
        file_candidates: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
        known: dict[str, int] = {}
        for specifier in _walk(tree.root_node):
            if specifier.type != "enum_specifier":
                continue
            body = specifier.child_by_field_name("body")
            if body is None:
                continue
            previous: int | None = None
            for enumerator in body.named_children:
                if enumerator.type != "enumerator":
                    continue
                name_node = enumerator.child_by_field_name("name")
                if name_node is None:
                    continue
                name = node_text(name_node, source).strip()
                value_node = enumerator.child_by_field_name("value")
                if value_node is not None:
                    previous = self._evaluate_enum_expression(
                        value_node, source, known
                    )
                elif previous is not None:
                    previous += 1
                if previous is None:
                    continue
                known[name] = previous
                file_candidates[name].append(
                    (
                        str(previous),
                        str(file_path),
                        enumerator.start_point.row + 1,
                    )
                )
        return file_name, file_candidates

    def _visible_enum_index(
        self, file_name: str
    ) -> tuple[dict[str, tuple[str, str, int]], set[str]]:
        cached = self._visible_enum_cache.get(file_name)
        if cached is not None:
            return cached
        candidates: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
        ambiguities: set[str] = set()
        for visible_file in self._visible_files(file_name):
            ambiguities.update(
                self.enum_ambiguities_by_file.get(visible_file, set())
            )
            for name, entry in self.enum_values_by_file.get(visible_file, {}).items():
                candidates[name].append(entry)

        values: dict[str, tuple[str, str, int]] = {}
        for name, entries in candidates.items():
            if len({entry[0] for entry in entries}) > 1:
                ambiguities.add(name)
            else:
                values[name] = sorted(
                    entries, key=lambda entry: (entry[1], entry[2])
                )[0]
        result = values, ambiguities
        self._visible_enum_cache[file_name] = result
        return result

    def _evaluate_enum_expression(
        self, node: Any, source: bytes, known: dict[str, int]
    ) -> int | None:
        """Evaluate a conservative integer expression used by an enumerator."""
        node_type = node.type
        text = strip_outer_parens(node_text(node, source).strip())
        if node_type == "number_literal":
            return self._parse_c_integer_literal(text)
        if node_type == "identifier":
            return self._integer_symbol_value(text, known, set())
        if node_type == "parenthesized_expression":
            children = list(node.named_children)
            return (
                self._evaluate_enum_expression(children[0], source, known)
                if children
                else None
            )
        if node_type == "unary_expression":
            children = list(node.named_children)
            if not children:
                return None
            value = self._evaluate_enum_expression(children[-1], source, known)
            if value is None:
                return None
            operator = node.children[0].type if node.children else ""
            return {
                "+": lambda: value,
                "-": lambda: -value,
                "~": lambda: ~value,
                "!": lambda: int(not value),
            }.get(operator, lambda: None)()
        if node_type == "binary_expression":
            children = list(node.named_children)
            if len(children) != 2 or len(node.children) < 3:
                return None
            left = self._evaluate_enum_expression(children[0], source, known)
            right = self._evaluate_enum_expression(children[1], source, known)
            if left is None or right is None:
                return None
            operator = node.children[1].type
            try:
                if operator == "+":
                    return left + right
                if operator == "-":
                    return left - right
                if operator == "*":
                    return left * right
                if operator == "/":
                    return int(left / right) if right else None
                if operator == "%":
                    return left % right if right else None
                if operator == "<<":
                    return left << right
                if operator == ">>":
                    return left >> right
                if operator == "|":
                    return left | right
                if operator == "&":
                    return left & right
                if operator == "^":
                    return left ^ right
            except (ArithmeticError, ValueError):
                return None
        return None

    def _parse_c_integer_literal(self, value: str) -> int | None:
        value = strip_outer_parens(value.strip())
        value = re.sub(r"[uUlL]+$", "", value)
        if not value:
            return None
        try:
            if value.lower().startswith("0x"):
                return int(value, 16)
            if value.lower().startswith("0b"):
                return int(value, 2)
            if len(value) > 1 and value.startswith("0"):
                return int(value, 8)
            return int(value, 10)
        except ValueError:
            return None

    def _integer_symbol_value(
        self, name: str, known: dict[str, int], visited: set[str]
    ) -> int | None:
        if name in known:
            return known[name]
        if name in visited:
            return None
        visited.add(name)
        macro = self._all_macros().get(name)
        if macro is None:
            return None
        replacement = strip_outer_parens(macro[0].strip())
        literal = self._parse_c_integer_literal(replacement)
        if literal is not None:
            return literal
        if _IDENTIFIER.fullmatch(replacement):
            return self._integer_symbol_value(replacement, known, visited)
        return None

    # --------------------------------------------------------------- utilities
    def _literal(self, value: str) -> bool:
        value = strip_outer_parens(value.strip())
        return bool(
            _NUMBER.fullmatch(value)
            or _STRING_OR_CHAR.fullmatch(value)
            or value in {"NULL", "true", "false", "nullptr"}
        )

    def _all_macros(self, file_name: str | None = None) -> dict[str, tuple[str, str]]:
        """Return macros visible from one active include chain."""
        combined: dict[str, tuple[str, str]] = {}
        visible = set(self._visible_files(file_name)) if file_name else set(self.trees)
        visible_paths = {
            str(Path(self.project_structure.get(name, name)).resolve())
            for name in visible
        }
        for name, value in self.builder_macros.items():
            definition_path = str(Path(value[1]).resolve()) if value[1] else ""
            if not file_name or not definition_path or definition_path in visible_paths:
                combined[name] = (value[0], value[1])
        for visible_name in self._visible_files(file_name or self.main_file_name):
            macros = self.file_macros.get(visible_name, {})
            path = self.project_structure.get(visible_name, "")
            for name, value in macros.items():
                combined.setdefault(name, (value, path))
        return combined

    def _resolve_macro(
        self, name: str, file_name: str | None = None
    ) -> tuple[str, str, int] | None:
        if not _IDENTIFIER.fullmatch(name):
            return None
        visible_enum_values, visible_enum_ambiguities = self._visible_enum_index(
            file_name or self.main_file_name
        )
        if name in visible_enum_ambiguities:
            return None
        enum_value = visible_enum_values.get(name)
        if enum_value is not None:
            return enum_value
        macros = self._all_macros(file_name)
        current = name
        visited: set[str] = set()
        source_file = ""
        while current in macros and current not in visited:
            visited.add(current)
            replacement, source_file = macros[current]
            replacement = strip_outer_parens(replacement.strip())
            if self._literal(replacement):
                return replacement, source_file, self._macro_line(source_file, current)
            if not _IDENTIFIER.fullmatch(replacement):
                return None
            current = replacement
        return None

    def _macro_line(self, file_path: str, macro_name: str) -> int:
        try:
            for line_number, line in enumerate(
                Path(file_path).read_text(encoding="latin-1").splitlines(), start=1
            ):
                if re.match(rf"\s*#\s*define\s+{re.escape(macro_name)}\b", line):
                    return line_number
        except OSError:
            pass
        return -1

    def _parameter_fast_path_safe(
        self, function: FunctionInfo, name: str, before_byte: int
    ) -> bool:
        if function.ast_node is None:
            return False
        for node in _walk(function.ast_node):
            if node.start_byte >= before_byte:
                continue
            if node.type == "assignment_expression":
                left = node.child_by_field_name("left")
                if left is not None and re.search(
                    rf"\b{re.escape(name)}\b", node_text(left, function.source)
                ):
                    return False
            text = node_text(node, function.source)
            if node.type == "update_expression" and re.search(
                rf"\b{re.escape(name)}\b", text
            ):
                return False
            if node.type in {"pointer_expression", "unary_expression"} and re.fullmatch(
                rf"\s*&\s*{re.escape(name)}\s*", text
            ):
                return False
            # This analyzer is C-only: a bare identifier in an argument is
            # passed by value and cannot reassign the caller's parameter.
            # Address-taking (the mutating form) is rejected above.
        return True

    def _local_reaching_definitions(
        self, site: IndexedSite, name: str
    ) -> list[Expression]:
        function = self.functions.get(site.caller_id)
        if function is None or function.ast_node is None:
            return []
        candidates: list[tuple[int, Expression, Any]] = []
        for node in _walk(function.ast_node):
            if node.start_byte >= site.start_byte:
                continue
            if node.type == "assignment_expression":
                left = node.child_by_field_name("left")
                right = node.child_by_field_name("right")
                if (
                    left is not None
                    and right is not None
                    and node_text(left, function.source).strip() == name
                ):
                    candidates.append(
                        (node.start_byte, self._expression(right, site), node)
                    )
            elif node.type == "init_declarator":
                declarator = node.child_by_field_name("declarator")
                value = node.child_by_field_name("value")
                if (
                    value is not None
                    and _extract_declarator_identifier(declarator, function.source)
                    == name
                ):
                    candidates.append(
                        (node.start_byte, self._expression(value, site), node)
                    )
        if not candidates:
            return []
        candidates.sort(key=lambda item: item[0])
        latest = candidates[-1]
        controlling_if = self._ancestor(latest[2], "if_statement")
        if controlling_if is not None and controlling_if.end_byte <= site.start_byte:
            # An ``else if`` arm is itself an if_statement, so the latest
            # assignment's innermost if may be a link of a longer chain.  Walk
            # up through enclosing ifs whose arm contains the chain so every
            # live arm of if / else if / else contributes its values; a
            # missing else or an arm without an assignment keeps the old
            # conservative bail-out.
            chain_root = controlling_if
            current = chain_root
            while True:
                parent = current.parent
                # An ``else if`` link sits inside an else_clause wrapper;
                # the enclosing if is its parent.
                if parent is not None and parent.type == "else_clause":
                    parent = parent.parent
                if parent is None or parent.type != "if_statement":
                    break
                consequence = parent.child_by_field_name("consequence")
                alternative = parent.child_by_field_name("alternative")
                contained = (
                    (consequence is not None and self._contains(consequence, current))
                    or (alternative is not None and self._contains(alternative, current))
                )
                if not contained:
                    break
                chain_root = parent
                current = chain_root
            reaching = self._collect_branch_values(chain_root, candidates)
            return reaching if reaching else []
        return [latest[1]]

    def _contains(self, ancestor: Any, node: Any) -> bool:
        """True when ``ancestor`` is ``node`` itself or encloses it.

        Tree-sitter node wrappers are recreated on every access, so compare
        the stable node id, not object identity.
        """
        current = node
        while current is not None:
            if current.id == ancestor.id:
                return True
            current = current.parent
        return False

    def _collect_branch_values(
        self, arm: Any, candidates: list[tuple[int, Expression, Any]]
    ) -> list[Expression] | None:
        """Values the variable can hold after one if-chain arm executes.

        Returns ``None`` when the conservative behavior must bail out (no
        else, or an arm that does not assign the variable).  An arm that is
        itself an ``if_statement`` (an ``else if`` link) contributes both of
        its arms, recursively, in source order.
        """
        if arm is None:
            return None
        if arm.type == "else_clause":
            named = arm.named_children
            arm = named[0] if len(named) == 1 else None
            if arm is None:
                return None
        if arm.type == "if_statement":
            consequence = arm.child_by_field_name("consequence")
            alternative = arm.child_by_field_name("alternative")
            if consequence is None:
                return None
            values = self._collect_branch_values(consequence, candidates)
            if values is None:
                return None
            if alternative is None:
                # No else: the variable may keep an earlier value.
                return None
            alt_values = self._collect_branch_values(alternative, candidates)
            if alt_values is None:
                return None
            return values + alt_values
        direct = [
            (offset, expression)
            for offset, expression, node in candidates
            if offset >= arm.start_byte and node.end_byte <= arm.end_byte
        ]
        if not direct:
            return None
        return [max(direct, key=lambda item: item[0])[1]]

    def _expression(self, node: Any, site: IndexedSite) -> Expression:
        return Expression(
            text=node_text(node, site.source),
            node=node,
            file_name=site.file_name,
            file_path=site.file_path,
            line=node.start_point.row + 1,
        )

    def _ancestor(self, node: Any, node_type: str) -> Any | None:
        current = node.parent
        while current is not None:
            if current.type == node_type:
                return current
            current = current.parent
        return None

    def _source_fact(
        self, value: str, kind: str, expression: Expression, query: Query
    ) -> Fact:
        return Fact(
            value=value,
            origin_kind=kind,
            source_file=expression.file_path,
            source_line=expression.line,
            source_expr=expression.text.strip(),
            origin_query=query.token(),
            source_site_id=query.token(),
        )

    def _cycle_fact(self, query: Query) -> Fact:
        return Fact(
            value=self.query_labels.get(query.token(), query.token()),
            origin_kind="RECURSIVE",
            source_file="",
            source_line=-1,
            source_expr=self.query_labels.get(query.token(), query.token()),
            origin_query=query.token(),
            source_site_id=query.token(),
        )

    def _unresolved_fact(self, query: Query, expression: str) -> Fact:
        site = self.sites.get(getattr(query, "call_site_id", ""))
        return Fact(
            value=expression,
            origin_kind="UNRESOLVED",
            source_file=site.file_path if site else "",
            source_line=site.line if site else -1,
            source_expr=expression,
            origin_query=query.token(),
            source_site_id=query.token(),
        )

    def _deduplicate_facts(self, facts: list[Fact]) -> list[Fact]:
        unique: dict[tuple, Fact] = {}
        for fact in facts:
            key = fact.source_key + (fact.link_method, fact.resolved_by)
            unique.setdefault(key, fact)
        return list(unique.values())

    def _deduplicate_records(self, records: list[ResolvedSeed]) -> list[ResolvedSeed]:
        unique: dict[tuple, ResolvedSeed] = {}
        for record in records:
            key = (
                record.seed.site.site_id,
                record.arg_index,
                record.fact.source_key,
                record.operation,
                record.seed.launch_via,
                (record.fact.metadata or {}).get("correlation_id") or "__legacy__",
            )
            existing = unique.get(key)
            if existing is None:
                unique[key] = record
            else:
                known = {tuple(path) for path in existing.paths}
                existing.paths.extend(
                    path for path in record.paths if tuple(path) not in known
                )
                known_legacy = {tuple(path) for path in existing.legacy_paths}
                existing.legacy_paths.extend(
                    path
                    for path in record.legacy_paths
                    if tuple(path) not in known_legacy
                )
                existing.path_count += record.path_count
                existing.paths_truncated = (
                    existing.paths_truncated or record.paths_truncated
                )
        return list(unique.values())

    @staticmethod
    def fact_id(record: ResolvedSeed, process_name: str) -> str:
        raw = "\x1f".join(
            [
                process_name,
                record.seed.target_function,
                record.seed.site.site_id,
                str(record.arg_index),
                *map(str, record.fact.source_key),
                str((record.fact.metadata or {}).get("correlation_id") or "__legacy__"),
            ]
        )
        return (
            "fact:"
            + hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:20]
        )
