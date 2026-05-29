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

from tm.auth.capability_token import ALL_CAPABILITIES, CapabilityTokenConfigError, resolve_operation_token  # noqa: E402
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
            "TASKMANAGEDAI_BACKEND_URL": "https://taskhub.example.ts.net",
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
        (["settings", "autonomy", "--level", "L2", "--expected-level", "L0"], "task_write"),
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


def test_settings_autonomy_updates_autonomy_level_with_cas_baseline() -> None:
    code, _out, err, requests = _run_cli(
        ["settings", "autonomy", "--level", "L3", "--expected-level", "L1"]
    )

    assert code == 0
    assert err == ""
    assert requests[0].method == "PATCH"
    assert requests[0].path == f"/api/v1/me/projects/{_PROJECT_ID}/autonomy"
    assert requests[0].capability == "task_write"
    # Codex adversarial R8 (HIGH): compare-and-swap baseline (expected_autonomy_level) を
    # 必ず送る。policy_profile などの server-owned field は送らない。
    assert requests[0].json_body == {
        "autonomy_level": "L3",
        "expected_autonomy_level": "L1",
    }


def test_settings_autonomy_requires_expected_level() -> None:
    # --expected-level を省略すると CLI が exit 2 (argparse required) で拒否する
    code, _out, _err, requests = _run_cli(["settings", "autonomy", "--level", "L3"])

    assert code != 0
    assert requests == []


def test_context_show_is_read_only_current_project_surface() -> None:
    code, out, err, requests = _run_cli(["--json", "context", "show"], env={"TASKMANAGEDAI_PROJECT_ID": ""})

    assert code == 0
    assert err == ""
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].path == "/api/v1/me/current_project"
    assert requests[0].capability == "context_show"
    assert requests[0].mutating is False
    assert json.loads(out)["path"] == "/api/v1/me/current_project"


def test_doctor_is_read_only_health_surface() -> None:
    code, out, err, requests = _run_cli(["--json", "doctor"], env={"TASKMANAGEDAI_PROJECT_ID": ""})

    assert code == 0
    assert err == ""
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].path == "/healthz"
    assert requests[0].capability == "doctor"
    assert requests[0].mutating is False
    assert json.loads(out)["path"] == "/healthz"


def test_run_plan_dry_run_uses_response_only_onboarding_endpoint() -> None:
    code, _out, err, requests = _run_cli(
        [
            "run",
            "plan",
            "--dry-run",
            "--purpose",
            "Plan the first safe task",
            "--expected-artifact",
            "reviewed plan",
            "--allowed-action-class",
            "pr_open",
            "--starter-mode",
            "draft_pr_requires_approval",
            "--target-repo-ref",
            "t-ohga/TaskManagedAI",
            "--budget-cap",
            "0 USD committed",
        ]
    )

    assert code == 0
    assert err == ""
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].path == "/api/v1/onboarding/dry_run_plan"
    assert requests[0].capability == "onboarding_dry_run"
    assert requests[0].mutating is False
    assert requests[0].approval_required is False
    assert requests[0].json_body == {
        "purpose": "Plan the first safe task",
        "expected_artifact": "reviewed plan",
        "allowed_action_class": "pr_open",
        "starter_mode": "draft_pr_requires_approval",
        "target_repo_ref": "t-ohga/TaskManagedAI",
        "budget_cap": "0 USD committed",
    }


def test_ticket_intake_guided_uses_response_only_onboarding_endpoint() -> None:
    code, _out, err, requests = _run_cli(
        [
            "ticket",
            "intake",
            "--guided",
            "--purpose",
            "Plan the first safe task",
            "--expected-artifact",
            "reviewed plan",
        ]
    )

    assert code == 0
    assert err == ""
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].path == "/api/v1/onboarding/dry_run_plan"
    assert requests[0].capability == "onboarding_dry_run"
    assert requests[0].mutating is False
    assert requests[0].json_body == {
        "purpose": "Plan the first safe task",
        "expected_artifact": "reviewed plan",
        "allowed_action_class": "read_only",
        "starter_mode": "plan_only",
    }


