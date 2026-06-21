"""L3: DB mutation boundary active-registry gate (§9.10 R10 F-001).

SQLAlchemy session の `before_commit` event に attach し、commit 直前に
local host の active marker + freeze/decommission + fleet membership を
fail-closed verify する。

invariants:
- gate fail → commit を `IntegrityError` で abort + transaction rollback
- read-only transactions (`session.is_modified()` で mutation 検出) は skip
  (audit log read など read-only commit を不要に block しないため)
- service layer 内の direct mutation は SQLAlchemy session を経由するため
  本 listener で全件捕捉される (L1 FastAPI dependency + L2 worker gate を補完)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from scripts import taskhub_active_registry_gate as gate_helper

logger = logging.getLogger(__name__)

GATE_KIND_DB_COMMIT: str = "db_commit"


@dataclass(frozen=True, slots=True)
class DbGateConfig:
    """DB mutation gate 設定 (session factory に attach される)。"""

    config_dir: Path
    host_id: str
    public_key_resolver: Callable[[str], bytes | None]


class ActiveRegistryGateRejectedCommit(IntegrityError):
    """active-registry gate が commit を reject したことを示す `IntegrityError` サブクラス。

    `IntegrityError` を継承することで、既存の SQLAlchemy error handling
    (`Session.rollback()` 自動発火、ORM レイヤの transaction abort) に乗る。
    """

    def __init__(self, reason_code: str) -> None:
        message = (
            "active-registry gate rejected commit: "
            f"reason_code={reason_code}"
        )
        # IntegrityError(statement, params, orig)
        super().__init__(message, None, Exception(reason_code))
        self.reason_code = reason_code


_DML_EXECUTED_KEY: str = "_active_registry_dml_executed"

# ADR-00048 §A-3: emergency-stop engage/clear の DB 書込は **host-freeze DML mutation gate に
# 阻まれてはならない** (安全機能 = 全停止が host freeze 状態に左右されない)。emergency-stop service
# が commit する session に本 flag を立て、gate の before_commit listener は flag 検出時に bypass する。
# managed_agents supervision (cross-process kill) とは別責務 (A-3): freeze gate は host-fleet DML
# mutation gate であり、emergency-stop は安全弁。安全弁の書込が freeze で詰むのは fail-open の逆 = 危険。
_EMERGENCY_STOP_BYPASS_KEY: str = "_emergency_stop_gate_bypass"


# ADR-00048 §A-3 (LOW-2): bypass の blast radius を構造的に閉じる。bypass-flagged session の
# ORM-tracked mutation は emergency-stop 関連 model のみ許可し、無関係 model 混入なら fail-closed で
# reject する (whole-commit scope のまま無制限に exempt しない)。
#
# 限界 (honest): emergency-stop service の AgentRun status reset / AgentRunEvent append は
# statement-based DML (`execute(update/insert)`) で session.new/dirty/deleted に現れないため、本 guard は
# ORM-tracked instance (session.add した SuperintendentEmergencyStop / AuditEvent) のみを検査する。
# statement-based DML は freeze gate からも bypass されるが、emergency-stop service の tenant-scoped な
# AgentRun/AgentRunEvent 限定 update であり、本 guard は「無関係な ORM model を session.add した状態で
# bypass commit する」誤用を構造的に弾く目的 (主防御は service 単独使用 + per-request fresh session)。
_EMERGENCY_STOP_BYPASS_ALLOWED_MODELS: frozenset[str] = frozenset(
    {
        "SuperintendentEmergencyStop",
        "AuditEvent",
        "AgentRun",
        "AgentRunEvent",
    }
)


class EmergencyStopBypassScopeViolation(IntegrityError):
    """A-3 bypass session に emergency-stop 無関係の ORM mutation が混入した (fail-closed)。

    ``IntegrityError`` を継承し既存 SQLAlchemy rollback handling に乗せる (gate reject と同様)。
    """

    def __init__(self, model_name: str) -> None:
        message = (
            "emergency-stop gate bypass rejected: unrelated ORM mutation in bypassed "
            f"commit (model={model_name})"
        )
        super().__init__(message, None, Exception("emergency_stop_bypass_scope_violation"))


def mark_emergency_stop_bypass(session: AsyncSession | Session) -> None:
    """ADR-00048 §A-3: 本 session の commit を active-registry freeze gate から exempt する。

    emergency-stop engage/clear の service が呼ぶ。本 flag を立てた session の commit は
    ``before_commit`` listener (sync ``Session`` を受け取る) で gate 評価を skip する (freeze 状態でも
    emergency-stop の latch 書込 / run block-resume を必ず永続化する)。本 flag は emergency-stop service
    のみが立てる (一般 mutation 経路からは到達しない private helper)。

    LOW-2: bypass は **whole-commit scope** だが、``before_commit`` で bypass-flagged session の
    ORM-tracked instance を allowlist (``_EMERGENCY_STOP_BYPASS_ALLOWED_MODELS``) に照合し、無関係
    model 混入なら ``EmergencyStopBypassScopeViolation`` で fail-closed reject する (blast radius を閉じる)。

    ``AsyncSession`` の場合は内部の sync ``Session`` (``before_commit`` listener が見るのと同一 instance)
    の ``info`` dict に flag を立てる (両者は同じ dict を共有する)。
    """
    sync_session = session.sync_session if isinstance(session, AsyncSession) else session
    sync_session.info[_EMERGENCY_STOP_BYPASS_KEY] = True


def _assert_emergency_stop_bypass_scope(session: Session) -> None:
    """bypass-flagged commit の ORM-tracked mutation が emergency-stop 関連 model のみか確認 (LOW-2)。

    無関係 model が session.new/dirty/deleted に乗っていれば fail-closed で reject する。
    """
    for instance in (*session.new, *session.dirty, *session.deleted):
        model_name = type(instance).__name__
        if model_name not in _EMERGENCY_STOP_BYPASS_ALLOWED_MODELS:
            raise EmergencyStopBypassScopeViolation(model_name)


def _session_has_mutations(session: Session) -> bool:
    """session に pending INSERT/UPDATE/DELETE が含まれているかを確認。

    Codex PR #85 R1 F-005 fix (P2): `session.dirty` は optimistic で、column
    に同値を再代入しただけでも entry が乗ることがある (SQLAlchemy 公式 docs)。
    `is_modified()` で net column change を per-instance に確認することで
    read-only / no-op commit を gate から確実に exempt する。

    Codex PR #85 R2 F-R2-006 fix (P1): SQL `execute(update(...))` /
    `execute(delete(...))` などの statement-based DML は session.new / dirty /
    deleted に entry を作らない (`backend/app/repositories/base.py` 経由)。
    `do_orm_execute` listener で session.info に `_DML_EXECUTED_KEY` を set
    することで、これらの DML も mutation として確実に detect する。
    """
    if session.info.get(_DML_EXECUTED_KEY, False):
        return True
    if session.new or session.deleted:
        return True
    # `session.dirty` の各 instance に対し net change を確認
    for instance in session.dirty:
        try:
            if session.is_modified(instance, include_collections=True):
                return True
        except Exception:  # noqa: BLE001 - 検査失敗時は fail-closed (mutation あり扱い)
            return True
    return False


def _on_orm_execute(orm_execute_state: object) -> None:
    """SQLAlchemy `do_orm_execute` listener: UPDATE/DELETE/INSERT 検出時に flag set。

    Codex PR #85 R2 F-R2-006 fix (P1): statement-based DML (Core-level execute) を
    capture するため、ORM execute event hook で is_update / is_delete / is_insert
    属性を確認し、該当 session.info に flag を set する。
    """
    is_update = bool(getattr(orm_execute_state, "is_update", False))
    is_delete = bool(getattr(orm_execute_state, "is_delete", False))
    is_insert = bool(getattr(orm_execute_state, "is_insert", False))
    if is_update or is_delete or is_insert:
        session = getattr(orm_execute_state, "session", None)
        if session is not None:
            session.info[_DML_EXECUTED_KEY] = True


def _on_before_flush(
    session: Session, flush_context: object, instances: object
) -> None:
    """SQLAlchemy `before_flush` listener: ORM 経由 mutation を flush 直前に capture。

    Codex PR #85 R3 F-R3-002 fix (P1): autoflush / explicit flush() でも
    session.new / deleted / dirty が clear される前に flag を set する。
    `before_commit` は autoflush 後に発火する可能性があるため、本 listener が
    最初に拾うことで commit-time の gate check で漏れなく mutation を検出する。
    """
    _ = flush_context, instances  # SQLAlchemy event signature 整合のため
    if session.new or session.deleted:
        session.info[_DML_EXECUTED_KEY] = True
        return
    for instance in session.dirty:
        try:
            if session.is_modified(instance, include_collections=True):
                session.info[_DML_EXECUTED_KEY] = True
                return
        except Exception:  # noqa: BLE001 - 検査失敗時は fail-closed (mutation 扱い)
            session.info[_DML_EXECUTED_KEY] = True
            return


def _on_after_commit_or_rollback(session: Session) -> None:
    """commit / rollback 後に DML / emergency-stop bypass flag を clear (次 transaction へ持ち越さない)。"""
    session.info.pop(_DML_EXECUTED_KEY, None)
    session.info.pop(_EMERGENCY_STOP_BYPASS_KEY, None)


def _build_before_commit_listener(
    cfg: DbGateConfig,
) -> Callable[[Session], None]:
    def _on_before_commit(session: Session) -> None:
        # ADR-00048 §A-3: emergency-stop engage/clear は host-freeze gate を bypass する
        # (安全弁の書込が freeze 状態に左右されない)。mutation 検出より前に評価し、bypass された
        # commit は freeze gate を走らせない。ただし LOW-2: bypass session の ORM-tracked mutation が
        # emergency-stop 関連 model のみであることを assert し、無関係 model 混入なら fail-closed reject
        # (blast radius を構造的に閉じる)。
        if session.info.get(_EMERGENCY_STOP_BYPASS_KEY, False):
            _assert_emergency_stop_bypass_scope(session)
            return
        if not _session_has_mutations(session):
            return
        outcome = gate_helper.evaluate_gate(
            cfg.config_dir,
            expected_host_id=cfg.host_id,
            gate_kind=GATE_KIND_DB_COMMIT,
            public_key_resolver=cfg.public_key_resolver,
        )
        if outcome.passed:
            return
        logger.warning(
            "active_registry_db_commit_rejected_by_gate",
            extra={
                "reason_code": outcome.reason_code,
                "gate_kind": GATE_KIND_DB_COMMIT,
                "host_id_expected": outcome.state.host_id_expected,
                "active_marker_present": outcome.state.active_marker_present,
                "freeze_marker_present": outcome.state.freeze_marker_present,
                "decommission_marker_present": outcome.state.decommission_marker_present,
                "fleet_loaded": outcome.state.fleet_loaded,
                "fleet_host_status": outcome.state.fleet_host_status,
                "signer_ownership_ok": outcome.state.signer_ownership_ok,
                "mutation_count": (
                    len(session.new) + len(session.dirty) + len(session.deleted)
                ),
            },
        )
        raise ActiveRegistryGateRejectedCommit(
            "taskhub_active_registry_db_commit_rejected_by_gate"
        )

    return _on_before_commit


def attach_db_mutation_gate(
    session_class: type[Session],
    *,
    config_dir: Path,
    host_id: str,
    public_key_resolver: Callable[[str], bytes | None],
) -> Callable[[Session], None]:
    """`session_class` (例: `sessionmaker.class_`) に gate listeners を attach。

    Codex PR #85 R2 F-R2-006 fix (P1): `before_commit` に加えて
    `do_orm_execute` (DML 検出) + `after_commit` / `after_rollback` (flag clear) も attach。

    返り値は `before_commit` listener handle (test で `event.remove()` 経由 detach 用)。
    本関数は idempotent ではないので、同一 session class に複数回呼ばない。
    """
    cfg = DbGateConfig(
        config_dir=config_dir,
        host_id=host_id,
        public_key_resolver=public_key_resolver,
    )
    listener = _build_before_commit_listener(cfg)
    event.listen(session_class, "before_commit", listener)
    # F-R2-006 fix: DML execute detection + transaction-scope flag clear
    event.listen(session_class, "do_orm_execute", _on_orm_execute)
    # F-R3-002 fix: ORM flush 直前に session.new/deleted/dirty を capture
    # (autoflush で session collections が clear される前に flag set)
    event.listen(session_class, "before_flush", _on_before_flush)
    event.listen(session_class, "after_commit", _on_after_commit_or_rollback)
    event.listen(session_class, "after_rollback", _on_after_commit_or_rollback)
    return listener


def detach_db_mutation_gate(
    session_class: type[Session], listener: Callable[[Session], None]
) -> None:
    """test 用: listener detach。production runtime では使わない。"""
    event.remove(session_class, "before_commit", listener)
    # F-R2-006 + F-R3-002 fix: 同 attach した auxiliary listeners も detach (既に
    # remove 済みは debug log のみ、production runtime では呼ばれない経路のため
    # log で十分)。
    for event_name, aux_listener in (
        ("do_orm_execute", _on_orm_execute),
        ("before_flush", _on_before_flush),
        ("after_commit", _on_after_commit_or_rollback),
        ("after_rollback", _on_after_commit_or_rollback),
    ):
        try:
            event.remove(session_class, event_name, aux_listener)
        except Exception as exc:  # noqa: BLE001 - 既に remove 済みなら OK (test 用 detach)
            logger.debug(
                "active_registry_db_mutation_gate_detach_skipped",
                extra={"event_name": event_name, "exc": str(exc)},
            )


def configure_db_mutation_gate_from_settings(
    session_class: type[Session],
    *,
    settings: object | None = None,
) -> Callable[[Session], None] | None:
    """Settings.active_registry_gate_enabled に応じて L3 listener を attach。

    Codex PR #85 R1 F-004 fix (P1): production wiring を実装。
    Codex PR #85 R3 F-R3-001 fix (P2): caller が settings を inject 可能。
    `create_app(settings=...)` 経由の programmatic / test app 構築で
    cached `get_settings()` ではなく injected Settings を尊重する。

    enabled=False (default) なら no-op (None 返却)、enabled=True なら file-based
    resolver + attach、production startup で host_id 未設定なら ValueError。

    Returns:
        attached listener (test 用 detach handle) or None (gate disabled)
    """
    # 遅延 import (循環依存防止)
    from pathlib import Path

    from backend.app.config import Settings, get_settings
    from scripts import taskhub_active_registry_gate as gate_helper

    resolved_settings = settings if isinstance(settings, Settings) else get_settings()
    if not resolved_settings.active_registry_gate_enabled:
        return None
    host_id = resolved_settings.taskhub_host_id.strip()
    if not host_id:
        raise ValueError(
            "TASKMANAGEDAI_TASKHUB_HOST_ID is required when "
            "TASKMANAGEDAI_ACTIVE_REGISTRY_GATE_ENABLED=true."
        )
    config_dir = Path(resolved_settings.taskhub_config_dir)
    resolver = gate_helper.build_file_based_public_key_resolver(config_dir)
    listener = attach_db_mutation_gate(
        session_class,
        config_dir=config_dir,
        host_id=host_id,
        public_key_resolver=resolver,
    )
    logger.info(
        "active_registry_db_mutation_gate_attached",
        extra={
            "host_id": host_id,
            "config_dir": str(config_dir),
            "gate_kind": GATE_KIND_DB_COMMIT,
        },
    )
    return listener
