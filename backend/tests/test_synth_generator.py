"""Synthetic generator: read-only source, determinism, keys, planted effects (V2-SYN-1..5)."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.models import GroundTruthManifest  # noqa: E402
from scripts.synth.context import REAL_TABLES, open_read_only  # noqa: E402
from scripts.synth.fixture import build_fixture  # noqa: E402
from scripts.synth.generate import SCHEMAS, generate, sha256  # noqa: E402
from semantic.tables import TableRegistry  # noqa: E402

COMMITTED_ANSWER_KEY = REPO_ROOT / "data" / "SYNTHETIC_GROUND_TRUTH.md"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("synth")
    source = build_fixture(root / "olist.sqlite")
    before = sha256(source)
    result = generate(source, root / "v2.sqlite", markdown_path=root / "GROUND_TRUTH.md")
    return {"root": root, "source": source, "source_sha": before, "result": result}


def _q(path: Path, sql: str, *params):
    with sqlite3.connect(path) as conn:
        return conn.execute(sql, params).fetchall()


# --------------------------------------------------------------------------- #
# V2-SYN-1 / V2-SYN-2
# --------------------------------------------------------------------------- #


def test_source_is_unchanged_and_opened_read_only(built):
    assert sha256(built["source"]) == built["source_sha"] == built["result"].source_sha256
    with open_read_only(built["source"]) as conn, pytest.raises(sqlite3.OperationalError):
        conn.execute("CREATE TABLE x (a INTEGER)")


def test_refuses_to_write_onto_the_source(built):
    with pytest.raises(ValueError, match="V2-SYN-1"):
        generate(built["source"], built["source"], markdown_path=None)


def test_same_seed_is_byte_identical(built):
    again = generate(built["source"], built["root"] / "again.sqlite", markdown_path=None)
    assert again.database_sha256 == built["result"].database_sha256


def test_different_seed_differs(built):
    other = generate(built["source"], built["root"] / "other.sqlite", seed=1, markdown_path=None)
    assert other.database_sha256 != built["result"].database_sha256


# --------------------------------------------------------------------------- #
# Tables and keys (V2-SYN-3, acceptance 1.3/1.4)
# --------------------------------------------------------------------------- #


def test_nineteen_tables_and_registry_agrees(built):
    counts = built["result"].row_counts
    assert len(counts) == 19
    assert all(count > 0 for count in counts.values())
    registry = TableRegistry.default()
    assert {t.name for t in registry.synthetic()} == set(SCHEMAS)
    for name, columns in SCHEMAS.items():
        names = {column for column, _ in columns}
        assert set(registry.require(name).key_columns) <= names, name
        assert registry.require(name).date_column in names, name


def test_real_tables_are_copied_verbatim(built):
    target = built["result"].target
    for table in REAL_TABLES:
        assert _q(built["source"], f'SELECT * FROM "{table}" ORDER BY rowid') == _q(
            target, f'SELECT * FROM "{table}" ORDER BY rowid'
        ), table


@pytest.mark.parametrize(
    ("label", "sql"),
    [
        ("returns->order_items", "SELECT COUNT(*) FROM returns r LEFT JOIN order_items i ON i.order_id = r.order_id AND i.order_item_id = r.order_item_id WHERE i.order_id IS NULL"),
        ("price_history->products", "SELECT COUNT(*) FROM price_history p LEFT JOIN products x ON x.product_id = p.product_id WHERE x.product_id IS NULL"),
        ("competitor_prices->products", "SELECT COUNT(*) FROM competitor_prices p LEFT JOIN products x ON x.product_id = p.product_id WHERE x.product_id IS NULL"),
        ("segments->customers", "SELECT COUNT(*) FROM customer_segments s WHERE s.customer_unique_id NOT IN (SELECT customer_unique_id FROM customers)"),
        ("marketing category", "SELECT COUNT(*) FROM marketing_spend WHERE category NOT IN (SELECT product_category_name FROM products WHERE product_category_name IS NOT NULL)"),
        ("inventory category", "SELECT COUNT(*) FROM inventory_daily WHERE category NOT IN (SELECT product_category_name FROM products WHERE product_category_name IS NOT NULL)"),
        ("promotion category", "SELECT COUNT(*) FROM promotions WHERE category NOT IN (SELECT product_category_name FROM products WHERE product_category_name IS NOT NULL)"),
        ("traffic state", "SELECT COUNT(*) FROM web_traffic WHERE state NOT IN (SELECT customer_state FROM customers)"),
        ("sla state", "SELECT COUNT(*) FROM delivery_sla WHERE state NOT IN (SELECT customer_state FROM customers)"),
        ("target state", "SELECT COUNT(*) FROM regional_targets WHERE state NOT IN (SELECT customer_state FROM customers)"),
    ],
)
def test_every_synthetic_key_resolves_to_a_real_one(built, label, sql):
    assert _q(built["result"].target, sql) == [(0,)], label


@pytest.mark.parametrize(
    ("table", "column"),
    [(name, TableRegistry.default().require(name).date_column) for name in SCHEMAS],
)
def test_synthetic_dates_lie_in_the_real_months(built, table, column):
    (low, high), = _q(built["result"].target, f'SELECT MIN("{column}"), MAX("{column}") FROM "{table}"')
    assert "2016-09" <= low[:7] and high[:7] <= "2018-10", (table, low, high)


def test_covering_indexes_exist(built):
    names = {row[0] for row in _q(built["result"].target, "SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"idx_returns_item_cover", "idx_price_history_cover", "idx_order_items_cover"} <= names


# --------------------------------------------------------------------------- #
# Planted effects (acceptance 1.5, 1.6)
# --------------------------------------------------------------------------- #


def _facts(built) -> dict[str, dict]:
    sidecar = json.loads((built["result"].target.with_name("synthetic_ground_truth.json")).read_text())
    return {fact["fact_id"]: fact for fact in sidecar["facts"]}


def test_every_plant_has_an_effect_and_a_manifest_entry(built):
    facts = _facts(built)
    for plant in ("E1", "E2", "E3", "E4", "E5"):
        assert any(f["plant"] == plant and f["role"] == "effect" and f["is_cause"] for f in facts.values()), plant
    for plant in ("E1", "E2", "E3", "E4"):
        assert any(f["plant"] == plant and f["role"] == "confounder" for f in facts.values()), plant
    # Where a fact's realised size is measured on the same column it plants,
    # the two must agree. (E3-promo's realised value is the implied AOV
    # change, a different quantity, so it is excluded.)
    for fact in facts.values():
        if None in (fact["expected_pct"], fact["realised_pct"]) or fact["fact_id"] == "E3-promo":
            continue
        assert fact["realised_pct"] == pytest.approx(fact["expected_pct"], abs=0.002), fact["fact_id"]


def test_e1_sessions_drop_in_sp_and_rj_not_elsewhere(built):
    def ratio(state):
        (inside,), = _q(built["result"].target, "SELECT AVG(sessions) FROM web_traffic WHERE state = ? AND date BETWEEN '2018-03-15' AND '2018-06-14'", state)
        (before,), = _q(built["result"].target, "SELECT AVG(sessions) FROM web_traffic WHERE state = ? AND date BETWEEN '2018-01-15' AND '2018-03-14'", state)
        return inside / before

    assert ratio("SP") < 0.85 and ratio("RJ") < 0.85
    assert ratio("MG") > 0.95


def test_e2_stockouts_zero_the_top_categories(built):
    rows = _q(built["result"].target, "SELECT category, MIN(stockout_flag), MAX(units_sold) FROM inventory_daily WHERE date BETWEEN '2017-11-20' AND '2017-12-10' AND category IN ('cama_mesa_banho','beleza_saude','esporte_lazer') GROUP BY category")
    assert rows and all(flag == 1 and units == 0 for _, flag, units in rows)


def test_e3_promotion_and_conversion_lift(built):
    target = built["result"].target
    assert _q(target, "SELECT COUNT(*), MIN(discount_pct) FROM promotions WHERE promo_id LIKE 'E3-%'") == [(7, 20.0)]
    (inside,), = _q(target, "SELECT AVG(conversion_rate) FROM web_traffic WHERE date BETWEEN '2018-01-01' AND '2018-02-28'")
    (outside,), = _q(target, "SELECT AVG(conversion_rate) FROM web_traffic WHERE date BETWEEN '2017-10-01' AND '2017-12-31'")
    assert inside / outside == pytest.approx(1.15, abs=0.02)


def test_e4_delay_and_lagged_late_returns(built):
    target = built["result"].target
    (june,), = _q(target, "SELECT AVG(sla_breach_flag) FROM delivery_sla WHERE carrier = 'jadlog' AND state IN ('PR','SC','RS') AND date LIKE '2018-06-%'")
    (may,), = _q(target, "SELECT AVG(sla_breach_flag) FROM delivery_sla WHERE carrier = 'jadlog' AND state IN ('PR','SC','RS') AND date LIKE '2018-05-%'")
    assert june > 0.9 and may < 0.2
    late = _q(target, "SELECT COUNT(*) FROM returns r JOIN orders o ON o.order_id = r.order_id WHERE r.reason = 'late_delivery' AND r.return_date = date(o.order_purchase_timestamp, '+21 days')")
    assert late[0][0] >= 1


def test_e5_price_step_is_exactly_ten_percent(built):
    rows = _q(built["result"].target, """
        SELECT p.price, (SELECT q.price FROM price_history q WHERE q.product_id = p.product_id AND q.date < p.date ORDER BY q.date DESC LIMIT 1)
        FROM price_history p JOIN products x ON x.product_id = p.product_id
        WHERE x.product_category_name = 'moveis_decoracao' AND p.date = '2018-04-01'""")
    assert rows
    for new, old in rows:
        assert new == pytest.approx(old * 1.10, abs=0.011)
    assert _facts(built)["E5-units"]["expected_pct"] == pytest.approx(1.10 ** -1.5 - 1, abs=1e-6)


# --------------------------------------------------------------------------- #
# The answer key
# --------------------------------------------------------------------------- #


def test_committed_answer_key_matches_the_generator(built):
    assert COMMITTED_ANSWER_KEY.read_text() == (built["root"] / "GROUND_TRUTH.md").read_text()


def test_sidecar_holds_a_valid_v1_manifest_and_the_db_hash(built):
    sidecar = json.loads((built["result"].target.with_name("synthetic_ground_truth.json")).read_text())
    assert sidecar["database_sha256"] == built["result"].database_sha256
    manifest = GroundTruthManifest.model_validate(sidecar["v1_manifest"])
    assert manifest.anomalies and manifest.drivers and manifest.confounders


def test_answer_key_is_not_on_an_agent_readable_path():
    backend_src = REPO_ROOT / "backend" / "src"
    assert backend_src not in COMMITTED_ANSWER_KEY.parents
    for source in backend_src.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "SYNTHETIC_GROUND_TRUTH" not in text and "synthetic_ground_truth" not in text, source
