"""Local integration coverage for the BE-2 Python service boundary."""
import sqlite3

import pytest

from src.onboarding.service import OnboardingService
from src.knowledge.stores import MetricRegistry


def warehouse(path):
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, email TEXT);
        INSERT INTO customers VALUES (1, 'private@example.test');
    """)
    connection.commit()
    connection.close()


def test_persistent_onboarding_review_and_refresh_service(tmp_path):
    database = tmp_path / "warehouse.sqlite"
    warehouse(database)
    root = tmp_path / "service"
    service = OnboardingService(root)

    started = service.start(database)
    job_id = started["job_id"]
    status = service.wait(job_id)
    assert status["status"] == "needs_review"
    assert status["stages"]["report"]["status"] == "complete"
    assert service.sensitive_columns(job_id) == ["customers.email"]
    assert service.report(job_id)["table_count"] == 1

    published = service.decide_review(job_id, reviewer="reviewer-1",
                                      approve_sensitive=["customers.email"])
    assert published["status"] == "complete"
    assert service.sensitive_columns(job_id) == []

    reopened = OnboardingService(root)
    assert reopened.status(job_id)["catalog_version"] == published["catalog_version"]
    refresh_job = reopened.refresh(job_id)
    refreshed = reopened.wait(refresh_job["job_id"])
    assert refreshed["status"] == "complete"
    assert reopened.report(job_id)["changed_tables"] == []

    with pytest.raises(KeyError):
        reopened.status("unknown-job")


def test_service_requires_named_reviewer_and_reports_missing_warehouse(tmp_path):
    service = OnboardingService(tmp_path / "service")
    with pytest.raises(FileNotFoundError, match="SQLite warehouse"):
        service.start(tmp_path / "missing.sqlite")

    database = tmp_path / "warehouse.sqlite"
    warehouse(database)
    job_id = service.start(database)["job_id"]
    service.wait(job_id)
    with pytest.raises(ValueError, match="named human reviewer"):
        service.decide_review(job_id, reviewer="unknown", approve_sensitive=["customers.email"])


def test_service_exposes_golden_and_registry_review_workflows(tmp_path):
    service = OnboardingService(tmp_path / "service",
                                metric_reviewer_authorizer=lambda identity: identity == "reviewer-3")
    candidate_id = service.golden.propose(
        "count all active users", "SELECT COUNT(*) FROM users", "run-1",
        [{"name": "result-check", "passed": True}],
    )
    assert service.golden_candidates()[0]["entry_id"] == candidate_id
    service.decide_golden(candidate_id, approve=False, reviewer="reviewer-2",
                          result_checks_passed=False, rejection_reason="Incorrect reference result.")
    assert service.golden_candidates() == []

    metric = {
        "name": "revenue", "synonyms": ["sales"], "formula": "SUM(amount)",
        "required_filters": [], "grain": ["month"], "date_column": "created_at",
        "allowed_dimensions": [], "base_table": "orders", "join_path": [],
        "caveats": [], "reconciliation_values": {},
    }
    proposed = service.registry.propose(metric)
    assert service.registry_changes() == [proposed]
    service.decide_registry(proposed["id"], approve=True, reviewer="reviewer-3")
    assert service.registry_changes() == []
    assert service.registry.resolve("sales")["name"] == "revenue"


def test_async_jobs_are_durable_and_refresh_schedule_is_persisted(tmp_path):
    database = tmp_path / "warehouse.sqlite"
    warehouse(database)
    root = tmp_path / "service"
    service = OnboardingService(root, max_workers=1)
    job_id = service.start(database)["job_id"]
    assert service.status(job_id)["status"] in {"queued", "running", "needs_review"}
    completed = service.wait(job_id)
    assert completed["status"] == "needs_review", {
        "status": completed["status"],
        "error": completed["error"],
        "stages": completed["stages"],
    }

    schedule = service.schedule_refresh(job_id, interval_seconds=60)
    assert schedule["enabled"]
    reopened = OnboardingService(root)
    assert reopened.run_due_refreshes(now=schedule["next_run"] - 1) == []
    assert reopened.run_due_refreshes(now=schedule["next_run"]) == [job_id]
    assert reopened.wait(job_id)["mode"] == "refresh"
    reopened.unschedule_refresh(job_id)
    assert reopened.run_due_refreshes(now=schedule["next_run"] + 3600) == []


def test_async_job_retries_a_transient_file_permission_error(tmp_path, monkeypatch):
    import src.onboarding.service as service_module

    database = tmp_path / "warehouse.sqlite"
    warehouse(database)
    original_build = service_module.build_catalog
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("transient file lock")
        return original_build(*args, **kwargs)

    monkeypatch.setattr(service_module, "build_catalog", fail_once)
    service = OnboardingService(tmp_path / "service", max_workers=1)
    job_id = service.start(database)["job_id"]

    completed = service.wait(job_id)

    assert completed["status"] == "needs_review", completed
    assert attempts == 2


def test_scheduler_rejects_invalid_intervals_and_active_duplicate_refresh(tmp_path, monkeypatch):
    import threading
    import src.onboarding.service as service_module

    database = tmp_path / "warehouse.sqlite"
    warehouse(database)
    service = OnboardingService(tmp_path / "service", max_workers=1)
    entered = threading.Event()
    release = threading.Event()
    original_build = service_module.build_catalog

    def blocked_build(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return original_build(*args, **kwargs)

    monkeypatch.setattr(service_module, "build_catalog", blocked_build)
    job_id = service.start(database)["job_id"]
    assert entered.wait(timeout=5)
    with pytest.raises(ValueError, match="positive"):
        service.schedule_refresh(job_id, interval_seconds=0)
    with pytest.raises(RuntimeError, match="already active"):
        service.refresh(job_id)
    release.set()
    service.wait(job_id)


def test_failed_and_interrupted_jobs_can_be_recovered_and_retried(tmp_path, monkeypatch):
    import src.onboarding.service as service_module

    database = tmp_path / "warehouse.sqlite"
    warehouse(database)
    service = OnboardingService(tmp_path / "service")
    original_build = service_module.build_catalog

    def fail_build(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(service_module, "build_catalog", fail_build)
    job_id = service.start(database)["job_id"]
    assert service.wait(job_id)["status"] == "failed"
    assert service.status(job_id)["error"].startswith("OSError: simulated disk failure")

    monkeypatch.setattr(service_module, "build_catalog", original_build)
    assert service.retry(job_id)["job_id"] == job_id
    assert service.wait(job_id)["status"] == "needs_review"

    with service._connect() as db:
        db.execute("UPDATE jobs SET status='running', updated_at='2000-01-01T00:00:00+00:00' WHERE job_id=?", (job_id,))
    assert service.recover_interrupted_jobs(older_than_seconds=60) == [job_id]
    assert service.status(job_id)["status"] == "failed"
    with pytest.raises(ValueError, match="positive"):
        service.recover_interrupted_jobs(older_than_seconds=0)
