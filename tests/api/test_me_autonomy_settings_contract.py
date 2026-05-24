from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.app.api import me as me_api
from backend.app.api.me import (
    ProjectAutonomySettingsUpdate,
    update_project_autonomy_endpoint,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-0000000aa004")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-0000000aa002")
ACTOR_ID = UUID("00000000-0000-4000-8000-0000000aa001")


class _CommitTrackingSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


class _AutonomySettingsService:
    def __init__(self, session: _CommitTrackingSession) -> None:
        self.session = session

    async def update_autonomy_level(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        autonomy_level: str,
    ) -> SimpleNamespace | None:
        if project_id != PROJECT_ID:
            return None
        return SimpleNamespace(
            tenant_id=tenant_id,
            id=project_id,
            workspace_id=WORKSPACE_ID,
            slug="project-second",
            name="Project Second",
            status="active",
            policy_profile="default",
            autonomy_level=autonomy_level,
        )


def test_project_autonomy_settings_payload_rejects_policy_profile() -> None:
    with pytest.raises(ValidationError, match="policy_profile|extra_forbidden"):
        ProjectAutonomySettingsUpdate.model_validate(
            {
                "autonomy_level": "L2",
                "policy_profile": "low_risk_auto_allow",
            }
        )


@pytest.mark.asyncio
async def test_update_project_autonomy_endpoint_commits_successful_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(me_api, "ProjectAutonomySettingsService", _AutonomySettingsService)
    session = _CommitTrackingSession()

    response = await update_project_autonomy_endpoint(
        project_id=PROJECT_ID,
        payload=ProjectAutonomySettingsUpdate(autonomy_level="L3"),
        _cli_capability=None,
        actor_id=ACTOR_ID,
        tenant_id=1,
        session=session,  # type: ignore[arg-type]
    )

    assert session.committed is True
    assert response.project_id == PROJECT_ID
    assert response.autonomy_level == "L3"
    assert response.policy_profile == "default"


@pytest.mark.asyncio
async def test_update_project_autonomy_endpoint_does_not_commit_missing_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(me_api, "ProjectAutonomySettingsService", _AutonomySettingsService)
    session = _CommitTrackingSession()

    with pytest.raises(HTTPException) as exc_info:
        await update_project_autonomy_endpoint(
            project_id=UUID("00000000-0000-4000-8000-0000000aa099"),
            payload=ProjectAutonomySettingsUpdate(autonomy_level="L1"),
            _cli_capability=None,
            actor_id=ACTOR_ID,
            tenant_id=1,
            session=session,  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 404
    assert session.committed is False
