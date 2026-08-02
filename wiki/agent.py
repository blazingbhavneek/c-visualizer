"""Lead + subagent research over the call graph.

Shape, following `llm-wiki-dist`'s researcher: a **lead** that plans and never
reads source (`search` / `explore` / `finish`), and **subagents** that each
start from one function, actually read code, follow the graph, and report back.
Subagents run concurrently, one per region, so a question spanning several
processes is explored in parallel rather than in one long chain.

Two things are load-bearing and worth stating plainly.

**Handles.**  A model never sees a raw node id.  Ids here look like
`function:a6b3c1ae83c09ec1`, and models reliably mangle them — dropping the
prefix, truncating the hash — which then fails to resolve and the agent
silently loses its evidence.  So every id handed out is a short handle (`F1`,
`R1`) mapped back server-side, and any handle that leaks into prose is either
rewritten into a citation link or stripped.

**Subagent tools are graph-native, not file-native.**  A generic wiki agent
gets `read` and `grep`.  Here a subagent gets `callers`, `callees`,
`call_path`, `resources` and `traces` — so its claims about control flow are
grounded in the recorded graph instead of reconstructed from source it has
only partly read.  This is the whole reason the answers can carry real,
clickable invocation paths.
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

from . import graphops as G
from .config import Settings
from .corpus import Corpus
from .index import RetrievalIndex
from .llm import ChatClient, tool
from .present import build_answer, function_link, path_link, resource_link

Emit = Callable[[dict[str, Any]], None]

HANDLE = re.compile(r"\b([FR])(\d{1,3})\b")


class Stopped(Exception):
    """Raised when the caller cancelled the run."""


class Handles:
    """Two-way map between short handles and real ids. Thread-safe."""

    def __init__(self) -> None:
        self._to_id: dict[str, str] = {}
        self._to_handle: dict[str, str] = {}
        self._counts: dict[str, int] = {"F": 0, "R": 0}
        self._lock = threading.Lock()

    def issue(self, kind: str, real_id: str) -> str:
        prefix = "F" if kind == "function" else "R"
        with self._lock:
            existing = self._to_handle.get(real_id)
            if existing:
                return existing
            self._counts[prefix] += 1
            handle = f"{prefix}{self._counts[prefix]}"
            self._to_handle[real_id] = handle
            self._to_id[handle] = real_id
            return handle

    def resolve(self, handle: Any) -> str | None:
        text = str(handle or "").strip().strip("`'\"[]()")
        with self._lock:
            if text in self._to_id:
                return self._to_id[text]
            # Models write `F3.`, `**F3**`, `f3` — recover the handle rather
            # than discarding a usable reference.
            match = HANDLE.search(text.upper())
            if match:
                return self._to_id.get(f"{match.group(1)}{match.group(2)}")
        return None

    def kind_of(self, handle: str) -> str:
        return "function" if str(handle).upper().startswith("F") else "resource"


@dataclass
class Run:
    """Accumulated state for one question."""

    question: str
    lang: str
    handles: Handles = field(default_factory=Handles)
    cited: list[str] = field(default_factory=list)
    paths: list[G.Path] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    subagent_reports: list[dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)


class Researcher:
    def __init__(
        self,
        corpus: Corpus,
        index: RetrievalIndex,
        chat: ChatClient,
        settings: Settings,
    ) -> None:
        self.corpus = corpus
        self.index = index
        self.chat = chat
        self.settings = settings

    # ------------------------------------------------------------- formatting

    def _describe(self, run: Run, hit) -> str:
        if hit.ref_kind == "function":
            function = self.corpus.function(hit.ref_id)
            if function is None:
                return ""
            handle = run.handles.issue("function", function.id)
            summary = (function.summary or function.signature() or "").strip().replace("\n", " ")
            return (
                f"{handle}  {function.name}  ({function.location}) "
                f"[{', '.join(function.processes)}]\n     {summary[:300]}"
            )
        resource = self.corpus.resource(hit.ref_id)
        if resource is None:
            return ""
        handle = run.handles.issue("resource", resource.key)
        return (
            f"{handle}  {resource.kind} {resource.name} "
            f"[{', '.join(resource.processes)}] — daemon resource"
        )

    def _search(self, run: Run, query: str, emit: Emit, phase: str, agent: int | None = None) -> str:
        emit({"type": "search", "phase": phase, "query": query, "agent": agent})
        hits = self.index.search(query, limit=self.settings.rerank_top_k)
        if not hits:
            return "No match. Try different words, or a function or resource name."

        lines = [self._describe(run, hit) for hit in hits]
        items = []
        for hit in hits:
            handle = run.handles.issue(
                hit.ref_kind, hit.ref_id
            )
            items.append(
                {
                    "handle": handle,
                    "name": hit.name,
                    "kind": hit.ref_kind,
                    "file": (
                        self.corpus.function(hit.ref_id).file_name
                        if hit.ref_kind == "function" and self.corpus.function(hit.ref_id)
                        else None
                    ),
                    "process": (
                        self.corpus.function(hit.ref_id).processes[0]
                        if hit.ref_kind == "function"
                        and self.corpus.function(hit.ref_id)
                        and self.corpus.function(hit.ref_id).processes
                        else None
                    ),
                }
            )
        emit({"type": "candidates", "items": items, "agent": agent})
        return "\n".join(line for line in lines if line)

    # ------------------------------------------------------------------ tools

    def _lead_tools(self) -> list[dict]:
        return [
            tool(
                "search",
                "Search the call graph for functions and daemon resources.",
                {"text": {"type": "string", "description": "Search query"}},
                ["text"],
            ),
            tool(
                "explore",
                "Dispatch subagents to read code around specific handles. "
                "Give each one the single step of the question its region should answer.",
                {
                    "handles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Handles from search, e.g. ['F1','F4']",
                    },
                    "questions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "One sub-question per handle, same order",
                    },
                },
                ["handles"],
            ),
            tool(
                "finish",
                "Give the final answer in Markdown, citing handles inline as [F1].",
                {
                    "answer": {"type": "string", "description": "Final answer in Markdown"},
                    "cited": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Handles supporting the answer",
                    },
                },
                ["answer"],
            ),
        ]

    def _sub_tools(self) -> list[dict]:
        handle_arg = {"handle": {"type": "string", "description": "A handle such as F3"}}
        return [
            tool("read", "Read a function's full source and summary.", handle_arg, ["handle"]),
            tool("callers", "List what calls this function, with line and edge kind.", handle_arg, ["handle"]),
            tool("callees", "List what this function calls.", handle_arg, ["handle"]),
            tool(
                "call_path",
                "Find the control-flow path between two functions.",
                {
                    "from_handle": {"type": "string"},
                    "to_handle": {"type": "string"},
                },
                ["from_handle", "to_handle"],
            ),
            tool("resources", "List the daemon resources a function touches.", handle_arg, ["handle"]),
            tool(
                "resource_users",
                "List the functions that write to or read from a daemon resource.",
                {"handle": {"type": "string", "description": "A resource handle such as R2"}},
                ["handle"],
            ),
            tool(
                "traces",
                "Recorded invocation paths that end at a daemon API name.",
                {"api": {"type": "string", "description": "API name, e.g. scf_hist_save"}},
                ["api"],
            ),
            tool("search", "Search for more functions or resources.", {"text": {"type": "string"}}, ["text"]),
            tool(
                "finish",
                "Report what this region says about the assigned question.",
                {
                    "answer": {"type": "string"},
                    "cited": {"type": "array", "items": {"type": "string"}},
                },
                ["answer"],
            ),
        ]

    def _run_tool(self, run: Run, name: str, args: dict, emit: Emit, agent: int) -> str:
        handles = run.handles

        def function_for(key: str = "handle"):
            real = handles.resolve(args.get(key))
            return self.corpus.function(real) if real else None

        if name == "read":
            function = function_for()
            if function is None:
                return "Unknown handle. Use one from search results."
            emit(
                {
                    "type": "read",
                    "agent": agent,
                    "handle": handles.issue("function", function.id),
                    "name": function.name,
                    "file": function.file_name,
                    "start_line": function.start_line,
                    "end_line": function.end_line,
                }
            )
            run.cited.append(function.id)
            body = function.source or "(no source recorded — external or library boundary)"
            return (
                f"{function.name} — {function.location} [{', '.join(function.processes)}]\n"
                f"summary: {function.summary or '(none)'}\n\n"
                f"{body[: self.settings.max_source_chars]}"
            )

        if name in {"callers", "callees"}:
            function = function_for()
            if function is None:
                return "Unknown handle."
            emit(
                {
                    "type": "follow_link",
                    "agent": agent,
                    "handle": handles.issue("function", function.id),
                    "name": function.name,
                    "direction": name,
                }
            )
            rows = (G.callers if name == "callers" else G.callees)(self.corpus, function.id)
            if not rows:
                return f"No {name} recorded for {function.name}."
            lines = []
            for row in rows[:40]:
                handle = handles.issue("function", row["id"])
                via = f" via {row['via']}" if row.get("via") else ""
                lines.append(
                    f"{handle}  {row['name']}  ({row['file_name']}:{row['line']}) "
                    f"[{row['process']}] {row['kind']}{via}"
                )
            return "\n".join(lines)

        if name == "call_path":
            source = function_for("from_handle")
            target = function_for("to_handle")
            if source is None or target is None:
                return "Unknown handle on one side."
            emit(
                {
                    "type": "follow_link",
                    "agent": agent,
                    "handle": handles.issue("function", target.id),
                    "name": f"{source.name} → {target.name}",
                    "direction": "path",
                }
            )
            paths = G.call_paths(self.corpus, source.id, target.id, max_paths=3)
            if not paths:
                return f"No recorded path from {source.name} to {target.name}."
            run.paths.extend(paths)
            return "\n".join(f"{path.label}  [{path.process}]" for path in paths)

        if name == "resources":
            function = function_for()
            if function is None:
                return "Unknown handle."
            emit(
                {
                    "type": "follow_link",
                    "agent": agent,
                    "handle": handles.issue("function", function.id),
                    "name": function.name,
                    "direction": "resources",
                }
            )
            touched = G.resources_for_function(self.corpus, function.id)
            if not touched:
                return f"{function.name} touches no recorded daemon resource."
            lines = []
            for item in touched:
                handle = handles.issue("resource", item["key"])
                run.resources.append(item["key"])
                lines.append(
                    f"{handle}  {item['key']}  {item['direction']}  "
                    f"{'/'.join(item['operations'])} via {', '.join(item['target_apis'])}"
                )
            return "\n".join(lines)

        if name == "resource_users":
            key = handles.resolve(args.get("handle"))
            view = G.functions_for_resource(self.corpus, key) if key else None
            if not view:
                return "Unknown resource handle."
            emit(
                {
                    "type": "follow_link",
                    "agent": agent,
                    "handle": str(args.get("handle")),
                    "name": view["key"],
                    "direction": "resource_users",
                }
            )
            run.resources.append(view["key"])
            lines = [f"{view['key']} — processes: {', '.join(view['processes'])}"]
            for label, rows in (("writes", view["producers"]), ("reads", view["consumers"])):
                for row in rows[:20]:
                    handle = handles.issue("function", row["id"])
                    lines.append(
                        f"  {label}: {handle}  {row['name']} [{row['process']}] "
                        f"{row['operation']} via {row['target_api']}"
                    )
            return "\n".join(lines)

        if name == "traces":
            api = str(args.get("api") or "").strip()
            paths = G.traces_as_paths(self.corpus, api, limit=6)
            if not paths:
                return f"No recorded trace ends at {api}."
            run.paths.extend(paths)
            emit({"type": "follow_link", "agent": agent, "name": api, "direction": "traces", "handle": ""})
            return "\n".join(f"[{path.process}] {path.label}" for path in paths)

        if name == "search":
            return self._search(run, str(args.get("text") or ""), emit, "sub", agent)

        return f"Unknown tool {name}."

    # ------------------------------------------------------------- subagents

    def _run_subagent(
        self,
        run: Run,
        start_handle: str,
        sub_question: str,
        index: int,
        emit: Emit,
        stop: threading.Event | None,
    ) -> dict[str, Any]:
        real_id = run.handles.resolve(start_handle)
        function = self.corpus.function(real_id) if real_id else None
        emit(
            {
                "type": "subagent_start",
                "agent": index,
                "node": {
                    "handle": start_handle,
                    "name": function.name if function else start_handle,
                    "file": function.file_name if function else None,
                    "process": function.processes[0] if function and function.processes else None,
                },
                "sub_question": sub_question,
            }
        )

        task = (
            f"Overall question (context only): {run.question}\n\nYour assigned part: {sub_question}"
            if sub_question
            else f"Question: {run.question}"
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You explore one region of a C call graph and report what it says.\n"
                    "Read your starting function first, then follow callers, callees, "
                    "resources or traces as needed. Base every claim on what the tools "
                    "return; never guess a call path.\n"
                    "Refer to functions by their handle (F1, F2) and resources by theirs "
                    "(R1). Call finish when you can answer, or to say this region does "
                    "not contain the answer."
                ),
            },
            {
                "role": "user",
                "content": f"{task}\n\nYour starting point: {start_handle}",
            },
        ]

        report = {"start": start_handle, "answer": "", "cited": []}
        tools = self._sub_tools()

        for step in range(self.settings.subagent_max_steps):
            if stop is not None and stop.is_set():
                raise Stopped()
            last = step == self.settings.subagent_max_steps - 1
            completion = self.chat.complete(
                messages,
                # On the final turn only `finish` is on the table.  Without
                # that the last turn is usually another read and everything
                # the subagent gathered is discarded unreported.  See
                # `_finish_only` for why this is done by withholding tools
                # rather than with `tool_choice`.
                tools=_finish_only(tools) if last else tools,
            )
            if completion.error:
                report["answer"] = f"(subagent failed: {completion.error})"
                break
            if not completion.tool_calls:
                report["answer"] = completion.content.strip()
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": completion.content or None,
                    "tool_calls": [
                        {
                            "id": call.id or f"call_{position}",
                            "type": "function",
                            "function": {"name": call.name, "arguments": _dumps(call.arguments)},
                        }
                        for position, call in enumerate(completion.tool_calls)
                    ],
                }
            )

            finished = False
            for position, call in enumerate(completion.tool_calls):
                if call.name == "finish":
                    report["answer"] = str(call.arguments.get("answer") or "").strip()
                    report["cited"] = [str(item) for item in call.arguments.get("cited") or []]
                    finished = True
                    result = "reported"
                else:
                    result = self._run_tool(run, call.name, call.arguments, emit, index)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id or f"call_{position}",
                        "content": result[:16000],
                    }
                )
            if finished:
                break

        for handle in report["cited"]:
            resolved = run.handles.resolve(handle)
            if resolved and self.corpus.function(resolved):
                run.cited.append(resolved)

        emit({"type": "subagent_done", "agent": index, "cited": report["cited"]})
        return report

    def _explore(self, run: Run, handles: list[str], questions: list[str], emit: Emit, stop) -> str:
        starts, seen = [], set()
        for handle in handles:
            real = run.handles.resolve(handle)
            if real and real not in seen and self.corpus.function(real):
                seen.add(real)
                starts.append(run.handles.issue("function", real))
            if len(starts) >= self.settings.subagent_count:
                break

        if not starts:
            return "No valid handle. Search first, then pass exact handles from the results."

        emit(
            {
                "type": "subagents_spawned",
                "starts": [
                    {
                        "handle": handle,
                        "name": (function := self.corpus.function(run.handles.resolve(handle))).name,
                        "file": function.file_name,
                        "process": function.processes[0] if function.processes else None,
                    }
                    for handle in starts
                ],
            }
        )

        assigned = list(questions or [])
        reports: list[dict | None] = [None] * len(starts)
        lock = threading.Lock()

        def safe_emit(event: dict) -> None:
            with lock:
                emit(event)

        workers = max(1, min(self.settings.subagent_concurrency, len(starts)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    self._run_subagent,
                    run,
                    handle,
                    assigned[position] if position < len(assigned) else "",
                    position + 1,
                    safe_emit,
                    stop,
                ): position
                for position, handle in enumerate(starts)
            }
            for future in as_completed(futures):
                position = futures[future]
                try:
                    reports[position] = future.result()
                except Stopped:
                    for pending in futures:
                        pending.cancel()
                    raise
                except Exception as exc:  # one bad region must not sink the run
                    reports[position] = {
                        "start": starts[position],
                        "answer": f"(subagent failed: {exc})",
                        "cited": [],
                    }

        blocks = ["Subagent reports:"]
        for position, report in enumerate(reports, start=1):
            if not report:
                continue
            run.subagent_reports.append(report)
            cited = ", ".join(report.get("cited") or []) or "(none)"
            blocks.append(
                f"\n### Subagent {position} — started at {report['start']}\n"
                f"{report['answer']}\nEvidence: {cited}"
            )
        return "\n".join(blocks)

    # ------------------------------------------------------------------- lead

    def ask(self, question: str, lang: str = "ja", emit: Emit | None = None, stop=None) -> dict:
        emit = emit or (lambda event: None)
        run = Run(question=question, lang=lang)

        if not self.chat.available:
            return build_answer(
                (
                    "チャットモデルが設定されていないため、この質問には回答できません。"
                    "構造的な質問（「X を呼ぶのは」「R に書き込むのは」など）は"
                    "モデルなしで回答できます。\n"
                    if lang.startswith("ja")
                    else "No chat model is configured, so this question cannot be researched. "
                    "Structural questions ('what calls X', 'who writes to R') are answered "
                    "without a model.\n"
                ),
                corpus=self.corpus,
            )

        seed = self._search(run, question, emit, "main")
        emit({"type": "route", "decision": "deep", "reason": "research question"})

        language = "日本語" if lang.startswith("ja") else "English"
        messages = [
            {
                "role": "system",
                "content": (
                    "You coordinate research over a C codebase's call graph. You do not "
                    "read source yourself — you search, dispatch subagents to regions, and "
                    "write the final answer from their reports.\n"
                    f"Answer in {language}, in Markdown. Cite evidence inline using the "
                    "handles, written as [F1] or [R2] — they are rewritten into links.\n"
                    "Give each subagent one step of the question, not the whole thing."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{question}\n\nInitial candidates:\n{seed}\n\n"
                    "Dispatch subagents with explore(), then finish()."
                ),
            },
        ]

        tools = self._lead_tools()
        answer_text = ""
        cited_handles: list[str] = []

        for step in range(self.settings.lead_max_steps):
            if stop is not None and stop.is_set():
                raise Stopped()
            last = step == self.settings.lead_max_steps - 1
            completion = self.chat.complete(
                messages,
                # A lead still searching on its last turn is cut off and every
                # subagent report is discarded, so the last turn offers only
                # `finish`.
                tools=_finish_only(tools) if last else tools,
            )
            if completion.error:
                answer_text = f"(research failed: {completion.error})"
                break
            if not completion.tool_calls:
                answer_text = completion.content.strip()
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": completion.content or None,
                    "tool_calls": [
                        {
                            "id": call.id or f"lead_{position}",
                            "type": "function",
                            "function": {"name": call.name, "arguments": _dumps(call.arguments)},
                        }
                        for position, call in enumerate(completion.tool_calls)
                    ],
                }
            )

            finished = False
            for position, call in enumerate(completion.tool_calls):
                if call.name == "finish":
                    answer_text = str(call.arguments.get("answer") or "").strip()
                    cited_handles = [str(item) for item in call.arguments.get("cited") or []]
                    finished = True
                    result = "done"
                elif call.name == "explore":
                    result = self._explore(
                        run,
                        [str(item) for item in call.arguments.get("handles") or []],
                        [str(item) for item in call.arguments.get("questions") or []],
                        emit,
                        stop,
                    )
                elif call.name == "search":
                    result = self._search(run, str(call.arguments.get("text") or ""), emit, "main")
                else:
                    result = f"Unknown tool {call.name}."
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id or f"lead_{position}",
                        "content": result[:24000],
                    }
                )
            if finished:
                break

        emit({"type": "compiling"})

        for handle in cited_handles:
            resolved = run.handles.resolve(handle)
            if resolved and self.corpus.function(resolved):
                run.cited.append(resolved)

        text = self._link_handles(run, answer_text)
        cited_ids = list(dict.fromkeys(run.cited))

        # Backfill the daemon resources every cited function touches.
        # A subagent only records a resource if it happened to call the
        # `resources` tool, so an answer could discuss `Q_ALARM_HI` and
        # `ARC_AUDIT` at length while the rail's resource section sat empty —
        # which is precisely the evidence this tool exists to surface.  The
        # attribution is already in the graph, so take it from there rather
        # than depending on the model to have asked.
        resource_keys = list(run.resources)
        for function_id in cited_ids:
            for item in G.resources_for_function(self.corpus, function_id):
                resource_keys.append(item["key"])

        # Same reasoning for invocation paths: a subagent records one only if
        # it happened to call `call_path` or `traces`, so a perfectly good
        # answer could arrive with an empty Paths section.  Showing how `main`
        # reaches the cited functions is the question users ask next anyway.
        paths = list(run.paths)
        if not paths:
            for function_id in cited_ids[:3]:
                paths.extend(G.paths_from_entry(self.corpus, function_id, max_paths=2))

        return build_answer(
            text,
            corpus=self.corpus,
            cited_ids=cited_ids,
            paths=_dedupe_paths(paths),
            resource_keys=list(dict.fromkeys(resource_keys)),
            stats={
                "elapsed_ms": int((time.time() - run.started_at) * 1000),
                "subagents": len(run.subagent_reports),
            },
        )

    def _link_handles(self, run: Run, text: str) -> str:
        """Rewrite `[F3]` into a citation link; strip anything unresolvable.

        A handle left in the prose is meaningless to a reader, so an unknown
        one is removed rather than shown.
        """

        def replace(match: re.Match) -> str:
            handle = f"{match.group(1)}{match.group(2)}"
            real = run.handles.resolve(handle)
            if not real:
                return ""
            function = self.corpus.function(real)
            if function is not None:
                run.cited.append(function.id)
                return function_link(function)
            resource = self.corpus.resource(real)
            if resource is not None:
                run.resources.append(resource.key)
                return resource_link(resource.key, f"{resource.kind} {resource.name}")
            return ""

        # `[F3]` first, then any bare `F3` the model wrote outside brackets.
        text = re.sub(r"\[([FR])(\d{1,3})\]", replace, text or "")
        return HANDLE.sub(replace, text)


def _finish_only(tools: list[dict]) -> list[dict]:
    """Restrict the offered tools to `finish`.

    The obvious way to force a tool is `tool_choice`, and it does not work
    here.  Measured against the configured server: a named
    `tool_choice={"type":"function","function":{"name":"finish"}}` was ignored
    and `search` was called anyway, and `tool_choice="required"` was worse —
    it produced a call to a `grep` tool that was never offered at all.
    Withholding every other tool is honoured, so that is the mechanism.

    (This is also why `_run_tool` answers unknown names with a message rather
    than raising: a model that invents `grep` will invent others.)
    """
    finish = [item for item in tools if item.get("function", {}).get("name") == "finish"]
    return finish or tools


def _dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}"


def _dedupe_paths(paths: list[G.Path]) -> list[G.Path]:
    seen: set[str] = set()
    unique: list[G.Path] = []
    for path in paths:
        signature = f"{path.process}|{path.label}"
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(path)
    return unique[:8]
