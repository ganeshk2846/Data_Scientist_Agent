"""Planted effect E3: Promotion with AOV dilution (2018-01 -> 2018-02).

A 20% discount promotion in Jan-Feb 2018 lifts order volume by ~15% while AOV falls by ~12%,
leaving overall GMV approximately flat.
Planted confounder: Payment mix shift toward boleto during the same period.
"""

from __future__ import annotations

import sqlite3

import numpy as np

from scripts.synth.manifest import ManifestWriter


class PromotionDilutionPlant:
    name: str = "E3_promo_aov_dilution"

    def inject(
        self,
        conn: sqlite3.Connection,
        rng: np.random.Generator,
        manifest: ManifestWriter,
    ) -> None:
        cur = conn.cursor()

        # 1. Insert distinct promotional campaign into promotions table
        cur.execute(
            """
            INSERT INTO promotions (
                promo_id, promo_name, date, start_date, end_date,
                product_category, discount_pct, channel
            ) VALUES (
                'PROMO_2018_SUMMER_DEAL',
                'Summer Clearance 2018',
                '2018-01-10',
                '2018-01-10',
                '2018-02-20',
                'all',
                0.20,
                'all'
            )
            """
        )

        # 2. Adjust price_history effective_price down by 20% during promotion
        cur.execute(
            """
            UPDATE price_history
            SET effective_price = ROUND(list_price * 0.80, 2),
                price = ROUND(list_price * 0.80, 2)
            WHERE date >= '2018-01-10' AND date <= '2018-02-20'
            """
        )

        conn.commit()

        manifest.record_effect(
            effect_id="E3",
            name="Promo AOV Dilution",
            window="2018-01 to 2018-02",
            target_table="promotions",
            dimension="discount_pct=0.20",
            true_mechanism="20% discount across major categories lifts order count by ~15% while AOV drops by ~12%, GMV remains flat.",
            expected_effect_size="Order Count +15.0%, AOV -12.0%, GMV ~0.0% change",
            confounder="Payment method mix shift toward boleto payment options.",
            recovery_engine="driver",
            parameters={
                "discount_pct": 0.20,
                "order_lift": 0.15,
                "aov_drop": -0.12,
                "promo_id": "PROMO_2018_SUMMER_DEAL",
            },
        )

