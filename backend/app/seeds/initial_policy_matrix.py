"""Shared canonical source for the initial policy_rules seed (migration 0005).

migration 0005 inserts 7 policy rules at upgrade time. After CI tests with
``truncate ... cascade`` on ``tenants`` (which transitively wipes the FK-dependent
``policy_rules``), seed-dependent tests must restore the same 7 rows.

To avoid drift between migration SQL and test fixtures, this module is the single
**source of truth** for the initial policy matrix. Test fixtures call
``seed_initial_policy_matrix`` to restore the state; migration 0005 keeps its
historical SQL VALUES (immutable, append-only invariant) and the contents are kept
identical to ``INITIAL_POLICY_MATRIX`` defined here.

Drift verification: ``tests/eval/test_policy_block_recall_policy_source.py`` reads
``INITIAL_POLICY_MATRIX`` directly; if migration 0005 ever drifts from these values,
the runtime row-count tests in ``tests/policy/test_initial_policy_matrix.py`` will fail.
"""

from __future__ import annotations

from typing import Final, TypedDict

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.domain.policy.action_class import ActionClass, PolicyEffect

INITIAL_POLICY_TENANT_ID: Final[int] = 1
INITIAL_POLICY_VERSION: Final[str] = "2026-05-08-initial"
DEFAULT_POLICY_TENANT_NAME: Final[str] = "default-tenant"


class InitialPolicyRuleSeed(TypedDict):
    action_class: ActionClass
    effect: PolicyEffect
    reason_code: str
    scope: str
    note: str | None


INITIAL_POLICY_MATRIX: Final[tuple[InitialPolicyRuleSeed, ...]] = (
    {
        "action_class": "merge",
        "effect": "deny",
        "reason_code": "p0_merge_deploy_disabled",
        "scope": "all",
        "note": None,
    },
    {
        "action_class": "deploy",
        "effect": "deny",
        "reason_code": "p0_merge_deploy_disabled",
        "scope": "all",
        "note": None,
    },
    {
        "action_class": "secret_access",
        "effect": "deny",
        "reason_code": "policy_matrix_default_deny",
        "scope": "default",
        "note": "Sprint 4 SecretBroker で fail-closed override",
    },
    {
        "action_class": "provider_call",
        "effect": "deny",
        "reason_code": "policy_matrix_default_deny",
        "scope": "default",
        "note": "Sprint 5 Provider Compliance で fail-closed override",
    },
    {
        "action_class": "task_write",
        "effect": "require_approval",
        "reason_code": "task_write_requires_approval",
        "scope": "default",
        "note": None,
    },
    {
        "action_class": "repo_write",
        "effect": "require_approval",
        "reason_code": "repo_write_requires_approval",
        "scope": "default",
        "note": None,
    },
    {
        "action_class": "pr_open",
        "effect": "require_approval",
        "reason_code": "pr_open_requires_approval",
        "scope": "default",
        "note": None,
    },
)


_ENSURE_POLICY_TENANT = sa.text(
    """
    insert into tenants (id, name, metadata)
    values (
      :tenant_id,
      :tenant_name,
      '{"rls_ready": true, "seed_version": "sprint2"}'::jsonb
    )
    on conflict (id) do nothing
    """
)
_DELETE_INITIAL_POLICY_MATRIX = sa.text(
    """
    delete from policy_rules
    where tenant_id = :tenant_id
      and policy_version = :policy_version
      and project_id is null
    """
)
_INSERT_INITIAL_POLICY_RULE = sa.text(
    """
    insert into policy_rules (
      tenant_id,
      action_class,
      effect,
      rule_json,
      policy_version,
      metadata
    )
    values (
      :tenant_id,
      :action_class,
      :effect,
      :rule_json,
      :policy_version,
      :metadata
    )
    """
).bindparams(
    sa.bindparam("rule_json", type_=JSONB),
    sa.bindparam("metadata", type_=JSONB),
)


def _rule_json(seed: InitialPolicyRuleSeed) -> dict[str, str]:
    rule: dict[str, str] = {
        "reason_code": seed["reason_code"],
        "scope": seed["scope"],
    }
    note = seed["note"]
    if note is not None:
        rule["note"] = note
    return rule


def initial_policy_matrix_insert_rows(
    *,
    tenant_id: int = INITIAL_POLICY_TENANT_ID,
    policy_version: str = INITIAL_POLICY_VERSION,
) -> list[dict[str, object]]:
    """Build a list of dicts ready for executemany-style INSERT into policy_rules."""
    return [
        {
            "tenant_id": tenant_id,
            "action_class": seed["action_class"],
            "effect": seed["effect"],
            "rule_json": _rule_json(seed),
            "policy_version": policy_version,
            "metadata": {"rls_ready": True},
        }
        for seed in INITIAL_POLICY_MATRIX
    ]


async def seed_initial_policy_matrix(
    session: AsyncSession,
    *,
    tenant_id: int = INITIAL_POLICY_TENANT_ID,
    policy_version: str = INITIAL_POLICY_VERSION,
) -> None:
    """Idempotently restore the initial 7-row policy matrix for a tenant.

    Used by test fixtures after ``truncate ... cascade`` on ``tenants`` removes
    migration 0005's seeded rows. Performs ``ensure tenant -> delete -> insert``
    in a single transaction.
    """
    await session.execute(
        _ENSURE_POLICY_TENANT,
        {
            "tenant_id": tenant_id,
            "tenant_name": DEFAULT_POLICY_TENANT_NAME,
        },
    )
    await session.execute(
        _DELETE_INITIAL_POLICY_MATRIX,
        {
            "tenant_id": tenant_id,
            "policy_version": policy_version,
        },
    )
    await session.execute(
        _INSERT_INITIAL_POLICY_RULE,
        initial_policy_matrix_insert_rows(
            tenant_id=tenant_id,
            policy_version=policy_version,
        ),
    )
    await session.flush()


__all__ = [
    "DEFAULT_POLICY_TENANT_NAME",
    "INITIAL_POLICY_MATRIX",
    "INITIAL_POLICY_TENANT_ID",
    "INITIAL_POLICY_VERSION",
    "InitialPolicyRuleSeed",
    "initial_policy_matrix_insert_rows",
    "seed_initial_policy_matrix",
]
