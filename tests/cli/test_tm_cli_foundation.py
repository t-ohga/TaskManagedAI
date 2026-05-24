from __future__ import annotations

import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_ROOT = _REPO_ROOT / "cli"
if str(_CLI_ROOT) not in sys.path:
    sys.path.insert(0, str(_CLI_ROOT))

from tm.auth.capability_token import ALL_CAPABILITIES  # noqa: E402
from tm.client import OPERATION_TOKEN_HEADER, ClientConfig  # noqa: E402
from tm.config.profile_loader import ProfileConfigError, ProfileLoader  # noqa: E402
from tm.main import main  # noqa: E402
from tm.output.json_formatter import format_json  # noqa: E402
from tm.types import ApiRequest, JSONValue  # noqa: E402

_PROJECT_ID = "11111111-1111-4111-8111-111111111111"
_RUN_ID = "22222222-2222-4222-8222-222222222222"


class TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


@dataclass
class CapturingClient:
    config: ClientConfig
    requests: list[ApiRequest]

    def request(self, request: ApiRequest) -> JSONValue:
        self.requests.append(request)
        return {
            "ok": True,
            "path": request.path,
            "method": request.method,
            "header_name": OPERATION_TOKEN_HEADER,
            "authorization_header_used": False,
            "operation_token": self.config.operation_token or "",
        }


def _run_cli(
    argv: list[str],
    *,
    env: dict[str, str] | None = None,
    tty: bool = False,
) -> tuple[int, str, str, list[ApiRequest]]:
    out = TtyStringIO() if tty else io.StringIO()
    err = io.StringIO()
    requests: list[ApiRequest] = []

    def factory(config: ClientConfig) -> CapturingClient:
        return CapturingClient(config=config, requests=requests)

    code = main(
        argv,
        stdout=out,
        stderr=err,
        env={
            "TASKMANAGEDAI_PROJECT_ID": _PROJECT_ID,
            "TASKMANAGEDAI_BACKEND_URL": "https://taskhub.test",
            "TASKMANAGEDAI_OPERATION_TOKEN": "raw-operation-token-for-runtime-only",
            **(env or {}),
        },
        cwd=_REPO_ROOT,
        profile_loader=ProfileLoader(profile_path=Path("/does/not/exist")),
        client_factory=factory,
    )
    return code, out.getvalue(), err.getvalue(), requests


def test_ticket_list_uses_project_route_and_non_bearer_operation_header() -> None:
    code, out, err, requests = _run_cli(["--json", "ticket", "list"])

    assert code == 0
    assert err == ""
    assert len(requests) == 1
    assert requests[0].path == f"/api/v1/projects/{_PROJECT_ID}/tickets"
    assert requests[0].method == "GET"
    payload = json.loads(out)
    assert payload["header_name"] == OPERATION_TOKEN_HEADER
    assert payload["authorization_header_used"] is False
    assert payload["operation_token"] == "[REDACTED]"


@pytest.mark.parametrize(
    ("argv", "capability"),
    [
        (["ticket", "list"], "task_list"),
        (["ticket", "show", "t1"], "task_show"),
        (["ticket", "create", "--slug", "new-task", "--title", "New task"], "task_create"),
        (["ticket", "update", "t1", "--title", "Updated"], "task_write"),
        (["approval", "list"], "approval_list"),
        (["approval", "approve", "a1", "--rationale", "ok"], "approval_decide"),
        (["repo", "status"], "repo_status"),
        (["repo", "push", "--branch", "main"], "repo_push"),
        (["pr", "open", "--base", "main", "--head", "feature", "--title", "PR"], "pr_open"),
        (["run", "show", _RUN_ID], "run_show"),
        (["run", "cancel", _RUN_ID], "run_cancel"),
        (["secret", "use", "secret/ref", "--purpose", "test"], "secret_resolve"),
        (["provider", "call", "--provider", "openai", "--feature", "chat", "--payload-json", "{}"], "provider_call"),
    ],
)
def test_command_surface_matches_13_capability_matrix(argv: list[str], capability: str) -> None:
    code, _out, _err, requests = _run_cli(argv, tty=True)

    assert code == 0
    assert requests[0].capability == capability


