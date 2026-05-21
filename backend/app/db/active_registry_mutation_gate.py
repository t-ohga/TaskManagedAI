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


def _session_has_mutations(session: Session) -> bool:
    """session に pending INSERT/UPDATE/DELETE が含まれているかを確認。

    read-only な commit (例: identity map のみ flush していない select session)
    を block しないための optimization + correctness 保護。
    """
    return bool(session.new) or bool(session.dirty) or bool(session.deleted)


def _build_before_commit_listener(
    cfg: DbGateConfig,
) -> Callable[[Session], None]:
    def _on_before_commit(session: Session) -> None:
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
    """`session_class` (例: `sessionmaker.class_`) に `before_commit` listener を attach。

    返り値は listener handle (test で `event.remove()` 経由 detach 用)。
    本関数は idempotent ではないので、同一 session class に複数回呼ばない。
    """
    cfg = DbGateConfig(
        config_dir=config_dir,
        host_id=host_id,
        public_key_resolver=public_key_resolver,
    )
    listener = _build_before_commit_listener(cfg)
    event.listen(session_class, "before_commit", listener)
    return listener


def detach_db_mutation_gate(
    session_class: type[Session], listener: Callable[[Session], None]
) -> None:
    """test 用: listener detach。production runtime では使わない。"""
    event.remove(session_class, "before_commit", listener)
