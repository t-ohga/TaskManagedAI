from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.app.api import me as me_api
from backend.app.api.me import (
    ProjectAutonomySettingsUpdate,
    ProjectProfileUpdate,
    update_project_autonomy_endpoint,
    update_project_profile_endpoint,
)
from backend.app.services.policy.autonomy_settings import (
    AutonomyExpectationMismatch,
    AutonomyUpdateResult,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-0000000aa004")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-0000000aa002")
ACTOR_ID = UUID("00000000-0000-4000-8000-0000000aa001")


def _fake_project(autonomy_level: str = "L0", *, name: str = "Project Second",
                  description: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        tenant_id=1,
        id=PROJECT_ID,
        workspace_id=WORKSPACE_ID,
        slug="project-second",
        name=name,
        description=description,
        status="active",
        policy_profile="default",
        autonomy_level=autonomy_level,
    )


class _CommitTrackingSession:
    """add / commit を tracking する最小 fake session。

    M-3 (ADR-00035) で autonomy endpoint は service (CAS writer) に委譲し、結果に応じて
    config_changed audit を session.add してから commit する。本 fake はその経路を再現する。
    """

    def __init__(self) -> None:
        self.committed = False
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True


def _make_fake_autonomy_service(
    *,
    result: AutonomyUpdateResult | None = None,
    raises: bool = False,
) -> type:
    """endpoint↔service contract 用の設定可能 fake service を返す。

    CAS の実ロジック (row lock / 比較) は service の DB-backed test
    (tests/api/test_me_api.py) で検証する。本 fake は endpoint が service の結果を
    HTTP に写像する分岐 (changed -> audit / no-op -> no audit / mismatch -> 409 /
    None -> 404) を検証するためのもの。
    """

    class _FakeService:
        def __init__(self, session: object) -> None:
            self.session = session

        async def update_autonomy_level(
            self,
            *,
            tenant_id: int,
            project_id: UUID,
            autonomy_level: str,
            expected_autonomy_level: str,
        ) -> AutonomyUpdateResult | None:
            if raises:
                raise AutonomyExpectationMismatch(
                    expected=expected_autonomy_level,
                    actual="L0",
                )
            return result

    return _FakeService


def test_project_autonomy_settings_payload_rejects_policy_profile() -> None:
    with pytest.raises(ValidationError, match="policy_profile|extra_forbidden"):
        ProjectAutonomySettingsUpdate.model_validate(
            {
                "autonomy_level": "L2",
                "expected_autonomy_level": "L0",
                "policy_profile": "low_risk_auto_allow",
            }
        )


def test_project_autonomy_settings_payload_requires_expected_autonomy_level() -> None:
    """Codex adversarial R8 (HIGH): expected_autonomy_level は必須。省略すると CAS を
    すり抜けて re-escalation できてしまうため、validation error にする。
    """
    with pytest.raises(ValidationError, match="expected_autonomy_level"):
        ProjectAutonomySettingsUpdate.model_validate({"autonomy_level": "L3"})


def test_project_profile_update_rejects_policy_profile_and_autonomy() -> None:
    """name/description endpoint は policy_profile / autonomy_level を smuggle 不可."""
    with pytest.raises(ValidationError, match="extra_forbidden|policy_profile"):
        ProjectProfileUpdate.model_validate(
            {"name": "X", "policy_profile": "low_risk_auto_allow"}
        )
    with pytest.raises(ValidationError, match="extra_forbidden|autonomy_level"):
        ProjectProfileUpdate.model_validate({"name": "X", "autonomy_level": "L3"})


def test_project_profile_update_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        ProjectProfileUpdate.model_validate({"name": ""})


def test_project_profile_update_rejects_explicit_null_name() -> None:
    """Codex adversarial R1: name=null は NOT NULL カラムに流せないため reject (422)."""
    with pytest.raises(ValidationError, match="null"):
        ProjectProfileUpdate.model_validate({"name": None})


def test_project_profile_update_rejects_blank_only_name() -> None:
    """空白のみ name は reject (frontend trim をすり抜ける直接 API 呼び出し対策)."""
    with pytest.raises(ValidationError, match="空白"):
        ProjectProfileUpdate.model_validate({"name": "   "})


def test_project_profile_update_strips_name_whitespace() -> None:
    """受理時は前後空白を strip して保持する."""
    parsed = ProjectProfileUpdate.model_validate({"name": "  My Project  "})
    assert parsed.name == "My Project"


def test_project_profile_update_allows_description_only_without_name() -> None:
    """name を省略すれば description-only 更新が成立 (name は変更なし)."""
    parsed = ProjectProfileUpdate.model_validate({"description": "新説明"})
    assert "name" not in parsed.model_fields_set
    assert parsed.description == "新説明"


def test_project_profile_update_allows_explicit_null_description() -> None:
    """description=null は explicit clear として許容 (name と異なり nullable)."""
    parsed = ProjectProfileUpdate.model_validate({"description": None})
    assert "description" in parsed.model_fields_set
    assert parsed.description is None


# --- endpoint↔service 写像テスト (CAS 実ロジックは service の DB-backed test で検証) ---
# 本 endpoint は CAS を service に委譲し、service の結果を HTTP に写像する:
#   AutonomyUpdateResult(changed=True)  -> audit + commit
#   AutonomyUpdateResult(changed=False) -> commit のみ (no-op audit なし)
#   AutonomyExpectationMismatch         -> 409 (commit / audit なし)
#   None                                -> 404 (commit / audit なし)


