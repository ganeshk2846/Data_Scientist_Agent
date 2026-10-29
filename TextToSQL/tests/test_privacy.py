import json
import sqlite3
from pathlib import Path
import subprocess
import sys

from src.knowledge.stores import TraceStore
from src.onboarding.pipeline import build_catalog
from src.onboarding.privacy import sensitive_value
from src.onboarding.profiler import profile_database


def make_canary_database(path: Path):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE contacts (col_17 TEXT, f3 TEXT, data TEXT, notes TEXT, context TEXT)")
    email = "Audit.Canary-6382@example.invalid"
    connection.execute(
        "INSERT INTO contacts VALUES (?, ?, ?, ?, ?)",
        (email, "AUDIT.CANARY-6382", "last4 6382", "https%3A%2F%2Fexample.invalid%2Fcontact%3FAUDIT%3D" + email.replace("@", "%40"), json.dumps({"contact": email})),
    )
    connection.commit()
    connection.close()


def test_standalone_profiler_masks_values_and_partial_canaries(tmp_path):
    db_path = tmp_path / "pii.sqlite"
    make_canary_database(db_path)
    profile = profile_database(str(db_path))
    serialized = repr(profile)
    for canary in ("Audit.Canary-6382@example.invalid", "AUDIT.CANARY-6382", "6382", "%40example"):
        assert canary.casefold() not in serialized.casefold()
    stats = profile["contacts"]["columns"]
    assert set(profile["contacts"]["sensitive_columns"]) == {"col_17", "f3", "data", "notes", "context"}
    for column in profile["contacts"]["sensitive_columns"]:
        assert stats[column]["sample_values"] == []
        assert stats[column]["min"] is None
        assert stats[column]["max"] is None


def test_pattern_detector_recognizes_supported_secret_shapes():
    assert sensitive_value("person@example.invalid")
    assert sensitive_value("+1 (415) 555-0198")
    assert sensitive_value("123-45-6789")
    assert sensitive_value("4111 1111 1111 1111")
    assert sensitive_value("198.51.100.23")
    assert sensitive_value("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature")
    assert sensitive_value("sk-abcdefghijklmnopqrstuvwx")
    assert sensitive_value("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
    assert not sensitive_value("2026-10-28")


def test_pipeline_masks_canary_from_all_json_artifacts(tmp_path):
    db_path = tmp_path / "pii.sqlite"
    output = tmp_path / "catalog"
    make_canary_database(db_path)
    report = build_catalog(db_path, output)
    assert report["self_test"]["passed"]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in output.glob("*.json"))
    for canary in ("Audit.Canary-6382@example.invalid", "AUDIT.CANARY-6382", "6382", "%40example"):
        assert canary.casefold() not in combined.casefold()
    index = json.loads((output / "index_build.json").read_text(encoding="utf-8"))
    assert not any(name in index["value_index"] for name in report["masked_columns"])
    assert not any("example.invalid" in json.dumps(item).casefold() for item in index["dense"]["documents"])
    assert not any(f"column:{name}" in index["dense"]["vectors"] for name in report["masked_columns"])


def test_cli_report_output_contains_no_canary(tmp_path):
    db_path = tmp_path / "cli.sqlite"
    output = tmp_path / "cli-catalog"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE people (col_17 TEXT)")
    connection.execute("INSERT INTO people VALUES (?)", ("cli-leak-7351@example.invalid",))
    connection.commit()
    connection.close()
    result = subprocess.run([sys.executable, "-m", "src.onboarding", "build", "--warehouse", str(db_path), "--output", str(output)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0
    assert "cli-leak-7351@example.invalid" not in result.stdout + result.stderr
    assert (output / "report.json").is_file()


def test_trace_store_redacts_before_persistence(tmp_path):
    path = tmp_path / "traces.json"
    TraceStore(path).append({"prompt": "contact person@example.invalid; last4 1234"})
    content = path.read_text(encoding="utf-8")
    assert "person@example.invalid" not in content
    assert "1234" not in content


def test_high_cardinality_name_column_is_masked_for_review(tmp_path):
    db_path = tmp_path / "names.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT)")
    connection.executemany("INSERT INTO people VALUES (?, ?)", [(i, f"ordinary-label-{i:05d}") for i in range(1, 1202)])
    connection.commit()
    connection.close()
    profile = profile_database(str(db_path))
    name = profile["people"]["columns"]["name"]
    assert name["high_cardinality_name"] is True
    assert name["sensitive"] is True
    assert name["sample_values"] == []
