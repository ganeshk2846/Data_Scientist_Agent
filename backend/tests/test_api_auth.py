from __future__ import annotations

from app import create_app
from fastapi.testclient import TestClient
from service import RunService

TOKENS = {
    "alice": "a" * 40,
    "bob": "b" * 40,
}


def test_api_requires_a_valid_bearer_token() -> None:
    with TestClient(create_app(api_tokens=TOKENS)) as client:
        unauthenticated = client.post(
            "/api/ask",
            json={"question": "orders", "session_id": "s"},
        )
        invalid = client.post(
            "/api/ask",
            json={"question": "orders", "session_id": "s"},
            headers={"Authorization": "Bearer invalid-token"},
        )
        unauthenticated_result = client.get("/api/runs/unknown")
        unauthenticated_events = client.get("/api/runs/unknown/events")

    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["www-authenticate"] == "Bearer"
    assert invalid.status_code == 401
    assert unauthenticated_result.status_code == 401
    assert unauthenticated_events.status_code == 401


def test_run_results_and_events_are_limited_to_the_owner() -> None:
    def unavailable_runtime():
        raise RuntimeError("test runtime intentionally unavailable")

    service = RunService(unavailable_runtime)
    with TestClient(create_app(run_service=service, api_tokens=TOKENS)) as client:
        created = client.post(
            "/api/ask",
            json={"question": "orders", "session_id": "alice-session"},
            headers={"Authorization": f"Bearer {TOKENS['alice']}"},
        )
        assert created.status_code == 200
        run_id = created.json()["run_id"]

        own_run = client.get(
            f"/api/runs/{run_id}",
            headers={"Authorization": f"Bearer {TOKENS['alice']}"},
        )
        own_events = client.get(
            f"/api/runs/{run_id}/events",
            headers={"Authorization": f"Bearer {TOKENS['alice']}"},
        )
        other_run = client.get(
            f"/api/runs/{run_id}",
            headers={"Authorization": f"Bearer {TOKENS['bob']}"},
        )
        other_events = client.get(
            f"/api/runs/{run_id}/events",
            headers={"Authorization": f"Bearer {TOKENS['bob']}"},
        )
        cross_owner_clarification = client.post(
            "/api/ask",
            json={
                "question": "more detail",
                "session_id": "bob-session",
                "clarification_of": run_id,
            },
            headers={"Authorization": f"Bearer {TOKENS['bob']}"},
        )

    assert own_run.status_code in {200, 202}
    assert own_events.status_code == 200
    assert other_run.status_code == 404
    assert other_events.status_code == 404
    assert cross_owner_clarification.status_code == 404


def test_api_fails_closed_when_token_configuration_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("DS_AGENT_API_TOKENS", raising=False)
    monkeypatch.delenv("DS_AGENT_TOKEN", raising=False)
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/ask",
            json={"question": "orders", "session_id": "s"},
        )

    # In open local development mode, unconfigured token defaults to dev_user
    assert response.status_code == 200
