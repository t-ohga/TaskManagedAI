"""ADR-00050 SP-028: verification 後の best-effort webhook event enrichment。

`GitHubWebhookVerifier` が accepted を返した **後** にのみ呼ばれ、PR / CI イベントの非機密 field のみを
`github_webhook_events` に保存する。既存 ingress security contract (verifier / secret resolver /
replay store) は一切変更しない。失敗しても verification 応答を巻き戻さない (best-effort、R2 F-005)。

処理段階 (ADR-00050 §payload 処理):
1. event_kind header が追跡対象 5 種でなければ skip (issues 等は記録しない、error ではない)。
2. body を JSON parse → 不正なら `parse_validation_failed` quarantine。
3. event_kind 別 shape 検証 → 期待 key 欠落なら `payload_shape_mismatch` quarantine。
4. allowlist field 抽出 + **値レベル redaction** (raw-secret/canary scan → drop、NFC + control 除去 + 長さ bound)。
5. repository を `(tenant_id, 'github', str(repository.id))` で解決 (installation_ref 一致は要求しない、共有
   p0 webhook secret のため)。0 件 → `unregistered_repo` quarantine、複数 → `repo_lookup_ambiguous`。
6. `(tenant_id, delivery_id)` unique で dedup insert。conflict 時 payload_hash 比較: 一致は idempotent、
   不一致は audit anomaly のみ (quarantine row は unique 衝突回避のため作らない、R2 F-003)。
"""

from __future__ import annotations

import json
import logging
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.github_webhook_event import (
    ACTION_MAX_LENGTH,
    DELIVERY_ID_MAX_LENGTH,
    EXTERNAL_REF_MAX_LENGTH,
    SENDER_LOGIN_MAX_LENGTH,
    STATE_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    WEBHOOK_EVENT_KINDS,
    GitHubWebhookEvent,
    WebhookEventKind,
    WebhookQuarantineReason,
)
from backend.app.db.models.repository import Repository
from backend.app.repositories._payload_secret_scan import _RAW_SECRET_PATTERNS

logger = logging.getLogger(__name__)

WEBHOOK_DELIVERY_HASH_MISMATCH_AUDIT_EVENT_TYPE = "github_webhook_delivery_hash_mismatch"

_EVENT_KINDS: frozenset[str] = frozenset(WEBHOOK_EVENT_KINDS)
_MAX_PERSIST_ATTEMPTS = 2


def _strip_invisible(value: str) -> str:
    """全 Unicode control (Cc) + format (Cf) 文字を除去する。

    Codex adversarial F-2: zero-width 文字 (U+200B/U+200C/U+200D/U+FEFF 等、category Cf) で secret
    token を分断すると、contiguous な ``_RAW_SECRET_PATTERNS`` を回避して redaction を擦り抜ける。
    Cc (C0/C1 control) + Cf (format / bidi / zero-width) を一括除去してから scan することで、不可視
    文字による token 分断 bypass を塞ぐ (bidi / 制御文字 injection 防止も兼ねる)。
    """

    return "".join(ch for ch in value if unicodedata.category(ch) not in ("Cc", "Cf"))


@dataclass(frozen=True, slots=True)
class WebhookEventOutcome:
    """parse + persist の結果。endpoint は status に関わらず 202 を返す (best-effort)。"""

    status: str  # accepted | quarantined | idempotent | anomaly | skipped | persist_failed
    event_id: UUID | None = None
    quarantine_reason: str | None = None


@dataclass(frozen=True, slots=True)
class _ExtractedFields:
    action: str | None
    external_ref: str | None
    state: str | None
    title: str | None
    sender_login: str | None
    repo_external_id: str | None


