from __future__ import annotations

from pathlib import Path
from typing import cast, get_args

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Table, UniqueConstraint

from backend.app.db.models.inter_agent_message import (
    InterAgentMessage,
    InterAgentReceiverKind,
)

EXPECTED_COLUMNS = (
    "id",
    "project_id",
    "parent_run_id",
    "child_run_id",
    "sender_actor_id",
    "sender_run_id",
    "receiver_kind",
    "receiver_ref",
    "payload_data_class",
    "trust_level",
    "approval_request_id",
    "source_artifact_id",
    "artifact_hash",
    "policy_version",
    "provider_request_fingerprint",
    "action_class",
    "payload_hash",
    "artifact_ref",
    "seq_no",
    "previous_hash",
    "schema_version",
    "idempotency_key",
    "expires_at",
    "created_at",
    "consumed_at",
    "consumed_by_run_id",
    "tenant_id",
)
EXPECTED_RECEIVER_KINDS = ("agent_run", "role", "broadcast")
EXPECTED_CHECKS = {
    "inter_agent_messages_ck_receiver_kind",
    "inter_agent_messages_ck_payload_data_class",
    "inter_agent_messages_ck_trust_level",
    "inter_agent_messages_ck_payload_hash_sha256_hex",
    "inter_agent_messages_ck_previous_hash_sha256_hex",
    "inter_agent_messages_ck_artifact_hash_sha256_hex",
    "inter_agent_messages_ck_artifact_ref_non_empty",
    "inter_agent_messages_ck_schema_version_non_empty",
    "inter_agent_messages_ck_idempotency_key_non_empty",
    "inter_agent_messages_ck_expires_after_created",
    "inter_agent_messages_ck_consumed_state_consistency",
    "inter_agent_messages_ck_receiver_target_consistency",
    "inter_agent_messages_ck_sender_not_consumer",
    "inter_agent_messages_ck_action_class_subset",
    "inter_agent_messages_ck_trusted_instruction_refs",
}
EXPECTED_UNIQUES = {
    ("tenant_id", "id"),
    ("tenant_id", "project_id", "parent_run_id", "seq_no"),
    ("tenant_id", "project_id", "parent_run_id", "idempotency_key"),
}
EXPECTED_FKS = {
    (("tenant_id",), "tenants", ("id",)),
    (("tenant_id", "project_id"), "projects", ("tenant_id", "id")),
    (
        ("tenant_id", "project_id", "parent_run_id"),
        "agent_runs",
        ("tenant_id", "project_id", "id"),
    ),
    (
        ("tenant_id", "project_id", "child_run_id"),
        "agent_runs",
        ("tenant_id", "project_id", "id"),
    ),
    (
        ("tenant_id", "project_id", "sender_run_id"),
        "agent_runs",
        ("tenant_id", "project_id", "id"),
    ),
    (
        ("tenant_id", "project_id", "consumed_by_run_id"),
        "agent_runs",
        ("tenant_id", "project_id", "id"),
    ),
    (("tenant_id", "sender_actor_id"), "actors", ("tenant_id", "id")),
    (("tenant_id", "approval_request_id"), "approval_requests", ("tenant_id", "id")),
    (
        ("tenant_id", "project_id", "source_artifact_id"),
        "artifacts",
        ("tenant_id", "project_id", "id"),
    ),
}
MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "0030_sp015_inter_agent_messages.py"
)


def _table() -> Table:
    return cast(Table, InterAgentMessage.__table__)


def _constraint_names(kind: type[CheckConstraint]) -> set[str]:
    return {
        str(constraint.name)
        for constraint in _table().constraints
        if isinstance(constraint, kind)
        and constraint.name is not None
    }


def test_inter_agent_message_columns_are_exact() -> None:
    assert tuple(_table().columns.keys()) == EXPECTED_COLUMNS
    assert "data_class" not in _table().columns


def test_receiver_kind_enum_is_exact() -> None:
    assert get_args(InterAgentReceiverKind) == EXPECTED_RECEIVER_KINDS


def test_schema_check_constraints_are_present() -> None:
    assert EXPECTED_CHECKS <= _constraint_names(CheckConstraint)


def test_receiver_target_and_action_class_checks_are_fail_closed() -> None:
    checks = {
        str(constraint.name): str(constraint.sqltext)
        for constraint in _table().constraints
        if isinstance(constraint, CheckConstraint)
    }

    receiver_target = checks["inter_agent_messages_ck_receiver_target_consistency"]
    assert "receiver_kind = 'agent_run'" in receiver_target
    assert "child_run_id is not null" in receiver_target
    assert "receiver_ref is null" in receiver_target
    assert "receiver_kind = 'role'" in receiver_target
    assert "child_run_id is null" in receiver_target
    assert "nullif(receiver_ref, '') is not null" in receiver_target
    assert "receiver_kind = 'broadcast'" in receiver_target

    action_class = checks["inter_agent_messages_ck_action_class_subset"]
    assert "merge" not in action_class
    assert "deploy" not in action_class
    assert "provider_call" in action_class


def test_project_scoped_unique_constraints_are_present() -> None:
    actual = {
        tuple(column.name for column in constraint.columns)
        for constraint in _table().constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert EXPECTED_UNIQUES <= actual
    assert ("tenant_id", "parent_run_id", "seq_no") not in actual
    assert ("tenant_id", "parent_run_id", "idempotency_key") not in actual


def test_foreign_keys_are_tenant_and_project_scoped() -> None:
    actual = {
        (
            tuple(element.parent.name for element in constraint.elements),
            constraint.elements[0].target_fullname.split(".", 1)[0],
            tuple(element.target_fullname.split(".", 1)[1] for element in constraint.elements),
        )
        for constraint in _table().constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }

    assert EXPECTED_FKS <= actual


def test_migration_receiver_eligibility_preserves_project_boundary() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "inter_agent_messages_uq_tenant_project_parent_seq" in source
    assert "inter_agent_messages_uq_tenant_project_parent_idempotency" in source
    assert "receiver_kind = 'role'" in source
    assert "receiver_kind = 'broadcast'" in source
    assert "inter_agent_messages_ck_action_class_subset" in source
    assert '["tenant_id", "project_id", "source_artifact_id"]' in source
    assert "payload_data_class" in source
    assert "data_class text" not in source
