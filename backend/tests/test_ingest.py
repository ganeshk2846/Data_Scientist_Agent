"""Tests for read-only CSV ingestion profiler (GRD-2, SAFE-2)."""

import tempfile
from pathlib import Path

from scripts.ingest import ingest_folder, profile_csv


def test_profile_csv_infers_types_and_primary_key():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "test_merchants.csv"
        csv_path.write_text(
            "merchant_id,merchant_name,signup_date,commission_rate\n"
            "M1,Alpha Store,2017-05-01,0.15\n"
            "M2,Beta Shop,2017-06-12,0.12\n"
            "M3,Gamma Goods,2017-08-20,0.18\n",
            encoding="utf-8",
        )

        profile = profile_csv(csv_path)
        assert profile["table_name"] == "test_merchants"
        assert profile["row_count"] == 3
        assert profile["columns"]["merchant_id"]["type"] in ("TEXT", "INTEGER")
        assert profile["columns"]["commission_rate"]["type"] == "REAL"
        assert profile["columns"]["signup_date"]["type"] == "DATE"
        assert "merchant_id" in profile["candidate_primary_keys"]
        assert len(profile["proposed_join_edges"]) > 0
        assert profile["proposed_join_edges"][0]["status"] == "pending_human_approval"


def test_ingest_folder_generates_manifest_without_warehouse_writes():
    with tempfile.TemporaryDirectory() as tmpdir:
        folder = Path(tmpdir)
        (folder / "table_a.csv").write_text("id,val\n1,10\n2,20\n", encoding="utf-8")
        (folder / "table_b.csv").write_text(
            "code,customer_state\nC1,SP\nC2,RJ\n", encoding="utf-8"
        )

        manifest = ingest_folder(folder)
        assert len(manifest["tables"]) == 2
        assert "table_a" in manifest["tables"]
        assert "table_b" in manifest["tables"]
        assert (
            manifest["tables"]["table_b"]["proposed_join_edges"][0]["target_table"]
            == "customers"
        )