async def record_webhook_event(
    session: AsyncSession,
    *,
    tenant_id: int,
    installation_id: int,
    delivery_id: str,
    event_kind_header: str | None,
    payload: bytes,
    payload_hash: str,
) -> WebhookEventOutcome:
    """verification accepted 後に webhook event を best-effort で記録する。

    例外を endpoint へ伝播させない (best-effort)。transient persist 失敗は bounded retry 後に log +
    ``persist_failed`` を返し、verification 応答は巻き戻さない (R2 F-005)。
    """

    kind = (event_kind_header or "").strip()
    if kind not in _EVENT_KINDS:
        # 追跡対象外 (issues / ping 等)。error ではなく単に記録しない。
        return WebhookEventOutcome(status="skipped")
    event_kind: WebhookEventKind = kind  # type: ignore[assignment]  # _EVENT_KINDS で絞り込み済

    if not delivery_id or len(delivery_id) > DELIVERY_ID_MAX_LENGTH:
        # delivery_id は verifier で検証済だが、長さ bound (DB CHECK と同値) を defense-in-depth で確認。
        return WebhookEventOutcome(status="skipped")

    parsed = _parse_body(payload)
    if parsed is None:
        return await _persist(
            session,
            tenant_id=tenant_id,
            delivery_id=delivery_id,
            payload_hash=payload_hash,
            event_kind=event_kind,
            installation_id=installation_id,
            status="quarantined",
            repository_id=None,
            quarantine_reason="parse_validation_failed",
            fields=None,
        )

    extracted = _extract_fields(event_kind, parsed)
    if extracted is None:
        return await _persist(
            session,
            tenant_id=tenant_id,
            delivery_id=delivery_id,
            payload_hash=payload_hash,
            event_kind=event_kind,
            installation_id=installation_id,
            status="quarantined",
            repository_id=None,
            quarantine_reason="payload_shape_mismatch",
            fields=None,
        )

    repository_id, repo_reason = await _resolve_repository(
        session, tenant_id=tenant_id, external_id=extracted.repo_external_id
    )
    if repo_reason is not None:
        return await _persist(
            session,
            tenant_id=tenant_id,
            delivery_id=delivery_id,
            payload_hash=payload_hash,
            event_kind=event_kind,
            installation_id=installation_id,
            status="quarantined",
            repository_id=None,
            quarantine_reason=repo_reason,
            fields=extracted,
        )

    return await _persist(
        session,
        tenant_id=tenant_id,
        delivery_id=delivery_id,
        payload_hash=payload_hash,
        event_kind=event_kind,
        installation_id=installation_id,
        status="accepted",
        repository_id=repository_id,
        quarantine_reason=None,
        fields=extracted,
    )


def _parse_body(payload: bytes) -> dict[str, Any] | None:
    try:
        decoded: Any = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    return decoded


def _extract_fields(event_kind: WebhookEventKind, body: dict[str, Any]) -> _ExtractedFields | None:
    """event_kind 別に allowlist field を抽出。期待 shape を満たさなければ None (shape mismatch)。"""

    repo_external_id = _clean(_repo_external_id(body), EXTERNAL_REF_MAX_LENGTH)
    sender_login = _clean(_sender_login(body), SENDER_LOGIN_MAX_LENGTH)
    action = _clean(_str_or_none(body.get("action")), ACTION_MAX_LENGTH)

    if event_kind == "pull_request":
        pr = body.get("pull_request")
        if not isinstance(pr, dict):
            return None
        merged = pr.get("merged") is True
        state = "merged" if merged else _str_or_none(pr.get("state"))
        return _ExtractedFields(
            action=action,
            external_ref=_clean(_str_or_none(pr.get("number")), EXTERNAL_REF_MAX_LENGTH),
            state=_clean(state, STATE_MAX_LENGTH),
            title=_clean(_str_or_none(pr.get("title")), TITLE_MAX_LENGTH),
            sender_login=sender_login,
            repo_external_id=repo_external_id,
        )
    if event_kind in ("check_run", "check_suite"):
        wrapper = body.get(event_kind)
        if not isinstance(wrapper, dict):
            return None
        conclusion = _str_or_none(wrapper.get("conclusion"))
        state = conclusion if conclusion is not None else _str_or_none(wrapper.get("status"))
        return _ExtractedFields(
            action=action,
            external_ref=_clean(_str_or_none(wrapper.get("head_sha")), EXTERNAL_REF_MAX_LENGTH),
            state=_clean(state, STATE_MAX_LENGTH),
            title=None,
            sender_login=sender_login,
            repo_external_id=repo_external_id,
        )
    if event_kind == "status":
        state = _str_or_none(body.get("state"))
        sha = _str_or_none(body.get("sha"))
        if state is None or sha is None:
            return None
        return _ExtractedFields(
            action=None,
            external_ref=_clean(sha, EXTERNAL_REF_MAX_LENGTH),
            state=_clean(state, STATE_MAX_LENGTH),
            title=_clean(_str_or_none(body.get("context")), TITLE_MAX_LENGTH),
            sender_login=sender_login,
            repo_external_id=repo_external_id,
        )
    # push
    ref = _str_or_none(body.get("ref"))
    if ref is None:
        return None
    return _ExtractedFields(
        action=None,
        external_ref=_clean(_str_or_none(body.get("after")), EXTERNAL_REF_MAX_LENGTH),
        state=None,
        title=_clean(ref, TITLE_MAX_LENGTH),
        sender_login=sender_login,
        repo_external_id=repo_external_id,
    )


