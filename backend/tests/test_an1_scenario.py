from __future__ import annotations

from analysts.scenario import ScenarioAnalyst
from contracts.models import AnalystInput
from contracts.v2 import ScenarioResult
from test_an1_elasticity import _price_tables


def test_price_scenario_is_seeded_fit_backed_and_has_all_disclosures():
    price, competitor = _price_tables()
    analyst_input = AnalystInput(
        module="scenario",
        params={"price_change_pct": 5.0},
        tables={
            "price_history": price,
            "competitor_prices": competitor,
        },
        run_id="RUN-SCENARIO",
        seed=23,
    )
    analyst = ScenarioAnalyst()

    first = analyst.run(analyst_input)
    second = analyst.run(analyst_input)

    assert first.status == "ok"
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert isinstance(first.result, ScenarioResult)
    assert first.result.synthetic_data is True
    assert first.result.price_change_pct == 5.0
    assert first.result.elasticity < 0.0
    assert first.result.elasticity_interval[0] <= first.result.elasticity <= first.result.elasticity_interval[1]
    assert first.result.r_squared > 0.99
    assert first.result.observations == price.row_count
    assert len(first.result.disclosures) == 5
    assert any("synthetic data" in item.lower() for item in first.result.disclosures)
    assert any("observational" in item.lower() for item in first.result.disclosures)
    assert len(first.result.sensitivity) >= 2
    assert first.result.revenue_delta_interval[0] <= first.result.revenue_delta_interval[1]
    assert "Q-PRICE" in first.sources
    assert "Q-COMPETITOR" in first.sources


def test_price_scenario_refuses_only_when_fit_inputs_are_missing():
    output = ScenarioAnalyst().run(
        AnalystInput(
            module="scenario",
            params={"price_change_pct": 5.0},
            tables={},
            run_id="RUN-NO-FIT",
            seed=1,
        )
    )

    assert output.status == "insufficient_evidence"
    assert output.result is None
    assert "price_history" in output.reason
    assert "competitor_prices" in output.reason
