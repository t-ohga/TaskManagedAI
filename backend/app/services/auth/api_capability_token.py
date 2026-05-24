from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.api_capability_token import ApiCapabilityToken
from backend.app.db.models.principal import Principal
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.schemas.api_capability_token import (
    ApiCapabilityAction,
    ApiCapabilityAuthMethod,
)
from backend.app.services.orchestrator._shared import ensure_tenant_context

API_CAPABILITY_ACTIONS: frozenset[ApiCapabilityAction] = frozenset(
    {
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
)
TENANT_WIDE_READ_ONLY_ACTIONS: frozenset[ApiCapabilityAction] = frozenset(
    {
        "task_list",
        "task_show",
        "approval_list",
        "repo_status",
        "run_show",
    }
)
AUDIENCE: Literal["taskmanagedai-api"] = "taskmanagedai-api"
_SHA256_HEX_RE = re.compile(r"^[a-f0-9]{64}$")


class ApiCapabilityTokenDenied(ValueError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class ApiCapabilityTokenIssueResult:
    token: ApiCapabilityToken
    raw_operation_token: str


@dataclass(frozen=True)
class ApiCapabilityTokenRevokeResult:
    token_id: UUID
    revoked_at: datetime


@dataclass(frozen=True)
class ApiCapabilityTokenAuthorizeResult:
    token: ApiCapabilityToken


class ApiCapabilityTokenService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def issue(
        self,
        *,
        tenant_id: int,
        actor_id: UUID,
        project_id: UUID | None,
        device_id: str | None,
        allowed_actions: list[ApiCapabilityAction],
        scope_constraint: dict[str, Any],
        auth_method: ApiCapabilityAuthMethod,
        auth_context_hash: str,
        request_binding_hash: str,
        ttl_minutes: int,
        now: datetime | None = None,
    ) -> ApiCapabilityTokenIssueResult:
        issued_at = _utc_now(now)
        expires_at = issued_at + timedelta(minutes=ttl_minutes)
        await ensure_tenant_context(self.session, tenant_id)
        try:
            self._validate_issue_request(
                project_id=project_id,
                device_id=device_id,
                allowed_actions=allowed_actions,
                scope_constraint=scope_constraint,
                auth_method=auth_method,
                auth_context_hash=auth_context_hash,
                request_binding_hash=request_binding_hash,
                ttl_minutes=ttl_minutes,
            )
        except ApiCapabilityTokenDenied as exc:
            await self._append_denied(
                tenant_id=tenant_id,
                actor_id=actor_id,
                reason_code=exc.reason_code,
                project_id=project_id,
                allowed_actions=allowed_actions,
            )
            raise

        raw_operation_token = secrets.token_urlsafe(48)
        principal = Principal(
            tenant_id=tenant_id,
            actor_id=actor_id,
            principal_type="capability_token",
            auth_context_hash=auth_context_hash,
            expires_at=expires_at,
            metadata_={
                "rls_ready": True,
                "credential_kind": "cli_operation",
                "auth_method": auth_method,
            },
        )
        self.session.add(principal)
        await self.session.flush()

        token = ApiCapabilityToken(
            tenant_id=tenant_id,
            project_id=project_id,
            token_hash=_sha256_text(raw_operation_token),
            actor_id=actor_id,
            principal_id=principal.id,
            device_id=device_id,
            allowed_actions=list(allowed_actions),
            scope_constraint=scope_constraint,
            audience=AUDIENCE,
            auth_context_hash=auth_context_hash,
            request_binding_hash=request_binding_hash,
            status="issued",
            issued_at=issued_at,
            expires_at=expires_at,
            jti=uuid4().hex,
            metadata_={
                "rls_ready": True,
                "credential_kind": "cli_operation",
            },
        )
        self.session.add(token)
        await self.session.flush()
        await self._append_issued(
            tenant_id=tenant_id,
            actor_id=actor_id,
            token=token,
        )
        return ApiCapabilityTokenIssueResult(
            token=token,
            raw_operation_token=raw_operation_token,
        )

    async def refresh(
        self,
        *,
        tenant_id: int,
        actor_id: UUID,
        raw_operation_token: str,
        ttl_minutes: int,
        now: datetime | None = None,
    ) -> ApiCapabilityTokenIssueResult:
        if ttl_minutes < 5 or ttl_minutes > 30:
            await self._append_denied(
                tenant_id=tenant_id,
                actor_id=actor_id,
                reason_code="ttl_out_of_bounds",
                project_id=None,
                allowed_actions=[],
            )
            raise ApiCapabilityTokenDenied("ttl_out_of_bounds")
        current = await self._get_issued_token(
            tenant_id=tenant_id,
            actor_id=actor_id,
            raw_operation_token=raw_operation_token,
            now=now,
        )
        revoked_at = _utc_now(now)
        current.status = "revoked"
        current.revoked_at = revoked_at
        await self.session.flush()
        await self._append_revoked(
            tenant_id=tenant_id,
            actor_id=actor_id,
            token=current,
            revoked_at=revoked_at,
            reason_code="refreshed",
        )
        return await self.issue(
            tenant_id=tenant_id,
            actor_id=actor_id,
            project_id=current.project_id,
            device_id=current.device_id,
            allowed_actions=_stored_actions(current),
            scope_constraint=dict(current.scope_constraint),
            auth_method="keyring",
            auth_context_hash=current.auth_context_hash,
            request_binding_hash=current.request_binding_hash,
            ttl_minutes=ttl_minutes,
            now=now,
        )

    async def revoke(
        self,
        *,
        tenant_id: int,
        actor_id: UUID,
        raw_operation_token: str,
        now: datetime | None = None,
    ) -> ApiCapabilityTokenRevokeResult:
        current = await self._get_token_by_raw_value(
            tenant_id=tenant_id,
            raw_operation_token=raw_operation_token,
        )
        revoked_at = _utc_now(now)
        if current is None or current.actor_id != actor_id:
            await self._append_denied(
                tenant_id=tenant_id,
                actor_id=actor_id,
                reason_code="invalid_operation_token",
                project_id=None,
                allowed_actions=[],
            )
            raise ApiCapabilityTokenDenied("invalid_operation_token")
        if current.status != "revoked":
            current.status = "revoked"
            current.revoked_at = revoked_at
            await self.session.flush()
            await self._append_revoked(
                tenant_id=tenant_id,
                actor_id=actor_id,
                token=current,
                revoked_at=revoked_at,
                reason_code="explicit_revoke",
            )
        if current.revoked_at is None:
            raise ApiCapabilityTokenDenied("revoked_at_missing")
        return ApiCapabilityTokenRevokeResult(
            token_id=current.id,
            revoked_at=current.revoked_at,
        )

    async def authorize_request(
        self,
        *,
        tenant_id: int,
        actor_id: UUID,
        raw_operation_token: str,
        required_action: ApiCapabilityAction,
        project_id: UUID | None,
        now: datetime | None = None,
    ) -> ApiCapabilityTokenAuthorizeResult:
        token = await self._get_issued_token(
            tenant_id=tenant_id,
            actor_id=actor_id,
            raw_operation_token=raw_operation_token,
            now=now,
            mark_used=False,
        )
        mismatch_reason = _classify_authorization_mismatch(
            token=token,
            required_action=required_action,
            project_id=project_id,
        )
        if mismatch_reason is not None:
            await self._append_scope_mismatch(
                tenant_id=tenant_id,
                actor_id=actor_id,
                token=token,
                reason_code=mismatch_reason,
                required_action=required_action,
                requested_project_id=project_id,
            )
            raise ApiCapabilityTokenDenied(mismatch_reason)

        token.last_used_at = _utc_now(now)
        await self.session.flush()
        return ApiCapabilityTokenAuthorizeResult(token=token)

    async def _get_issued_token(
        self,
        *,
        tenant_id: int,
        actor_id: UUID,
        raw_operation_token: str,
        now: datetime | None,
        mark_used: bool = True,
    ) -> ApiCapabilityToken:
        checked_at = _utc_now(now)
        token = await self._get_token_by_raw_value(
            tenant_id=tenant_id,
            raw_operation_token=raw_operation_token,
        )
        if token is None or token.actor_id != actor_id:
            reason_code = "invalid_operation_token"
        elif token.status != "issued" or token.revoked_at is not None:
            reason_code = "revoked"
        elif token.expires_at <= checked_at:
            reason_code = "expired"
        else:
            if mark_used:
                token.last_used_at = checked_at
                await self.session.flush()
            return token
        await self._append_denied(
            tenant_id=tenant_id,
            actor_id=actor_id,
            reason_code=reason_code,
            project_id=token.project_id if token is not None else None,
            allowed_actions=_stored_actions(token) if token is not None else [],
        )
        raise ApiCapabilityTokenDenied(reason_code)

    async def _get_token_by_raw_value(
        self,
        *,
        tenant_id: int,
        raw_operation_token: str,
    ) -> ApiCapabilityToken | None:
        return cast(
            ApiCapabilityToken | None,
            await self.session.scalar(
                sa.select(ApiCapabilityToken).where(
                    ApiCapabilityToken.tenant_id == tenant_id,
                    ApiCapabilityToken.token_hash == _sha256_text(raw_operation_token),
                )
            ),
        )

    @staticmethod
    def _validate_issue_request(
        *,
        project_id: UUID | None,
        device_id: str | None,
        allowed_actions: list[ApiCapabilityAction],
        scope_constraint: dict[str, Any],
        auth_method: ApiCapabilityAuthMethod,
        auth_context_hash: str,
        request_binding_hash: str,
        ttl_minutes: int,
    ) -> None:
        if auth_method == "plain":
            raise ApiCapabilityTokenDenied("plain_auth_method_rejected")
        if ttl_minutes < 5 or ttl_minutes > 30:
            raise ApiCapabilityTokenDenied("ttl_out_of_bounds")
        if _SHA256_HEX_RE.fullmatch(auth_context_hash) is None:
            raise ApiCapabilityTokenDenied("auth_context_hash_invalid")
        if _SHA256_HEX_RE.fullmatch(request_binding_hash) is None:
            raise ApiCapabilityTokenDenied("request_binding_hash_invalid")
        if not allowed_actions:
            raise ApiCapabilityTokenDenied("allowed_actions_empty")
        if any(action not in API_CAPABILITY_ACTIONS for action in allowed_actions):
            raise ApiCapabilityTokenDenied("allowed_action_unknown")
        if len(set(allowed_actions)) != len(allowed_actions):
            raise ApiCapabilityTokenDenied("allowed_actions_duplicate")
        if project_id is None and not set(allowed_actions).issubset(
            TENANT_WIDE_READ_ONLY_ACTIONS
        ):
            raise ApiCapabilityTokenDenied("tenant_wide_scope_requires_read_only")
        scope_project_id = scope_constraint.get("project_id")
        if scope_project_id is not None and (
            project_id is None or str(scope_project_id) != str(project_id)
        ):
            raise ApiCapabilityTokenDenied("scope_constraint_project_mismatch")
        try:
            assert_no_raw_secret(scope_constraint, path="$api_capability.scope_constraint")
        except ValueError as exc:
            raise ApiCapabilityTokenDenied("scope_constraint_raw_secret_rejected") from exc
        if device_id is not None:
            try:
                assert_no_raw_secret(
                    {"device_id_value": device_id},
                    path="$api_capability.device_id",
                )
            except ValueError as exc:
                raise ApiCapabilityTokenDenied("device_id_raw_secret_rejected") from exc

    async def _append_issued(
        self,
        *,
        tenant_id: int,
        actor_id: UUID,
        token: ApiCapabilityToken,
    ) -> None:
        await AuditEventRepository(self.session).append(
            tenant_id=tenant_id,
            event_type="api_capability_token_issued",
            payload=_token_audit_payload(token, reason_code="issued"),
            actor_id=actor_id,
            principal_id=token.principal_id,
            correlation_id=f"api-capability:{_sha256_text(str(token.id))}",
        )

    async def _append_revoked(
        self,
        *,
        tenant_id: int,
        actor_id: UUID,
        token: ApiCapabilityToken,
        revoked_at: datetime,
        reason_code: str,
    ) -> None:
        payload = _token_audit_payload(token, reason_code=reason_code)
        payload["revoked_at"] = revoked_at.isoformat()
        await AuditEventRepository(self.session).append(
            tenant_id=tenant_id,
            event_type="api_capability_token_revoked",
            payload=payload,
            actor_id=actor_id,
            principal_id=token.principal_id,
            correlation_id=f"api-capability:{_sha256_text(str(token.id))}",
        )

    async def _append_denied(
        self,
        *,
        tenant_id: int,
        actor_id: UUID,
        reason_code: str,
        project_id: UUID | None,
        allowed_actions: list[ApiCapabilityAction],
    ) -> None:
        await AuditEventRepository(self.session).append(
            tenant_id=tenant_id,
            event_type="api_capability_token_denied",
            payload={
                "rls_ready": True,
                "reason_code": reason_code,
                "project_id": str(project_id) if project_id is not None else None,
                "allowed_actions": list(allowed_actions),
                "redaction_status": "ref_only",
            },
            actor_id=actor_id,
            correlation_id=f"api-capability-denied:{reason_code}",
        )

    async def _append_scope_mismatch(
        self,
        *,
        tenant_id: int,
        actor_id: UUID,
        token: ApiCapabilityToken,
        reason_code: str,
        required_action: ApiCapabilityAction,
        requested_project_id: UUID | None,
    ) -> None:
        await AuditEventRepository(self.session).append(
            tenant_id=tenant_id,
            event_type="api_capability_token_scope_mismatch",
            payload={
                "rls_ready": True,
                "reason_code": reason_code,
                "api_capability_id_hash": _sha256_text(str(token.id)),
                "principal_id": str(token.principal_id),
                "token_project_id": str(token.project_id)
                if token.project_id is not None
                else None,
                "requested_project_id": str(requested_project_id)
                if requested_project_id is not None
                else None,
                "required_action": required_action,
                "allowed_actions": list(token.allowed_actions),
                "redaction_status": "ref_only",
            },
            actor_id=actor_id,
            principal_id=token.principal_id,
            correlation_id=f"api-capability-scope-mismatch:{_sha256_text(str(token.id))}",
        )


def _token_audit_payload(
    token: ApiCapabilityToken,
    *,
    reason_code: str,
) -> dict[str, Any]:
    return {
        "rls_ready": True,
        "reason_code": reason_code,
        "api_capability_id_hash": _sha256_text(str(token.id)),
        "principal_id": str(token.principal_id),
        "project_id": str(token.project_id) if token.project_id is not None else None,
        "allowed_actions": list(token.allowed_actions),
        "scope_constraint_hash": _sha256_json(token.scope_constraint),
        "audience": token.audience,
        "device_id_hash": _sha256_text(token.device_id) if token.device_id else None,
        "expires_at": token.expires_at.isoformat(),
        "redaction_status": "ref_only",
    }


def _stored_actions(token: ApiCapabilityToken) -> list[ApiCapabilityAction]:
    return cast(list[ApiCapabilityAction], list(token.allowed_actions))


def _classify_authorization_mismatch(
    *,
    token: ApiCapabilityToken,
    required_action: ApiCapabilityAction,
    project_id: UUID | None,
) -> str | None:
    if token.audience != AUDIENCE:
        return "audience_mismatch"
    if required_action not in _stored_actions(token):
        return "action_scope_mismatch"
    if token.project_id is not None and token.project_id != project_id:
        return "project_scope_mismatch"
    scope_project_id = token.scope_constraint.get("project_id")
    if scope_project_id is not None and str(scope_project_id) != (
        str(token.project_id) if token.project_id is not None else None
    ):
        return "scope_constraint_project_mismatch"
    if (
        token.project_id is None
        and project_id is not None
        and required_action not in TENANT_WIDE_READ_ONLY_ACTIONS
    ):
        return "tenant_wide_scope_requires_read_only"
    return None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _sha256_text(canonical)


def _utc_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(tz=UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ApiCapabilityTokenDenied("timestamp_must_be_timezone_aware")
    return value.astimezone(UTC)


__all__ = [
    "API_CAPABILITY_ACTIONS",
    "ApiCapabilityTokenAuthorizeResult",
    "ApiCapabilityTokenDenied",
    "ApiCapabilityTokenIssueResult",
    "ApiCapabilityTokenRevokeResult",
    "ApiCapabilityTokenService",
]
