"""FastAPI surface for runs, SSE progress, and complete answer envelopes."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Automatically add backend/src to Python search path
_SRC_DIR = str(Path(__file__).resolve().parent)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

from auth import ApiTokenAuthenticator
from contracts.models import AnswerEnvelope, AskRequest, AskResponse
from feedback import FeedbackRequest, FeedbackStore
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from service import (
    RunNotFoundError,
    RunService,
    build_runtime,
    format_sse_event,
)
from service_v2 import AskV2Request, V2Runner
from trace_logger import TraceLogger

_DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[2] / "brazil_ecommerce.sqlite"
# DS_AGENT_DB points the backend at another database, e.g. the V2 build
# data/brazil_ecommerce_v2.sqlite; DS_AGENT_DATABASE is the older name and
# still works. With neither set, the real snapshot stays the default.
_DATABASE_PATH = (
    Path(
        os.environ.get("DS_AGENT_DB")
        or os.environ.get("DS_AGENT_DATABASE")
        or _DEFAULT_DATABASE_PATH
    )
    .expanduser()
    .resolve()
)
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
        client = reasoning_client
        if client is None:
            try:
                from models.client import OllamaClient

                client = OllamaClient(model=os.environ.get("LLM_MODEL", "gemini-3.5-flash-lite"), base_url=os.environ.get("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"), api_key=os.environ.get("LLM_API_KEY"))
            except Exception:
                client = None
        service = RunService(
            lambda: build_runtime(
                resolved_database,
                reasoning_client=client,
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

    v2 = V2Runner(service)
    feedback = FeedbackStore.from_environment()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            v2.close()
            service.close()

    app = FastAPI(
        title="DS Agent",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.run_service = service
    app.state.api_authenticator = authenticator
    app.state.v2_runner = v2

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

    @app.post("/api/v2/ask", response_model=AskResponse)
    def ask_v2(
        payload: AskV2Request,
        authorization: str | None = Header(default=None),
    ) -> AskResponse:
        """The V2 pipeline: intent, grounding, clarification, plan, steps (additive; /api/ask is unchanged)."""
        principal = authenticator.authenticate(authorization)
        try:
            run_id = v2.submit(payload, owner_id=principal)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return AskResponse(run_id=run_id)

    @app.get("/api/v2/runs/{run_id}")
    def get_run_v2(
        run_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        principal = authenticator.authenticate(authorization)
        try:
            if service.store.owner_id(run_id) != principal:
                raise RunNotFoundError(run_id)
            envelope = service.store.wait_for_envelope(run_id, timeout=15.0)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        if envelope is None:
            return JSONResponse(status_code=202, content={"contract_version": "2.0.0", "run_id": run_id, "status": "running"})
        return JSONResponse(content=envelope.model_dump(mode="json"))

    @app.get("/api/sessions/{session_id}/history")
    def session_history(
        session_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        """The session's ContextState (contracts.md §1): the caller's own turns only (OPS-4)."""
        principal = authenticator.authenticate(authorization)
        state = v2.contexts.history(principal, session_id, catalog_version=v2.catalog_version())
        return JSONResponse(content=state.model_dump(mode="json"))

    @app.post("/api/sessions/{session_id}/reset")
    def session_reset(
        session_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        """Forget the caller's context for this session; the next question is cold."""
        principal = authenticator.authenticate(authorization)
        cleared = v2.contexts.reset(principal, session_id)
        return JSONResponse(content={"session_id": session_id, "cleared_turns": cleared})

    @app.post("/api/sessions/{session_id}/feedback")
    def session_feedback(
        session_id: str,
        payload: FeedbackRequest,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        """Thumbs up / down on one of the caller's own runs, with an optional reason (Track 5)."""
        principal = authenticator.authenticate(authorization)
        try:
            if service.store.owner_id(payload.run_id) != principal:
                raise RunNotFoundError(payload.run_id)
            record = feedback.record(principal, session_id, payload)
        except RunNotFoundError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse(content=record.model_dump(mode="json"))

    @app.get("/api/sessions/{session_id}/feedback")
    def session_feedback_list(
        session_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        """The caller's own ratings in this session, one per run (Track 5)."""
        principal = authenticator.authenticate(authorization)
        records = feedback.list(principal, session_id)
        return JSONResponse(content={"session_id": session_id, "feedback": [r.model_dump(mode="json") for r in records]})

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
