"""Shared fixtures: one seeded V2 build per test session.

The real snapshot is sourced separately, so the V2 tests run the generator
and the analytical build against the Olist-shaped fixture instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BUILD_STAMP = "2026-10-30T00:00:00Z"


@pytest.fixture(scope="session")
def v2_build(tmp_path_factory):
    from scripts.build_analytical_tables import build
    from scripts.synth.fixture import build_fixture
    from scripts.synth.generate import generate

    root = tmp_path_factory.mktemp("v2")
    source = build_fixture(root / "olist.sqlite")
    result = generate(source, root / "brazil_ecommerce_v2.sqlite", markdown_path=root / "GROUND_TRUTH.md")
    counts = build(result.target, computed_at=BUILD_STAMP)
    return {"root": root, "source": source, "generation": result, "analytical_counts": counts, "db": result.target}
