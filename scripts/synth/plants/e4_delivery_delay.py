"""E4 - one carrier's delivery times jump in the South; late returns follow."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..manifest import ManifestWriter, PlantedFact
from ._util import in_window, realised, require_values

START, END = "2018-06-01", "2018-06-30"
CARRIER = "jadlog"
STATES = ("PR", "SC", "RS")
EXTRA_DAYS = 6
LATE_RETURN_RATE = 0.06
RETURN_LAG_DAYS = 21
FREIGHT_RISE = 0.15


class DeliveryDelay:
    name = "E4"

    def inject(self, frames, ctx, rng: np.random.Generator, manifest: ManifestWriter) -> None:
        require_values(ctx.state_codes, STATES, "customer states")
        sla = frames["delivery_sla"]
        hit = in_window(sla["date"], START, END) & (sla["carrier"] == CARRIER) & sla["state"].isin(STATES)
        before = sla.loc[hit, "actual_days"].sum()
        sla.loc[hit, "actual_days"] = sla.loc[hit, "actual_days"] + EXTRA_DAYS
        sla["sla_breach_flag"] = (sla["actual_days"] > sla["promised_days"]).astype(np.int64)
        manifest.record(PlantedFact(
            plant=self.name, fact_id="E4-delay", role="effect", table="delivery_sla",
            column="actual_days", period_start=START, period_end=END, dimension="carrier",
            dimension_values=(CARRIER,), planted_effect=f"actual_days + {EXTRA_DAYS} for {CARRIER} in PR, SC and RS; sla_breach_flag recomputed",
            expected_pct=None, is_cause=True, realised_pct=realised(before, sla.loc[hit, "actual_days"].sum()),
        ))

        items = ctx.items
        south = items[
            (items["status"] == "delivered")
            & items["state"].isin(STATES)
            & (items["purchase"] >= pd.Timestamp(START))
            & (items["purchase"] < pd.Timestamp(END) + pd.Timedelta(days=1))
        ]
        existing = frames["returns"]
        taken = set(zip(existing["order_id"], existing["order_item_id"]))
        candidates = south[[(o, i) not in taken for o, i in zip(south["order_id"], south["order_item_id"])]]
        # An exact count, not a Bernoulli draw, so the effect is planted exactly.
        count = max(1, round(LATE_RETURN_RATE * len(candidates))) if len(candidates) else 0
        picks = np.sort(rng.choice(len(candidates), size=count, replace=False)) if count else []
        chosen = candidates.iloc[picks]
        added = pd.DataFrame({
            "order_id": chosen["order_id"],
            "order_item_id": chosen["order_item_id"].astype(np.int64),
            "return_date": (chosen["purchase"].dt.normalize() + pd.Timedelta(days=RETURN_LAG_DAYS)).dt.strftime("%Y-%m-%d"),
            "reason": "late_delivery",
            "refund_value": np.round(chosen["price"], 2),
        })
        frames["returns"] = pd.concat([existing, added], ignore_index=True)
        manifest.record(PlantedFact(
            plant=self.name, fact_id="E4-late-returns", role="effect", table="returns",
            column="reason", period_start=START, period_end=END, dimension="customer_state",
            dimension_values=STATES,
            planted_effect=f"extra late_delivery returns on exactly {LATE_RETURN_RATE:.0%} of delivered South items bought in the window, {RETURN_LAG_DAYS} days after purchase",
            expected_pct=None, is_cause=False, realised_rows=len(added),
            note=(
                "The ~3-week lagged outcome. Spec E4 names review_score; real order_reviews are not modified, "
                "so the synthetic outcome is late-delivery returns."
            ),
        ))

        freight = in_window(sla["date"], START, END) & sla["state"].isin(STATES)
        before = sla.loc[freight, "freight_cost"].sum()
        sla.loc[freight, "freight_cost"] = np.round(sla.loc[freight, "freight_cost"] * (1 + FREIGHT_RISE), 2)
        manifest.record(PlantedFact(
            plant=self.name, fact_id="E4-freight-confounder", role="confounder", table="delivery_sla",
            column="freight_cost", period_start=START, period_end=END, dimension="customer_state",
            dimension_values=STATES, planted_effect="freight_cost x 1.15 for every carrier in the South",
            expected_pct=FREIGHT_RISE, is_cause=False,
            realised_pct=realised(before, sla.loc[freight, "freight_cost"].sum()),
            note="A consequence of the disruption, not its cause: tests reverse-causation discipline.",
        ))