def test_onboarding_cli_requires_explicit_dry_run_or_guided_flag(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err, requests = _run_cli(
        [
            "run",
            "plan",
            "--purpose",
            "Plan the first safe task",
            "--expected-artifact",
            "reviewed plan",
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert out == ""
    assert err == ""
    assert "--dry-run" in captured.err
    assert requests == []

    code, out, err, requests = _run_cli(
        [
            "ticket",
            "intake",
            "--purpose",
            "Plan the first safe task",
            "--expected-artifact",
            "reviewed plan",
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert out == ""
    assert err == ""
    assert "--guided" in captured.err
    assert requests == []


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
                        "backend_url": "https://taskhub.example.ts.net",
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
                    "default": {"backend_url": "https://taskhub.example.ts.net"},
                    "unused": {"access_token": "must-not-be-stored"},
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProfileConfigError, match="profiles.unused.access_token"):
        ProfileLoader(profile_path=profile_path).load("default", {})


@pytest.mark.parametrize(
    "backend_url",
    [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "https://taskhub.example.ts.net",
        "http://100.64.0.10:8000",
    ],
)
def test_profile_loader_accepts_closed_network_backend_urls(tmp_path: Path, backend_url: str) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps({"profiles": {"default": {"backend_url": backend_url}}}),
        encoding="utf-8",
    )

    profile = ProfileLoader(profile_path=profile_path).load("default", {})

    assert profile.backend_url == backend_url


@pytest.mark.parametrize(
    ("backend_url", "error"),
    [
        ("https://taskhub.example.com", "localhost, Tailscale"),
        ("http://8.8.8.8:8000", "public IP is rejected"),
        ("ftp://taskhub.example.ts.net", "http"),
    ],
)
def test_profile_loader_rejects_public_backend_urls(
    tmp_path: Path,
    backend_url: str,
    error: str,
) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps({"profiles": {"default": {"backend_url": backend_url}}}),
        encoding="utf-8",
    )

    with pytest.raises(ProfileConfigError, match=error):
        ProfileLoader(profile_path=profile_path).load("default", {})


def test_public_backend_url_env_override_fails_before_network() -> None:
    code, out, err, requests = _run_cli(
        ["ticket", "list"],
        env={"TASKMANAGEDAI_BACKEND_URL": "https://taskhub.example.com"},
    )

    assert code == 2
    assert out == ""
    assert "tm_config_error" in err
    assert requests == []


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


def test_memory_insights_is_read_only_api_surface() -> None:
    code, out, err, requests = _run_cli(
        ["--json", "memory", "insights", "--record-kind", "auto_completion", "--limit", "5"]
    )

    assert code == 0
    assert err == ""
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].path == f"/api/v1/projects/{_PROJECT_ID}/memory/insights"
    assert requests[0].capability == "memory_insights"
    assert requests[0].mutating is False
    assert "memory_insights" not in ALL_CAPABILITIES
    assert requests[0].params == {"limit": "5", "record_kind": "auto_completion"}
    assert json.loads(out)["path"] == f"/api/v1/projects/{_PROJECT_ID}/memory/insights"


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


def test_profile_env_credential_ref_resolves_runtime_operation_token(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "profiles": {
                    "default": {
                        "backend_url": "https://taskhub.example.ts.net",
                        "auth_method": "env",
                        "operation_token_env": "TM_PROFILE_OPERATION_TOKEN",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    out = io.StringIO()
    err = io.StringIO()
    requests: list[ApiRequest] = []

    def factory(config: ClientConfig) -> CapturingClient:
        return CapturingClient(config=config, requests=requests)

    code = main(
        ["--json", "auth", "refresh"],
        stdout=out,
        stderr=err,
        env={
            "TASKMANAGEDAI_PROJECT_ID": _PROJECT_ID,
            "TASKMANAGEDAI_PROFILE_PATH": str(profile_path),
            "TM_PROFILE_OPERATION_TOKEN": "profile-env-token",
        },
        cwd=_REPO_ROOT,
        client_factory=factory,
    )

    assert code == 0
    assert err.getvalue() == ""
    assert requests[0].json_body == {"operation_token": "profile-env-token", "ttl_minutes": 5}
    assert json.loads(out.getvalue())["operation_token"] == "[REDACTED]"


def test_profile_plain_auth_method_is_rejected_before_network(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps({"profiles": {"default": {"auth_method": "plain"}}}),
        encoding="utf-8",
    )
    out = io.StringIO()
    err = io.StringIO()
    requests: list[ApiRequest] = []

    def factory(config: ClientConfig) -> CapturingClient:
        return CapturingClient(config=config, requests=requests)

    code = main(
        ["auth", "refresh"],
        stdout=out,
        stderr=err,
        env={"TASKMANAGEDAI_PROFILE_PATH": str(profile_path)},
        cwd=_REPO_ROOT,
        client_factory=factory,
    )

    assert code == 2
    assert out.getvalue() == ""
    assert "tm_operation_token_config_error" in err.getvalue()
    assert requests == []


def test_keyring_credential_source_resolves_with_injected_getter() -> None:
    value = resolve_operation_token(
        {},
        auth_method="keyring",
        credential_ref="taskmanagedai/default",
        keyring_getter=lambda service, account: f"{service}:{account}:token",
    )

    assert value == "taskmanagedai:default:token"


def test_sops_credential_source_resolves_nested_key_with_injected_decryptor(tmp_path: Path) -> None:
    value = resolve_operation_token(
        {},
        auth_method="sops",
        credential_ref=f"{tmp_path / 'profile.enc.json'}#cli.operation_token",
        sops_decryptor=lambda path: {"cli": {"operation_token": f"token-from-{path.name}"}},
    )

    assert value == "token-from-profile.enc.json"


def test_sops_credential_source_rejects_missing_key(tmp_path: Path) -> None:
    with pytest.raises(CapabilityTokenConfigError, match="key path not found"):
        resolve_operation_token(
            {},
            auth_method="sops",
            credential_ref=f"{tmp_path / 'profile.enc.json'}#cli.operation_token",
            sops_decryptor=lambda _path: {"cli": {}},
        )
