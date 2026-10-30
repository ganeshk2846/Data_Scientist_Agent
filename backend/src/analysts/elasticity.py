"""Observed log-log demand elasticity fits for scenario analysis."""

from __future__ import annotations

import math
from datetime import date, datetime

import numpy as np
import statsmodels.api as sm
from pydantic import Field
from scipy.stats import t

from contracts.models import ContractModel, TableRef


class ElasticityFit(ContractModel):
    elasticity: float = Field(allow_inf_nan=False)
    standard_error: float = Field(gt=0.0, allow_inf_nan=False)
    interval: tuple[float, float]
    r_squared: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    controls: tuple[str, ...] = Field(min_length=1)
    observations: int = Field(ge=3)
    category: str = "all"
    pooled: bool = False


def estimate_price_elasticity(
    price_history: TableRef,
    competitor_prices: TableRef,
    *,
    demand: TableRef | None = None,
    promotions: TableRef | None = None,
    category: str | None = None,
) -> tuple[ElasticityFit | None, str | None]:
    """Fit log(quantity) on log(price) with competitor and promotion controls."""

    price_cols = _columns(price_history)
    competitor_cols = _columns(competitor_prices)
    if not {"date", "product_id", "effective_price"} <= price_cols.keys():
        return None, "price_history needs date, product_id and effective_price."
    if not {"date", "product_id", "competitor_price"} <= competitor_cols.keys():
        return None, "competitor_prices needs date, product_id and competitor_price."
    demand_table = demand or price_history
    demand_cols = _columns(demand_table)
    quantity_name = next(
        (name for name in ("units_sold", "quantity", "realized_volume", "orders") if name in demand_cols),
        None,
    )
    if quantity_name is None:
        return None, "Realized volume is required to estimate price elasticity."
    promo_table = promotions
    promo_cols = _columns(promo_table) if promo_table is not None else {}
    price_rows = _rows_by_key(
        price_history,
        price_cols["date"],
        price_cols["product_id"],
    )
    competitor_rows = _rows_by_key(
        competitor_prices,
        competitor_cols["date"],
        competitor_cols["product_id"],
    )
    demand_rows = _rows_by_key(
        demand_table,
        demand_cols["date"],
        demand_cols["product_id"],
    )
    promo_by_date: dict[tuple[str, str], list[float]] = {}
    if promo_table is not None and {"date", "discount_pct"} <= promo_cols.keys():
        promo_by_date = _rows_by_key(
            promo_table,
            promo_cols["date"],
            promo_cols.get("product_id"),
            value_index=promo_cols["discount_pct"],
        )

    observations: list[tuple[float, float, float, float]] = []
    selected_category = category
    category_idx = price_cols.get("product_category")
    for key in sorted(set(price_rows) & set(competitor_rows) & set(demand_rows)):
        price_row = price_rows[key][0]
        if selected_category is not None and category_idx is not None:
            if str(price_row[category_idx]) != selected_category:
                continue
        try:
            price = _positive(price_row[price_cols["effective_price"]])
            competitor = _positive(
                math.fsum(
                    _positive(row[competitor_cols["competitor_price"]])
                    for row in competitor_rows[key]
                )
                / len(competitor_rows[key])
            )
            quantity = _positive(demand_rows[key][0][demand_cols[quantity_name]])
        except (IndexError, TypeError, ValueError):
            continue
        promo = 0.0
        if "promotion_pct" in price_cols:
            try:
                promo = float(price_row[price_cols["promotion_pct"]])
            except (TypeError, ValueError):
                continue
        elif promo_by_date:
            promo_values = promo_by_date.get(key, ())
            if not promo_values and key[1]:
                promo_values = promo_by_date.get((key[0], ""), ())
            if promo_values:
                promo = math.fsum(promo_values) / len(promo_values)
        if not math.isfinite(promo):
            continue
        observations.append(
            (
                math.log(price),
                math.log(quantity),
                math.log(competitor / price),
                promo,
            )
        )
    if len(observations) < 12 and selected_category is not None:
        return estimate_price_elasticity(
            price_history,
            competitor_prices,
            demand=demand,
            promotions=promotions,
            category=None,
        )
    if len(observations) < 12:
        return None, "At least 12 matched positive price, competitor-price and volume observations are required."

    promotion_varies = len({item[3] for item in observations}) > 1
    design = [
        [1.0, price, relative_competitor]
        + ([promotion] if promotion_varies else [])
        for price, _, relative_competitor, promotion in observations
    ]
    x = np.asarray(design, dtype=float)
    y = np.asarray([quantity for _, quantity, _, _ in observations], dtype=float)
    if float(np.ptp(x[:, 1])) <= 1e-10:
        return None, "No meaningful price variation exists for the elasticity fit."
    if np.linalg.matrix_rank(x) < x.shape[1]:
        return None, "The elasticity controls are collinear and cannot be estimated."
    try:
        fitted = sm.OLS(y, x).fit()
    except (FloatingPointError, np.linalg.LinAlgError, RuntimeError, ValueError) as exc:
        return None, f"The elasticity regression could not be estimated: {type(exc).__name__}."
    coefficient = float(fitted.params[1])
    standard_error = float(fitted.bse[1])
    if not math.isfinite(coefficient) or not math.isfinite(standard_error) or standard_error <= 0:
        return None, "The fitted price coefficient has no finite uncertainty estimate."
    critical = float(t.ppf(0.975, int(fitted.df_resid)))
    lower = coefficient - critical * standard_error
    upper = coefficient + critical * standard_error
    controls = ["log_relative_competitor_price"]
    if promotion_varies:
        controls.append("promotion_discount")
    return (
        ElasticityFit(
            elasticity=coefficient,
            standard_error=standard_error,
            interval=(lower, upper),
            r_squared=min(1.0, max(0.0, float(fitted.rsquared))),
            controls=tuple(controls),
            observations=len(observations),
            category=selected_category or "all",
            pooled=selected_category is None,
        ),
        None,
    )


def _columns(table: TableRef | None) -> dict[str, int]:
    if table is None:
        return {}
    return {column.name.lower(): index for index, column in enumerate(table.columns)}


def _rows_by_key(
    table: TableRef,
    date_index: int,
    product_index: int | None,
    *,
    value_index: int | None = None,
) -> dict[tuple[str, str], list]:
    output: dict[tuple[str, str], list] = {}
    for row in table.rows:
        if max(date_index, product_index or 0, value_index or 0) >= len(row):
            continue
        period = _period_key(row[date_index])
        product = str(row[product_index]).strip() if product_index is not None else ""
        if period is None:
            continue
        key = (period, product)
        if value_index is None:
            output.setdefault(key, []).append(row)
            continue
        try:
            value = float(row[value_index])
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            output.setdefault(key, []).append(value)
    return output


def _period_key(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()[:10]
    return None


def _positive(value: object) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("log-log inputs must be finite and positive")
    return number


__all__ = ["ElasticityFit", "estimate_price_elasticity"]
