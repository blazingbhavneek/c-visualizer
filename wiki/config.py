"""Configuration for the wiki agent: env vars, with a JSON file underneath.

Precedence is `environment > wiki.config.json > built-in default`, matching how
`function_summaries.py` already reads its own settings.  Every model endpoint
is optional: with none configured the package still answers structural
questions by pure graph traversal, so a missing key degrades the product
rather than breaking it.

Model families need different prompt prefixes to retrieve well, and getting
that wrong is silent — retrieval simply gets worse.  `prefix_policy()` keys the
known conventions off the model id so swapping models does not quietly cost
recall.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "wiki.config.json"

# Retrieval prefix conventions, keyed by a substring of the model id.
#
# Qwen3-Embedding wants an instruction on the query side only.  Ruri v3
# (cl-nagoya) wants a literal Japanese prefix on *both* sides and loses
# noticeable recall without it.  Anything unrecognised gets no prefix, which
# is correct for the majority of sentence-transformers checkpoints.
PREFIX_POLICIES: dict[str, dict[str, str]] = {
    "qwen3-embedding": {
        "query": "Instruct: {task}\nQuery: ",
        "document": "",
    },
    "ruri-v3": {
        "query": "検索クエリ: ",
        "document": "検索文書: ",
    },
    "ruri-": {
        "query": "クエリ: ",
        "document": "文章: ",
    },
    "bge-m3": {"query": "", "document": ""},
    "e5": {"query": "query: ", "document": "passage: "},
}

DEFAULT_EMBED_TASK = (
    "Given a question about a C codebase, retrieve the functions, call paths "
    "and daemon resources that answer it"
)


def _flag(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    # --- endpoints -------------------------------------------------------
    embed_base_url: str | None = None
    embed_model: str | None = None
    embed_api_key: str = "EMPTY"
    embed_task: str = DEFAULT_EMBED_TASK
    embed_batch: int = 32

    rerank_base_url: str | None = None
    rerank_model: str | None = None
    rerank_api_key: str = "EMPTY"

    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str = "EMPTY"
    llm_temperature: float = 0.1

    timeout_seconds: float = 120.0

    # --- retrieval shape -------------------------------------------------
    # Weighted reciprocal-rank fusion over four lanes.  Identifier queries are
    # what BM25 is unbeatable at ("who calls scf_hist_save"), conceptual ones
    # are what the dense lanes are for, so neither dominates.
    rrf_k: int = 60
    pool_bm25: int = 40
    pool_summary_vec: int = 40
    pool_source_vec: int = 40
    weight_bm25: float = 1.0
    weight_summary_vec: float = 1.0
    weight_source_vec: float = 0.7
    weight_name_exact: float = 2.0

    rerank_pool: int = 40
    rerank_top_k: int = 12

    # The cross-encoder is authoritative on topical relevance but blind to
    # exact-identifier intent, so its score is blended with the fusion rank
    # rather than replacing it.  See `RetrievalIndex._rerank`.
    weight_fusion_prior: float = 0.25
    weight_exact_bonus: float = 0.30

    # --- agent shape -----------------------------------------------------
    subagent_count: int = 4
    subagent_concurrency: int = 4
    lead_max_steps: int = 6
    subagent_max_steps: int = 8
    max_source_chars: int = 12_000

    # --- caching ---------------------------------------------------------
    cache_dir: Path | None = None
    use_cache: bool = True

    extras: dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------------- load

    @classmethod
    def load(cls, project_root: Path | None = None) -> "Settings":
        root = Path(project_root or Path(__file__).resolve().parent.parent)
        file_values: dict[str, Any] = {}
        config_path = root / CONFIG_FILENAME
        if config_path.is_file():
            try:
                loaded = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    file_values = loaded
            except (OSError, json.JSONDecodeError):
                # A malformed config must not stop the visualizer from
                # serving; the status endpoint surfaces the degraded state.
                file_values = {}

        def pick(env: str, key: str, default: Any) -> Any:
            raw = os.environ.get(env)
            if raw is not None and raw != "":
                return raw
            if key in file_values:
                return file_values[key]
            return default

        settings = cls(
            embed_base_url=pick("WIKI_EMBED_BASE_URL", "embed_base_url", None),
            embed_model=pick("WIKI_EMBED_MODEL", "embed_model", None),
            embed_api_key=str(pick("WIKI_EMBED_API_KEY", "embed_api_key", "EMPTY")),
            embed_task=str(pick("WIKI_EMBED_TASK", "embed_task", DEFAULT_EMBED_TASK)),
            embed_batch=int(pick("WIKI_EMBED_BATCH", "embed_batch", 32)),
            rerank_base_url=pick("WIKI_RERANK_BASE_URL", "rerank_base_url", None),
            rerank_model=pick("WIKI_RERANK_MODEL", "rerank_model", None),
            rerank_api_key=str(pick("WIKI_RERANK_API_KEY", "rerank_api_key", "EMPTY")),
            llm_base_url=pick("WIKI_LLM_BASE_URL", "llm_base_url", None),
            llm_model=pick("WIKI_LLM_MODEL", "llm_model", None),
            llm_api_key=str(pick("WIKI_LLM_API_KEY", "llm_api_key", "EMPTY")),
            llm_temperature=float(pick("WIKI_LLM_TEMPERATURE", "llm_temperature", 0.1)),
            timeout_seconds=float(pick("WIKI_TIMEOUT", "timeout_seconds", 120.0)),
            subagent_count=int(pick("WIKI_SUBAGENTS", "subagent_count", 4)),
            subagent_concurrency=int(pick("WIKI_SUBAGENT_CONCURRENCY", "subagent_concurrency", 4)),
            rerank_top_k=int(pick("WIKI_RERANK_TOP_K", "rerank_top_k", 12)),
            use_cache=_flag(os.environ.get("WIKI_CACHE"), bool(file_values.get("use_cache", True))),
            extras={k: v for k, v in file_values.items() if k.startswith("x_")},
        )

        cache = pick("WIKI_CACHE_DIR", "cache_dir", None)
        settings.cache_dir = Path(cache) if cache else root / ".wiki_cache"
        return settings

    # ------------------------------------------------------------ helpers

    @property
    def has_embeddings(self) -> bool:
        return bool(self.embed_base_url and self.embed_model)

    @property
    def has_reranker(self) -> bool:
        return bool(self.rerank_base_url and self.rerank_model)

    @property
    def has_llm(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)

    def prefix_policy(self) -> dict[str, str]:
        """Query/document prefixes for the configured embedding model."""
        model = (self.embed_model or "").lower()
        for marker, policy in PREFIX_POLICIES.items():
            if marker in model:
                return {
                    "query": policy["query"].replace("{task}", self.embed_task),
                    "document": policy["document"],
                }
        return {"query": "", "document": ""}

    def describe(self) -> dict[str, Any]:
        """What `/api/wiki/status` reports. Never includes an API key."""
        return {
            "embed_model": self.embed_model,
            "embed_base_url": self.embed_base_url,
            "rerank_model": self.rerank_model,
            "rerank_base_url": self.rerank_base_url,
            "llm_model": self.llm_model,
            "llm_base_url": self.llm_base_url,
            "has_embeddings": self.has_embeddings,
            "has_reranker": self.has_reranker,
            "has_llm": self.has_llm,
            "prefixes": self.prefix_policy(),
        }
