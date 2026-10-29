"""FastAPI surface for runs, SSE progress, and complete answer envelopes."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Iterator

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from contracts.models import AnswerEnvelope, AskRequest, AskResponse
from auth import ApiTokenAuthenticator
from service import (
    RunNotFoundError,
    RunService,
    build_runtime,
    format_sse_event,
)
from trace_logger import TraceLogger

_DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[2] / "brazil_ecommerce.sqlite"
_DATABASE_PATH = Path(
    os.environ.get("DS_AGENT_DATABASE", _DEFAULT_DATABASE_PATH)
).expanduser().resolve()
_TRACE_DIR = Path(__file__).resolve().parents[1] / "traces"
_FRONTEND_INDEX = (
    Path(__file__).resolve().parents[2] / "frontend" / "index.html"
).resolve()


def create_app(
    *,
    database_path: str | Path | None = None,
    trace_dir: str | Path | None = None,
    reasoning_client: object | None = None,
    run_service: RunService | None = None,
    api_tokens: dict[str, str] | None = None,
) -> FastAPI:
    """Build the API app; dependencies can be replaced for tests."""

    if run_service is None:
        resolved_database = Path(database_path or _DATABASE_PATH)
        service = RunService(
            lambda: build_runtime(
                resolved_database,
                reasoning_client=reasoning_client,
            ),
            logger=TraceLogger(trace_dir or _TRACE_DIR),
        )
    else:
        service = run_service
    authenticator = (
        ApiTokenAuthenticator.from_environment()
        if api_tokens is None
        else ApiTokenAuthenticator(api_tokens)
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            service.close()

    app = FastAPI(
        title="DS Agent",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.run_service = service
    app.state.api_authenticator = authenticator

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        if _FRONTEND_INDEX.exists():
            return HTMLResponse(content=_FRONTEND_INDEX.read_text(encoding="utf-8"))
        return HTMLResponse(
            content="""<!DOCTYPE html>
<html>
<head><title>DS Agent</title></head>
<body style="font-family:sans-serif;background:#0b0f19;color:#e5e7eb;padding:40px;">
  <h1>Enterprise Data Scientist Agent</h1>
  <p>Interactive API docs: <a href="/docs" style="color:#38bdf8;">/docs</a></p>
</body>
</html>"""
        )

    @app.post("/api/ask", response_model=AskResponse)
    def ask(
        payload: AskRequest,
        authorization: str | None = Header(default=None),
    ) -> AskResponse:
        principal = authenticator.authenticate(authorization)
        try:
            run_id = service.submit(
                payload.question,
                owner_id=principal,
                session_id=payload.session_id,
                clarification_of=payload.clarification_of,
            )
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return AskResponse(run_id=run_id)

    @app.get("/api/runs/{run_id}/events")
    def events(
        run_id: str,
        last_event_id: str | None = Header(
            default=None,
            alias="Last-Event-ID",
        ),
        authorization: str | None = Header(default=None),
    ) -> StreamingResponse:
        principal = authenticator.authenticate(authorization)
        try:
            if service.store.owner_id(run_id) != principal:
                raise RunNotFoundError(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        after = _parse_last_event_id(last_event_id)
        return StreamingResponse(
            _event_stream(service, run_id, after=after),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/runs/{run_id}", response_model=AnswerEnvelope)
    def get_run(
        run_id: str,
        authorization: str | None = Header(default=None),
    ) -> AnswerEnvelope | JSONResponse:
        principal = authenticator.authenticate(authorization)
        try:
            if service.store.owner_id(run_id) != principal:
                raise RunNotFoundError(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        try:
            envelope = service.store.wait_for_envelope(run_id, timeout=15.0)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        if envelope is None:
            return JSONResponse(
                status_code=202,
                content={
                    "contract_version": "1.0.0",
                    "run_id": run_id,
                    "status": "running",
                },
            )
        return envelope

    return app


def _event_stream(
    service: RunService,
    run_id: str,
    *,
    after: int,
) -> Iterator[str]:
    try:
        for event in service.store.stream(run_id, after=after):
            if event is None:
                yield ": keep-alive\n\n"
            else:
                yield format_sse_event(event)
    except RunNotFoundError:
        return


def _parse_last_event_id(value: str | None) -> int:
    if value is None or not value.strip():
        return 0
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Last-Event-ID must be an integer sequence number",
        ) from exc
    if parsed < 0:
        raise HTTPException(
            status_code=400,
            detail="Last-Event-ID must not be negative",
        )
    return parsed


app = create_app()


__all__ = ["app", "create_app"]
