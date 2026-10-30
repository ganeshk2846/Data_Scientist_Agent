"""Planted effect E1: Marketing cut (2018-03 -> 2018-05).

Paid-search spend cut ~40% in SP and RJ; traffic follows with a ~2-week lag.
Planted confounder: Category-mix shift in computers_accessories during the same window.
"""

from __future__ import annotations

import sqlite3

import numpy as np

from scripts.synth.manifest import ManifestWriter


class MarketingCutPlant:
    name: str = "E1_marketing_cut"

    def inject(
        self,
        conn: sqlite3.Connection,
        rng: np.random.Generator,
        manifest: ManifestWriter,
    ) -> None:
        cur = conn.cursor()

        # 1. Cut paid_search marketing spend in SP and RJ between 2018-03-01 and 2018-05-31 by ~40%
        cur.execute(
            """
            UPDATE marketing_spend
            SET spend = ROUND(spend * 0.60, 2),
                impressions = CAST(ROUND(impressions * 0.65) AS INTEGER),
                clicks = CAST(ROUND(clicks * 0.62) AS INTEGER)
            WHERE channel = 'paid_search'
              AND customer_state IN ('SP', 'RJ')
              AND date >= '2018-03-01' AND date <= '2018-05-31'
            """
        )

        # 2. Confounder: category-mix shift in computers_accessories
        # (Spend increased in direct/social to simulate a confounding mix shift)
        cur.execute(
            """
            UPDATE marketing_spend
            SET spend = ROUND(spend * 1.15, 2)
            WHERE category = 'computers_accessories'
              AND channel IN ('social', 'direct')
              AND date >= '2018-03-01' AND date <= '2018-05-31'
            """
        )

        # 3. Traffic drop with ~2-week lag (starting around 2018-03-15)
        cur.execute(
            """
            UPDATE web_traffic
            SET sessions = CAST(ROUND(sessions * 0.82) AS INTEGER),
                checkout_starts = CAST(ROUND(checkout_starts * 0.80) AS INTEGER)
            WHERE channel = 'paid_search'
              AND customer_state IN ('SP', 'RJ')
              AND date >= '2018-03-15' AND date <= '2018-06-15'
            """
        )

        conn.commit()

        manifest.record_effect(
            effect_id="E1",
            name="Marketing Cut",
            window="2018-03 to 2018-05",
            target_table="marketing_spend",
            dimension="channel='paid_search', customer_state in ('SP', 'RJ')",
            true_mechanism="Paid-search marketing spend reduced by 40% in SP and RJ; traffic follows with a ~2-week lag.",
            expected_effect_size="Spend -40.0%, Sessions -18.0%",
            confounder="Category-mix shift in computers_accessories channel spend during the same period.",
            recovery_engine="driver",
            parameters={
                "spend_reduction": 0.40,
                "lag_days": 14,
                "states": ["SP", "RJ"],
                "channel": "paid_search",
            },
        )
