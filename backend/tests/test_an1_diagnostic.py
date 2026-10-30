from __future__ import annotations

from datetime import date

from analysts.driver import DriverAnalyst
from contracts.models import AnalystColumn, AnalystInput, Period, TableRef
from contracts.v2 import DiagnosticResult


def _table(query_id, names, rows, roles):
    return TableRef(
        query_id=query_id,
        columns=tuple(
            AnalystColumn(name=name, type="TEXT" if name in roles["text"] else "REAL", role=roles["roles"][name])
            for name in names
        ),
        row_count=len(rows),
        uri=f"inline://{query_id}",
        rows=tuple(tuple(row) for row in rows),
    )


def _month(index):
    year = 2017 + (index // 12)
    month = index % 12 + 1
    return date(year, month, 1).isoformat()


def test_driver_ranks_indicator_correlations_and_caps_feature_importance():
    contrib_rows = tuple((_month(index), "SP", 100.0 + index * 10.0) for index in range(18))
    spend_rows = tuple((_month(index), 500.0 + index * 20.0) for index in range(18))
    traffic_rows = tuple(
        (_month(index), 50.0 + index * 3.0, 0.2 + index * 0.01)
        for index in range(18)
    )
    tables = {
        "contrib": _table(
            "Q-CONTRIB",
            ("period", "customer_state", "value"),
            contrib_rows,
            {"text": {"period", "customer_state"}, "roles": {"period": "time", "customer_state": "dimension", "value": "measure"}},
        ),
        "marketing_spend": _table(
            "Q-SPEND",
            ("date", "spend"),
            spend_rows,
            {"text": {"date"}, "roles": {"date": "time", "spend": "measure"}},
        ),
        "web_traffic": _table(
            "Q-TRAFFIC",
            ("date", "sessions", "bounce_rate"),
            traffic_rows,
            {"text": {"date"}, "roles": {"date": "time", "sessions": "measure", "bounce_rate": "measure"}},
        ),
    }
    output = DriverAnalyst().run(
        AnalystInput(
            module="driver",
            params={
                "metric": "revenue",
                "current_period": Period(start=date(2018, 1, 1), end=date(2018, 4, 1)),
                "comparison_period": Period(start=date(2017, 10, 1), end=date(2018, 1, 1)),
                "dimensions": ("customer_state",),
                "aggregation": "sum",
                "alpha": 0.05,
            },
            tables=tables,
            run_id="RUN-DRIVER-INDICATORS",
            seed=19,
        )
    )

    assert output.status == "ok"
    assert isinstance(output.result, DiagnosticResult)
    assert output.result.indicator_drivers
    assert all(item.grade == 2 for item in output.result.indicator_drivers)
    assert all(item.p_value is not None and item.q_value is not None for item in output.result.indicator_drivers)
    assert output.result.feature_importance
    assert all(item.grade <= 2 for item in output.result.feature_importance)
    assert output.result.correction_used == "benjamini_hochberg_0.05"
    assert any("not causal" in assumption.lower() for assumption in output.assumptions)
    assert {"Q-CONTRIB", "Q-SPEND", "Q-TRAFFIC"} <= set(output.sources)


def test_driver_ratio_decomposition_reconciles_without_additive_shares():
    rows = (
        ("2018-01-01", "A", 10.0, 5.0),
        ("2018-01-01", "B", 20.0, 10.0),
        ("2018-02-01", "A", 12.0, 4.0),
        ("2018-02-01", "B", 25.0, 10.0),
    )
    table = _table(
        "Q-RATIO",
        ("period", "product_category", "numerator", "denominator"),
        rows,
        {"text": {"period", "product_category"}, "roles": {"period": "time", "product_category": "dimension", "numerator": "measure", "denominator": "measure"}},
    )
    output = DriverAnalyst().run(
        AnalystInput(
            module="driver",
            params={
                "metric": "aov",
                "current_period": Period(start=date(2018, 2, 1), end=date(2018, 3, 1)),
                "comparison_period": Period(start=date(2018, 1, 1), end=date(2018, 2, 1)),
                "dimensions": ("product_category",),
                "aggregation": "ratio",
                "value_decomposition": True,
            },
            tables={"contrib": table},
            run_id="RUN-RATIO",
            seed=1,
        )
    )

    assert output.status == "ok"
    assert isinstance(output.result, DiagnosticResult)
    assert abs(output.result.reconciliation_error) < 1e-10
    assert abs(sum(item.contribution for item in output.result.drivers) - output.result.total_change) < 1e-10
    assert all(item.share == 0.0 for item in output.result.drivers)
    assert {item.dimension.rsplit(" ", 1)[-1].strip("()") for item in output.result.drivers} == {"numerator", "denominator"}
    assert any("not additive shares" in assumption.lower() for assumption in output.assumptions)


def test_driver_ratio_without_measured_denominator_returns_insufficient():
    table = _table(
        "Q-RATIO-MISSING",
        ("period", "product_category", "value"),
        (("2018-01-01", "A", 10.0), ("2018-02-01", "A", 12.0)),
        {"text": {"period", "product_category"}, "roles": {"period": "time", "product_category": "dimension", "value": "measure"}},
    )
    output = DriverAnalyst().run(
        AnalystInput(
            module="driver",
            params={
                "metric": "aov",
                "current_period": Period(start=date(2018, 2, 1), end=date(2018, 3, 1)),
                "comparison_period": Period(start=date(2018, 1, 1), end=date(2018, 2, 1)),
                "dimensions": ("product_category",),
                "aggregation": "ratio",
            },
            tables={"contrib": table},
            run_id="RUN-RATIO-MISSING",
            seed=1,
        )
    )

    assert output.status == "insufficient_evidence"
    assert output.result is None
    assert "numerator" in output.reason.lower()
