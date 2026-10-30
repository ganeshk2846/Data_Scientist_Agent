"""E1 - paid-search cut; sessions in SP and RJ follow two weeks later."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..manifest import ManifestWriter, PlantedFact
from ._util import in_window, realised, require_values

START, END = "2018-03-01", "2018-05-31"
LAG_DAYS = 14
SPEND_CUT = -0.40
SESSION_DROP = -0.24
STATES = ("SP", "RJ")
MIX_SHIFT = 0.30
#: Fixed rather than measured, so the answer key does not depend on the source.
MIX_CATEGORIES = ("cama_mesa_banho", "beleza_saude", "esporte_lazer")


def _shift(day: str, days: int) -> str:
    return (pd.Timestamp(day) + pd.Timedelta(days=days)).strftime("%Y-%m-%d")


class MarketingCut:
    name = "E1"

    def inject(self, frames, ctx, rng: np.random.Generator, manifest: ManifestWriter) -> None:
        require_values(ctx.state_codes, STATES, "customer states")
        spend = frames["marketing_spend"]
        cut = in_window(spend["date"], START, END) & (spend["channel"] == "paid_search")
        before = spend.loc[cut, "spend"].sum()
        spend.loc[cut, "spend"] = np.round(spend.loc[cut, "spend"] * (1 + SPEND_CUT), 2)
        manifest.record(PlantedFact(
            plant=self.name, fact_id="E1-spend", role="effect", table="marketing_spend",
            column="spend", period_start=START, period_end=END, dimension="channel",
            dimension_values=("paid_search",), planted_effect="paid_search spend x 0.60, every category",
            expected_pct=SPEND_CUT, is_cause=True, realised_pct=realised(before, spend.loc[cut, "spend"].sum()),
        ))

        traffic = frames["web_traffic"]
        lag_start, lag_end = _shift(START, LAG_DAYS), _shift(END, LAG_DAYS)
        hit = in_window(traffic["date"], lag_start, lag_end) & traffic["state"].isin(STATES)
        before = traffic.loc[hit, "sessions"].sum()
        traffic.loc[hit, "sessions"] = np.round(traffic.loc[hit, "sessions"] * (1 + SESSION_DROP)).astype(np.int64)
        manifest.record(PlantedFact(
            plant=self.name, fact_id="E1-sessions", role="effect", table="web_traffic",
            column="sessions", period_start=lag_start, period_end=lag_end, dimension="customer_state",
            dimension_values=STATES, planted_effect=f"sessions x 0.76, lagged {LAG_DAYS} days behind the cut",
            expected_pct=SESSION_DROP, is_cause=False, realised_pct=realised(before, traffic.loc[hit, "sessions"].sum()),
            note="Outcome of the cut. Spec E1 also names order count; real orders are not modified, so the synthetic outcome is sessions.",
        ))

        # Confounder: a category-mix shift in social spend, same window, total unchanged.
        social = in_window(spend["date"], START, END) & (spend["channel"] == "social")
        require_values(ctx.category_names, MIX_CATEGORIES, "categories")
        top = list(MIX_CATEGORIES)
        is_top = spend["category"].isin(top)
        shrink, grow = social & is_top, social & ~is_top
        before_top = spend.loc[shrink, "spend"].sum()
        moved_by_day = spend.loc[shrink].groupby("date")["spend"].sum() * MIX_SHIFT
        spend.loc[shrink, "spend"] = spend.loc[shrink, "spend"] * (1 - MIX_SHIFT)
        other_by_day = spend.loc[grow].groupby("date")["spend"].sum()
        dates = spend.loc[grow, "date"]
        weight = spend.loc[grow, "spend"] / dates.map(other_by_day)
        spend.loc[grow, "spend"] = spend.loc[grow, "spend"] + dates.map(moved_by_day) * weight
        spend["spend"] = np.round(spend["spend"], 2)
        manifest.record(PlantedFact(
            plant=self.name, fact_id="E1-mix-confounder", role="confounder", table="marketing_spend",
            column="spend", period_start=START, period_end=END, dimension="product_category",
            dimension_values=tuple(top), planted_effect="social spend share of the top 3 categories x 0.70, moved to the other categories; social total unchanged",
            expected_pct=-MIX_SHIFT, is_cause=False,
            realised_pct=realised(before_top, spend.loc[social & is_top, "spend"].sum()),
            note="Moves in the same window as the decline but does not drive sessions; must not be reported as the driver.",
        ))
