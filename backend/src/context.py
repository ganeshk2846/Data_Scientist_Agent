"""Per-session conversation context for the V2 path (Track 4, contracts.md §1).

``ContextStore`` holds one :class:`ContextState` per ``(owner_id, session_id)``:

- **CTX-1.** At most :data:`CONTEXT_WINDOW` (10) turns; the oldest is dropped
  first. The question rewriter reads only ``ContextState.rewrite_turns()``,
  the last :data:`REWRITE_WINDOW` (3) turns (CTX-1b).
- **CTX-2.** A turn stores ``claim_ids`` as references (``"C1"``) and a
  number-free ``scope_summary``. No answer value, conclusion text or row is
  ever stored here.
- **CTX-3.** A state built under another ``catalog_version`` is dropped on read,
  so a follow-up after a catalog change is a cold question.
- **CTX-4.** A ``blocked`` turn records the question with ``resolved = None``.
- **CTX-5.** ``scope_summary`` is one safe-to-display line.
- **OPS-4.** The key includes the *authenticated* principal, never a value the
  client supplies, so one user's session id cannot read another user's context.

Storage is in memory. Setting ``DS_AGENT_CONTEXT_DB`` (or passing ``path``)
also persists each state as JSON in a **separate** SQLite file holding one
table, ``context_sessions``. The store refuses a file that holds any other
table, so it can never be pointed at the warehouse (``brazil_ecommerce.sqlite``).
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from contracts.v2 import (
    CONTEXT_WINDOW,
    ClarificationRequest,
    ContextState,
    ConversationTurn,
    IntentName,
    ResolvedQuestion,
)
from intent import describe_period
from pydantic import ValidationError

CONTEXT_DB_ENV = "DS_AGENT_CONTEXT_DB"
_TABLE = "context_sessions"
_TURN_NUMBER = re.compile(r"^T(\d+)$")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def scope_summary(resolved: ResolvedQuestion | None, *, intent: IntentName | None, status: str) -> str:
    """One number-free line describing what a turn asked (CTX-2, CTX-5).

    Built only from the resolved slots - metric id, window, filters,
    breakdowns - never from the answer, so no figure can leak into context.
    """

    parts: list[str] = []
    if resolved is not None:
        parts.append(resolved.metric_id or resolved.ungoverned_metric_term or "no metric")
        if resolved.period is not None:
            parts.append(describe_period(resolved.period))
        if resolved.comparison_period is not None:
            parts.append(f"vs {describe_period(resolved.comparison_period)}")
        for item in resolved.filters:
            parts.append(f"{item.dimension} {item.operator} {'/'.join(item.values)}")
        if resolved.dimensions:
            parts.append(f"by {', '.join(resolved.dimensions)}")
    if intent is not None:
        parts.append(intent)
    parts.append(status)
    return " · ".join(part.replace("\n", " ").replace("\r", " ") for part in parts)[:300]


class ContextStore:
    """Thread-safe store of bounded per-session context, keyed by owner and session."""

    def __init__(self, *, path: str | Path | None = None, window: int = CONTEXT_WINDOW) -> None:
        if not 1 <= window <= CONTEXT_WINDOW:
            raise ValueError(f"window must be between 1 and {CONTEXT_WINDOW}")
        self.window = window
        self._lock = threading.RLock()
        self._states: dict[tuple[str, str], ContextState] = {}
        self.path = Path(path).expanduser().resolve() if path else None
        if self.path is not None:
            self._init_db(self.path)

    @classmethod
    def from_environment(cls) -> ContextStore:
        raw = os.environ.get(CONTEXT_DB_ENV, "").strip()
        return cls(path=raw or None)

    # ------------------------------------------------------------------ #
    # reads

    def get(self, owner_id: str, session_id: str, *, catalog_version: str) -> ContextState:
        """The session's context, empty if absent or built under another catalog (CTX-3)."""

        key = (owner_id, session_id)
        with self._lock:
            state = self._states.get(key)
            if state is None and self.path is not None:
                state = self._load(key)
                if state is not None:
                    self._states[key] = state
            if state is not None and not state.is_valid_for(catalog_version):
                self._drop(key)
                state = None
            if state is None:
                return ContextState(session_id=session_id, catalog_version=catalog_version)
            return state

    def history(self, owner_id: str, session_id: str, *, catalog_version: str) -> ContextState:
        return self.get(owner_id, session_id, catalog_version=catalog_version)

    # ------------------------------------------------------------------ #
    # writes

    def record(
        self,
        owner_id: str,
        session_id: str,
        *,
        catalog_version: str,
        run_id: str,
        question: str,
        status: str,
        resolved: ResolvedQuestion | None,
        intent: IntentName | None,
        claim_ids: Iterable[str] = (),
        pending_clarification: ClarificationRequest | None = None,
    ) -> ConversationTurn:
        """Append one turn, dropping the oldest beyond the window (CTX-1)."""

        if status == "blocked":
            # CTX-4: an injection attempt cannot seed the next turn.
            resolved = None
        with self._lock:
            state = self.get(owner_id, session_id, catalog_version=catalog_version)
            turn = ConversationTurn(
                turn_id=f"T{self._next_number(state.turns)}",
                run_id=run_id,
                at=_now(),
                question=question,
                resolved=resolved,
                intent=intent,
                status=status,  # type: ignore[arg-type]
                claim_ids=tuple(claim_ids),
                scope_summary=scope_summary(resolved, intent=intent, status=status),
            )
            turns = (*state.turns, turn)[-self.window:]
            updated = ContextState(
                session_id=session_id,
                catalog_version=catalog_version,
                turns=turns,
                pending_clarification=pending_clarification,
            )
            self._states[(owner_id, session_id)] = updated
            self._save((owner_id, session_id), updated)
            return turn

    def reset(self, owner_id: str, session_id: str) -> int:
        """Forget the session's context; returns how many turns were dropped."""

        key = (owner_id, session_id)
        with self._lock:
            state = self._states.get(key)
            if state is None and self.path is not None:
                state = self._load(key)
            count = len(state.turns) if state is not None else 0
            self._drop(key)
            return count

    # ------------------------------------------------------------------ #

    @staticmethod
    def _next_number(turns: Iterable[ConversationTurn]) -> int:
        numbers = [int(match.group(1)) for turn in turns if (match := _TURN_NUMBER.match(turn.turn_id))]
        return max(numbers, default=0) + 1

    def _drop(self, key: tuple[str, str]) -> None:
        self._states.pop(key, None)
        if self.path is not None:
            with self._connect() as connection:
                connection.execute(f"DELETE FROM {_TABLE} WHERE owner_id = ? AND session_id = ?", key)

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
            uri = f"file:{path}?mode=ro"
            probe = sqlite3.connect(uri, uri=True)
            try:
                names = {row[0] for row in probe.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            finally:
                probe.close()
            others = names - {_TABLE}
            if others:
                raise ValueError(
                    f"{path} already holds other tables ({', '.join(sorted(others)[:5])}); the context store "
                    f"must use its own SQLite file and never the warehouse"
                )
        with self._connect() as connection:
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
                "owner_id TEXT NOT NULL, session_id TEXT NOT NULL, state_json TEXT NOT NULL, "
                "updated_at TEXT NOT NULL, PRIMARY KEY (owner_id, session_id))"
            )

    def _load(self, key: tuple[str, str]) -> ContextState | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT state_json FROM {_TABLE} WHERE owner_id = ? AND session_id = ?", key
            ).fetchone()
        if row is None:
            return None
        try:
            return ContextState.model_validate_json(row[0])
        except ValidationError:
            # A row that no longer validates is dropped, never half-used.
            return None

    def _save(self, key: tuple[str, str], state: ContextState) -> None:
        if self.path is None:
            return
        with self._connect() as connection:
            connection.execute(
                f"INSERT INTO {_TABLE} (owner_id, session_id, state_json, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(owner_id, session_id) DO UPDATE SET state_json = excluded.state_json, "
                "updated_at = excluded.updated_at",
                (*key, state.model_dump_json(), _now()),
            )


__all__ = ["CONTEXT_DB_ENV", "ContextStore", "scope_summary"]