def _repo_external_id(body: dict[str, Any]) -> str | None:
    repository = body.get("repository")
    if not isinstance(repository, dict):
        return None
    repo_id = repository.get("id")
    if isinstance(repo_id, bool) or not isinstance(repo_id, int):
        return None
    return str(repo_id)


def _sender_login(body: dict[str, Any]) -> str | None:
    sender = body.get("sender")
    if not isinstance(sender, dict):
        return None
    return _str_or_none(sender.get("login"))


def _str_or_none(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    return None


def _clean(value: str | None, max_length: int) -> str | None:
    """値レベル redaction (R1 F-Q3 / F-007): secret-shaped 値は drop、NFC + control 除去 + 長さ bound。"""

    if value is None:
        return None
    # NFC 正規化 → 不可視文字 (Cc/Cf、zero-width 含む) を除去してから secret scan する。
    # 除去を scan の前に行うことで zero-width 分断 bypass を塞ぐ (Codex adversarial F-2)。
    normalized = _strip_invisible(unicodedata.normalize("NFC", value)).strip()
    if not normalized:
        return None
    for _kind, regex in _RAW_SECRET_PATTERNS:
        if regex.search(normalized):
            # secret-shaped token が allowlist field の値に混入 → 当該 field を drop (保存しない)。
            return None
    if len(normalized) > max_length:
        normalized = normalized[:max_length]
    return normalized or None


async def _resolve_repository(
    session: AsyncSession,
    *,
    tenant_id: int,
    external_id: str | None,
) -> tuple[UUID | None, WebhookQuarantineReason | None]:
    """`(tenant_id, 'github', external_id)` で repository を解決。(repository_id, quarantine_reason)。"""

    if external_id is None:
        return None, "unregistered_repo"
    rows = (
        await session.execute(
            select(Repository.id).where(
                Repository.tenant_id == tenant_id,
                Repository.provider == "github",
                Repository.external_id == external_id,
            )
        )
    ).scalars().all()
    if len(rows) == 0:
        return None, "unregistered_repo"
    if len(rows) > 1:
        # (tenant_id, provider, external_id) unique のため通常発生しないが defensive。
        return None, "repo_lookup_ambiguous"
    return rows[0], None


async def _persist(
    session: AsyncSession,
    *,
    tenant_id: int,
    delivery_id: str,
    payload_hash: str,
    event_kind: WebhookEventKind,
    installation_id: int,
    status: str,
    repository_id: UUID | None,
    quarantine_reason: WebhookQuarantineReason | None,
    fields: _ExtractedFields | None,
) -> WebhookEventOutcome:
    """dedup insert を bounded retry 付きで実行 (best-effort、例外は呼び元へ伝播しない)。"""

    values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "repository_id": repository_id,
        "delivery_id": delivery_id,
        "payload_hash": payload_hash,
        "event_kind": event_kind,
        "status": status,
        "quarantine_reason": quarantine_reason,
        "action": fields.action if fields else None,
        "external_ref": fields.external_ref if fields else None,
        "state": fields.state if fields else None,
        "title": fields.title if fields else None,
        "sender_login": fields.sender_login if fields else None,
        "received_at": datetime.now(UTC),
    }

    last_exc: Exception | None = None
    for _attempt in range(_MAX_PERSIST_ATTEMPTS):
        try:
            return await _insert_or_dedup(
                session,
                tenant_id=tenant_id,
                delivery_id=delivery_id,
                payload_hash=payload_hash,
                event_kind=event_kind,
                installation_id=installation_id,
                status=status,
                quarantine_reason=quarantine_reason,
                values=values,
            )
        except SQLAlchemyError as exc:  # transient DB 障害 (timeout / connection 等)
            last_exc = exc
            await _safe_rollback(session)
    # bounded retry でも回復せず: best-effort なので raw payload なしで log し 202 を返す。
    logger.warning(
        "github webhook event persist failed after retries: "
        "tenant_id=%s delivery_id_present=%s event_kind=%s error=%s",
        tenant_id,
        bool(delivery_id),
        event_kind,
        type(last_exc).__name__ if last_exc is not None else "unknown",
    )
    return WebhookEventOutcome(status="persist_failed")


