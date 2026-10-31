"""The session API: follow-ups over HTTP, GET history, POST reset, owner isolation (Track 4)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.filterwarnings("ignore::ResourceWarning")

ALICE, BOB = "a" * 40, "b" * 40


@pytest.fixture(scope="module")
def client(v2_build):
    from app import create_app
    from fastapi.testclient import TestClient
    from service import RunService, build_runtime

    service = RunService(lambda: build_runtime(v2_build["db"], reasoning_client=False))
    app = create_app(run_service=service, api_tokens={"alice": ALICE, "bob": BOB})
    with TestClient(app) as test_client:
        yield test_client


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _ask(client, question: str, session: str, token: str = ALICE, **extra) -> tuple[str, dict]:
    response = client.post("/api/v2/ask", json={"question": question, "session_id": session, **extra}, headers=_auth(token))
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    return run_id, client.get(f"/api/v2/runs/{run_id}", headers=_auth(token)).json()


def test_a_follow_up_over_http_returns_the_interpreted_question_and_is_in_history(client):
    _, first = _ask(client, "revenue in SP in July 2018", "chat-1")
    assert first["status"] == "answered"
    run_id, second = _ask(client, "What about RJ?", "chat-1")
    resolved = second["resolved_question"]
    assert second["status"] == "answered"
    assert resolved["effective_text"] == "What was revenue in RJ in July 2018?"
    assert resolved["resolution_source"] == "context" and "metric_id" in resolved["inherited_fields"]
    assert second["route"]["labels"] == ["lookup"]
    stream = client.get(f"/api/runs/{run_id}/events", headers=_auth(ALICE)).text
    assert "event: context" in stream and "What was revenue in RJ in July 2018?" in stream
    for v1_event in ("event: step_started", "event: step_finished", "event: answer"):
        assert v1_event in stream

    history = client.get("/api/sessions/chat-1/history", headers=_auth(ALICE))
    assert history.status_code == 200
    state = history.json()
    assert state["contract_version"] == "2.0.0" and state["session_id"] == "chat-1"
    assert [turn["question"] for turn in state["turns"]] == ["revenue in SP in July 2018", "What about RJ?"]
    assert [turn["turn_id"] for turn in state["turns"]] == ["T1", "T2"]
    assert state["turns"][1]["resolved"]["effective_text"] == "What was revenue in RJ in July 2018?"
    assert all(claim.startswith("C") for turn in state["turns"] for claim in turn["claim_ids"])
    assert "conclusion" not in history.text  # CTX-2: no answer text is kept


def test_history_and_reset_are_scoped_to_the_authenticated_owner(client):
    _ask(client, "revenue in SP in July 2018", "shared-id", ALICE)
    assert client.get("/api/sessions/shared-id/history", headers=_auth(BOB)).json()["turns"] == []
    # Bob's follow-up on the same session id does not see Alice's context.
    _, bob = _ask(client, "What about RJ?", "shared-id", BOB)
    assert bob["status"] == "clarify"
    assert client.post("/api/sessions/shared-id/reset", headers=_auth(BOB)).json()["cleared_turns"] == 1  # Bob's own turn
    assert len(client.get("/api/sessions/shared-id/history", headers=_auth(ALICE)).json()["turns"]) == 1


def test_post_reset_clears_the_session_and_the_next_follow_up_is_cold(client):
    _ask(client, "revenue in SP in July 2018", "chat-reset")
    reset = client.post("/api/sessions/chat-reset/reset", headers=_auth(ALICE))
    assert reset.status_code == 200 and reset.json() == {"session_id": "chat-reset", "cleared_turns": 1}
    assert client.get("/api/sessions/chat-reset/history", headers=_auth(ALICE)).json()["turns"] == []
    _, after = _ask(client, "What about RJ?", "chat-reset")
    assert after["status"] == "clarify"


def test_reset_context_on_ask_and_the_new_topic_phrase(client):
    _ask(client, "revenue in SP in July 2018", "chat-flag")
    _, flagged = _ask(client, "What about RJ?", "chat-flag", reset_context=True)
    assert flagged["status"] == "clarify"
    _ask(client, "revenue in SP in July 2018", "chat-phrase")
    _, ack = _ask(client, "new topic", "chat-phrase")
    assert ack["status"] == "clarify" and ack["clarification"]["question"].startswith("Context cleared")
    assert client.get("/api/sessions/chat-phrase/history", headers=_auth(ALICE)).json()["turns"] == []


def test_session_endpoints_require_the_bearer_token(client):
    assert client.get("/api/sessions/chat-1/history").status_code == 401
    assert client.post("/api/sessions/chat-1/reset").status_code == 401
    assert client.get("/api/sessions/chat-1/history", headers=_auth("z" * 40)).status_code == 401


def test_the_v1_ask_route_is_unchanged(client):
    response = client.post("/api/ask", json={"question": "What data do you have?", "session_id": "v1"}, headers=_auth(ALICE))
    assert response.status_code == 200 and set(response.json()) == {"contract_version", "run_id"}
    envelope = client.get(f"/api/runs/{response.json()['run_id']}", headers=_auth(ALICE)).json()
    assert envelope["contract_version"] == "1.0.0"
    assert "resolved_question" not in envelope
