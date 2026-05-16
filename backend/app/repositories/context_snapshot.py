from __future__ import annotations

import re
from datetime import datetime
from typing import Any, NoReturn, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.context_snapshot import (
    CONTEXT_SNAPSHOT_REQUIRED_COLUMNS,
    ContextSnapshot,
    JsonDict,
)
from backend.app.domain.agent_runtime.snapshot_kind import (
    ALL_SNAPSHOT_KINDS,
    SnapshotKind,
)
from backend.app.repositories._payload_secret_scan import (
    _PROHIBITED_PAYLOAD_KEYS,
    _RAW_SECRET_PATTERNS,
    assert_no_raw_secret,
)
from backend.app.repositories.artifact import assert_sha256_hex
from backend.app.repositories.base import BaseRepository
from backend.app.schemas.research.evidence_set import ResearchSetReference
from backend.app.services.research.evidence_set_hash import compute_evidence_set_hash

_CONTEXT_SNAPSHOT_REQUIRED_NONNULL_COLUMNS: tuple[str, ...] = (
    "prompt_pack_version",
    "prompt_pack_lock",
    "policy_version",
    "policy_pack_lock",
    "repo_state",
    "tool_manifest",
    "evidence_set_hash",
    "provider_request_fingerprint",
    "snapshot_kind",
)

_REPO_STATE_REQUIRED_KEYS = frozenset({"commit_sha", "branch", "dirty", "diff_hash"})
_TOOL_MANIFEST_REQUIRED_KEYS = frozenset({"registry_version", "allowlist_hash"})
_PROVIDER_REQUEST_FINGERPRINT_REQUIRED_KEYS = frozenset({"model_resolved"})
_PROVIDER_CONTINUATION_REF_REQUIRED_KEYS = frozenset(
    {"provider", "kind", "artifact_ref", "sha256", "expires_at", "exportable"}
)


