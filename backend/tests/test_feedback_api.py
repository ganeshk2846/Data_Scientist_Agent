"""Answer feedback: thumbs up / down with a reason, stored per session and owner (Track 5, item 8)."""

from __future__ import annotations

import sqlite3

import pytest
from feedback import FeedbackRequest, FeedbackStore
from pydantic import ValidationError

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


def _run(client, question: str, session: str, token: str = ALICE) -> str:
    response = client.post("/api/v2/ask", json={"question": question, "session_id": session}, headers=_auth(token))
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    client.get(f"/api/v2/runs/{run_id}", headers=_auth(token))
    return run_id


def test_a_rating_is_stored_per_session_and_replaced_on_re_rating(client):
    run_id = _run(client, "revenue in SP in July 2018", "fb-1")
    first = client.post("/api/sessions/fb-1/feedback", json={"run_id": run_id, "rating": "up"}, headers=_auth(ALICE))
    assert first.status_code == 200 and first.json()["rating"] == "up" and first.json()["reason"] is None
    second = client.post("/api/sessions/fb-1/feedback", json={"run_id": run_id, "rating": "down", "reason": "  wrong\nmonth "},
                         headers=_auth(ALICE))
    assert second.status_code == 200 and second.json()["reason"] == "wrong month"
    listed = client.get("/api/sessions/fb-1/feedback", headers=_auth(ALICE)).json()["feedback"]
    assert [(item["run_id"], item["rating"]) for item in listed] == [(run_id, "down")]
    assert client.get("/api/sessions/other/feedback", headers=_auth(ALICE)).json()["feedback"] == []


def test_feedback_is_scoped_to_the_authenticated_owner(client):
    run_id = _run(client, "revenue in SP in July 2018", "fb-2")
    stolen = client.post("/api/sessions/fb-2/feedback", json={"run_id": run_id, "rating": "down"}, headers=_auth(BOB))
    assert stolen.status_code == 404
    client.post("/api/sessions/fb-2/feedback", json={"run_id": run_id, "rating": "up"}, headers=_auth(ALICE))
    assert client.get("/api/sessions/fb-2/feedback", headers=_auth(BOB)).json()["feedback"] == []
    assert client.get("/api/sessions/fb-2/feedback").status_code == 401


def test_unknown_runs_and_bad_payloads_are_rejected(client):
    assert client.post("/api/sessions/s/feedback", json={"run_id": "nope", "rating": "up"}, headers=_auth(ALICE)).status_code == 404
    assert client.post("/api/sessions/s/feedback", json={"run_id": "x", "rating": "meh"}, headers=_auth(ALICE)).status_code == 422
    assert client.post("/api/sessions/s/feedback", json={"run_id": "x", "rating": "up", "reason": "r" * 501},
                       headers=_auth(ALICE)).status_code == 422


def test_persistence_uses_its_own_file_and_refuses_the_warehouse(tmp_path):
    path = tmp_path / "feedback.sqlite"
    store = FeedbackStore(path=path)
    store.record("alice", "s1", FeedbackRequest(run_id="r1", rating="up", reason="clear"))
    reloaded = FeedbackStore(path=path)
    assert [(r.run_id, r.rating, r.reason) for r in reloaded.list("alice", "s1")] == [("r1", "up", "clear")]
    assert reloaded.list("bob", "s1") == ()
    warehouse = tmp_path / "warehouse.sqlite"
    connection = sqlite3.connect(warehouse)
    connection.execute("CREATE TABLE orders (id TEXT)")
    connection.commit()
    connection.close()
    with pytest.raises(ValueError, match="never the warehouse"):
        FeedbackStore(path=warehouse)


def test_request_model_forbids_extra_fields():
    with pytest.raises(ValidationError):
        FeedbackRequest(run_id="r", rating="up", owner_id="bob")  # type: ignore[call-arg]
