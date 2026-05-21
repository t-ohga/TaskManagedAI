"""L2: ARQ worker active-registry gate (§9.10 R10 F-001).

ARQ worker startup + 各 job dequeue 前に active marker + freeze/decommission
+ fleet membership + signer ownership を fail-closed verify する。

invariants:
- worker startup 時に gate fail → process exit 1 (`worker_startup_aborted` event)
- dequeue 前に gate fail → job を retry queue へ戻す (graceful)
- in-flight job 中に freeze/decommission marker が現れた場合は graceful cancel
  (`worker_in_flight_cancel_requested`)
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from pathlib import Path

from scripts import taskhub_active_registry_gate as gate_helper

logger = logging.getLogger(__name__)

GATE_KIND_STARTUP: str = "worker_startup"
GATE_KIND_DEQUEUE: str = "worker_dequeue"

_GATE_CTX_KEY: str = "active_registry_gate_config"


@dataclass(frozen=True, slots=True)
class WorkerGateConfig:
    """worker startup 時に context に attach される gate 設定。"""

    config_dir: Path
    host_id: str
    public_key_resolver: Callable[[str], bytes | None]


class WorkerStartupAbort(SystemExit):
    """ARQ worker startup 時に gate fail を表す例外 (exit code 1)。

    `SystemExit(1)` のサブクラスにすることで、ARQ runtime / asyncio loop が
    確実に process を終了させる (graceful shutdown を経由)。
    """

    def __init__(self, reason_code: str) -> None:
        super().__init__(1)
        self.reason_code = reason_code


class WorkerDequeueRejected(RuntimeError):
    """dequeue 前 gate fail を表す例外。job runner は本例外を catch して queue 戻し / retry。"""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def attach_worker_gate_config(
    ctx: MutableMapping[str, object],
    *,
    config_dir: Path,
    host_id: str,
    public_key_resolver: Callable[[str], bytes | None],
) -> None:
    """ARQ on_startup から呼び出して worker context に gate 設定を attach。"""
    ctx[_GATE_CTX_KEY] = WorkerGateConfig(
        config_dir=config_dir,
        host_id=host_id,
        public_key_resolver=public_key_resolver,
    )


def _resolve_worker_gate_config(ctx: MutableMapping[str, object]) -> WorkerGateConfig:
    cfg = ctx.get(_GATE_CTX_KEY)
    if not isinstance(cfg, WorkerGateConfig):
        raise WorkerStartupAbort("taskhub_active_registry_gate_not_configured")
    return cfg


def verify_worker_startup(ctx: MutableMapping[str, object]) -> None:
    """ARQ on_startup hook で呼び出す。gate fail なら `WorkerStartupAbort(SystemExit(1))`。"""
    cfg = _resolve_worker_gate_config(ctx)
    outcome = gate_helper.evaluate_gate(
        cfg.config_dir,
        expected_host_id=cfg.host_id,
        gate_kind=GATE_KIND_STARTUP,
        public_key_resolver=cfg.public_key_resolver,
    )
    if outcome.passed:
        return
    logger.error(
        "worker_startup_aborted",
        extra={
            "reason_code": outcome.reason_code,
            "gate_kind": GATE_KIND_STARTUP,
            "host_id_expected": outcome.state.host_id_expected,
            "active_marker_present": outcome.state.active_marker_present,
            "freeze_marker_present": outcome.state.freeze_marker_present,
            "decommission_marker_present": outcome.state.decommission_marker_present,
            "fleet_loaded": outcome.state.fleet_loaded,
            "fleet_host_status": outcome.state.fleet_host_status,
        },
    )
    # 監査ログ後に SystemExit(1) (テスト/CI から override 可能なように直接 raise)
    raise WorkerStartupAbort("taskhub_active_registry_worker_startup_aborted")


def verify_worker_dequeue(ctx: MutableMapping[str, object]) -> None:
    """各 job dequeue 直前に呼び出す。gate fail なら `WorkerDequeueRejected`。

    runtime: job runner / ARQ on_job_start hook 等で wrap して使う。
    fail 時は job を retry queue (`queue_paused` semantics) へ戻すのが caller の責務。
    """
    cfg = _resolve_worker_gate_config(ctx)
    outcome = gate_helper.evaluate_gate(
        cfg.config_dir,
        expected_host_id=cfg.host_id,
        gate_kind=GATE_KIND_DEQUEUE,
        public_key_resolver=cfg.public_key_resolver,
    )
    if outcome.passed:
        return
    logger.warning(
        "worker_dequeue_rejected_by_gate",
        extra={
            "reason_code": outcome.reason_code,
            "gate_kind": GATE_KIND_DEQUEUE,
            "host_id_expected": outcome.state.host_id_expected,
            "freeze_marker_present": outcome.state.freeze_marker_present,
            "decommission_marker_present": outcome.state.decommission_marker_present,
        },
    )
    raise WorkerDequeueRejected("taskhub_active_registry_worker_dequeue_rejected_by_gate")


def exit_with_startup_abort(reason_code: str) -> None:
    """test / production の最終 fallback: stderr 出力 + os._exit(1)。

    通常は `verify_worker_startup` が raise する `WorkerStartupAbort(SystemExit(1))` で
    asyncio runtime が gracefully process を終了させるが、loop の外で呼び出された場合の
    緊急 fallback として用意。
    """
    sys.stderr.write(
        f"worker_startup_aborted reason_code={reason_code}\n"
    )
    sys.stderr.flush()
    os._exit(1)
