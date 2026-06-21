from __future__ import annotations

import hashlib
import inspect
import logging
import re
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypeVar, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.db.models.secret_capability_token import SecretCapabilityToken
from backend.app.db.models.secret_ref import SecretRef
from backend.app.domain.agent_runtime.operation_context import (
    OperationContext,
    RequestedOperation,
    compute_fingerprint,
    compute_payload_hash,
)
from backend.app.repositories.audit_event import AuditEventRepository
from backend.app.repositories.secret_capability_token import (
    ClaimDenyReason,
    ClaimResult,
    SecretCapabilityTokenRepository,
)
from backend.app.services.secrets.local_secret_store import LocalSecretStoreError
from backend.app.services.secrets.resolver_dispatch import CompositeResolverError
from backend.app.services.secrets.sops_resolver import SopsResolverError

logger = logging.getLogger(__name__)

# atomic claim 後の secret resolve で fail-closed に raise する custody/resolver 系例外 (Codex R14-F2)。
# LocalSecretStore (marker 不在 / backend drift / permission / decrypt 失敗) /
# CompositeSecretResolver (local material gate / 未知 backend) / SopsSubprocessResolver。
_RESOLVER_CUSTODY_ERRORS: tuple[type[Exception], ...] = (
    CompositeResolverError,
    LocalSecretStoreError,
    SopsResolverError,
)

IssueDenyReason = Literal[
    "secret_ref_not_found",
    "secret_ref_not_active",
    "operation_mismatch",
    "consumer_mismatch",
    "approval_required",
    "approval_not_found",
    "approval_not_approved",
    "approval_action_class_mismatch",
    "approval_diff_hash_mismatch",
    "approval_target_mismatch",
    "approval_tenant_mismatch",
    "approval_run_mismatch",
    "ttl_out_of_bounds",
    "shadow_run_mutation_forbidden",
    "run_required_for_repo_mutation",
    "material_not_present",
    "secret_target_mismatch",
]
RedeemDenyReason = Literal[
    "not_found",
    "expired",
    "token_used",
    "actor_mismatch",
    "run_mismatch",
    "fingerprint_mismatch",
    "operation_mismatch",
    "secret_ref_revoked",
    "secret_ref_deprecated",
    "scope_constraint_invalid",
    "scope_mismatch",
    "name_mismatch",
    "version_mismatch",
    "consumer_mismatch",
    "material_not_present",
    "secret_target_mismatch",
]

T = TypeVar("T")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

# secret 自己参照 operation (target = {secret_ref_id, version})。target を caller 入力として信用せず、
# 実 secret_ref と target.secret_ref_id / version の同一性を issue / claim 両方で強制する (Codex R16-F2)。
# 怠ると secret A の token を発行しつつ target に secret B を入れ、B の approval で通す substitution が可能。
_SECRET_SELF_TARGET_OPERATIONS: frozenset[str] = frozenset(
    {"secret.verify", "rotation.read_old", "rotation.read_new"}
)


def _secret_target_matches(target: Mapping[str, Any], secret_ref: SecretRef) -> bool:
    """secret 自己参照 operation の target が実 secret_ref と一致するか (R16-F2)。"""
    return str(target.get("secret_ref_id")) == str(secret_ref.id) and target.get(
        "version"
    ) == secret_ref.version


# rotation verify 専用 operation: 新 version material を promote 前に `pending` + `material_state='present'`
# の状態で検証/読取するため、status='active' のみの gate を緩め pending を許可する (Codex R17-F1、
# secretbroker-boundary §5/§7/§9 「rotation verify 専用 operation だけ pending を許可」に準拠)。
# pending 許可は material_state='present' 必須 + R16-F2 の target↔secret_ref 同一性が併せて担保する。
_ROTATION_PENDING_VERIFY_OPERATIONS: frozenset[str] = frozenset(
    {"rotation.read_new", "secret.verify"}
)


def _secret_ref_status_allowed(
    status: str, requested_operation: RequestedOperation
) -> bool:
    """secret_ref.status が当該 operation で許可されるか (active 常時 / pending は rotation verify のみ)。"""
    if status == "active":
        return True
    return (
        status == "pending"
        and requested_operation in _ROTATION_PENDING_VERIFY_OPERATIONS
    )

# SP-029 (ADR-00055 §設計制約 3、Codex R1 F-2): shadow run は repo mutation の
# capability token を発行できない (downstream の repo write / PR open / merge を
# transitively 封鎖)。provider.call は shadow でも通常経路で許可される (§7)、
# secret.verify / rotation.* は read/admin のため対象外。
_SHADOW_FORBIDDEN_OPERATIONS: frozenset[RequestedOperation] = frozenset(
    {"repo.push", "repo.pr_open"}
)


