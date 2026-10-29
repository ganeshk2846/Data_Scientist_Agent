"""GRD-11 synonym seed and end-to-end paraphrase recall."""
import json
from pathlib import Path

from data_gen.generator import generate
from src.knowledge.catalog_api import CatalogAPI
from src.knowledge.retrieval import SchemaRetriever
from src.onboarding.pipeline import build_catalog


CASES = (
    {"question": "clients by territory", "table": "cstmr_dim"},
    {"question": "purchase total", "table": "ord_hdr"},
    {"question": "basket contents", "table": "ord_line"},
    {"question": "product catalog", "table": "item_dim"},
    {"question": "performance trend", "table": "monthly_kpi"},
    {"question": "churn risk", "table": "customer_risk"},
)


def _recall(retriever, cases):
    hits = 0
    for case in cases:
        result = retriever.retrieve(case["question"])
        hits += bool(result.tables[:1] == (case["table"],))
    return hits / len(cases)


def test_synonym_seed_improves_end_to_end_paraphrase_recall(tmp_path):
    root = Path(__file__).resolve().parents[1]
    terms = json.loads((root / "contracts" / "BE2_SYNONYMS.json").read_text(encoding="utf-8"))
    warehouse = tmp_path / "synonyms.sqlite"
    generate(warehouse, table_count=50, seed=7, snapshot="development")

    seeded_output = tmp_path / "seeded"
    seeded_output.mkdir()
    (seeded_output / "business_terms.json").write_text(json.dumps(terms), encoding="utf-8")
    build_catalog(warehouse, seeded_output)
    seeded_api = CatalogAPI(seeded_output / "catalog.json")
    seeded = SchemaRetriever(seeded_api)

    for case in CASES:
        result = seeded.retrieve(case["question"])
        assert not result.needs_clarification, (case["question"], result.clarification)
        assert result.tables[0] == case["table"], (case["question"], result.tables)

    baseline_output = tmp_path / "baseline"
    build_catalog(warehouse, baseline_output)
    baseline = SchemaRetriever(CatalogAPI(baseline_output / "catalog.json"))

    assert _recall(seeded, CASES) == 1.0
    assert _recall(baseline, CASES) < 1.0

    node_ids = set(seeded_api.graph().nodes)
    assert {"term:cstmr_dim", "term:clients"} <= node_ids
    assert any(item["kind"] == "business_term" and item["name"] == "cstmr_dim"
               for item in seeded_api.search("clients"))
