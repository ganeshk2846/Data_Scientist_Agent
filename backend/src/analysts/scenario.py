"""Fit-backed price scenarios with deterministic uncertainty propagation."""

from __future__ import annotations

import math

import numpy as np
from pydantic import Field, ValidationError, model_validator

from contracts.models import AnalystInput, ContractModel, TableRef
from contracts.v2 import AnalystOutput, ScenarioParam, ScenarioResult, ScenarioSensitivity

from .elasticity import estimate_price_elasticity


_DISCLOSURES = (
    "This estimate is based on synthetic data from price_history and competitor_prices.",
    "The elasticity is observational, not the result of a randomized price experiment.",
    "The point estimate, 95% confidence interval and model R-squared describe the fitted relationship.",
    "Controls include relative competitor price and promotion discount when those measurements vary.",
    "Unmeasured factors may move price and demand together; this scenario is not proof of a causal response.",
)


class ScenarioParams(ContractModel):
    scenario_params: tuple[ScenarioParam, ...] = ()
    price_change_pct: float | None = Field(default=None, gt=-100.0)
    category: str | None = None
    alpha: float = Field(default=0.05, gt=0.0, lt=0.5)

    @model_validator(mode="after")
    def _has_a_price_change(self) -> ScenarioParams:
        if self.price_change_pct is None and not self.scenario_params:
            raise ValueError("a fitted price scenario needs a measured price change")
        if len(self.scenario_params) > 1:
            raise ValueError("this scenario accepts one fitted price perturbation")
        if self.scenario_params:
            parameter = self.scenario_params[0]
            if parameter.kind != "multiplicative" or parameter.target not in {
                "price",
                "effective_price",
                "price_history",
            }:
                raise ValueError("the fitted elasticity scenario requires a multiplicative price change")
        return self

    def change_fraction(self) -> float:
        if self.price_change_pct is not None:
            return self.price_change_pct / 100.0
        return self.scenario_params[0].value - 1.0


class ScenarioAnalyst:
    module = "scenario"

    def run(self, inp: AnalystInput) -> AnalystOutput:
        price_history = inp.tables.get("price_history")
        competitor_prices = inp.tables.get("competitor_prices")
        if price_history is None or competitor_prices is None:
            missing = tuple(
                name
                for name, table in (
                    ("price_history", price_history),
                    ("competitor_prices", competitor_prices),
                )
                if table is None
            )
            return _insufficient(
                f"Price elasticity cannot be fit because required synthetic input is missing: {', '.join(missing)}.",
                inp,
                (price_history, competitor_prices),
            )
        try:
            params = ScenarioParams.model_validate(inp.params)
        except ValidationError as exc:
            return _insufficient(f"Invalid scenario parameters: {exc}", inp, (price_history, competitor_prices))
        demand = inp.tables.get("inventory_daily") or inp.tables.get("demand")
        promotions = inp.tables.get("promotions")
        fit, reason = estimate_price_elasticity(
            price_history,
            competitor_prices,
            demand=demand,
            promotions=promotions,
            category=params.category,
        )
        if fit is None:
            return _insufficient(
                reason or "No supported price elasticity fit could be estimated.",
                inp,
                (price_history, competitor_prices, demand, promotions),
            )
        change = params.change_fraction()
        if not math.isfinite(change) or change <= -1.0:
            return _insufficient("The price change must leave a positive price.", inp, (price_history, competitor_prices))

        try:
            point_demand = (1.0 + change) ** fit.elasticity - 1.0
            point_revenue = (1.0 + change) ** (1.0 + fit.elasticity) - 1.0
            rng = np.random.default_rng(inp.seed if inp.seed is not None else 0)
            draws = rng.normal(fit.elasticity, fit.standard_error, size=5000)
            with np.errstate(over="ignore", invalid="ignore"):
                revenue_draws = np.power(1.0 + change, 1.0 + draws) - 1.0
        except (OverflowError, ValueError):
            return _insufficient(
                "The fitted scenario cannot be evaluated at this price change.",
                inp,
                (price_history, competitor_prices, demand, promotions),
            )
        tail = params.alpha / 2.0
        revenue_interval = (
            float(np.quantile(revenue_draws, tail) * 100.0),
            float(np.quantile(revenue_draws, 1.0 - tail) * 100.0),
        )
        shocks = {change / 2.0, change, max(-0.99, change * 2.0)}
        sensitivity = tuple(
            ScenarioSensitivity(
                shock_pct=shock * 100.0,
                revenue_delta_pct=_scenario_revenue_delta(shock, fit.elasticity),
            )
            for shock in sorted(shocks)
        )
        scenario_values = (
            point_demand,
            point_revenue,
            *revenue_interval,
            *(item.revenue_delta_pct for item in sensitivity),
        )
        if not all(math.isfinite(value) for value in scenario_values):
            return _insufficient(
                "The fitted scenario exceeds the finite numeric range.",
                inp,
                (price_history, competitor_prices, demand, promotions),
            )
        tables = tuple(
            table.query_id
            for table in (price_history, competitor_prices, demand, promotions)
            if table is not None
        )
        assumptions = (
            *_DISCLOSURES,
            f"The fitted demand response is {(point_demand * 100.0):.3f}% for a {change * 100.0:.3f}% price change.",
            "The confidence interval propagates uncertainty in the fitted elasticity with a fixed-seed Monte Carlo simulation.",
            "The fit pools product observations when a category has fewer than 12 usable rows.",
        )
        return AnalystOutput(
            module="scenario",
            status="ok",
            result=ScenarioResult(
                scenario=f"Price change {change * 100.0:.3f}%",
                price_change_pct=change * 100.0,
                elasticity=fit.elasticity,
                elasticity_interval=fit.interval,
                r_squared=fit.r_squared,
                controls=fit.controls,
                demand_delta_pct=point_demand * 100.0,
                revenue_delta_pct=point_revenue * 100.0,
                revenue_delta_interval=revenue_interval,
                sensitivity=sensitivity,
                observations=fit.observations,
                synthetic_data=True,
                disclosures=_DISCLOSURES,
            ),
            parameters={
                "category": fit.category,
                "pooled": fit.pooled,
                "price_change_pct": change * 100.0,
                "seed": inp.seed if inp.seed is not None else 0,
                "simulation_draws": 5000,
            },
            assumptions=assumptions,
            sources=tables,
        )


def _insufficient(
    reason: str,
    inp: AnalystInput,
    tables: tuple[TableRef | None, ...] = (),
) -> AnalystOutput:
    return AnalystOutput(
        module="scenario",
        status="insufficient_evidence",
        reason=reason,
        sources=tuple(table.query_id for table in tables if table is not None),
    )


def _scenario_revenue_delta(shock: float, elasticity: float) -> float:
    try:
        return ((1.0 + shock) ** (1.0 + elasticity) - 1.0) * 100.0
    except OverflowError:
        return math.inf


__all__ = ["ScenarioAnalyst", "ScenarioParams"]