@dataclass(frozen=True, slots=True)
class BrokerIssueResult:
    raw_token: str
    token_id: UUID
    secret_ref_id: UUID
    expires_at: datetime

    @property
    def capability_token(self) -> str:
        return self.raw_token

    @property
    def capability_id(self) -> UUID:
        return self.token_id


@dataclass(frozen=True, slots=True)
class BrokerRedeemDenied:
    reason_code: RedeemDenyReason
    requested_operation: RequestedOperation
    computed_fingerprint: str | None = None
    capability_id: UUID | None = None
    secret_ref_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class BrokerRedeemResult[T]:
    capability_id: UUID
    secret_ref_id: UUID
    requested_operation: RequestedOperation
    operation_result: T | None


@dataclass(frozen=True, slots=True)
class SecretHandle:
    secret_ref_id: UUID
    scope: str
    name: str
    version: str


@dataclass(frozen=True, slots=True)
class BrokerOperationContext:
    tenant_id: int
    actor_id: UUID
    run_id: UUID | None
    requested_operation: RequestedOperation
    target: Mapping[str, Any]
    payload_hash: str
    secret_handle: SecretHandle


class BrokerIssueDenied(ValueError):
    def __init__(self, reason_code: IssueDenyReason) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


# resolver は (secret_ref, *, allow_pending_verify=False) を受ける (Codex R18-F1)。broker は rotation
# verify 専用 op の pending+present に対してのみ allow_pending_verify=True を渡し、direct/webhook 経路は
# default False で fail-closed を維持する。Callable[..., ...] で kwarg を許容する。
SecretResolver = Callable[..., object | Awaitable[object]]
OperationCallback = Callable[[BrokerOperationContext], T | Awaitable[T]]

MultiAgentSecretDenyReason = Literal[
    "agent_decider_forbidden",
    "tier_2_agent_decider_attempt",
    "actor_type_mismatch",
    "role_id_mismatch",
    "lease_expired_no_secret_access",
    "progress_lease_violated",
]

MULTI_AGENT_SECRET_DENY_REASON_VALUES: tuple[MultiAgentSecretDenyReason, ...] = (
    "agent_decider_forbidden",
    "tier_2_agent_decider_attempt",
    "actor_type_mismatch",
    "role_id_mismatch",
    "lease_expired_no_secret_access",
    "progress_lease_violated",
)

MULTI_AGENT_SECRET_DENY_REASONS: frozenset[str] = frozenset(MULTI_AGENT_SECRET_DENY_REASON_VALUES)


class SecretBrokerMultiAgentDeniedPayload(BaseModel):
    reason_code: MultiAgentSecretDenyReason
    actor_id: str
    run_id: str | None = None
    role_id: str | None = None


