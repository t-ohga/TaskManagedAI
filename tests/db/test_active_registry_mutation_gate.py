"""L3 DB mutation boundary gate tests (§9.10 R10 F-001).

SQLAlchemy `before_commit` event listener が:
- mutation を伴う commit を gate fail 時に `ActiveRegistryGateRejectedCommit` で abort
- mutation を伴わない commit (read-only) は skip (block しない)
- gate passed 時は commit 成功
- decommission / freeze marker 出現で commit reject (R10 F-001 直接)

を保証する。
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import Column, Engine, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from backend.app.db.active_registry_mutation_gate import (
    ActiveRegistryGateRejectedCommit,
    attach_db_mutation_gate,
    detach_db_mutation_gate,
)
from scripts import taskhub_active_registry as ar
from scripts import taskhub_active_registry_gate as gate_helper

Base = declarative_base()


class _Sample(Base):  # type: ignore[misc, valid-type]
    __tablename__ = "sample_for_gate_test"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)


def _signer_fp(priv: Ed25519PrivateKey) -> str:
    raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")[:32]


def _setup_active_registry(
    tmp_path: Path, *, with_active_marker: bool = True
) -> tuple[Path, Ed25519PrivateKey, str]:
    """fleet + active marker を disk に配置。

    `with_active_marker=False` で active marker を不在化 (R10 F-001 negative)。
    """
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


def _make_engine_and_session(
    config_dir: Path,
    priv: Ed25519PrivateKey,
    fp: str,
    host_id: str = "host-target",
) -> tuple[Engine, sessionmaker[Session], Callable[[Session], None]]:
    """in-memory sqlite engine + sessionmaker + L3 listener attach。

    返り値 tuple: (engine, SessionLocal, listener)。listener は detach 時の
    handle として保持する。
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    def resolver(query_fp: str) -> bytes | None:
        return pub_bytes if query_fp == fp else None

    listener = attach_db_mutation_gate(
        SessionLocal.class_,
        config_dir=config_dir,
        host_id=host_id,
        public_key_resolver=resolver,
    )
    return engine, SessionLocal, listener


def test_db_commit_succeeds_when_gate_passes(tmp_path: Path) -> None:
    """gate pass → INSERT + commit 成功."""
    config_dir, priv, fp = _setup_active_registry(tmp_path)
    engine, SessionLocal, listener = _make_engine_and_session(config_dir, priv, fp)
    try:
        with SessionLocal() as session:
            session.add(_Sample(id=1, name="alpha"))
            session.commit()
            row = session.get(_Sample, 1)
            assert row is not None
            assert row.name == "alpha"
    finally:
        detach_db_mutation_gate(SessionLocal.class_, listener)
        engine.dispose()


def test_db_commit_guard_rejects_without_active_marker(tmp_path: Path) -> None:
    """plan §9.10 R10 F-001: active marker 不在で commit fail (mutation あり)."""
    config_dir, priv, fp = _setup_active_registry(tmp_path, with_active_marker=False)
    engine, SessionLocal, listener = _make_engine_and_session(config_dir, priv, fp)
    try:
        with SessionLocal() as session:
            session.add(_Sample(id=1, name="alpha"))
            with pytest.raises(ActiveRegistryGateRejectedCommit) as excinfo:
                session.commit()
            assert (
                excinfo.value.reason_code
                == "taskhub_active_registry_db_commit_rejected_by_gate"
            )
            # session が rollback されている (raise 後の state)
            session.rollback()
            assert session.get(_Sample, 1) is None
    finally:
        detach_db_mutation_gate(SessionLocal.class_, listener)
        engine.dispose()


def test_service_layer_direct_write_rejected_when_decommissioned(tmp_path: Path) -> None:
    """plan §9.10 R10 F-001: decommission.signed 後の service-layer direct INSERT も reject."""
    config_dir, priv, fp = _setup_active_registry(tmp_path)
    # decommission marker を配置 (cutover 後 source 状態)
    (config_dir / gate_helper.ACTIVE_REGISTRY_DIRNAME / gate_helper.DECOMMISSION_MARKER_FILENAME).write_text(
        json.dumps({"host_id": "host-target", "decommissioned_at": "2026-05-21T12:00:00Z"}),
        encoding="utf-8",
    )
    engine, SessionLocal, listener = _make_engine_and_session(config_dir, priv, fp)
    try:
        with SessionLocal() as session:
            session.add(_Sample(id=1, name="alpha"))
            with pytest.raises(ActiveRegistryGateRejectedCommit):
                session.commit()
    finally:
        detach_db_mutation_gate(SessionLocal.class_, listener)
        engine.dispose()


def test_db_commit_skips_gate_for_read_only_transaction(tmp_path: Path) -> None:
    """mutation を伴わない commit (read-only) は gate を skip (block しない)."""
    config_dir, priv, fp = _setup_active_registry(tmp_path, with_active_marker=False)
    engine, SessionLocal, listener = _make_engine_and_session(config_dir, priv, fp)
    try:
        with SessionLocal() as session:
            # session.new/dirty/deleted がすべて空 → gate を呼ばない
            session.commit()  # 例外発生せず
    finally:
        detach_db_mutation_gate(SessionLocal.class_, listener)
        engine.dispose()


def test_db_commit_rejects_on_freeze_marker(tmp_path: Path) -> None:
    """freeze.signed 出現後の mutation commit は reject."""
    config_dir, priv, fp = _setup_active_registry(tmp_path)
    (config_dir / gate_helper.ACTIVE_REGISTRY_DIRNAME / gate_helper.FREEZE_MARKER_FILENAME).write_text(
        json.dumps({"host_id": "host-target", "frozen_at": "2026-05-21T11:00:00Z"}),
        encoding="utf-8",
    )
    engine, SessionLocal, listener = _make_engine_and_session(config_dir, priv, fp)
    try:
        with SessionLocal() as session:
            session.add(_Sample(id=2, name="beta"))
            with pytest.raises(ActiveRegistryGateRejectedCommit) as excinfo:
                session.commit()
            assert "taskhub_active_registry_db_commit_rejected_by_gate" in str(
                excinfo.value.reason_code
            )
    finally:
        detach_db_mutation_gate(SessionLocal.class_, listener)
        engine.dispose()


def test_db_commit_rejects_when_marker_appears_mid_session(tmp_path: Path) -> None:
    """session 開始後に freeze marker が現れても commit 直前 gate check で reject (mid-flight)."""
    config_dir, priv, fp = _setup_active_registry(tmp_path)
    engine, SessionLocal, listener = _make_engine_and_session(config_dir, priv, fp)
    try:
        with SessionLocal() as session:
            session.add(_Sample(id=3, name="gamma"))
            # session 開始後に freeze marker を出現
            (config_dir / gate_helper.ACTIVE_REGISTRY_DIRNAME / gate_helper.FREEZE_MARKER_FILENAME).write_text(
                json.dumps(
                    {"host_id": "host-target", "frozen_at": "2026-05-21T11:00:00Z"}
                ),
                encoding="utf-8",
            )
            with pytest.raises(ActiveRegistryGateRejectedCommit):
                session.commit()
    finally:
        detach_db_mutation_gate(SessionLocal.class_, listener)
        engine.dispose()
