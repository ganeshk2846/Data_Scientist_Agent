"""'What data do you have?' from the catalog (D1, acceptance 1.13, 1.16)."""

from __future__ import annotations

import re
import sqlite3

from semantic.discovery import catalog_facts, describe_warehouse, render_answer
from sqlalchemy import create_engine


def _describe(db):
    engine = create_engine(f"sqlite:///file:{db.as_posix()}?mode=ro&uri=true")
    with engine.connect() as connection:
        return describe_warehouse(connection)


def test_lists_all_19_tables_with_counts_dates_and_labels(v2_build):
    description = _describe(v2_build["db"])
    base = [t for t in description.tables if t.layer != "analytical"]

    assert len(base) == 19 and all(t.present for t in base)
    assert len(description.synthetic_tables) == 10
    counts = v2_build["generation"].row_counts
    for table in base:
        assert table.row_count == counts[table.name]
    orders = next(t for t in base if t.name == "orders")
    assert orders.date_min.startswith("2016-09") and orders.date_max.startswith("2018-10")


def test_answer_names_every_synthetic_table_and_metric(v2_build):
    description = _describe(v2_build["db"])
    answer = render_answer(description)

    assert "19 tables" in answer
    assert "not measurements of the real business" in answer
    for name in description.synthetic_tables:
        assert f"`{name}`" in answer
    assert "16 metrics" in answer
    assert re.search(r"`marketing_spend` \(Marketing Spend\) \| sum \| \*\*synthetic\*\*", answer)
    assert "last complete month" in answer


def test_every_figure_in_the_answer_is_a_catalog_or_sql_fact(v2_build):
    """SAFE-8: numbers in the answer are row counts, dates or catalog counts only."""
    description = _describe(v2_build["db"])
    answer = render_answer(description)
    allowed = {f"{t.row_count:,}" for t in description.tables if t.present}
    allowed |= {str(len(description.metrics)), "19", "10", "9"}
    allowed |= {part for t in description.tables if t.date_min for part in (*t.date_min.split("-"), *t.date_max.split("-"))}
    allowed |= {"2016", "2018", "09", "10", "08"}  # the completeness note
    text = re.sub(r"`[^`]*`", "", answer)  # identifiers like idx names / versions
    for number in re.findall(r"\d+(?:,\d{3})*", text):
        assert number in allowed, number


def test_catalog_facts_payload_carries_sources(v2_build):
    payload = catalog_facts(_describe(v2_build["db"]))
    sources = {fact.source for fact in payload.facts}
    assert sources == {"catalog", "sql"}
    assert any(f.key == "table.marketing_spend.layer" and f.value == "synthetic" for f in payload.facts)


def test_real_only_database_marks_synthetic_tables_missing(v2_build):
    description = _describe(v2_build["source"])
    missing = {t.name for t in description.tables if not t.present and t.layer == "synthetic"}
    assert len(missing) == 10
    assert "Registered but not loaded" in render_answer(description)
    with sqlite3.connect(v2_build["source"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'marketing_spend'").fetchone() == (0,)
