from src.onboarding.scale_report import collect_scale_report, render_markdown


def test_scale_report_records_environment_and_dense_vectors():
    result = collect_scale_report((50,), seed=7)
    run = result["runs"][0]
    assert run["tables"] == 50
    assert run["dense_vectors"] > 0
    assert run["self_test_passed"] is True
    assert run["status"] in {"complete", "needs_review"}
    assert result["environment"]["python"]
    assert result["environment"]["platform"]
    assert result["cost"]["measured"] is False
    assert result["cost"]["estimated_cost_usd"] is None

    markdown = render_markdown(result)
    assert "# BE-2 local scale report" in markdown
    assert "| 50 |" in markdown
    assert "python -m src.onboarding.scale_report --sizes 50 200 500" in markdown
