"""The semantics/ context layer documents every table, column and metric (scope.md 2.4)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from scripts.synth.fixture import _DDL
from scripts.synth.generate import SCHEMAS
from semantic.metrics_v2 import all_metrics
from semantic.tables import TableRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]
SEMANTICS = REPO_ROOT / "semantics"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from render_semantics import render_metrics  # noqa: E402

REAL_COLUMNS = {
    match.group(1): re.findall(r'"(\w+)" (?:TEXT|INTEGER|REAL)', match.group(2))
    for match in re.finditer(r'CREATE TABLE "(\w+)" \((.*?)\);', _DDL)
}


@pytest.mark.parametrize("table", [t.name for t in TableRegistry.default().base()])
def test_every_table_has_a_page_naming_every_column(table):
    page = (SEMANTICS / f"{table}.md").read_text()
    columns = [c for c, _ in SCHEMAS[table]] if table in SCHEMAS else REAL_COLUMNS[table]
    assert columns
    for column in columns:
        assert f"`{column}`" in page, (table, column)
    for heading in ("## Columns", "## Join keys", "## Caveats"):
        assert heading in page, (table, heading)
    synthetic = TableRegistry.default().require(table).is_synthetic
    assert ("**synthetic**" in page) == synthetic, table


def test_analytical_tables_are_documented():
    page = (SEMANTICS / "analytical_tables.md").read_text()
    for table in TableRegistry.default().analytical():
        assert f"`{table.name}`" in page


def test_metrics_page_is_generated_from_the_registries():
    assert (SEMANTICS / "metrics.md").read_text() == render_metrics()
    for metric in all_metrics().metrics:
        assert f"## `{metric.metric_id}`" in render_metrics()


def test_glossary_and_rules():
    glossary = (SEMANTICS / "glossary.md").read_text()
    for term in ("GMV", "Gross vs net revenue", "customer_unique_id", "Complete period", "Synthetic"):
        assert term in glossary
    rules = (SEMANTICS / "RULES.md").read_text()
    assert "SAFE-8" in rules and "2018-08" in rules and "Label synthetic data" in rules
