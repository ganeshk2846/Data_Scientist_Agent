"""Stage 6 description review: drafts stay drafts until named approval."""
import json
import sqlite3

import pytest

from src.knowledge.catalog_api import CatalogAPI
from src.knowledge.retrieval import SchemaRetriever
from src.onboarding.pipeline import build_catalog, review_descriptions


def _warehouse(path):
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, region TEXT);
        CREATE TABLE invoices (invoice_id INTEGER PRIMARY KEY, amount REAL);
    """)
    connection.close()


def test_description_drafts_require_approval_before_publication(tmp_path):
    warehouse = tmp_path / "descriptions.sqlite"
    _warehouse(warehouse)
    output = tmp_path / "catalog"
    build_catalog(warehouse, output, descriptions={
        "customers": "Draft customer text",
        "invoices": "Draft invoice text",
    })

    catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["descriptions"]["customers"]["status"] == "draft"
    assert catalog["descriptions"]["customers"]["text"] == "Draft customer text"
    assert catalog["descriptions"]["invoices"]["status"] == "draft"

    index = json.loads((output / "index_build.json").read_text(encoding="utf-8"))
    table_docs = {item["name"]: item["text"] for item in index["keyword"] if item["kind"] == "table"}
    assert "Draft customer text" not in table_docs["customers"]
    assert "Draft invoice text" not in table_docs["invoices"]
    assert "Draft customer text" not in SchemaRetriever(CatalogAPI(output / "catalog.json")).retrieve("customers").text

    review_descriptions(output, approve={
        "customers": "Approved customer master data.",
        "customers.region": "Geographic sales territory.",
    }, reject=["invoices"], reviewer="alice")

    build_catalog(warehouse, output)
    catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
    index = json.loads((output / "index_build.json").read_text(encoding="utf-8"))
    review = json.loads((output / "review.json").read_text(encoding="utf-8"))

    assert catalog["descriptions"]["customers"]["status"] == "approved"
    assert catalog["descriptions"]["customers"]["text"] == "Approved customer master data."
    assert catalog["descriptions"]["customers"]["reviewer"] == "alice"
    assert catalog["descriptions"]["customers"]["columns"]["region"]["status"] == "approved"
    assert catalog["descriptions"]["customers"]["columns"]["region"]["text"] == "Geographic sales territory."
    assert catalog["descriptions"]["invoices"]["status"] == "rejected"

    docs = {item["name"]: item["text"] for item in index["keyword"] if item["kind"] in {"table", "column"}}
    assert "Approved customer master data." in docs["customers"]
    assert "Geographic sales territory." in docs["customers.region"]
    assert "Draft invoice text" not in docs["invoices"]
    assert "Approved customer master data." in SchemaRetriever(CatalogAPI(output / "catalog.json")).retrieve("customers").text
    assert review["description_decisions"]["customers"]["reviewer"] == "alice"
    assert [row["status"] for row in review["description_decision_history"]["customers"]] == ["approved"]


def test_description_review_requires_named_reviewer_and_valid_target(tmp_path):
    warehouse = tmp_path / "invalid.sqlite"
    _warehouse(warehouse)
    output = tmp_path / "catalog"
    build_catalog(warehouse, output)

    with pytest.raises(ValueError, match="named human reviewer"):
        review_descriptions(output, approve={"customers": "text"}, reviewer="system")
    with pytest.raises(ValueError, match="non-empty"):
        review_descriptions(output, approve={"customers": "  "}, reviewer="alice")
    with pytest.raises(ValueError, match="Unknown description target"):
        review_descriptions(output, approve={"missing": "text"}, reviewer="alice")
