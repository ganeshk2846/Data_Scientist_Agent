"""Catalog-backed keyword/dense schema and value retrieval for TextToSQL.

Persisted local hashed n-gram vectors provide a deterministic dense-vector
baseline. Learned embedders and cross-encoders remain optional adapters.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Protocol

from knowledge.catalog_api import CatalogAPI
from knowledge.dense_index import (
    ENCODER_VERSION,
    HashedNgramEncoder,
    document_id,
    payload_matches_documents,
)

WORD = re.compile(r"[\w]+", re.UNICODE)
TRIGRAM_MIN_SCORE = 0.65
CONFIDENCE_THRESHOLD = 0.65
# Monotone piecewise-linear anchors fitted on the labeled local retrieval fixture.
# Raw RRF scores are rank-fusion values, not probabilities.
CONFIDENCE_ANCHORS = (
    (0.0, 0.0),
    (0.25, 0.45),
    (0.45, 0.65),
    (0.50, 0.72),
    (0.75, 0.88),
    (1.0, 0.97),
)
CONTEXT_TOKEN_BUDGET = 1800  # conservative estimate; leave margin under 2,000


def calibrate_confidence(raw_score: float) -> float:
    score = min(1.0, max(0.0, float(raw_score)))
    for (left_x, left_y), (right_x, right_y) in zip(
        CONFIDENCE_ANCHORS, CONFIDENCE_ANCHORS[1:]
    ):
        if score <= right_x:
            span = right_x - left_x
            return left_y + (right_y - left_y) * (
                (score - left_x) / span if span else 0.0
            )
    return CONFIDENCE_ANCHORS[-1][1]


class Embedder(Protocol):
    def embed(self, text: str) -> tuple[float, ...]: ...


class Reranker(Protocol):
    def score(self, query: str, document: str) -> float: ...


@dataclass(frozen=True)
class RetrievedContext:
    schema: dict[str, list[str]]
    text: str
    tables: tuple[str, ...]
    columns: tuple[str, ...]
    approved_joins: tuple[dict, ...]
    warnings: tuple[dict, ...]
    confidence: float
    estimated_tokens: int
    retrieval_mode: str
    needs_clarification: bool = False
    clarification: str | None = None


def _tokens(text: str) -> set[str]:
    parts = WORD.findall(text.replace("_", " ").replace(".", " "))
    normalized = set()
    for part in parts:
        word = part.casefold()
        normalized.add(word)
        if len(word) > 4 and word.endswith("ies"):
            normalized.add(word[:-3] + "y")
        elif len(word) > 4 and word.endswith("s"):
            normalized.add(word[:-1])
    return normalized


def _expand_synonyms(words: set[str], documents: list[dict]) -> set[str]:
    expanded = set(words)
    for document in documents:
        if document.get("kind") != "business_term":
            continue
        aliases = {
            token
            for phrase in document.get("synonyms", [])
            for token in _tokens(str(phrase))
        }
        if words & aliases:
            expanded |= _tokens(str(document.get("name", "")))
    return expanded


def _grams(text: str) -> set[str]:
    normalized = "  " + " ".join(WORD.findall(text.casefold())) + "  "
    return {
        normalized[index : index + 3] for index in range(max(0, len(normalized) - 2))
    }


def _similarity(left: str, right: str) -> float:
    if left.casefold().strip() == right.casefold().strip():
        return 1.0
    a, b = _grams(left), _grams(right)
    return 2 * len(a & b) / max(1, len(a) + len(b))


class ValueIndex:
    """Exact and trigram lookup over the masked catalog's categorical index."""

    def __init__(
        self, catalog: CatalogAPI, *, minimum_confidence: float = TRIGRAM_MIN_SCORE
    ):
        self.minimum_confidence = minimum_confidence
        self.values: list[tuple[str, str]] = []
        try:
            index = catalog.index()
            masked = set(index.get("sensitive_columns", []))
            profiles = catalog.data.get("profiles", {})
            for column, values in index.get("value_index", {}).items():
                table, name = column.split(".", 1)
                if column in masked or profiles.get(table, {}).get("columns", {}).get(
                    name, {}
                ).get("sensitive"):
                    continue
                self.values.extend(
                    (column, str(value)) for value in values if value is not None
                )
        except (FileNotFoundError, KeyError, ValueError):
            pass

    def link(
        self, phrase: str, column_hint: str | None = None, *, limit: int = 5
    ) -> list[dict]:
        ranked = []
        for column, literal in self.values:
            if column_hint and column != column_hint:
                continue
            score = _similarity(phrase, literal)
            if score:
                table, name = column.split(".", 1)
                ranked.append(
                    {
                        "table": table,
                        "column": name,
                        "literal": literal,
                        "confidence": round(score, 4),
                    }
                )
        return sorted(
            ranked,
            key=lambda item: (
                -item["confidence"],
                item["table"],
                item["column"],
                item["literal"],
            ),
        )[:limit]


