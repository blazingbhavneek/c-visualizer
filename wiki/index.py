"""Hybrid retrieval over a corpus: BM25 + dense lanes fused, then reranked.

Why four lanes rather than one embedding index:

* Half the questions this tool gets are *identifier* questions — "who calls
  `scf_hist_save`", "where is `Q_ALARM_LO` written".  BM25 is unbeatable at
  those and an embedding model is mediocre at them.
* The other half are conceptual — "how does a boiler trip get recorded" — and
  are exactly what BM25 misses, because the summary says "persists the trip
  record" and never uses the questioner's words.
* Names and summaries retrieve differently from source bodies, so they get
  separate lanes rather than being concatenated into one blurred document.

The lanes are fused with weighted reciprocal-rank fusion, which needs no score
calibration between lanes — important here, because a BM25 score and a cosine
similarity are not comparable quantities.  A cross-encoder then reranks the
fused pool, which is where most of the final precision comes from.

Every lane is optional.  With no embedding endpoint this degrades to BM25 plus
exact-name matching, which still answers the identifier half of the workload.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .config import Settings
from .corpus import Corpus, FunctionRef
from .embed import EmbeddingClient, RerankClient

SOURCE_CHUNK_LINES = 45
SOURCE_CHUNK_OVERLAP = 8

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def tokenize(text: str) -> list[str]:
    """Identifier-aware tokenizer with a CJK fallback.

    `scf_hist_save` yields `scf_hist_save` *and* `scf`, `hist`, `save`: the
    whole identifier so an exact query ranks it decisively, the parts so a
    query for "hist save" finds it without the user knowing the naming
    convention.  Emitting only the parts — the obvious mistake — makes every
    `scf_*` function look alike to BM25.

    Japanese has no whitespace to split on and we have no morphological
    analyser, so CJK runs are indexed as character bigrams.  Crude, but it
    keeps BM25 from being blind to a Japanese query; the dense lane is what
    actually carries those.
    """
    lowered = unicodedata.normalize("NFKC", text or "")
    tokens: list[str] = []

    for match in _WORD.finditer(lowered):
        word = match.group(0).strip("_")
        if not word:
            continue
        tokens.append(word.lower())

        parts: list[str] = []
        for piece in word.split("_"):
            if piece:
                parts.extend(part for part in _CAMEL.split(piece) if part)
        if len(parts) > 1:
            tokens.extend(part.lower() for part in parts)

    for run in _CJK.findall(lowered):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))

    return tokens


@dataclass(slots=True)
class Document:
    """One retrievable unit. Several documents may point at one function."""

    id: str
    lane: str  # "summary" | "source" | "resource"
    ref_kind: str  # "function" | "resource"
    ref_id: str
    text: str
    process: str | None = None
    name: str = ""
    start_line: int | None = None
    end_line: int | None = None


@dataclass(slots=True)
class Hit:
    ref_kind: str
    ref_id: str
    name: str
    score: float
    lanes: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    rerank_score: float | None = None


class BM25:
    """Okapi BM25 over pre-tokenized documents."""

    def __init__(self, corpus_tokens: Sequence[Sequence[str]], k1: float = 1.4, b: float = 0.72):
        self.k1 = k1
        self.b = b
        self.length = [len(tokens) for tokens in corpus_tokens]
        self.average_length = (sum(self.length) / len(self.length)) if self.length else 0.0
        self.frequencies: list[dict[str, int]] = []
        document_frequency: dict[str, int] = defaultdict(int)

        for tokens in corpus_tokens:
            counts: dict[str, int] = defaultdict(int)
            for token in tokens:
                counts[token] += 1
            self.frequencies.append(dict(counts))
            for token in counts:
                document_frequency[token] += 1

        total = len(corpus_tokens)
        self.idf = {
            token: math.log(1.0 + (total - frequency + 0.5) / (frequency + 0.5))
            for token, frequency in document_frequency.items()
        }
        self.postings: dict[str, list[int]] = defaultdict(list)
        for position, counts in enumerate(self.frequencies):
            for token in counts:
                self.postings[token].append(position)

    def search(self, query_tokens: Sequence[str], limit: int) -> list[tuple[int, float]]:
        scores: dict[int, float] = defaultdict(float)
        for token in set(query_tokens):
            idf = self.idf.get(token)
            if idf is None:
                continue
            for position in self.postings.get(token, ()):
                frequency = self.frequencies[position].get(token, 0)
                norm = 1.0 - self.b + self.b * (
                    self.length[position] / self.average_length if self.average_length else 1.0
                )
                scores[position] += idf * (frequency * (self.k1 + 1.0)) / (frequency + self.k1 * norm)
        ranked = sorted(scores.items(), key=lambda item: -item[1])
        return ranked[:limit]


def _chunk_source(source: str, start_line: int) -> list[tuple[str, int, int]]:
    lines = source.splitlines()
    if not lines:
        return []
    if len(lines) <= SOURCE_CHUNK_LINES:
        return [(source, start_line, start_line + len(lines) - 1)]

    chunks: list[tuple[str, int, int]] = []
    step = SOURCE_CHUNK_LINES - SOURCE_CHUNK_OVERLAP
    for offset in range(0, len(lines), step):
        window = lines[offset : offset + SOURCE_CHUNK_LINES]
        if not window:
            break
        chunks.append(
            ("\n".join(window), start_line + offset, start_line + offset + len(window) - 1)
        )
        if offset + SOURCE_CHUNK_LINES >= len(lines):
            break
    return chunks


def build_documents(corpus: Corpus) -> list[Document]:
    """One summary document per function, plus source chunks and resources."""
    documents: list[Document] = []

    for function in corpus.iter_functions():
        processes = ", ".join(function.processes)
        header = (
            f"{function.name} — {function.file_name or '?'}"
            f"{f':{function.start_line}-{function.end_line}' if function.start_line > 0 else ''}"
            f" [{processes}]"
        )
        parts = [header, function.signature()]
        if function.summary:
            parts.append(function.summary)
        elif function.summary_hint:
            parts.append(function.summary_hint)
        if function.is_external:
            parts.append("external library boundary")

        documents.append(
            Document(
                id=f"summary:{function.id}",
                lane="summary",
                ref_kind="function",
                ref_id=function.id,
                text="\n".join(part for part in parts if part),
                process=function.processes[0] if function.processes else None,
                name=function.name,
                start_line=function.start_line,
                end_line=function.end_line,
            )
        )

        if function.has_source:
            for position, (text, start, end) in enumerate(
                _chunk_source(function.source or "", max(1, function.start_line))
            ):
                documents.append(
                    Document(
                        id=f"source:{function.id}:{position}",
                        lane="source",
                        ref_kind="function",
                        ref_id=function.id,
                        text=f"{function.name} ({function.file_name}:{start}-{end})\n{text}",
                        process=function.processes[0] if function.processes else None,
                        name=function.name,
                        start_line=start,
                        end_line=end,
                    )
                )

    for key, resource in corpus.resources.items():
        interactions = corpus.interactions_on(key)
        apis = sorted({item.target_api for item in interactions if item.target_api})
        operations = sorted({item.operation for item in interactions if item.operation})
        touching = sorted(
            {
                corpus.function(item.function_id).name
                for item in interactions
                if item.function_id and corpus.function(item.function_id)
            }
        )
        documents.append(
            Document(
                id=f"resource:{key}",
                lane="resource",
                ref_kind="resource",
                ref_id=key,
                text=(
                    f"{resource.kind} {resource.name} — daemon resource\n"
                    f"processes: {', '.join(resource.processes)}\n"
                    f"APIs: {', '.join(apis)}\n"
                    f"operations: {', '.join(operations)}\n"
                    f"touched by: {', '.join(touching[:24])}"
                ),
                process=resource.processes[0] if resource.processes else None,
                name=resource.name,
            )
        )

    return documents


class RetrievalIndex:
    """Built once per run selection, queried many times."""

    def __init__(
        self,
        corpus: Corpus,
        settings: Settings,
        embedder: EmbeddingClient | None = None,
        reranker: RerankClient | None = None,
    ) -> None:
        self.corpus = corpus
        self.settings = settings
        self.embedder = embedder
        self.reranker = reranker

        self.documents: list[Document] = []
        self.bm25: BM25 | None = None
        self._vectors: Any = None  # numpy array, or None
        self._vector_rows: list[int] = []  # index into self.documents
        self.embedded = 0
        self.error: str | None = None
        self._by_name: dict[str, list[str]] = defaultdict(list)

    # -------------------------------------------------------------- building

    def build(self, embed: bool = True) -> "RetrievalIndex":
        self.documents = build_documents(self.corpus)
        self.bm25 = BM25([tokenize(document.text) for document in self.documents])

        for function in self.corpus.iter_functions():
            self._by_name[function.name.lower()].append(function.id)
        for key, resource in self.corpus.resources.items():
            self._by_name[resource.name.lower()].append(key)

        if embed and self.embedder and self.embedder.available:
            self._build_vectors()
        return self

    def _build_vectors(self) -> None:
        try:
            import numpy
        except ImportError:
            self.error = "numpy not available; dense lanes disabled"
            return

        rows = [
            position
            for position, document in enumerate(self.documents)
            if document.lane in {"summary", "source", "resource"}
        ]
        vectors = self.embedder.embed_documents([self.documents[row].text for row in rows])  # type: ignore[union-attr]

        kept_rows: list[int] = []
        kept_vectors: list[list[float]] = []
        for row, vector in zip(rows, vectors):
            if vector:
                kept_rows.append(row)
                kept_vectors.append(vector)

        if not kept_vectors:
            self.error = self.embedder.last_error or "no document could be embedded"  # type: ignore[union-attr]
            return

        matrix = numpy.asarray(kept_vectors, dtype="float32")
        norms = numpy.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        self._vectors = matrix / norms
        self._vector_rows = kept_rows
        self.embedded = len(kept_rows)

    @property
    def ready(self) -> bool:
        return self.bm25 is not None

    @property
    def has_dense(self) -> bool:
        return self._vectors is not None

    def stats(self) -> dict[str, Any]:
        lanes: dict[str, int] = defaultdict(int)
        for document in self.documents:
            lanes[document.lane] += 1
        return {
            "documents": len(self.documents),
            "lanes": dict(lanes),
            "embedded": self.embedded,
            "dense": self.has_dense,
            "reranker": bool(self.reranker and self.reranker.available),
            "error": self.error,
        }

    # --------------------------------------------------------------- queries

    def search(self, query: str, limit: int | None = None, process: str | None = None) -> list[Hit]:
        """Fused, reranked retrieval. Returns hits keyed by function/resource."""
        limit = limit or self.settings.rerank_top_k
        if not self.ready or not (query or "").strip():
            return []

        settings = self.settings
        contributions: dict[str, float] = defaultdict(float)
        lanes_by_ref: dict[str, set[str]] = defaultdict(set)
        evidence: dict[str, list[dict]] = defaultdict(list)

        def award(document: Document, rank: int, weight: float, lane: str) -> None:
            if process and document.process and document.process != process:
                return
            contributions[document.ref_id] += weight / (settings.rrf_k + rank)
            lanes_by_ref[document.ref_id].add(lane)
            if document.lane in {"source", "summary", "resource"} and len(evidence[document.ref_id]) < 3:
                evidence[document.ref_id].append(
                    {
                        "lane": document.lane,
                        "text": document.text[:900],
                        "start_line": document.start_line,
                        "end_line": document.end_line,
                    }
                )

        # lane 1 — BM25 over every document
        for rank, (position, _score) in enumerate(
            self.bm25.search(tokenize(query), settings.pool_bm25), start=1  # type: ignore[union-attr]
        ):
            award(self.documents[position], rank, settings.weight_bm25, "bm25")

        # lanes 2 and 3 — dense, summary and source scored separately so a
        # long body cannot crowd out a precise summary match
        if self.has_dense and self.embedder:
            query_vector = self.embedder.embed_query(query)
            if query_vector:
                self._dense_award(query_vector, award)

        # lane 4 — exact identifier match, which fusion alone under-ranks
        for token in set(tokenize(query)):
            for ref_id in self._by_name.get(token, ()):
                contributions[ref_id] += settings.weight_name_exact / (settings.rrf_k + 1)
                lanes_by_ref[ref_id].add("name")

        if not contributions:
            return []

        ranked = sorted(contributions.items(), key=lambda item: -item[1])[: settings.rerank_pool]
        hits = [
            hit
            for hit in (self._make_hit(ref_id, score, lanes_by_ref, evidence) for ref_id, score in ranked)
            if hit is not None
        ]
        return self._rerank(query, hits)[:limit]

    def _dense_award(self, query_vector: Sequence[float], award) -> None:
        import numpy

        vector = numpy.asarray(query_vector, dtype="float32")
        norm = float(numpy.linalg.norm(vector)) or 1.0
        similarities = self._vectors @ (vector / norm)

        settings = self.settings
        for lane, weight, pool in (
            ("summary", settings.weight_summary_vec, settings.pool_summary_vec),
            ("source", settings.weight_source_vec, settings.pool_source_vec),
            ("resource", settings.weight_summary_vec, settings.pool_summary_vec),
        ):
            candidates = [
                (position, float(similarities[position]))
                for position, row in enumerate(self._vector_rows)
                if self.documents[row].lane == lane
            ]
            candidates.sort(key=lambda item: -item[1])
            for rank, (position, _similarity) in enumerate(candidates[:pool], start=1):
                award(self.documents[self._vector_rows[position]], rank, weight, f"vec_{lane}")

    def _make_hit(self, ref_id: str, score: float, lanes, evidence) -> Hit | None:
        function = self.corpus.function(ref_id)
        if function is not None:
            return Hit(
                ref_kind="function",
                ref_id=ref_id,
                name=function.name,
                score=score,
                lanes=sorted(lanes.get(ref_id, ())),
                evidence=evidence.get(ref_id, []),
            )
        resource = self.corpus.resource(ref_id)
        if resource is not None:
            return Hit(
                ref_kind="resource",
                ref_id=ref_id,
                name=resource.key,
                score=score,
                lanes=sorted(lanes.get(ref_id, ())),
                evidence=evidence.get(ref_id, []),
            )
        return None

    def _rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        if not hits or not self.reranker or not self.reranker.available:
            return hits

        passages = []
        for hit in hits:
            if hit.ref_kind == "function":
                function = self.corpus.function(hit.ref_id)
                text = f"{function.name} ({function.location})\n{function.summary or function.signature()}" if function else hit.name
            else:
                text = hit.evidence[0]["text"] if hit.evidence else hit.name
            passages.append(text[:1800])

        scores = self.reranker.score(query, passages)
        if scores is None:
            # Endpoint down: keep fusion order rather than pretending every
            # candidate scored zero.
            return hits

        # Blend rather than replace.  Sorting on the cross-encoder alone loses
        # exact-identifier intent: asked for `scf_hist_save` it scored
        # `pg_hist_flush_buffer` 0.995 against the real `scf_hist_save` 0.992,
        # because both are plainly "about" history saving and the encoder has
        # no notion that the user typed one of them verbatim.  Fusion rank
        # knows, so it keeps a vote, and an exact name match keeps a bigger
        # one.
        best_fusion = max((hit.score for hit in hits), default=0.0) or 1.0
        for hit, score in zip(hits, scores):
            hit.rerank_score = score

        def blended(hit: Hit) -> float:
            fusion = hit.score / best_fusion
            exact = self.settings.weight_exact_bonus if "name" in hit.lanes else 0.0
            return (hit.rerank_score or 0.0) + self.settings.weight_fusion_prior * fusion + exact

        return sorted(hits, key=lambda hit: (-blended(hit), -hit.score))
