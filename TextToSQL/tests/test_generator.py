import hashlib
import json
import sqlite3

from data_gen.generator import generate, generate_snapshot_pair
from data_gen.scoring import load_ground_truth
from data_gen.provenance import directory_sha256, register_dataset
from data_gen.splits import QuestionSplitStore
from data_gen.access import ScoringAccessPolicy
from data_gen.access import heldout_scoring_scope
import pytest


def test_same_seed_has_identical_database_hash_and_manifest(tmp_path):
    first = generate(tmp_path / "first.sqlite", table_count=50, seed=73)
    second = generate(tmp_path / "second.sqlite", table_count=50, seed=73)
    assert first["database_sha256"] == second["database_sha256"]
    assert first["planted_features"] == second["planted_features"]
    assert first["generated_at"] == second["generated_at"]
    assert first["snapshot"] == second["snapshot"] == "development"


def test_manifest_claims_only_features_actually_seeded(tmp_path):
    manifest = generate(tmp_path / "warehouse.sqlite", table_count=50, seed=7)
    assert manifest["planted_features"]["cryptic_tables"] == 40
    assert manifest["planted_features"]["stale_copy_rows"] == 80
    assert manifest["planted_features"]["soft_deleted_orders"] > 0
    assert manifest["planted_features"]["missing_declared_foreign_keys"] is True
    connection = sqlite3.connect(tmp_path / "warehouse.sqlite")
    foreign_keys = sum(connection.execute(f"PRAGMA foreign_key_list('{table}')").fetchall().__len__() for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    connection.close()
    assert foreign_keys == 0


def test_scale_ladder_and_distinct_snapshot_seeds(tmp_path):
    hashes = {}
    for count in (50, 200, 500):
        manifest = generate(tmp_path / f"scale-{count}.sqlite", table_count=count, seed=91)
        connection = sqlite3.connect(tmp_path / f"scale-{count}.sqlite")
        actual_tables = connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]
        connection.close()
        assert manifest["table_count"] == count == actual_tables
        hashes[count] = manifest["database_sha256"]
    dev = generate(tmp_path / "dev.sqlite", table_count=50, seed=7, snapshot="development")
    heldout = generate(tmp_path / "heldout.sqlite", table_count=50, seed=8, snapshot="held-out")
    assert len(set(hashes.values())) == 3
    assert dev["snapshot"] == "development" and heldout["snapshot"] == "held-out"
    assert dev["database_sha256"] != heldout["database_sha256"]


def test_generator_plants_required_edges_and_keeps_truth_outside_warehouse(tmp_path):
    db = tmp_path / "generated" / "warehouse.sqlite"
    truth_dir = tmp_path / "scoring-only"
    public = generate(db, table_count=50, seed=5, snapshot="held-out", truth_dir=truth_dir)
    policy = ScoringAccessPolicy(["test-scorer"])
    with pytest.raises(PermissionError):
        load_ground_truth(public["snapshot_id"], public["database_sha256"], principal="agent",
                          scoring_policy=policy, truth_dir=truth_dir)
    truth = load_ground_truth(public["snapshot_id"], public["database_sha256"], principal="test-scorer",
                              scoring_policy=policy, truth_dir=truth_dir)
    assert truth["split"] == "heldout"
    assert truth["anomalies"] and truth["drivers"] and truth["confounders"]
    assert truth["negative_controls"] and truth["churn_process"] and truth["sql_traps"]
    assert public["planted_features"]["merged_customer_cases"] > 0
    assert public["planted_features"]["late_event_rows"] > 0
    assert public["planted_features"]["truncated_snapshot_rows"] > 0
    assert not db.with_suffix(".manifest.json").read_text(encoding="utf-8").find("correct_result_sql") >= 0
    connection = sqlite3.connect(db)
    assert connection.execute("SELECT COUNT(*) FROM ord_hdr WHERE is_test=1").fetchone()[0] > 0
    assert connection.execute("SELECT COUNT(*) FROM cstmr_archive GROUP BY cstmr_id HAVING COUNT(*) > 1").fetchone()
    assert connection.execute("SELECT COUNT(*) FROM customer_merge_map").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM late_events WHERE ingested_at > event_date").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM daily_snapshot WHERE is_complete=0").fetchone()[0] == 1
    connection.close()


def test_heldout_question_access_is_scoring_only_and_immutable(tmp_path):
    store = QuestionSplitStore(tmp_path / "questions.json")
    cases = [{"id": "dev-1", "split": "development", "question": "Count orders"},
             {"id": "hold-1", "split": "held-out", "question": "Revenue by region"}]
    store.create(cases)
    assert len(store.get("development")) == 1
    assert json.loads(store.path.read_text(encoding="utf-8")) == [cases[0] | {"database_layer": "synthetic_enterprise"}]
    assert json.loads(store.heldout_path.read_text(encoding="utf-8")) == [cases[1] | {"database_layer": "synthetic_enterprise"}]
    with pytest.raises(PermissionError):
        store.get("held-out")
    with pytest.raises(PermissionError):
        store.get("held-out", principal="test-scorer")
    policy = ScoringAccessPolicy(["test-scorer"])
    with pytest.raises(PermissionError):
        store.get("held-out", principal="agent", scoring_policy=policy)
    assert len(store.get("held-out", principal="test-scorer", scoring_policy=policy)) == 1
    with pytest.raises(TypeError, match="collection"):
        ScoringAccessPolicy("test-scorer")
    with pytest.raises(FileExistsError):
        store.create([{**cases[0], "question": "changed"}, cases[1]])


