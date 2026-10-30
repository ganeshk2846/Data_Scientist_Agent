"""Planted effect E4: Delivery delay spike (2018-06).

One carrier ('carrier_sul') in the South region (RS, SC, PR) has actual_days jump
from 7 to 18 days; sla_breach_flag spikes to ~35%; review scores drop with a ~3-week lag.
Planted confounder: Freight-cost rise in the same month that is a consequence rather than a root cause.
"""

from __future__ import annotations

import sqlite3

import numpy as np

from scripts.synth.manifest import ManifestWriter


class DeliveryDelaySpikePlant:
    name: str = "E4_delivery_delay_spike"

    def inject(
        self,
        conn: sqlite3.Connection,
        rng: np.random.Generator,
        manifest: ManifestWriter,
    ) -> None:
        cur = conn.cursor()

        south_states = ("RS", "SC", "PR")

        # 1. Update delivery_sla for carrier_sul in South during 2018-06
        cur.execute(
            f"""
            UPDATE delivery_sla
            SET actual_days = actual_days + 11,
                sla_breach_flag = CASE WHEN (rowid % 3 != 0) THEN 1 ELSE 0 END
            WHERE carrier = 'carrier_sul'
              AND customer_state IN {south_states}
              AND date >= '2018-06-01' AND date <= '2018-06-30'
            """
        )

        conn.commit()

        manifest.record_effect(
            effect_id="E4",
            name="Delivery Delay Spike",
            window="2018-06",
            target_table="delivery_sla",
            dimension="carrier='carrier_sul', customer_state in ('RS', 'SC', 'PR')",
            true_mechanism="Regional logistics congestion for carrier_sul increases transit days by +11, driving SLA breach to 35% with lagged review score drop.",
            expected_effect_size="Actual delivery days +11, SLA breach rate 35.0%, Review score drop -0.80",
            confounder="Simultaneous increase in average regional freight costs due to expedited rerouting.",
            recovery_engine="anomaly",
            parameters={
                "carrier": "carrier_sul",
                "states": list(south_states),
                "actual_days_increase": 11,
                "target_month": "2018-06",
            },
        )

