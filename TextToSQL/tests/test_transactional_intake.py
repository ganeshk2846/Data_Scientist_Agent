import sqlite3

import pytest

from data_gen.transactional_intake import (SOURCE_LICENSE, SOURCE_NAME, SOURCE_URL, import_rows,
                                          intake_workbook, validate_privacy_approval,
                                          validate_uci_provenance)


def test_import_preserves_repeated_lines_and_removes_direct_identifiers(tmp_path):
    target = tmp_path / "filtered.sqlite"
    rows = [
        ["InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate",
         "UnitPrice", "CustomerID", "Country"],
        ["536365", "85123A", "white hanging heart", 6, "2010-12-01 08:26", 2.55, 17850, "United Kingdom"],
        ["536365", "85123A", "white hanging heart", 6, "2010-12-01 08:26", 2.55, 17850, "United Kingdom"],
        ["C536366", "71053", "red mug", -1, "2010-12-01 08:28", 3.39, 17850, "United Kingdom"],
        [None, "bad", "invalid", "not-a-number", "", 0, 17850, ""],
    ]

    counts = import_rows(rows, target)

    assert counts == {"imported_rows": 3, "rejected_rows": 1, "transaction_groups": 2}
    connection = sqlite3.connect(target)
    try:
        schema = {row[1] for row in connection.execute("PRAGMA table_info(transactions)")}
        assert "customerid" not in {column.casefold() for column in schema}
        assert "invoiceno" not in {column.casefold() for column in schema}
        records = connection.execute(
            "SELECT transaction_id, quantity, is_cancellation FROM transactions ORDER BY row_id"
        ).fetchall()
    finally:
        connection.close()
    assert records == [("txn-00000001", 6, 0), ("txn-00000001", 6, 0),
                       ("txn-00000002", -1, 1)]


def test_import_refuses_to_overwrite_existing_output(tmp_path):
    target = tmp_path / "existing.sqlite"
    target.write_bytes(b"preserve this")
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        import_rows([["InvoiceNo"]], target)
    assert target.read_bytes() == b"preserve this"


def test_import_requires_transaction_fields(tmp_path):
    with pytest.raises(ValueError, match="missing columns"):
        import_rows([["InvoiceNo", "CustomerID"]], tmp_path / "invalid.sqlite")


def test_import_rejects_duplicate_headers_and_nonfinite_or_fractional_values(tmp_path):
    headers = ["InvoiceNo", "StockCode", "Quantity", "InvoiceDate", "UnitPrice", "Country", "extra", "EXTRA"]
    with pytest.raises(ValueError, match="duplicate column headers"):
        import_rows([headers], tmp_path / "duplicate.sqlite")
    rows = [["InvoiceNo", "StockCode", "Quantity", "InvoiceDate", "UnitPrice", "Country"],
            ["1", "sku", 1.5, "2020-01-01", 1.0, "UK"],
            ["2", "sku", 1, "2020-01-01", float("nan"), "UK"]]
    with pytest.raises(ValueError, match="no valid transaction rows"):
        import_rows(rows, tmp_path / "empty.sqlite")
    assert not (tmp_path / "empty.sqlite").exists()


def test_intake_reports_absent_workbook_and_missing_approval_evidence(tmp_path):
    with pytest.raises(FileNotFoundError, match="source workbook not found"):
        intake_workbook(tmp_path / "missing.xlsx", tmp_path / "out.sqlite",
                        privacy_approval_ref="PRIV-123", privacy_approval_record=tmp_path / "approval.json")
    workbook = tmp_path / "provided.xlsx"
    workbook.write_bytes(b"fixture only; not a workbook")
    with pytest.raises(ValueError, match="reference is required"):
        intake_workbook(workbook, tmp_path / "out.sqlite", privacy_approval_ref=" ",
                        privacy_approval_record=tmp_path / "approval.json")
    with pytest.raises(ValueError, match="record path is required"):
        intake_workbook(workbook, tmp_path / "out.sqlite", privacy_approval_ref="PRIV-123")
    assert not (tmp_path / "out.sqlite").exists()


def test_privacy_approval_record_must_match_dataset_scope_and_reviewer(tmp_path):
    approval = tmp_path / "approval.json"
    approval.write_text('{"reference":"PRIV-1","status":"pending"}', encoding="utf-8")
    with pytest.raises(ValueError, match="requires non-empty fields"):
        validate_privacy_approval("PRIV-1", approval)
    approval.write_text(
        '{"reference":"PRIV-1","status":"approved","dataset_url":"wrong",'
        '"scope":"development","reviewer":"R","reviewed_at":"2026-10-29"}', encoding="utf-8")
    with pytest.raises(ValueError, match="cover UCI"):
        validate_privacy_approval("PRIV-1", approval)
    assert validate_privacy_approval(
        "PRIV-1", _approval_record(approval))['reference'] == "PRIV-1"


def _approval_record(path):
    import json
    path.write_text(json.dumps({"reference": "PRIV-1", "status": "approved",
                                "dataset_url": SOURCE_URL, "scope": "UCI development intake",
                                "reviewer": "Privacy Reviewer", "reviewed_at": "2026-10-29T10:00:00Z"}),
                    encoding="utf-8")
    return path


def test_uci_intake_provenance_rejects_invalid_source_license_or_permitted_use():
    valid = {"name": SOURCE_NAME, "url": SOURCE_URL, "licence": SOURCE_LICENSE,
             "permitted_use": "Development use with attribution", "split": "development",
             "layer": "public_transactional", "citation": "source citation", "doi": "10.24432/C5CG6D",
             "privacy_approval_ref": "PRIV-1", "transformation": "CustomerID removed",
             "source_sha256": "a" * 64, "artifact_sha256": "b" * 64}
    validate_uci_provenance(valid)
    for field, value in (("url", "https://example.invalid/data"),
                         ("licence", "unknown"), ("split", "held-out"),
                         ("permitted_use", "private research only")):
        with pytest.raises(ValueError, match="provenance|permitted_use"):
            validate_uci_provenance({**valid, field: value})
