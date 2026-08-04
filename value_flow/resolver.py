from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
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

_NUMBER = re.compile(
    r"^[+-]?(?:0[xX][0-9a-fA-F]+|0[bB][01]+|0[0-7]+|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)[uUlLfF]*$"
)
_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")
_STRING_OR_CHAR = re.compile(
    r"^(?:u8|u|U|L)?(?:\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])+')$", re.DOTALL
)


@dataclass(slots=True)
class Expression:
    text: str
    node: Any | None
    file_name: str
    file_path: str
    line: int


@dataclass(slots=True)
class FunctionInfo:
    function_id: str
    node: FunctionNode
    ast_node: Any | None
    source: bytes
    parameters: list[str]
    parameter_nodes: list[Any]


@dataclass(slots=True)
class IndexedSite:
    site_id: str
    caller_id: str
    callee_id: str
    callee_name: str
    file_name: str
    file_path: str
    line: int
    start_byte: int
    end_byte: int
    ast_node: Any | None
    source: bytes
    arguments: list[Expression]
    raw_call_site: CallSite
    macro_name: str | None = None
    # True when a macro boundary was crossed but argument positions could not
    # be mapped onto the expanded function. Reading a position here would be
    # off by however many arguments the macro injects, so it must not be done.
    macro_args_unmapped: bool = False

    def argument(self, index: int) -> Expression | None:
        if index < 1 or index > len(self.arguments):
            return None
        return self.arguments[index - 1]


@dataclass(frozen=True, slots=True)
class CallerEdge:
    caller_id: str
    callee_id: str
    site_id: str
    synthetic_callback: bool = False
    launch_via: str = ""
    call_function: str = ""


@dataclass(slots=True)
class Seed:
    site: IndexedSite
    target_function: str
    config: dict[str, Any]
    launch_via: str = "FORK"
    call_function: str = "main"
    function_source_file: str = ""
    function_source_line: str = "-1 (Main function)"


@dataclass(slots=True)
class ResolvedSeed:
    seed: Seed
    arg_index: int
    fact: Fact
    operation: str
    call_number: str | None
    paths: list[list[str]] = field(default_factory=list)
    path_count: int = 0
    paths_truncated: bool = False
    query_token: str = ""
    seconds: float = 0.0
    # Same chain in the call-graph label grammar, for the legacy feed only.
    legacy_labels: list[str] = field(default_factory=list)


OneHopResolver = Callable[
    [IndexedSite, int, str], OneHopAnswer | None | Awaitable[OneHopAnswer | None]
]
ReturnUseResolver = Callable[[IndexedSite, str], str | None | Awaitable[str | None]]
HandleFallbackResolver = Callable[
    [IndexedSite, int, tuple[str, ...]],
    list[OneHopAnswer] | None | Awaitable[list[OneHopAnswer] | None],
]


