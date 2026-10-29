from src.onboarding.health import health_report


def test_health_report_is_local_secret_safe_and_distinguishes_optional_dependencies(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "do-not-print-this-value")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "model-name")
    monkeypatch.setenv("TEXTTOSQL_MODEL_CACHE", str(tmp_path / "empty-model-cache"))
    report = health_report(tmp_path)
    rendered = str(report)
    assert report["ready"] is True
    assert report["llm"]["configured"] is True
    assert report["optional_models"]["embedding"]["weights_cached"] is False
    assert report["optional_models"]["embedding"]["revision_pinned"] is True
    assert "do-not-print-this-value" not in rendered
    assert "network" in report["scope"]


def test_health_report_rejects_partial_model_override(tmp_path, monkeypatch):
    monkeypatch.setenv("TEXTTOSQL_EMBEDDING_MODEL_ID", "custom/model")
    monkeypatch.delenv("TEXTTOSQL_EMBEDDING_MODEL_REVISION", raising=False)
    report = health_report(tmp_path)
    assert report["optional_models"]["embedding"]["revision_pinned"] is False


def test_health_report_flags_invalid_llm_timeout_without_printing_values(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CONNECT_TIMEOUT_SECONDS", "nan")
    report = health_report(tmp_path)
    assert report["llm"]["runtime_options_valid"] is False
