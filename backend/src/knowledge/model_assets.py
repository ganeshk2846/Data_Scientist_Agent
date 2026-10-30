"""Explicit downloader for the pinned Apache-2.0 BE-2 local models.

This command is intentionally never called by onboarding. It needs network
access and downloads public model weights only when an operator explicitly
runs it. No Hub token is used or read.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .semantic_models import (
    DEFAULT_MODEL_CACHE,
    EMBEDDING_MODEL_ID,
    EMBEDDING_MODEL_REVISION,
    RERANKER_MODEL_ID,
    RERANKER_MODEL_REVISION,
    configured_pin,
)


def download_models(
    cache_dir: str | Path, *, include_reranker: bool = True
) -> list[dict[str, str]]:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as error:
        raise RuntimeError(
            "Install requirements-embeddings.txt before downloading model assets"
        ) from error
    cache = Path(cache_dir).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    embedding = configured_pin(
        "embedding", EMBEDDING_MODEL_ID, EMBEDDING_MODEL_REVISION
    )
    assets = [(embedding.model_id, embedding.revision)]
    if include_reranker:
        reranker = configured_pin(
            "reranker", RERANKER_MODEL_ID, RERANKER_MODEL_REVISION
        )
        assets.append((reranker.model_id, reranker.revision))
    downloaded = []
    for model_id, revision in assets:
        try:
            path = snapshot_download(
                repo_id=model_id,
                revision=revision,
                cache_dir=str(cache),
                token=False,
                local_files_only=False,
            )
        except Exception as error:
            raise RuntimeError(
                f"Could not provision pinned model {model_id}@{revision}; verify approved network access "
                "or supply the exact revision in the model cache. No model-quality evaluation was run."
            ) from error
        downloaded.append(
            {"model_id": model_id, "revision": revision, "path": str(path)}
        )
    return downloaded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir",
        default=os.environ.get("TEXTTOSQL_MODEL_CACHE", DEFAULT_MODEL_CACHE),
    )
    parser.add_argument("--without-reranker", action="store_true")
    args = parser.parse_args()
    for asset in download_models(
        args.cache_dir, include_reranker=not args.without_reranker
    ):
        print(f"READY {asset['model_id']}@{asset['revision']} at {asset['path']}")


if __name__ == "__main__":
    main()
