"""Extend agent_run_events prohibited payload key DB CHECK from 18 -> 21 keys.

Revision ID: 0014_prohibited_event_keys_21
Revises: 0013_cli_event_type_28
Create Date: 2026-05-13 00:00:00.000000

Sprint 6 batch 2 (Codex SP6B2 R1 F-007 MEDIUM adopt): repository scanner
(``backend.app.repositories._payload_secret_scan._PROHIBITED_PAYLOAD_KEYS``)
は 21 keys を持つが、agent_run_events の DB CHECK 制約は migration 0008 以来
18 keys しか defense していなかった。

本 migration で **defense-in-depth の 21 key 完全整合** を実現する:
- 追加 keys: ``secret_capability_token`` / ``raw_token`` / ``session_token``
- 既存 18 keys は不変 (additive only、ADR Gate Criteria #8 非該当)

Note: jsonpath::jsonpath は `strict` mode で全 nested object を walk するため、
ネストされた cli_process_completed event payload の中に新 keys が混入しても
DB レベルで reject される。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014_prohibited_event_keys_21"
down_revision: str | None = "0013_cli_event_type_28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _build_check_sql(keys: tuple[str, ...]) -> str:
    disjunction = " || ".join(f'@.key == "{key}"' for key in keys)
    return (
        "not jsonb_path_exists(event_payload, "
        "'strict $.** ? (@.type() == \"object\")."
        f"keyvalue() ? ({disjunction})'::jsonpath)"
    )


# 21 keys (Sprint 6 batch 2 で 18 -> 21)
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

# 18 keys (downgrade target)
_KEYS_18 = _KEYS_21[:18]


def upgrade() -> None:
    op.drop_constraint(
        "agent_run_events_ck_no_prohibited_payload_keys",
        "agent_run_events",
        type_="check",
    )
    op.create_check_constraint(
        "agent_run_events_ck_no_prohibited_payload_keys",
        "agent_run_events",
        _build_check_sql(_KEYS_21),
    )


def downgrade() -> None:
    op.drop_constraint(
        "agent_run_events_ck_no_prohibited_payload_keys",
        "agent_run_events",
        type_="check",
    )
    op.create_check_constraint(
        "agent_run_events_ck_no_prohibited_payload_keys",
        "agent_run_events",
        _build_check_sql(_KEYS_18),
    )