class SecretBroker:
    def __init__(
        self,
        session: AsyncSession,
        *,
        secret_resolver: SecretResolver | None = None,
    ) -> None:
        self.session = session
        self.secret_resolver = secret_resolver

    async def issue_capability_token(
        self,
        *,
        tenant_id: int,
        actor_id: UUID,
        run_id: UUID | None,
        secret_ref_id: UUID,
        requested_operation: RequestedOperation,
        target: Mapping[str, Any],
        payload: object | None = None,
        payload_hash: str | None = None,
        approval_id: UUID | None = None,
        policy_version: str,
        provider_compliance_matrix_version: str | None = None,
        ttl: timedelta = timedelta(minutes=15),
    ) -> BrokerIssueResult:
        if ttl < timedelta(minutes=5) or ttl > timedelta(minutes=30):
            raise BrokerIssueDenied("ttl_out_of_bounds")

        # SP-029 (Codex R1 F-2 / R3 F-1): repo mutation capability は production run に
        # binding 必須。run_mode は DB row から解決し caller 申告に依存しない
        # (server-owned boundary)。
        await self._assert_repo_mutation_run_is_production(
            tenant_id=tenant_id,
            run_id=run_id,
            requested_operation=requested_operation,
        )

        resolved_payload_hash = _resolve_payload_hash(payload=payload, payload_hash=payload_hash)

        secret_ref = await self._get_secret_ref(
            tenant_id=tenant_id,
            secret_ref_id=secret_ref_id,
            lock=False,
        )
        if secret_ref is None:
            raise BrokerIssueDenied("secret_ref_not_found")

        self._validate_secret_ref_for_issue(
            secret_ref=secret_ref,
            actor_id=actor_id,
            requested_operation=requested_operation,
        )
        # secret 自己参照 operation は target を caller 入力として信用せず、実 secret_ref と
        # target.secret_ref_id / version の同一性を強制する (Codex R16-F2)。approval は target から
        # 導出した resource_ref で照合されるため、approval 照合の前に target↔secret_ref を固定する
        # (secret A を発行しつつ target/approval を secret B に向ける substitution を封じる)。
        if (
            requested_operation in _SECRET_SELF_TARGET_OPERATIONS
            and not _secret_target_matches(target, secret_ref)
        ):
            raise BrokerIssueDenied("secret_target_mismatch")
        await self._validate_approval(
            tenant_id=tenant_id,
            approval_id=approval_id,
            run_id=run_id,
            requested_operation=requested_operation,
            target=target,
            payload_hash=resolved_payload_hash,
        )

        operation_context = OperationContext(
            tenant_id=tenant_id,
            actor_id=actor_id,
            run_id=run_id,
            secret_ref_id=secret_ref.id,
            requested_operation=requested_operation,
            target=dict(target),
            payload_hash=resolved_payload_hash,
            approval_id=approval_id,
            policy_version=policy_version,
            provider_compliance_matrix_version=provider_compliance_matrix_version,
        )
        expected_fingerprint = compute_fingerprint(operation_context)

        raw_capability = secrets.token_urlsafe(32)
        capability_hash = hashlib.sha256(raw_capability.encode("utf-8")).hexdigest()
        now = datetime.now(tz=UTC)
        expires_at = now + ttl

        capability = SecretCapabilityToken(
            tenant_id=tenant_id,
            secret_ref_id=secret_ref.id,
            token_hash=capability_hash,
            allowed_operations=[requested_operation],
            scope_constraint={
                "scope": secret_ref.scope,
                "name": secret_ref.name,
                "version": secret_ref.version,
            },
            issued_to_actor_id=actor_id,
            issued_run_id=run_id,
            expected_request_fingerprint=expected_fingerprint,
            expires_at=expires_at,
            used_at=None,
            status="issued",
            created_at=now,
            metadata_={"rls_ready": True, "audience": "SecretBroker"},
        )
        self.session.add(capability)
        await self.session.flush()

        await AuditEventRepository(self.session).append(
            tenant_id=tenant_id,
            event_type="secret_capability_issued",
            actor_id=actor_id,
            payload={
                "capability_id": str(capability.id),
                "secret_ref_id": str(secret_ref.id),
                "run_id": None if run_id is None else str(run_id),
                "requested_operation": requested_operation,
                "expected_request_fingerprint_hash": _fingerprint_audit_hash(
                    expected_fingerprint
                ),
                "expires_at": expires_at.isoformat(),
            },
        )

        return BrokerIssueResult(
            raw_token=raw_capability,
            token_id=capability.id,
            secret_ref_id=secret_ref.id,
            expires_at=expires_at,
        )

    async def redeem_capability_token(
        self,
        *,
        tenant_id: int,
        actor_id: UUID,
        run_id: UUID | None,
        raw_token: str,
        requested_operation: RequestedOperation,
        target: Mapping[str, Any],
        payload: object | None = None,
        payload_hash: str | None = None,
        approval_id: UUID | None = None,
        policy_version: str,
        provider_compliance_matrix_version: str | None = None,
        operation: OperationCallback[T] | None = None,
    ) -> BrokerRedeemResult[T] | BrokerRedeemDenied:
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        token = await self.session.scalar(
            sa.select(SecretCapabilityToken).where(
                SecretCapabilityToken.tenant_id == tenant_id,
                SecretCapabilityToken.token_hash == token_hash,
            )
        )
        if token is None:
            denied = BrokerRedeemDenied(
                reason_code="not_found",
                requested_operation=requested_operation,
            )
            await self._audit_redeem_denied(tenant_id, actor_id, denied, run_id)
            return denied

        try:
            resolved_payload_hash = _resolve_payload_hash(
                payload=payload,
                payload_hash=payload_hash,
            )
            operation_context = OperationContext(
                tenant_id=tenant_id,
                actor_id=actor_id,
                run_id=run_id,
                secret_ref_id=token.secret_ref_id,
                requested_operation=requested_operation,
                target=dict(target),
                payload_hash=resolved_payload_hash,
                approval_id=approval_id,
                policy_version=policy_version,
                provider_compliance_matrix_version=provider_compliance_matrix_version,
            )
            computed_fingerprint = compute_fingerprint(operation_context)
        except ValueError:
            denied = BrokerRedeemDenied(
                reason_code="fingerprint_mismatch",
                requested_operation=requested_operation,
                capability_id=token.id,
                secret_ref_id=token.secret_ref_id,
            )
            await self._audit_redeem_denied(tenant_id, actor_id, denied, run_id)
            return denied

        claim = await SecretCapabilityTokenRepository(self.session).atomic_claim(
            tenant_id=tenant_id,
            token_hash=token_hash,
            actor_id=actor_id,
            run_id=run_id,
            requested_operation=requested_operation,
            computed_fingerprint=computed_fingerprint,
        )
        if not claim.claimed:
            denied = _claim_denial_to_broker_denial(
                claim=claim,
                requested_operation=requested_operation,
                computed_fingerprint=computed_fingerprint,
            )
            await self._audit_redeem_denied(tenant_id, actor_id, denied, run_id)
            return denied

        capability_id, secret_ref_id = _claimed_ids(claim)
        secret_ref = await self._get_secret_ref(
            tenant_id=tenant_id,
            secret_ref_id=secret_ref_id,
            lock=True,
        )
        post_claim_denial = self._validate_secret_ref_after_claim(
            secret_ref=secret_ref,
            actor_id=actor_id,
            requested_operation=requested_operation,
            claim=claim,
            computed_fingerprint=computed_fingerprint,
        )
        if post_claim_denial is not None:
            await self._mark_claimed_token_revoked(tenant_id, capability_id)
            await self._audit_redeem_denied(tenant_id, actor_id, post_claim_denial, run_id)
            return post_claim_denial

        if secret_ref is None:
            raise RuntimeError("SecretBroker invariant violated: secret_ref missing after claim.")
        # secret 自己参照 operation の target↔secret_ref 同一性を claim 後にも再検証する (Codex R16-F2、
        # defense-in-depth)。fingerprint 一致は redeem-target == issue-target を保証するが、issue 前の
        # 旧 token / 将来の経路差に備え、resolve 済 secret_ref と target.secret_ref_id / version を再固定する。
        if (
            requested_operation in _SECRET_SELF_TARGET_OPERATIONS
            and not _secret_target_matches(target, secret_ref)
        ):
            denied = BrokerRedeemDenied(
                reason_code="secret_target_mismatch",
                requested_operation=requested_operation,
                computed_fingerprint=computed_fingerprint,
                capability_id=capability_id,
                secret_ref_id=secret_ref_id,
            )
            await self._mark_claimed_token_revoked(tenant_id, capability_id)
            await self._audit_redeem_denied(tenant_id, actor_id, denied, run_id)
            return denied
        # custody/resolver fail-closed (marker 不在 / backend drift / permission / decrypt 失敗 /
        # material gate) は **pre-resolve と operation 内の再 resolve の両方**で起き得る (Codex R14-F2 +
        # R15-F1)。operation path (例: GitHubAppAdapter→HttpxGitHubTransport が installation token を再
        # resolve) で raise すると、atomic claim 済 token を消費したまま例外伝播し denied audit + token
        # revoke を bypass する (500 + token_used 誤分類)。両 path を同一 helper で denied 化する。
        # rotation verify 専用 op の pending+present は resolver の status gate を緩める (Codex R18-F1)。
        # broker gate (R17-F1) と resolver gate (R6-F2) の整合: broker 経由 verify のみ pending を resolve 可。
        allow_pending_verify = (
            requested_operation in _ROTATION_PENDING_VERIFY_OPERATIONS
            and secret_ref.status == "pending"
        )
        try:
            resolved_secret = await self._resolve_secret(
                secret_ref, allow_pending_verify=allow_pending_verify
            )
        except _RESOLVER_CUSTODY_ERRORS:
            return await self._deny_after_claim_custody_failure(
                tenant_id=tenant_id,
                actor_id=actor_id,
                run_id=run_id,
                capability_id=capability_id,
                secret_ref_id=secret_ref_id,
                requested_operation=requested_operation,
                computed_fingerprint=computed_fingerprint,
                stage="resolve",
            )
        del resolved_secret

        result: T | None = None
        if operation is not None:
            context = BrokerOperationContext(
                tenant_id=tenant_id,
                actor_id=actor_id,
                run_id=run_id,
                requested_operation=requested_operation,
                target=dict(target),
                payload_hash=resolved_payload_hash,
                secret_handle=SecretHandle(
                    secret_ref_id=secret_ref.id,
                    scope=secret_ref.scope,
                    name=secret_ref.name,
                    version=secret_ref.version,
                ),
            )
            # 非 custody な operation 失敗 (provider 5xx / GitHub API error 等) は従来どおり伝播させ token は
            # 消費済扱い (boundary §9)。custody/resolver 失敗 (operation 内再 resolve) のみ denied 化する。
            try:
                result = await _maybe_await(operation(context))
            except _RESOLVER_CUSTODY_ERRORS:
                return await self._deny_after_claim_custody_failure(
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    run_id=run_id,
                    capability_id=capability_id,
                    secret_ref_id=secret_ref_id,
                    requested_operation=requested_operation,
                    computed_fingerprint=computed_fingerprint,
                    stage="operation",
                )

        await self._mark_claimed_token_used(tenant_id, capability_id)
        await AuditEventRepository(self.session).append(
            tenant_id=tenant_id,
            event_type="secret_capability_redeemed",
            actor_id=actor_id,
            payload={
                "capability_id": str(capability_id),
                "secret_ref_id": str(secret_ref_id),
                "run_id": None if run_id is None else str(run_id),
                "requested_operation": requested_operation,
                "expected_request_fingerprint_hash": _fingerprint_audit_hash(
                    computed_fingerprint
                ),
            },
        )

        return BrokerRedeemResult(
            capability_id=capability_id,
            secret_ref_id=secret_ref_id,
            requested_operation=requested_operation,
            operation_result=result,
        )

    async def _assert_repo_mutation_run_is_production(
        self,
        *,
        tenant_id: int,
        run_id: UUID | None,
        requested_operation: RequestedOperation,
    ) -> None:
        """repo mutation capability を production run に binding 必須で fail-closed 化する。

        repo.push / repo.pr_open のみが対象 (provider.call / secret.verify /
        rotation.* は対象外で run binding 任意)。caller が ``run_id`` を落とす / 不在
        UUID を詐称して shadow guard を迂回するのを防ぐため、repo mutation は
        ``run_id`` 必須 + ``(tenant_id, run_id)`` 実在 + ``run_mode='production'`` を
        要求する (Codex R1 F-2 / R3 F-1、server-owned boundary)。run_mode は creation
        後 immutable なので issue 時 1 回の確認で十分 (redeem 側 re-check 不要)。
        """

        if requested_operation not in _SHADOW_FORBIDDEN_OPERATIONS:
            return
        if run_id is None:
            raise BrokerIssueDenied("run_required_for_repo_mutation")
        run = await self.session.scalar(
            sa.select(AgentRun).where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.id == run_id,
            )
        )
        if run is None:
            raise BrokerIssueDenied("run_required_for_repo_mutation")
        if run.run_mode != "production":
            raise BrokerIssueDenied("shadow_run_mutation_forbidden")

    async def _get_secret_ref(
        self,
        *,
        tenant_id: int,
        secret_ref_id: UUID,
        lock: bool,
    ) -> SecretRef | None:
        stmt = sa.select(SecretRef).where(
            SecretRef.tenant_id == tenant_id,
            SecretRef.id == secret_ref_id,
        )
        if lock:
            stmt = stmt.with_for_update()
        return cast(SecretRef | None, await self.session.scalar(stmt))

    def _validate_secret_ref_for_issue(
        self,
        *,
        secret_ref: SecretRef,
        actor_id: UUID,
        requested_operation: RequestedOperation,
    ) -> None:
        # status='active' が通常。rotation verify 専用 operation のみ pending を許可する (Codex R17-F1、
        # 新 version material を promote 前に検証する rotate→verify→promote flow、boundary §5/§7/§9)。
        if not _secret_ref_status_allowed(secret_ref.status, requested_operation):
            raise BrokerIssueDenied("secret_ref_not_active")
        # material lifecycle gate (ADR-00058 finding-2): store 未完了 (writing) / purge 中・済
        # (purging/purged) の row から token を発行しない (false-present 防止)。pending verify も present 必須。
        if secret_ref.material_state != "present":
            raise BrokerIssueDenied("material_not_present")
        if requested_operation not in secret_ref.allowed_operations:
            raise BrokerIssueDenied("operation_mismatch")
        if not _actor_allowed(actor_id, secret_ref.allowed_consumers):
            raise BrokerIssueDenied("consumer_mismatch")

    async def _validate_approval(
        self,
        *,
        tenant_id: int,
        approval_id: UUID | None,
        run_id: UUID | None,
        requested_operation: RequestedOperation,
        target: Mapping[str, Any],
        payload_hash: str,
    ) -> None:
        if approval_id is None:
            if _operation_requires_approval(requested_operation):
                raise BrokerIssueDenied("approval_required")
            return

        approval = await self.session.scalar(
            sa.select(ApprovalRequest).where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.id == approval_id,
            )
        )
        if approval is None:
            raise BrokerIssueDenied("approval_not_found")
        if approval.tenant_id != tenant_id:
            raise BrokerIssueDenied("approval_tenant_mismatch")
        if approval.status != "approved":
            raise BrokerIssueDenied("approval_not_approved")

        expected_action_class = _operation_to_action_class(requested_operation)
        if approval.action_class != expected_action_class:
            raise BrokerIssueDenied("approval_action_class_mismatch")

        if requested_operation in {"repo.push", "repo.pr_open"}:
            if approval.diff_hash != payload_hash:
                raise BrokerIssueDenied("approval_diff_hash_mismatch")
            # SP-029 (Codex R6 F-2): repo mutation approval は capability と同一 run に
            # binding 必須。run_id を借用した別 run の approval で shadow diff を push する
            # 経路を塞ぐ (approval と capability の run binding 一致 = server-owned)。
            if approval.run_id is None or approval.run_id != run_id:
                raise BrokerIssueDenied("approval_run_mismatch")
        elif requested_operation == "provider.call":
            if approval.provider_request_fingerprint != payload_hash:
                raise BrokerIssueDenied("approval_diff_hash_mismatch")

        if approval.resource_ref != _operation_target_to_ref(target, requested_operation):
            raise BrokerIssueDenied("approval_target_mismatch")

    def _validate_secret_ref_after_claim(
        self,
        *,
        secret_ref: SecretRef | None,
        actor_id: UUID,
        requested_operation: RequestedOperation,
        claim: ClaimResult,
        computed_fingerprint: str,
    ) -> BrokerRedeemDenied | None:
        if secret_ref is None:
            return BrokerRedeemDenied(
                reason_code="secret_ref_revoked",
                requested_operation=requested_operation,
                computed_fingerprint=computed_fingerprint,
                capability_id=claim.capability_id,
                secret_ref_id=claim.secret_ref_id,
            )
        if secret_ref.status == "revoked":
            return BrokerRedeemDenied(
                reason_code="secret_ref_revoked",
                requested_operation=requested_operation,
                computed_fingerprint=computed_fingerprint,
                capability_id=claim.capability_id,
                secret_ref_id=claim.secret_ref_id,
            )
        if secret_ref.status == "deprecated":
            return BrokerRedeemDenied(
                reason_code="secret_ref_deprecated",
                requested_operation=requested_operation,
                computed_fingerprint=computed_fingerprint,
                capability_id=claim.capability_id,
                secret_ref_id=claim.secret_ref_id,
            )
        # active が通常。rotation verify 専用 operation のみ pending を許可 (Codex R17-F1、issue gate と mirror)。
        if not _secret_ref_status_allowed(secret_ref.status, requested_operation):
            return BrokerRedeemDenied(
                reason_code="secret_ref_revoked",
                requested_operation=requested_operation,
                computed_fingerprint=computed_fingerprint,
                capability_id=claim.capability_id,
                secret_ref_id=claim.secret_ref_id,
            )
        # material lifecycle gate (ADR-00058 finding-2): redeem 時の secret_ref 再検証でも
        # material_state='present' を必須化 (writing/purging/purged は material_not_present で deny)。
        if secret_ref.material_state != "present":
            return BrokerRedeemDenied(
                reason_code="material_not_present",
                requested_operation=requested_operation,
                computed_fingerprint=computed_fingerprint,
                capability_id=claim.capability_id,
                secret_ref_id=claim.secret_ref_id,
            )

        constraint = claim.scope_constraint
        if not isinstance(constraint, dict):
            return BrokerRedeemDenied(
                reason_code="scope_constraint_invalid",
                requested_operation=requested_operation,
                computed_fingerprint=computed_fingerprint,
                capability_id=claim.capability_id,
                secret_ref_id=claim.secret_ref_id,
            )
        if constraint.get("scope") != secret_ref.scope:
            return BrokerRedeemDenied(
                reason_code="scope_mismatch",
                requested_operation=requested_operation,
                computed_fingerprint=computed_fingerprint,
                capability_id=claim.capability_id,
                secret_ref_id=claim.secret_ref_id,
            )
        if constraint.get("name") != secret_ref.name:
            return BrokerRedeemDenied(
                reason_code="name_mismatch",
                requested_operation=requested_operation,
                computed_fingerprint=computed_fingerprint,
                capability_id=claim.capability_id,
                secret_ref_id=claim.secret_ref_id,
            )
        if constraint.get("version") != secret_ref.version:
            return BrokerRedeemDenied(
                reason_code="version_mismatch",
                requested_operation=requested_operation,
                computed_fingerprint=computed_fingerprint,
                capability_id=claim.capability_id,
                secret_ref_id=claim.secret_ref_id,
            )
        if requested_operation not in secret_ref.allowed_operations:
            return BrokerRedeemDenied(
                reason_code="operation_mismatch",
                requested_operation=requested_operation,
                computed_fingerprint=computed_fingerprint,
                capability_id=claim.capability_id,
                secret_ref_id=claim.secret_ref_id,
            )
        if not _actor_allowed(actor_id, secret_ref.allowed_consumers):
            return BrokerRedeemDenied(
                reason_code="consumer_mismatch",
                requested_operation=requested_operation,
                computed_fingerprint=computed_fingerprint,
                capability_id=claim.capability_id,
                secret_ref_id=claim.secret_ref_id,
            )
        return None

    async def _deny_after_claim_custody_failure(
        self,
        *,
        tenant_id: int,
        actor_id: UUID,
        run_id: UUID | None,
        capability_id: UUID,
        secret_ref_id: UUID,
        requested_operation: RequestedOperation,
        computed_fingerprint: str | None,
        stage: str,
    ) -> BrokerRedeemDenied:
        """atomic claim 後の custody/resolver 失敗を fail-closed deny にする (Codex R14-F2 / R15-F1)。

        claimed token を revoke + ``secret_capability_denied`` audit にして
        ``BrokerRedeemDenied(material_not_present)`` を返す。raw secret / 例外詳細は audit / response に
        出さず reason_code と stage (resolve / operation) のみ残す。
        """
        logger.warning(
            "secret custody resolve failed after atomic claim; denying redeem fail-closed",
            extra={
                "tenant_id": tenant_id,
                "capability_id": str(capability_id),
                "secret_ref_id": str(secret_ref_id),
                "stage": stage,
            },
        )
        denied = BrokerRedeemDenied(
            reason_code="material_not_present",
            requested_operation=requested_operation,
            computed_fingerprint=computed_fingerprint,
            capability_id=capability_id,
            secret_ref_id=secret_ref_id,
        )
        await self._mark_claimed_token_revoked(tenant_id, capability_id)
        await self._audit_redeem_denied(tenant_id, actor_id, denied, run_id)
        return denied

    async def _resolve_secret(
        self, secret_ref: SecretRef, *, allow_pending_verify: bool = False
    ) -> object:
        if self.secret_resolver is None:
            return SecretHandle(
                secret_ref_id=secret_ref.id,
                scope=secret_ref.scope,
                name=secret_ref.name,
                version=secret_ref.version,
            )
        # rotation verify 専用 op の pending+present のみ resolver の status gate を緩める (Codex R18-F1)。
        return await _maybe_await(
            self.secret_resolver(secret_ref, allow_pending_verify=allow_pending_verify)
        )

    async def _mark_claimed_token_used(self, tenant_id: int, capability_id: UUID) -> None:
        await self.session.execute(
            sa.update(SecretCapabilityToken)
            .where(
                SecretCapabilityToken.tenant_id == tenant_id,
                SecretCapabilityToken.id == capability_id,
            )
            .values(status="used")
        )

    async def _mark_claimed_token_revoked(self, tenant_id: int, capability_id: UUID) -> None:
        await self.session.execute(
            sa.update(SecretCapabilityToken)
            .where(
                SecretCapabilityToken.tenant_id == tenant_id,
                SecretCapabilityToken.id == capability_id,
            )
            .values(status="revoked")
        )

    async def _audit_redeem_denied(
        self,
        tenant_id: int,
        actor_id: UUID,
        denied: BrokerRedeemDenied,
        run_id: UUID | None,
    ) -> None:
        await AuditEventRepository(self.session).append(
            tenant_id=tenant_id,
            event_type="secret_capability_denied",
            actor_id=actor_id,
            payload={
                "reason_code": denied.reason_code,
                "capability_id": None
                if denied.capability_id is None
                else str(denied.capability_id),
                "secret_ref_id": None if denied.secret_ref_id is None else str(denied.secret_ref_id),
                "run_id": None if run_id is None else str(run_id),
                "requested_operation": denied.requested_operation,
                "expected_request_fingerprint_hash": _fingerprint_audit_hash(
                    denied.computed_fingerprint
                ),
            },
        )


