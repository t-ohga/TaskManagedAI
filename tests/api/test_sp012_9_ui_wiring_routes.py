from __future__ import annotations

from backend.app.api.agent_runs import _payload_keys as agent_run_payload_keys
from backend.app.api.audit import _payload_keys as audit_payload_keys
from backend.app.config import Settings
from backend.app.main import create_app


def _settings() -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        dev_login_cookie_secret="test-cookie-secret-for-sp012-9-ui-wiring",
    )


def test_sp012_9_read_only_routes_are_registered() -> None:
    app = create_app(_settings())
    routes = {
        (getattr(route, "path", None), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in app.routes
    }

    assert ("/api/v1/agent_runs", ("GET",)) in routes
    assert ("/api/v1/agent_runs/{run_id}", ("GET",)) in routes
    assert ("/api/v1/audit_events", ("GET",)) in routes
    assert ("/api/v1/me/projects", ("GET",)) in routes
    assert ("/api/v1/me/projects/{project_id}/autonomy", ("PATCH",)) in routes


def test_agent_run_event_payload_response_exposes_keys_only() -> None:
    keys, status = agent_run_payload_keys({"reason_code": "allow", "safe_hash": "abc"})

    assert keys == ["reason_code", "safe_hash"]
    assert status == "keys_only"


def test_agent_run_event_payload_suppresses_secret_shaped_payload() -> None:
    keys, status = agent_run_payload_keys({"api_key": "sk-fakeButLooksSecret0123456789"})

    assert keys == []
    assert status == "blocked_by_secret_scan"


def test_audit_payload_response_exposes_keys_only() -> None:
    keys, status = audit_payload_keys({"reason_code": "allow", "ticket_id": "T-1"})

    assert keys == ["reason_code", "ticket_id"]
    assert status == "keys_only"


def test_audit_payload_suppresses_secret_shaped_payload() -> None:
    keys, status = audit_payload_keys({"provider_key": "redacted"})

    assert keys == []
    assert status == "blocked_by_secret_scan"