async def _insert_or_dedup(
    session: AsyncSession,
    *,
    tenant_id: int,
    delivery_id: str,
    payload_hash: str,
    event_kind: WebhookEventKind,
    installation_id: int,
    status: str,
    quarantine_reason: WebhookQuarantineReason | None,
    values: dict[str, Any],
) -> WebhookEventOutcome:
    insert_stmt = (
        pg_insert(GitHubWebhookEvent)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["tenant_id", "delivery_id"])
        .returning(GitHubWebhookEvent.id)
    )
    inserted_id = (await session.execute(insert_stmt)).scalar_one_or_none()
    if inserted_id is not None:
        await session.commit()
        outcome_status = "accepted" if status == "accepted" else "quarantined"
        return WebhookEventOutcome(
            status=outcome_status,
            event_id=inserted_id,
            quarantine_reason=quarantine_reason,
        )

    # conflict: 既存 row の payload_hash と比較 (R2 F-002/F-003)。
    existing_hash = (
        await session.execute(
            select(GitHubWebhookEvent.payload_hash).where(
                GitHubWebhookEvent.tenant_id == tenant_id,
                GitHubWebhookEvent.delivery_id == delivery_id,
            )
        )
    ).scalar_one_or_none()
    if existing_hash == payload_hash:
        await session.commit()
        return WebhookEventOutcome(status="idempotent")

    # 同一 delivery_id で別 body = security anomaly。既存 row は保持し audit anomaly のみ (row 追加なし)。
    await _append_anomaly_audit(
        session,
        tenant_id=tenant_id,
        delivery_id=delivery_id,
        event_kind=event_kind,
        installation_id=installation_id,
        new_payload_hash=payload_hash,
        existing_payload_hash=existing_hash,
    )
    await session.commit()
    return WebhookEventOutcome(status="anomaly")


async def _append_anomaly_audit(
    session: AsyncSession,
    *,
    tenant_id: int,
    delivery_id: str,
    event_kind: WebhookEventKind,
    installation_id: int,
    new_payload_hash: str,
    existing_payload_hash: str | None,
) -> None:
    # 遅延 import で循環 import を避ける (audit repository は多数の model を import する)。
    from backend.app.repositories.audit_event import AuditEventRepository

    await AuditEventRepository(session).append(
        tenant_id=tenant_id,
        event_type=WEBHOOK_DELIVERY_HASH_MISMATCH_AUDIT_EVENT_TYPE,
        payload={
            "reason_code": "delivery_payload_hash_mismatch",
            "redacted": True,
            "tenant_id": tenant_id,
            "installation_id": installation_id,
            "event_kind": event_kind,
            "delivery_id_hash": _delivery_id_hash(delivery_id),
            "new_payload_hash_prefix": new_payload_hash[:16],
            "existing_payload_hash_prefix": (
                existing_payload_hash[:16] if existing_payload_hash is not None else None
            ),
        },
    )


def _delivery_id_hash(delivery_id: str) -> str:
    import hashlib

    return hashlib.sha256(delivery_id.encode("utf-8")).hexdigest()


async def _safe_rollback(session: AsyncSession) -> None:
    try:
        await session.rollback()
    except SQLAlchemyError:  # pragma: no cover - rollback 失敗は best-effort なので握る
        logger.warning("github webhook event session rollback failed")


__all__ = [
    "WEBHOOK_DELIVERY_HASH_MISMATCH_AUDIT_EVENT_TYPE",
    "WebhookEventOutcome",
    "record_webhook_event",
]
