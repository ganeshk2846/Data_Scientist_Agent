from __future__ import annotations

import math
from datetime import date, timedelta

from analysts.elasticity import estimate_price_elasticity
from contracts.models import AnalystColumn, TableRef


def _price_tables():
    price_rows = []
    competitor_rows = []
    for day in range(36):
        for product in range(4):
            date_value = (date(2018, 1, 1) + timedelta(days=day)).isoformat()
            index = day * 4 + product
            price = 20.0 + product * 8.0 + (index % 11) * 1.7
            competitor = 27.0 + product * 5.0 + ((index * 7) % 13) * 1.1
            promotion = float((index % 5) * 0.03)
            quantity = math.exp(
                8.0
                - 1.2 * math.log(price)
                + 0.3 * math.log(competitor / price)
                + 0.15 * promotion
                + 0.02 * math.sin(index)
            )
            price_rows.append(
                (date_value, f"p{product}", price, competitor, promotion, quantity)
            )
            competitor_rows.append((date_value, f"p{product}", competitor))
    price_table = TableRef(
        query_id="Q-PRICE",
        columns=(
            AnalystColumn(name="date", type="TEXT", role="time"),
            AnalystColumn(name="product_id", type="TEXT", role="key"),
            AnalystColumn(name="effective_price", type="REAL", role="measure"),
            AnalystColumn(name="competitor_price", type="REAL", role="measure"),
            AnalystColumn(name="promotion_pct", type="REAL", role="measure"),
            AnalystColumn(name="units_sold", type="REAL", role="measure"),
        ),
        row_count=len(price_rows),
        uri="inline://Q-PRICE",
        rows=tuple(price_rows),
    )
    competitor_table = TableRef(
        query_id="Q-COMPETITOR",
        columns=(
            AnalystColumn(name="date", type="TEXT", role="time"),
            AnalystColumn(name="product_id", type="TEXT", role="key"),
            AnalystColumn(name="competitor_price", type="REAL", role="measure"),
        ),
        row_count=len(competitor_rows),
        uri="inline://Q-COMPETITOR",
        rows=tuple(competitor_rows),
    )
    return price_table, competitor_table


def test_log_log_fit_recovers_known_elasticity_with_controls_and_interval():
    price, competitor = _price_tables()
    fit, reason = estimate_price_elasticity(price, competitor)

    assert reason is None
    assert fit is not None
    assert abs(fit.elasticity + 1.2) < 0.1
    assert fit.interval[0] <= fit.elasticity <= fit.interval[1]
    assert fit.r_squared > 0.99
    assert fit.observations == price.row_count
    assert "log_relative_competitor_price" in fit.controls
    assert "promotion_discount" in fit.controls
    assert fit.pooled is True


def test_log_log_fit_requires_price_variation_and_realized_volume():
    price, competitor = _price_tables()
    rows = tuple(
        (row[0], row[1], 25.0, row[3], row[4], row[5])
        for row in price.rows
    )
    flat_price = TableRef(
        query_id=price.query_id,
        columns=price.columns,
        row_count=len(rows),
        uri=price.uri,
        rows=rows,
    )
    fit, reason = estimate_price_elasticity(flat_price, competitor)
    assert fit is None
    assert "variation" in reason

    missing_volume = TableRef(
        query_id=price.query_id,
        columns=price.columns[:5],
        row_count=price.row_count,
        uri=price.uri,
        rows=tuple(row[:5] for row in price.rows),
    )
    fit, reason = estimate_price_elasticity(missing_volume, competitor)
    assert fit is None
    assert "volume" in reason
