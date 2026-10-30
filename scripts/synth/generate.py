"""Seeded, deterministic synthetic data generator for V2 Data Layer (V2-SYN-1..5).

Copies real Olist tables from brazil_ecommerce.sqlite (read-only mode) into
data/brazil_ecommerce_v2.sqlite, synthesizes 10 operational indicator tables
keyed to real entities and complete periods (2016-10 -> 2018-08), injects
planted causal effects E1-E4 + elasticity, and writes the ground-truth manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

# Add project root to sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np

from scripts.synth.manifest import ManifestWriter
from scripts.synth.plants.e1_marketing import MarketingCutPlant
from scripts.synth.plants.e2_stockouts import StockoutsPlant
from scripts.synth.plants.e3_promo import PromotionDilutionPlant
from scripts.synth.plants.e4_delivery import DeliveryDelaySpikePlant
from scripts.synth.plants.e5_elasticity import PriceElasticityPlant

REAL_TABLES = (
    "customers",
    "geolocation",
    "order_items",
    "order_payments",
    "order_reviews",
    "orders",
    "product_category_translation",
    "products",
    "sellers",
)

CHANNELS = ("paid_search", "organic_search", "social", "email", "direct", "display")
CARRIERS = ("correios_pac", "correios_sedex", "loggi_express", "carrier_sul")
SEGMENTS = ("Champions", "Loyal", "At Risk", "Hibernating", "New")
LTV_BANDS = ("Tier 1 (High)", "Tier 2 (Mid)", "Tier 3 (Standard)")
RETURN_REASONS = (
    "defective_item",
    "wrong_size",
    "item_not_as_described",
    "late_delivery",
    "buyer_remorse",
)


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _date_range(start_date: date, end_date: date) -> list[str]:
    days = (end_date - start_date).days + 1
    return [(start_date + timedelta(days=i)).isoformat() for i in range(days)]


def generate(
    source_db: str | Path = "brazil_ecommerce.sqlite",
    target_db: str | Path = "data/brazil_ecommerce_v2.sqlite",
    seed: int = 42,
) -> Path:
    source_path = Path(source_db).resolve()
    target_path = Path(target_db).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if not source_path.exists():
        raise FileNotFoundError(f"Source database not found at {source_path}")

    # V2-SYN-1: Read-only check and checksum preservation
    sha_before = _compute_sha256(source_path)

    # Remove existing target if rebuilding
    if target_path.exists():
        target_path.unlink()

    # Read from source strictly read-only
    ro_uri = f"file:{source_path.as_posix()}?mode=ro"
    src_conn = sqlite3.connect(ro_uri, uri=True)
    dst_conn = sqlite3.connect(target_path)

    # 1. Copy real tables verbatim
    print(f"[*] Copying 9 real Olist tables to {target_path}...")
    src_cur = src_conn.cursor()
    dst_cur = dst_conn.cursor()

    for table in REAL_TABLES:
        ddl = src_cur.execute(
            f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'"
        ).fetchone()
        if ddl and ddl[0]:
            dst_cur.execute(ddl[0])
            rows = src_cur.execute(f"SELECT * FROM {table}").fetchall()
            if rows:
                placeholders = ",".join("?" * len(rows[0]))
                dst_cur.executemany(
                    f"INSERT INTO {table} VALUES ({placeholders})", rows
                )

    dst_conn.commit()

    # 2. Extract reference entities for realistic foreign key binding (V2-SYN-3)
    categories = [
        r[0]
        for r in src_cur.execute(
            "SELECT DISTINCT product_category_name FROM products WHERE product_category_name IS NOT NULL"
        ).fetchall()
    ]
    states = [
        r[0]
        for r in src_cur.execute(
            "SELECT DISTINCT customer_state FROM customers WHERE customer_state IS NOT NULL"
        ).fetchall()
    ]
    product_ids = [
        r[0]
        for r in src_cur.execute(
            "SELECT product_id FROM products LIMIT 5000"
        ).fetchall()
    ]
    customer_uniques = [
        r[0]
        for r in src_cur.execute(
            "SELECT DISTINCT customer_unique_id FROM customers LIMIT 20000"
        ).fetchall()
    ]
    order_item_tuples = [
        (r[0], r[1], r[2])
        for r in src_cur.execute(
            "SELECT oi.order_id, oi.order_item_id, oi.price FROM order_items oi JOIN orders o ON oi.order_id = o.order_id WHERE o.order_status = 'delivered' LIMIT 15000"
        ).fetchall()
    ]

    src_conn.close()

    # Verify source db was never touched
    sha_after = _compute_sha256(source_path)
    if sha_before != sha_after:
        raise RuntimeError(
            "CRITICAL: Source database was modified during generation! (V2-SYN-1)"
        )

    # 3. Deterministic initialization
    rng = np.random.default_rng(seed)
    dates = _date_range(date(2016, 10, 1), date(2018, 8, 31))

    print("[*] Generating 10 synthetic operational tables...")

    # Table 1: marketing_spend
    dst_cur.execute(
        """
        CREATE TABLE marketing_spend (
            date TEXT NOT NULL,
            channel TEXT NOT NULL,
            category TEXT NOT NULL,
            customer_state TEXT NOT NULL,
            spend REAL NOT NULL,
            impressions INTEGER NOT NULL,
            clicks INTEGER NOT NULL
        )
        """
    )
    marketing_rows = []
    top_states = ("SP", "RJ", "MG", "RS", "PR")
    sample_categories = categories[:10]
    for d in dates[::2]:  # every 2 days
        for ch in ("paid_search", "social", "email", "direct"):
            for st in top_states:
                cat = sample_categories[int(rng.integers(0, len(sample_categories)))]
                spend = float(round(rng.uniform(150.0, 1200.0), 2))
                cpc = rng.uniform(0.5, 1.8)
                clicks = int(spend / cpc)
                impressions = clicks * int(rng.integers(15, 45))
                marketing_rows.append((d, ch, cat, st, spend, impressions, clicks))

    dst_cur.executemany(
        "INSERT INTO marketing_spend VALUES (?,?,?,?,?,?,?)", marketing_rows
    )

    # Table 2: promotions
    dst_cur.execute(
        """
        CREATE TABLE promotions (
            promo_id TEXT PRIMARY KEY,
            promo_name TEXT NOT NULL,
            date TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            product_category TEXT NOT NULL,
            discount_pct REAL NOT NULL,
            channel TEXT NOT NULL
        )
        """
    )
    promo_rows = [
        (
            "PROMO_BLACK_FRIDAY_2017",
            "Black Friday 2017",
            "2017-11-20",
            "2017-11-20",
            "2017-11-28",
            "all",
            0.25,
            "all",
        ),
        (
            "PROMO_EASTER_2017",
            "Easter 2017 Deals",
            "2017-04-10",
            "2017-04-10",
            "2017-04-18",
            "utilidades_domesticas",
            0.15,
            "social",
        ),
        (
            "PROMO_TECH_MADNESS_2017",
            "Tech Week 2017",
            "2017-08-01",
            "2017-08-01",
            "2017-08-08",
            "informatica_acessorios",
            0.20,
            "paid_search",
        ),
        (
            "PROMO_NEW_YEAR_2018",
            "New Year Kickoff 2018",
            "2018-01-02",
            "2018-01-02",
            "2018-01-09",
            "beleza_saude",
            0.10,
            "email",
        ),
        (
            "PROMO_CARNIVAL_2018",
            "Carnival Fiesta 2018",
            "2018-02-08",
            "2018-02-08",
            "2018-02-15",
            "esporte_lazer",
            0.15,
            "social",
        ),
    ]
    dst_cur.executemany("INSERT INTO promotions VALUES (?,?,?,?,?,?,?,?)", promo_rows)

    # Table 3: inventory_daily
    dst_cur.execute(
        """
        CREATE TABLE inventory_daily (
            date TEXT NOT NULL,
            product_id TEXT NOT NULL,
            product_category TEXT NOT NULL,
            units_on_hand INTEGER NOT NULL,
            units_sold INTEGER NOT NULL,
            stockout_flag INTEGER NOT NULL
        )
        """
    )
    inv_products = product_ids[:300]
    inv_rows = []
    # Sample dates once weekly across window
    for d in dates[::7]:
        for pid in inv_products:
            cat = categories[int(rng.integers(0, len(categories)))]
            on_hand = int(rng.integers(5, 120))
            sold = int(rng.integers(0, 8))
            inv_rows.append((d, pid, cat, on_hand, sold, 0))
    dst_cur.executemany("INSERT INTO inventory_daily VALUES (?,?,?,?,?,?)", inv_rows)

    # Table 4: web_traffic
    dst_cur.execute(
        """
        CREATE TABLE web_traffic (
            date TEXT NOT NULL,
            channel TEXT NOT NULL,
            customer_state TEXT NOT NULL,
            sessions INTEGER NOT NULL,
            conversion_rate REAL NOT NULL,
            bounce_rate REAL NOT NULL,
            add_to_cart INTEGER NOT NULL,
            checkout_starts INTEGER NOT NULL
        )
        """
    )
    traffic_rows = []
    for d in dates:
        for ch in ("paid_search", "organic_search", "social", "direct"):
            for st in ("SP", "RJ", "MG"):
                sessions = int(rng.integers(120, 1800))
                conv = float(round(rng.uniform(0.015, 0.045), 4))
                bounce = float(round(rng.uniform(0.35, 0.55), 4))
                cart = int(sessions * rng.uniform(0.08, 0.16))
                chk = int(cart * rng.uniform(0.4, 0.7))
                traffic_rows.append((d, ch, st, sessions, conv, bounce, cart, chk))
    dst_cur.executemany(
        "INSERT INTO web_traffic VALUES (?,?,?,?,?,?,?,?)", traffic_rows
    )

    # Table 5: price_history
    dst_cur.execute(
        """
        CREATE TABLE price_history (
            product_id TEXT NOT NULL,
            date TEXT NOT NULL,
            list_price REAL NOT NULL,
            effective_price REAL NOT NULL,
            price REAL NOT NULL
        )
        """
    )
    price_rows = []
    for pid in inv_products[:150]:
        base_p = float(round(rng.uniform(25.0, 450.0), 2))
        for d in dates[::14]:
            eff_p = base_p
            price_rows.append((pid, d, base_p, eff_p, eff_p))
    dst_cur.executemany("INSERT INTO price_history VALUES (?,?,?,?,?)", price_rows)

    # Table 6: competitor_prices
    dst_cur.execute(
        """
        CREATE TABLE competitor_prices (
            date TEXT NOT NULL,
            product_id TEXT NOT NULL,
            competitor_price REAL NOT NULL,
            competitor_name TEXT NOT NULL
        )
        """
    )
    comp_names = ("MercadoLivre_Top", "Amazon_BR", "MagazineLuiza", "B2W_Retail")
    comp_rows = []
    for pid in inv_products[:150]:
        for d in dates[::28]:
            cname = comp_names[int(rng.integers(0, len(comp_names)))]
            cp = float(round(rng.uniform(24.0, 440.0), 2))
            comp_rows.append((d, pid, cp, cname))
    dst_cur.executemany("INSERT INTO competitor_prices VALUES (?,?,?,?)", comp_rows)

    # Table 7: customer_segments
    dst_cur.execute(
        """
        CREATE TABLE customer_segments (
            customer_unique_id TEXT PRIMARY KEY,
            segment TEXT NOT NULL,
            ltv_band TEXT NOT NULL,
            acquisition_channel TEXT NOT NULL,
            assigned_at TEXT NOT NULL
        )
        """
    )
    cust_rows = []
    for cid in customer_uniques:
        seg = SEGMENTS[int(rng.integers(0, len(SEGMENTS)))]
        ltv = LTV_BANDS[int(rng.integers(0, len(LTV_BANDS)))]
        ch = CHANNELS[int(rng.integers(0, len(CHANNELS)))]
        assigned = "2018-01-01"
        cust_rows.append((cid, seg, ltv, ch, assigned))
    dst_cur.executemany("INSERT INTO customer_segments VALUES (?,?,?,?,?)", cust_rows)

    # Table 8: regional_targets
    dst_cur.execute(
        """
        CREATE TABLE regional_targets (
            month TEXT NOT NULL,
            customer_state TEXT NOT NULL,
            metric_id TEXT NOT NULL,
            target_value REAL NOT NULL,
            revenue_target REAL NOT NULL
        )
        """
    )
    months = sorted(list({d[:7] for d in dates}))
    target_rows = []
    for m in months:
        for st in states:
            base_rev = (
                120000.0 if st == "SP" else (45000.0 if st in ("RJ", "MG") else 12000.0)
            )
            target_rev = float(round(base_rev * rng.uniform(0.95, 1.25), 2))
            target_rows.append((m, st, "revenue", target_rev, target_rev))
            target_orders = float(
                round((target_rev / 135.0) * rng.uniform(0.95, 1.05), 1)
            )
            target_rows.append((m, st, "order_count", target_orders, target_rev))
    dst_cur.executemany("INSERT INTO regional_targets VALUES (?,?,?,?,?)", target_rows)

    # Table 9: returns
    dst_cur.execute(
        """
        CREATE TABLE returns (
            order_id TEXT NOT NULL,
            order_item_id INTEGER NOT NULL,
            return_date TEXT NOT NULL,
            reason TEXT NOT NULL,
            refund_value REAL NOT NULL
        )
        """
    )
    return_rows = []
    for oid, item_id, price in order_item_tuples:
        if rng.random() < 0.045:  # ~4.5% return rate
            rdate = "2018-03-12"
            reason = RETURN_REASONS[int(rng.integers(0, len(RETURN_REASONS)))]
            return_rows.append((oid, item_id, rdate, reason, float(price)))
    dst_cur.executemany("INSERT INTO returns VALUES (?,?,?,?,?)", return_rows)

    # Table 10: delivery_sla
    dst_cur.execute(
        """
        CREATE TABLE delivery_sla (
            date TEXT NOT NULL,
            carrier TEXT NOT NULL,
            customer_state TEXT NOT NULL,
            promised_days INTEGER NOT NULL,
            actual_days INTEGER NOT NULL,
            sla_breach_flag INTEGER NOT NULL
        )
        """
    )
    sla_rows = []
    for d in dates[::3]:
        for car in CARRIERS:
            for st in ("SP", "RJ", "MG", "RS", "SC", "PR"):
                promised = int(rng.integers(5, 12))
                actual = int(promised + rng.integers(-2, 3))
                breach = 1 if actual > promised else 0
                sla_rows.append((d, car, st, promised, actual, breach))
    dst_cur.executemany("INSERT INTO delivery_sla VALUES (?,?,?,?,?,?)", sla_rows)

    dst_conn.commit()

    # 4. Inject planted effects E1-E5
    print("[*] Injecting planted effects E1-E5...")
    manifest = ManifestWriter()
    plugins = [
        MarketingCutPlant(),
        StockoutsPlant(),
        PromotionDilutionPlant(),
        DeliveryDelaySpikePlant(),
        PriceElasticityPlant(),
    ]
    for plugin in plugins:
        plugin.inject(dst_conn, rng, manifest)

    # 5. Build covering indexes for join keys
    print("[*] Creating covering indexes for synthetic join keys...")
    indexes = [
        "CREATE INDEX idx_synth_marketing_date ON marketing_spend(date)",
        "CREATE INDEX idx_synth_marketing_channel_state ON marketing_spend(channel, customer_state)",
        "CREATE INDEX idx_synth_inventory_date_prod ON inventory_daily(date, product_id)",
        "CREATE INDEX idx_synth_inventory_stockout ON inventory_daily(stockout_flag)",
        "CREATE INDEX idx_synth_traffic_date_channel ON web_traffic(date, channel)",
        "CREATE INDEX idx_synth_price_product_date ON price_history(product_id, date)",
        "CREATE INDEX idx_synth_competitor_prod_date ON competitor_prices(product_id, date)",
        "CREATE INDEX idx_synth_cust_seg_id ON customer_segments(customer_unique_id)",
        "CREATE INDEX idx_synth_regional_month_st ON regional_targets(month, customer_state)",
        "CREATE INDEX idx_synth_returns_order ON returns(order_id, order_item_id)",
        "CREATE INDEX idx_synth_sla_date_carrier ON delivery_sla(date, carrier, customer_state)",
    ]
    for idx_sql in indexes:
        dst_cur.execute(idx_sql)

    dst_conn.commit()
    dst_conn.close()

    # 6. Write manifest answer key to data/
    data_dir = target_path.parent
    md_path, json_path = manifest.write(data_dir)
    print(f"[*] Evaluation answer key written to {md_path} and {json_path}")

    # Final checksum verification
    sha_final = _compute_sha256(source_path)
    assert sha_before == sha_final, "Source database was modified!"
    print(f"[+] Successfully generated {target_path} (reproducible seed={seed}).")
    return target_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deterministic Synthetic Data Generator (Track 1)"
    )
    parser.add_argument(
        "--source",
        default="brazil_ecommerce.sqlite",
        help="Path to real SQLite database",
    )
    parser.add_argument(
        "--target",
        default="data/brazil_ecommerce_v2.sqlite",
        help="Path to output database",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="RNG seed for reproducibility"
    )
    args = parser.parse_args()

    generate(source_db=args.source, target_db=args.target, seed=args.seed)


if __name__ == "__main__":
    main()