class SchemaRetriever:
    """Keyword/dense RRF retrieval, approved-join expansion and bounded pruning."""

    def __init__(
        self,
        catalog: CatalogAPI,
        *,
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
        rrf_k: int = 60,
        minimum_score: float = 0.01,
        token_budget: int = CONTEXT_TOKEN_BUDGET,
        use_dense: bool = True,
    ):
        if rrf_k < 1 or token_budget < 1:
            raise ValueError("rrf_k and token_budget must be positive")
        self.catalog = catalog
        self._model_failure: str | None = None
        try:
            index_data = catalog.index()
            dense_payload = index_data.get("dense", {})
            keyword_documents = index_data.get("keyword", [])
        except (FileNotFoundError, KeyError, ValueError, TypeError):
            dense_payload = {}
            keyword_documents = []
        self._dense_payload = dense_payload
        self._keyword_documents = keyword_documents
        if (
            use_dense
            and embedder is None
            and dense_payload.get("backend") == "sentence_transformers_dense_v1"
        ):
            try:
                from knowledge.semantic_models import SentenceTransformerEmbedder

                embedder = SentenceTransformerEmbedder.load_local()
            except RuntimeError as error:
                # Learned weights/dependency are optional locally. A missing
                # model disables dense retrieval rather than substituting a
                # different encoder against incompatible persisted vectors.
                self._model_failure = str(error)
                embedder = None
        if use_dense and embedder is not None:
            saved_version = dense_payload.get("encoder_version")
            query_version = getattr(embedder, "encoder_version", None)
            if saved_version and query_version and saved_version != query_version:
                raise ValueError(
                    "configured embedding model does not match the persisted dense index"
                )
        self.embedder = embedder if use_dense else None
        payload_valid = use_dense and payload_matches_documents(
            dense_payload, keyword_documents
        )
        if self.embedder is None:
            self._persisted_dense = (
                dense_payload
                if payload_valid
                and dense_payload.get("backend") == "hashed_ngram_dense_v1"
                and dense_payload.get("encoder_version") == ENCODER_VERSION
                else None
            )
            self._dense_encoder = (
                HashedNgramEncoder(dense_payload["dimensions"])
                if self._persisted_dense
                else None
            )
        else:
            query_version = getattr(self.embedder, "encoder_version", None)
            can_reuse = bool(
                payload_valid
                and query_version
                and dense_payload.get("encoder_version") == query_version
            )
            self._persisted_dense = dense_payload if can_reuse else None
            self._dense_encoder = self.embedder
        self.reranker = reranker
        self._reranker_failure: str | None = None
        self._rrf_k = rrf_k
        self.minimum_score = minimum_score
        self.token_budget = min(token_budget, CONTEXT_TOKEN_BUDGET)

    @property
    def mode(self) -> str:
        if self.embedder is not None:
            base = "hybrid_learned"
        elif self._persisted_dense:
            base = "hybrid_hashed_fallback" if self._model_failure else "hybrid_hashed"
        else:
            base = (
                "keyword_only_fallback"
                if self._model_failure
                else "keyword_only_dense_unavailable"
            )
        if self._reranker_failure:
            return f"{base}_reranker_fallback"
        return f"{base}_reranked" if self.reranker is not None else base

    @property
    def rrf_k(self) -> int:
        return self._rrf_k

    def _rank(self, query: str) -> list[tuple[str, float, dict]]:
        try:
            documents = self.catalog.index().get("keyword", [])
        except (OSError, KeyError, TypeError, ValueError):
            # A partial publication or unreadable index must not fall back to
            # uncatalogued schema; retrieval clarifies instead.
            return []
        words = _expand_synonyms(_tokens(query), documents)
        keyword = []
        for doc in documents:
            if doc.get("kind") not in {"table", "column", "metric", "business_term"}:
                continue
            text = f"{doc.get('name', '')} {doc.get('text', '')}"
            doc_words = _tokens(text)
            overlap = len(words & doc_words)
            if overlap:
                score = overlap / max(1, len(words))
                keyword.append((doc, score))
        keyword.sort(key=lambda row: (-row[1], row[0].get("name", "")))
        fused: dict[str, float] = {}
        records: dict[str, dict] = {}
        sources: list[list[tuple[dict, float]]] = [keyword]
        dense = []
        if self.embedder or self._persisted_dense:
            try:
                encoder = self.embedder or self._dense_encoder
                qvec = _validated_embedding(encoder, query)
                for doc in documents:
                    if doc.get("kind") not in {
                        "table",
                        "column",
                        "metric",
                        "business_term",
                    }:
                        continue
                    if self._persisted_dense:
                        dvec = self._persisted_dense["vectors"].get(document_id(doc))
                        if dvec is None:
                            continue
                    else:
                        dvec = _validated_embedding(
                            encoder, f"{doc.get('name', '')} {doc.get('text', '')}"
                        )
                    score = _cosine(qvec, dvec)
                    if score > 0:
                        dense.append((doc, score))
                dense.sort(key=lambda row: (-row[1], row[0].get("name", "")))
                sources.append(dense)
            except Exception as error:
                # An optional model failure must never turn into a random or
                # partially ranked result. Disable it for this retriever and
                # restart ranking from the deterministic local fallback.
                self._model_failure = f"embedding runtime failed ({type(error).__name__}); using deterministic lexical retrieval"
                self.embedder = None
                dense_payload = self._dense_payload
                keyword_documents = self._keyword_documents
                hashed_valid = (
                    payload_matches_documents(dense_payload, keyword_documents)
                    and dense_payload.get("backend") == "hashed_ngram_dense_v1"
                    and dense_payload.get("encoder_version") == ENCODER_VERSION
                )
                self._persisted_dense = dense_payload if hashed_valid else None
                self._dense_encoder = (
                    HashedNgramEncoder(dense_payload["dimensions"])
                    if hashed_valid
                    else None
                )
                return self._rank(query)
        normalizer = len(sources) / (self.rrf_k + 1)
        for source in sources:
            for rank, (doc, score) in enumerate(source, 1):
                key = doc.get("name", "")
                fused[key] = fused.get(key, 0) + (1 / (self.rrf_k + rank)) / normalizer
                records[key] = doc
        result = []
        for key, score in fused.items():
            doc = records[key]
            table = (
                key
                if doc.get("kind") == "table"
                else key.split(".", 1)[0]
                if doc.get("kind") == "column"
                else None
            )
            trust = self.catalog.data.get("trust", {}).get(table, {}) if table else {}
            if trust.get("likely_stale_copy"):
                score *= 0.5
            elif (
                trust.get("freshness_days") is not None
                and trust["freshness_days"] <= 14
            ):
                score *= 1.1
            result.append((key, score, doc))
        result.sort(key=lambda row: (-row[1], row[0]))
        if self.reranker:
            try:
                reranked = []
                for row in result:
                    score = float(self.reranker.score(query, row[2].get("text", "")))
                    if not math.isfinite(score):
                        raise ValueError("reranker returned a non-finite score")
                    reranked.append((score, row))
            except Exception as error:
                # Keep the deterministic RRF ranking available if the optional
                # reranker fails at runtime; expose the degraded mode to callers.
                self._reranker_failure = type(error).__name__
            else:
                result = [
                    row
                    for _, row in sorted(
                        reranked, key=lambda item: (-item[0], -item[1][1], item[1][0])
                    )
                ]
        return result

    def retrieve(
        self, query: str, *, quoted_values: list[str] | None = None
    ) -> RetrievedContext:
        catalog = self.catalog.data
        raw_ranked = self._rank(query)
        warnings = self._runtime_warnings()
        ranked = [
            (name, score, doc)
            for name, score, doc in raw_ranked
            if score >= self.minimum_score
        ]
        if not ranked:
            return RetrievedContext(
                {},
                "",
                (),
                (),
                (),
                tuple(warnings),
                0.0,
                0,
                self.mode,
                True,
                "I could not confidently identify a relevant table or column. Please clarify the requested data.",
            )
        confidence = calibrate_confidence(ranked[0][1])
        if confidence < CONFIDENCE_THRESHOLD:
            return RetrievedContext(
                {},
                "",
                (),
                (),
                (),
                tuple(warnings),
                confidence,
                0,
                self.mode,
                True,
                "I could not confidently identify a relevant table or column. Please clarify the requested data.",
            )
        tables: list[str] = []
        selected_columns: dict[str, set[str]] = {}
        for name, _, doc in ranked:
            table = doc.get("table") or (
                name
                if doc.get("kind") == "table"
                else name.split(".", 1)[0]
                if doc.get("kind") == "column" and "." in name
                else None
            )
            if table in catalog["tables"] and table not in tables:
                tables.append(table)
            if doc.get("kind") == "column" and table in catalog["tables"]:
                selected_columns.setdefault(table, set()).add(name.split(".", 1)[-1])
        if not tables:
            return RetrievedContext(
                {},
                "",
                (),
                (),
                (),
                tuple(warnings),
                0.0,
                0,
                self.mode,
                True,
                "The catalog did not identify a usable table. Please clarify the requested data.",
            )
        tables = tables[:6]
        # Add connector tables only through a shortest path made entirely of approved joins.
        expanded = list(tables)
        joins = []
        for i, left in enumerate(tables):
            for right in tables[i + 1 :]:
                path = self.catalog.paths(left, right, approved_only=True)
                if not path:
                    continue
                for edge in path:
                    if edge not in joins:
                        joins.append(edge)
                    for endpoint in (edge["left"]["table"], edge["right"]["table"]):
                        if endpoint not in expanded:
                            expanded.append(endpoint)
        schema: dict[str, list[str]] = {}
        context_lines = []
        warnings = list(warnings)
        used_columns = []
        for table in expanded:
            table_entry = catalog["tables"][table]
            columns = table_entry.get("columns", [])
            primary = {col["name"] for col in columns if col.get("primary_key")}
            foreign = {
                col["name"]
                for col in columns
                if any(
                    fk.get("column") == col["name"]
                    for fk in table_entry.get("foreign_keys", [])
                )
            }
            chosen = selected_columns.get(table, set()) | primary | foreign
            # If lexical retrieval selected only the table name, permit only keys; do not disclose full schema.
            if not chosen:
                chosen = set()
            profile = catalog.get("profiles", {}).get(table, {}).get("columns", {})
            visible = [
                col
                for col in columns
                if col["name"] in chosen
                and not profile.get(col["name"], {}).get("sensitive")
            ]
            schema[table] = [col["name"] for col in visible]
            table_line = f"TABLE {table}: " + ", ".join(
                f"{col['name']} ({col.get('type') or 'unknown'})" for col in visible
            )
            description_entry = catalog.get("descriptions", {}).get(table, {})
            description = (
                description_entry.get("text")
                if description_entry.get("status") == "approved"
                else None
            )
            if description:
                table_line += f"; description: {description}"
            context_lines.append(table_line)
            for col in visible:
                used_columns.append(f"{table}.{col['name']}")
                stats = profile.get(col["name"], {})
                col_warnings = []
                if stats.get("null_rate", 0) >= 0.2:
                    col_warnings.append(f"high null share ({stats['null_rate']:.0%})")
                formats = stats.get("formats", [])
                if len(formats) > 1:
                    col_warnings.append("mixed formats: " + ", ".join(formats))
                if re.search(
                    r"(^|_)(deleted|is_deleted|deleted_at|is_active|active)(_|$)",
                    col["name"],
                    re.IGNORECASE,
                ):
                    col_warnings.append(
                        "possible soft-delete/active flag; confirm filter semantics"
                    )
                if col_warnings:
                    warnings.append(
                        {"column": f"{table}.{col['name']}", "warnings": col_warnings}
                    )
                    context_lines.append(
                        f"WARNING {table}.{col['name']}: " + "; ".join(col_warnings)
                    )
        # A real encoder tokenizer is not configured; this conservative character estimate
        # reserves 10% under the spec limit and never silently truncates identifiers.
        if sum(_estimated_tokens(line) for line in context_lines) > self.token_budget:
            return RetrievedContext(
                {},
                "",
                tuple(tables),
                (),
                tuple(joins),
                tuple(warnings),
                confidence,
                sum(_estimated_tokens(line) for line in context_lines),
                self.mode,
                True,
                "The relevant schema exceeds the safe context budget. Please narrow the question.",
            )
        context = "\n".join(context_lines)
        if joins:
            context += "\nAPPROVED JOIN EDGES: " + "; ".join(
                _edge_text(edge) for edge in joins
            )
        if _estimated_tokens(context) > self.token_budget:
            return RetrievedContext(
                {},
                "",
                tuple(expanded),
                (),
                tuple(joins),
                tuple(warnings),
                confidence,
                _estimated_tokens(context),
                self.mode,
                True,
                "The relevant schema exceeds the safe context budget. Please narrow the question.",
            )
        if quoted_values:
            index = ValueIndex(self.catalog)
            for phrase in quoted_values:
                matches = index.link(phrase)
                if not matches or matches[0]["confidence"] < TRIGRAM_MIN_SCORE:
                    return RetrievedContext(
                        schema,
                        context,
                        tuple(tables),
                        tuple(used_columns),
                        tuple(joins),
                        tuple(warnings),
                        confidence,
                        _estimated_tokens(context),
                        self.mode,
                        True,
                        f"I could not confidently match {phrase!r}. Which catalog value did you mean?",
                    )
                context += "\nVALUE MATCH: " + json_line(matches[0])
                if _estimated_tokens(context) > self.token_budget:
                    return RetrievedContext(
                        {},
                        "",
                        tuple(expanded),
                        (),
                        tuple(joins),
                        tuple(warnings),
                        confidence,
                        _estimated_tokens(context),
                        self.mode,
                        True,
                        "The relevant schema and value evidence exceed the safe context budget. Please narrow the question.",
                    )
        return RetrievedContext(
            schema,
            context,
            tuple(expanded),
            tuple(used_columns),
            tuple(joins),
            tuple(warnings),
            confidence,
            _estimated_tokens(context),
            self.mode,
        )

    def _runtime_warnings(self) -> list[dict]:
        warnings = []
        if self._model_failure:
            warnings.append({"retrieval": self._model_failure})
        if self._reranker_failure:
            warnings.append(
                {
                    "retrieval": f"reranker failed; retained RRF ranking ({self._reranker_failure})"
                }
            )
        return warnings


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norms = math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))
    return max(0.0, dot / norms) if norms else 0.0


def _validated_embedding(encoder, text: str) -> tuple[float, ...]:
    vector = tuple(float(value) for value in encoder.embed(text))
    expected = getattr(encoder, "dimensions", None)
    if (
        not vector
        or (expected is not None and len(vector) != int(expected))
        or not all(math.isfinite(value) for value in vector)
    ):
        raise ValueError(
            "embedding returned an invalid vector shape or non-finite value"
        )
    return vector


def _estimated_tokens(text: str) -> int:
    # Four chars/token is a conservative rough estimate for English and identifiers.
    return math.ceil(len(text) / 4)


def _edge_text(edge: dict) -> str:
    left, right = edge["left"], edge["right"]
    left_cols = ",".join(left.get("columns", [left.get("column")]))
    right_cols = ",".join(right.get("columns", [right.get("column")]))
    return f"{left['table']}.{left_cols}={right['table']}.{right_cols} ({edge['cardinality']})"


def json_line(value: dict) -> str:
    import json

    return json.dumps(value, ensure_ascii=True, sort_keys=True)