def test_heldout_scope_blocks_development_split_generator_and_provenance_mutations(tmp_path):
    store = QuestionSplitStore(tmp_path / "questions.json")
    record = {"name": "fixture", "url": "local://fixture", "version": "1", "licence": "test",
              "permitted_use": "development", "split": "development", "layer": "benchmark",
              "intake_status": "candidate_not_ingested"}
    with heldout_scoring_scope():
        with pytest.raises(PermissionError, match="held-out scoring"):
            store.create([{"id": "dev", "split": "development", "question": "public"}])
        with pytest.raises(PermissionError, match="held-out scoring"):
            generate(tmp_path / "forbidden.sqlite", table_count=50, seed=2)
        with pytest.raises(PermissionError, match="held-out scoring"):
            register_dataset(record, tmp_path / "provenance.json")
    assert not (tmp_path / "questions.json").exists()
    assert not (tmp_path / "forbidden.sqlite").exists()
    assert not (tmp_path / "provenance.json").exists()


def test_provenance_requires_dataset_layer(tmp_path):
    base = {"name": "benchmark", "url": "local://fixture", "version": "1", "licence": "test",
            "permitted_use": "evaluation", "split": "development", "intake_status": "candidate_not_ingested"}
    with pytest.raises(ValueError, match="layer"):
        register_dataset(base, tmp_path / "provenance.json")
    assert register_dataset({**base, "layer": "benchmark"}, tmp_path / "provenance.json")["layer"] == "benchmark"


def test_public_transactional_candidate_records_attribution_and_not_ingested(tmp_path):
    record = {
        "name": "UCI Online Retail II", "url": "https://archive.ics.uci.edu/dataset/502/online+retail+ii",
        "version": "UCI dataset 502", "licence": "CC BY 4.0",
        "permitted_use": "Share and adapt with attribution; review personal-data obligations before intake",
        "split": "development", "layer": "public_transactional",
        "citation": "Chen (2012), UCI Machine Learning Repository",
        "doi": "10.24432/C5CG6D", "intake_status": "candidate_not_ingested",
    }
    saved = register_dataset(record, tmp_path / "provenance.json")
    assert saved["intake_status"] == "candidate_not_ingested"
    assert saved["split"] == "development"
    assert saved["doi"] == "10.24432/C5CG6D"
    with pytest.raises(ValueError, match="intake_status"):
        register_dataset({**record, "intake_status": "downloaded"}, tmp_path / "bad.json")
    with pytest.raises(ValueError, match="URL"):
        register_dataset({**record, "url": "not-a-url"}, tmp_path / "invalid-url.json")
    with pytest.raises(ValueError, match="SHA-256"):
        register_dataset({**record, "intake_status": "ingested", "artifact_sha256": "bad"},
                         tmp_path / "invalid-hash.json")


def test_dataset_directory_hash_is_reproducible_and_content_sensitive(tmp_path):
    snapshot = tmp_path / "snapshot"
    (snapshot / "nested").mkdir(parents=True)
    (snapshot / "a.json").write_text('{"a":1}', encoding="utf-8")
    (snapshot / "nested" / "b.db").write_bytes(b"database")
    first = directory_sha256(snapshot)
    assert directory_sha256(snapshot) == first
    (snapshot / "nested" / "b.db").write_bytes(b"changed")
    assert directory_sha256(snapshot) != first


def test_snapshot_pair_has_distinct_seeds_and_injection_settings(tmp_path):
    pair = generate_snapshot_pair(tmp_path / "snapshots", table_count=50, seed=17, truth_dir=tmp_path / "truth")
    assert pair["build"]["seed"] != pair["heldout"]["seed"]
    assert pair["build"]["injection_config"] != pair["heldout"]["injection_config"]
    assert pair["build"]["snapshot"] == "development"
    assert pair["heldout"]["snapshot"] == "held-out"


def test_plant_plugin_records_every_added_fact(tmp_path):
    class Plugin:
        name = "plant-extra-control"

        def inject(self, warehouse, rng, manifest):
            warehouse.execute("CREATE TABLE plugin_control (control_id INTEGER)")
            warehouse.execute("INSERT INTO plugin_control VALUES (7)")
            manifest.record("negative_controls", {"control_id": "plugin-7", "metric": "test", "unit": {"dimension": "id", "value": "7"}, "period": {"start": "2025-01-01", "end": "2025-01-02"}, "kind": "ordinary"})

    db = tmp_path / "plugin.sqlite"
    result = generate(db, table_count=50, seed=33, plugins=[Plugin()], truth_dir=tmp_path / "truth")
    truth = load_ground_truth(result["snapshot_id"], result["database_sha256"], principal="test-scorer",
                              scoring_policy=ScoringAccessPolicy(["test-scorer"]),
                              truth_dir=tmp_path / "truth")
    assert result["plugins"] == ["plant-extra-control"]
    assert any(row["control_id"] == "plugin-7" for row in truth["negative_controls"])
    connection = sqlite3.connect(db)
    assert connection.execute("SELECT control_id FROM plugin_control").fetchone()[0] == 7
    connection.close()
