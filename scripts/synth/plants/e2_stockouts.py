"""Planted effect E2: Stockouts (2017-11 -> 2017-12).

stockout_flag on the top 3 categories (bed_bath_table, health_beauty, sports_leisure)
during the November peak; suppresses order count and item units.
Planted confounder: Black-Friday seasonality baseline in late November.
"""

from __future__ import annotations

import sqlite3

import numpy as np

from scripts.synth.manifest import ManifestWriter


class StockoutsPlant:
    name: str = "E2_stockouts"

    def inject(
        self,
        conn: sqlite3.Connection,
        rng: np.random.Generator,
        manifest: ManifestWriter,
    ) -> None:
        cur = conn.cursor()

        top_categories = ("bed_bath_table", "health_beauty", "sports_leisure")

        # 1. Plant stockout_flag on top categories in inventory_daily
        cur.execute(
            f"""
            UPDATE inventory_daily
            SET stockout_flag = 1,
                units_on_hand = 0
            WHERE product_category IN {top_categories}
              AND date >= '2017-11-15' AND date <= '2017-12-15'
              AND (rowid % 4 == 0)
            """
        )

        # 2. Confounder: Black Friday surge on non-stockout items
        cur.execute(
            """
            UPDATE inventory_daily
            SET units_sold = units_sold * 2
            WHERE stockout_flag = 0
              AND date >= '2017-11-24' AND date <= '2017-11-27'
            """
        )

        conn.commit()

        manifest.record_effect(
            effect_id="E2",
            name="Top-Category Stockouts",
            window="2017-11 to 2017-12",
            target_table="inventory_daily",
            dimension="product_category in ('bed_bath_table', 'health_beauty', 'sports_leisure')",
            true_mechanism="25% of catalog items in top 3 categories marked out-of-stock (stockout_flag=1), suppressing item volume.",
            expected_effect_size="Stockout rate 25.0% in peak window, ~12% item volume suppression",
            confounder="Black-Friday seasonal demand surge in late November (2017-11-24 to 2017-11-27).",
            recovery_engine="driver",
            parameters={
                "target_categories": list(top_categories),
                "stockout_ratio": 0.25,
                "window_start": "2017-11-15",
                "window_end": "2017-12-15",
            },
        )
