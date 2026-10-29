"""Application-level scoring authorization, supplied by a trusted host.

This is a deny-by-default code boundary only. Filesystem ACLs and a separate OS
identity are still required to protect held-out artifacts from workspace users.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar

_ACTIVE_SPLIT: ContextVar[str] = ContextVar("texttosql_active_split", default="development")


@contextmanager
def heldout_scoring_scope():
    token = _ACTIVE_SPLIT.set("held-out")
    try:
        yield
    finally:
        _ACTIVE_SPLIT.reset(token)


def require_development_write(operation: str) -> None:
    if _ACTIVE_SPLIT.get() == "held-out":
        raise PermissionError(f"{operation} is blocked during held-out scoring")


class ScoringAccessPolicy:
    def __init__(self, authorized_principals):
        if isinstance(authorized_principals, str):
            raise TypeError("authorized_principals must be a collection of authenticated principal IDs")
        self._principals = frozenset(
            value.strip() for value in authorized_principals if isinstance(value, str) and value.strip()
        )

    @classmethod
    def from_environment(cls) -> "ScoringAccessPolicy":
        """Read host-provisioned principals; keep this variable outside dev control."""
        return cls(os.environ.get("TEXTTOSQL_SCORING_PRINCIPALS", "").split(","))

    def authorize(self, principal: str | None) -> bool:
        return bool(isinstance(principal, str) and principal.strip()
                    and principal.strip() in self._principals)

    def require(self, principal: str | None) -> None:
        if not self.authorize(principal):
            raise PermissionError("held-out data is denied: authenticated scoring principal required")
