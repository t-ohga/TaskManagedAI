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

import functools
import logging
import os
import sys
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def verify_worker_dequeue_if_configured(ctx: MutableMapping[str, object]) -> None:
    """gate config が attach されていれば dequeue verify、未 attach なら no-op。

    Codex PR #85 R2 F-R2-002 fix (P1): ARQ `on_job_start` hook から呼ぶ。
    gate disabled (default) では何もせず通過、enabled なら verify_worker_dequeue。

    test 環境では gate config が attach されないため、本関数は no-op 経路を提供。
    """
    cfg = ctx.get(_GATE_CTX_KEY)
    if not isinstance(cfg, WorkerGateConfig):
        return  # gate disabled / not configured → no-op
    verify_worker_dequeue(ctx)


def with_active_registry_gate(
    task_fn: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    """ARQ task function を gate check + re-enqueue handling で wrap する decorator。

    Codex PR #85 R5 F-R5-001 fix (P1): `on_job_start` から `ArqRetry` を raise する
    ことは ARQ worker job-execution try/except の外側で発生するため、task wrapper 経由に変更。
    Codex PR #85 R6 F-R6-001 fix (P1): `ArqRetry(defer=60)` を毎回 raise すると
    ARQ default `max_tries=5` を消費し sustained freeze/decommission window で job が
    permanent failure になる。`ctx["redis"].enqueue_job(...)` で fresh try counter で
    新規 job を投入 + current job は None 返却 (success 扱い) するようにする。
    enqueue 失敗時は ArqRetry fallback (max_tries に拘束されるが drop よりはまし)。

    使い方:
        @with_active_registry_gate
        async def my_task(ctx, ...):
            ...

    または WorkerSettings.functions list で wrap:
        functions = [with_active_registry_gate(my_task)]
    """
    # 遅延 import (arq.worker.Retry の循環依存防止 + test 環境での optional import)
    from arq.worker import Retry as ArqRetry

    @functools.wraps(task_fn)
    async def _wrapped(
        ctx: MutableMapping[str, object],
        *args: object,
        **kwargs: object,
    ) -> Any:  # noqa: ANN401 - ARQ task function は任意の戻り値型を許可
        try:
            verify_worker_dequeue_if_configured(ctx)
        except WorkerDequeueRejected as exc:
            # Codex R6 F-R6-001 fix: fresh re-enqueue で max_tries 消費を回避
            redis = ctx.get("redis")
            enqueue_job = getattr(redis, "enqueue_job", None)
            if callable(enqueue_job):
                try:
                    result = enqueue_job(task_fn.__name__, *args, _defer_by=60, **kwargs)
                    # ArqRedis.enqueue_job は coroutine を返す。dynamic call のため
                    # `inspect.isawaitable` で safe に await。
                    import inspect

                    if inspect.isawaitable(result):
                        await result
                except Exception as enqueue_exc:  # noqa: BLE001 - redis 接続不可等
                    logger.error(
                        "worker_gate_re_enqueue_failed_fallback_to_retry",
                        extra={
                            "reason_code": exc.reason_code,
                            "task": task_fn.__name__,
                            "enqueue_exc": str(enqueue_exc),
                        },
                    )
                    raise ArqRetry(defer=60) from exc
                logger.warning(
                    "worker_dequeue_rejected_re_enqueued",
                    extra={
                        "reason_code": exc.reason_code,
                        "task": task_fn.__name__,
                        "defer_seconds": 60,
                    },
                )
                return None  # current job 完了 (success)、新規 job が defer 後再実行
            # fallback: redis pool 未取得 → ArqRetry (max_tries 拘束だが drop よりはまし)
            logger.warning(
                "worker_dequeue_rejected_retry_scheduled_no_redis",
                extra={"reason_code": exc.reason_code, "defer_seconds": 60},
            )
            raise ArqRetry(defer=60) from exc
        return await task_fn(ctx, *args, **kwargs)

    return _wrapped


def configure_worker_gate_from_settings(
    ctx: MutableMapping[str, object],
) -> bool:
    """ARQ on_startup から呼び出す: Settings.active_registry_gate_enabled に応じて attach。

    Codex PR #85 R1 F-003 fix (P1): production wiring を実装。
    enabled=False (default) なら no-op、enabled=True なら file-based resolver で attach +
    `verify_worker_startup(ctx)` を即時実行 (失敗時 `WorkerStartupAbort(SystemExit(1))`)。

    Returns:
        True: gate を attach + startup verify 成功
        False: gate skip (development / test)
    """
    # 遅延 import (循環依存防止)
    from backend.app.config import get_settings
    from scripts import taskhub_active_registry_gate as gate_helper

    settings = get_settings()
    if not settings.active_registry_gate_enabled:
        return False
    host_id = settings.taskhub_host_id.strip()
    if not host_id:
        raise ValueError(
            "TASKMANAGEDAI_TASKHUB_HOST_ID is required when "
            "TASKMANAGEDAI_ACTIVE_REGISTRY_GATE_ENABLED=true."
        )
    from pathlib import Path

    config_dir = Path(settings.taskhub_config_dir)
    resolver = gate_helper.build_file_based_public_key_resolver(config_dir)
    attach_worker_gate_config(
        ctx,
        config_dir=config_dir,
        host_id=host_id,
        public_key_resolver=resolver,
    )
    # startup verify (失敗時 raise SystemExit(1))
    verify_worker_startup(ctx)
    logger.info(
        "active_registry_worker_gate_attached",
        extra={
            "host_id": host_id,
            "config_dir": str(config_dir),
            "gate_kind": GATE_KIND_STARTUP,
        },
    )
    return True
