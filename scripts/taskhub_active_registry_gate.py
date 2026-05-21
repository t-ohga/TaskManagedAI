"""Active-registry gate shared helper (§9.10 R10 F-001 + §9.4 R2 F-007).

3 layer defense-in-depth (L1 FastAPI dependency / L2 ARQ worker / L3 SQLAlchemy
before_commit listener) は本 helper を共通基盤として、active marker resolution +
freeze/decommission detection + fleet membership + signer ownership exact match
+ active marker signature verify (fail-closed) を一元化する。

Plan §9.4 F-007 で L1 FastAPI dependency を導入、§9.7 R6 F-002 で current fleet
policy check を追加、§9.10 R10 F-001 で全 write surface (API + worker + DB
commit boundary) に拡張。本 helper は marker resolution + verification の正本。

Layout (`<config_dir>/active_registry/`):
    - active.signed                : target active marker (current host)
    - freeze.signed                : source freeze (existing PR #75)
    - decommission.signed          : source decommission (cutover terminal)
    - active_registry_fleet.signed.json : fleet membership (root-signed)
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scripts import taskhub_active_registry as ar

__all__ = [
    "ACTIVE_REGISTRY_DIRNAME",
    "ACTIVE_MARKER_FILENAME",
    "FREEZE_MARKER_FILENAME",
    "DECOMMISSION_MARKER_FILENAME",
    "FLEET_MEMBERSHIP_FILENAME",
    "FLEET_MEMBERSHIP_DOMAIN",
    "SIGNERS_DIRNAME",
    "GateState",
    "GateOutcome",
    "GateKind",
    "PublicKeyResolver",
    "evaluate_gate",
    "load_fleet_membership_from_disk",
    "build_file_based_public_key_resolver",
]

SIGNERS_DIRNAME: Final[str] = "signers"
# Codex PR #85 R4 F-R4-002 fix (P1): 既存 fingerprint encoding (base64 first 32
# chars) で `/`, `+`, `=` が出るため、これを backward compat で許可。
# path traversal 防御は filename encoding (sha256 hash) + resolve confinement +
# O_NOFOLLOW で行う (4 層 defense は維持)。
_SIGNER_FINGERPRINT_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9+/=_-]{1,128}$")
_ED25519_RAW_KEY_LEN: Final[int] = 32

ACTIVE_REGISTRY_DIRNAME: Final[str] = "active_registry"
ACTIVE_MARKER_FILENAME: Final[str] = "active.signed"
FREEZE_MARKER_FILENAME: Final[str] = "freeze.signed"
DECOMMISSION_MARKER_FILENAME: Final[str] = "decommission.signed"
FLEET_MEMBERSHIP_FILENAME: Final[str] = "active_registry_fleet.signed.json"
# Codex PR #85 R4 F-R4-001 fix (P1): canonical producer/validator
# `scripts/taskhub_active_registry.py:DOMAIN_FLEET_MEMBERSHIP_V1` を import で参照
# (hard-coded string で drift していた)。
FLEET_MEMBERSHIP_DOMAIN: Final[str] = ar.DOMAIN_FLEET_MEMBERSHIP_V1

GateKind = str  # "api_write" | "worker_startup" | "worker_dequeue" | "db_commit"
PublicKeyResolver = Callable[[str], bytes | None]
"""`signer_fingerprint -> public_key_bytes (32 bytes Ed25519) | None`。