class ContextSnapshotRepository(BaseRepository[ContextSnapshot]):
    def __init__(self, session: AsyncSession, tenant_id: int | None = None) -> None:
        super().__init__(session, ContextSnapshot, tenant_id=tenant_id)

    async def create(self, tenant_id: int, payload: dict[str, Any]) -> NoReturn:
        raise NotImplementedError(
            "ContextSnapshot rows are immutable. Use create_snapshot."
        )

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> NoReturn:
        raise NotImplementedError("ContextSnapshot rows are immutable. update is prohibited.")

    async def delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("ContextSnapshot rows are immutable. delete is prohibited.")

    def statement_for_update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> NoReturn:
        raise NotImplementedError(
            "ContextSnapshot rows are immutable. statement_for_update is prohibited."
        )

    def statement_for_delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError(
            "ContextSnapshot rows are immutable. statement_for_delete is prohibited."
        )

    async def create_snapshot(
        self,
        *,
        tenant_id: int,
        run_id: UUID,
        prompt_pack_version: str | None = None,
        prompt_pack_lock: str | None = None,
        policy_version: str | None = None,
        policy_pack_lock: str | None = None,
        repo_state: dict[str, Any] | None = None,
        tool_manifest: dict[str, Any] | None = None,
        evidence_set_reference: ResearchSetReference | None = None,
        inherit_evidence_set_hash_from_snapshot_id: UUID | None = None,
        provider_continuation_ref: dict[str, Any] | None = None,
        provider_request_fingerprint: dict[str, Any] | None = None,
        snapshot_kind: SnapshotKind | str | None = None,
    ) -> ContextSnapshot:
        self._require_tenant_id(tenant_id)
        if evidence_set_reference is not None and not isinstance(
            evidence_set_reference,
            ResearchSetReference,
        ):
            raise TypeError("evidence_set_reference must be ResearchSetReference or None.")
        # F-PR22-001 P2 adopt: ``inherit_evidence_set_hash_from_snapshot_id``
        # carries a prior server-emitted ``evidence_set_hash`` forward to
        # resume/repair snapshots without breaking server-owned-boundary §1.
        # The caller supplies only the prior ContextSnapshot.id (a UUID); the
        # hash itself is loaded from the DB row, so it remains
        # server-trusted by transitivity. Mutually exclusive with
        # ``evidence_set_reference``.
        if (
            evidence_set_reference is not None
            and inherit_evidence_set_hash_from_snapshot_id is not None
        ):
            raise ValueError(
                "evidence_set_reference and "
                "inherit_evidence_set_hash_from_snapshot_id are mutually exclusive."
            )
        # F-PR22-R2-007 P2 adopt: only resume snapshots may inherit a prior
        # ``evidence_set_hash``. input / pre_tool / post_tool / final
        # snapshots are paired with the currently active research binding
        # and must recompute the hash from the latest ResearchSetReference
        # (or fall back to the deterministic empty-set hash). Allowing
        # inheritance for non-resume kinds would let callers create new
        # snapshots that carry stale evidence bindings.
        if (
            inherit_evidence_set_hash_from_snapshot_id is not None
            and snapshot_kind != "resume"
        ):
            raise ValueError(
                "inherit_evidence_set_hash_from_snapshot_id is only valid "
                "for snapshot_kind='resume'."
            )

        self._assert_snapshot_contract(
            prompt_pack_version=prompt_pack_version,
            prompt_pack_lock=prompt_pack_lock,
            policy_version=policy_version,
            policy_pack_lock=policy_pack_lock,
            repo_state=repo_state,
            tool_manifest=tool_manifest,
            provider_continuation_ref=provider_continuation_ref,
            provider_request_fingerprint=provider_request_fingerprint,
            snapshot_kind=snapshot_kind,
        )
        await self._ensure_tenant_context(tenant_id)

        if evidence_set_reference is not None:
            run_project_id = await self._get_run_project_id(tenant_id, run_id)
            if run_project_id is None:
                raise ValueError("run_id does not belong to tenant_id.")
            if run_project_id != evidence_set_reference.project_id:
                raise ValueError(
                    "evidence_set_reference.project_id must match AgentRun.project_id."
                )

        if inherit_evidence_set_hash_from_snapshot_id is not None:
            evidence_set_hash = await self._inherit_evidence_set_hash(
                tenant_id,
                run_id,
                inherit_evidence_set_hash_from_snapshot_id,
            )
        else:
            evidence_set_hash = await compute_evidence_set_hash(
                self.session,
                tenant_id,
                evidence_set_reference,
            )

        # F-PR22-CI-001 P1 fix: SQLAlchemy serializes Python ``None`` to JSONB
        # ``'null'`` literal for nullable JSONB columns, which violates the
        # ``context_snapshots_ck_continuation_ref_required`` CHECK constraint
        # (it allows SQL NULL but rejects JSON null). Omit the column from the
        # ORM constructor when None so the DB default (SQL NULL) applies.
        snapshot_kwargs: dict[str, Any] = {
            "tenant_id": tenant_id,
            "run_id": run_id,
            "prompt_pack_version": cast(str, prompt_pack_version),
            "prompt_pack_lock": cast(str, prompt_pack_lock),
            "policy_version": cast(str, policy_version),
            "policy_pack_lock": cast(str, policy_pack_lock),
            "repo_state": cast(JsonDict, repo_state),
            "tool_manifest": cast(JsonDict, tool_manifest),
            "evidence_set_hash": evidence_set_hash,
            "provider_request_fingerprint": cast(JsonDict, provider_request_fingerprint),
            "snapshot_kind": cast(SnapshotKind, snapshot_kind),
        }
        if provider_continuation_ref is not None:
            snapshot_kwargs["provider_continuation_ref"] = provider_continuation_ref
        snapshot = ContextSnapshot(**snapshot_kwargs)
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    async def _get_run_project_id(self, tenant_id: int, run_id: UUID) -> UUID | None:
        return cast(
            UUID | None,
            await self.session.scalar(
                select(AgentRun.project_id).where(
                    AgentRun.tenant_id == tenant_id,
                    AgentRun.id == run_id,
                )
            ),
        )

    async def _inherit_evidence_set_hash(
        self,
        tenant_id: int,
        run_id: UUID,
        previous_snapshot_id: UUID,
    ) -> str:
        """Carry forward a server-emitted ``evidence_set_hash`` (F-PR22-001 P2).

        Reads the hash from a prior ``ContextSnapshot`` row scoped to
        ``(tenant_id, run_id)``. The DB CHECK ``^[0-9a-f]{64}$`` guarantees
        the value is a canonical sha256 hex. The caller supplies only the
        previous snapshot's UUID; this method does not accept caller-supplied
        hash material.
        """

        previous_hash = cast(
            str | None,
            await self.session.scalar(
                select(ContextSnapshot.evidence_set_hash).where(
                    ContextSnapshot.tenant_id == tenant_id,
                    ContextSnapshot.run_id == run_id,
                    ContextSnapshot.id == previous_snapshot_id,
                )
            ),
        )
        if previous_hash is None:
            raise ValueError(
                "inherit_evidence_set_hash_from_snapshot_id does not match a "
                "ContextSnapshot row in (tenant_id, run_id)."
            )
        return previous_hash

    @classmethod
    def _assert_snapshot_contract(
        cls,
        *,
        prompt_pack_version: str | None,
        prompt_pack_lock: str | None,
        policy_version: str | None,
        policy_pack_lock: str | None,
        repo_state: dict[str, Any] | None,
        tool_manifest: dict[str, Any] | None,
        provider_continuation_ref: dict[str, Any] | None,
        provider_request_fingerprint: dict[str, Any] | None,
        snapshot_kind: SnapshotKind | str | None,
    ) -> None:
        required_values: dict[str, object | None] = {
            "prompt_pack_version": prompt_pack_version,
            "prompt_pack_lock": prompt_pack_lock,
            "policy_version": policy_version,
            "policy_pack_lock": policy_pack_lock,
            "repo_state": repo_state,
            "tool_manifest": tool_manifest,
            "provider_request_fingerprint": provider_request_fingerprint,
            "snapshot_kind": snapshot_kind,
        }
        missing = [name for name, value in required_values.items() if value is None]
        if missing:
            raise ValueError(
                "ContextSnapshot required columns missing or null: "
                + ", ".join(missing)
            )

        if not isinstance(prompt_pack_version, str) or not prompt_pack_version.strip():
            raise ValueError("prompt_pack_version must be a non-empty string.")
        if not isinstance(policy_version, str) or not policy_version.strip():
            raise ValueError("policy_version must be a non-empty string.")

        assert_sha256_hex(cast(str, prompt_pack_lock), field_name="prompt_pack_lock")
        assert_sha256_hex(cast(str, policy_pack_lock), field_name="policy_pack_lock")

        if snapshot_kind not in ALL_SNAPSHOT_KINDS:
            raise ValueError(f"unknown snapshot_kind: {snapshot_kind!r}")

        cls._assert_json_object(
            repo_state,
            field_name="repo_state",
            required_keys=_REPO_STATE_REQUIRED_KEYS,
        )
        if not isinstance(cast(dict[str, Any], repo_state).get("dirty"), bool):
            raise ValueError("repo_state.dirty must be a bool.")

        cls._assert_json_object(
            tool_manifest,
            field_name="tool_manifest",
            required_keys=_TOOL_MANIFEST_REQUIRED_KEYS,
        )
        cls._assert_json_object(
            provider_request_fingerprint,
            field_name="provider_request_fingerprint",
            required_keys=_PROVIDER_REQUEST_FINGERPRINT_REQUIRED_KEYS,
        )

        cls._assert_provider_continuation_ref(provider_continuation_ref)

        assert_no_raw_secret(
            {
                "prompt_pack_version": prompt_pack_version,
                "prompt_pack_lock": prompt_pack_lock,
                "policy_version": policy_version,
                "policy_pack_lock": policy_pack_lock,
                "repo_state": repo_state,
                "tool_manifest": tool_manifest,
                "provider_continuation_ref": provider_continuation_ref,
                "provider_request_fingerprint": provider_request_fingerprint,
                "snapshot_kind": snapshot_kind,
            },
            path="$context_snapshot",
        )

    @staticmethod
    def _assert_json_object(
        value: dict[str, Any] | None,
        *,
        field_name: str,
        required_keys: frozenset[str],
    ) -> None:
        if not isinstance(value, dict):
            raise ValueError(f"{field_name} must be a JSON object.")
        missing = sorted(required_keys - set(value))
        if missing:
            raise ValueError(f"{field_name} missing required keys: {', '.join(missing)}")

    @staticmethod
    def _assert_provider_continuation_ref(ref: dict[str, Any] | None) -> None:
        """F-004 (R2): provider_continuation_ref の各 field を型・非空・timestamp 検証。"""

        if ref is None:
            return
        if not isinstance(ref, dict):
            raise ValueError("provider_continuation_ref must be dict or None")

        required = ("provider", "kind", "artifact_ref", "sha256", "expires_at", "exportable")
        missing = [key for key in required if key not in ref]
        if missing:
            raise ValueError(f"provider_continuation_ref missing keys: {missing}")

        for str_field in ("provider", "kind", "artifact_ref"):
            if not isinstance(ref[str_field], str) or not ref[str_field].strip():
                raise ValueError(
                    f"provider_continuation_ref.{str_field} must be non-empty str"
                )

        if not isinstance(ref["sha256"], str) or not re.fullmatch(
            r"[a-f0-9]{64}",
            ref["sha256"],
        ):
            raise ValueError("provider_continuation_ref.sha256 must be 64-char lowercase hex")

        if not isinstance(ref["expires_at"], str):
            raise ValueError("provider_continuation_ref.expires_at must be ISO 8601 string")
        try:
            datetime.fromisoformat(ref["expires_at"].replace("Z", "+00:00"))
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "provider_continuation_ref.expires_at not parseable as ISO 8601: "
                f"{ref['expires_at']!r}"
            ) from exc

        if ref["exportable"] is not False:
            raise ValueError(
                "provider_continuation_ref.exportable must be False "
                f"(got {ref['exportable']!r})"
            )


