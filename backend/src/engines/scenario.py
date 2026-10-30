"""Scenario (WHAT IF): price elasticity from price history vs realised units
(log-log regression), "raise price X%" simulated with Monte Carlo
intervals, and sensitivity on the main drivers.

Reuses :class:`analysts.scenario.ScenarioAnalyst` - and through it
:func:`analysts.elasticity.estimate_price_elasticity` - for the fit, the
5,000-draw Monte Carlo interval and the five mandatory disclosures. This
module adds:

* the price change read from the question ("raise prices by 10%");
* the category-period panel with two-way fixed effects removed, so the fit
  is within-category and net of common trend and seasonality;
* a driver sensitivity sweep: the elasticity at its CI bounds, competitor
  prices, promotion depth and the size of the price move, each with its own
  Monte Carlo interval; plus the result in R$ when a baseline revenue is
  measured.

It never invents a coefficient: every response used is estimated from the
supplied rows. Real orders are not modified by the synthetic layer, so
realised demand is ``inventory_daily.units_sold`` (V2-SYN-1).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

import numpy as np
import statsmodels.api as sm
from pydantic import Field

from analysts import registry
from contracts.models import ContractModel
from contracts.v2 import FitQuality, ScenarioResult

from . import prep
from .base import EngineData, Timer, analyst_input, engine_result, frame_from_table, guarded, insufficient
from .report import ChartHint, EngineReport, EngineRun, KeyNumber, ReportTable, confidence_from

ENGINE_VERSION = "scenario-2.0.0"
DRAWS = 5000

_UP = r"(?:raise|raising|increase|increasing|lift|lifting|hike|push|put up|aumentar|subir)"
_DOWN = r"(?:cut|cutting|lower|lowering|reduce|reducing|decrease|decreasing|drop|dropping|discount|baixar|reduzir)"
_PCT = r"([0-9]+(?:[.,][0-9]+)?)\s*(?:%|percent|por cento)"
_PRICE = r"(?:the\s+)?(?:list\s+)?(?:prices?|pre[cç]os?)"
_PATTERNS = (
    (re.compile(rf"{_UP}\s+{_PRICE}\s+(?:\w+\s+){{0,4}}?(?:by|em|de)?\s*{_PCT}"), 1.0),
    (re.compile(rf"{_DOWN}\s+{_PRICE}\s+(?:\w+\s+){{0,4}}?(?:by|em|de)?\s*{_PCT}"), -1.0),
    (re.compile(rf"{_PCT}\s+(?:price\s+)?(?:increase|rise|hike|higher)"), 1.0),
    (re.compile(rf"{_PCT}\s+(?:price\s+)?(?:cut|decrease|drop|reduction|lower)"), -1.0),
    (re.compile(rf"{_PRICE}\s*([+-])\s*([0-9]+(?:[.,][0-9]+)?)\s*%"), 0.0),
)


def price_change_from_question(question: str) -> float | None:
    """The signed % price change a question asks about, or ``None``."""
    text = " ".join(question.lower().split())
    for pattern, sign in _PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        if sign == 0.0:
            return float(match.group(2).replace(",", ".")) * (1.0 if match.group(1) == "+" else -1.0)
        return sign * float(match.group(1).replace(",", "."))
    return None


class ScenarioEngineParams(ContractModel):
    question: str | None = None
    price_change_pct: float | None = Field(default=None, gt=-100.0)
    category: str | None = None
    alpha: float = Field(default=0.05, gt=0.0, lt=0.5)
    competitor_shock_pct: float = Field(default=10.0, ge=0.0)
    promotion_shock_pts: float = Field(default=10.0, ge=0.0)
    unit: str = "R$"
    grain: str = "month"


def _panel(data: EngineData, parsed: ScenarioEngineParams) -> dict[str, Any] | None:
    """Prepared elasticity tables: passed in directly, or built from a sales panel."""
    if data.table("price_history") is not None and data.table("competitor_prices") is not None:
        return {name: data.tables[name] for name in ("price_history", "competitor_prices", "demand") if name in data.tables}
    sales = data.table("sales")
    if sales is None:
        return None
    competitor = data.table("competitor")
    frames = prep.elasticity_panel(frame_from_table(sales), frame_from_table(competitor) if competitor is not None else None,
                                   grain=parsed.grain)
    return {
        "price_history": prep.as_table(frames["price_history"], "SCN-PRICE", roles={"date": "time", "product_id": "key"}),
        "competitor_prices": prep.as_table(frames["competitor_prices"], "SCN-COMP", roles={"date": "time", "product_id": "key"}),
        "demand": prep.as_table(frames["demand"], "SCN-DEMAND", roles={"date": "time", "product_id": "key"}),
    }


def _coefficients(tables: Mapping[str, Any], category: str | None) -> dict[str, float]:
    """Competitor and promotion coefficients from the same design as the fit.

    Only used to size the driver sensitivity; the elasticity itself comes from
    the existing estimator.
    """
    price = frame_from_table(tables["price_history"]).set_index(["date", "product_id"])
    comp = frame_from_table(tables["competitor_prices"]).set_index(["date", "product_id"])
    demand = frame_from_table(tables["demand"]).set_index(["date", "product_id"])
    joined = price.join(comp, how="inner").join(demand, how="inner")
    if category is not None and "product_category" in joined:
        subset = joined[joined["product_category"] == category]
        joined = subset if len(subset) >= 12 else joined
    joined = joined[(joined["effective_price"] > 0) & (joined["competitor_price"] > 0) & (joined["units_sold"] > 0)]
    if len(joined) < 12:
        return {"competitor": 0.0, "promotion": 0.0, "competitor_se": 0.0, "promotion_se": 0.0,
                "competitor_p": 1.0, "promotion_p": 1.0}
    design = np.column_stack([
        np.ones(len(joined)),
        np.log(joined["effective_price"]),
        np.log(joined["competitor_price"] / joined["effective_price"]),
        joined.get("promotion_pct", 0.0),
    ])
    keep = [0, 1, 2] + ([3] if np.ptp(design[:, 3]) > 0 else [])
    fitted = sm.OLS(np.log(joined["units_sold"]).to_numpy(), design[:, keep]).fit()
    params = list(fitted.params) + ([0.0] if len(keep) == 3 else [])
    errors = list(fitted.bse) + ([0.0] if len(keep) == 3 else [])
    p_values = list(fitted.pvalues) + ([1.0] if len(keep) == 3 else [])
    return {
        "competitor": float(params[2]), "competitor_se": float(errors[2]), "competitor_p": float(p_values[2]),
        "promotion": float(params[3]), "promotion_se": float(errors[3]), "promotion_p": float(p_values[3]),
    }


def _revenue(change: float, elasticity: np.ndarray | float, demand_multiplier: float = 1.0) -> np.ndarray | float:
    return (1.0 + change) ** (1.0 + elasticity) * demand_multiplier - 1.0


def sensitivity_sweep(
    *, change: float, fit: ScenarioResult, coefficients: Mapping[str, float], params: ScenarioEngineParams, seed: int
) -> list[tuple[Any, ...]]:
    """Revenue change (%) when each main driver moves over its plausible range."""
    rng = np.random.default_rng(seed)
    se = max((fit.elasticity_interval[1] - fit.elasticity_interval[0]) / (2 * 1.959963984540054), 1e-9)
    draws = rng.normal(fit.elasticity, se, size=DRAWS)
    tail = params.alpha / 2.0

    def case(driver: str, setting: str, change_value: float, elasticity: float, multiplier: float,
             use_draws: bool = True, multiplier_draws: np.ndarray | None = None):
        point = float(_revenue(change_value, elasticity, multiplier)) * 100.0
        sampled_e = draws if use_draws else np.full(DRAWS, elasticity)
        sampled_m = multiplier_draws if multiplier_draws is not None else multiplier
        sampled = _revenue(change_value, sampled_e, sampled_m) * 100.0
        return (driver, setting, point, float(np.quantile(sampled, tail)), float(np.quantile(sampled, 1 - tail)))

    competitor = coefficients.get("competitor", 0.0)
    promotion = coefficients.get("promotion", 0.0)
    competitor_draws = rng.normal(competitor, max(coefficients.get("competitor_se", 0.0), 1e-12), size=DRAWS)
    promotion_draws = rng.normal(promotion, max(coefficients.get("promotion_se", 0.0), 1e-12), size=DRAWS)
    shock = params.competitor_shock_pct / 100.0
    points = params.promotion_shock_pts
    return [
        case("elasticity", f"CI low ({fit.elasticity_interval[0]:.3f})", change, fit.elasticity_interval[0], 1.0, False),
        case("elasticity", f"CI high ({fit.elasticity_interval[1]:.3f})", change, fit.elasticity_interval[1], 1.0, False),
        case("competitor_price", f"-{params.competitor_shock_pct:g}%", change, fit.elasticity, (1 - shock) ** competitor,
             multiplier_draws=(1 - shock) ** competitor_draws),
        case("competitor_price", f"+{params.competitor_shock_pct:g}%", change, fit.elasticity, (1 + shock) ** competitor,
             multiplier_draws=(1 + shock) ** competitor_draws),
        case("promotion_depth", f"+{points:g} pts", change, fit.elasticity, math.exp(promotion * points),
             multiplier_draws=np.exp(promotion_draws * points)),
        case("price_change", f"{change * 50:.1f}%", change / 2.0, fit.elasticity, 1.0),
        case("price_change", f"{change * 200:.1f}%", max(-0.99, change * 2.0), fit.elasticity, 1.0),
    ]


@guarded("python.scenario", ENGINE_VERSION, "log_log_ols_monte_carlo")
def execute(params: Mapping[str, Any], data: EngineData) -> EngineRun:
    """Simulate a stated price change from an elasticity estimated on the rows."""

    timer = Timer()
    parsed = ScenarioEngineParams.model_validate(dict(params))
    change_pct = parsed.price_change_pct
    source = "given explicitly"
    if change_pct is None and parsed.question:
        change_pct = price_change_from_question(parsed.question)
        source = f"read from the question ({parsed.question!r})"
    if change_pct is None:
        return insufficient(tool="python.scenario", reason="State the price change to simulate, e.g. 'raise prices by 10%'.",
                            data=data, timer=timer, engine_version=ENGINE_VERSION, method="log_log_ols_monte_carlo")
    tables = _panel(data, parsed)
    if tables is None:
        return insufficient(tool="python.scenario",
                            reason="Price elasticity cannot be fit: no price_history/competitor_prices or sales panel was supplied.",
                            data=data, timer=timer, engine_version=ENGINE_VERSION, method="log_log_ols_monte_carlo")
    analyst_tables = {"price_history": tables["price_history"], "competitor_prices": tables["competitor_prices"]}
    if "demand" in tables:
        analyst_tables["demand"] = tables["demand"]
    output = registry.resolve("scenario").run(
        analyst_input("scenario", {"price_change_pct": change_pct, "category": parsed.category, "alpha": parsed.alpha},
                      analyst_tables, data)
    )
    if output.status != "ok" or not isinstance(output.result, ScenarioResult):
        return engine_result(tool="python.scenario", output=output,
                             report=EngineReport(engine="scenario", method="log_log_ols_monte_carlo", confidence=confidence_from(basis="not run")),
                             data=data, timer=timer, method="log_log_ols_monte_carlo", engine_version=ENGINE_VERSION)
    fit = output.result
    coefficients = (
        _coefficients(analyst_tables, parsed.category)
        if "demand" in analyst_tables
        else {"competitor": 0.0, "promotion": 0.0, "competitor_se": 0.0, "promotion_se": 0.0, "competitor_p": 1.0, "promotion_p": 1.0}
    )
    sweep = sensitivity_sweep(change=change_pct / 100.0, fit=fit, coefficients=coefficients, params=parsed, seed=data.seed)

    baseline_revenue: float | None = None
    baseline = data.table("baseline")
    if baseline is not None and baseline.rows:
        names = [column.name for column in baseline.columns]
        baseline_revenue = math.fsum(float(row[names.index("revenue")]) for row in baseline.rows) if "revenue" in names else None

    report = _report(parsed, fit, sweep, coefficients, change_pct, source, baseline_revenue)
    return engine_result(
        tool="python.scenario", output=output, report=report, data=data, timer=timer,
        method="log_log_ols_monte_carlo", engine_version=ENGINE_VERSION, library="statsmodels+numpy",
        fit_quality=FitQuality(measure="r_squared", value=fit.r_squared, n_observations=fit.observations),
    )


def run(params: Mapping[str, Any], data: EngineData):
    return execute(params, data).result


def _driver_notes(coefficients: Mapping[str, float], alpha: float) -> tuple[str, ...]:
    notes = []
    for name, label in (("competitor", "competitor price"), ("promotion", "promotion depth")):
        p_value = coefficients.get(f"{name}_p", 1.0)
        if p_value >= alpha:
            notes.append(f"The {label} response is not distinguishable from zero (p = {p_value:.3f}); its sensitivity band reflects that.")
    return tuple(notes)


def _report(
    params: ScenarioEngineParams,
    fit: ScenarioResult,
    sweep: list[tuple[Any, ...]],
    coefficients: Mapping[str, float],
    change_pct: float,
    source: str,
    baseline_revenue: float | None,
) -> EngineReport:
    numbers = [
        KeyNumber(name="price_change_pct", value=change_pct, unit="%", label="price change"),
        KeyNumber(name="elasticity", value=fit.elasticity, label="own-price elasticity"),
        KeyNumber(name="elasticity_low", value=fit.elasticity_interval[0], label="elasticity CI low"),
        KeyNumber(name="elasticity_high", value=fit.elasticity_interval[1], label="elasticity CI high"),
        KeyNumber(name="r_squared", value=fit.r_squared, label="R-squared"),
        KeyNumber(name="demand_delta_pct", value=fit.demand_delta_pct, unit="%", label="demand change"),
        KeyNumber(name="revenue_delta_pct", value=fit.revenue_delta_pct, unit="%", label="revenue change"),
        KeyNumber(name="revenue_delta_low", value=fit.revenue_delta_interval[0], unit="%", label="revenue change interval low"),
        KeyNumber(name="revenue_delta_high", value=fit.revenue_delta_interval[1], unit="%", label="revenue change interval high"),
        KeyNumber(name="competitor_coefficient", value=coefficients.get("competitor", 0.0), label="log relative competitor price"),
        KeyNumber(name="competitor_p_value", value=coefficients.get("competitor_p"), label="competitor coefficient p-value"),
        KeyNumber(name="promotion_coefficient", value=coefficients.get("promotion", 0.0), label="per discount point"),
        KeyNumber(name="promotion_p_value", value=coefficients.get("promotion_p"), label="promotion coefficient p-value"),
    ]
    if baseline_revenue is not None:
        numbers += [
            KeyNumber(name="baseline_revenue", value=baseline_revenue, unit=params.unit, label="measured baseline revenue"),
            KeyNumber(name="revenue_delta", value=baseline_revenue * fit.revenue_delta_pct / 100.0, unit=params.unit, label="revenue change"),
            KeyNumber(name="revenue_delta_low_value", value=baseline_revenue * fit.revenue_delta_interval[0] / 100.0, unit=params.unit, label="interval low"),
            KeyNumber(name="revenue_delta_high_value", value=baseline_revenue * fit.revenue_delta_interval[1] / 100.0, unit=params.unit, label="interval high"),
        ]
    swing = sorted(
        {row[0] for row in sweep},
        key=lambda driver: -max(abs(row[2] - fit.revenue_delta_pct) for row in sweep if row[0] == driver),
    )
    tornado = tuple(row for driver in swing for row in sweep if row[0] == driver)
    covers = fit.elasticity_interval[1] < 0
    return EngineReport(
        engine="scenario",
        method="log_log_ols_monte_carlo",
        tables=(
            ReportTable(name="sensitivity", columns=("driver", "setting", "revenue_delta_pct", "interval_low", "interval_high"), rows=tornado),
            ReportTable(name="scenario", columns=("price_change_pct", "demand_delta_pct", "revenue_delta_pct", "interval_low", "interval_high"),
                        rows=((change_pct, fit.demand_delta_pct, fit.revenue_delta_pct, *fit.revenue_delta_interval),)),
        ),
        key_numbers=tuple(numbers),
        assumptions=(
            f"The price change was {source}.",
            *fit.disclosures,
            "The fit is within-category and net of common period effects (two-way fixed effects removed before OLS).",
            "Demand is mean daily units on in-stock days; stockout days censor demand and are excluded.",
            f"Sensitivity drivers are ranked by how far they move the revenue change; each case uses {DRAWS} seeded Monte Carlo draws "
            "over the elasticity and the driver coefficient.",
            *_driver_notes(coefficients, params.alpha),
        ),
        confidence=confidence_from(interval=fit.elasticity_interval, sample_size=fit.observations,
                                   grade=2 if covers else 1, basis="Elasticity interval width and fit sample size (observational)."),
        chart_hint=ChartHint(kind="range_band", table="sensitivity", x="driver", y=("revenue_delta_pct", "interval_low", "interval_high"),
                             series="setting", title=f"Revenue change for a {change_pct:g}% price change: sensitivity"),
    )


__all__ = ["ScenarioEngineParams", "execute", "price_change_from_question", "run", "sensitivity_sweep"]