`None` を返した場合 fail-closed (signer unknown reason_code)。
"""


@dataclass(frozen=True, slots=True)
class GateState:
    """gate evaluation 中の resolved state (snapshot)。

    test / observability で参照可能。本 dataclass は read-only snapshot で、
    gate decision には影響しない (decision は GateOutcome.passed)。
    """

    host_id_expected: str
    active_marker_present: bool
    active_marker_host_id_match: bool
    active_marker_signature_verified: bool
    freeze_marker_present: bool
    decommission_marker_present: bool
    fleet_loaded: bool
    fleet_host_status: str | None  # "active" | "retired" | "revoked" | None
    signer_ownership_ok: bool


@dataclass(frozen=True, slots=True)
class GateOutcome:
    """gate evaluation の結果。`reason_code` は `passed=False` のとき非空。

    passed=True なら write 許可、False なら fail-closed (caller が L1/L2/L3 で
    異なる error response / 503 / IntegrityError などへ map する)。
    """

    passed: bool
    reason_code: str
    state: GateState


def _config_dir_active_registry(config_dir: Path) -> Path:
    return config_dir / ACTIVE_REGISTRY_DIRNAME


def load_fleet_membership_from_disk(config_dir: Path) -> ar.FleetMembership | None:
    """`<config_dir>/active_registry/active_registry_fleet.signed.json` を load。

    not found / malformed JSON / schema mismatch は `None` を返す (caller が
    `taskhub_active_registry_fleet_membership_unavailable` reason_code に map)。
    """
    path = _config_dir_active_registry(config_dir) / FLEET_MEMBERSHIP_FILENAME
    if not path.exists():
        return None
    try:
        doc = ar.read_marker_doc(path)
    except Exception:  # noqa: BLE001 - fail-closed
        return None
    try:
        # Codex PR #85 R1 F-002 fix (P2): domain field exact match を必須化。
        # 同 structure の別 schema (例: signed manifest / approval document) を
        # 誤って fleet membership として load しないため fail-closed。
        if str(doc.get("domain", "")) != FLEET_MEMBERSHIP_DOMAIN:
            return None
        hosts_raw = doc.get("hosts", [])
        if not isinstance(hosts_raw, list):
            return None
        hosts: list[ar.FleetHost] = []
        for h in hosts_raw:
            if not isinstance(h, dict):
                return None
            hosts.append(
                ar.FleetHost(
                    host_id=str(h["host_id"]),
                    endpoint=str(h["endpoint"]),
                    role=str(h["role"]),
                    status=str(h["status"]),
                    valid_from=str(h["valid_from"]),
                    valid_to=str(h["valid_to"]),
                    allowed_marker_kinds=tuple(h.get("allowed_marker_kinds", ())),
                    allowed_marker_signer_fingerprints=tuple(
                        h.get("allowed_marker_signer_fingerprints", ())
                    ),
                )
            )
        return ar.FleetMembership(
            generation=int(doc["generation"]),
            hosts=tuple(hosts),
            head_signed_at=str(doc["head_signed_at"]),
            root_signature=str(doc["root_signature"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _load_active_marker(config_dir: Path) -> ar.ActiveMarker | None:
    path = _config_dir_active_registry(config_dir) / ACTIVE_MARKER_FILENAME
    if not path.exists():
        return None
    try:
        doc = ar.read_marker_doc(path)
        return ar.ActiveMarker(
            host_id=str(doc["host_id"]),
            migration_epoch=int(doc["migration_epoch"]),
            migration_epoch_issued_at=str(doc["migration_epoch_issued_at"]),
            activated_at=str(doc["activated_at"]),
            signer_fingerprint=str(doc["signer_fingerprint"]),
            source_host_id=str(doc["source_host_id"]),
            source_decommission_chain_hash=str(doc["source_decommission_chain_hash"]),
            source_decommission_signer_fingerprint=str(
                doc["source_decommission_signer_fingerprint"]
            ),
            cutover_id=str(doc["cutover_id"]),
            cutover_approval_id=str(doc["cutover_approval_id"]),
            cutover_approval_claim_hash=str(doc["cutover_approval_claim_hash"]),
            signature=str(doc["signature"]),
        )
    except Exception:  # noqa: BLE001 - malformed marker => fail-closed
        return None


def _marker_file_exists(config_dir: Path, filename: str) -> bool:
    return (_config_dir_active_registry(config_dir) / filename).exists()


def _safe_filename_for_fingerprint(fingerprint: str) -> str:
    """Codex PR #85 R4 F-R4-002 fix (P1): fingerprint -> safe filename mapping.

    既存 fingerprint encoding (base64 first 32 chars) は `/`, `+`, `=` を含み得るため、
    sha256 hash の hex を filename として使用 (path traversal を構造的に排除)。
    operator deployment: `taskhub-genkey <fingerprint>` (Sprint 13) で sha256 を計算して
    `<config_dir>/active_registry/signers/<sha256hex>.pub` に key を配置する。
    backward compat: 同一 fingerprint は同一 sha256 を再現するため、operator が
    手動で計算した hash と一致する。
    """
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    return f"{digest}.pub"


def build_file_based_public_key_resolver(
    config_dir: Path,
) -> Callable[[str], bytes | None]:
    """`<config_dir>/active_registry/signers/<sha256(fingerprint)>.pub` から Ed25519 raw 32 bytes を load。

    Codex PR #85 R2 F-R2-001/F-R2-005 fix + R4 F-R4-002 fix:
    - Layer 1: 型 check + regex (`/`/`\\`/NUL を弾く)
    - Layer 2: fingerprint -> sha256 filename mapping (path traversal 構造的排除、
      R4 F-R4-002 で `/` 等含む fingerprint も safe filename に変換)
    - Layer 3: `path.resolve()` confinement (signers_dir 直下保証)
    - Layer 4: `os.open(O_NOFOLLOW)` で atomic symlink reject + size check

    operator deployment:
        1. fingerprint = base64 first 32 chars (既存 producer / verify_signer_host_ownership 経由)
        2. filename = sha256(fingerprint).hexdigest() + ".pub" (本 helper 内で計算)
        3. <config_dir>/active_registry/signers/<sha256hex>.pub に raw 32 bytes 書込
        4. file permission 0400、symlink 禁止 (`O_NOFOLLOW` で atomic 検出)
    """
    signers_dir = _config_dir_active_registry(config_dir) / SIGNERS_DIRNAME

    def _resolve(fingerprint: str) -> bytes | None:
        # Layer 1: 型 check + regex (existing fingerprint format を accept、NUL は弾く)
        if not isinstance(fingerprint, str) or not _SIGNER_FINGERPRINT_RE.match(fingerprint):
            return None
        # NUL bytes は regex で弾けない場合があるため explicit check
        if "\x00" in fingerprint:
            return None
        # Layer 2: sha256 hash で filename を確実に safe な hex 文字列に変換
        safe_filename = _safe_filename_for_fingerprint(fingerprint)
        path = signers_dir / safe_filename
        # Layer 3: resolve confinement (path traversal 構造的に排除済みだが defense-in-depth)
        try:
            resolved = path.resolve(strict=False)
            base_resolved = signers_dir.resolve(strict=False)
            if not str(resolved).startswith(str(base_resolved) + os.sep) and resolved != base_resolved:
                return None
        except (OSError, RuntimeError):
            return None
        # Layer 4: O_NOFOLLOW で atomic symlink reject + read
        try:
            fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            return None
        try:
            data = os.read(fd, _ED25519_RAW_KEY_LEN + 1)
        finally:
            os.close(fd)
        if len(data) != _ED25519_RAW_KEY_LEN:
            return None
        return data

    return _resolve


def evaluate_gate(
    config_dir: Path,
    *,
    expected_host_id: str,
    gate_kind: GateKind,
    public_key_resolver: PublicKeyResolver,
    fleet: ar.FleetMembership | None = None,
) -> GateOutcome:
    """Gate 評価の正本 (L1/L2/L3 共通)。

    Order (fail-closed):
    1. fleet membership 取得 (None なら taskhub_active_registry_fleet_membership_unavailable)
    2. active marker 取得 (None なら taskhub_active_registry_active_marker_absent)
    3. active marker host_id == expected_host_id (mismatch なら host_id_mismatch)
    4. freeze.signed 存在チェック (存在なら taskhub_active_registry_freeze_marker_present_write_blocked)
    5. decommission.signed 存在チェック (存在なら taskhub_active_registry_decommission_marker_present_write_blocked)
    6. fleet host status == "active" + lifecycle window + signer ownership exact match
       (`verify_signer_host_ownership` 経由、§9.5 R3 F-002 + §9.7 R6 F-002)
    7. active marker signature verify (Ed25519、public_key_resolver 経由)
       resolver が None 返却なら taskhub_active_registry_signer_public_key_unavailable
       signature 不正なら taskhub_active_registry_signature_verify_failed
    8. すべて pass で GateOutcome(passed=True, reason_code="", state=...)
    """
    _ = gate_kind  # 現状 gate_kind は audit/observability 用、決定論理には未使用
    fleet_loaded = fleet is not None
    if not fleet_loaded:
        fleet = load_fleet_membership_from_disk(config_dir)
        fleet_loaded = fleet is not None

    state_init = GateState(
        host_id_expected=expected_host_id,
        active_marker_present=False,
        active_marker_host_id_match=False,
        active_marker_signature_verified=False,
        freeze_marker_present=False,
        decommission_marker_present=False,
        fleet_loaded=fleet_loaded,
        fleet_host_status=None,
        signer_ownership_ok=False,
    )

    if fleet is None:
        return GateOutcome(
            passed=False,
            reason_code="taskhub_active_registry_fleet_membership_unavailable",
            state=state_init,
        )

    active = _load_active_marker(config_dir)
    if active is None:
        return GateOutcome(
            passed=False,
            reason_code="taskhub_active_registry_active_marker_absent",
            state=state_init,
        )

    state_with_active = GateState(
        host_id_expected=expected_host_id,
        active_marker_present=True,
        active_marker_host_id_match=(active.host_id == expected_host_id),
        active_marker_signature_verified=False,
        freeze_marker_present=_marker_file_exists(config_dir, FREEZE_MARKER_FILENAME),
        decommission_marker_present=_marker_file_exists(config_dir, DECOMMISSION_MARKER_FILENAME),
        fleet_loaded=True,
        fleet_host_status=None,
        signer_ownership_ok=False,
    )

    if active.host_id != expected_host_id:
        return GateOutcome(
            passed=False,
            reason_code="taskhub_active_registry_host_id_mismatch",
            state=state_with_active,
        )

    if state_with_active.freeze_marker_present:
        return GateOutcome(
            passed=False,
            reason_code="taskhub_active_registry_freeze_marker_present_write_blocked",
            state=state_with_active,
        )

    if state_with_active.decommission_marker_present:
        return GateOutcome(
            passed=False,
            reason_code="taskhub_active_registry_decommission_marker_present_write_blocked",
            state=state_with_active,
        )

    host = fleet.find_host(expected_host_id)
    fleet_status = host.status if host is not None else None
    ownership_ok, ownership_reason = ar.verify_signer_host_ownership(
        fleet=fleet,
        marker_host_id=active.host_id,
        marker_signer_fingerprint=active.signer_fingerprint,
        marker_kind="active",
    )

    state_after_ownership = GateState(
        host_id_expected=expected_host_id,
        active_marker_present=True,
        active_marker_host_id_match=True,
        active_marker_signature_verified=False,
        freeze_marker_present=False,
        decommission_marker_present=False,
        fleet_loaded=True,
        fleet_host_status=fleet_status,
        signer_ownership_ok=ownership_ok,
    )

    if not ownership_ok:
        return GateOutcome(
            passed=False,
            reason_code=ownership_reason or "taskhub_active_registry_signer_ownership_failed",
            state=state_after_ownership,
        )

    try:
        public_key = public_key_resolver(active.signer_fingerprint)
    except Exception:  # noqa: BLE001 - resolver 例外も fail-closed
        public_key = None
    if public_key is None:
        return GateOutcome(
            passed=False,
            reason_code="taskhub_active_registry_signer_public_key_unavailable",
            state=state_after_ownership,
        )

    canonical_bytes = ar._rfc8785_canonical_bytes(active.canonical_payload())  # noqa: SLF001
    signature_ok = ar.verify_ed25519_signature(public_key, active.signature, canonical_bytes)

    state_final = GateState(
        host_id_expected=expected_host_id,
        active_marker_present=True,
        active_marker_host_id_match=True,
        active_marker_signature_verified=signature_ok,
        freeze_marker_present=False,
        decommission_marker_present=False,
        fleet_loaded=True,
        fleet_host_status=fleet_status,
        signer_ownership_ok=True,
    )

    if not signature_ok:
        return GateOutcome(
            passed=False,
            reason_code="taskhub_active_registry_signature_verify_failed",
            state=state_final,
        )

    return GateOutcome(passed=True, reason_code="", state=state_final)
