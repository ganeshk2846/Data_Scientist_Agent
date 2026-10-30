"""Tests for precomputed analytical tables and engine provenance (AT-1..5, S5)."""

import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
V2_DB = REPO_ROOT / "data/brazil_ecommerce_v2.sqlite"


def test_s5_spikes_answered_in_one_read():
    """S5: 'What are the spikes across all months' answers from analytical_anomalies in one read."""
    assert V2_DB.exists(), "data/brazil_ecommerce_v2.sqlite must be generated"
    conn = sqlite3.connect(f"file:{V2_DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Query flagged spikes
    rows = cur.execute(
        """
        SELECT kpi, date, grain, dimension, dimension_value, value, expected, delta, delta_pct,
               direction, score, flagged, engine_version, catalog_version
        FROM analytical_anomalies
        WHERE flagged = 1 AND direction = 'spike'
        ORDER BY score DESC
        """
    ).fetchall()

    assert len(rows) > 0, "Expected at least one flagged spike anomaly"
    top_spike = rows[0]
    assert top_spike["flagged"] == 1
    assert top_spike["direction"] == "spike"
    assert top_spike["engine_version"] == "2.0.0"
    assert top_spike["catalog_version"] == "2026.10.1"

    conn.close()


def test_analytical_forecasts_anchor_and_mape():
    """AT-3, AT-4: Forecasts are anchored on complete period 2018-08 with valid MAPE."""
    conn = sqlite3.connect(f"file:{V2_DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    forecasts = cur.execute(
        """
        SELECT kpi, anchor_period, ds, yhat, yhat_lower, yhat_upper, model, mape
        FROM analytical_forecasts
        WHERE kpi = 'revenue'
        ORDER BY ds
        """
    ).fetchall()

    assert len(forecasts) == 4, (
        f"Expected 4 forecast horizon months, found {len(forecasts)}"
    )
    for f in forecasts:
        assert f["anchor_period"] == "2018-08", (
            f"Anchor period must be 2018-08, got {f['anchor_period']}"
        )
        assert f["yhat_lower"] <= f["yhat"] <= f["yhat_upper"]
        assert f["model"] in ("ets", "prophet")
        assert f["mape"] is None or f["mape"] > 0.0

    conn.close()