def _claim_denial_to_broker_denial(
    *,
    claim: ClaimResult,
    requested_operation: RequestedOperation,
    computed_fingerprint: str,
) -> BrokerRedeemDenied:
    reason: RedeemDenyReason = _claim_reason_to_redeem_reason(claim.reason_code)
    return BrokerRedeemDenied(
        reason_code=reason,
        requested_operation=requested_operation,
        computed_fingerprint=computed_fingerprint,
        capability_id=claim.capability_id,
        secret_ref_id=claim.secret_ref_id,
    )


def _claimed_ids(claim: ClaimResult) -> tuple[UUID, UUID]:
    if claim.capability_id is None or claim.secret_ref_id is None:
        raise RuntimeError("SecretBroker invariant violated: claimed token ids are missing.")
    return claim.capability_id, claim.secret_ref_id


def _claim_reason_to_redeem_reason(reason: ClaimDenyReason | None) -> RedeemDenyReason:
    if reason in {
        "not_found",
        "expired",
        "token_used",
        "actor_mismatch",
        "run_mismatch",
        "fingerprint_mismatch",
        "operation_mismatch",
    }:
        return reason
    return "not_found"


def _actor_allowed(actor_id: UUID, allowed_consumers: list[str]) -> bool:
    actor = str(actor_id)
    return actor in allowed_consumers or f"actor:{actor}" in allowed_consumers


