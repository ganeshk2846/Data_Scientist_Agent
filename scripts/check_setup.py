"""Check the local setup before starting the backend; read-only, changes nothing.

The commonest reason for "What if we raise prices 5%?" (and the other synthetic-layer questions)
returning INSUFFICIENT EVIDENCE is that the backend is reading the raw Olist snapshot instead of
the V2 build: no price history, no precomputed analytical tables and no indexes. This prints which
database the backend will open - by the same rule as backend/src/app.py - and what it is missing.

    python scripts/check_setup.py          # exit code 0 when everything needed is in place
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = ("marketing_spend", "promotions", "inventory_daily", "web_traffic", "price_history", "competitor_prices",
             "customer_segments", "regional_targets", "returns", "delivery_sla")
ANALYTICAL = ("kpi_daily", "analytical_series", "analytical_anomalies", "analytical_forecasts", "driver_contributions")
INDEXES = ("idx_order_items_cover", "idx_orders_status_order_id", "idx_order_payments_cover")


def backend_database() -> tuple[Path, str]:
    """The file app.py opens: DS_AGENT_DB, else DS_AGENT_DATABASE, else brazil_ecommerce.sqlite at the repo root."""
    for name in ("DS_AGENT_DB", "DS_AGENT_DATABASE"):
        if os.environ.get(name):
            return Path(os.environ[name]).expanduser().resolve(), name
    return ROOT / "brazil_ecommerce.sqlite", "default (neither DS_AGENT_DB nor DS_AGENT_DATABASE is set)"


def main() -> int:
    windows = os.name == "nt"
    set_cmd = "set" if windows else "export"
    v2 = ROOT / "data" / "brazil_ecommerce_v2.sqlite"
    problems: list[str] = []
    print(f"Python {sys.version.split()[0]} at {sys.executable}")
    if sys.version_info < (3, 11):  # noqa: UP036 - the point is to catch an older interpreter
        problems.append("Python 3.11 or newer is required.")

    path, source = backend_database()
    print(f"Backend database: {path}\n  chosen by: {source}")
    if not path.exists():
        problems.append(f"{path} does not exist.")
    else:
        with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
            orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] if "orders" in tables else 0
        print(f"  orders: {orders:,} ({'the real Olist snapshot size' if orders == 99_441 else 'not the real snapshot - a fixture or stand-in'})")
        for label, names in (("synthetic tables", SYNTHETIC), ("analytical tables", ANALYTICAL), ("indexes", INDEXES)):
            have = indexes if label == "indexes" else tables
            missing = [name for name in names if name not in have]
            print(f"  {label}: {'all present' if not missing else 'MISSING ' + ', '.join(missing)}")
            if missing:
                problems.append(f"the backend database has no {label} ({', '.join(missing[:3])}...)")

    token = os.environ.get("DS_AGENT_TOKEN", "")
    print(f"DS_AGENT_TOKEN: {'set' if token else 'not set'}")
    if token and len(token) < 32:
        problems.append("DS_AGENT_TOKEN must be at least 32 characters.")
    if not token and not os.environ.get("DS_AGENT_API_TOKENS"):
        print("  (no token: the API runs without authentication, as user 'dev_user'; the web app's proxy sends none)")

    if not problems:
        print("\nOK - start the backend from this same terminal.")
        return 0
    print("\nProblems:")
    for problem in problems:
        print(f"  - {problem}")
    print("\nFix:")
    if not v2.exists():
        snapshot = ROOT / "brazil_ecommerce.sqlite"
        print("  python scripts/build_v2.py --source brazil_ecommerce.sqlite" if snapshot.exists() else
              "  put brazil_ecommerce.sqlite in the repository root, then: python scripts/build_v2.py --source brazil_ecommerce.sqlite\n"
              "  (or, without the snapshot: python scripts/build_v2.py --fixture)")
    print(f"  {set_cmd} DS_AGENT_DB={v2}")
    print("  then run this check again in the same terminal, and start the backend from it.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
