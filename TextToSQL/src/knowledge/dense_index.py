"""Deterministic local dense-vector index using signed feature hashing.

This encoder is dependency-free and reproducible. Its word and character
features provide a compact dense vector representation, but it is not a
learned semantic model and should not be described as one.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Iterable

ENCODER_VERSION = "signed-word-char-ngram-v1"
DEFAULT_DIMENSIONS = 512
WORD = re.compile(r"[a-z0-9]+", re.I)


class HashedNgramEncoder:
    def __init__(self, dimensions: int = DEFAULT_DIMENSIONS):
        if dimensions < 64:
            raise ValueError("dense vector dimensions must be at least 64")
        self.dimensions = dimensions

    def embed(self, text: str) -> tuple[float, ...]:
        vector = [0.0] * self.dimensions
        words = [word.casefold() for word in WORD.findall(text or "")]
        features: list[tuple[str, float]] = [(f"w:{word}", 1.0) for word in words]
        features.extend((f"b:{left}_{right}", 0.5) for left, right in zip(words, words[1:]))
        for word in words:
            padded = f"^{word}$"
            features.extend((f"c:{padded[i:i + 3]}", 0.25) for i in range(max(0, len(padded) - 2)))
        for feature, weight in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign * weight
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return tuple(vector)


def document_id(document: dict) -> str:
    return f"{document.get('kind', '')}:{document.get('name', '')}"


def _indexed_documents(documents: Iterable[dict]) -> list[dict]:
    return [doc for doc in documents if doc.get("kind") in {"table", "column", "metric", "business_term"}]


def corpus_sha256(documents: Iterable[dict]) -> str:
    selected = _indexed_documents(documents)
    return hashlib.sha256(json.dumps(selected, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()


def _json_sha256(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_dense_payload(documents: Iterable[dict], *, dimensions: int = DEFAULT_DIMENSIONS,
                        previous: dict | None = None, encoder=None) -> dict:
    encoder = encoder or HashedNgramEncoder(dimensions)
    encoder_dimensions = int(getattr(encoder, "dimensions", dimensions))
    if encoder_dimensions < 1:
        raise ValueError("dense encoder must report a positive dimension")
    if dimensions != DEFAULT_DIMENSIONS and dimensions != encoder_dimensions:
        raise ValueError("requested dimensions do not match the dense encoder")
    encoder_version = str(getattr(encoder, "encoder_version", ENCODER_VERSION))
    backend = str(getattr(encoder, "backend", "hashed_ngram_dense_v1"))
    if not encoder_version or not backend:
        raise ValueError("dense encoder must identify its backend and version")
    all_documents = list(documents)
    selected = _indexed_documents(all_documents)
    reusable = bool(previous and valid_payload(previous)
                    and previous.get("encoder_version") == encoder_version
                    and previous.get("dimensions") == encoder_dimensions
                    and previous.get("backend") == backend)
    previous_documents = {document_id(doc): doc for doc in previous.get("documents", [])} if reusable else {}
    previous_vectors = previous.get("vectors", {}) if previous and previous_documents else {}
    vectors = {}
    reused = 0
    for doc in selected:
        key = document_id(doc)
        if previous_documents.get(key) == doc and key in previous_vectors:
            vectors[key] = previous_vectors[key]
            reused += 1
        else:
            vector = list(encoder.embed(f"{doc.get('name', '')} {doc.get('text', '')}"))
            if len(vector) != encoder_dimensions or not all(
                    isinstance(value, (int, float)) and math.isfinite(value) for value in vector):
                raise ValueError(f"dense encoder returned an invalid vector for {key}")
            vectors[key] = vector
    corpus_digest = corpus_sha256(selected)
    index_version = "dense-" + hashlib.sha256(f"{encoder_version}:{encoder_dimensions}:{corpus_digest}".encode()).hexdigest()[:16]
    payload = {
        "backend": backend,
        "encoder_version": encoder_version,
        "dimensions": encoder_dimensions,
        "corpus_sha256": corpus_digest,
        "vectors_sha256": _json_sha256(vectors),
        "index_version": index_version,
        "vectors": vectors,
        "documents": selected,
        "reused_vector_count": reused,
        "rebuilt_vector_count": len(selected) - reused,
    }
    for attribute, field in (("model_id", "model_id"), ("revision", "model_revision")):
        value = getattr(encoder, attribute, None)
        if value is not None:
            payload[field] = str(value)
    return payload


def valid_payload(payload: dict) -> bool:
    if not isinstance(payload.get("backend"), str) or not payload.get("backend"):
        return False
    if not isinstance(payload.get("encoder_version"), str) or not payload.get("encoder_version"):
        return False
    dimensions = payload.get("dimensions")
    vectors = payload.get("vectors")
    documents = payload.get("documents")
    if (not isinstance(dimensions, int) or dimensions < 1 or not isinstance(vectors, dict)
            or not isinstance(documents, list) or not payload.get("index_version")
            or not payload.get("corpus_sha256")):
        return False
    expected_ids = {document_id(doc) for doc in documents}
    expected_index_version = "dense-" + hashlib.sha256(
        f"{payload['encoder_version']}:{dimensions}:{payload['corpus_sha256']}".encode()).hexdigest()[:16]
    return (set(vectors) == expected_ids
            and payload.get("corpus_sha256") == corpus_sha256(documents)
            and payload.get("index_version") == expected_index_version
            and payload.get("vectors_sha256") == _json_sha256(vectors)
            and all(isinstance(vector, list) and len(vector) == dimensions
                    and all(isinstance(v, (int, float)) and math.isfinite(v) for v in vector) for vector in vectors.values()))


def payload_matches_documents(payload: dict, documents: Iterable[dict]) -> bool:
    return valid_payload(payload) and payload.get("corpus_sha256") == corpus_sha256(documents)
