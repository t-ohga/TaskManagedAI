"""Extend artifacts prohibited payload key DB CHECK from 18 -> 21 keys.

Revision ID: 0015_artifact_prohibited_keys_21
Revises: 0014_prohibited_event_keys_21
Create Date: 2026-05-13 00:00:00.000000

Sprint 6 batch 2 (Codex SP6B2 R2 follow-up): agent_run_events と整合させる。
agent_run_events は migration 0014 で 21 keys 化済。artifacts は migration
0009 の 18 keys のままだった drift を解消する。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015_artifact_prohibited_keys_21"
down_revision: str | None = "0014_prohibited_event_keys_21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _build_check_sql(keys: tuple[str, ...]) -> str:
    disjunction = " || ".join(f'@.key == "{key}"' for key in keys)
    return (
        "not jsonb_path_exists(content_jsonb, "
        "'strict $.** ? (@.type() == \"object\")."
        f"keyvalue() ? ({disjunction})'::jsonpath)"
    )


_KEYS_21 = (
    "api_key",
    "api_token",
    "raw_secret",
    "secret",
    "secret_value",
    "private_key",
    "auth_token",
    "bearer_token",
    "capability_token",
    "capability_token_value",
    "provider_key",
    "github_installation_token",
    "github_app_private_key",
    "tailscale_auth_key",
    "sops_age_key",
    "age_private_key",
    "canary_value",
    "raw_canary",
    "secret_capability_token",
    "raw_token",
    "session_token",
)
_KEYS_18 = _KEYS_21[:18]


def upgrade() -> None:
    op.drop_constraint(
        "artifacts_ck_no_prohibited_payload_keys",
        "artifacts",
        type_="check",
    )
    op.create_check_constraint(
        "artifacts_ck_no_prohibited_payload_keys",
        "artifacts",
        _build_check_sql(_KEYS_21),
    )


def downgrade() -> None:
    op.drop_constraint(
        "artifacts_ck_no_prohibited_payload_keys",
        "artifacts",
        type_="check",
    )
    op.create_check_constraint(
        "artifacts_ck_no_prohibited_payload_keys",
        "artifacts",
        _build_check_sql(_KEYS_18),
    )
