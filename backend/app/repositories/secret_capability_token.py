from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.secret_capability_token import SecretCapabilityToken
from backend.app.repositories.base import BaseRepository

ClaimDenyReason = Literal[
    "not_found",
    "expired",
    "token_used",
    "actor_mismatch",
    "run_mismatch",
    "fingerprint_mismatch",
    "operation_mismatch",
]


@dataclass(frozen=True, slots=True)
class ClaimResult:
    claimed: bool
    reason_code: ClaimDenyReason | None
    capability_id: UUID | None
    secret_ref_id: UUID | None
    allowed_operations: list[str]
    scope_constraint: dict[str, object]

    @classmethod
    def success(
        cls,
        *,
        capability_id: UUID,
        secret_ref_id: UUID,
        allowed_operations: list[str],
        scope_constraint: dict[str, object],
    ) -> ClaimResult:
        return cls(
            claimed=True,
            reason_code=None,
            capability_id=capability_id,
            secret_ref_id=secret_ref_id,
            allowed_operations=allowed_operations,
            scope_constraint=scope_constraint,
        )

    @classmethod
    def denied(
        cls,
        reason_code: ClaimDenyReason,
        *,
        capability_id: UUID | None = None,
        secret_ref_id: UUID | None = None,
    ) -> ClaimResult:
        return cls(
            claimed=False,
            reason_code=reason_code,
            capability_id=capability_id,
            secret_ref_id=secret_ref_id,
            allowed_operations=[],
            scope_constraint={},
        )


class SecretCapabilityTokenRepository(BaseRepository[SecretCapabilityToken]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SecretCapabilityToken)

    async def get(self, tenant_id: int, id: UUID) -> SecretCapabilityToken | None:
        return await super().get(tenant_id=tenant_id, id=id)

    async def atomic_claim(
        self,
        *,
        tenant_id: int,
        token_hash: str,
        actor_id: UUID,
        run_id: UUID | None,
        requested_operation: str,
        computed_fingerprint: str,
    ) -> ClaimResult:
        if computed_fingerprint is None:
            raise ValueError("computed_fingerprint is required for atomic claim.")

        await self._ensure_tenant_context(tenant_id)

        result = await self.session.execute(
            sa.text(
                """
                update secret_capability_tokens
                   set status = 'redeeming',
                       used_at = now()
                 where tenant_id = :tenant_id
                   and token_hash = :token_hash
                   and status = 'issued'
                   and used_at is null
                   and expires_at > now()
                   and issued_to_actor_id = cast(:actor_id as uuid)
                   and issued_run_id is not distinct from cast(:run_id as uuid)
                   and expected_request_fingerprint = :computed_fingerprint
                   and allowed_operations ? :requested_operation
                returning id, secret_ref_id, allowed_operations, scope_constraint
                """
            ),
            {
                "tenant_id": tenant_id,
                "token_hash": token_hash,
                "actor_id": str(actor_id),
                "run_id": None if run_id is None else str(run_id),
                "computed_fingerprint": computed_fingerprint,
                "requested_operation": requested_operation,
            },
        )
        row = result.mappings().first()
        if row is not None:
            return ClaimResult.success(
                capability_id=row["id"],
                secret_ref_id=row["secret_ref_id"],
                allowed_operations=list(row["allowed_operations"]),
                scope_constraint=dict(row["scope_constraint"]),
            )

        return await self._classify_denied_claim(
            tenant_id=tenant_id,
            token_hash=token_hash,
            actor_id=actor_id,
            run_id=run_id,
            requested_operation=requested_operation,
            computed_fingerprint=computed_fingerprint,
        )

    async def _classify_denied_claim(
        self,
        *,
        tenant_id: int,
        token_hash: str,
        actor_id: UUID,
        run_id: UUID | None,
        requested_operation: str,
        computed_fingerprint: str,
    ) -> ClaimResult:
        result = await self.session.execute(
            sa.text(
                """
                select id,
                       secret_ref_id,
                       status,
                       used_at,
                       expires_at,
                       issued_to_actor_id,
                       issued_run_id,
                       expected_request_fingerprint,
                       allowed_operations
                  from secret_capability_tokens
                 where tenant_id = :tenant_id
                   and token_hash = :token_hash
                 limit 1
                """
            ),
            {"tenant_id": tenant_id, "token_hash": token_hash},
        )
        row = result.mappings().first()
        if row is None:
            return ClaimResult.denied("not_found")

        capability_id = row["id"]
        secret_ref_id = row["secret_ref_id"]
        expires_at = row["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        if row["status"] == "issued" and row["used_at"] is None and expires_at <= datetime.now(tz=UTC):
            return ClaimResult.denied(
                "expired",
                capability_id=capability_id,
                secret_ref_id=secret_ref_id,
            )
        if row["status"] != "issued" or row["used_at"] is not None:
            reason: ClaimDenyReason = (
                "token_used" if row["status"] in {"redeeming", "used"} or row["used_at"] is not None else "not_found"
            )
            return ClaimResult.denied(
                reason,
                capability_id=capability_id,
                secret_ref_id=secret_ref_id,
            )
        if row["issued_to_actor_id"] != actor_id:
            return ClaimResult.denied(
                "actor_mismatch",
                capability_id=capability_id,
                secret_ref_id=secret_ref_id,
            )
        if row["issued_run_id"] != run_id:
            return ClaimResult.denied(
                "run_mismatch",
                capability_id=capability_id,
                secret_ref_id=secret_ref_id,
            )
        if row["expected_request_fingerprint"] != computed_fingerprint:
            return ClaimResult.denied(
                "fingerprint_mismatch",
                capability_id=capability_id,
                secret_ref_id=secret_ref_id,
            )
        if requested_operation not in list(row["allowed_operations"]):
            return ClaimResult.denied(
                "operation_mismatch",
                capability_id=capability_id,
                secret_ref_id=secret_ref_id,
            )

        return ClaimResult.denied(
            "not_found",
            capability_id=capability_id,
            secret_ref_id=secret_ref_id,
        )


async def claim_token(
    session: AsyncSession,
    *,
    tenant_id: int,
    token_hash: str,
    actor_id: UUID,
    run_id: UUID | None,
    requested_operation: str,
    computed_fingerprint: str,
) -> ClaimResult:
    return await SecretCapabilityTokenRepository(session).atomic_claim(
        tenant_id=tenant_id,
        token_hash=token_hash,
        actor_id=actor_id,
        run_id=run_id,
        requested_operation=requested_operation,
        computed_fingerprint=computed_fingerprint,
    )


__all__ = [
    "ClaimDenyReason",
    "ClaimResult",
    "SecretCapabilityTokenRepository",
    "claim_token",
]