@pytest.mark.asyncio
async def test_update_project_autonomy_endpoint_audits_when_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """service が changed=True を返すと endpoint は config_changed audit を記録し commit する."""
    project = _fake_project(autonomy_level="L3")
    monkeypatch.setattr(
        me_api,
        "ProjectAutonomySettingsService",
        _make_fake_autonomy_service(
            result=AutonomyUpdateResult(
                project=project,  # type: ignore[arg-type]
                previous_autonomy_level="L0",
                changed=True,
            )
        ),
    )
    session = _CommitTrackingSession()

    response = await update_project_autonomy_endpoint(
        project_id=PROJECT_ID,
        payload=ProjectAutonomySettingsUpdate(autonomy_level="L3", expected_autonomy_level="L0"),
        _cli_capability=None,
        actor_id=ACTOR_ID,
        tenant_id=1,
        session=session,  # type: ignore[arg-type]
    )

    assert session.committed is True
    assert response.project_id == PROJECT_ID
    assert response.autonomy_level == "L3"
    assert response.policy_profile == "default"

    # config_changed audit が service の previous / new を含めて記録される
    assert len(session.added) == 1
    audit = session.added[0]
    assert audit.event_type == "config_changed"  # type: ignore[attr-defined]
    payload = audit.event_payload  # type: ignore[attr-defined]
    assert payload["changed_fields"] == ["autonomy_level"]
    assert payload["previous_autonomy_level"] == "L0"
    assert payload["new_autonomy_level"] == "L3"
    assert payload["resolved_policy_profile"] == "default"


@pytest.mark.asyncio
async def test_update_project_autonomy_endpoint_no_op_skips_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex adversarial R2 (HIGH): service が changed=False (no-op) を返すと audit を残さない.

    AI 権限制御 audit は実遷移と 1:1 対応する。
    """
    project = _fake_project(autonomy_level="L2")
    monkeypatch.setattr(
        me_api,
        "ProjectAutonomySettingsService",
        _make_fake_autonomy_service(
            result=AutonomyUpdateResult(
                project=project,  # type: ignore[arg-type]
                previous_autonomy_level="L2",
                changed=False,
            )
        ),
    )
    session = _CommitTrackingSession()

    response = await update_project_autonomy_endpoint(
        project_id=PROJECT_ID,
        payload=ProjectAutonomySettingsUpdate(autonomy_level="L2", expected_autonomy_level="L2"),
        _cli_capability=None,
        actor_id=ACTOR_ID,
        tenant_id=1,
        session=session,  # type: ignore[arg-type]
    )

    assert session.committed is True
    assert session.added == []
    assert response.autonomy_level == "L2"


@pytest.mark.asyncio
async def test_update_project_autonomy_endpoint_cas_mismatch_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex adversarial R7/R9 (HIGH): service が AutonomyExpectationMismatch を raise すると
    endpoint は 409 を返し、commit も audit もしない。
    """
    monkeypatch.setattr(
        me_api,
        "ProjectAutonomySettingsService",
        _make_fake_autonomy_service(raises=True),
    )
    session = _CommitTrackingSession()

    with pytest.raises(HTTPException) as exc_info:
        await update_project_autonomy_endpoint(
            project_id=PROJECT_ID,
            payload=ProjectAutonomySettingsUpdate(
                autonomy_level="L3", expected_autonomy_level="L0"
            ),
            _cli_capability=None,
            actor_id=ACTOR_ID,
            tenant_id=1,
            session=session,  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 409
    assert session.committed is False
    assert session.added == []


@pytest.mark.asyncio
async def test_update_project_autonomy_endpoint_404_missing_project_no_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """service が None (project 不在) を返すと endpoint は 404 を返し、commit も audit もしない."""
    monkeypatch.setattr(
        me_api,
        "ProjectAutonomySettingsService",
        _make_fake_autonomy_service(result=None),
    )
    session = _CommitTrackingSession()

    with pytest.raises(HTTPException) as exc_info:
        await update_project_autonomy_endpoint(
            project_id=UUID("00000000-0000-4000-8000-0000000aa099"),
            payload=ProjectAutonomySettingsUpdate(autonomy_level="L1", expected_autonomy_level="L0"),
            _cli_capability=None,
            actor_id=ACTOR_ID,
            tenant_id=1,
            session=session,  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 404
    assert session.committed is False
    assert session.added == []


# NOTE: update_project_profile_endpoint の更新 / audit / no-op delta 挙動は実 delta 比較で
# row lock + repo.update RETURNING を伴うため、fake session ではなく DB-backed test
# (tests/api/test_me_api.py の test_update_project_profile_endpoint_* / Codex R3) で検証する。


@pytest.mark.asyncio
async def test_update_project_profile_endpoint_empty_payload_400() -> None:
    session = _CommitTrackingSession()
    with pytest.raises(HTTPException) as exc_info:
        await update_project_profile_endpoint(
            project_id=PROJECT_ID,
            payload=ProjectProfileUpdate(),
            _cli_capability=None,
            actor_id=ACTOR_ID,
            tenant_id=1,
            session=session,  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 400
    assert session.committed is False
