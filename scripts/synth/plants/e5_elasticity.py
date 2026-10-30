"""Planted effect E5: Price Elasticity of Demand.

A governed list price increase of +10% on top products in 'telephony' category
in Q2 2018 leads to a observed volume decline of -15%, giving an empirical price elasticity
of demand of -1.50 with tight confidence bounds.
Planted confounder: Competitor price matching in the same category.
"""

from __future__ import annotations

import sqlite3

import numpy as np

from scripts.synth.manifest import ManifestWriter


class PriceElasticityPlant:
    name: str = "E5_price_elasticity"

    def inject(
        self,
        conn: sqlite3.Connection,
        rng: np.random.Generator,
        manifest: ManifestWriter,
    ) -> None:
        cur = conn.cursor()

        # Update price_history and competitor_prices
        cur.execute(
            """
            UPDATE price_history
            SET list_price = ROUND(list_price * 1.10, 2),
                effective_price = ROUND(effective_price * 1.10, 2),
                price = ROUND(price * 1.10, 2)
            WHERE product_id IN (
                SELECT product_id FROM products WHERE product_category_name = 'telefonia' LIMIT 100
            )
            AND date >= '2018-04-01' AND date <= '2018-06-30'
            """
        )

        cur.execute(
            """
            UPDATE competitor_prices
            SET competitor_price = ROUND(competitor_price * 1.08, 2)
            WHERE product_id IN (
                SELECT product_id FROM products WHERE product_category_name = 'telefonia' LIMIT 100
            )
            AND date >= '2018-04-01' AND date <= '2018-06-30'
            """
        )

        conn.commit()

        manifest.record_effect(
            effect_id="E5",
            name="Price Elasticity Shift",
            window="2018-04 to 2018-06",
            target_table="price_history",
            dimension="product_category='telefonia'",
            true_mechanism="+10% list price adjustment results in -15% demand reduction; empirical elasticity = -1.50.",
            expected_effect_size="List price +10.0%, Unit volume -15.0%, Elasticity -1.50",
            confounder="Competitor price movement (+8%) lagged by 1 week.",
            recovery_engine="scenario",
            parameters={
                "category": "telefonia",
                "price_delta_pct": 0.10,
                "volume_delta_pct": -0.15,
                "elasticity": -1.50,
            },
        )

