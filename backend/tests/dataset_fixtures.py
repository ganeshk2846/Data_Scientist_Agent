"""Shared marker for tests that require the separately sourced Olist database."""

import os
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
DB_PATH = Path(
    os.environ.get("DS_AGENT_DATABASE", BACKEND_DIR / ".." / "brazil_ecommerce.sqlite")
).expanduser().resolve()
requires_olist = pytest.mark.skipif(
    not DB_PATH.is_file(),
    reason=(
        "Olist SQLite fixture is not present; obtain it through an approved "
        "source and set DS_AGENT_DATABASE"
    ),
)
