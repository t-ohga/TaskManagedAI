from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest

from fastapi.routing import APIRoute

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_ROOT = _REPO_ROOT / "cli"
if str(_CLI_ROOT) not in sys.path:
    sys.path.insert(0, str(_CLI_ROOT))

from tm.auth.capability_token import ALL_CAPABILITIES  # noqa: E402
from tm.client import ClientConfig  # noqa: E402
from tm.config.profile_loader import ProfileLoader  # noqa: E402
from tm.main import main  # noqa: E402
from tm.types import ApiRequest, JSONValue  # noqa: E402

from backend.app.config import Settings  # noqa: E402
from backend.app.main import create_app  # noqa: E402

PROJECT_ID = "11111111-1111-4111-8111-111111111111"
TICKET_ID = "22222222-2222-4222-8222-222222222222"
APPROVAL_ID = "33333333-3333-4333-8333-333333333333"
RUN_ID = "44444444-4444-4444-8444-444444444444"

BackendStatus = Literal["live", "planned"]
UiStatus = Literal["live", "policy_surface"]


class TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


@dataclass(frozen=True)
class CapturingClient:
    config: ClientConfig
    requests: list[ApiRequest]

    def request(self, request: ApiRequest) -> JSONValue:
        self.requests.append(request)
        return {"ok": True}


@dataclass(frozen=True)
class ParityCase:
    capability: str
    argv: tuple[str, ...]
    method: str
    path: str
    backend_route: str
    backend_status: BackendStatus
    ui_status: UiStatus
    ui_reference: str
    db_row: str
    audit_event: str


PARITY_CASES: tuple[ParityCase, ...] = (
    ParityCase(
        capability="task_list",
        argv=("ticket", "list"),
        method="GET",
        path=f"/api/v1/projects/{PROJECT_ID}/tickets",
        backend_route="/api/v1/projects/{project_id}/tickets",
        backend_status="live",
        ui_status="live",
        ui_reference="frontend/lib/api/tickets.ts",
        db_row="tickets:list",
        audit_event="none_read_only",
    ),
    ParityCase(
        capability="task_show",
        argv=("ticket", "show", TICKET_ID),
        method="GET",
        path=f"/api/v1/projects/{PROJECT_ID}/tickets/{TICKET_ID}",
        backend_route="/api/v1/projects/{project_id}/tickets/{ticket_id}",
        backend_status="live",
        ui_status="live",
        ui_reference="frontend/lib/api/tickets.ts",
        db_row="tickets:get",
        audit_event="none_read_only",
    ),
    ParityCase(
        capability="task_create",
        argv=("ticket", "create", "--slug", "parity-ticket", "--title", "Parity ticket"),
        method="POST",
        path=f"/api/v1/projects/{PROJECT_ID}/tickets",
        backend_route="/api/v1/projects/{project_id}/tickets",
        backend_status="live",
        ui_status="live",
        ui_reference="frontend/app/(admin)/tickets/actions.ts",
        db_row="tickets:create",
        audit_event="ticket_created",
    ),
    ParityCase(
        capability="task_write",
        argv=("ticket", "update", TICKET_ID, "--title", "Updated"),
        method="PATCH",
        path=f"/api/v1/projects/{PROJECT_ID}/tickets/{TICKET_ID}",
        backend_route="/api/v1/projects/{project_id}/tickets/{ticket_id}",
        backend_status="live",
        ui_status="live",
        ui_reference="frontend/app/(admin)/tickets/[id]/actions.ts",
        db_row="tickets:update",
        audit_event="ticket_updated|ticket_status_changed",
    ),
    ParityCase(
        capability="approval_list",
        argv=("approval", "list"),
        method="GET",
        path="/api/v1/approvals",
        backend_route="/api/v1/approvals",
        backend_status="live",
        ui_status="live",
        ui_reference="frontend/lib/api/approvals.ts",
        db_row="approval_requests:list",
        audit_event="none_read_only",
    ),
    ParityCase(
        capability="approval_decide",
        argv=("approval", "approve", APPROVAL_ID, "--rationale", "ok"),
        method="POST",
        path=f"/api/v1/approvals/{APPROVAL_ID}/decide",
        backend_route="/api/v1/approvals/{approval_id}/decide",
        backend_status="live",
        ui_status="live",
        ui_reference="frontend/lib/api/approvals.ts",
        db_row="approval_requests:decide",
        audit_event="approval_decided",
    ),
    ParityCase(
        capability="repo_status",
        argv=("repo", "status"),
        method="GET",
        path=f"/api/v1/projects/{PROJECT_ID}/repo/status",
        backend_route="/api/v1/projects/{project_id}/repo/status",
        backend_status="planned",
        ui_status="policy_surface",
        ui_reference="frontend/app/(admin)/_components/sprint9-admin-ui.tsx",
        db_row="repositories:status_snapshot",
        audit_event="none_read_only",
    ),
    ParityCase(
        capability="repo_push",
        argv=("repo", "push", "--branch", "main"),
        method="POST",
        path=f"/api/v1/projects/{PROJECT_ID}/repo/push",
        backend_route="/api/v1/projects/{project_id}/repo/push",
        backend_status="planned",
        ui_status="policy_surface",
        ui_reference="frontend/app/(admin)/_components/sprint9-admin-ui.tsx",
        db_row="repo_operations:push_request",
        audit_event="repo_push_requested",
    ),
    ParityCase(
        capability="pr_open",
        argv=("pr", "open", "--base", "main", "--head", "feature", "--title", "PR"),
        method="POST",
        path=f"/api/v1/projects/{PROJECT_ID}/pull-requests",
        backend_route="/api/v1/projects/{project_id}/pull-requests",
        backend_status="planned",
        ui_status="policy_surface",
        ui_reference="frontend/app/(admin)/_components/sprint9-admin-ui.tsx",
        db_row="pull_requests:draft_request",
        audit_event="repo_pr_opened",
    ),
    ParityCase(
        capability="run_show",
        argv=("run", "show", RUN_ID),
        method="GET",
        path=f"/api/v1/agent_runs/{RUN_ID}",
        backend_route="/api/v1/agent_runs/{run_id}",
        backend_status="live",
        ui_status="live",
        ui_reference="frontend/lib/api/agent-runs.ts",
        db_row="agent_runs:get",
        audit_event="none_read_only",
    ),
    ParityCase(
        capability="run_cancel",
        argv=("run", "cancel", RUN_ID, "--reason", "operator requested"),
        method="POST",
        path=f"/api/v1/agent_runs/{RUN_ID}/cancel",
        backend_route="/api/v1/agent_runs/{run_id}/cancel",
        backend_status="live",
        ui_status="policy_surface",
        ui_reference="frontend/app/(admin)/runs/[id]/page.tsx",
        db_row="agent_runs:cancel",
        audit_event="agent_run_cancel_requested",
    ),
    ParityCase(
        capability="secret_resolve",
        argv=("secret", "use", "secret/ref", "--purpose", "parity"),
        method="POST",
        path=f"/api/v1/projects/{PROJECT_ID}/secrets/resolve",
        backend_route="/api/v1/projects/{project_id}/secrets/resolve",
        backend_status="planned",
        ui_status="policy_surface",
        ui_reference="frontend/app/(admin)/_components/sprint9-admin-ui.tsx",
        db_row="secret_refs:brokered_resolve",
        audit_event="secret_capability_redeemed",
    ),
    ParityCase(
        capability="provider_call",
        argv=("provider", "call", "--provider", "openai", "--feature", "chat", "--payload-json", "{}"),
        method="POST",
        path=f"/api/v1/projects/{PROJECT_ID}/providers/call",
        backend_route="/api/v1/projects/{project_id}/providers/call",
        backend_status="planned",
        ui_status="policy_surface",
        ui_reference="frontend/app/(admin)/_components/sprint9-admin-ui.tsx",
        db_row="provider_usage:record",
        audit_event="provider_call_requested",
    ),
)


