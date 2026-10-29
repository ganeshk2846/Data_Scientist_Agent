"""Optional, pinned, local-only open-source embedding and reranking models.

The optional runtime dependency is installed from requirements-embeddings.txt.
Model loading is local-only: downloading weights is an explicit environment
setup action, never an implicit onboarding side effect.
"""
from __future__ import annotations

import math
import os
import re
from pathlib import Path
from dataclasses import dataclass

EMBEDDING_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_MODEL_REVISION = "2a7cca6ad7605f3183bce07f677bda658059bbe9"
RERANKER_MODEL_ID = "cross-encoder/ms-marco-MiniLM-L6-v2"
RERANKER_MODEL_REVISION = "f130f2b05c9b70e021b4833afe43c6993e2c7563"
DEFAULT_MODEL_CACHE = str(Path.home() / ".cache" / "texttosql-models")


class ModelAssetsUnavailable(RuntimeError):
    """Pinned model files or their optional runtime are not available offline."""


class ModelConfigurationError(ValueError):
    """A model override is not explicitly pinned to an immutable revision."""


@dataclass(frozen=True)
class ModelPin:
    model_id: str
    revision: str

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", self.model_id or ""):
            raise ModelConfigurationError("model id must be an organization/repository identifier")
        if not re.fullmatch(r"[0-9a-f]{40}", self.revision or ""):
            raise ModelConfigurationError("model revision must be a full 40-character lowercase commit pin")


def configured_pin(kind: str, model_id: str, revision: str) -> ModelPin:
    """Read optional overrides; changing a model always requires its own full pin."""
    prefix = f"TEXTTOSQL_{kind.upper()}_MODEL"
    configured_id = os.environ.get(f"{prefix}_ID")
    configured_revision = os.environ.get(f"{prefix}_REVISION")
    if configured_id and not configured_revision:
        raise ModelConfigurationError(f"{prefix}_REVISION is required when overriding {prefix}_ID")
    if configured_revision and not configured_id:
        raise ModelConfigurationError(f"{prefix}_ID is required when overriding {prefix}_REVISION")
    return ModelPin(configured_id or model_id, configured_revision or revision)


def _cache_path(cache_folder: str | None) -> Path:
    return Path(cache_folder or os.environ.get("TEXTTOSQL_MODEL_CACHE") or DEFAULT_MODEL_CACHE)


def _require_cached_revision(cache: Path, pin: ModelPin) -> None:
    repo = "models--" + pin.model_id.replace("/", "--")
    snapshots = cache / repo / "snapshots" / pin.revision
    direct = cache / pin.model_id / pin.revision
    if not snapshots.is_dir() and not direct.is_dir():
        raise ModelAssetsUnavailable(
            f"Pinned model {pin.model_id}@{pin.revision} is not cached at {cache}; "
            "provision the exact revision, then rerun the documented model evaluation."
        )


class SentenceTransformerEmbedder:
    """384-dimensional encoder using a pinned local Sentence Transformers model."""

    backend = "sentence_transformers_dense_v1"

    def __init__(self, model, *, model_id: str = EMBEDDING_MODEL_ID,
                 revision: str = EMBEDDING_MODEL_REVISION):
        pin = ModelPin(model_id, revision)
        self.model = model
        self.model_id = pin.model_id
        self.revision = pin.revision
        self.encoder_version = f"{pin.model_id}@{pin.revision}"
        self.dimensions = int(model.get_sentence_embedding_dimension())
        if self.dimensions <= 0:
            raise ValueError("embedding model must report a positive dimension")

    @classmethod
    def load_local(cls, *, cache_folder: str | None = None, model_id: str | None = None,
                   revision: str | None = None):
        if (model_id is None) != (revision is None):
            raise ModelConfigurationError("model_id and revision overrides must be supplied together")
        pin = ModelPin(model_id, revision) if model_id is not None else configured_pin(
            "embedding", EMBEDDING_MODEL_ID, EMBEDDING_MODEL_REVISION)
        cache = _cache_path(cache_folder)
        _require_cached_revision(cache, pin)
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise ModelAssetsUnavailable(
                "Sentence Transformers runtime is missing; install requirements-embeddings.txt "
                "in an environment with approved package access."
            ) from error
        try:
            model = SentenceTransformer(pin.model_id, revision=pin.revision,
                                        cache_folder=str(cache), local_files_only=True,
                                        trust_remote_code=False)
        except (OSError, ValueError) as error:
            raise ModelAssetsUnavailable(
                f"Could not load pinned embedding {pin.model_id}@{pin.revision} from local cache {cache}: {error}"
            ) from error
        return cls(model, model_id=pin.model_id, revision=pin.revision)

    def embed(self, text: str) -> tuple[float, ...]:
        vector = self.model.encode(
            text, normalize_embeddings=True, convert_to_numpy=True,
            show_progress_bar=False,
        )
        result = tuple(float(value) for value in vector)
        if len(result) != self.dimensions or not all(math.isfinite(value) for value in result):
            raise ValueError("embedding model returned an invalid vector")
        return result


class CrossEncoderReranker:
    """Pinned local cross-encoder adapter for the existing reranker interface."""

    def __init__(self, model, *, model_id: str = RERANKER_MODEL_ID,
                 revision: str = RERANKER_MODEL_REVISION):
        self.model = model
        self.model_id = model_id
        self.revision = revision

    @classmethod
    def load_local(cls, *, cache_folder: str | None = None, model_id: str | None = None,
                   revision: str | None = None):
        if (model_id is None) != (revision is None):
            raise ModelConfigurationError("model_id and revision overrides must be supplied together")
        pin = ModelPin(model_id, revision) if model_id is not None else configured_pin(
            "reranker", RERANKER_MODEL_ID, RERANKER_MODEL_REVISION)
        cache = _cache_path(cache_folder)
        _require_cached_revision(cache, pin)
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as error:
            raise ModelAssetsUnavailable(
                "Sentence Transformers runtime is missing; install requirements-embeddings.txt "
                "in an environment with approved package access."
            ) from error
        try:
            model = CrossEncoder(pin.model_id, revision=pin.revision, cache_folder=str(cache),
                                 local_files_only=True, trust_remote_code=False)
        except (OSError, ValueError) as error:
            raise ModelAssetsUnavailable(
                f"Could not load pinned reranker {pin.model_id}@{pin.revision} from local cache {cache}: {error}"
            ) from error
        return cls(model, model_id=pin.model_id, revision=pin.revision)

    def score(self, query: str, document: str) -> float:
        values = self.model.predict([(query, document)], show_progress_bar=False)
        if hasattr(values, "tolist"):
            values = values.tolist()
        score = float(values[0] if isinstance(values, (list, tuple)) else values)
        if not math.isfinite(score):
            raise ValueError("reranker returned a non-finite score")
        return score
