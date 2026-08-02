"""OpenAI-compatible embedding and rerank clients.

Stdlib only, matching `function_summaries.py`: the visualizer's serving path
must not grow a hard dependency on an HTTP library, and both endpoints are a
single POST each.

Everything degrades rather than raises.  A cold or missing endpoint turns the
dense retrieval lane off and leaves BM25 and structural traversal working, so
the product loses recall instead of falling over.  Callers check `.available`
and read `.last_error` for the status endpoint.

Embeddings are cached to disk keyed by `sha1(prefix + text)` and the model id,
because the corpus barely changes between runs: re-indexing after a tracer run
should re-embed only the functions whose source actually moved.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from pathlib import Path
from typing import Any, Sequence

from .config import Settings
from .http import TransportError, api_root, get_json, post_json


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class VectorCache:
    """Disk-backed `sha1 -> vector` map, one file per embedding model."""

    def __init__(self, directory: Path, model: str, enabled: bool = True) -> None:
        self.enabled = enabled
        slug = "".join(character if character.isalnum() else "_" for character in model)[:80]
        self.path = Path(directory) / f"embeddings-{slug}.json"
        self._entries: dict[str, list[float]] = {}
        self._dirty = False
        self._lock = threading.Lock()
        if enabled and self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._entries = {k: v for k, v in loaded.items() if isinstance(v, list)}
            except (OSError, json.JSONDecodeError):
                # A truncated cache costs re-embedding, nothing more.
                self._entries = {}

    @staticmethod
    def key(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()

    def get(self, text: str) -> list[float] | None:
        if not self.enabled:
            return None
        return self._entries.get(self.key(text))

    def put(self, text: str, vector: list[float]) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._entries[self.key(text)] = list(vector)
            self._dirty = True

    def flush(self) -> None:
        if not self.enabled or not self._dirty:
            return
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix(".tmp")
                temporary.write_text(json.dumps(self._entries), encoding="utf-8")
                temporary.replace(self.path)
                self._dirty = False
            except OSError:
                pass

    def __len__(self) -> int:
        return len(self._entries)


class EmbeddingClient:
    """Batched embeddings with per-model query/document prefixes."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.embed_model or ""
        self.base_url = api_root(settings.embed_base_url)
        self.prefixes = settings.prefix_policy()
        self.dimension: int | None = None
        self.last_error: str | None = None
        self.cache = VectorCache(
            settings.cache_dir or Path(".wiki_cache"),
            self.model or "none",
            enabled=settings.use_cache and bool(self.model),
        )

    @property
    def available(self) -> bool:
        return bool(self.base_url and self.model)

    def probe(self) -> bool:
        """One cheap call so the status endpoint can report honestly."""
        if not self.available:
            self.last_error = "no embedding endpoint configured"
            return False
        vector = self.embed_query("availability probe")
        return vector is not None

    def embed_query(self, text: str) -> list[float] | None:
        prefixed = f"{self.prefixes.get('query', '')}{text}"
        vectors = self._embed([prefixed])
        return vectors[0] if vectors else None

    def embed_documents(self, texts: Sequence[str]) -> list[list[float] | None]:
        prefix = self.prefixes.get("document", "")
        return self._embed_many([f"{prefix}{text}" for text in texts])

    # ------------------------------------------------------------ internals

    def _embed_many(self, texts: Sequence[str]) -> list[list[float] | None]:
        results: list[list[float] | None] = [None] * len(texts)
        pending: list[tuple[int, str]] = []

        for position, text in enumerate(texts):
            cached = self.cache.get(text)
            if cached is not None:
                results[position] = cached
            else:
                pending.append((position, text))

        batch_size = max(1, int(self.settings.embed_batch))
        for start in range(0, len(pending), batch_size):
            chunk = pending[start : start + batch_size]
            vectors = self._embed([text for _, text in chunk])
            if vectors is None:
                continue
            for (position, text), vector in zip(chunk, vectors):
                results[position] = vector
                self.cache.put(text, vector)

        self.cache.flush()
        return results

    def _embed(self, texts: Sequence[str], attempt: int = 0) -> list[list[float]] | None:
        if not self.available or not texts:
            return None
        try:
            payload = post_json(
                f"{self.base_url}/v1/embeddings",
                {"model": self.model, "input": list(texts)},
                self.settings.embed_api_key,
                self.settings.timeout_seconds,
            )
        except TransportError as exc:
            # One batch too large for the server's context is the common
            # failure; halving is cheaper than guessing token counts.
            if len(texts) > 1 and attempt < 4:
                middle = len(texts) // 2
                left = self._embed(texts[:middle], attempt + 1)
                right = self._embed(texts[middle:], attempt + 1)
                if left is not None and right is not None:
                    return left + right
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                return self._embed(texts, attempt + 1)
            self.last_error = f"embedding request failed: {exc}"
            return None

        data = payload.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            self.last_error = "embedding response did not match the request"
            return None

        # vLLM preserves request order, but the field is documented as
        # authoritative, so sort by it rather than trusting position.
        ordered = sorted(data, key=lambda item: item.get("index", 0))
        vectors = [item.get("embedding") for item in ordered]
        if any(not isinstance(vector, list) for vector in vectors):
            self.last_error = "embedding response contained no vector"
            return None

        self.dimension = len(vectors[0])
        self.last_error = None
        return vectors  # type: ignore[return-value]