async def create_snapshot(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
    prompt_pack_version: str,
    prompt_pack_lock: str,
    policy_version: str,
    policy_pack_lock: str,
    repo_state: dict[str, Any],
    tool_manifest: dict[str, Any],
    evidence_set_reference: ResearchSetReference | None = None,
    inherit_evidence_set_hash_from_snapshot_id: UUID | None = None,
    provider_continuation_ref: dict[str, Any] | None,
    provider_request_fingerprint: dict[str, Any],
    snapshot_kind: SnapshotKind | str,
) -> ContextSnapshot:
    return await ContextSnapshotRepository(session).create_snapshot(
        tenant_id=tenant_id,
        run_id=run_id,
        prompt_pack_version=prompt_pack_version,
        prompt_pack_lock=prompt_pack_lock,
        policy_version=policy_version,
        policy_pack_lock=policy_pack_lock,
        repo_state=repo_state,
        tool_manifest=tool_manifest,
        evidence_set_reference=evidence_set_reference,
        inherit_evidence_set_hash_from_snapshot_id=inherit_evidence_set_hash_from_snapshot_id,
        provider_continuation_ref=provider_continuation_ref,
        provider_request_fingerprint=provider_request_fingerprint,
        snapshot_kind=snapshot_kind,
    )


__all__ = [
    "CONTEXT_SNAPSHOT_REQUIRED_COLUMNS",
    "ContextSnapshotRepository",
    "_PROHIBITED_PAYLOAD_KEYS",
    "_RAW_SECRET_PATTERNS",
    "assert_no_raw_secret",
    "create_snapshot",
]