def test_all_13_capabilities_are_exercised_by_command_surface() -> None:
    command_capabilities = {
        "task_list",
        "task_show",
        "task_create",
        "task_write",
        "approval_list",
        "approval_decide",
        "repo_status",
        "repo_push",
        "pr_open",
        "run_show",
        "run_cancel",
        "secret_resolve",
        "provider_call",
    }

    assert command_capabilities == set(ALL_CAPABILITIES)


def test_mutating_command_without_project_fails_closed_before_network() -> None:
    code, out, err, requests = _run_cli(
        ["ticket", "create", "--slug", "new-task", "--title", "New task"],
        env={"TASKMANAGEDAI_PROJECT_ID": ""},
    )

    assert code == 2
    assert out == ""
    assert "tm_project_unresolved" in err
    assert requests == []


def test_agent_mode_blocks_mutating_command_before_network() -> None:
    code, out, err, requests = _run_cli(
        ["--agent-mode", "repo", "push", "--branch", "main"],
    )

    assert code == 2
    assert out == ""
    assert "tm_agent_mode_mutation_denied" in err
    assert requests == []


def test_non_interactive_approval_required_command_fails_closed() -> None:
    code, out, err, requests = _run_cli(["--no-interactive", "secret", "use", "secret/ref", "--purpose", "test"])

    assert code == 2
    assert out == ""
    assert "tm_non_interactive_approval_denied" in err
    assert requests == []


def test_profile_loader_rejects_raw_operation_token(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "profiles": {
                    "default": {
                        "backend_url": "https://taskhub.test",
                        "operation_token": "must-not-be-stored",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProfileConfigError, match="raw operation token"):
        ProfileLoader(profile_path=profile_path).load("default", {})


def test_profile_loader_rejects_raw_operation_token_in_inactive_profile(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "profiles": {
                    "default": {"backend_url": "https://taskhub.test"},
                    "unused": {"access_token": "must-not-be-stored"},
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProfileConfigError, match="profiles.unused.access_token"):
        ProfileLoader(profile_path=profile_path).load("default", {})


def test_json_formatter_redacts_secret_shaped_output() -> None:
    formatted = format_json(
        {
            "token_id": "not-secret-id",
            "operation_token": "raw-token",
            "nested": {"secret_value": "raw-secret"},
        }
    )
    payload = json.loads(formatted)

    assert payload == {
        "nested": {"secret_value": "[REDACTED]"},
        "operation_token": "[REDACTED]",
        "token_id": "not-secret-id",
    }


def test_memory_commands_are_disabled_without_network() -> None:
    code, out, err, requests = _run_cli(["--json", "memory", "search", "anything"])

    assert code == 3
    assert err == ""
    assert requests == []
    assert json.loads(out)["error_code"] == "tm_memory_disabled"


def test_auth_refresh_injects_runtime_operation_token_only_at_request_boundary() -> None:
    code, out, err, requests = _run_cli(["--json", "auth", "refresh"])

    assert code == 0
    assert err == ""
    assert len(requests) == 1
    assert requests[0].path == "/api/v1/auth/cli-token/refresh"
    assert requests[0].json_body == {
        "operation_token": "raw-operation-token-for-runtime-only",
        "ttl_minutes": 5,
    }
    assert json.loads(out)["operation_token"] == "[REDACTED]"


def test_auth_refresh_without_runtime_operation_token_fails_before_network() -> None:
    code, out, err, requests = _run_cli(["auth", "refresh"], env={"TASKMANAGEDAI_OPERATION_TOKEN": ""})

    assert code == 2
    assert out == ""
    assert "tm_operation_token_missing" in err
    assert requests == []
