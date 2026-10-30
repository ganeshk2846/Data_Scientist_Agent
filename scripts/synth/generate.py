"""Seeded synthetic-layer generator (V2-SYN-1..5; build plan Track 1).

    python scripts/synth/generate.py [--source brazil_ecommerce.sqlite] \
        [--target data/brazil_ecommerce_v2.sqlite] [--seed 20261030]

* Opens the real snapshot **read-only** (``?mode=ro``) and checks its SHA-256
  is unchanged at the end (V2-SYN-1). Refuses to write onto the source.
* Copies the nine real tables verbatim, then writes the ten synthetic tables
  keyed to real ids, categories, states and months (V2-SYN-3).
* Applies the planted effects E1-E5 through synthetic tables only and writes
  the answer key (``data/SYNTHETIC_GROUND_TRUTH.md`` + JSON sidecar).
* Adds covering indexes for the new join keys (``docs/DB_INDEXES.md``).
* Same source + same seed => byte-identical database (V2-SYN-2).

pandas and numpy only. SDV and Mimesis are not used: every synthetic table
here is a driver table whose effect sizes must be planted exactly, and none
needs synthetic names or addresses.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "scripts.synth"

from . import base  # noqa: E402
from .context import REAL_TABLES, load_context, open_read_only  # noqa: E402
from .manifest import ManifestWriter, write_outputs  # noqa: E402
from .plants import PLANTS  # noqa: E402

GENERATOR_VERSION = "v2.0.0"
DEFAULT_SEED = 20261030
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = REPO_ROOT / "brazil_ecommerce.sqlite"
DEFAULT_TARGET = REPO_ROOT / "data" / "brazil_ecommerce_v2.sqlite"
DEFAULT_MARKDOWN = REPO_ROOT / "data" / "SYNTHETIC_GROUND_TRUTH.md"

#: Column order and SQLite types of every synthetic table.
SCHEMAS: dict[str, tuple[tuple[str, str], ...]] = {
    "marketing_spend": (("date", "TEXT"), ("channel", "TEXT"), ("category", "TEXT"), ("spend", "REAL")),
    "promotions": (("promo_id", "TEXT"), ("category", "TEXT"), ("start_date", "TEXT"), ("end_date", "TEXT"), ("discount_pct", "REAL")),
    "inventory_daily": (("date", "TEXT"), ("category", "TEXT"), ("stock_on_hand", "INTEGER"), ("units_sold", "INTEGER"), ("stockout_flag", "INTEGER")),
    "web_traffic": (("date", "TEXT"), ("state", "TEXT"), ("sessions", "INTEGER"), ("conversion_rate", "REAL"), ("boleto_share", "REAL")),
    "price_history": (("product_id", "TEXT"), ("date", "TEXT"), ("price", "REAL"), ("unit_cost", "REAL")),
    "competitor_prices": (("product_id", "TEXT"), ("date", "TEXT"), ("competitor", "TEXT"), ("price", "REAL")),
    "customer_segments": (("customer_unique_id", "TEXT"), ("segment", "TEXT"), ("ltv_band", "TEXT"), ("acquisition_channel", "TEXT"), ("assigned_at", "TEXT")),
    "regional_targets": (("state", "TEXT"), ("month", "TEXT"), ("revenue_target", "REAL")),
    "returns": (("order_id", "TEXT"), ("order_item_id", "INTEGER"), ("return_date", "TEXT"), ("reason", "TEXT"), ("refund_value", "REAL")),
    "delivery_sla": (("date", "TEXT"), ("carrier", "TEXT"), ("state", "TEXT"), ("promised_days", "INTEGER"), ("actual_days", "INTEGER"), ("sla_breach_flag", "INTEGER"), ("freight_cost", "REAL")),
}

#: Covering indexes: join/filter key first, read columns after (docs/DB_INDEXES.md).
INDEXES: tuple[str, ...] = (
    "CREATE INDEX idx_order_items_cover ON order_items(order_id, price, freight_value)",
    "CREATE INDEX idx_orders_status_order_id ON orders(order_status, order_id)",
    "CREATE INDEX idx_order_payments_cover ON order_payments(order_id, payment_value)",
    "CREATE INDEX idx_orders_purchase_cover ON orders(order_purchase_timestamp, order_id, order_status, customer_id)",
    "CREATE INDEX idx_customers_unique_cover ON customers(customer_unique_id, customer_id, customer_state)",
    "CREATE INDEX idx_order_items_product_cover ON order_items(product_id, order_id, order_item_id, price)",
    "CREATE INDEX idx_returns_item_cover ON returns(order_id, order_item_id, refund_value, reason)",
    "CREATE INDEX idx_price_history_cover ON price_history(product_id, date, price, unit_cost)",
    "CREATE INDEX idx_competitor_prices_cover ON competitor_prices(product_id, date, competitor, price)",
    "CREATE INDEX idx_customer_segments_cover ON customer_segments(customer_unique_id, segment, ltv_band)",
    "CREATE INDEX idx_regional_targets_cover ON regional_targets(state, month, revenue_target)",
    "CREATE INDEX idx_web_traffic_cover ON web_traffic(state, date, sessions, conversion_rate)",
    "CREATE INDEX idx_inventory_daily_cover ON inventory_daily(category, date, units_sold, stockout_flag)",
    "CREATE INDEX idx_marketing_spend_cover ON marketing_spend(category, date, channel, spend)",
    "CREATE INDEX idx_delivery_sla_cover ON delivery_sla(state, date, carrier, actual_days, promised_days)",
    "CREATE INDEX idx_promotions_category ON promotions(category, start_date, end_date, discount_pct)",
)

_ROUND = {"REAL": 6}


@dataclass(frozen=True)
class GenerationResult:
    target: Path
    database_sha256: str
    source_sha256: str
    row_counts: dict[str, int]
    manifest: ManifestWriter


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rngs(seed: int, names: tuple[str, ...]) -> dict[str, np.random.Generator]:
    children = np.random.SeedSequence(seed).spawn(len(names))
    return {name: np.random.default_rng(child) for name, child in zip(names, children, strict=True)}


_STREAMS = (
    "marketing_spend", "promotions", "price_steps", "price_history", "inventory", "stock",
    "web_traffic", "competitor_prices", "customer_segments", "regional_targets", "returns",
    "delivery_sla", *(plant.name for plant in PLANTS),
)


def build_frames(ctx, seed: int, manifest: ManifestWriter) -> dict[str, pd.DataFrame]:
    """All ten synthetic tables, planted, as DataFrames in their final schema."""
    rng = _rngs(seed, _STREAMS)
    steps = base.category_price_steps(ctx, rng["price_steps"])
    for plant in PLANTS:
        if hasattr(plant, "plan_prices"):
            steps = plant.plan_prices(steps, ctx, manifest)
    index = base.category_price_index(ctx, steps)

    frames: dict[str, pd.DataFrame] = {
        "marketing_spend": base.marketing_spend(ctx, rng["marketing_spend"]),
        "promotions": base.promotions(ctx, rng["promotions"]),
        "price_history": base.price_history(ctx, steps, rng["price_history"]),
        "inventory_demand": base.inventory_demand(ctx, index, rng["inventory"]),
        "web_traffic": base.web_traffic(ctx, rng["web_traffic"]),
        "competitor_prices": base.competitor_prices(ctx, rng["competitor_prices"]),
        "customer_segments": base.customer_segments(ctx, rng["customer_segments"]),
        "regional_targets": base.regional_targets(ctx, rng["regional_targets"]),
        "returns": base.returns(ctx, rng["returns"]),
        "delivery_sla": base.delivery_sla(ctx, rng["delivery_sla"]),
    }
    for plant in PLANTS:
        plant.inject(frames, ctx, rng[plant.name], manifest)

    frames["inventory_daily"] = base.finalize_inventory(frames.pop("inventory_demand"), rng["stock"])
    frames["returns"] = frames["returns"].sort_values(["order_id", "order_item_id"], kind="mergesort").reset_index(drop=True)
    for name, columns in SCHEMAS.items():
        frames[name] = frames[name][[column for column, _ in columns]].reset_index(drop=True)
    return frames


def _copy_real_tables(conn: sqlite3.Connection) -> None:
    for table in REAL_TABLES:
        (ddl,) = conn.execute(
            "SELECT sql FROM src.sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        conn.execute(ddl)
        conn.execute(f'INSERT INTO main."{table}" SELECT * FROM src."{table}"')


def _write_frame(conn: sqlite3.Connection, name: str, frame: pd.DataFrame) -> None:
    columns = SCHEMAS[name]
    conn.execute(f'CREATE TABLE "{name}" (' + ", ".join(f'"{c}" {t}' for c, t in columns) + ")")
    values = []
    for column, kind in columns:
        series = frame[column]
        if kind == "REAL":
            values.append(np.round(series.astype(float).to_numpy(), _ROUND["REAL"]).tolist())
        elif kind == "INTEGER":
            values.append(series.astype(np.int64).tolist())
        else:
            values.append(series.astype(str).tolist())
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(f'INSERT INTO "{name}" VALUES ({placeholders})', zip(*values, strict=True))


def generate(
    source: Path = DEFAULT_SOURCE,
    target: Path = DEFAULT_TARGET,
    *,
    seed: int = DEFAULT_SEED,
    markdown_path: Path | None = DEFAULT_MARKDOWN,
) -> GenerationResult:
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target:
        raise ValueError("the target must not be the real snapshot (V2-SYN-1)")
    source_sha = sha256(source)

    with open_read_only(source) as src:
        ctx = load_context(src)
    manifest = ManifestWriter(seed=seed, generator_version=GENERATOR_VERSION)
    frames = build_frames(ctx, seed, manifest)

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".partial")
    for stale in (partial, target):
        if stale.exists():
            stale.unlink()
    conn = sqlite3.connect(f"file:{partial.as_posix()}?mode=rwc", uri=True)
    try:
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("ATTACH DATABASE ? AS src", (f"file:{source.as_posix()}?mode=ro",))
        _copy_real_tables(conn)
        conn.commit()
        conn.execute("DETACH DATABASE src")
        for name in SCHEMAS:
            _write_frame(conn, name, frames[name])
        for statement in INDEXES:
            conn.execute(statement)
        conn.execute("ANALYZE")
        conn.commit()
        conn.execute("VACUUM")
        row_counts = {
            name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in (*REAL_TABLES, *SCHEMAS)
        }
    finally:
        conn.close()
    partial.replace(target)

    if sha256(source) != source_sha:
        raise RuntimeError("the real snapshot changed during generation (V2-SYN-1)")
    database_sha = sha256(target)
    if markdown_path is not None:
        write_outputs(
            manifest,
            markdown_path=Path(markdown_path),
            json_path=target.with_name("synthetic_ground_truth.json"),
            database_sha256=database_sha,
            snapshot_id=f"v2-{seed}",
        )
    return GenerationResult(target, database_sha, source_sha, row_counts, manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build data/brazil_ecommerce_v2.sqlite.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args(argv)
    result = generate(args.source, args.target, seed=args.seed, markdown_path=args.markdown)
    width = max(len(name) for name in result.row_counts)
    for name, count in result.row_counts.items():
        print(f"{name:<{width}}  {count:>10,}")
    print(f"sha256 {result.database_sha256}  ->  {result.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
