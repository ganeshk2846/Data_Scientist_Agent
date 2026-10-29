"""Durable local BE-2 service boundary with asynchronous refresh workers.

The HTTP/authentication boundary belongs to BE-1. Reviewer names passed here
must come from its authenticated principal, never untrusted request data.
"""
from __future__ import annotations

import json
import contextlib
import sqlite3
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.knowledge.stores import GoldenStore, MetricRegistry
from .privacy import redact_payload
from .pipeline import approve_review, build_catalog


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


class OnboardingService:
    """Persistent job/review service; jobs run on a bounded local worker pool.

    The job and schedule index is SQLite/WAL-backed. Each onboarding build has
    its own artifact directory. ``run_scheduler`` may be hosted as a service
    process to execute persisted schedules; stopping that process does not
    lose schedules or job records.
    """

    def __init__(self, root: str | Path, *, max_workers: int = 2, dense_encoder=None,
                 metric_reviewer_authorizer=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "service.sqlite3"
        self.registry = MetricRegistry(self.root / "metrics.json",
                                      reviewer_authorizer=metric_reviewer_authorizer)
        self.golden = GoldenStore(self.root / "golden.json")
        self.dense_encoder = dense_encoder
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="be2-onboard")
        self._futures: dict[str, Future] = {}
        self._guard = threading.RLock()
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY, source TEXT NOT NULL, output TEXT NOT NULL,
                    mode TEXT NOT NULL, status TEXT NOT NULL, catalog_version TEXT,
                    error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS refresh_schedules (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
                    interval_seconds INTEGER NOT NULL, next_run REAL NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1
                );
            """)

    @contextlib.contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA busy_timeout=30000")
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise
        finally:
            db.close()

    def start(self, connection: str | Path, *, sensitive_columns: list[str] | None = None,
              descriptions: dict[str, str] | None = None) -> dict[str, str]:
        source = Path(connection).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"SQLite warehouse not found: {source}")
        job_id = uuid.uuid4().hex
        output = self.root / "jobs" / job_id
        self._insert_job(job_id, source, output, "initial")
        self._submit(job_id, sensitive_columns=sensitive_columns, descriptions=descriptions)
        return {"job_id": job_id}

    def _insert_job(self, job_id: str, source: Path, output: Path, mode: str) -> None:
        now = _utc_now()
        with self._connect() as db:
            db.execute("INSERT INTO jobs VALUES (?, ?, ?, ?, 'queued', NULL, NULL, ?, ?)",
                       (job_id, str(source), str(output), mode, now, now))

    def _submit(self, job_id: str, *, sensitive_columns: list[str] | None = None,
                descriptions: dict[str, str] | None = None) -> None:
        with self._guard:
            future = self._executor.submit(self._run, job_id, sensitive_columns, descriptions,
                                           self.dense_encoder)
            self._futures[job_id] = future

    def _run(self, job_id: str, sensitive_columns, descriptions, dense_encoder):
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            db.execute("UPDATE jobs SET status='running', error=NULL, updated_at=? WHERE job_id=?",
                       (_utc_now(), job_id))
        stop_heartbeat = threading.Event()
        heartbeat = threading.Thread(target=self._heartbeat, args=(job_id, stop_heartbeat),
                                     name=f"be2-heartbeat-{job_id[:8]}", daemon=True)
        heartbeat.start()
        try:
            for attempt in range(3):
                try:
                    report = build_catalog(
                        row["source"],
                        row["output"],
                        sensitive_columns=sensitive_columns,
                        descriptions=descriptions,
                        dense_encoder=dense_encoder,
                    )
                    break
                except PermissionError:
                    if attempt == 2:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        except Exception as error:
            stop_heartbeat.set()
            heartbeat.join()
            with self._connect() as db:
                safe_detail = str(redact_payload(str(error)))
                safe_error = f"{type(error).__name__}: {safe_detail}"[:500]
                db.execute("UPDATE jobs SET status='failed', error=?, updated_at=? WHERE job_id=?",
                           (safe_error, _utc_now(), job_id))
            return
        stop_heartbeat.set()
        heartbeat.join()
        with self._connect() as db:
            db.execute("UPDATE jobs SET status=?, catalog_version=?, error=NULL, updated_at=? WHERE job_id=?",
                       (report["status"], report["catalog_version"], _utc_now(), job_id))

    def _heartbeat(self, job_id: str, stop_event: threading.Event) -> None:
        while not stop_event.wait(10):
            with self._connect() as db:
                db.execute("UPDATE jobs SET updated_at=? WHERE job_id=? AND status='running'",
                           (_utc_now(), job_id))

    def wait(self, job_id: str, timeout: float = 30.0) -> dict[str, Any]:
        """Wait for a local worker (primarily useful to CLI/tests)."""
        with self._guard:
            future = self._futures.get(job_id)
        if future is not None:
            future.result(timeout=timeout)
        return self.status(job_id)

    def status(self, job_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        output = Path(row["output"])
        state = _read(output / "job.json", {})
        return {"job_id": job_id, "status": row["status"],
                "catalog_version": row["catalog_version"], "stages": state.get("stages", {}),
                "error": row["error"], "mode": row["mode"], "updated_at": row["updated_at"]}

    def report(self, job_id: str) -> dict[str, Any]:
        output = Path(self._job(job_id)["output"])
        path = output / "report.json"
        if not path.exists():
            raise RuntimeError(f"Onboarding report is not available for job {job_id}")
        return _read(path, {})

    def refresh(self, job_id: str) -> dict[str, str]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] in ("queued", "running"):
                raise RuntimeError(f"Job {job_id} is already active")
            db.execute("UPDATE jobs SET mode='refresh', status='queued', error=NULL, updated_at=? WHERE job_id=?",
                       (_utc_now(), job_id))
        self._submit(job_id)
        return {"job_id": job_id}

    def recover_interrupted_jobs(self, *, older_than_seconds: int = 300) -> list[str]:
        """Mark jobs with expired worker leases failed so an operator can retry.

        Recovery is explicit to avoid one service process mistaking another
        live worker for an abandoned job. ``retry`` reuses pipeline artifacts,
        whose stage-level recovery is already tested.
        """
        if older_than_seconds < 1:
            raise ValueError("older_than_seconds must be positive")
        cutoff = datetime.fromtimestamp(time.time() - older_than_seconds, timezone.utc).isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT job_id FROM jobs WHERE status IN ('queued','running') AND updated_at < ?",
                              (cutoff,)).fetchall()
            job_ids = [row["job_id"] for row in rows]
            db.executemany("UPDATE jobs SET status='failed', error='worker lease expired', updated_at=? WHERE job_id=?",
                           [(_utc_now(), job_id) for job_id in job_ids])
        return job_ids

    def retry(self, job_id: str) -> dict[str, str]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] in ("queued", "running"):
                raise RuntimeError(f"Job {job_id} is already active")
            db.execute("UPDATE jobs SET status='queued', error=NULL, updated_at=? WHERE job_id=?",
                       (_utc_now(), job_id))
        self._submit(job_id)
        return {"job_id": job_id}

    def schedule_refresh(self, job_id: str, *, interval_seconds: int) -> dict[str, Any]:
        if interval_seconds < 1:
            raise ValueError("interval_seconds must be positive")
        self._job(job_id)
        next_run = time.time() + interval_seconds
        with self._connect() as db:
            db.execute("INSERT INTO refresh_schedules(job_id, interval_seconds, next_run, enabled) VALUES (?, ?, ?, 1) "
                       "ON CONFLICT(job_id) DO UPDATE SET interval_seconds=excluded.interval_seconds, "
                       "next_run=excluded.next_run, enabled=1",
                       (job_id, interval_seconds, next_run))
        return {"job_id": job_id, "interval_seconds": interval_seconds, "next_run": next_run, "enabled": True}

    def unschedule_refresh(self, job_id: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE refresh_schedules SET enabled=0 WHERE job_id=?", (job_id,))

    def run_due_refreshes(self, *, now: float | None = None) -> list[str]:
        """Queue due jobs; safe to call repeatedly from one scheduler process."""
        timestamp = time.time() if now is None else now
        due: list[str] = []
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT s.job_id, s.interval_seconds FROM refresh_schedules s "
                              "JOIN jobs j USING(job_id) WHERE s.enabled=1 AND s.next_run<=? "
                              "AND j.status NOT IN ('queued','running')", (timestamp,)).fetchall()
            for row in rows:
                db.execute("UPDATE refresh_schedules SET next_run=? WHERE job_id=?",
                           (timestamp + row["interval_seconds"], row["job_id"]))
                db.execute("UPDATE jobs SET mode='refresh', status='queued', error=NULL, updated_at=? WHERE job_id=?",
                           (_utc_now(), row["job_id"]))
                due.append(row["job_id"])
        for job_id in due:
            self._submit(job_id)
        return due

    def run_scheduler(self, stop_event: threading.Event, *, poll_seconds: float = 1.0) -> None:
        """Host this loop in a supervised process to run persisted schedules."""
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        while not stop_event.is_set():
            self.run_due_refreshes()
            stop_event.wait(poll_seconds)

    def joins(self, job_id: str, *, status: str | None = None) -> list[dict[str, Any]]:
        catalog = _read(Path(self._job(job_id)["output"]) / "catalog.json", {})
        rows = catalog.get("joins", [])
        return [row for row in rows if status is None or row.get("status") == status]

    def sensitive_columns(self, job_id: str) -> list[str]:
        return list(self.report(job_id).get("sensitive_suggestions_pending", []))

    def decide_review(self, job_id: str, *, reviewer: str,
                      approve_joins: list[str] | None = None, reject_joins: list[str] | None = None,
                      approve_sensitive: list[str] | None = None, reject_sensitive: list[str] | None = None) -> dict[str, Any]:
        output = self._job(job_id)["output"]
        approve_review(output, approve_joins=approve_joins, reject_joins=reject_joins,
                       approve_sensitive=approve_sensitive, reject_sensitive=reject_sensitive,
                       reviewer=reviewer)
        queued = self.refresh(job_id)
        return self.wait(queued["job_id"])

    def golden_candidates(self) -> list[dict[str, Any]]:
        rows = _read(self.golden.path, [])
        return [row for row in rows if row.get("status") == "proposed"]

    def decide_golden(self, candidate_id: str, *, approve: bool, reviewer: str,
                      result_checks_passed: bool, heldout_questions: list[str] | None = None,
                      rejection_reason: str | None = None) -> None:
        self.golden.decide(candidate_id, approve=approve, reviewer=reviewer,
                           result_checks_passed=result_checks_passed,
                           heldout_questions=heldout_questions, rejection_reason=rejection_reason)

    def registry_changes(self) -> list[dict[str, Any]]:
        rows = _read(self.registry.path, [])
        return [row for row in rows if row.get("status") == "proposed"]

    def decide_registry(self, metric_id: str, *, approve: bool, reviewer: str,
                        note: str | None = None, version: int | None = None) -> None:
        self.registry.decide(metric_id, approve=approve, reviewer=reviewer, note=note, version=version)

    def _job(self, job_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    def close(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=not wait)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
