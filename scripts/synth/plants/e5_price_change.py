"""E5 - a +10% list-price change in one category with a known elasticity."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import TRUE_ELASTICITY
from ..manifest import ManifestWriter, PlantedFact
from ._util import require_values

CATEGORY = "moveis_decoracao"
DATE = "2018-04-01"
PRICE_CHANGE = 0.10
QUIET_DAYS = 60


class PriceChange:
    name = "E5"

    def plan_prices(self, steps: pd.DataFrame, ctx, manifest: ManifestWriter) -> pd.DataFrame:
        """Add the step, clearing other steps nearby so the change is identifiable."""
        require_values(ctx.category_names, (CATEGORY,), "categories")
        day = pd.Timestamp(DATE)
        near = (steps["category"] == CATEGORY) & (
            (pd.to_datetime(steps["date"]) - day).abs() <= pd.Timedelta(days=QUIET_DAYS)
        )
        steps = steps[~near]
        step = pd.DataFrame({"category": [CATEGORY], "date": [DATE], "multiplier": [1 + PRICE_CHANGE]})
        steps = pd.concat([steps, step], ignore_index=True).sort_values(["category", "date"], kind="mergesort")
        manifest.record(PlantedFact(
            plant=self.name, fact_id="E5-price", role="effect", table="price_history",
            column="price", period_start=DATE, period_end="2018-10-31", dimension="product_category",
            dimension_values=(CATEGORY,), planted_effect="list price x 1.10 for every product in the category; no other repricing within 60 days",
            expected_pct=PRICE_CHANGE, is_cause=True,
        ))
        expected_units = round((1 + PRICE_CHANGE) ** TRUE_ELASTICITY - 1, 6)
        manifest.record(PlantedFact(
            plant=self.name, fact_id="E5-units", role="effect", table="inventory_daily",
            column="units_sold", period_start=DATE, period_end="2018-10-31", dimension="product_category",
            dimension_values=(CATEGORY,), planted_effect=f"demand responds with elasticity {TRUE_ELASTICITY}: 1.10 ** {TRUE_ELASTICITY}",
            expected_pct=expected_units, is_cause=False,
            note=(
                f"True own-price elasticity is {TRUE_ELASTICITY} for every category, applied to every list-price "
                "step (base repricing too). Competitor prices are independent of ours, so they are a valid control."
            ),
        ))
        return steps.reset_index(drop=True)

    def inject(self, frames, ctx, rng: np.random.Generator, manifest: ManifestWriter) -> None:
        manifest.record(PlantedFact(
            plant=self.name, fact_id="E5-competitor-control", role="negative_control", table="competitor_prices",
            column="price", period_start=DATE, period_end="2018-10-31", dimension="product_category",
            dimension_values=(CATEGORY,), planted_effect="none: competitor prices are not changed",
            expected_pct=0.0, is_cause=False,
            note="A fit that attributes the demand drop to competitor pricing is wrong.",
        ))
