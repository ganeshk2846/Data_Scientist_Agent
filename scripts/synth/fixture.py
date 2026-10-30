"""A small, seeded database shaped exactly like the Olist snapshot.

The real ``brazil_ecommerce.sqlite`` is sourced separately and is not in the
repository, so tests and CI build this stand-in instead. It has the nine
real tables with the real column names and types, real Brazilian state
codes, real Olist category names, and the snapshot's monthly order shape
scaled down about 20x, **including its truncated edges** (2016-09, the
2016-11 gap, 2016-12, 2018-09 and 2018-10), so every completeness and
generator rule is exercised on the same traps as the real data.

It is a test fixture, not data: nothing here is a measurement of anything.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

# Real Olist monthly order counts divided by ~20, edges kept tiny.
FIXTURE_MONTHLY_ORDERS: dict[str, int] = {
    "2016-09": 1, "2016-10": 16, "2016-12": 1,
    "2017-01": 40, "2017-02": 89, "2017-03": 134, "2017-04": 120,
    "2017-05": 185, "2017-06": 162, "2017-07": 201, "2017-08": 217,
    "2017-09": 214, "2017-10": 232, "2017-11": 377, "2017-12": 284,
    "2018-01": 363, "2018-02": 336, "2018-03": 361, "2018-04": 347,
    "2018-05": 344, "2018-06": 308, "2018-07": 315, "2018-08": 326,
    "2018-09": 1, "2018-10": 1,
}

# State code, share of orders (approximately the real mix).
STATES: tuple[tuple[str, float], ...] = (
    ("SP", 0.42), ("RJ", 0.13), ("MG", 0.12), ("RS", 0.055), ("PR", 0.05),
    ("SC", 0.037), ("BA", 0.034), ("DF", 0.021), ("ES", 0.02), ("GO", 0.02),
    ("PE", 0.017), ("CE", 0.013), ("PA", 0.01), ("MT", 0.009), ("MA", 0.0075),
    ("MS", 0.0072), ("PB", 0.0054), ("PI", 0.005), ("RN", 0.0049), ("AL", 0.0041),
    ("SE", 0.0034), ("TO", 0.0028), ("RO", 0.0025), ("AM", 0.0015), ("AC", 0.0008),
    ("AP", 0.0007), ("RR", 0.0005),
)

# Real Olist category names with their English translation.
CATEGORIES: tuple[tuple[str, str, float], ...] = (
    ("cama_mesa_banho", "bed_bath_table", 0.13),
    ("beleza_saude", "health_beauty", 0.12),
    ("esporte_lazer", "sports_leisure", 0.11),
    ("moveis_decoracao", "furniture_decor", 0.10),
    ("informatica_acessorios", "computers_accessories", 0.09),
    ("utilidades_domesticas", "housewares", 0.08),
    ("relogios_presentes", "watches_gifts", 0.07),
    ("telefonia", "telephony", 0.06),
    ("ferramentas_jardim", "garden_tools", 0.06),
    ("automotivo", "auto", 0.05),
    ("brinquedos", "toys", 0.05),
    ("cool_stuff", "cool_stuff", 0.04),
    ("perfumaria", "perfumery", 0.04),
)

PAYMENT_TYPES = (("credit_card", 0.74), ("boleto", 0.19), ("voucher", 0.055), ("debit_card", 0.015))

_DDL = """
CREATE TABLE "customers" ("customer_id" TEXT, "customer_unique_id" TEXT, "customer_zip_code_prefix" INTEGER, "customer_city" TEXT, "customer_state" TEXT);
CREATE TABLE "geolocation" ("geolocation_zip_code_prefix" INTEGER, "geolocation_lat" REAL, "geolocation_lng" REAL, "geolocation_city" TEXT, "geolocation_state" TEXT);
CREATE TABLE "order_items" ("order_id" TEXT, "order_item_id" INTEGER, "product_id" TEXT, "seller_id" TEXT, "shipping_limit_date" TEXT, "price" REAL, "freight_value" REAL);
CREATE TABLE "order_payments" ("order_id" TEXT, "payment_sequential" INTEGER, "payment_type" TEXT, "payment_installments" INTEGER, "payment_value" REAL);
CREATE TABLE "order_reviews" ("review_id" TEXT, "order_id" TEXT, "review_score" INTEGER, "review_comment_title" TEXT, "review_comment_message" TEXT, "review_creation_date" TEXT, "review_answer_timestamp" TEXT);
CREATE TABLE "orders" ("order_id" TEXT, "customer_id" TEXT, "order_status" TEXT, "order_purchase_timestamp" TEXT, "order_approved_at" TEXT, "order_delivered_carrier_date" TEXT, "order_delivered_customer_date" TEXT, "order_estimated_delivery_date" TEXT);
CREATE TABLE "product_category_translation" ("product_category_name" TEXT, "product_category_name_english" TEXT);
CREATE TABLE "products" ("product_id" TEXT, "product_category_name" TEXT, "product_name_lenght" REAL, "product_description_lenght" REAL, "product_photos_qty" REAL, "product_weight_g" REAL, "product_length_cm" REAL, "product_height_cm" REAL, "product_width_cm" REAL);
CREATE TABLE "sellers" ("seller_id" TEXT, "seller_zip_code_prefix" INTEGER, "seller_city" TEXT, "seller_state" TEXT);
"""


def _hex(rng: np.random.Generator) -> str:
    return "".join(f"{value:02x}" for value in rng.integers(0, 256, size=16))


def _ts(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def build_fixture(path: Path, seed: int = 7) -> Path:
    """Write the fixture database to ``path`` (overwriting it) and return it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    rng = np.random.default_rng(seed)

    state_codes = [code for code, _ in STATES]
    state_p = np.array([share for _, share in STATES])
    state_p = state_p / state_p.sum()
    cat_names = [name for name, _, _ in CATEGORIES]
    cat_p = np.array([share for _, _, share in CATEGORIES])
    cat_p = cat_p / cat_p.sum()
    pay_names = [name for name, _ in PAYMENT_TYPES]
    pay_p = np.array([share for _, share in PAYMENT_TYPES])

    products = []
    product_price = {}
    product_cat = {}
    for index in range(260):
        product_id = _hex(rng)
        category = cat_names[rng.choice(len(cat_names), p=cat_p)] if index % 50 else None
        products.append((product_id, category, 40.0, 500.0, 2.0, 800.0, 20.0, 10.0, 15.0))
        product_price[product_id] = round(float(rng.lognormal(4.4, 0.6)), 2)
        product_cat[product_id] = category
    product_ids = [row[0] for row in products]

    sellers = [(_hex(rng), 1000 + i, "sao paulo", state_codes[rng.choice(len(state_codes), p=state_p)]) for i in range(40)]
    seller_ids = [row[0] for row in sellers]

    customers, orders, items, payments, reviews = [], [], [], [], []
    unique_pool: list[tuple[str, str]] = []  # (customer_unique_id, state)
    for period, count in FIXTURE_MONTHLY_ORDERS.items():
        year, month = (int(part) for part in period.split("-"))
        first = datetime(year, month, 1)
        days = ((first.replace(day=28) + timedelta(days=4)).replace(day=1) - first).days
        if period == "2018-10":
            days = 17
        for _ in range(count):
            moment = first + timedelta(days=int(rng.integers(0, days)), seconds=int(rng.integers(0, 86400)))
            if unique_pool and rng.random() < 0.03:
                unique_id, state = unique_pool[int(rng.integers(0, len(unique_pool)))]
            else:
                unique_id = _hex(rng)
                state = state_codes[rng.choice(len(state_codes), p=state_p)]
                unique_pool.append((unique_id, state))
            customer_id, order_id = _hex(rng), _hex(rng)
            customers.append((customer_id, unique_id, 1000 + int(rng.integers(0, 9000)), "cidade", state))
            roll = rng.random()
            if moment >= datetime(2018, 9, 1):
                status = "canceled" if roll < 0.5 else "shipped"
            else:
                status = "canceled" if roll < 0.007 else "unavailable" if roll < 0.013 else "delivered"
            delivered = moment + timedelta(days=int(rng.integers(5, 25)))
            orders.append((
                order_id, customer_id, status, _ts(moment), _ts(moment + timedelta(hours=2)),
                _ts(moment + timedelta(days=2)) if status == "delivered" else None,
                _ts(delivered) if status == "delivered" else None,
                _ts(moment + timedelta(days=24)),
            ))
            total = 0.0
            for item_index in range(1, 1 + (2 if rng.random() < 0.1 else 1)):
                product_id = product_ids[int(rng.integers(0, len(product_ids)))]
                price = product_price[product_id]
                freight = round(float(rng.uniform(8, 30)), 2)
                total += price + freight
                items.append((order_id, item_index, product_id, seller_ids[int(rng.integers(0, len(seller_ids)))],
                              _ts(moment + timedelta(days=3)), price, freight))
            payments.append((order_id, 1, pay_names[rng.choice(len(pay_names), p=pay_p)], int(rng.integers(1, 6)), round(total, 2)))
            if rng.random() < 0.97:
                score = int(rng.choice([1, 2, 3, 4, 5], p=[0.11, 0.03, 0.08, 0.19, 0.59]))
                reviews.append((_hex(rng), order_id, score, None, None,
                                _ts(delivered + timedelta(days=1)), _ts(delivered + timedelta(days=2))))

    geolocation = [(1000 + i, -23.5 + i * 0.01, -46.6, "sao paulo", "SP") for i in range(50)]
    translation = [(name, english) for name, english, _ in CATEGORIES]

    with sqlite3.connect(path) as conn:
        conn.executescript(_DDL)
        conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?)", customers)
        conn.executemany("INSERT INTO geolocation VALUES (?,?,?,?,?)", geolocation)
        conn.executemany("INSERT INTO order_items VALUES (?,?,?,?,?,?,?)", items)
        conn.executemany("INSERT INTO order_payments VALUES (?,?,?,?,?)", payments)
        conn.executemany("INSERT INTO order_reviews VALUES (?,?,?,?,?,?,?)", reviews)
        conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)", orders)
        conn.executemany("INSERT INTO product_category_translation VALUES (?,?)", translation)
        conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?)", products)
        conn.executemany("INSERT INTO sellers VALUES (?,?,?,?)", sellers)
    return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    print(build_fixture(args.path, args.seed))
