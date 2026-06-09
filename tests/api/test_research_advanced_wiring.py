"""SP-032 (ADR-00052 R1 F-004/F-005): write endpoint の owner gate wiring guard (no-DB)。

conflict_groups / domain_trust の全 write endpoint が ``require_project_owner`` を経由し、bare
``get_current_actor_id`` に巻き戻っていないことを drift guard として固定する。owner gate の
非 owner -> 403 挙動自体は DB-backed test で別途固定する。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable

import pytest

from backend.app.api.approval_inbox import get_current_actor_id
from backend.app.api.conflict_groups import (
    assign_claim_endpoint,
    create_conflict_group_endpoint,
    unassign_claim_endpoint,
    update_conflict_group_endpoint,
)
from backend.app.api.dependencies.project_active_guard import require_active_project
from backend.app.api.domain_trust import (
    create_domain_trust_endpoint,
    delete_domain_trust_endpoint,
    update_domain_trust_endpoint,
)
from backend.app.api.me import require_project_owner

_PROJECT_SCOPED_WRITES: list[Callable[..., object]] = [
    create_conflict_group_endpoint,
    update_conflict_group_endpoint,
    assign_claim_endpoint,
    unassign_claim_endpoint,
]

_TENANT_SCOPED_WRITES: list[Callable[..., object]] = [
    create_domain_trust_endpoint,
    update_domain_trust_endpoint,
    delete_domain_trust_endpoint,
]


def _dependencies(endpoint: Callable[..., object]) -> list[object]:
    signature = inspect.signature(endpoint)
    return [
        getattr(param.default, "dependency", None)
        for param in signature.parameters.values()
    ]


@pytest.mark.parametrize("endpoint", _PROJECT_SCOPED_WRITES + _TENANT_SCOPED_WRITES)
def test_write_endpoint_uses_owner_gate(endpoint: Callable[..., object]) -> None:
    deps = _dependencies(endpoint)
    assert require_project_owner in deps, f"{endpoint.__name__} must depend on require_project_owner"


@pytest.mark.parametrize("endpoint", _PROJECT_SCOPED_WRITES + _TENANT_SCOPED_WRITES)
def test_write_endpoint_not_bare_actor(endpoint: Callable[..., object]) -> None:
    deps = _dependencies(endpoint)
    assert get_current_actor_id not in deps, (
        f"{endpoint.__name__} must not weaken owner gate to bare get_current_actor_id"
    )


@pytest.mark.parametrize("endpoint", _PROJECT_SCOPED_WRITES)
def test_project_scoped_write_requires_active_project(endpoint: Callable[..., object]) -> None:
    deps = _dependencies(endpoint)
    assert require_active_project in deps, (
        f"{endpoint.__name__} (project route) must depend on require_active_project"
    )


def test_domain_trust_update_schema_is_domain_immutable() -> None:
    """R1 F-013: PATCH body は domain を受け付けない (immutable)。"""
    from backend.app.schemas.domain_trust import DomainTrustUpdate

    assert "domain" not in DomainTrustUpdate.model_fields


def test_conflict_group_create_schema_rejects_server_owned_fields() -> None:
    """create body は tenant_id / project_id / metadata / status を受け付けない (server-owned)。"""
    from pydantic import ValidationError

    from backend.app.schemas.conflict_group import ConflictGroupCreate

    for forbidden in ("tenant_id", "project_id", "research_task_id", "metadata", "status"):
        with pytest.raises(ValidationError):
            ConflictGroupCreate.model_validate({"title": "x", forbidden: "y"})
