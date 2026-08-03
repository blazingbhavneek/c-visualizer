"""Dependency-aware, bottom-up summaries for visualizer function graphs.

The legacy tracer resolves selected daemon/API arguments.  This module is a
separate pass over the complete static call graph: leaf functions are
summarized first, then their callers receive those summaries as context.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol


class SummaryClient(Protocol):
    async def summarize(self, *, system: str, prompt: str) -> str: ...


class WikiClient(Protocol):
    async def ask(self, question: str) -> str: ...


@dataclass(slots=True)
class SummaryConfig:
    enabled: bool = False
    model: str | None = None
    base_url: str | None = None
    api_key: str = "EMPTY"
    wiki_url: str | None = None
    wiki_api_key: str | None = None
    wiki_placeholder: bool = False
    concurrency: int = 8
    timeout_seconds: float = 60.0
    max_source_chars: int = 30_000
    max_dependency_chars: int = 24_000
    use_cache: bool = True
    # Re-running summaries over finished results should only fill the gaps, even
    # when the fingerprint cache is gone. Off during a normal run, where the
    # cache decides what to reuse.
    only_missing: bool = False

    @classmethod
    def from_env(cls) -> "SummaryConfig":
        enabled = os.environ.get("FUNCTION_SUMMARIES", "0").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        return cls(
            enabled=enabled,
            model=os.environ.get("FUNCTION_SUMMARY_MODEL"),
            base_url=os.environ.get("FUNCTION_SUMMARY_BASE_URL"),
            api_key=os.environ.get("FUNCTION_SUMMARY_API_KEY", "EMPTY"),
            wiki_url=os.environ.get("LLM_WIKI_ASK_URL"),
            wiki_api_key=os.environ.get("LLM_WIKI_API_KEY"),
            wiki_placeholder=os.environ.get("LLM_WIKI_PLACEHOLDER", "0").lower()
            in {"1", "true", "yes", "on"},
            concurrency=max(1, int(os.environ.get("FUNCTION_SUMMARY_CONCURRENCY", "8"))),
            timeout_seconds=max(
                1.0, float(os.environ.get("FUNCTION_SUMMARY_TIMEOUT", "60"))
            ),
            use_cache=os.environ.get("FUNCTION_SUMMARY_CACHE", "1").lower()
            not in {"0", "false", "no", "off"},
        )


class OpenAISummaryClient:
    """Small async adapter for OpenAI-compatible chat-completions servers."""

    def __init__(self, config: SummaryConfig) -> None:
        if not config.model:
            raise ValueError(
                "Function summaries need FUNCTION_SUMMARY_MODEL or --summary-model."
            )
        from openai import AsyncOpenAI

        kwargs: dict[str, Any] = {"api_key": config.api_key}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        self.client = AsyncOpenAI(**kwargs)
        self.model = config.model
        self.timeout = config.timeout_seconds

    async def summarize(self, *, system: str, prompt: str) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=700,
            timeout=self.timeout,
        )
        return (response.choices[0].message.content or "").strip()


class HttpWikiClient:
    """POST questions to either a JSON `/ask` API or an SSE ask endpoint."""

    def __init__(
        self, url: str, *, timeout_seconds: float = 60.0, api_key: str | None = None
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key
        self._disabled_error: str | None = None

    @staticmethod
    def _answer_from_payload(payload: Any) -> str | None:
        if isinstance(payload, str):
            return payload.strip() or None
        if not isinstance(payload, dict):
            return None
        for key in ("answer", "text", "content", "output", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            nested = HttpWikiClient._answer_from_payload(value)
            if nested:
                return nested
        return HttpWikiClient._answer_from_payload(payload.get("data"))

    @classmethod
    def _parse_response(cls, body: str, content_type: str) -> str:
        if "text/event-stream" not in content_type and body.lstrip().startswith(("{", "[")):
            return cls._answer_from_payload(json.loads(body)) or ""

        answers: list[str] = []
        stream_error: str | None = None
        for line in body.splitlines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                payload = json.loads(data)
                if isinstance(payload, dict) and payload.get("type") == "error":
                    stream_error = cls._answer_from_payload(payload) or "unknown stream error"
                    continue
                if isinstance(payload, dict) and payload.get("type") not in (None, "answer"):
                    continue
                answer = cls._answer_from_payload(payload)
            except json.JSONDecodeError:
                answer = data
            if answer:
                answers.append(answer)
        if stream_error and not answers:
            raise RuntimeError(f"llm-wiki stream error: {stream_error}")
        return answers[-1] if answers else body.strip()

    def _ask_sync(self, question: str) -> str:
        body = json.dumps({"question": question}).encode("utf-8")
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            request = urllib.request.Request(
                self.url, data=body, headers=headers, method="POST"
            )
            remaining = max(1.0, deadline - time.monotonic())
            try:
                with urllib.request.urlopen(
                    request, timeout=min(10.0, remaining)
                ) as response:
                    content_type = response.headers.get("Content-Type", "")
                    text = response.read().decode("utf-8", errors="replace")
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                retryable = False
                try:
                    retryable = bool(json.loads(detail).get("retryable"))
                except (json.JSONDecodeError, AttributeError):
                    pass
                # llm-wiki-dist lazily builds a selected database. Its ask
                # handler can surface that cold start as retryable 502/503.
                if (
                    exc.code in {502, 503}
                    and retryable
                    and time.monotonic() < deadline
                ):
                    time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
                    continue
                raise RuntimeError(
                    f"llm-wiki returned HTTP {exc.code}: {detail}"
                ) from exc
            except urllib.error.URLError as exc:
                raise RuntimeError(f"llm-wiki request failed: {exc.reason}") from exc
        answer = self._parse_response(text, content_type)
        if not answer:
            raise RuntimeError("llm-wiki returned no answer")
        return answer

    async def ask(self, question: str) -> str:
        if self._disabled_error:
            raise RuntimeError(self._disabled_error)
        try:
            return await asyncio.to_thread(self._ask_sync, question)
        except Exception as exc:
            # A dead/misconfigured wiki should cost at most one concurrency
            # wave, not one timeout for every function in a large repository.
            self._disabled_error = str(exc)
            raise


class PlaceholderWikiClient:
    """Honest offline stand-in used to exercise wiki-enriched scheduling."""

    is_placeholder = True

    async def ask(self, question: str) -> str:
        return (
            "[OFFLINE LLM-WIKI PLACEHOLDER] No theory/API/manual facts were "
            "available during this test. Do not infer library behavior from this "
            "placeholder. A real run must call the configured llm-wiki /api/ask "
            "endpoint. Requested lookup: "
            + question
        )


def _strongly_connected_components(
    nodes: set[str], dependencies: dict[str, set[str]]
) -> list[list[str]]:
    """Iterative Kosaraju SCCs keep deep generated call chains stack-safe."""
    visited: set[str] = set()
    finishing_order: list[str] = []
    for start in sorted(nodes):
        if start in visited:
            continue
        visited.add(start)
        stack = [(start, False)]
        while stack:
            node, expanded = stack.pop()
            if expanded:
                finishing_order.append(node)
                continue
            stack.append((node, True))
            for child in sorted(dependencies.get(node, set()), reverse=True):
                if child in nodes and child not in visited:
                    visited.add(child)
                    stack.append((child, False))

    reverse_dependencies: dict[str, set[str]] = {node: set() for node in nodes}
    for caller, children in dependencies.items():
        for child in children:
            if caller in nodes and child in nodes:
                reverse_dependencies[child].add(caller)

    components: list[list[str]] = []
    assigned: set[str] = set()
    for start in reversed(finishing_order):
        if start in assigned:
            continue
        component = []
        stack = [start]
        assigned.add(start)
        while stack:
            node = stack.pop()
            component.append(node)
            for parent in sorted(reverse_dependencies[node], reverse=True):
                if parent not in assigned:
                    assigned.add(parent)
                    stack.append(parent)
        components.append(sorted(component))
    return components


def dependency_layers(
    function_ids: set[str], dependencies: dict[str, set[str]]
) -> list[list[list[str]]]:
    """Return SCC groups in leaf-to-root layers.

    A layer is safe to flatten into coroutines and run with ``asyncio.gather``;
    every dependency outside the current recursive group is in an earlier layer.
    """
    components = _strongly_connected_components(function_ids, dependencies)
    component_for = {
        function_id: component_index
        for component_index, component in enumerate(components)
        for function_id in component
    }
    component_dependencies: dict[int, set[int]] = {}
    for component_index, component in enumerate(components):
        component_dependencies[component_index] = {
            component_for[child]
            for function_id in component
            for child in dependencies.get(function_id, set())
            if component_for[child] != component_index
        }

    remaining = set(range(len(components)))
    completed: set[int] = set()
    layers: list[list[list[str]]] = []
    while remaining:
        ready = sorted(
            (
                component_index
                for component_index in remaining
                if component_dependencies[component_index] <= completed
            ),
            key=lambda component_index: components[component_index],
        )
        if not ready:  # Defensive only: SCC condensation is always acyclic.
            ready = sorted(remaining)
        layers.append([components[component_index] for component_index in ready])
        completed.update(ready)
        remaining.difference_update(ready)
    return layers


class FunctionSummarizer:
    def __init__(
        self,
        *,
        functions: dict[str, dict[str, Any]],
        calls: dict[str, dict[str, Any]],
        summary_client: SummaryClient,
        config: SummaryConfig,
        wiki_client: WikiClient | None = None,
        cache_path: Path | None = None,
        checkpoint: Callable[[], Any | Awaitable[Any]] | None = None,
    ) -> None:
        self.functions = functions
        self.calls = calls
        self.summary_client = summary_client
        self.config = config
        self.wiki_client = wiki_client
        self.cache_path = cache_path
        self.checkpoint = checkpoint
        self.semaphore = asyncio.Semaphore(max(1, config.concurrency))
        self.cache = self._load_cache() if config.use_cache else {"version": 1, "entries": {}}
        self.fingerprints: dict[str, str] = {}

        self.internal_ids = {
            function_id
            for function_id, function in functions.items()
            if not function.get("is_external") and not function.get("is_library_api")
        }
        self.dependencies: dict[str, set[str]] = {function_id: set() for function_id in self.internal_ids}
        self.external_calls: dict[str, set[str]] = {function_id: set() for function_id in self.internal_ids}
        for call in calls.values():
            source = call.get("source")
            target = call.get("target")
            if source not in self.internal_ids or target not in functions:
                continue
            target_function = functions[target]
            if target_function.get("is_external") or target_function.get("is_library_api"):
                self.external_calls[source].add(target_function.get("name", target))
            if target in self.internal_ids:
                self.dependencies[source].add(target)

    def _load_cache(self) -> dict[str, Any]:
        if not self.cache_path or not self.cache_path.is_file():
            return {"version": 1, "entries": {}}
        try:
            loaded = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "entries": {}}
        return loaded if loaded.get("version") == 1 else {"version": 1, "entries": {}}

    def _write_cache(self) -> None:
        if not self.config.use_cache or not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self.cache_path.name}.", dir=self.cache_path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.cache, handle, ensure_ascii=False, indent=2)
            os.replace(temporary_name, self.cache_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def _fingerprint(self, function_id: str, recursive_group: set[str]) -> str:
        function = self.functions[function_id]
        dependency_fingerprints = [
            self.fingerprints.get(child, child)
            for child in sorted(self.dependencies[function_id] - recursive_group)
        ]
        peer_sources = [
            self.functions[peer].get("source_sha256", "")
            for peer in sorted(recursive_group - {function_id})
        ]
        value = json.dumps(
            {
                "source": function.get("source_sha256")
                or hashlib.sha256(function.get("source", "").encode("utf-8", errors="replace")).hexdigest(),
                "dependencies": dependency_fingerprints,
                "recursive_peers": peer_sources,
                "external_calls": sorted(self.external_calls[function_id]),
                "model": self.config.model,
                "wiki_url": self.config.wiki_url,
            },
            sort_keys=True,
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    async def _wiki_context(self, function_id: str) -> tuple[str, str]:
        external_calls = sorted(self.external_calls[function_id])
        if not external_calls:
            return "not_needed", ""
        if self.wiki_client is None:
            return "unconfigured", ""
        function = self.functions[function_id]
        question = (
            "Using the theory/API/manual knowledge in this wiki, explain only the behavior, "
            "parameters, return values, side effects, and important constraints of these library "
            f"functions used by {function.get('name')}: {', '.join(external_calls)}. "
            "Do not infer behavior for project-local functions."
        )
        try:
            status = (
                "placeholder"
                if getattr(self.wiki_client, "is_placeholder", False)
                else "ready"
            )
            return status, (await self.wiki_client.ask(question))[:20_000]
        except Exception as exc:  # Wiki knowledge is enrichment; code summarization can continue.
            return "error", f"llm-wiki unavailable: {exc}"

    def _prompt(
        self,
        function_id: str,
        recursive_group: set[str],
        wiki_context: str,
    ) -> str:
        function = self.functions[function_id]
        dependency_blocks = []
        for child in sorted(self.dependencies[function_id] - recursive_group):
            child_function = self.functions[child]
            child_summary = child_function.get("summary") or "Summary unavailable; rely on the call name only."
            dependency_blocks.append(f"- {child_function.get('name')}: {child_summary}")
        dependencies = "\n".join(dependency_blocks) or "(none; this is a leaf function)"
        dependencies = dependencies[: self.config.max_dependency_chars]

        recursive_peers = [
            self.functions[peer].get("name", peer)
            for peer in sorted(recursive_group - {function_id})
        ]
        source = function.get("source", "")[: self.config.max_source_chars]
        external = ", ".join(sorted(self.external_calls[function_id])) or "(none)"
        return f"""Summarize this C function for engineers navigating a code graph.

