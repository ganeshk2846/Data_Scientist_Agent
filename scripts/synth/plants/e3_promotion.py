"""E3 - a 20% promotion lifts orders ~15% while AOV falls ~12%."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..manifest import ManifestWriter, PlantedFact
from ._util import in_window, realised, require_values

START, END = "2018-01-01", "2018-02-28"
DISCOUNT = 20.0
ORDER_LIFT = 0.15
BOLETO_SHIFT = 0.08
CATEGORIES = (
    "cama_mesa_banho",
    "beleza_saude",
    "esporte_lazer",
    "moveis_decoracao",
    "informatica_acessorios",
    "utilidades_domesticas",
    "relogios_presentes",
)


class Promotion:
    name = "E3"

    def inject(self, frames, ctx, rng: np.random.Generator, manifest: ManifestWriter) -> None:
        require_values(ctx.category_names, CATEGORIES, "categories")
        promos = frames["promotions"]
        added = pd.DataFrame({
            "promo_id": [f"E3-{i + 1:02d}" for i in range(len(CATEGORIES))],
            "category": list(CATEGORIES),
            "start_date": START,
            "end_date": END,
            "discount_pct": DISCOUNT,
        })
        frames["promotions"] = pd.concat([promos, added], ignore_index=True)
        share = float(ctx.categories.set_index("category").loc[list(CATEGORIES), "gmv_share"].sum())
        implied_aov = round(-DISCOUNT / 100 * share, 6)
        manifest.record(PlantedFact(
            plant=self.name, fact_id="E3-promo", role="effect", table="promotions",
            column="discount_pct", period_start=START, period_end=END, dimension="product_category",
            dimension_values=CATEGORIES, planted_effect="one 20% promotion per listed category",
            expected_pct=-DISCOUNT / 100, is_cause=True, realised_pct=implied_aov,
            note=(
                "Average selling price falls by 20% x the promoted categories' share of GMV; that share is "
                "taken from the source at build time, so realised_pct (the implied AOV change, about -12% on "
                "the real snapshot) is in the sidecar. Requires the ratio decomposition: AOV moves for a "
                "price/mix reason, not a volume reason."
            ),
        ))

        traffic = frames["web_traffic"]
        hit = in_window(traffic["date"], START, END)
        converted = (traffic["sessions"] * traffic["conversion_rate"])
        before = converted[hit].sum()
        traffic.loc[hit, "conversion_rate"] = traffic.loc[hit, "conversion_rate"] * (1 + ORDER_LIFT)
        after = (traffic["sessions"] * traffic["conversion_rate"])[hit].sum()
        manifest.record(PlantedFact(
            plant=self.name, fact_id="E3-orders", role="effect", table="web_traffic",
            column="conversion_rate", period_start=START, period_end=END, dimension="customer_state",
            dimension_values=("all",), planted_effect="conversion_rate x 1.15 in every state (orders = sessions x conversion)",
            expected_pct=ORDER_LIFT, is_cause=False, realised_pct=realised(before, after),
            note="GMV is roughly flat: (1 + 15%) x (1 - 12%) is about +1%.",
        ))

        demand = frames["inventory_demand"]
        lift = in_window(demand["date"], START, END) & demand["category"].isin(CATEGORIES)
        before = demand.loc[lift, "expected_demand"].sum()
        demand.loc[lift, "expected_demand"] *= 1 + ORDER_LIFT
        manifest.record(PlantedFact(
            plant=self.name, fact_id="E3-units", role="effect", table="inventory_daily",
            column="units_sold", period_start=START, period_end=END, dimension="product_category",
            dimension_values=CATEGORIES, planted_effect="expected demand x 1.15 in promoted categories",
            expected_pct=ORDER_LIFT, is_cause=False,
            realised_pct=realised(before, demand.loc[lift, "expected_demand"].sum()),
            note="A promotion is not a list-price change: an elasticity fit must control for promotions.",
        ))

        before = traffic.loc[hit, "boleto_share"].mean()
        traffic.loc[hit, "boleto_share"] = np.clip(traffic.loc[hit, "boleto_share"] + BOLETO_SHIFT, 0.0, 1.0)
        manifest.record(PlantedFact(
            plant=self.name, fact_id="E3-boleto-confounder", role="confounder", table="web_traffic",
            column="boleto_share", period_start=START, period_end=END, dimension="payment_type",
            dimension_values=("boleto",), planted_effect="boleto checkout share +8 points in every state",
            expected_pct=None, is_cause=False,
            realised_pct=realised(before, traffic.loc[hit, "boleto_share"].mean()),
            note="Payment-mix shift in the same window; it does not cause the AOV fall. Real order_payments are not modified.",
        ))