def _operation_requires_approval(requested_operation: RequestedOperation) -> bool:
    return requested_operation in {
        "repo.push",
        "repo.pr_open",
        "rotation.read_old",
        "rotation.read_new",
    }


def _operation_to_action_class(requested_operation: RequestedOperation) -> str:
    mapping: dict[RequestedOperation, str] = {
        "provider.call": "provider_call",
        "repo.push": "repo_write",
        "repo.pr_open": "pr_open",
        "secret.verify": "secret_access",
        "rotation.read_old": "secret_access",
        "rotation.read_new": "secret_access",
    }
    return mapping[requested_operation]


def _operation_target_to_ref(
    target: Mapping[str, Any],
    requested_operation: RequestedOperation,
) -> str:
    if requested_operation == "provider.call":
        return (
            f"provider:{_target_string(target, 'provider')}:"
            f"{_target_string(target, 'api_or_feature')}:"
            f"{_target_string(target, 'model_resolved')}"
        )
    if requested_operation == "repo.push":
        return (
            f"repo:{_target_string(target, 'repo_full_name')}:"
            f"{_target_string(target, 'branch')}"
        )
    if requested_operation == "repo.pr_open":
        draft = target.get("draft")
        if draft is not True:
            raise BrokerIssueDenied("approval_target_mismatch")
        # Codex PR #1 R1 F-PR1-002 P1 adopt: `commit_sha` / `repo_state_commit_sha`
        # を approval resource_ref に含めることで、fresh commit_sha / state を
        # 持つ stale repo capability request が古い approval を再利用できない
        # ようにする (approval を repo state にも bind)。
        # Codex PR #8 R1 F-PR8-002 P2 adopt: commit_sha / repo_state_commit_sha
        # は git SHA hex format (`:` 等 separator を含まない) を validate
        # することで、resource_ref への raw concatenation で別 tuple が
        # 同 ref に collide する ambiguity を防止する。
        return (
            f"repo:{_target_string(target, 'repo_full_name')}:pr:"
            f"{_target_string(target, 'base_branch')}:"
            f"{_target_string(target, 'head_branch')}:draft:"
            f"commit:{_target_git_sha(target, 'commit_sha')}:"
            f"state:{_target_git_sha(target, 'repo_state_commit_sha')}"
        )
    return (
        f"secret_ref:{_target_string(target, 'secret_ref_id')}:"
        f"{_target_string(target, 'version')}"
    )