class RerankClient:
    """Cross-encoder rerank, with a graceful no-op when unavailable."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.rerank_model or ""
        self.base_url = api_root(settings.rerank_base_url)
        self.last_error: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.base_url and self.model)

    def probe(self) -> bool:
        if not self.available:
            self.last_error = "no rerank endpoint configured"
            return False
        scores = self.score("availability probe", ["availability probe"])
        return scores is not None

    def score(self, query: str, documents: Sequence[str]) -> list[float] | None:
        """Relevance in [0, 1] per document, or None if the endpoint is down.

        `None` and `[0.0, ...]` mean different things and callers must not
        conflate them: the first says "no opinion, keep the fusion order",
        the second says "genuinely irrelevant".
        """
        if not self.available or not documents:
            return None

        payload = {
            "model": self.model,
            "query": query,
            "documents": list(documents),
            "top_n": len(documents),
        }
        for path in ("/v1/rerank", "/rerank"):
            try:
                response = post_json(
                    f"{self.base_url}{path}",
                    payload,
                    self.settings.rerank_api_key,
                    self.settings.timeout_seconds,
                )
            except TransportError as exc:
                self.last_error = f"rerank request failed: {exc}"
                continue

            results = response.get("results") or response.get("data")
            if not isinstance(results, list):
                self.last_error = "rerank response had no results"
                continue

            scores = [0.0] * len(documents)
            for item in results:
                index = item.get("index")
                if isinstance(index, int) and 0 <= index < len(scores):
                    scores[index] = float(item.get("relevance_score", item.get("score", 0.0)))
            self.last_error = None
            return scores

        return None


def build_clients(settings: Settings) -> tuple[EmbeddingClient, RerankClient]:
    return EmbeddingClient(settings), RerankClient(settings)


def discover(candidate_urls: Sequence[str], timeout: float = 3.0) -> dict[str, Any]:
    """Ask each base URL what it serves, so config can be checked, not guessed.

    A vLLM server exposes both `/v1/embeddings` and `/v1/rerank` regardless of
    what it loaded, so the served model id is the only reliable signal of which
    role a port actually plays.
    """
    found: list[dict[str, Any]] = []
    for url in candidate_urls:
        base = api_root(url)
        try:
            payload = get_json(f"{base}/v1/models", timeout=timeout)
        except TransportError as exc:
            found.append({"base_url": base, "reachable": False, "error": str(exc)})
            continue

        for model in payload.get("data") or []:
            identifier = str(model.get("id") or "")
            lowered = identifier.lower()
            if "rerank" in lowered or "cross-encoder" in lowered:
                role = "rerank"
            elif "embed" in lowered or "ruri" in lowered or "bge-m3" in lowered:
                role = "embed"
            else:
                role = "unknown"
            found.append(
                {
                    "base_url": base,
                    "reachable": True,
                    "model": identifier,
                    "role": role,
                    "max_model_len": model.get("max_model_len"),
                }
            )
    return {"endpoints": found}
