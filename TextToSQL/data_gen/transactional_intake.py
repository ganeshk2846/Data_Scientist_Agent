"""Privacy-gated, reproducible intake of the public UCI Online Retail II XLSX.

The intake tool never downloads data. It accepts a workbook obtained from the
official UCI record, requires an explicit privacy-review reference, removes
CustomerID, and replaces original invoice numbers with encounter-order IDs.
The transformation is pseudonymization, not a guarantee of anonymization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
from datetime import date, datetime
from itertools import chain
from pathlib import Path
from typing import Iterable

from .provenance import register_dataset

SOURCE_NAME = "UCI Online Retail II"
SOURCE_URL = "https://archive.ics.uci.edu/dataset/502/online+retail+ii"
SOURCE_LICENSE = "Creative Commons Attribution 4.0 International (CC BY 4.0)"
REQUIRED_HEADERS = {"invoiceno", "stockcode", "quantity", "invoicedate", "unitprice", "country"}
TRANSFORMATION = "CustomerID column dropped; original InvoiceNo values replaced by deterministic encounter-order transaction IDs; source rows retained in original sheet order. This is pseudonymization, not anonymization."
PERMITTED_USE = "Development use with attribution under CC BY 4.0; transformed intake excludes CustomerID and replaces InvoiceNo with deterministic transaction group IDs."


def validate_uci_provenance(record: dict) -> None:
    """Fail closed on missing or conflicting source, licence, split or use metadata."""
    expected = {"name": SOURCE_NAME, "url": SOURCE_URL, "licence": SOURCE_LICENSE,
                "split": "development", "layer": "public_transactional"}
    for field, value in expected.items():
        if record.get(field) != value:
            raise ValueError(f"UCI intake provenance field {field!r} must be {value!r}")
    permitted = record.get("permitted_use", "")
    if not isinstance(permitted, str) or "development" not in permitted.casefold() or "attribution" not in permitted.casefold():
        raise ValueError("UCI permitted_use must explicitly allow development use with attribution")
    for field in ("citation", "doi", "privacy_approval_ref", "transformation"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            raise ValueError(f"UCI intake provenance requires non-empty {field}")
    for field in ("source_sha256", "artifact_sha256"):
        value = record.get(field)
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.casefold()):
            raise ValueError(f"UCI intake provenance requires a 64-character {field}")


def validate_privacy_approval(reference: str, record_path: str | Path | None) -> dict:
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("A privacy review approval reference is required before intake")
    if record_path is None:
        raise ValueError("A privacy approval record path is required; a free-text reference alone is not evidence")
    path = Path(record_path)
    if not path.is_file():
        raise FileNotFoundError(f"Privacy approval record not found: {path}")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Privacy approval record is unreadable or invalid JSON: {path}") from error
    required = ("reference", "status", "dataset_url", "scope", "reviewer", "reviewed_at")
    missing = [field for field in required if not isinstance(record.get(field), str) or not record[field].strip()]
    if missing:
        raise ValueError(f"Privacy approval record requires non-empty fields: {', '.join(missing)}")
    if record["reference"].strip() != reference.strip() or record["status"].casefold() != "approved":
        raise ValueError("Privacy approval reference is not an approved matching record")
    if record["dataset_url"] != SOURCE_URL or "development" not in record["scope"].casefold():
        raise ValueError("Privacy approval record must cover UCI Online Retail II development intake")
    try:
        datetime.fromisoformat(record["reviewed_at"].replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Privacy approval reviewed_at must be an ISO-8601 timestamp") from error
    if record["reviewer"].strip().casefold() in {"unknown", "unattributed", "placeholder", "test"}:
        raise ValueError("Privacy approval record must identify its actual reviewer")
    return record


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_header(value) -> str:
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def _iso_date(value) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    return str(value or "").strip()


def import_rows(rows: Iterable[Iterable[object]], database_path: str | Path) -> dict[str, int]:
    """Write normalized workbook rows to a new SQLite DB without CustomerID."""
    target = Path(database_path)
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite dataset intake target: {target}")
    iterator = iter(rows)
    try:
        headers = [_normalized_header(value) for value in next(iterator)]
    except StopIteration as error:
        raise ValueError("workbook sheet is empty") from error
    missing = REQUIRED_HEADERS - set(headers)
    if missing:
        raise ValueError(f"UCI transaction sheet is missing columns: {sorted(missing)}")
    if len(headers) != len(set(headers)):
        raise ValueError("UCI transaction sheet contains duplicate column headers")
    columns = {name: headers.index(name) for name in REQUIRED_HEADERS}
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    invoice_ids: dict[str, int] = {}
    imported = rejected = 0
    try:
        connection.execute("""
            CREATE TABLE transactions (
                row_id INTEGER PRIMARY KEY,
                transaction_id TEXT NOT NULL,
                item_code TEXT,
                description TEXT,
                quantity INTEGER NOT NULL,
                invoice_date TEXT NOT NULL,
                unit_price_gbp REAL NOT NULL,
                country TEXT,
                is_cancellation INTEGER NOT NULL
            )
        """)
        batch = []
        description_index = headers.index("description") if "description" in headers else None
        for row in iterator:
            row = list(row)
            if len(row) < len(headers):
                row.extend([None] * (len(headers) - len(row)))
            try:
                raw_invoice = str(row[columns["invoiceno"]]).strip()
                item_code = str(row[columns["stockcode"]] or "").strip()
                raw_quantity = row[columns["quantity"]]
                numeric_quantity = float(raw_quantity)
                if not math.isfinite(numeric_quantity) or not numeric_quantity.is_integer():
                    raise ValueError("quantity must be finite and integral")
                quantity = int(raw_quantity)
                invoice_date = _iso_date(row[columns["invoicedate"]])
                unit_price = float(row[columns["unitprice"]])
                country = str(row[columns["country"]] or "").strip()
                if not raw_invoice or not item_code or not invoice_date or not country:
                    raise ValueError("required field missing")
                if not math.isfinite(unit_price) or unit_price < 0:
                    raise ValueError("unit price must be finite and non-negative")
            except (IndexError, TypeError, ValueError, OverflowError):
                rejected += 1
                continue
            if raw_invoice not in invoice_ids:
                invoice_ids[raw_invoice] = len(invoice_ids) + 1
            transaction_id = f"txn-{invoice_ids[raw_invoice]:08d}"
            cancelled = int(raw_invoice.casefold().startswith("c"))
            description = (str(row[description_index]).strip()
                           if description_index is not None and row[description_index] is not None else None)
            batch.append((transaction_id, item_code, description, quantity, invoice_date,
                          unit_price, country, cancelled))
            if len(batch) >= 5000:
                connection.executemany("INSERT INTO transactions (transaction_id, item_code, description, quantity, invoice_date, unit_price_gbp, country, is_cancellation) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", batch)
                imported += len(batch)
                batch.clear()
        if batch:
            connection.executemany("INSERT INTO transactions (transaction_id, item_code, description, quantity, invoice_date, unit_price_gbp, country, is_cancellation) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", batch)
            imported += len(batch)
        if imported == 0:
            raise ValueError("workbook contained no valid transaction rows; no intake artifact was published")
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        target.unlink(missing_ok=True)
        raise
    else:
        connection.close()
    return {"imported_rows": imported, "rejected_rows": rejected,
            "transaction_groups": len(invoice_ids)}


def intake_workbook(workbook_path: str | Path, output_db: str | Path, *,
                    privacy_approval_ref: str, privacy_approval_record: str | Path | None = None,
                    provenance_path: str | Path = "data/provenance.json") -> dict:
    source = Path(workbook_path)
    if not source.is_file():
        raise FileNotFoundError(f"UCI source workbook not found: {source}")
    approval = validate_privacy_approval(privacy_approval_ref, privacy_approval_record)
    try:
        from openpyxl import load_workbook
    except ImportError as error:
        raise RuntimeError("Install requirements-uci-intake.txt to read the official XLSX") from error

    workbook_hash = file_sha256(source)
    workbook = load_workbook(source, read_only=True, data_only=True)
    counts = None
    try:
        for sheet in workbook.worksheets:
            sheet_rows = sheet.iter_rows(values_only=True)
            try:
                header = next(sheet_rows)
            except StopIteration:
                continue
            if REQUIRED_HEADERS <= {_normalized_header(value) for value in header}:
                counts = import_rows(chain([header], sheet_rows), output_db)
                break
    finally:
        workbook.close()
    if counts is None:
        raise ValueError("no workbook sheet contains the required UCI transaction fields")

    output_hash = file_sha256(output_db)
    record = {
        "name": SOURCE_NAME,
        "url": SOURCE_URL,
        "version": f"UCI dataset 502; source sha256 {workbook_hash}",
        "licence": SOURCE_LICENSE,
        "permitted_use": PERMITTED_USE,
        "split": "development",
        "layer": "public_transactional",
        "citation": "Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning Repository.",
        "doi": "10.24432/C5CG6D",
        "intake_status": "ingested",
        "source_sha256": workbook_hash,
        "artifact_sha256": output_hash,
        "transformation": TRANSFORMATION,
        "privacy_approval_ref": privacy_approval_ref.strip(),
    }
    try:
        validate_uci_provenance(record)
        record["privacy_approval_reviewer"] = approval["reviewer"]
        record["privacy_approval_reviewed_at"] = approval["reviewed_at"]
        register_dataset(record, provenance_path)
    except Exception:
        # Do not leave a dataset artifact that has no corresponding provenance.
        Path(output_db).unlink(missing_ok=True)
        raise
    return {**counts, "source_sha256": workbook_hash,
            "artifact_sha256": output_hash, "provenance": record}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="official UCI workbook downloaded separately")
    parser.add_argument("--output", required=True, help="new SQLite target; existing files are refused")
    parser.add_argument("--privacy-approval-ref", required=True,
                        help="identifier for the completed privacy review")
    parser.add_argument("--privacy-approval-record", required=True,
                        help="path to the organization-provided approval record JSON")
    parser.add_argument("--provenance", default="data/provenance.json")
    args = parser.parse_args()
    result = intake_workbook(args.source, args.output,
                             privacy_approval_ref=args.privacy_approval_ref,
                             privacy_approval_record=args.privacy_approval_record,
                             provenance_path=args.provenance)
    print(f"Imported {result['imported_rows']} rows; rejected {result['rejected_rows']}; "
          f"source sha256={result['source_sha256']}; artifact sha256={result['artifact_sha256']}")


if __name__ == "__main__":
    main()
