"""L2 ARQ worker active-registry gate tests (§9.10 R10 F-001).

negative tests (plan §9.10 R10 F-001):
- test_worker_startup_aborted_when_active_marker_invalid (startup gate fail)
- test_worker_job_rejected_after_freeze_marker (dequeue gate fail)
- test_async_task_queue_paused_on_decommission (dequeue gate fail)
- test_in_flight_job_graceful_cancel_on_freeze_marker (mid-flight verify_worker_dequeue)
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.app.workers.active_registry_worker_gate import (
    WorkerDequeueRejected,
    WorkerStartupAbort,
    attach_worker_gate_config,
    verify_worker_dequeue,
    verify_worker_startup,
)
from scripts import taskhub_active_registry as ar
from scripts import taskhub_active_registry_gate as gate_helper


def _signer_fp(priv: Ed25519PrivateKey) -> str:
    raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")[:32]


def _setup_active(
    tmp_path: Path, *, with_active_marker: bool = True
) -> tuple[Path, Ed25519PrivateKey, str]:
    priv = Ed25519PrivateKey.generate()
    fp = _signer_fp(priv)
    host_id = "host-target"
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

    if with_active_marker:
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
            cutover_approval_id="apr-1",
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


def _attach(
    ctx: dict[str, object], config_dir: Path, priv: Ed25519PrivateKey, fp: str
) -> None:
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    def resolver(query_fp: str) -> bytes | None:
        return pub_bytes if query_fp == fp else None

    attach_worker_gate_config(
        ctx,
        config_dir=config_dir,
        host_id="host-target",
        public_key_resolver=resolver,
    )


def test_worker_startup_succeeds_when_gate_passes(tmp_path: Path) -> None:
    """active marker + fleet OK → startup gate pass (raise しない)."""
    config_dir, priv, fp = _setup_active(tmp_path)
    ctx: dict[str, object] = {}
    _attach(ctx, config_dir, priv, fp)
    verify_worker_startup(ctx)  # 例外なし


def test_worker_startup_aborted_when_active_marker_invalid(tmp_path: Path) -> None:
    """plan §9.10 R10 F-001: active marker 不在 → WorkerStartupAbort(SystemExit(1))."""
    config_dir, priv, fp = _setup_active(tmp_path, with_active_marker=False)
    ctx: dict[str, object] = {}
    _attach(ctx, config_dir, priv, fp)
    with pytest.raises(WorkerStartupAbort) as excinfo:
        verify_worker_startup(ctx)
    # SystemExit を継承するため、code は 1
    assert excinfo.value.code == 1
    assert excinfo.value.reason_code == (
        "taskhub_active_registry_worker_startup_aborted"
    )


def test_worker_startup_aborted_when_gate_not_configured() -> None:
    """gate config 未 attach → fail-closed (raise WorkerStartupAbort)."""
    ctx: dict[str, object] = {}
    with pytest.raises(WorkerStartupAbort) as excinfo:
        verify_worker_startup(ctx)
    assert excinfo.value.reason_code == (
        "taskhub_active_registry_gate_not_configured"
    )


def test_worker_dequeue_succeeds_when_gate_passes(tmp_path: Path) -> None:
    """gate pass → dequeue pass (raise しない)."""
    config_dir, priv, fp = _setup_active(tmp_path)
    ctx: dict[str, object] = {}
    _attach(ctx, config_dir, priv, fp)
    verify_worker_dequeue(ctx)


def test_worker_job_rejected_after_freeze_marker(tmp_path: Path) -> None:
    """plan §9.10 R10 F-001: freeze.signed 出現後の job dequeue → WorkerDequeueRejected."""
    config_dir, priv, fp = _setup_active(tmp_path)
    ctx: dict[str, object] = {}
    _attach(ctx, config_dir, priv, fp)
    # 最初の dequeue は pass
    verify_worker_dequeue(ctx)
    # freeze.signed を出現
    (config_dir / gate_helper.ACTIVE_REGISTRY_DIRNAME / gate_helper.FREEZE_MARKER_FILENAME).write_text(
        json.dumps({"host_id": "host-target", "frozen_at": "2026-05-21T11:00:00Z"}),
        encoding="utf-8",
    )
    # 次の dequeue は reject
    with pytest.raises(WorkerDequeueRejected) as excinfo:
        verify_worker_dequeue(ctx)
    assert excinfo.value.reason_code == (
        "taskhub_active_registry_worker_dequeue_rejected_by_gate"
    )


def test_async_task_queue_paused_on_decommission(tmp_path: Path) -> None:
    """plan §9.10 R10 F-001: decommission.signed 出現後の dequeue → WorkerDequeueRejected."""
    config_dir, priv, fp = _setup_active(tmp_path)
    ctx: dict[str, object] = {}
    _attach(ctx, config_dir, priv, fp)
    (config_dir / gate_helper.ACTIVE_REGISTRY_DIRNAME / gate_helper.DECOMMISSION_MARKER_FILENAME).write_text(
        json.dumps({"host_id": "host-target", "decommissioned_at": "2026-05-21T12:00:00Z"}),
        encoding="utf-8",
    )
    with pytest.raises(WorkerDequeueRejected):
        verify_worker_dequeue(ctx)


def test_in_flight_job_graceful_cancel_on_freeze_marker(tmp_path: Path) -> None:
    """plan §9.10 R10 F-001: in-flight job 中に freeze 検出 → next verify_worker_dequeue で reject.

    実 ARQ runtime では job runner が verify_worker_dequeue を再呼出して
    graceful cancel する想定。本テストでは mid-flight 検出 contract を確認。
    """
    config_dir, priv, fp = _setup_active(tmp_path)
    ctx: dict[str, object] = {}
    _attach(ctx, config_dir, priv, fp)
    # job 開始時の verify は pass
    verify_worker_dequeue(ctx)
    # mid-flight: freeze marker が現れる
    (config_dir / gate_helper.ACTIVE_REGISTRY_DIRNAME / gate_helper.FREEZE_MARKER_FILENAME).write_text(
        json.dumps({"host_id": "host-target", "frozen_at": "2026-05-21T11:00:00Z"}),
        encoding="utf-8",
    )
    # 続行 verify は reject (job runner はこれで cancel 判断)
    with pytest.raises(WorkerDequeueRejected):
        verify_worker_dequeue(ctx)


def test_worker_dequeue_aborted_when_gate_not_configured() -> None:
    """gate config 未 attach → WorkerStartupAbort (SystemExit fail-closed)."""
    ctx: dict[str, object] = {}
    with pytest.raises(WorkerStartupAbort):
        verify_worker_dequeue(ctx)
