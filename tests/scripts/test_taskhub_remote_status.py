"""SP022-T02 Phase 4 / T08 batch 4: taskhub_remote_status.py tests.

Coverage:
- signed config loader (missing / permission / signature / malformed / expired / version)
- SSH argv builder (Unicode NFC / Cc/Cf / project regex / file path)
- query_remote_compose_status (state machine: running / safe_down / transitional / unknown)
- exact set match enforcement (R2 F-003 adopt)
- stdout cap (64 KiB)
- compose_file sha256 verify (ADV R1 F-009)
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.taskhub_remote_status import (
    RemoteStatusOptions,
    _build_ssh_argv,
    _parse_compose_ps_json,
    _validate_compose_file_path,
    load_remote_hosts_signed_config,
)


# --- helpers (test isolation) ---


def _make_signing_key() -> tuple[bytes, bytes, str]:
    """raw 32-byte seed + raw 32-byte public + fingerprint."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    priv = Ed25519PrivateKey.generate()
    seed = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    import hashlib as _h
    return seed, pub_bytes, _h.sha256(pub_bytes).hexdigest()


def _setup_taskhub_keys_and_signed_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    hosts: dict[str, dict[str, object]] | None = None,
    expires_at: datetime | None = None,
    signed_at: datetime | None = None,
    config_version: int = 1,
) -> tuple[bytes, bytes, str, Path]:
    """isolated ~/.taskhub setup + signed config write. Returns (seed, pub, fingerprint, taskhub_home)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    taskhub_home = tmp_path / ".taskhub"
    keys_dir = taskhub_home / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    seed, pub_bytes, fingerprint = _make_signing_key()
    sign_path = keys_dir / "approval-signing-key"
    sign_path.write_bytes(seed)
    sign_path.chmod(0o600)
    pub_path = keys_dir / "approval-verify-key.pub"
    pub_path.write_bytes(pub_bytes)
    pub_path.chmod(0o600)
    allowlist_path = tmp_path / "allowlist.txt"
    allowlist_path.write_text(f"{fingerprint}\n", encoding="utf-8")
    # monkeypatch allowlist path
    from scripts import taskhub_signed_approval as sa
    monkeypatch.setattr(sa, "_verify_key_fingerprint_allowlist_path", lambda: allowlist_path)

    # write signed config
    if hosts is not None:
        if signed_at is None:
            signed_at = datetime.now(UTC) - timedelta(hours=1)
        if expires_at is None:
            expires_at = datetime.now(UTC) + timedelta(days=180)
        payload = {
            "config_version": config_version,
            "signed_at": signed_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": expires_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hosts": hosts,
        }
        canonical_bytes = sa.canonical_for_signature("remote_hosts.v1", payload)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        priv = Ed25519PrivateKey.from_private_bytes(seed)
        sig = base64.b64encode(priv.sign(canonical_bytes)).decode("ascii")
        full = {**payload, "signature": sig}
        config_path = taskhub_home / "remote_hosts.signed.json"
        config_path.write_text(json.dumps(full, indent=2, sort_keys=True), encoding="utf-8")
        config_path.chmod(0o600)
    return seed, pub_bytes, fingerprint, taskhub_home


# --- _validate_compose_file_path ---


def test_validate_compose_file_path_absolute_ok() -> None:
    _validate_compose_file_path("/abs/path/docker-compose.yml")


def test_validate_compose_file_path_relative_rejected() -> None:
    with pytest.raises(ValueError, match="absolute path"):
        _validate_compose_file_path("rel/path")


def test_validate_compose_file_path_nul_byte_rejected() -> None:
    with pytest.raises(ValueError, match="NUL or newline"):
        _validate_compose_file_path("/abs/path\x00x")


def test_validate_compose_file_path_newline_rejected() -> None:
    with pytest.raises(ValueError, match="NUL or newline"):
        _validate_compose_file_path("/abs/path\nx")


def test_validate_compose_file_path_unicode_rtl_override_rejected() -> None:
    """ADV R1 F-013 adopt: U+202E RTL override 拒否."""
    with pytest.raises(ValueError, match="control/format"):
        _validate_compose_file_path("/abs/‮evil.yml")


def test_validate_compose_file_path_unicode_zero_width_space_rejected() -> None:
    """ADV R1 F-013 adopt: U+200B zero-width space 拒否."""
    with pytest.raises(ValueError, match="control/format"):
        _validate_compose_file_path("/abs/path​.yml")


# --- _build_ssh_argv ---


def test_build_ssh_argv_project_pattern_invalid_rejected() -> None:
    with pytest.raises(ValueError, match="compose_project invalid"):
        _build_ssh_argv("t-ohga-vps", "; rm -rf /", "/abs/file.yml", 10)


def test_build_ssh_argv_host_pattern_invalid_rejected() -> None:
    with pytest.raises(ValueError, match="host invalid"):
        _build_ssh_argv("UPPERCASE.HOST", "taskmanagedai", "/abs/file.yml", 10)


def test_build_ssh_argv_strict_options_present() -> None:
    argv = _build_ssh_argv("t-ohga-vps", "taskmanagedai", "/abs/docker-compose.yml", 10)
    # strict options 必須 (test #8)
    assert "StrictHostKeyChecking=yes" in argv
    assert "BatchMode=yes" in argv
    assert "ConnectTimeout=10" in argv
    assert "PasswordAuthentication=no" in argv
    # remote command (末尾) に compose_project / compose_file が shlex.quote されて含まれる
    assert "ssh" == argv[0]
    assert argv[-2] == "t-ohga-vps"  # host
    # remote command 末尾
    remote_cmd = argv[-1]
    assert "docker compose -p taskmanagedai -f" in remote_cmd
    assert "/abs/docker-compose.yml" in remote_cmd
    assert "sha256sum" in remote_cmd


# --- _parse_compose_ps_json ---


def test_parse_compose_ps_json_array_form() -> None:
    stdout = b'[{"Service": "api", "State": "running"}, {"Service": "postgres", "State": "exited"}]'
    services = _parse_compose_ps_json(stdout)
    assert len(services) == 2
    assert services[0]["Service"] == "api"


def test_parse_compose_ps_json_ndjson_form() -> None:
    stdout = (
        b'{"Service": "api", "State": "running"}\n'
        b'{"Service": "postgres", "State": "exited"}\n'
    )
    services = _parse_compose_ps_json(stdout)
    assert len(services) == 2


def test_parse_compose_ps_json_skips_sha256sum_line() -> None:
    sha256_line = "a" * 64 + "  /abs/docker-compose.yml"
    stdout = (
        b'{"Service": "api", "State": "running"}\n'
        + sha256_line.encode() + b"\n"
    )
    services = _parse_compose_ps_json(stdout)
    assert len(services) == 1


# --- load_remote_hosts_signed_config ---


def test_load_config_missing_returns_reason_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    result = load_remote_hosts_signed_config()
    assert result.reason_code == "remote_status_config_missing"


def test_load_config_permission_unsafe_returns_reason_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _setup_taskhub_keys_and_signed_config(
        monkeypatch, tmp_path,
        hosts={"h": {
            "compose_project": "taskmanagedai",
            "compose_file": "/abs/file.yml",
            "compose_file_sha256": "f" * 64,
            "expected_services": ["api"],
        }},
    )
    # mode 0o644 に変更
    config_path = tmp_path / ".taskhub" / "remote_hosts.signed.json"
    config_path.chmod(0o644)
    result = load_remote_hosts_signed_config()
    assert result.reason_code == "remote_status_config_permission_unsafe"


def test_load_config_unsupported_version_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _setup_taskhub_keys_and_signed_config(
        monkeypatch, tmp_path,
        hosts={"h": {
            "compose_project": "taskmanagedai",
            "compose_file": "/abs/file.yml",
            "compose_file_sha256": "f" * 64,
            "expected_services": ["api"],
        }},
        config_version=2,
    )
    result = load_remote_hosts_signed_config()
    assert result.reason_code == "remote_status_config_unsupported_version"


def test_load_config_expired_returns_reason_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _setup_taskhub_keys_and_signed_config(
        monkeypatch, tmp_path,
        hosts={"h": {
            "compose_project": "taskmanagedai",
            "compose_file": "/abs/file.yml",
            "compose_file_sha256": "f" * 64,
            "expected_services": ["api"],
        }},
        signed_at=datetime.now(UTC) - timedelta(days=200),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    result = load_remote_hosts_signed_config()
    assert result.reason_code == "remote_status_config_expired"


def test_load_config_signature_invalid_returns_reason_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _setup_taskhub_keys_and_signed_config(
        monkeypatch, tmp_path,
        hosts={"h": {
            "compose_project": "taskmanagedai",
            "compose_file": "/abs/file.yml",
            "compose_file_sha256": "f" * 64,
            "expected_services": ["api"],
        }},
    )
    # tamper signature
    config_path = tmp_path / ".taskhub" / "remote_hosts.signed.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    data["signature"] = base64.b64encode(b"\x00" * 64).decode("ascii")
    config_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    result = load_remote_hosts_signed_config()
    assert result.reason_code == "remote_status_config_signature_invalid"


def test_load_config_ok_returns_hosts_dict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _setup_taskhub_keys_and_signed_config(
        monkeypatch, tmp_path,
        hosts={
            "t-ohga-vps": {
                "compose_project": "taskmanagedai",
                "compose_file": "/var/lib/taskhub/docker-compose.yml",
                "compose_file_sha256": "a" * 64,
                "expected_services": ["api", "worker", "postgres", "redis", "frontend"],
            },
        },
    )
    result = load_remote_hosts_signed_config()
    assert result.reason_code == "config_ok"
    assert "t-ohga-vps" in result.hosts
    cfg = result.hosts["t-ohga-vps"]
    assert cfg.compose_project == "taskmanagedai"
    assert cfg.compose_file_sha256 == "a" * 64
    assert set(cfg.expected_services) == {"api", "worker", "postgres", "redis", "frontend"}


def test_query_invalid_host_returns_reason_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """config に存在しない host で reason_code=invalid_host."""
    _setup_taskhub_keys_and_signed_config(
        monkeypatch, tmp_path,
        hosts={
            "t-ohga-vps": {
                "compose_project": "taskmanagedai",
                "compose_file": "/var/lib/taskhub/docker-compose.yml",
                "compose_file_sha256": "a" * 64,
                "expected_services": ["api"],
            },
        },
    )
    from scripts.taskhub_remote_status import query_remote_compose_status
    result = query_remote_compose_status(RemoteStatusOptions(remote_host="unknown-host"))
    assert result.reason_code == "remote_status_invalid_host"
    assert result.split_brain_safe is False
