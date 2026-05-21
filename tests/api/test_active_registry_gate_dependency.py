"""L1 FastAPI dependency tests (§9.4 R2 F-007 + §9.10 R10 F-001).

negative tests (plan §9.4 F-007 + §9.10 R10):
- test_decommissioned_source_rejects_api_write
- test_pending_cutover_target_does_not_accept_write (active marker absent)
- test_service_startup_fails_without_active_marker (gate not configured)
- test_service_startup_fails_with_frozen_marker
- test_service_startup_fails_with_stale_active_marker_signature
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies.active_registry_gate import (
    configure_active_registry_gate,
    install_active_registry_gate_middleware,
    require_active_registry_write_authority,
)
from scripts import taskhub_active_registry as ar
from scripts import taskhub_active_registry_gate as gate_helper


def _signer_fingerprint(pub: Ed25519PublicKey) -> str:
    raw = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")[:32]


def _setup_fleet_and_active(
    tmp_path: Path, *, host_id: str = "host-target"
) -> tuple[Path, Ed25519PrivateKey, str]:
    priv = Ed25519PrivateKey.generate()
    fp = _signer_fingerprint(priv.public_key())
    config_dir = tmp_path / "etc-taskhub"
    ar_dir = config_dir / gate_helper.ACTIVE_REGISTRY_DIRNAME
    ar_dir.mkdir(parents=True)

    fleet_doc = {
        "domain": "taskhub.active_registry_fleet_membership.v1",
        "generation": 1,
        "hosts": [
            {
                "host_id": host_id,
                "endpoint": "https://h.example",
                "role": "target",
                "status": "active",
                "allowed_marker_signer_fingerprints": [fp],
                "allowed_marker_kinds": ["active", "decommission", "freeze"],
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_to": "2027-01-01T00:00:00Z",
            }
        ],
        "head_signed_at": "2026-05-21T10:00:00Z",
        "root_signature": "",
    }
    (ar_dir / gate_helper.FLEET_MEMBERSHIP_FILENAME).write_text(
        json.dumps(fleet_doc), encoding="utf-8"
    )

    marker = ar.ActiveMarker(
        host_id=host_id,
        migration_epoch=1,
        migration_epoch_issued_at="2026-05-21T10:00:00Z",
        activated_at="2026-05-21T10:05:00Z",
        signer_fingerprint=fp,
        source_host_id="host-source",
        source_decommission_chain_hash="a" * 64,
        source_decommission_signer_fingerprint="src-fp",
        cutover_id="cutover-1",
        cutover_approval_id="apr-cutover-1",
        cutover_approval_claim_hash="b" * 64,
        signature="",
    )
    canonical = ar._rfc8785_canonical_bytes(marker.canonical_payload())  # noqa: SLF001
    sig = priv.sign(canonical)
    doc = dict(marker.canonical_payload())
    doc["signature"] = base64.b64encode(sig).decode("ascii")
    (ar_dir / gate_helper.ACTIVE_MARKER_FILENAME).write_text(
        json.dumps(doc), encoding="utf-8"
    )
    return config_dir, priv, fp


def _build_app_with_gate(
    config_dir: Path, host_id: str, priv: Ed25519PrivateKey, fp: str
) -> FastAPI:
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    def resolver(query_fp: str) -> bytes | None:
        return pub_bytes if query_fp == fp else None

    app = FastAPI()
    configure_active_registry_gate(
        app.state,
        config_dir=config_dir,
        host_id=host_id,
        public_key_resolver=resolver,
    )

    @app.post("/test/write", dependencies=[Depends(require_active_registry_write_authority)])
    async def _write() -> dict[str, str]:
        return {"status": "written"}

    return app


def test_api_write_succeeds_when_gate_passes(tmp_path: Path) -> None:
    config_dir, priv, fp = _setup_fleet_and_active(tmp_path)
    app = _build_app_with_gate(config_dir, "host-target", priv, fp)
    with TestClient(app) as client:
        response = client.post("/test/write")
    assert response.status_code == 200
    assert response.json() == {"status": "written"}


def test_decommissioned_source_rejects_api_write(tmp_path: Path) -> None:
    """plan §9.4 F-007: decommission.signed 存在 → 503 + reason_code."""
    config_dir, priv, fp = _setup_fleet_and_active(tmp_path)
    (config_dir / gate_helper.ACTIVE_REGISTRY_DIRNAME / gate_helper.DECOMMISSION_MARKER_FILENAME).write_text(
        json.dumps({"host_id": "host-target", "decommissioned_at": "2026-05-21T12:00:00Z"}),
        encoding="utf-8",
    )
    app = _build_app_with_gate(config_dir, "host-target", priv, fp)
    with TestClient(app) as client:
        response = client.post("/test/write")
    assert response.status_code == 503
    body = response.json()
    assert body["detail"]["error_code"] == "active_registry_write_rejected_by_gate"
    assert body["detail"]["reason_code"] == (
        "taskhub_active_registry_write_rejected_by_gate"
    )


def test_pending_cutover_target_does_not_accept_write(tmp_path: Path) -> None:
    """plan §9.4 F-007: active marker 不在 (cutover pending) → 503."""
    config_dir, priv, fp = _setup_fleet_and_active(tmp_path)
    # active marker を削除
    (config_dir / gate_helper.ACTIVE_REGISTRY_DIRNAME / gate_helper.ACTIVE_MARKER_FILENAME).unlink()
    app = _build_app_with_gate(config_dir, "host-target", priv, fp)
    with TestClient(app) as client:
        response = client.post("/test/write")
    assert response.status_code == 503
    assert response.json()["detail"]["reason_code"] == (
        "taskhub_active_registry_write_rejected_by_gate"
    )


def test_service_startup_fails_without_gate_configured(tmp_path: Path) -> None:
    """plan §9.4 F-007: gate not configured → 503 + active_registry_gate_not_configured."""
    _ = tmp_path
    app = FastAPI()

    @app.post("/test/write", dependencies=[Depends(require_active_registry_write_authority)])
    async def _write() -> dict[str, str]:
        return {"status": "written"}

    with TestClient(app) as client:
        response = client.post("/test/write")
    assert response.status_code == 503
    body = response.json()
    assert body["detail"]["error_code"] == "active_registry_gate_not_configured"
    assert body["detail"]["reason_code"] == (
        "taskhub_active_registry_gate_not_configured"
    )


def test_service_startup_fails_with_frozen_marker(tmp_path: Path) -> None:
    """plan §9.4 F-007: freeze.signed 存在 → 503."""
    config_dir, priv, fp = _setup_fleet_and_active(tmp_path)
    (config_dir / gate_helper.ACTIVE_REGISTRY_DIRNAME / gate_helper.FREEZE_MARKER_FILENAME).write_text(
        json.dumps({"host_id": "host-target", "frozen_at": "2026-05-21T11:00:00Z"}),
        encoding="utf-8",
    )
    app = _build_app_with_gate(config_dir, "host-target", priv, fp)
    with TestClient(app) as client:
        response = client.post("/test/write")
    assert response.status_code == 503
    assert response.json()["detail"]["reason_code"] == (
        "taskhub_active_registry_write_rejected_by_gate"
    )


def test_service_startup_fails_with_stale_active_marker_signature(tmp_path: Path) -> None:
    """plan §9.4 F-007: signature stale (resolver が別 public key) → signature_verify_failed."""
    config_dir, _priv, fp = _setup_fleet_and_active(tmp_path)
    # resolver は別 keypair の public key を返す → signature verify fail
    decoy_pub = (
        Ed25519PrivateKey.generate().public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )

    def stale_resolver(_query_fp: str) -> bytes | None:
        return decoy_pub

    app = FastAPI()
    configure_active_registry_gate(
        app.state,
        config_dir=config_dir,
        host_id="host-target",
        public_key_resolver=stale_resolver,
    )

    @app.post("/test/write", dependencies=[Depends(require_active_registry_write_authority)])
    async def _write() -> dict[str, str]:
        return {"status": "written"}

    with TestClient(app) as client:
        response = client.post("/test/write")
    assert response.status_code == 503
    assert response.json()["detail"]["reason_code"] == (
        "taskhub_active_registry_write_rejected_by_gate"
    )
    _ = fp  # 参照 (fixture 引数 unpack 整合)


def test_api_write_rejected_on_malformed_gate_config(tmp_path: Path) -> None:
    """Codex R1 F-006 (P2) fix: 部分的に attach された malformed config も 503 fail-closed."""
    app = FastAPI()
    # 部分的に attach (host_id 欠落、tmp_path で path traversal 安全な fixture を使用)
    app.state.active_registry_gate_config = {
        "config_dir": tmp_path / "no-such-config",
        # "host_id": "..." 欠落
        "public_key_resolver": lambda _fp: None,
    }

    @app.post("/test/write", dependencies=[Depends(require_active_registry_write_authority)])
    async def _write() -> dict[str, str]:
        return {"status": "written"}

    with TestClient(app) as client:
        response = client.post("/test/write")
    assert response.status_code == 503
    body = response.json()
    assert body["detail"]["error_code"] == "active_registry_gate_malformed_config"
    assert body["detail"]["reason_code"] == (
        "taskhub_active_registry_gate_malformed_config"
    )


def test_middleware_blocks_write_methods_when_gate_fails(tmp_path: Path) -> None:
    """Codex R2 F-R2-003 (P2) fix: POST/PUT/PATCH/DELETE が gate fail で 503 になる."""
    config_dir, priv, fp = _setup_fleet_and_active(tmp_path)
    # decommission marker 配置 → gate fail
    (
        config_dir / gate_helper.ACTIVE_REGISTRY_DIRNAME / gate_helper.DECOMMISSION_MARKER_FILENAME
    ).write_text(
        json.dumps({"host_id": "host-target", "decommissioned_at": "2026-05-21T12:00:00Z"}),
        encoding="utf-8",
    )
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    def resolver(query_fp: str) -> bytes | None:
        return pub_bytes if query_fp == fp else None

    app = FastAPI()
    configure_active_registry_gate(
        app.state,
        config_dir=config_dir,
        host_id="host-target",
        public_key_resolver=resolver,
    )
    install_active_registry_gate_middleware(app)

    @app.post("/api/write")
    async def _write() -> dict[str, str]:
        return {"status": "written"}

    @app.get("/api/read")
    async def _read() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(app) as client:
        # write は middleware で 503 (endpoint 自体に dependency 不要)
        response = client.post("/api/write")
        assert response.status_code == 503
        assert response.json()["detail"]["reason_code"] == (
            "taskhub_active_registry_write_rejected_by_gate"
        )
        # read は middleware で通過
        response = client.get("/api/read")
        assert response.status_code == 200


def test_middleware_skips_when_gate_not_configured(tmp_path: Path) -> None:
    """Codex R2 F-R2-003 (P2) fix: gate disabled (config 未 attach) なら middleware も no-op."""
    _ = tmp_path
    app = FastAPI()
    # gate config を attach しない (default disabled)
    install_active_registry_gate_middleware(app)

    @app.post("/api/write")
    async def _write() -> dict[str, str]:
        return {"status": "written"}

    with TestClient(app) as client:
        response = client.post("/api/write")
    assert response.status_code == 200
    assert response.json() == {"status": "written"}


def test_middleware_exempts_health_metrics_auth(tmp_path: Path) -> None:
    """Codex R2 F-R2-003 (P2) fix: /health, /metrics, /auth/* は gate 経路を bypass."""
    config_dir, priv, fp = _setup_fleet_and_active(tmp_path)
    # 完全 gate fail 条件 (active marker 削除)
    (
        config_dir / gate_helper.ACTIVE_REGISTRY_DIRNAME / gate_helper.ACTIVE_MARKER_FILENAME
    ).unlink()
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    def resolver(query_fp: str) -> bytes | None:
        return pub_bytes if query_fp == fp else None

    app = FastAPI()
    configure_active_registry_gate(
        app.state,
        config_dir=config_dir,
        host_id="host-target",
        public_key_resolver=resolver,
    )
    install_active_registry_gate_middleware(app)

    @app.post("/auth/dev-login")
    async def _auth() -> dict[str, str]:
        return {"status": "logged-in"}

    @app.post("/api/write")
    async def _write() -> dict[str, str]:
        return {"status": "written"}

    with TestClient(app) as client:
        # /auth/* は exempt → 200
        assert client.post("/auth/dev-login").status_code == 200
        # /api/write は middleware で reject
        assert client.post("/api/write").status_code == 503


def test_configure_active_registry_gate_is_idempotent(tmp_path: Path) -> None:
    """同じ config を複数回 attach しても safe (idempotent)."""
    config_dir, priv, fp = _setup_fleet_and_active(tmp_path)
    app = _build_app_with_gate(config_dir, "host-target", priv, fp)
    # 2 回目 attach
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    def resolver(_q: str) -> bytes | None:
        return pub_bytes

    configure_active_registry_gate(
        app.state,
        config_dir=config_dir,
        host_id="host-target",
        public_key_resolver=resolver,
    )
    with TestClient(app) as client:
        response = client.post("/test/write")
    assert response.status_code == 200


# === pytest fixture for L2/L3 reuse (test_active_registry_gates) ===
@pytest.fixture
def _unused_marker_sentinel(tmp_path: Path) -> Path:
    """テストファイル間で fixture が衝突しないよう一意な fixture 名を保持."""
    return tmp_path