Function: {function.get('name')}
File: {function.get('file')}
Definition lines: {function.get('start_line')}–{function.get('end_line')}
Recursive peers in the same dependency component: {', '.join(recursive_peers) or '(none)'}
External/library calls: {external}

Already-computed direct callee summaries:
{dependencies}

Relevant llm-wiki API/manual knowledge:
{wiki_context or '(none available)'}

Function source:
```c
{source}
```

Write one compact paragraph covering purpose, inputs/outputs, key state or side effects, control flow, and how its callees contribute. Distinguish facts visible in code from API facts supplied by the wiki. Do not invent missing behavior."""

    @staticmethod
    def _clean_summary(summary: str) -> str:
        summary = summary.strip()
        summary = re.sub(r"^```(?:text|markdown)?\s*", "", summary, flags=re.IGNORECASE)
        summary = re.sub(r"\s*```$", "", summary)
        return summary.strip()

    async def _summarize_one(
        self, function_id: str, recursive_group: set[str], layer: int
    ) -> str:
        function = self.functions[function_id]
        fingerprint = self._fingerprint(function_id, recursive_group)
        self.fingerprints[function_id] = fingerprint
        if self.config.only_missing and (function.get("summary") or "").strip():
            function.setdefault("summary_status", "ready")
            return "cached"
        cached = self.cache.get("entries", {}).get(function_id, {})
        if cached.get("fingerprint") == fingerprint and cached.get("summary"):
            function.update(
                {
                    "summary": cached["summary"],
                    "summary_status": "ready",
                    "summary_cached": True,
                    "summary_layer": layer,
                    "summary_dependencies": sorted(self.dependencies[function_id]),
                    "wiki_status": cached.get("wiki_status", "cached"),
                }
            )
            return "cached"

        async with self.semaphore:
            wiki_status, wiki_context = await self._wiki_context(function_id)
            try:
                summary = await self.summary_client.summarize(
                    system=(
                        "You are a precise C codebase documentation assistant. "
                        "Use provided callee summaries as established context and never guess."
                    ),
                    prompt=self._prompt(function_id, recursive_group, wiki_context),
                )
                summary = self._clean_summary(summary)
                if not summary:
                    raise RuntimeError("summary model returned an empty response")
            except Exception as exc:
                function.update(
                    {
                        "summary": None,
                        "summary_status": "pending",
                        "summary_error": str(exc),
                        "summary_layer": layer,
                        "summary_dependencies": sorted(self.dependencies[function_id]),
                        "wiki_status": wiki_status,
                    }
                )
                return "failed"

        function.update(
            {
                "summary": summary,
                "summary_status": "ready",
                "summary_cached": False,
                "summary_layer": layer,
                "summary_dependencies": sorted(self.dependencies[function_id]),
                "wiki_status": wiki_status,
            }
        )
        self.cache.setdefault("entries", {})[function_id] = {
            "fingerprint": fingerprint,
            "summary": summary,
            "wiki_status": wiki_status,
        }
        return "ready"

    async def run(self) -> dict[str, int]:
        layers = dependency_layers(self.internal_ids, self.dependencies)
        report = {"functions": len(self.internal_ids), "layers": len(layers), "ready": 0, "cached": 0, "failed": 0}
        for layer_index, component_groups in enumerate(layers):
            tasks = [
                self._summarize_one(function_id, set(component), layer_index)
                for component in component_groups
                for function_id in component
            ]
            outcomes = await asyncio.gather(*tasks)
            for outcome in outcomes:
                report[outcome] += 1
            self._write_cache()
            if self.checkpoint:
                checkpoint_result = self.checkpoint()
                if asyncio.iscoroutine(checkpoint_result):
                    await checkpoint_result
        return report


async def summarize_collector(
    collector: Any,
    config: SummaryConfig,
    *,
    summary_client: SummaryClient | None = None,
    wiki_client: WikiClient | None = None,
) -> dict[str, int]:
    """Run the complete bottom-up pass and checkpoint each dependency layer."""
    if not config.enabled:
        return {"functions": 0, "layers": 0, "ready": 0, "cached": 0, "failed": 0}
    if wiki_client is None and not config.wiki_placeholder and not config.wiki_url:
        raise ValueError(
            "Function summaries require LLM_WIKI_ASK_URL/--wiki-url. "
            "For an offline test, explicitly use --wiki-placeholder."
        )
    summary_client = summary_client or OpenAISummaryClient(config)
    if wiki_client is None:
        if config.wiki_placeholder:
            wiki_client = PlaceholderWikiClient()
        elif config.wiki_url:
            wiki_client = HttpWikiClient(
                config.wiki_url,
                timeout_seconds=config.timeout_seconds,
                api_key=config.wiki_api_key,
            )
    cache_path = (
        collector.results_root
        / "visualizer"
        / collector.process_name
        / "function-summary-cache.json"
    )
    summarizer = FunctionSummarizer(
        functions=collector.functions,
        calls=collector.calls,
        summary_client=summary_client,
        wiki_client=wiki_client,
        config=config,
        cache_path=cache_path,
        checkpoint=collector.write,
    )
    return await summarizer.run()
