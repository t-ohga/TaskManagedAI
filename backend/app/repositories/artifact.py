from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from typing import Any, NamedTuple, NoReturn, cast
from uuid import UUID

from sqlalchemy import and_, case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.artifact import ALL_ARTIFACT_KINDS, Artifact, ArtifactKind
from backend.app.domain.agent_runtime.active_scope import (
    soft_deleted_ticket_run_exclusion,
)
from backend.app.domain.artifact.data_class import (
    ALL_PAYLOAD_DATA_CLASSES,
    PayloadDataClass,
)
from backend.app.repositories._payload_secret_scan import (
    _PROHIBITED_PAYLOAD_KEYS,
    _RAW_SECRET_PATTERNS,
    assert_no_raw_secret,
)
from backend.app.repositories.base import BaseRepository

_SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")

# ADR-00042: provider_continuation_ref は内部 continuation 参照 (ContextSnapshot UI 非露出 rule)。
# L-2 inventory からは child としても parent lineage としても除外する。
_PROVIDER_CONTINUATION_REF_KIND = "provider_continuation_ref"


class RunArtifactRow(NamedTuple):
    """ADR-00042 L-2: run artifact inventory の metadata-only 行 (content / content_hash なし)。"""

    id: UUID
    kind: str
    payload_data_class: str
    trust_level: str
    exportable: bool
    parent_artifact_id: UUID | None
    created_at: datetime


def is_sha256_hex(value: str) -> bool:
    return isinstance(value, str) and _SHA256_HEX_PATTERN.fullmatch(value) is not None


def assert_sha256_hex(value: str, *, field_name: str) -> None:
    if not is_sha256_hex(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 64 hex string.")


def _payload_child_path(path: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]"
    if key.isidentifier():
        return f"{path}.{key}"
    return f"{path}[{key!r}]"


def _normalize_json_for_hash(
    obj: object,
    *,
    path: str = "$",
    _seen: set[int] | None = None,
) -> object:
    if _seen is None:
        _seen = set()

    if isinstance(obj, dict):
        oid = id(obj)
        if oid in _seen:
            raise ValueError(f"artifact content_jsonb has cyclic reference at {path}.")
        _seen.add(oid)

        normalized: dict[str, object] = {}
        for key, value in obj.items():
            if not isinstance(key, str):
                raise ValueError(
                    f"artifact content_jsonb contains non-string key at {path}."
                )
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise ValueError(
                    "artifact content_jsonb contains duplicate keys after NFC "
                    f"normalization at {path}."
                )
            normalized[normalized_key] = _normalize_json_for_hash(
                value,
                path=_payload_child_path(path, key),
                _seen=_seen,
            )

        _seen.discard(oid)
        return normalized

    if isinstance(obj, list):
        oid = id(obj)
        if oid in _seen:
            raise ValueError(f"artifact content_jsonb has cyclic reference at {path}.")
        _seen.add(oid)

        normalized_list = [
            _normalize_json_for_hash(
                item,
                path=_payload_child_path(path, index),
                _seen=_seen,
            )
            for index, item in enumerate(obj)
        ]
        _seen.discard(oid)
        return normalized_list

    if isinstance(obj, tuple):
        return [
            _normalize_json_for_hash(
                item,
                path=_payload_child_path(path, index),
                _seen=_seen,
            )
            for index, item in enumerate(obj)
        ]

    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)

    if obj is None or isinstance(obj, (bool, int, float)):
        return obj

    raise ValueError(
        f"artifact content_jsonb contains unsupported JSON value at {path}: "
        f"{type(obj).__name__}"
    )


def canonical_json_for_hash(content_jsonb: dict[str, Any]) -> str:
    if not isinstance(content_jsonb, dict):
        raise ValueError("artifact content_jsonb must be a JSON object.")

    normalized = _normalize_json_for_hash(content_jsonb)
    try:
        canonical = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("artifact content_jsonb must be valid canonical JSON.") from exc

    return unicodedata.normalize("NFC", canonical)


def calculate_content_hash(content_jsonb: dict[str, Any]) -> str:
    canonical = canonical_json_for_hash(content_jsonb)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_content_hash(content_jsonb: dict[str, Any]) -> str:
    return calculate_content_hash(content_jsonb)


