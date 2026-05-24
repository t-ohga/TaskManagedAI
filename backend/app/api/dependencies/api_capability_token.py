from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.schemas.api_capability_token import ApiCapabilityAction
from backend.app.services.auth import (
    ApiCapabilityTokenAuthorizeResult,
    ApiCapabilityTokenDenied,
    ApiCapabilityTokenService,
)

OPERATION_TOKEN_HEADER = "X-TaskManagedAI-Operation-Token"  # noqa: S105 - header name, not a token value


def maybe_require_cli_capability(
    required_action: ApiCapabilityAction,
) -> Callable[..., object]:
    async def dependency(
        request: Request,
        project_id: UUID | None = None,
        actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
        tenant_id: int = Depends(get_tenant_id),  # noqa: B008
        session: AsyncSession = Depends(get_db_session),  # noqa: B008
    ) -> ApiCapabilityTokenAuthorizeResult | None:
        raw_operation_token = request.headers.get(OPERATION_TOKEN_HEADER)
        if not raw_operation_token:
            return None
        try:
            result = await ApiCapabilityTokenService(session).authorize_request(
                tenant_id=tenant_id,
                actor_id=actor_id,
                raw_operation_token=raw_operation_token,
                required_action=required_action,
                project_id=project_id,
            )
        except ApiCapabilityTokenDenied as exc:
            await session.commit()
            raise HTTPException(
                status_code=_status_code_for_denial(exc.reason_code),
                detail={
                    "error_code": "api_capability_token_denied",
                    "reason_code": exc.reason_code,
                },
            ) from exc
        await session.commit()
        return result

    return dependency


def _status_code_for_denial(reason_code: str) -> int:
    if reason_code == "invalid_operation_token":
        return status.HTTP_404_NOT_FOUND
    if reason_code in {"expired", "revoked"}:
        return status.HTTP_401_UNAUTHORIZED
    return status.HTTP_403_FORBIDDEN


__all__ = [
    "OPERATION_TOKEN_HEADER",
    "maybe_require_cli_capability",
]
