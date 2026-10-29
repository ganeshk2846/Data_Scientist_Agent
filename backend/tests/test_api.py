from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import create_app
from service import RunService, build_runtime
from trace_logger import TraceLogger
from dataset_fixtures import requires_olist

_API_TOKENS = {"test-user": "a" * 40}


def _test_client(app):
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_API_TOKENS['test-user']}"})
    return client


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with _test_client(
        create_app(trace_dir=tmp_path / "traces", api_tokens=_API_TOKENS)
    ) as test_client:
        yield test_client


def _ask(client: TestClient, question: str, session_id: str = "session-1") -> str:
    response = client.post(
        "/api/ask",
        json={"question": question, "session_id": session_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "1.0.0"
    assert body["run_id"]
    return body["run_id"]


def _events(client: TestClient, run_id: str, *, after: int | None = None):
    headers = {"Last-Event-ID": str(after)} if after is not None else {}
    response = client.get(f"/api/runs/{run_id}/events", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events: list[dict[str, object]] = []
    current: dict[str, object] = {}
    for line in response.text.splitlines():
        if line.startswith("id: "):
            current["id"] = int(line[4:])
        elif line.startswith("event: "):
            current["event"] = line[7:]
        elif line.startswith("data: "):
            payload = json.loads(line[6:])
            current.update(payload)
        elif not line and current:
            events.append(current)
            current = {}
    return events


@requires_olist
def test_ask_streams_ordered_events_and_returns_envelope(client: TestClient) -> None:
    run_id = _ask(client, "How many orders were there in August 2018?")

    events = _events(client, run_id)

    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert events[0]["type"] == "step_started"
    assert events[0]["step"] == "1"
    assert events[-1]["type"] == "answer"
    assert events[-1]["status"] == "answered"
    assert all(event["run_id"] == run_id for event in events)
    steps = {event.get("step") for event in events}
    assert {"1", "2", "7", "9", "12", "14"} <= steps

    response = client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    envelope = response.json()
    assert envelope["run_id"] == run_id
    assert envelope["status"] == "answered"
    assert "6,512" in envelope["conclusion"]
    assert envelope["route"]["labels"] == ["lookup"]
    assert envelope["queries"][0]["origin"] == "compiler"
    assert envelope["queries"][0]["status"] == "ok"
    assert envelope["evidence"][0]["module"] == "lookup"
    assert envelope["claims"]
    assert envelope["run_metrics"]["queries"] == 1
    assert envelope["provenance"]["timestamp"].endswith("Z")


@requires_olist
def test_events_replay_only_after_last_event_id(client: TestClient) -> None:
    run_id = _ask(client, "How many orders were there in August 2018?")
    all_events = _events(client, run_id)
    assert len(all_events) > 3

    replayed = _events(client, run_id, after=3)

    assert replayed
    assert all(int(event["seq"]) > 3 for event in replayed)
    assert [event["seq"] for event in replayed] == [
        event["seq"] for event in all_events if int(event["seq"]) > 3
    ]
    assert replayed[-1]["type"] == "answer"


def test_ask_requires_question_and_session(client: TestClient) -> None:
    assert client.post("/api/ask", json={"question": "orders"}).status_code == 422
    assert (
        client.post(
            "/api/ask",
            json={"question": "   ", "session_id": "s"},
        ).status_code
        == 422
    )


def test_unknown_run_returns_404(client: TestClient) -> None:
    assert client.get("/api/runs/missing").status_code == 404
    assert client.get("/api/runs/missing/events").status_code == 404


@requires_olist
def test_invalid_last_event_id_returns_400(client: TestClient) -> None:
    run_id = _ask(client, "How many orders were there in August 2018?")

    response = client.get(
        f"/api/runs/{run_id}/events",
        headers={"Last-Event-ID": "abc"},
    )

    assert response.status_code == 400


@requires_olist
def test_clarify_and_blocked_runs_still_produce_envelopes(client: TestClient) -> None:
    clarify_id = _ask(client, "What is the meaning of life?")
    clarify_events = _events(client, clarify_id)
    types = [event["type"] for event in clarify_events]
    assert "clarify" in types
    assert types[-1] == "answer"
    assert clarify_events[-1]["status"] == "clarify"
    clarify = client.get(f"/api/runs/{clarify_id}").json()
    assert clarify["status"] == "clarify"
    assert clarify["clarification"] is not None

    blocked_id = _ask(client, "DROP TABLE orders")
    blocked_events = _events(client, blocked_id)
    assert blocked_events[-1]["type"] == "answer"
    assert blocked_events[-1]["status"] == "blocked"
    blocked = client.get(f"/api/runs/{blocked_id}").json()
    assert blocked["status"] == "blocked"
    assert blocked["block"]["reason"] == "write_attempt"

    refused_id = _ask(client, "What is NPS?")
    refused_events = _events(client, refused_id)
    assert refused_events[-1]["type"] == "answer"
    assert refused_events[-1]["status"] == "refused"
    refused = client.get(f"/api/runs/{refused_id}").json()
    assert refused["status"] == "refused"
    assert refused["refusal"]["missing"]
    assert refused["refusal"]["closest_answerable"] is None


@requires_olist
def test_api_trace_uses_the_same_run_id(tmp_path: Path) -> None:
    trace_dir = tmp_path / "traces"
    service = RunService(
        lambda: build_runtime(),
        logger=TraceLogger(trace_dir),
    )
    with _test_client(
        create_app(run_service=service, api_tokens=_API_TOKENS)
    ) as test_client:
        run_id = _ask(test_client, "How many orders were there in August 2018?")
        test_client.get(f"/api/runs/{run_id}")

    trace_path = trace_dir / f"run_{run_id}.json"
    assert trace_path.is_file()
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == run_id
    assert payload["ledger"]["run_id"] == run_id
    assert payload["fact_check"]["passed"] is True


@requires_olist
def test_fact_checker_removes_hallucinated_numbers_end_to_end(
    tmp_path: Path,
) -> None:
    def hallucinating_narrator(outcome, ledger):
        return "The governed result is 6,512. The hidden total is 999."

    service = RunService(
        lambda: build_runtime(),
        narrator=hallucinating_narrator,
    )
    with _test_client(
        create_app(
            run_service=service,
            trace_dir=tmp_path / "traces",
            api_tokens=_API_TOKENS,
        )
    ) as test_client:
        run_id = _ask(
            test_client,
            "How many orders were there in August 2018?",
        )
        envelope = test_client.get(f"/api/runs/{run_id}").json()

    assert envelope["status"] == "answered"
    assert envelope["conclusion"] == "The governed result is 6,512."
    assert "999" not in envelope["conclusion"]


@requires_olist
def test_fully_hallucinated_narrative_falls_back_to_ledger(tmp_path: Path) -> None:
    service = RunService(
        lambda: build_runtime(),
        narrator=lambda outcome, ledger: "A hallucinated 999 appeared.",
    )
    with _test_client(
        create_app(run_service=service, api_tokens=_API_TOKENS)
    ) as test_client:
        run_id = _ask(
            test_client,
            "How many orders were there in August 2018?",
        )
        envelope = test_client.get(f"/api/runs/{run_id}").json()

    assert envelope["status"] == "answered"
    assert envelope["conclusion"] == "The governed result is 6,512."
    assert "999" not in envelope["conclusion"]


@requires_olist
def test_ask_comparative_lookup_returns_answered_with_verified_difference(
    client: TestClient,
) -> None:
    run_id = _ask(client, "difference in total sales in 2018 compared to 2017")

    events = _events(client, run_id)
    assert events[-1]["type"] == "answer"
    assert events[-1]["status"] == "answered"

    response = client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    envelope = response.json()
    assert envelope["run_id"] == run_id
    assert envelope["status"] == "answered"
    assert "8,594,831.98" in envelope["conclusion"]
    assert "7,092,491.65" in envelope["conclusion"]
    assert "1,502,340.33" in envelope["conclusion"]
    assert "21.18%" in envelope["conclusion"]
    assert len(envelope["queries"]) == 2
    assert envelope["run_metrics"]["queries"] == 2