def _walk(node: Any | None) -> Iterable[Any]:
    if node is None:
        return
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _extract_declarator_identifier(node: Any | None, source: bytes) -> str | None:
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
    """Resolve configured target arguments by walking value-carrying edges backward."""

    def __init__(
        self,
        *,
        graph: dict[str, list[CallSite]],
        registry: dict[str, FunctionNode],
        trees: dict[str, tuple[Any, bytes]],
        project_structure: dict[str, str],
        main_file_name: str,
        function_configs: dict[str, dict[str, Any]],
        macros: dict[str, tuple[str, str, str]] | None = None,
        file_macros: dict[str, dict[str, str]] | None = None,
        one_hop_resolver: OneHopResolver | None = None,
        return_use_resolver: ReturnUseResolver | None = None,
        handle_llm_resolver: HandleFallbackResolver | None = None,
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
        self.main_file_name = main_file_name
        self.function_configs = function_configs
        self.builder_macros = macros or {}
        self.file_macros = file_macros or {}
        self.one_hop_resolver = one_hop_resolver
        self.return_use_resolver = return_use_resolver
        self.handle_llm_resolver = handle_llm_resolver
        self.cache_path = cache_path
        self.path_cap = max(1, path_cap)
        self.llm_concurrency = max(1, llm_concurrency)
        self.progress = progress

        self.functions: dict[str, FunctionInfo] = {}
        self.sites: dict[str, IndexedSite] = {}
        self.sites_by_caller: dict[str, list[IndexedSite]] = defaultdict(list)
        self.reverse_callers: dict[str, list[CallerEdge]] = defaultdict(list)
        self.forward_edges: dict[str, list[CallerEdge]] = defaultdict(list)
        self.reachable: set[str] = set()
        self.seeds: list[Seed] = []

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
        self._operation_cache: dict[str, str] = {}
        self._call_number_cache: dict[tuple[str, tuple[str, ...]], str | None] = {}
        fingerprint = hashlib.sha256()
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

        self._build_function_index()
        self._build_call_index()
        self._build_callback_edges()
        self._compute_reachability()
        self._enumerate_seeds()
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
            ast_node = None
            for candidate in definitions_by_file.get(function_node.file_name, []):
                name = _extract_declarator_identifier(
                    candidate.child_by_field_name("declarator"), source
                )
                if name == function_node.name:
                    ast_node = candidate
                    break
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
                return [], True
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
                start_byte = (
                    call_site.start_byte
                    if call_site.start_byte >= 0
                    else (ast_node.start_byte if ast_node is not None else ordinal)
                )
                site_id = f"{caller.file_name}:{start_byte}"
                arguments = self._expressions_for_call(
                    ast_node, source, caller.file_name, file_path
                )
                callee = call_site.callee
                callee_id = callee.unique_id
                callee_name = callee.name
                macro_name = None
                macro_args_unmapped = False
                if callee.macro_expansion is not None:
                    macro_name = callee.name
                    callee_id = callee.macro_expansion.unique_id
                    callee_name = callee.macro_expansion.name
                    arguments, reliable = self._macro_call_arguments(
                        macro_name,
                        callee_name,
                        arguments,
                        caller.file_name,
                        file_path,
                        call_site.line_number,
                    )
                    macro_args_unmapped = not reliable
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
                    raw_call_site=call_site,
                    macro_name=macro_name,
                    macro_args_unmapped=macro_args_unmapped,
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
            callbacks: dict[str, FunctionNode] = {}
            for callback in site.raw_call_site.callbacks:
                callbacks.setdefault(callback.unique_id, callback)
            config = self.function_configs.get(site.raw_call_site.callee.name, {})
            for callback_id, callback in callbacks.items():
                synthetic_id = f"{site.site_id}#callback:{callback_id}"
                edge = CallerEdge(
                    caller_id=site.caller_id,
                    callee_id=callback_id,
                    site_id=synthetic_id,
                    synthetic_callback=True,
                    launch_via=config.get("launch", "NO DATA"),
                    call_function=callback.name,
                )
                self.reverse_callers[callback_id].append(edge)
                self.forward_edges[site.caller_id].append(edge)

    def _compute_reachability(self) -> None:
        main_id = f"[{self.main_file_name}]main"
        if main_id not in self.registry:
            return
        queue = deque([main_id])
        self.reachable.add(main_id)
        while queue:
            current = queue.popleft()
            for edge in self.forward_edges.get(current, []):
                if edge.callee_id not in self.reachable:
                    self.reachable.add(edge.callee_id)
                    queue.append(edge.callee_id)

    def _launch_metadata(self, function_id: str) -> tuple[str, str, str, str]:
        if function_id in self._launch_cache:
            return self._launch_cache[function_id]
        metadata = self._launch_metadata_uncached(function_id)
        self._launch_cache[function_id] = metadata
        return metadata

    def _launch_metadata_uncached(self, function_id: str) -> tuple[str, str, str, str]:
        main_id = f"[{self.main_file_name}]main"
        if function_id == main_id:
            path = self.project_structure.get(self.main_file_name, "")
            return "FORK", "main", path, "-1 (Main function)"
        queue = deque(
            [
                (
                    main_id,
                    (
                        "FORK",
                        "main",
                        self.project_structure.get(self.main_file_name, ""),
                        "-1 (Main function)",
                    ),
                )
            ]
        )
        visited = {main_id}
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
        return (
            "FORK",
            "main",
            self.project_structure.get(self.main_file_name, ""),
            "-1 (Main function)",
        )

    def _enumerate_seeds(self) -> None:
        for site in sorted(self.sites.values(), key=lambda item: item.site_id):
            if site.caller_id not in self.reachable:
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
            if (
                payload.get("schema_version") != 2
                or payload.get("fingerprint") != self.cache_fingerprint
            ):
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
            "schema_version": 2,
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
        site = self.sites.get(query.call_site_id)
        if site is None:
            return [self._unresolved_fact(query, "missing call site")]
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
                    origin_kind="CONST",
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
        raw = expression.text.strip()
        value = strip_outer_parens(raw)
        if self._literal(value):
            return [self._source_fact(value, "CONST", expression, query)]

        macro = self._resolve_macro(value)
        if macro is not None:
            resolved, macro_file, macro_line = macro
            return [
                Fact(
                    value=resolved,
                    origin_kind="MACRO",
                    source_file=macro_file or expression.file_path,
                    source_line=macro_line or expression.line,
                    source_expr=value,
                    origin_query=query.token(),
                    source_site_id=f"{macro_file}:{macro_line}:{value}",
                )
            ]

        if _IDENTIFIER.fullmatch(value):
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
                        origin_kind="CONST",
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

    async def _resolve_parameter(
        self, query: ParamQuery, stack: frozenset[str]
    ) -> list[Fact]:
        info = self.functions.get(query.function_id)
        callers = [
            edge
            for edge in self.reverse_callers.get(query.function_id, [])
            if edge.caller_id in self.reachable and not edge.synthetic_callback
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
            facts.extend(await self.resolve(child, stack))
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
        for index, argument in enumerate(site.arguments, start=1):
            root = normalise_handle(argument.text)
            if not root:
                continue
            for opening in opens:
                if any(
                    normalise_handle(candidate.text) == root
                    for candidate in opening.arguments
                ):
                    matches.add(index)
        return sorted(matches)

    def handle_query_for_seed(self, seed: Seed) -> HandleQuery | None:
        dependencies = tuple(
            name
            for name in seed.config.get("dependent_functions", [])
            if name in self.function_configs and name != seed.target_function
        )
        if not dependencies:
            return None
        candidates = self._handle_candidates(seed.site, dependencies)
        # Index 0 deliberately represents an ambiguous handle.  Keeping it as
        # a query lets the LLM and legacy-proximity fallbacks run and ensures a
        # visible HANDLE_AMBIGUOUS fact if neither can recover.
        query = HandleQuery(
            seed.site.site_id, candidates[0] if len(candidates) == 1 else 0
        )
        self._handle_dependencies[query.token()] = dependencies
        return query

    async def _resolve_handle(
        self, query: HandleQuery, stack: frozenset[str]
    ) -> list[Fact]:
        site = self.sites.get(query.call_site_id)
        dependencies = self._handle_dependencies.get(query.token(), ())
        if site is None or not dependencies:
            return [self._unresolved_fact(query, "HANDLE_AMBIGUOUS")]
        argument = site.argument(query.arg_index)
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
                    child = ArgQuery(opening.site_id, int(index))
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
                if edge.synthetic_callback or edge.caller_id not in self.reachable:
                    continue
                child = HandleQuery(edge.site_id, parameter_index)
                self._handle_dependencies[child.token()] = dependencies
                self._add_provenance(child, query)
                facts.extend(await self.resolve(child, stack))
            if facts:
                return facts

        # A global or struct field may be opened in another reachable function.
        global_bindings: list[IndexedSite] = []
        is_local = bool(function and self._is_local_variable(function, root))
        if root and ("->" in root or "." in root or not is_local):
            for caller_id in self.reachable:
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
                    child = ArgQuery(opening.site_id, int(index))
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
                origin_kind="CONST",
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

        for opening in self._proximity_opens(site.caller_id, dependencies):
            for index in (
                self.function_configs.get(opening.callee_name, {}).get("indices") or []
            ):
                child = ArgQuery(opening.site_id, int(index))
                self._add_provenance(child, query)
                for fact in await self.resolve(child, stack):
                    facts.append(
                        Fact(**{**fact.to_dict(), "link_method": "LEGACY_PROXIMITY"})
                    )
        return facts or [self._unresolved_fact(query, "HANDLE_AMBIGUOUS")]

    def _proximity_opens(
        self, caller_id: str, dependencies: tuple[str, ...]
    ) -> list[IndexedSite]:
        """Nearest open-family calls in this function or its closest ancestor.

        This keeps the intent of the former subtree-proximity guess -- an open
        that merely sits near the consumer on the call tree -- but finds it by
        walking caller edges instead of materialising main-to-target paths.
        Reached only when handle variable tracing and the LLM both fail.
        """
        queue = deque([caller_id])
        visited = {caller_id}
        while queue:
            current = queue.popleft()
            opens = [
                site
                for site in self.sites_by_caller.get(current, [])
                if site.callee_name in dependencies
            ]
            if opens:
                return opens
            for edge in sorted(
                self.reverse_callers.get(current, []), key=lambda item: item.site_id
            ):
                if edge.caller_id in self.reachable and edge.caller_id not in visited:
                    visited.add(edge.caller_id)
                    queue.append(edge.caller_id)
        return []

    def _binding_opens(
        self, caller_id: str, root: str, before_byte: int, dependencies: tuple[str, ...]
    ) -> list[IndexedSite]:
        candidates = [
            site
            for site in self.sites_by_caller.get(caller_id, [])
            if site.callee_name in dependencies
            and site.start_byte < before_byte
            and any(
                normalise_handle(argument.text) == root for argument in site.arguments
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
                normalise_handle(argument.text) == root for argument in site.arguments
            )
        ]
        if close_sites:
            last_close = max(item.start_byte for item in close_sites)
            candidates = [item for item in candidates if item.start_byte > last_close]
        return candidates

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
        async def resolve_seed(seed: Seed) -> list[ResolvedSeed]:
            started = time.perf_counter()
            rows = await self._resolve_seed(seed)
            if self.progress is not None:
                self.progress(seed, rows, time.perf_counter() - started)
            return rows

        nested = await asyncio.gather(*(resolve_seed(seed) for seed in self.seeds))
        records = [record for group in nested for record in group]
        self.persist_cache()
        return self._deduplicate_records(records)

    async def _resolve_seed(self, seed: Seed) -> list[ResolvedSeed]:
        operation = seed.config.get("type") or "NO DATA"
        if operation == "WRITEF/READF":
            operation_facts = await self.resolve(ReturnUseQuery(seed.site.site_id))
            operation = operation_facts[0].value if operation_facts else "UNRESOLVED"
        handle_query = self.handle_query_for_seed(seed)
        queries: list[tuple[int, Query]] = []
        if handle_query is not None:
            dependencies = self._handle_dependencies[handle_query.token()]
            for dependency in dependencies:
                for index in (
                    self.function_configs.get(dependency, {}).get("indices") or []
                ):
                    queries.append((int(index), handle_query))
        else:
            queries.extend(
                (int(index), ArgQuery(seed.site.site_id, int(index)))
                for index in seed.config.get("indices") or []
            )
        if not queries:
            no_target_query = ArgQuery(seed.site.site_id, 0)
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
            legacy_labels=self.legacy_path_labels(fact, token),
        )

    # ------------------------------------------------------------- provenance
    def _add_provenance(self, child: Query, parent: Query) -> None:
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
        origin = fact.origin_query
        destination = target.token()
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
                paths.append([self.query_labels.get(token, token) for token in path])
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
            paths = [[self.query_labels.get(destination, destination)]]
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
        labels: list[str] = []
        for token in self.provenance_tokens(fact, destination) or [destination]:
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

    # --------------------------------------------------------------- utilities
    def _literal(self, value: str) -> bool:
        value = strip_outer_parens(value.strip())
        return bool(
            _NUMBER.fullmatch(value)
            or _STRING_OR_CHAR.fullmatch(value)
            or value in {"NULL", "true", "false", "nullptr"}
        )

    def _all_macros(self) -> dict[str, tuple[str, str]]:
        combined: dict[str, tuple[str, str]] = {}
        for name, value in self.builder_macros.items():
            combined[name] = (value[0], value[1])
        for file_name, macros in self.file_macros.items():
            path = self.project_structure.get(file_name, "")
            for name, value in macros.items():
                combined[name] = (value, path)
        return combined

    def _resolve_macro(self, name: str) -> tuple[str, str, int] | None:
        if not _IDENTIFIER.fullmatch(name):
            return None
        macros = self._all_macros()
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
            consequence = controlling_if.child_by_field_name("consequence")
            alternative = controlling_if.child_by_field_name("alternative")
            if consequence is None or alternative is None:
                # With no else, an earlier definition can still reach the use;
                # leave that CFG-sensitive case to the LLM.
                return []
            reaching: list[Expression] = []
            for branch in (consequence, alternative):
                in_branch = [
                    (offset, expression)
                    for offset, expression, node in candidates
                    if node.start_byte >= branch.start_byte
                    and node.end_byte <= branch.end_byte
                ]
                if not in_branch:
                    return []
                reaching.append(max(in_branch, key=lambda item: item[0])[1])
            return reaching
        return [latest[1]]

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
            )
            existing = unique.get(key)
            if existing is None:
                unique[key] = record
            else:
                known = {tuple(path) for path in existing.paths}
                existing.paths.extend(
                    path for path in record.paths if tuple(path) not in known
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
            ]
        )
        return (
            "fact:"
            + hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:20]
        )
