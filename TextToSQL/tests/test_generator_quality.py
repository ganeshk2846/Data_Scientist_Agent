import json
import sqlite3

from data_gen.generator import generate
from data_gen.quality_checks import audit_generated_warehouse


def test_generated_warehouse_defects_are_independently_scored_and_truth_bound(tmp_path):
    warehouse = tmp_path / "warehouse.sqlite"
    truth_dir = tmp_path / "scoring"
    manifest = generate(warehouse, table_count=50, seed=7, truth_dir=truth_dir)
    truth_path = truth_dir / f"v{manifest['generator_version']}-{manifest['snapshot_id']}-{manifest['database_sha256'][:16]}.json"

    audited = audit_generated_warehouse(warehouse, warehouse.with_suffix(".manifest.json"), truth_path)

    assert audited["passed"], audited["checks"]
    assert audited["passed_count"] == audited["check_count"]
    assert audited["check_count"] == 17


def test_generator_audit_detects_a_removed_planted_defect(tmp_path):
    warehouse = tmp_path / "warehouse.sqlite"
    manifest = generate(warehouse, table_count=50, seed=7, truth_dir=tmp_path / "scoring")
    connection = sqlite3.connect(warehouse)
    connection.execute("UPDATE ord_hdr SET status='paid' WHERE status='PAID '")
    connection.commit()
    connection.close()

    audited = audit_generated_warehouse(warehouse, warehouse.with_suffix(".manifest.json"))

    failed = {item["name"] for item in audited["checks"] if not item["passed"]}
    assert not audited["passed"]
    assert "database_hash_matches_manifest" in failed
    assert "messy_status_value_present" in failed
