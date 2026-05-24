from __future__ import annotations

import pytest

from backend.app.domain.policy.autonomy_level import ALL_AUTONOMY_LEVELS
from backend.app.repositories.project import ProjectRepository
from backend.app.services.policy.autonomy_profile_resolver import (
    resolve_autonomy_policy_profile,
)


class _DummySession:
    pass


def test_autonomy_profile_resolver_defaults_all_levels_until_runtime_gate() -> None:
    resolutions = [
        resolve_autonomy_policy_profile(level, runtime_enabled=False)
        for level in sorted(ALL_AUTONOMY_LEVELS)
    ]

    assert {resolution.policy_profile for resolution in resolutions} == {"default"}
    assert {resolution.auto_allow_enabled for resolution in resolutions} == {False}
    assert {resolution.autonomy_level for resolution in resolutions} == ALL_AUTONOMY_LEVELS
    assert {
        resolution.reason_code for resolution in resolutions if resolution.autonomy_level != "L0"
    } == {"autonomy_runtime_disabled"}


def test_autonomy_profile_resolver_stays_default_when_runtime_flag_is_premature() -> None:
    resolutions = [
        resolve_autonomy_policy_profile(level, runtime_enabled=True)
        for level in sorted(ALL_AUTONOMY_LEVELS)
    ]

    assert {resolution.policy_profile for resolution in resolutions} == {"default"}
    assert {
        resolution.auto_allow_enabled
        for resolution in resolutions
        if resolution.autonomy_level != "L0"
    } == {True}
    assert {
        resolution.reason_code for resolution in resolutions if resolution.autonomy_level != "L0"
    } == {"autonomy_runtime_matrix_enabled"}


def test_autonomy_profile_resolver_rejects_unknown_level() -> None:
    with pytest.raises(ValueError, match="unknown autonomy_level"):
        resolve_autonomy_policy_profile("L4")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field_name", "field_value", "message"),
    [
        ("policy_profile", "low_risk_auto_allow", "policy_profile is server-owned"),
        ("autonomy_level", "L3", "autonomy_level must use the autonomy settings service"),
    ],
)
async def test_project_repository_rejects_policy_control_payloads(
    field_name: str,
    field_value: str,
    message: str,
) -> None:
    repository = ProjectRepository(_DummySession())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=message):
        await repository.create(tenant_id=1, payload={field_name: field_value})
