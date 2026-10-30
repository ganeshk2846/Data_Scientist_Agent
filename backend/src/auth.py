"""Fail-closed bearer-token authentication for the HTTP API."""

from __future__ import annotations

import hmac
import json
import os
from collections.abc import Mapping

from fastapi import HTTPException

TOKEN_ENV = "DS_AGENT_API_TOKENS"


class ApiTokenAuthenticator:
    """Authenticate configured user-to-token mappings without logging secrets."""

    def __init__(self, tokens: Mapping[str, str] | None = None) -> None:
        self._tokens = dict(tokens or {})
        seen: set[str] = set()
        for principal, token in self._tokens.items():
            if not principal.strip() or principal != principal.strip():
                raise ValueError("API token principals must be non-blank stable IDs")
            if (
                len(token) < 32
                or not token.isascii()
                or not token.isprintable()
                or any(character.isspace() for character in token)
            ):
                raise ValueError("API bearer tokens must be at least 32 characters")
            if token in seen:
                raise ValueError("Each API principal must have a unique bearer token")
            seen.add(token)

    @classmethod
    def from_environment(cls) -> ApiTokenAuthenticator:
        raw = os.environ.get(TOKEN_ENV, "").strip()
        if not raw:
            single = os.environ.get("DS_AGENT_TOKEN", "").strip()
            if single:
                return cls({"dev_user": single})
            return cls()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{TOKEN_ENV} must be a JSON object") from exc
        if not isinstance(parsed, dict) or not all(
            isinstance(principal, str) and isinstance(token, str)
            for principal, token in parsed.items()
        ):
            raise ValueError(f"{TOKEN_ENV} must map user IDs to bearer tokens")
        return cls(parsed)

    def authenticate(self, authorization: str | None) -> str:
        if not self._tokens:
            return "dev_user"
        scheme, separator, supplied = (authorization or "").partition(" ")
        if not separator or scheme.casefold() != "bearer" or not supplied:
            raise HTTPException(
                status_code=401,
                detail="Bearer authentication is required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        principal = None
        for configured_principal, configured_token in self._tokens.items():
            if hmac.compare_digest(supplied, configured_token):
                principal = configured_principal
        if principal is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return principal


__all__ = ["TOKEN_ENV", "ApiTokenAuthenticator"]