class ArtifactRepository(BaseRepository[Artifact]):
    def __init__(self, session: AsyncSession, tenant_id: int | None = None) -> None:
        super().__init__(session, Artifact, tenant_id=tenant_id)

    async def create(self, tenant_id: int, payload: dict[str, Any]) -> NoReturn:
        raise NotImplementedError(
            "Artifact rows are immutable. Use create_artifact with hash verification."
        )

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> NoReturn:
        raise NotImplementedError("Artifact rows are immutable. update is prohibited.")

    async def delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Artifact rows are immutable. delete is prohibited.")

    def statement_for_update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> NoReturn:
        raise NotImplementedError(
            "Artifact rows are immutable. statement_for_update is prohibited."
        )

    def statement_for_delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError(
            "Artifact rows are immutable. statement_for_delete is prohibited."
        )

    async def create_artifact(
        self,
        *,
        tenant_id: int,
        run_id: UUID,
        kind: ArtifactKind | str,
        content_hash: str,
        content_jsonb: dict[str, Any],
        payload_data_class: PayloadDataClass | str,
        exportable: bool = True,
        parent_artifact_id: UUID | None = None,
        project_id: UUID | None = None,  # NOT NULL in DB (migration 0019) but optional in API for backward compat
    ) -> Artifact:
        self._require_tenant_id(tenant_id)
        self._assert_artifact_contract(
            kind=kind,
            content_hash=content_hash,
            content_jsonb=content_jsonb,
            payload_data_class=payload_data_class,
            exportable=exportable,
        )
        await self._ensure_tenant_context(tenant_id)

        artifact = Artifact(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            kind=cast(ArtifactKind, kind),
            content_hash=content_hash,
            content_jsonb=content_jsonb,
            payload_data_class=cast(PayloadDataClass, payload_data_class),
            exportable=exportable,
            parent_artifact_id=parent_artifact_id,
        )
        self.session.add(artifact)
        await self.session.flush()
        return artifact

    async def list_run_artifacts(
        self, tenant_id: int, run_id: UUID
    ) -> list[RunArtifactRow] | None:
        """ADR-00042 L-2: run の artifact metadata 一覧 (metadata-only、content/hash 非 fetch)。

        `agent_runs` 起点の active-scope SELECT に `LEFT JOIN artifacts` し、**run 可視性と
        artifact 集約を同一 statement** で行う (TOCTOU / 将来再利用でも fail-closed):

        - run 行が無い (不存在 / tenant 外 / soft-deleted ticket bound) → ``None`` (呼出側 404)。
        - run 行あり + artifact 0 件 → 空 list (200 empty)。
        - run 行あり + artifact → metadata 行 list。

        `provider_continuation_ref` は child としても parent lineage としても除外 (ContextSnapshot
        UI 非露出 rule)。`parent_artifact_id` は parent が可視種別のときだけ返す (除外 ref の UUID /
        lineage を child 経由で漏らさない)。`content_jsonb` / `content_hash` は SELECT しない。
        """
        await self._ensure_tenant_context(tenant_id)

        a = aliased(Artifact, name="a")
        pa = aliased(Artifact, name="pa")
        stmt = (
            select(
                AgentRun.id.label("run_id"),
                a.id.label("artifact_id"),
                a.kind.label("kind"),
                a.payload_data_class.label("payload_data_class"),
                a.trust_level.label("trust_level"),
                a.exportable.label("exportable"),
                a.created_at.label("created_at"),
                case(
                    (pa.id.is_not(None), a.parent_artifact_id),
                    else_=None,
                ).label("parent_artifact_id"),
            )
            .select_from(AgentRun)
            .join(
                a,
                and_(
                    a.tenant_id == AgentRun.tenant_id,
                    a.project_id == AgentRun.project_id,
                    a.run_id == AgentRun.id,
                    a.kind != _PROVIDER_CONTINUATION_REF_KIND,
                ),
                isouter=True,
            )
            .join(
                pa,
                and_(
                    pa.tenant_id == a.tenant_id,
                    pa.project_id == a.project_id,
                    pa.run_id == a.run_id,
                    pa.id == a.parent_artifact_id,
                    pa.kind != _PROVIDER_CONTINUATION_REF_KIND,
                ),
                isouter=True,
            )
            .where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.id == run_id,
                soft_deleted_ticket_run_exclusion(),
            )
            .order_by(a.created_at, a.id)
        )
        result = await self.session.execute(stmt)
        rows = result.all()
        if not rows:
            # run 行が無い = run 不可視 (404)。run 可視 + artifact 0 件は 1 行 (artifact null) が返る。
            return None
        return [
            RunArtifactRow(
                id=row.artifact_id,
                kind=row.kind,
                payload_data_class=row.payload_data_class,
                trust_level=row.trust_level,
                exportable=row.exportable,
                parent_artifact_id=row.parent_artifact_id,
                created_at=row.created_at,
            )
            for row in rows
            if row.artifact_id is not None
        ]

    @classmethod
    def _assert_artifact_contract(
        cls,
        *,
        kind: ArtifactKind | str,
        content_hash: str,
        content_jsonb: dict[str, Any],
        payload_data_class: PayloadDataClass | str,
        exportable: bool,
    ) -> None:
        if kind not in ALL_ARTIFACT_KINDS:
            raise ValueError(f"unknown artifact kind: {kind!r}")
        if payload_data_class not in ALL_PAYLOAD_DATA_CLASSES:
            raise ValueError(f"unknown payload_data_class: {payload_data_class!r}")
        if not isinstance(exportable, bool):
            raise ValueError("artifact exportable must be a bool.")
        if kind == "provider_continuation_ref" and exportable:
            raise ValueError("provider_continuation_ref artifacts must be exportable=false.")
        if not isinstance(content_jsonb, dict):
            raise ValueError("artifact content_jsonb must be a JSON object.")

        assert_sha256_hex(content_hash, field_name="content_hash")
        assert_no_raw_secret(content_jsonb, path="$artifact.content_jsonb")

        recalculated_hash = calculate_content_hash(content_jsonb)
        if recalculated_hash != content_hash:
            raise ValueError(
                "artifact content_hash mismatch: provided hash does not match "
                "NFC UTF-8 canonical JSON SHA-256."
            )


async def create_artifact(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
    kind: ArtifactKind | str,
    content_hash: str,
    content_jsonb: dict[str, Any],
    payload_data_class: PayloadDataClass | str,
    exportable: bool = True,
    parent_artifact_id: UUID | None = None,
) -> Artifact:
    return await ArtifactRepository(session).create_artifact(
        tenant_id=tenant_id,
        run_id=run_id,
        kind=kind,
        content_hash=content_hash,
        content_jsonb=content_jsonb,
        payload_data_class=payload_data_class,
        exportable=exportable,
        parent_artifact_id=parent_artifact_id,
    )


__all__ = [
    "ArtifactRepository",
    "_PROHIBITED_PAYLOAD_KEYS",
    "_RAW_SECRET_PATTERNS",
    "assert_no_raw_secret",
    "assert_sha256_hex",
    "calculate_content_hash",
    "canonical_json_for_hash",
    "compute_content_hash",
    "create_artifact",
    "is_sha256_hex",
]

