"""Scenario engine: price change from the question, elasticity fit, Monte Carlo, sensitivity."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from contracts.v2 import ScenarioResult
from engine_helpers import assert_complete_report, data, stable, table

from engines import scenario
from engines.scenario import price_change_from_question

TRUE_ELASTICITY = -1.3


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What if we raise prices by 10%?", 10.0),
        ("what happens if we increase the price 5.5%", 5.5),
        ("cut prices by 15 percent", -15.0),
        ("a 7% price increase", 7.0),
        ("an 8% price cut on furniture", -8.0),
        ("price +12%", 12.0),
        ("e se aumentar preços em 10%?", 10.0),
    ],
)
def test_price_change_is_read_from_the_question(question, expected):
    assert price_change_from_question(question) == pytest.approx(expected)


def test_no_price_change_is_not_invented():
    assert price_change_from_question("what if competitors react?") is None
    run = scenario.execute({"question": "what if competitors react?"}, data({}))
    assert run.result.status == "insufficient_evidence"


def _sales(seed=2):
    """Category-day panel with independent list-price steps and a known elasticity."""
    rng = np.random.default_rng(seed)
    days = pd.date_range("2016-09-01", "2018-08-31", freq="D")
    rows, competitor = [], []
    for index, category in enumerate(("a", "b", "c", "d", "e", "f")):
        price = 50.0 + 10 * index
        steps = sorted(rng.choice(np.arange(30, len(days) - 30), size=6, replace=False))
        multipliers = rng.uniform(0.85, 1.15, size=6)
        level = np.ones(len(days))
        for step, multiplier in zip(steps, multipliers, strict=True):
            level[step:] *= multiplier
        for offset, day in enumerate(days):
            list_price = price * level[offset]
            demand = 20.0 * level[offset] ** TRUE_ELASTICITY * (1 + 0.1 * np.sin(offset / 30.0))
            rows.append((day.date().isoformat(), category, int(rng.poisson(demand)), 0, list_price, 0.0, list_price))
            if offset % 7 == 0:
                competitor.append((day.date().isoformat(), category, price * rng.lognormal(0.0, 0.03)))
    sales = pd.DataFrame(rows, columns=["date", "category", "quantity", "stockout_flag", "list_price", "discount_pct", "price"])
    return sales, pd.DataFrame(competitor, columns=["date", "category", "competitor_price"])


@pytest.fixture(scope="module")
def run():
    sales, competitor = _sales()
    tables = {"sales": table(sales, "Q-SALES", date="time"), "competitor": table(competitor, "Q-COMP", date="time"),
              "baseline": table(pd.DataFrame({"revenue": [100000.0]}), "Q-BASE")}
    return scenario.execute({"question": "What happens to revenue if we raise prices by 10%?"},
                            data(tables, sources=("price_history", "inventory_daily", "competitor_prices"), seed=13))


def test_elasticity_is_recovered_with_interval_and_all_disclosures(run):
    result = run.result.analyst_output.result
    assert isinstance(result, ScenarioResult)
    assert result.elasticity_interval[0] <= TRUE_ELASTICITY <= result.elasticity_interval[1]
    assert abs(result.elasticity - TRUE_ELASTICITY) < 0.25
    assert result.price_change_pct == pytest.approx(10.0)
    assert result.synthetic_data and len(result.disclosures) >= 5
    assert result.revenue_delta_interval[0] <= result.revenue_delta_pct <= result.revenue_delta_interval[1]
    assert run.result.provenance.data_layer == "synthetic"


def test_sensitivity_covers_the_main_drivers_with_intervals(run):
    rows = run.report.table("sensitivity").rows
    assert {row[0] for row in rows} == {"elasticity", "competitor_price", "promotion_depth", "price_change"}
    assert all(row[3] <= row[2] <= row[4] or row[3] == row[4] for row in rows)
    assert run.report.chart_hint.kind == "range_band"
    assert_complete_report(run.report)


def test_result_is_sized_in_reais_when_a_baseline_is_measured(run):
    assert run.report.number("baseline_revenue") == 100000.0
    assert run.report.number("revenue_delta") == pytest.approx(100000.0 * run.report.number("revenue_delta_pct") / 100.0)


def test_scenario_is_deterministic():
    sales, competitor = _sales()
    tables = {"sales": table(sales, "Q-SALES", date="time"), "competitor": table(competitor, "Q-COMP", date="time")}
    first = scenario.execute({"price_change_pct": 5.0}, data(tables, seed=1))
    second = scenario.execute({"price_change_pct": 5.0}, data(tables, seed=1))
    assert stable(first.result) == stable(second.result)
    assert first.report == second.report


def test_flat_prices_cannot_be_fit():
    sales, competitor = _sales()
    sales["list_price"] = 50.0
    sales["price"] = 50.0
    run = scenario.execute({"price_change_pct": 5.0}, data({"sales": table(sales, "Q-SALES", date="time")}))
    assert run.result.status == "insufficient_evidence"
