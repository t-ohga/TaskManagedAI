from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.schemas.api_capability_token import (
    CliTokenIssueRequest,
    CliTokenIssueResponse,
    CliTokenRefreshRequest,
    CliTokenRevokeRequest,
    CliTokenRevokeResponse,
)
from backend.app.services.auth import (
    ApiCapabilityTokenDenied,
    ApiCapabilityTokenIssueResult,
    ApiCapabilityTokenService,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/cli-login",
    response_model=CliTokenIssueResponse,
    summary="Issue a short-lived CLI operation token",
)
async def cli_login(
    payload: CliTokenIssueRequest,
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> CliTokenIssueResponse:
    try:
        result = await ApiCapabilityTokenService(session).issue(
            tenant_id=tenant_id,
            actor_id=actor_id,
            project_id=payload.project_id,
            device_id=payload.device_id,
            allowed_actions=payload.allowed_actions,
            scope_constraint=payload.scope_constraint,
            auth_method=payload.auth_method,
            auth_context_hash=payload.auth_context_hash,
            request_binding_hash=payload.request_binding_hash,
            ttl_minutes=payload.ttl_minutes,
        )
    except ApiCapabilityTokenDenied as exc:
        await session.commit()
        raise _capability_denied_http(exc) from exc
    await session.commit()
    return _issue_response(result)


@router.post(
    "/cli-token/refresh",
    response_model=CliTokenIssueResponse,
    summary="Refresh a short-lived CLI operation token",
)
async def refresh_cli_token(
    payload: CliTokenRefreshRequest,
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> CliTokenIssueResponse:
    try:
        result = await ApiCapabilityTokenService(session).refresh(
            tenant_id=tenant_id,
            actor_id=actor_id,
            raw_operation_token=payload.operation_token,
            ttl_minutes=payload.ttl_minutes,
        )
    except ApiCapabilityTokenDenied as exc:
        await session.commit()
        raise _capability_denied_http(exc) from exc
    await session.commit()
    return _issue_response(result)


@router.post(
    "/cli-token/revoke",
    response_model=CliTokenRevokeResponse,
    summary="Revoke a short-lived CLI operation token",
)
async def revoke_cli_token(
    payload: CliTokenRevokeRequest,
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> CliTokenRevokeResponse:
    try:
        result = await ApiCapabilityTokenService(session).revoke(
            tenant_id=tenant_id,
            actor_id=actor_id,
            raw_operation_token=payload.operation_token,
        )
    except ApiCapabilityTokenDenied as exc:
        await session.commit()
        raise _capability_denied_http(exc) from exc
    await session.commit()
    return CliTokenRevokeResponse(
        status="revoked",
        token_id=result.token_id,
        revoked_at=result.revoked_at,
    )


def _issue_response(result: ApiCapabilityTokenIssueResult) -> CliTokenIssueResponse:
    return CliTokenIssueResponse(
        status="issued",
        operation_token=result.raw_operation_token,
        token_id=result.token.id,
        principal_id=result.token.principal_id,
        expires_at=result.token.expires_at,
        audience="taskmanagedai-api",
        allowed_actions=list(result.token.allowed_actions),
    )


def _capability_denied_http(exc: ApiCapabilityTokenDenied) -> HTTPException:
    status_code = (
        status.HTTP_404_NOT_FOUND
        if exc.reason_code == "invalid_operation_token"
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(
        status_code=status_code,
        detail={
            "error_code": "api_capability_token_denied",
            "reason_code": exc.reason_code,
        },
    )


__all__ = [
    "cli_login",
    "refresh_cli_token",
    "revoke_cli_token",
    "router",
]