def _run_cli(argv: tuple[str, ...]) -> ApiRequest:
    requests: list[ApiRequest] = []

    def factory(config: ClientConfig) -> CapturingClient:
        return CapturingClient(config=config, requests=requests)

    code = main(
        list(argv),
        stdout=TtyStringIO(),
        stderr=io.StringIO(),
        env={
            "TASKMANAGEDAI_PROJECT_ID": PROJECT_ID,
            "TASKMANAGEDAI_BACKEND_URL": "https://taskhub.example.ts.net",
            "TASKMANAGEDAI_OPERATION_TOKEN": "runtime-token-only",
        },
        cwd=_REPO_ROOT,
        profile_loader=ProfileLoader(profile_path=Path("/does/not/exist")),
        client_factory=factory,
    )
    assert code == 0
    assert len(requests) == 1
    return requests[0]


def _backend_routes() -> set[tuple[str, str]]:
    app = create_app(
        Settings(
            environment="test",
            allowed_hosts=["testserver", "127.0.0.1", "localhost"],
            dev_login_cookie_secret="test-cookie-secret-for-parity-contract",
        )
    )
    routes: set[tuple[str, str]] = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods or set():
                routes.add((method, route.path))
    return routes


def test_parity_matrix_covers_exact_13_capabilities() -> None:
    capabilities = [case.capability for case in PARITY_CASES]

    assert len(PARITY_CASES) == 13
    assert len(set(capabilities)) == 13
    assert set(capabilities) == set(ALL_CAPABILITIES)


def test_cli_generated_requests_match_parity_contract() -> None:
    for case in PARITY_CASES:
        request = _run_cli(case.argv)

        assert request.capability == case.capability
        assert request.method == case.method
        assert request.path == case.path


def test_live_backend_routes_match_parity_contract() -> None:
    routes = _backend_routes()

    for case in PARITY_CASES:
        route_key = (case.method, case.backend_route)
        if case.backend_status == "live":
            assert route_key in routes
        else:
            assert route_key not in routes


def test_ui_references_and_docs_cover_all_parity_capabilities() -> None:
    docs = (_REPO_ROOT / "docs/cli/README.md").read_text(encoding="utf-8")

    for case in PARITY_CASES:
        ui_source = (_REPO_ROOT / case.ui_reference).read_text(encoding="utf-8")
        assert case.capability in docs
        if case.ui_status == "live":
            assert case.backend_route.split("{", maxsplit=1)[0] in ui_source
        else:
            assert case.capability.split("_", maxsplit=1)[0] in ui_source


def test_parity_contract_records_db_and_audit_expectations_for_each_capability() -> None:
    for case in PARITY_CASES:
        assert ":" in case.db_row
        assert case.audit_event
        assert "raw" not in case.audit_event
