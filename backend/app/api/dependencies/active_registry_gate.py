"""L1: API ingress active-registry gate (§9.4 R2 F-007 + §9.10 R10 F-001).

FastAPI dependency + middleware: write endpoint へ attach することで
freeze/decommission 状態の host が write を受け付けないことを保証する。
fail-closed (503 Service Unavailable)。

config_dir / host_id は backend/app/config.py の Settings から渡される
(`TASKMANAGEDAI_TASKHUB_CONFIG_DIR` + `TASKMANAGEDAI_TASKHUB_HOST_ID` env)。
public_key resolver は backend startup 時に DI 経由で attach される
(fleet_membership.allowed_marker_signer_fingerprints + 公開鍵 store からの解決)。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import cast

from fastapi import FastAPI, HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from scripts import taskhub_active_registry_gate as gate_helper

logger = logging.getLogger(__name__)

GATE_KIND_API: str = "api_write"

# Codex PR #85 R2 F-R2-003 fix (P2): HTTP method-based middleware で全 mutation 経路を
# fail-closed gate に通す (per-endpoint Depends 配線の代替、production wiring 完成)。
_WRITE_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# gate exempt paths: health / metrics / auth bootstrap (gate self-loop 防止)。
# operator が gate 修復のためにこれらの endpoint を叩けないと dead-lock になるため exempt。
_GATE_EXEMPT_PATH_PREFIXES: tuple[str, ...] = (
    "/health",
    "/metrics",
    "/api/v1/auth/",
    "/auth/",
)


def _resolve_gate_config(request: Request) -> tuple[Path, str, Callable[[str], bytes | None]]:
    """app.state.active_registry_gate_config から (config_dir, host_id, resolver) を取得。

    backend startup 時に `configure_active_registry_gate()` で attach される。
    attach 漏れ / 部分的 attach は設計違反 → fail-closed (503 + reason_code)。

    Codex PR #85 R1 F-006 fix (P2): 直接 indexing は KeyError → FastAPI 500 を
    引き起こすため、`.get()` + None check で defensive に 503 fail-closed。
    """
    cfg = getattr(request.app.state, "active_registry_gate_config", None)
    if not isinstance(cfg, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "active_registry_gate_not_configured",
                "reason_code": "taskhub_active_registry_gate_not_configured",
                "error_summary": (
                    "Active-registry gate is not configured for this FastAPI app. "
                    "configure_active_registry_gate() must be called at startup."
                ),
            },
        )
    config_dir = cfg.get("config_dir")
    host_id = cfg.get("host_id")
    resolver = cfg.get("public_key_resolver")
    if not isinstance(config_dir, Path) or not isinstance(host_id, str) or not callable(resolver):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "active_registry_gate_malformed_config",
                "reason_code": "taskhub_active_registry_gate_malformed_config",
                "error_summary": (
                    "Active-registry gate config is malformed (missing config_dir / "
                    "host_id / public_key_resolver). configure_active_registry_gate() "
                    "must supply all three fields."
                ),
            },
        )
    return config_dir, host_id, cast(Callable[[str], bytes | None], resolver)


def require_active_registry_write_authority(request: Request) -> None:
    """write endpoint dependency。pass なら何も返さない (FastAPI 慣習)、fail なら 503。"""
    config_dir, host_id, resolver = _resolve_gate_config(request)
    outcome = gate_helper.evaluate_gate(
        config_dir,
        expected_host_id=host_id,
        gate_kind=GATE_KIND_API,
        public_key_resolver=resolver,
    )
    if outcome.passed:
        return
    logger.warning(
        "active_registry_write_rejected_by_gate",
        extra={
            "reason_code": outcome.reason_code,
            "gate_kind": GATE_KIND_API,
            "host_id_expected": outcome.state.host_id_expected,
            "active_marker_present": outcome.state.active_marker_present,
            "freeze_marker_present": outcome.state.freeze_marker_present,
            "decommission_marker_present": outcome.state.decommission_marker_present,
            "fleet_loaded": outcome.state.fleet_loaded,
            "fleet_host_status": outcome.state.fleet_host_status,
            "signer_ownership_ok": outcome.state.signer_ownership_ok,
            "request_id": getattr(request.state, "request_id", None),
        },
    )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error_code": "active_registry_write_rejected_by_gate",
            "reason_code": "taskhub_active_registry_write_rejected_by_gate",
            "error_summary": (
                "Write rejected by active-registry gate. "
                f"Underlying reason: {outcome.reason_code}."
            ),
        },
    )


def configure_active_registry_gate(
    app_state: object,
    *,
    config_dir: Path,
    host_id: str,
    public_key_resolver: Callable[[str], bytes | None],
) -> None:
    """FastAPI startup から呼び出して gate 設定を attach。

    本関数は idempotent (同じ config を複数回 attach しても安全)。
    """
    # `app_state` は `FastAPI.state` (Starlette `State`) 想定で動的属性 set を許可。
    # `setattr` を明示することで Pyright/mypy の `object` 型推論を回避し、ruff B010 は
    # 動的 attribute 設計のため抑制する (test も同 API で attach 検証する)。
    setattr(  # noqa: B010
        app_state,
        "active_registry_gate_config",
        {
            "config_dir": config_dir,
            "host_id": host_id,
            "public_key_resolver": public_key_resolver,
        },
    )


def configure_active_registry_gate_from_settings(
    app_state: object, *, settings: object | None = None
) -> bool:
    """settings (Settings.active_registry_gate_enabled) から gate 設定を attach。

    Codex PR #85 R1 F-001 fix (P1): production wiring を実装。
    Codex PR #85 R2 F-R2-004 fix (P2): caller が settings を inject 可能 (test /
    programmatic app 構築で `create_app(settings)` の値を尊重)。未指定なら
    `get_settings()` の cached singleton を使用。

    Settings.active_registry_gate_enabled=True なら file-based resolver で attach。
    False (default) なら no-op (development / test の既存 fixture を維持)。
    production startup で enabled=True かつ host_id 未設定なら ValueError raise
    (fail-closed startup abort)。

    Returns:
        True: gate を attach (production deployment)
        False: gate skip (development / test default)
    """
    # 遅延 import (循環依存防止 + test での monkey-patch 容易性)
    from backend.app.config import Settings, get_settings

    resolved_settings = settings if isinstance(settings, Settings) else get_settings()
    if not resolved_settings.active_registry_gate_enabled:
        return False
    host_id = resolved_settings.taskhub_host_id.strip()
    if not host_id:
        raise ValueError(
            "TASKMANAGEDAI_TASKHUB_HOST_ID is required when "
            "TASKMANAGEDAI_ACTIVE_REGISTRY_GATE_ENABLED=true."
        )
    config_dir = Path(resolved_settings.taskhub_config_dir)
    resolver = gate_helper.build_file_based_public_key_resolver(config_dir)
    configure_active_registry_gate(
        app_state,
        config_dir=config_dir,
        host_id=host_id,
        public_key_resolver=resolver,
    )
    logger.info(
        "active_registry_gate_attached",
        extra={
            "host_id": host_id,
            "config_dir": str(config_dir),
            "gate_kind": GATE_KIND_API,
        },
    )
    return True


class ActiveRegistryGateMiddleware(BaseHTTPMiddleware):
    """全 write request (POST/PUT/PATCH/DELETE) を gate fail-closed で intercept。

    Codex PR #85 R2 F-R2-003 fix (P2): per-endpoint `Depends()` 配線の代替として
    HTTP method-based middleware で L1 ingress を強制。gate disabled (default) なら
    no-op (config not attached なら通過)、enabled なら全 mutation を 503 fail-closed。

    exempt: `/health`, `/metrics`, `/auth/*`, `/api/v1/auth/*`
    (gate self-loop / 修復経路を防ぐ)。
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method not in _WRITE_METHODS:
            return await call_next(request)
        path = request.url.path
        for exempt in _GATE_EXEMPT_PATH_PREFIXES:
            if path == exempt.rstrip("/") or path.startswith(exempt):
                return await call_next(request)
        cfg = getattr(request.app.state, "active_registry_gate_config", None)
        if cfg is None:
            # gate disabled (default、development / test) → no-op
            return await call_next(request)
        if not isinstance(cfg, dict):
            return _gate_error_response(
                503,
                "active_registry_gate_not_configured",
                "taskhub_active_registry_gate_not_configured",
                "Active-registry gate is not configured for this FastAPI app.",
            )
        config_dir = cfg.get("config_dir")
        host_id = cfg.get("host_id")
        resolver = cfg.get("public_key_resolver")
        if not isinstance(config_dir, Path) or not isinstance(host_id, str) or not callable(resolver):
            return _gate_error_response(
                503,
                "active_registry_gate_malformed_config",
                "taskhub_active_registry_gate_malformed_config",
                "Active-registry gate config is malformed.",
            )
        outcome = gate_helper.evaluate_gate(
            config_dir,
            expected_host_id=host_id,
            gate_kind=GATE_KIND_API,
            public_key_resolver=cast(Callable[[str], bytes | None], resolver),
        )
        if outcome.passed:
            return await call_next(request)
        logger.warning(
            "active_registry_write_rejected_by_middleware",
            extra={
                "reason_code": outcome.reason_code,
                "method": request.method,
                "path": path,
                "host_id_expected": outcome.state.host_id_expected,
                "active_marker_present": outcome.state.active_marker_present,
                "freeze_marker_present": outcome.state.freeze_marker_present,
                "decommission_marker_present": outcome.state.decommission_marker_present,
                "fleet_loaded": outcome.state.fleet_loaded,
                "request_id": getattr(request.state, "request_id", None),
            },
        )
        return _gate_error_response(
            503,
            "active_registry_write_rejected_by_gate",
            "taskhub_active_registry_write_rejected_by_gate",
            f"Write rejected by active-registry gate. Underlying reason: {outcome.reason_code}.",
        )


def _gate_error_response(
    status_code: int, error_code: str, reason_code: str, error_summary: str
) -> Response:
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": {
                "error_code": error_code,
                "reason_code": reason_code,
                "error_summary": error_summary,
            }
        },
    )


def install_active_registry_gate_middleware(app: FastAPI) -> None:
    """Codex PR #85 R2 F-R2-003 fix (P2): FastAPI app に middleware を add する。

    `create_app()` で `configure_active_registry_gate_from_settings(app.state)` 後に
    呼ぶことで、enabled / disabled どちらでも安全 (middleware 内で config 不在を判定)。
    """
    app.add_middleware(ActiveRegistryGateMiddleware)