def _target_string(target: Mapping[str, Any], key: str) -> str:
    value = target.get(key)
    if not isinstance(value, str) or not value:
        raise BrokerIssueDenied("approval_target_mismatch")
    return value


# Codex PR #8 R1 F-PR8-002 P2 adopt: git commit SHA hex pattern (SHA-1 40 char
# or SHA-256 64 char、`[0-9a-f]` のみ)。`:` 等 separator 文字が含まれないことを
# validate し、resource_ref への raw concatenation で別 tuple が同 ref に
# collide する ambiguity を防止する。
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")


def _target_git_sha(target: Mapping[str, Any], key: str) -> str:
    """target[key] が有効な git SHA hex (40 or 64 char) であることを validate."""
    value = _target_string(target, key)
    if not _GIT_SHA_RE.match(value):
        raise BrokerIssueDenied("approval_target_mismatch")
    return value


def _resolve_payload_hash(*, payload: object | None, payload_hash: str | None) -> str:
    if payload_hash is None:
        return compute_payload_hash(payload)
    if not _SHA256_RE.fullmatch(payload_hash):
        raise ValueError("payload_hash must be a SHA-256 lowercase hex digest.")
    if payload is not None and compute_payload_hash(payload) != payload_hash:
        raise ValueError("payload and payload_hash do not match.")
    return payload_hash


def _fingerprint_audit_hash(fingerprint: str | None) -> str | None:
    if fingerprint is None:
        return None
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


async def _maybe_await[T](value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = [
    "BrokerIssueDenied",
    "BrokerIssueResult",
    "BrokerOperationContext",
    "BrokerRedeemDenied",
    "BrokerRedeemResult",
    "MULTI_AGENT_SECRET_DENY_REASON_VALUES",
    "MULTI_AGENT_SECRET_DENY_REASONS",
    "MultiAgentSecretDenyReason",
    "SecretBroker",
    "SecretBrokerMultiAgentDeniedPayload",
    "SecretHandle",
]

