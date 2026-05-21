"""Tests for `scripts.taskhub_active_registry_gate` shared helper (§9.10 R10 F-001).

evaluate_gate の正本順序 (fail-closed):
1. fleet membership unavailable → taskhub_active_registry_fleet_membership_unavailable
2. active marker absent → taskhub_active_registry_active_marker_absent
3. active marker host_id mismatch → taskhub_active_registry_host_id_mismatch
4. freeze.signed present → taskhub_active_registry_freeze_marker_present_write_blocked
5. decommission.signed present → taskhub_active_registry_decommission_marker_present_write_blocked
6. signer ownership fail → underlying reason (taskhub_active_registry_*_violation など)
7. signer public key unavailable → taskhub_active_registry_signer_public_key_unavailable
8. signature verify failed → taskhub_active_registry_signature_verify_failed
9. all pass → passed=True / reason_code=""
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

from scripts import taskhub_active_registry as ar
from scripts import taskhub_active_registry_gate as gate_helper

# === Fixture helpers ===


def _signer_fingerprint(pub: Ed25519PublicKey) -> str:
    raw = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")[:32]


def _make_active_marker_doc(
    *,
    priv: Ed25519PrivateKey,
    host_id: str = "host-target",
    signer_fingerprint: str | None = None,
    cutover_id: str = "cutover-1",
    source_host_id: str = "host-source",
) -> dict[str, object]:
    pub = priv.public_key()
    fp = signer_fingerprint if signer_fingerprint is not None else _signer_fingerprint(pub)
    marker = ar.ActiveMarker(
        host_id=host_id,
        migration_epoch=1,
        migration_epoch_issued_at="2026-05-21T10:00:00Z",
        activated_at="2026-05-21T10:05:00Z",
        signer_fingerprint=fp,
        source_host_id=source_host_id,
        source_decommission_chain_hash="a" * 64,
        source_decommission_signer_fingerprint="src-fp",
        cutover_id=cutover_id,
        cutover_approval_id="apr-cutover-1",
        cutover_approval_claim_hash="b" * 64,
        signature="",  # placeholder
    )
    canonical = ar._rfc8785_canonical_bytes(marker.canonical_payload())  # noqa: SLF001
    sig = priv.sign(canonical)
    sig_b64 = base64.b64encode(sig).decode("ascii")
    doc = dict(marker.canonical_payload())
    doc["signature"] = sig_b64
    return doc


def _make_fleet_doc(
    *,
    host_id: str = "host-target",
    signer_fp: str = "fp-test",
    status: str = "active",
    role: str = "target",
    marker_kinds: tuple[str, ...] = ("active", "decommission", "freeze"),
    valid_from: str = "2026-01-01T00:00:00Z",
    valid_to: str = "2027-01-01T00:00:00Z",
) -> dict[str, object]:
    return {
        "domain": "taskhub.active_registry_fleet_membership.v1",
        "generation": 1,
        "hosts": [
            {
                "host_id": host_id,
                "endpoint": "https://host.example/api",
                "role": role,
                "status": status,
                "allowed_marker_signer_fingerprints": [signer_fp],
                "allowed_marker_kinds": list(marker_kinds),
                "valid_from": valid_from,
                "valid_to": valid_to,
            }
        ],
        "head_signed_at": "2026-05-21T10:00:00Z",
        "root_signature": "",
    }


def _write_marker(config_dir: Path, filename: str, doc: dict[str, object]) -> Path:
    ar_dir = config_dir / gate_helper.ACTIVE_REGISTRY_DIRNAME
    ar_dir.mkdir(parents=True, exist_ok=True)
    target = ar_dir / filename
    target.write_text(json.dumps(doc), encoding="utf-8")
    return target


def _setup_happy_path(
    tmp_path: Path,
) -> tuple[Path, str, Ed25519PrivateKey, str]:
    """Returns (config_dir, host_id, priv_key, signer_fingerprint).

    fleet + active marker を disk に配置、freeze/decommission は不在。
    public_key_resolver は priv.public_key().public_bytes() を返す closure を caller が作る。
    """
    priv = Ed25519PrivateKey.generate()
    fp = _signer_fingerprint(priv.public_key())
    host_id = "host-target"
    config_dir = tmp_path / "etc-taskhub"
    fleet_doc = _make_fleet_doc(host_id=host_id, signer_fp=fp)
    _write_marker(config_dir, gate_helper.FLEET_MEMBERSHIP_FILENAME, fleet_doc)
    active_doc = _make_active_marker_doc(priv=priv, host_id=host_id, signer_fingerprint=fp)
    _write_marker(config_dir, gate_helper.ACTIVE_MARKER_FILENAME, active_doc)
    return config_dir, host_id, priv, fp


def _resolver_from_keypair(
    priv: Ed25519PrivateKey, expected_fp: str
) -> gate_helper.PublicKeyResolver:
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    def _resolve(fp: str) -> bytes | None:
        return pub_bytes if fp == expected_fp else None

    return _resolve


# === evaluate_gate tests ===


def test_evaluate_gate_passes_in_happy_path(tmp_path: Path) -> None:
    """すべての invariant pass で GateOutcome(passed=True, reason_code="")."""
    config_dir, host_id, priv, fp = _setup_happy_path(tmp_path)
    resolver = _resolver_from_keypair(priv, fp)
    outcome = gate_helper.evaluate_gate(
        config_dir,
        expected_host_id=host_id,
        gate_kind="api_write",
        public_key_resolver=resolver,
    )
    assert outcome.passed is True
    assert outcome.reason_code == ""
    assert outcome.state.active_marker_present is True
    assert outcome.state.active_marker_host_id_match is True
    assert outcome.state.active_marker_signature_verified is True
    assert outcome.state.freeze_marker_present is False
    assert outcome.state.decommission_marker_present is False
    assert outcome.state.fleet_loaded is True
    assert outcome.state.fleet_host_status == "active"
    assert outcome.state.signer_ownership_ok is True


def test_evaluate_gate_rejects_when_fleet_membership_unavailable(tmp_path: Path) -> None:
    """fleet membership file 不在 → fail-closed (active marker は確認しない)."""
    config_dir = tmp_path / "etc-taskhub"
    (config_dir / gate_helper.ACTIVE_REGISTRY_DIRNAME).mkdir(parents=True)
    # active marker も書いて、確認 order の正本性を確認
    priv = Ed25519PrivateKey.generate()
    fp = _signer_fingerprint(priv.public_key())
    _write_marker(
        config_dir,
        gate_helper.ACTIVE_MARKER_FILENAME,
        _make_active_marker_doc(priv=priv, signer_fingerprint=fp),
    )
    outcome = gate_helper.evaluate_gate(
        config_dir,
        expected_host_id="host-target",
        gate_kind="api_write",
        public_key_resolver=lambda _: None,
    )
    assert outcome.passed is False
    assert outcome.reason_code == "taskhub_active_registry_fleet_membership_unavailable"
    assert outcome.state.fleet_loaded is False
    # fleet 不在で active marker check は実行されない
    assert outcome.state.active_marker_present is False


def test_evaluate_gate_rejects_when_active_marker_absent(tmp_path: Path) -> None:
    """fleet OK + active marker 不在 → taskhub_active_registry_active_marker_absent."""
    config_dir = tmp_path / "etc-taskhub"
    _write_marker(config_dir, gate_helper.FLEET_MEMBERSHIP_FILENAME, _make_fleet_doc())
    outcome = gate_helper.evaluate_gate(
        config_dir,
        expected_host_id="host-target",
        gate_kind="api_write",
        public_key_resolver=lambda _: None,
    )
    assert outcome.passed is False
    assert outcome.reason_code == "taskhub_active_registry_active_marker_absent"
    assert outcome.state.fleet_loaded is True
    assert outcome.state.active_marker_present is False


def test_evaluate_gate_rejects_host_id_mismatch(tmp_path: Path) -> None:
    """active marker.host_id が expected_host_id と異なる → host_id_mismatch."""
    config_dir = tmp_path / "etc-taskhub"
    priv = Ed25519PrivateKey.generate()
    fp = _signer_fingerprint(priv.public_key())
    _write_marker(
        config_dir,
        gate_helper.FLEET_MEMBERSHIP_FILENAME,
        _make_fleet_doc(host_id="host-other", signer_fp=fp),
    )
    _write_marker(
        config_dir,
        gate_helper.ACTIVE_MARKER_FILENAME,
        _make_active_marker_doc(priv=priv, host_id="host-other", signer_fingerprint=fp),
    )
    outcome = gate_helper.evaluate_gate(
        config_dir,
        expected_host_id="host-target",
        gate_kind="api_write",
        public_key_resolver=_resolver_from_keypair(priv, fp),
    )
    assert outcome.passed is False
    assert outcome.reason_code == "taskhub_active_registry_host_id_mismatch"


def test_evaluate_gate_rejects_when_freeze_marker_present(tmp_path: Path) -> None:
    """freeze.signed 存在 → freeze_marker_present_write_blocked (R10 F-001 直接)."""
    config_dir, host_id, priv, fp = _setup_happy_path(tmp_path)
    _write_marker(
        config_dir,
        gate_helper.FREEZE_MARKER_FILENAME,
        {"host_id": host_id, "frozen_at": "2026-05-21T11:00:00Z"},
    )
    outcome = gate_helper.evaluate_gate(
        config_dir,
        expected_host_id=host_id,
        gate_kind="api_write",
        public_key_resolver=_resolver_from_keypair(priv, fp),
    )
    assert outcome.passed is False
    assert outcome.reason_code == (
        "taskhub_active_registry_freeze_marker_present_write_blocked"
    )
    assert outcome.state.freeze_marker_present is True


def test_evaluate_gate_rejects_when_decommission_marker_present(tmp_path: Path) -> None:
    """decommission.signed 存在 → decommission_marker_present_write_blocked (R10 F-001 直接)."""
    config_dir, host_id, priv, fp = _setup_happy_path(tmp_path)
    _write_marker(
        config_dir,
        gate_helper.DECOMMISSION_MARKER_FILENAME,
        {"host_id": host_id, "decommissioned_at": "2026-05-21T12:00:00Z"},
    )
    outcome = gate_helper.evaluate_gate(
        config_dir,
        expected_host_id=host_id,
        gate_kind="api_write",
        public_key_resolver=_resolver_from_keypair(priv, fp),
    )
    assert outcome.passed is False
    assert outcome.reason_code == (
        "taskhub_active_registry_decommission_marker_present_write_blocked"
    )
    assert outcome.state.decommission_marker_present is True


def test_evaluate_gate_rejects_when_fleet_host_revoked(tmp_path: Path) -> None:
    """fleet host status=revoked → host_revoked_or_retired (verify_signer_host_ownership 経由)."""
    config_dir = tmp_path / "etc-taskhub"
    priv = Ed25519PrivateKey.generate()
    fp = _signer_fingerprint(priv.public_key())
    host_id = "host-target"
    _write_marker(
        config_dir,
        gate_helper.FLEET_MEMBERSHIP_FILENAME,
        _make_fleet_doc(host_id=host_id, signer_fp=fp, status="revoked"),
    )
    _write_marker(
        config_dir,
        gate_helper.ACTIVE_MARKER_FILENAME,
        _make_active_marker_doc(priv=priv, host_id=host_id, signer_fingerprint=fp),
    )
    outcome = gate_helper.evaluate_gate(
        config_dir,
        expected_host_id=host_id,
        gate_kind="api_write",
        public_key_resolver=_resolver_from_keypair(priv, fp),
    )
    assert outcome.passed is False
    assert outcome.reason_code == "taskhub_active_registry_host_revoked_or_retired"
    assert outcome.state.fleet_host_status == "revoked"


def test_evaluate_gate_rejects_when_public_key_unavailable(tmp_path: Path) -> None:
    """ownership pass + public_key_resolver(fp) -> None → signer_public_key_unavailable."""
    config_dir, host_id, _priv, _fp = _setup_happy_path(tmp_path)
    outcome = gate_helper.evaluate_gate(
        config_dir,
        expected_host_id=host_id,
        gate_kind="api_write",
        public_key_resolver=lambda _fp: None,
    )
    assert outcome.passed is False
    assert outcome.reason_code == "taskhub_active_registry_signer_public_key_unavailable"
    # ownership は pass しているはず (順序検証)
    assert outcome.state.signer_ownership_ok is True


def test_evaluate_gate_rejects_when_signature_verify_failed(tmp_path: Path) -> None:
    """正しい fingerprint でも別 keypair の public key を返すと signature verify が fail."""
    config_dir, host_id, priv, fp = _setup_happy_path(tmp_path)
    decoy = Ed25519PrivateKey.generate().public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _ = priv  # unused (decoy で別鍵)

    outcome = gate_helper.evaluate_gate(
        config_dir,
        expected_host_id=host_id,
        gate_kind="api_write",
        public_key_resolver=lambda _fp: decoy,
    )
    assert outcome.passed is False
    assert outcome.reason_code == "taskhub_active_registry_signature_verify_failed"
    assert outcome.state.active_marker_signature_verified is False


def test_evaluate_gate_rejects_when_resolver_raises(tmp_path: Path) -> None:
    """public_key_resolver が例外を投げても fail-closed (signer_public_key_unavailable)."""
    config_dir, host_id, _priv, _fp = _setup_happy_path(tmp_path)

    def _bad_resolver(_fp: str) -> bytes | None:
        raise RuntimeError("network down")

    outcome = gate_helper.evaluate_gate(
        config_dir,
        expected_host_id=host_id,
        gate_kind="api_write",
        public_key_resolver=_bad_resolver,
    )
    assert outcome.passed is False
    assert outcome.reason_code == "taskhub_active_registry_signer_public_key_unavailable"


def test_evaluate_gate_uses_injected_fleet(tmp_path: Path) -> None:
    """`fleet=` 引数を渡せば disk load を skip (test injection で有用)."""
    config_dir = tmp_path / "etc-taskhub"
    priv = Ed25519PrivateKey.generate()
    fp = _signer_fingerprint(priv.public_key())
    host_id = "host-target"
    # disk に fleet を置かない
    _write_marker(
        config_dir,
        gate_helper.ACTIVE_MARKER_FILENAME,
        _make_active_marker_doc(priv=priv, host_id=host_id, signer_fingerprint=fp),
    )
    injected_fleet = ar.FleetMembership(
        generation=1,
        hosts=(
            ar.FleetHost(
                host_id=host_id,
                endpoint="https://h.example",
                role="target",
                status="active",
                allowed_marker_signer_fingerprints=(fp,),
                allowed_marker_kinds=("active", "decommission", "freeze"),
                valid_from="2026-01-01T00:00:00Z",
                valid_to="2027-01-01T00:00:00Z",
            ),
        ),
        head_signed_at="2026-05-21T10:00:00Z",
        root_signature="",
    )
    outcome = gate_helper.evaluate_gate(
        config_dir,
        expected_host_id=host_id,
        gate_kind="api_write",
        public_key_resolver=_resolver_from_keypair(priv, fp),
        fleet=injected_fleet,
    )
    assert outcome.passed is True


# === load_fleet_membership_from_disk tests ===


def test_load_fleet_membership_returns_none_when_file_missing(tmp_path: Path) -> None:
    assert gate_helper.load_fleet_membership_from_disk(tmp_path) is None


def test_load_fleet_membership_returns_none_when_malformed_json(tmp_path: Path) -> None:
    ar_dir = tmp_path / gate_helper.ACTIVE_REGISTRY_DIRNAME
    ar_dir.mkdir()
    (ar_dir / gate_helper.FLEET_MEMBERSHIP_FILENAME).write_text("{not json", encoding="utf-8")
    assert gate_helper.load_fleet_membership_from_disk(tmp_path) is None


def test_load_fleet_membership_returns_none_when_missing_required_field(
    tmp_path: Path,
) -> None:
    doc = _make_fleet_doc()
    del doc["generation"]
    _write_marker(tmp_path, gate_helper.FLEET_MEMBERSHIP_FILENAME, doc)
    assert gate_helper.load_fleet_membership_from_disk(tmp_path) is None


def test_load_fleet_membership_parses_well_formed_doc(tmp_path: Path) -> None:
    _write_marker(tmp_path, gate_helper.FLEET_MEMBERSHIP_FILENAME, _make_fleet_doc())
    fleet = gate_helper.load_fleet_membership_from_disk(tmp_path)
    assert fleet is not None
    assert fleet.generation == 1
    assert len(fleet.hosts) == 1
    assert fleet.hosts[0].host_id == "host-target"


# === gate_kind paramization (smoke、L1/L2/L3 ともに同 reason_code をマップする保証) ===


@pytest.mark.parametrize(
    "gate_kind", ["api_write", "worker_startup", "worker_dequeue", "db_commit"]
)
def test_evaluate_gate_kind_does_not_change_decision(
    tmp_path: Path, gate_kind: str
) -> None:
    """gate_kind は audit/observability 用、決定論理には影響しない."""
    config_dir, host_id, priv, fp = _setup_happy_path(tmp_path)
    outcome = gate_helper.evaluate_gate(
        config_dir,
        expected_host_id=host_id,
        gate_kind=gate_kind,
        public_key_resolver=_resolver_from_keypair(priv, fp),
    )
    assert outcome.passed is True
