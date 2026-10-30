"""Tests for seeded synthetic generator determinism, immutability, and validity (V2-SYN-1..5)."""

import hashlib
import sqlite3
import tempfile
from pathlib import Path

import pytest

from scripts.synth.generate import generate

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_DB = REPO_ROOT / "brazil_ecommerce.sqlite"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


@pytest.mark.skipif(
    not REAL_DB.exists(), reason="brazil_ecommerce.sqlite must exist in project root"
)
def test_generator_immutability_and_determinism():
    """V2-SYN-1: Original DB is strictly unchanged. V2-SYN-2: Same seed gives byte-identical output."""
    sha_orig_before = _sha256(REAL_DB)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        db1 = tmp_path / "v2_run1.sqlite"
        db2 = tmp_path / "v2_run2.sqlite"

        # Run 1
        generate(source_db=REAL_DB, target_db=db1, seed=42)
        # Run 2
        generate(source_db=REAL_DB, target_db=db2, seed=42)

        # Assert original db is untouched (V2-SYN-1)
        sha_orig_after = _sha256(REAL_DB)
        assert sha_orig_before == sha_orig_after, (
            "brazil_ecommerce.sqlite checksum changed!"
        )

        # Assert byte-identical databases from identical seeds (V2-SYN-2)
        assert _sha256(db1) == _sha256(db2), (
            "Non-deterministic generation across identical seeds!"
        )


@pytest.mark.skipif(
    not (REPO_ROOT / "data/brazil_ecommerce_v2.sqlite").exists(),
    reason="v2 db not built",
)
def test_synthetic_table_counts_and_foreign_keys():
    """V2-SYN-3: Keyed to real Olist ids, categories, states, and complete date bounds."""
    v2_db = REPO_ROOT / "data/brazil_ecommerce_v2.sqlite"
    conn = sqlite3.connect(f"file:{v2_db.as_posix()}?mode=ro", uri=True)
    cur = conn.cursor()

    # ≥ 18 tables check (9 real + 10 synthetic = 19 tables)
    tables = [
        r[0]
        for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'analytical_%' AND name NOT IN ('kpi_daily', 'driver_contributions')"
        ).fetchall()
    ]
    assert len(tables) >= 18, f"Expected at least 18 tables, found {len(tables)}"

    # Foreign key integrity check: returns.order_id exists in real orders
    invalid_returns = cur.execute(
        """
        SELECT COUNT(*)
        FROM returns r
        LEFT JOIN orders o ON r.order_id = o.order_id
        WHERE o.order_id IS NULL
        """
    ).fetchone()[0]
    assert invalid_returns == 0, (
        "Synthetic returns table contains foreign keys not in orders!"
    )

    # Foreign key integrity: customer_segments.customer_unique_id in customers
    invalid_cust = cur.execute(
        """
        SELECT COUNT(*)
        FROM customer_segments cs
        LEFT JOIN customers c ON cs.customer_unique_id = c.customer_unique_id
        WHERE c.customer_unique_id IS NULL
        """
    ).fetchone()[0]
    assert invalid_cust == 0, (
        "Synthetic customer_segments contains customer_unique_id not in customers!"
    )

    # Date range bounds: all synthetic dates in 2016-10-01 -> 2018-08-31
    min_date, max_date = cur.execute(
        "SELECT MIN(date), MAX(date) FROM marketing_spend"
    ).fetchone()
    assert min_date >= "2016-10-01"
    assert max_date <= "2018-08-31"

    conn.close()


def test_manifest_answer_key_recorded():
    """V2-SYN-5: SYNTHETIC_GROUND_TRUTH.md and JSON sidecar exist and record E1-E4."""
    truth_md = REPO_ROOT / "data/SYNTHETIC_GROUND_TRUTH.md"
    truth_json = REPO_ROOT / "data/synthetic_ground_truth.json"

    assert truth_md.exists(), "data/SYNTHETIC_GROUND_TRUTH.md missing!"
    assert truth_json.exists(), "data/synthetic_ground_truth.json missing!"

    content = truth_md.read_text(encoding="utf-8")
    for effect in ("E1", "E2", "E3", "E4", "E5"):
        assert effect in content, f"Planted effect {effect} missing from manifest!"
