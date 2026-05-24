from __future__ import annotations

import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_ROOT = _REPO_ROOT / "cli"
if str(_CLI_ROOT) not in sys.path:
    sys.path.insert(0, str(_CLI_ROOT))

from tm.client import ClientConfig  # noqa: E402
from tm.config.profile_loader import ProfileLoader  # noqa: E402
from tm.main import main  # noqa: E402
from tm.output import format_human, format_json, format_yaml  # noqa: E402
from tm.types import ApiRequest, JSONValue  # noqa: E402

PROJECT_ID = "11111111-1111-4111-8111-111111111111"
RAW_OPENAI_KEY = "sk-" + ("A" * 40)
RAW_BEARER = "Bearer " + ("b" * 40)
RAW_GITHUB_TOKEN = "ghp_" + ("C" * 36)


class TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


@dataclass
class SecretLeakingClient:
    config: ClientConfig
    requests: list[ApiRequest]

    def request(self, request: ApiRequest) -> JSONValue:
        self.requests.append(request)
        return {
            "secret_ref": "secret/ref",
            "token_id": "not-secret-token-id",
            "message": f"provider returned {RAW_OPENAI_KEY}",
            "nested": {
                "credential": "credential-by-key",
                "diagnostic": RAW_BEARER,
            },
        }


def _secret_payload() -> dict[str, JSONValue]:
    return {
        "token_id": "safe-token-id",
        "message": f"provider returned {RAW_OPENAI_KEY}",
        "nested": {
            "secret_value": "raw-by-key",
            "note": f"do not print {RAW_GITHUB_TOKEN}",
            "items": [RAW_BEARER, "safe text"],
        },
    }


def test_output_formatters_redact_secret_keys_and_secret_shaped_values() -> None:
    payload = _secret_payload()

    for rendered in (
        format_json(payload),
        format_yaml(payload),
        format_human(payload),
    ):
        assert RAW_OPENAI_KEY not in rendered
        assert RAW_GITHUB_TOKEN not in rendered
        assert RAW_BEARER not in rendered
        assert "raw-by-key" not in rendered
        assert "[REDACTED]" in rendered
        assert "safe-token-id" in rendered


def test_secret_command_output_redacts_backend_secret_values_before_printing() -> None:
    out = TtyStringIO()
    err = io.StringIO()
    requests: list[ApiRequest] = []

    def factory(config: ClientConfig) -> SecretLeakingClient:
        return SecretLeakingClient(config=config, requests=requests)

    code = main(
        ["--json", "secret", "use", "secret/ref", "--purpose", "parity-redaction"],
        stdout=out,
        stderr=err,
        env={
            "TASKMANAGEDAI_PROJECT_ID": PROJECT_ID,
            "TASKMANAGEDAI_BACKEND_URL": "https://taskhub.example.ts.net",
            "TASKMANAGEDAI_OPERATION_TOKEN": "runtime-operation-token",
        },
        cwd=_REPO_ROOT,
        profile_loader=ProfileLoader(profile_path=Path("/does/not/exist")),
        client_factory=factory,
    )

    rendered = out.getvalue()
    parsed = json.loads(rendered)

    assert code == 0
    assert err.getvalue() == ""
    assert requests[0].path == f"/api/v1/projects/{PROJECT_ID}/secrets/resolve"
    assert RAW_OPENAI_KEY not in rendered
    assert RAW_BEARER not in rendered
    assert parsed["token_id"] == "not-secret-token-id"
    assert parsed["message"] == "[REDACTED]"
    assert parsed["nested"]["diagnostic"] == "[REDACTED]"
    assert parsed["nested"]["credential"] == "[REDACTED]"
