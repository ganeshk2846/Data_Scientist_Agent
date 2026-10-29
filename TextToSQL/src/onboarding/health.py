"""Local readiness checks for BE-2 startup; no network calls or secret output."""
from __future__ import annotations

import importlib.util
import math
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from src.knowledge.semantic_models import (DEFAULT_MODEL_CACHE, EMBEDDING_MODEL_ID,
                                          EMBEDDING_MODEL_REVISION, RERANKER_MODEL_ID,
                                          RERANKER_MODEL_REVISION, ModelConfigurationError,
                                          ModelAssetsUnavailable, configured_pin,
                                          _require_cached_revision)


def health_report(root: str | Path | None = None) -> dict:
    data_root = Path(root or os.environ.get("TEXTTOSQL_DATA_ROOT") or Path.cwd()).resolve()
    checks = {
        "python_supported": sys.version_info >= (3, 11),
        "sqlite_available": importlib.util.find_spec("sqlite3") is not None,
        "data_root_exists": data_root.is_dir(),
        "data_root_writable": data_root.is_dir() and os.access(data_root, os.W_OK),
    }
    model_cache = Path(os.environ.get("TEXTTOSQL_MODEL_CACHE", DEFAULT_MODEL_CACHE))
    models = {}
    for name, model_id, revision in (
        ("embedding", EMBEDDING_MODEL_ID, EMBEDDING_MODEL_REVISION),
        ("reranker", RERANKER_MODEL_ID, RERANKER_MODEL_REVISION),
    ):
        try:
            pin = configured_pin(name, model_id, revision)
        except ModelConfigurationError as error:
            models[name] = {"weights_cached": False, "runtime_available": importlib.util.find_spec("sentence_transformers") is not None,
                            "revision_pinned": False, "reason": str(error)}
        else:
            try:
                _require_cached_revision(model_cache, pin)
                cached, reason = True, None
            except ModelAssetsUnavailable as error:
                cached, reason = False, str(error)
            models[name] = {"weights_cached": cached,
                            "runtime_available": importlib.util.find_spec("sentence_transformers") is not None,
                            "revision_pinned": True}
            if reason:
                models[name]["reason"] = reason
        if not models[name].get("runtime_available") and "reason" not in models[name]:
            models[name]["reason"] = "optional sentence-transformers runtime is not installed"
    base_url = os.environ.get("LLM_BASE_URL", "")
    parsed = urlparse(base_url) if base_url else None
    llm_valid_url = bool(parsed and parsed.scheme in {"http", "https"} and parsed.netloc
                         and (parsed.scheme == "https" or parsed.hostname in {"localhost", "127.0.0.1", "::1"}))
    api_key = os.environ.get("LLM_API_KEY", "")
    key_configured = bool(api_key and not api_key.startswith(("sk-your-", "sk-or-...")))
    model_configured = bool(os.environ.get("LLM_MODEL", "qwen-plus").strip())
    try:
        retries_valid = 1 <= int(os.environ.get("LLM_MAX_ATTEMPTS", "3")) <= 10
        connect_valid = 0 < float(os.environ.get("LLM_CONNECT_TIMEOUT_SECONDS", "5")) <= 3600
        read_valid = 0 < float(os.environ.get("LLM_READ_TIMEOUT_SECONDS", "30")) <= 3600
        timing_valid = all(math.isfinite(float(os.environ.get(name, default))) for name, default in (
            ("LLM_CONNECT_TIMEOUT_SECONDS", "5"), ("LLM_READ_TIMEOUT_SECONDS", "30")))
    except ValueError:
        retries_valid = connect_valid = read_valid = timing_valid = False
    llm = {"configured": bool(llm_valid_url and key_configured and model_configured
                                and retries_valid and connect_valid and read_valid and timing_valid),
           "url_valid": llm_valid_url,
           "api_key_configured": key_configured,
           "model_configured": model_configured,
           "runtime_options_valid": bool(retries_valid and connect_valid and read_valid and timing_valid)}
    scoring_count = len([item for item in os.environ.get("TEXTTOSQL_SCORING_PRINCIPALS", "").split(",") if item.strip()])
    return {"ready": all(checks.values()), "checks": checks, "data_root": str(data_root),
            "optional_models": models, "llm": llm,
            "scoring_principals_configured": scoring_count,
            "scope": "local configuration check only; no service/network, identity-provider, ACL, or deployment validation"}
