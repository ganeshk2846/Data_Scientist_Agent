"""E2 - stockouts in the top 3 categories during the November peak."""

from __future__ import annotations

import numpy as np

from ..manifest import ManifestWriter, PlantedFact
from ._util import in_window, realised, require_values

START, END = "2017-11-20", "2017-12-10"
CATEGORIES = ("cama_mesa_banho", "beleza_saude", "esporte_lazer")
PEAKS = (("2016-11-21", "2016-11-30"), ("2017-11-20", "2017-11-30"))
PEAK_LIFT = 0.60


class Stockouts:
    name = "E2"

    def inject(self, frames, ctx, rng: np.random.Generator, manifest: ManifestWriter) -> None:
        require_values(ctx.category_names, CATEGORIES, "categories")
        demand = frames["inventory_demand"]

        # Confounder first: a genuine Black-Friday peak in every category.
        for start, end in PEAKS:
            peak = in_window(demand["date"], start, end)
            before = demand.loc[peak, "expected_demand"].sum()
            demand.loc[peak, "expected_demand"] *= 1 + PEAK_LIFT
            if start.startswith("2017"):
                manifest.record(PlantedFact(
                    plant=self.name, fact_id="E2-peak-confounder", role="confounder",
                    table="inventory_daily", column="units_sold", period_start=start, period_end=end,
                    dimension="product_category", dimension_values=("all",),
                    planted_effect="expected demand x 1.60 in every category (also 2016-11-21 to 2016-11-30)",
                    expected_pct=PEAK_LIFT, is_cause=False,
                    realised_pct=realised(before, demand.loc[peak, "expected_demand"].sum()),
                    note="A real seasonal peak in the same weeks; the baseline must not read it as the cause of the dip.",
                ))

        hit = in_window(demand["date"], START, END) & demand["category"].isin(CATEGORIES)
        demand.loc[hit, "forced_out"] = 1
        manifest.record(PlantedFact(
            plant=self.name, fact_id="E2-stockout", role="effect", table="inventory_daily",
            column="stockout_flag", period_start=START, period_end=END, dimension="product_category",
            dimension_values=CATEGORIES, planted_effect="stock forced to 0 and stockout_flag = 1 every day",
            expected_pct=None, is_cause=True,
        ))
        manifest.record(PlantedFact(
            plant=self.name, fact_id="E2-units", role="effect", table="inventory_daily",
            column="units_sold", period_start=START, period_end=END, dimension="product_category",
            dimension_values=CATEGORIES, planted_effect="units_sold = 0 while out of stock",
            expected_pct=-1.0, is_cause=False,
            note="Spec E2 names order and item count; real order_items are not modified, so the synthetic outcome is units_sold.",
        ))
