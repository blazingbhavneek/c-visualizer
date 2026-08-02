"""Answer structural questions by traversal, with no model in the loop.

A large share of what gets asked of a call-graph tool is not a research
question at all — it is a lookup: *what calls this*, *what does this call*,
*who writes to that queue*, *how does main reach here*.  The graph already
holds those answers exactly.  Sending them to a language model would be slower,
cost money, and introduce the one failure mode this tool cannot afford: a
confident, fluent, wrong call path.

So the router tries here first.  A hit returns in milliseconds with citations
and paths that are correct by construction; a miss falls through to the agent.
This also means the product stays useful with no LLM configured at all.

Intent detection is deliberately conservative.  Matching too eagerly would send
a genuine research question down a lookup path and answer it thinly, which is
worse than the round trip — so anything ambiguous returns None and lets the
agent handle it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from .corpus import Corpus, FunctionRef
from . import graphops as G
from .present import build_answer, function_link, path_link, resource_link

# Japanese and English cues for each intent.  Japanese first: it is the primary
# language of this UI, and the particle-marked forms ("を呼ぶ" / "から") are far
# more reliable cues than English word order.
CALLERS_CUES = (
    "を呼ぶ", "を呼び出す", "呼び出し元", "呼んでいる", "誰が呼", "どこから呼",
    "who calls", "what calls", "callers of", "called by", "call sites",
)
CALLEES_CUES = (
    "が呼ぶ", "を呼んでいる関数", "呼び出している関数", "何を呼",
    "what does", "callees of", "calls what", "which functions does",
)
WRITERS_CUES = (
    "に書き込", "へ書き込", "を書き込", "書き込むのは", "投入", "送信するのは",
    "who writes", "what writes", "writes to", "posts to", "produces",
)
READERS_CUES = (
    "を読み", "から読", "読み込むのは", "受信するのは", "購読",
    "who reads", "what reads", "reads from", "consumes", "subscribes",
)
REACH_CUES = ("どう到達", "どのように到達", "経路", "たどり着", "how does", "how do", "reach", "path from")
ENTRY_CUES = ("main から", "mainから", "エントリ", "起動から", "from main", "entry point")
DEFINE_CUES = ("とは", "の定義", "どこで定義", "何をする", "what is", "where is", "show me", "definition of")

IDENTIFIER = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b")

# Words that look like identifiers but never are, so a question phrased in
# English does not resolve its own verbs against the symbol table.
STOPWORDS = frozenset(
    {
        "the", "what", "which", "who", "does", "call", "calls", "called", "function",
        "functions", "where", "how", "from", "into", "this", "that", "reach", "reaches",
        "writes", "write", "reads", "read", "resource", "queue", "event", "file", "and",
        "for", "with", "show", "definition", "defined", "point", "entry", "main_file",
    }
)


@dataclass(slots=True)
class StructuralAnswer:
    payload: dict[str, Any]
    intent: str


def _cue(question: str, cues: tuple[str, ...]) -> bool:
    lowered = question.lower()
    return any(cue.lower() in lowered for cue in cues)


def _identifiers(corpus: Corpus, question: str) -> list[FunctionRef]:
    """Function names mentioned verbatim, in the order the question names them.

    Resolution is process-scoped, and that is not a nicety.  Six processes each
    define their own `main`, so "how does main reach bo_shed_load" resolves
    `main` to whichever snapshot sorts first — `proc_waterworks` — and then
    searches for a path to a `proc_boiler` function, finding none and reporting
    a confident "no path exists".  Scoped to the process implied by the more
    specific name, the same question finds two.

    So: resolve once to discover which process the question is about, then
    resolve everything again inside it.  The hint comes from the most specific
    name mentioned — the one living in the fewest processes — because a shared
    `scf_*` stub belongs to all six and implies nothing.

    Order is textual, not longest-first: `\\b` in the pattern already stops
    `bo` matching inside `bo_shed_load`, and "A reaches B" needs A before B.
    """
    words: list[str] = []
    for match in IDENTIFIER.finditer(question):
        word = match.group(1)
        if word.lower() in STOPWORDS or word in words:
            continue
        words.append(word)

    unscoped = [(word, corpus.resolve_name(word)) for word in words]
    resolved = [(word, function) for word, function in unscoped if function is not None]
    if not resolved:
        return []

    # Specificity is how many functions share the *name*, not how many
    # processes one resolution spans.  Each of the six `main`s lives in
    # exactly one process, so counting processes calls `main` maximally
    # specific and lets it pick the process — the opposite of what is wanted.
    # Counting same-name candidates ranks `main` (6) below `bo_shed_load` (1),
    # so the distinctive name decides.
    hint: str | None = None
    fewest = len(corpus.functions) + 1
    for word, function in resolved:
        candidates = len(corpus.by_name(word))
        if candidates < fewest and function.processes:
            fewest = candidates
            hint = function.processes[0]

    found: list[FunctionRef] = []
    seen: set[str] = set()
    for word, _function in resolved:
        scoped = corpus.resolve_name(word, hint)
        if scoped is not None and scoped.id not in seen:
            seen.add(scoped.id)
            found.append(scoped)
    return found


def _resources(corpus: Corpus, question: str) -> list[str]:
    keys: list[str] = []
    for word in {match.group(1) for match in IDENTIFIER.finditer(question)}:
        if word.lower() in STOPWORDS:
            continue
        keys.extend(G.find_resources(corpus, word, limit=3))
    for number in re.findall(r"\b\d{3,}\b", question):
        keys.extend(G.find_resources(corpus, number, limit=3))
    # Preserve first-seen order while dropping duplicates.
    return list(dict.fromkeys(keys))


def _ja(lang: str) -> bool:
    return (lang or "ja").lower().startswith("ja")


# --------------------------------------------------------------------- shapes


def _callers_answer(corpus: Corpus, function: FunctionRef, lang: str) -> dict[str, Any]:
    rows = G.callers(corpus, function.id)
    japanese = _ja(lang)
    link = function_link(function)

    if not rows:
        text = (
            f"## `{function.name}`\n\n"
            + (
                f"記録された呼び出し元はありません（{link}）。イベントやコールバック経由でのみ"
                "起動されるか、この実行結果では到達していない可能性があります。\n"
                if japanese
                else f"No recorded caller ({link}). It may be reached only via an event or "
                "callback, or not reached at all in this run.\n"
            )
        )
        return build_answer(text, corpus=corpus, cited_ids=[function.id], process=function.processes[0] if function.processes else None)

    heading = f"## `{function.name}` の呼び出し元\n\n" if japanese else f"## Callers of `{function.name}`\n\n"
    lead = (
        f"{len(rows)} 件の呼び出しが記録されています（{link}）。\n\n"
        if japanese
        else f"{len(rows)} recorded call site(s) ({link}).\n\n"
    )
    header = (
        "| 呼び出し元 | プロセス | 行 | 種別 |\n|---|---|---|---|\n"
        if japanese
        else "| Caller | Process | Line | Kind |\n|---|---|---|---|\n"
    )

    body = []
    cited = [function.id]
    for row in rows:
        caller = corpus.function(row["id"])
        label = function_link(caller) if caller else f"`{row['name']}`"
        via = f" via `{row['via']}`" if row.get("via") else ""
        body.append(
            f"| `{row['name']}` {label} | `{row['process']}` | {row['line'] or '—'} "
            f"| `{row['kind']}`{via} |\n"
        )
        cited.append(row["id"])

    paths = G.paths_from_entry(corpus, function.id, max_paths=3)
    tail = ""
    if paths:
        tail = ("\n### main からの経路\n\n" if japanese else "\n### Reached from main\n\n") + "".join(
            f"{position}. {path_link(path)}\n" for position, path in enumerate(paths, start=1)
        )

    return build_answer(
        heading + lead + header + "".join(body) + tail,
        corpus=corpus,
        cited_ids=cited,
        paths=paths,
        process=function.processes[0] if function.processes else None,
    )


def _callees_answer(corpus: Corpus, function: FunctionRef, lang: str) -> dict[str, Any]:
    rows = G.callees(corpus, function.id)
    japanese = _ja(lang)
    link = function_link(function)

    if not rows:
        text = (
            f"## `{function.name}`\n\n"
            + (
                f"他の関数を呼び出していません（{link}）。\n"
                if japanese
                else f"It calls no other recorded function ({link}).\n"
            )
        )
        return build_answer(text, corpus=corpus, cited_ids=[function.id])

    heading = f"## `{function.name}` が呼ぶ関数\n\n" if japanese else f"## What `{function.name}` calls\n\n"
    header = (
        "| 呼び出し先 | 行 | 種別 |\n|---|---|---|\n"
        if japanese
        else "| Callee | Line | Kind |\n|---|---|---|\n"
    )
    body = []
    cited = [function.id]
    resource_keys: list[str] = []
    for row in rows:
        callee = corpus.function(row["id"])
        label = function_link(callee) if callee and not callee.is_external else ""
        external = " *(external)*" if row.get("is_external") else ""
        body.append(f"| `{row['name']}`{external} {label} | {row['line'] or '—'} | `{row['kind']}` |\n")
        cited.append(row["id"])

    touched = G.resources_for_function(corpus, function.id)
    tail = ""
    if touched:
        resource_keys = [item["key"] for item in touched]
        tail = ("\n### 触れているデーモン資源\n\n" if japanese else "\n### Daemon resources touched\n\n") + "".join(
            f"- {resource_link(item['key'])} — `{'/'.join(item['operations']) or '—'}`"
            f" ({', '.join(item['target_apis'])})\n"
            for item in touched
        )

    return build_answer(
        heading + f"{link}\n\n" + header + "".join(body) + tail,
        corpus=corpus,
        cited_ids=cited,
        resource_keys=resource_keys,
        process=function.processes[0] if function.processes else None,
    )


def _resource_answer(corpus: Corpus, resource_key: str, lang: str, side: str | None) -> dict[str, Any]:
    view = G.functions_for_resource(corpus, resource_key)
    if not view:
        return {}
    japanese = _ja(lang)

    heading = f"## {view['kind']} `{view['name']}`\n\n" if japanese else f"## {view['kind']} `{view['name']}`\n\n"
    lead = (
        f"{len(view['processes'])} プロセスが触れています: "
        f"{', '.join(f'`{name}`' for name in view['processes'])}。"
        f"{'解決済み' if view['resolved'] else '未解決'}。\n\n"
        if japanese
        else f"Touched by {len(view['processes'])} process(es): "
        f"{', '.join(f'`{name}`' for name in view['processes'])}. "
        f"{'Resolved' if view['resolved'] else 'Unresolved'}.\n\n"
    )

    sections = []
    cited: list[str] = []
    wanted = {"writers": side in (None, "writers"), "readers": side in (None, "readers")}

    if wanted["writers"] and view["producers"]:
        sections.append("### 書き込み側\n\n" if japanese else "### Producers\n\n")
        for row in view["producers"]:
            function = corpus.function(row["id"])
            link = function_link(function) if function else ""
            value = row.get("value")
            binding = f" ({'値' if japanese else 'value'} `{value}`)" if value else ""
            sections.append(
                f"- `{row['process']}` → `{row['name']}` {link}"
                f" — `{row['operation']}` via `{row['target_api']}`{binding}\n"
            )
            cited.append(row["id"])
        sections.append("\n")

    if wanted["readers"] and view["consumers"]:
        sections.append("### 読み出し側\n\n" if japanese else "### Consumers\n\n")
        for row in view["consumers"]:
            function = corpus.function(row["id"])
            sections.append(
                f"- `{row['process']}` ← `{row['name']}` {function_link(function) if function else ''}"
                f" — `{row['operation']}` via `{row['target_api']}`\n"
            )
            cited.append(row["id"])
        sections.append("\n")

    if not view["producers"] and not view["consumers"]:
        sections.append(
            "この資源に紐づく関数は記録されていません。\n"
            if japanese
            else "No function is attributed to this resource in this run.\n"
        )
    elif wanted["readers"] and not view["consumers"]:
        sections.append(
            "> 読み出し側は記録されていません。この実行結果では書き込みのみが観測されています。\n"
            if japanese
            else "> No consumer recorded — only writes were observed in this run.\n"
        )

    return build_answer(
        heading + lead + "".join(sections),
        corpus=corpus,
        cited_ids=cited,
        resource_keys=[resource_key],
    )


def _reach_answer(corpus: Corpus, source: FunctionRef, target: FunctionRef, lang: str) -> dict[str, Any]:
    paths = G.call_paths(corpus, source.id, target.id, max_paths=4)
    japanese = _ja(lang)
    heading = (
        f"## `{source.name}` から `{target.name}` への経路\n\n"
        if japanese
        else f"## How `{source.name}` reaches `{target.name}`\n\n"
    )

    if not paths:
        # Two very different findings share this branch, and saying which is
        # most of the answer's value: a function nothing calls is a dead-code
        # or dispatch-table finding, while one that has callers but none from
        # here is a routing fact.  The 3D view already draws this distinction
        # on its unreached shelf; the prose should match it.
        target_callers = G.callers(corpus, target.id)
        if not target_callers:
            reason = (
                f"`{target.name}` にはこの実行結果で記録された呼び出し元が一つもありません"
                "（静的解析上、どこからも呼ばれていない）。関数ポインタ経由でのみ"
                "参照されているか、未使用の可能性があります。\n"
                if japanese
                else f"`{target.name}` has no recorded caller at all in this run — nothing in the "
                "static graph calls it. It may be reached only through a function pointer, "
                "or be unused.\n"
            )
        else:
            names = ", ".join(f"`{row['name']}`" for row in target_callers[:5])
            reason = (
                f"`{target.name}` は {names} から呼ばれていますが、"
                f"`{source.name}` からの経路はありません。"
                "イベントやフォークを経由する場合、経路がプロセスを跨いでいる可能性があります。\n"
                if japanese
                else f"`{target.name}` is called by {names}, but no route reaches it from "
                f"`{source.name}`. If they are connected via an event or a fork, the path may "
                "cross a process boundary.\n"
            )
        return build_answer(
            heading + reason,
            corpus=corpus,
            cited_ids=[source.id, target.id] + [row["id"] for row in target_callers[:5]],
        )

    body = "".join(
        f"{position}. {path_link(path)} — `{path.process}`\n"
        for position, path in enumerate(paths, start=1)
    )
    return build_answer(
        heading + body,
        corpus=corpus,
        cited_ids=[source.id, target.id],
        paths=paths,
        process=paths[0].process,
    )


def _define_answer(corpus: Corpus, function: FunctionRef, lang: str) -> dict[str, Any]:
    japanese = _ja(lang)
    incoming = len(G.callers(corpus, function.id))
    outgoing = len(G.callees(corpus, function.id))
    touched = G.resources_for_function(corpus, function.id)
    paths = G.paths_from_entry(corpus, function.id, max_paths=2)

    parts = [f"## `{function.name}`\n\n", f"`{function.signature()}` — {function_link(function)}\n\n"]
    if function.summary:
        parts.append(function.summary + "\n\n")

    facts = (
        f"- 呼び出し元 {incoming} 件 / 呼び出し先 {outgoing} 件\n"
        f"- プロセス: {', '.join(f'`{name}`' for name in function.processes)}\n"
        if japanese
        else f"- {incoming} caller(s), {outgoing} callee(s)\n"
        f"- Process(es): {', '.join(f'`{name}`' for name in function.processes)}\n"
    )
    parts.append(facts)
    if touched:
        parts.append(
            ("- デーモン資源: " if japanese else "- Daemon resources: ")
            + ", ".join(resource_link(item["key"]) for item in touched)
            + "\n"
        )
    parts.append("\n")

    if paths:
        parts.append("### main からの経路\n\n" if japanese else "### Reached from main\n\n")
        parts.extend(f"{position}. {path_link(path)}\n" for position, path in enumerate(paths, start=1))

    return build_answer(
        "".join(parts),
        corpus=corpus,
        cited_ids=[function.id],
        paths=paths,
        resource_keys=[item["key"] for item in touched],
        process=function.processes[0] if function.processes else None,
    )


# --------------------------------------------------------------------- router


def answer(corpus: Corpus, question: str, lang: str = "ja") -> StructuralAnswer | None:
    """Try to answer structurally. Returns None when the agent should take it."""
    text = (question or "").strip()
    if not text:
        return None

    functions = _identifiers(corpus, text)
    resources = _resources(corpus, text)

    # Resource questions are checked before function ones: "who writes to
    # Q_ALARM_LO" names a resource, and the daemon API in the same sentence
    # would otherwise win the identifier match.
    if resources and (_cue(text, WRITERS_CUES) or _cue(text, READERS_CUES)):
        side = "writers" if _cue(text, WRITERS_CUES) else "readers"
        payload = _resource_answer(corpus, resources[0], lang, side)
        if payload:
            return StructuralAnswer(payload, f"resource_{side}")

    if resources and not functions and len(resources) == 1:
        payload = _resource_answer(corpus, resources[0], lang, None)
        if payload:
            return StructuralAnswer(payload, "resource")

    if not functions:
        return None

    if len(functions) >= 2 and _cue(text, REACH_CUES):
        # `_identifiers` preserves the order the question names them, which is
        # the direction being asked about.
        return StructuralAnswer(_reach_answer(corpus, functions[0], functions[1], lang), "reach")

    primary = functions[0]

    if _cue(text, ENTRY_CUES) or (_cue(text, REACH_CUES) and len(functions) == 1):
        entry_paths = G.paths_from_entry(corpus, primary.id, max_paths=4)
        if entry_paths:
            japanese = _ja(lang)
            heading = (
                f"## main から `{primary.name}` への経路\n\n"
                if japanese
                else f"## How main reaches `{primary.name}`\n\n"
            )
            body = "".join(
                f"{position}. {path_link(path)} — `{path.process}`\n"
                for position, path in enumerate(entry_paths, start=1)
            )
            return StructuralAnswer(
                build_answer(
                    heading + body,
                    corpus=corpus,
                    cited_ids=[primary.id],
                    paths=entry_paths,
                    process=entry_paths[0].process,
                ),
                "from_entry",
            )

    if _cue(text, CALLERS_CUES):
        return StructuralAnswer(_callers_answer(corpus, primary, lang), "callers")

    if _cue(text, CALLEES_CUES):
        return StructuralAnswer(_callees_answer(corpus, primary, lang), "callees")

    if _cue(text, DEFINE_CUES) and len(functions) == 1:
        return StructuralAnswer(_define_answer(corpus, primary, lang), "define")

    return None
