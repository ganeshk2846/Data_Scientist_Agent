"""Per-session answer feedback: thumbs up / down with an optional reason (Track 5, item 8).

- Keyed by the **authenticated** principal and the session id, like the
  context store (OPS-4): one user can never read or overwrite another's.
- One rating per run; rating a run again replaces the earlier rating.
- A reason is one safe-to-display line of at most :data:`MAX_REASON` chars.
- Storage is in memory. Setting ``DS_AGENT_FEEDBACK_DB`` also persists to a
  **separate** SQLite file holding only ``answer_feedback``; the store refuses
  a file with any other table, so it can never be pointed at the warehouse.

Feedback never feeds back into an answer: no figure, ranking or route reads it.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FEEDBACK_DB_ENV = "DS_AGENT_FEEDBACK_DB"
MAX_REASON = 500
MAX_PER_SESSION = 200
_TABLE = "answer_feedback"

Rating = Literal["up", "down"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=128)
    rating: Rating
    reason: str | None = Field(default=None, max_length=MAX_REASON)

    @field_validator("reason")
    @classmethod
    def _one_line(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = " ".join(value.split())
        return text or None


class FeedbackRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    run_id: str
    rating: Rating
    reason: str | None = None
    created_at: str


class FeedbackStore:
    """Thread-safe feedback, keyed by (owner, session), one record per run."""

    def __init__(self, *, path: str | Path | None = None) -> None:
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str], dict[str, FeedbackRecord]] = {}
        self.path = Path(path).expanduser().resolve() if path else None
        if self.path is not None:
            self._init_db(self.path)

    @classmethod
    def from_environment(cls) -> FeedbackStore:
        raw = os.environ.get(FEEDBACK_DB_ENV, "").strip()
        return cls(path=raw or None)

    def record(self, owner_id: str, session_id: str, request: FeedbackRequest) -> FeedbackRecord:
        record = FeedbackRecord(session_id=session_id, run_id=request.run_id, rating=request.rating,
                                reason=request.reason, created_at=_now())
        key = (owner_id, session_id)
        with self._lock:
            bucket = self._bucket(key)
            if request.run_id not in bucket and len(bucket) >= MAX_PER_SESSION:
                raise ValueError(f"a session holds at most {MAX_PER_SESSION} ratings")
            bucket[request.run_id] = record
            if self.path is not None:
                with self._connect() as connection:
                    connection.execute(
                        f"INSERT INTO {_TABLE} (owner_id, session_id, run_id, rating, reason, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(owner_id, session_id, run_id) DO UPDATE SET "
                        "rating = excluded.rating, reason = excluded.reason, created_at = excluded.created_at",
                        (owner_id, session_id, record.run_id, record.rating, record.reason, record.created_at),
                    )
        return record

    def list(self, owner_id: str, session_id: str) -> tuple[FeedbackRecord, ...]:
        with self._lock:
            return tuple(self._bucket((owner_id, session_id)).values())

    def _bucket(self, key: tuple[str, str]) -> dict[str, FeedbackRecord]:
        bucket = self._records.get(key)
        if bucket is None:
            bucket = self._load(key) if self.path is not None else {}
            self._records[key] = bucket
        return bucket

    # ------------------------------------------------------------------ #
    # optional SQLite persistence (a separate file, never the warehouse)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        assert self.path is not None
        connection = sqlite3.connect(self.path, timeout=5.0)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _init_db(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 0:
            probe = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                names = {row[0] for row in probe.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            finally:
                probe.close()
            others = names - {_TABLE}
            if others:
                raise ValueError(
                    f"{path} already holds other tables ({', '.join(sorted(others)[:5])}); the feedback store "
                    f"must use its own SQLite file and never the warehouse"
                )
        with self._connect() as connection:
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
                "owner_id TEXT NOT NULL, session_id TEXT NOT NULL, run_id TEXT NOT NULL, rating TEXT NOT NULL, "
                "reason TEXT, created_at TEXT NOT NULL, PRIMARY KEY (owner_id, session_id, run_id))"
            )

    def _load(self, key: tuple[str, str]) -> dict[str, FeedbackRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT run_id, rating, reason, created_at FROM {_TABLE} WHERE owner_id = ? AND session_id = ? "
                "ORDER BY created_at", key,
            ).fetchall()
        bucket: dict[str, FeedbackRecord] = {}
        for run_id, rating, reason, created_at in rows:
            if rating in ("up", "down"):
                bucket[run_id] = FeedbackRecord(session_id=key[1], run_id=run_id, rating=rating, reason=reason,
                                                created_at=created_at)
        return bucket


__all__ = ["FEEDBACK_DB_ENV", "FeedbackRecord", "FeedbackRequest", "FeedbackStore"]
