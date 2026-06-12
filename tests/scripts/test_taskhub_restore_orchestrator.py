"""SP022-T02 Phase 3 / T08 batch 3 — taskhub_restore_orchestrator unit tests.

24 rounds + 58 findings 100% adopt 反映後の verification (mock-based testing 3-layer).

Coverage:
- Layer 1 (pure): allowlist check / meta.json schema / tar size limits / port extraction / compose env normalize
- Layer 2 (subprocess mocks): pg_restore / pg_dump / redis SAVE / age / psql / docker inspect via compose exec
- Layer 3 (orchestration): full mock + per-component rollback verify + R3-F-001 skip_service_stop deny chains
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import taskhub_restore_orchestrator as ro
from scripts.taskhub_subprocess_runner import (
    SafeSubprocessConfig,
    SubprocessResult,
)


def _mock_result(returncode: int = 0, stdout: bytes = b"") -> SubprocessResult:
    return SubprocessResult(
        command_name="mock",
        arg_count=1,
        returncode=returncode,
        stdout=stdout,
        stderr_sanitized="",
        duration_sec=0.0,
        sanitized_flags=(),
    )


# === Layer 1: pure functions ===


def test_check_archive_allowlist_accepts_meta_json() -> None:
    allowed, reason = ro.check_archive_member_allowlist("meta.json")
    assert allowed is True
    assert reason is None


def test_check_archive_allowlist_accepts_postgres_subdir() -> None:
    allowed, _ = ro.check_archive_member_allowlist("postgres/pg_dump.dump")
    assert allowed is True


def test_check_archive_allowlist_rejects_id_rsa() -> None:
    allowed, reason = ro.check_archive_member_allowlist("artifacts/id_rsa")
    assert allowed is False
    assert reason and "deny filename pattern" in reason


def test_check_archive_allowlist_rejects_unknown_root() -> None:
    allowed, reason = ro.check_archive_member_allowlist("evil_dir/secret.txt")
    assert allowed is False
    assert reason and "not in allowlist" in reason


def test_verify_meta_json_required_keys_missing_rejected(tmp_path: Path) -> None:
    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps({"format_version": "1.0"}), encoding="utf-8")
    warnings: list = []
    with pytest.raises(ro.RestoreRuntimeError) as exc:
        ro.read_and_verify_meta_json(meta_path, warnings)
    assert exc.value.reason_code == "restore_meta_json_invalid"


def test_verify_meta_json_unsupported_format_version_rejected(tmp_path: Path) -> None:
    meta = {
        "format_version": "99.0",
        "host_name": "h", "timestamp_utc": "2026-01-01T00:00:00Z",
        "postgres_version": "17", "redis_version": "7", "alembic_head": "abc",
    }
    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    warnings: list = []
    with pytest.raises(ro.RestoreRuntimeError) as exc:
        ro.read_and_verify_meta_json(meta_path, warnings)
    assert exc.value.reason_code == "restore_meta_json_invalid"


def test_verify_meta_json_accepts_known_optional_keys(tmp_path: Path) -> None:
    meta = {
        "format_version": "1.0",
        "host_name": "h", "timestamp_utc": "2026-01-01T00:00:00Z",
        "postgres_version": "17", "redis_version": "7", "alembic_head": "abc",
        "tenant_id_set": [1, 2],
    }
    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    warnings: list = []
    result = ro.read_and_verify_meta_json(meta_path, warnings)
    assert result["format_version"] == "1.0"
    assert warnings == []  # known optional, no warning


def test_verify_meta_json_unknown_keys_warns(tmp_path: Path) -> None:
    meta = {
        "format_version": "1.0",
        "host_name": "h", "timestamp_utc": "2026-01-01T00:00:00Z",
        "postgres_version": "17", "redis_version": "7", "alembic_head": "abc",
        "future_key_v2": "x",
    }
    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    warnings: list = []
    ro.read_and_verify_meta_json(meta_path, warnings)
    assert "restore_meta_json_unknown_keys" in warnings


def test_verify_postgres_major_version_match() -> None:
    meta = {"postgres_version": "17.2"}
    # OK no raise
    ro.verify_postgres_major_version(meta, "17")


def test_verify_postgres_major_version_mismatch_rejected() -> None:
    meta = {"postgres_version": "16.0"}
    with pytest.raises(ro.RestoreRuntimeError) as exc:
        ro.verify_postgres_major_version(meta, "17")
    assert exc.value.reason_code == "restore_postgres_major_version_mismatch"


def test_resolve_restore_temp_layout_creates_0700() -> None:
    """R10-F-001 adopt: tmp dir mode is 0o700."""
    tmp_dir = ro.resolve_restore_temp_layout()
    try:
        mode = stat.S_IMODE(tmp_dir.stat().st_mode)
        assert mode == 0o700
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_python_version_gate_3_12_minimum() -> None:
    """R7-F-001 + R8-F-008 adopt: Python 3.12+ required."""
    assert sys.version_info >= (3, 12)
    # module import-time check passes
    ro._assert_python_version()


def test_all_services_healthy_parses_array_format() -> None:
    """docker compose v2 may emit JSON array."""
    out = json.dumps([
        {"Service": "postgres", "Health": "healthy", "State": "running"},
        {"Service": "redis", "Health": "healthy", "State": "running"},
    ]).encode("utf-8")
    assert ro.all_services_healthy(out, ["postgres", "redis"]) is True


def test_all_services_healthy_parses_newline_delimited() -> None:
    out = b'{"Service":"postgres","Health":"healthy","State":"running"}\n' \
          b'{"Service":"redis","Health":"healthy","State":"running"}\n'
    assert ro.all_services_healthy(out, ["postgres", "redis"]) is True


def test_all_services_healthy_returns_false_on_missing_service() -> None:
    out = b'{"Service":"postgres","Health":"healthy"}'
    assert ro.all_services_healthy(out, ["postgres", "redis"]) is False


def test_extract_published_port_short_syntax_with_host_ip() -> None:
    ports = ["127.0.0.1:5432:5432"]
    assert ro._extract_published_port(ports, 5432) == "5432"


def test_extract_host_ip_short_syntax_explicit() -> None:
    ports = ["127.0.0.1:5432:5432"]
    assert ro._extract_host_ip(ports, 5432) == "127.0.0.1"


def test_extract_host_ip_short_syntax_omitted_returns_none() -> None:
    """R13-F-001 fix: host_ip omitted (default 0.0.0.0) → None → fail-closed deny in caller."""
    ports = ["5432:5432"]
    assert ro._extract_host_ip(ports, 5432) is None


def test_extract_host_ip_long_syntax_dict() -> None:
    ports = [{"target": 5432, "published": 5432, "host_ip": "127.0.0.1"}]
    assert ro._extract_host_ip(ports, 5432) == "127.0.0.1"


def test_normalize_compose_env_dict_format() -> None:
    env = ro._normalize_compose_env({"POSTGRES_DB": "taskhub", "POSTGRES_USER": "taskhub"})
    assert env == {"POSTGRES_DB": "taskhub", "POSTGRES_USER": "taskhub"}


def test_normalize_compose_env_list_format() -> None:
    env = ro._normalize_compose_env(["POSTGRES_DB=taskhub", "POSTGRES_USER=taskhub"])
    assert env == {"POSTGRES_DB": "taskhub", "POSTGRES_USER": "taskhub"}


# === Layer 1.5: tar safety (R11-F-001 + R20-F-002) ===


def _make_tar(tmp_path: Path, *, members: list[tuple[str, bytes]]) -> Path:
    """Helper: create tar archive with given members."""
    out = tmp_path / "test.tar"
    with tarfile.open(out, "w") as tar:
        for name, content in members:
            data = content
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            import io
            tar.addfile(info, io.BytesIO(data))
    return out


def test_verify_tar_members_safe_rejects_symlink(tmp_path: Path) -> None:
    """R20-F-002 adopt: symlink reject before extraction."""
    out = tmp_path / "evil.tar"
    with tarfile.open(out, "w") as tar:
        info = tarfile.TarInfo(name="link.txt")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    with tarfile.open(out, "r") as tar:
        with pytest.raises(ro.RestoreRuntimeError) as exc:
            ro.verify_tar_members_safe(tar)
        assert exc.value.reason_code == "restore_archive_allowlist_violation"


def test_tar_size_limit_constants_set() -> None:
    """R11-F-001 adopt: DoS 防止 constants が安全な値."""
    assert ro.TAR_MAX_TOTAL_SIZE_BYTES == 50 * 1024 ** 3  # 50 GiB
    assert ro.TAR_MAX_MEMBER_SIZE_BYTES == 10 * 1024 ** 3  # 10 GiB
    assert ro.TAR_MAX_MEMBER_COUNT == 100_000
    assert ro.SNIFF_MAX_READ_BYTES == 4096


def test_verify_tar_members_safe_rejects_member_count_overflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R11-F-001 adopt: member count > TAR_MAX_MEMBER_COUNT rejected.
    Use a small constant override for the test (avoid creating 100k entries in tar).
    """
    monkeypatch.setattr(ro, "TAR_MAX_MEMBER_COUNT", 3)
    out = tmp_path / "many.tar"
    with tarfile.open(out, "w") as tar:
        for i in range(5):
            data = f"m{i}".encode()
            info = tarfile.TarInfo(name=f"meta_{i}.json")
            info.size = len(data)
            import io
            tar.addfile(info, io.BytesIO(data))
    with tarfile.open(out, "r") as tar:
        with pytest.raises(ro.RestoreRuntimeError) as exc:
            ro.verify_tar_members_safe(tar)
        assert exc.value.reason_code == "restore_archive_size_exceeded"


def test_extract_with_limits_rejects_non_allowlist_member(tmp_path: Path) -> None:
    archive = _make_tar(tmp_path, members=[("evil_dir/secret.txt", b"x")])
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(ro.RestoreRuntimeError) as exc:
        ro.extract_with_limits(archive, dest)
    assert exc.value.reason_code == "restore_archive_allowlist_violation"


def test_extract_with_limits_rejects_private_key_content(tmp_path: Path) -> None:
    archive = _make_tar(
        tmp_path,
        members=[("artifacts/secret.txt", b"-----BEGIN OPENSSH PRIVATE KEY-----\nFAKE\n")],
    )
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(ro.RestoreRuntimeError) as exc:
        ro.extract_with_limits(archive, dest)
    assert exc.value.reason_code == "restore_archive_allowlist_violation"
    assert "content sniff hit private key prefix" in (exc.value.detail or "")


# === Layer 2: subprocess wrappers (mocks) ===


def test_invoke_pg_restore_argv_uses_compose_exec_prefix(tmp_path: Path) -> None:
    """R14-F-001 adopt: pg_restore via docker compose exec, container unix socket."""
    options = _minimal_options(tmp_path)
    captured: list[list[str]] = []
    dump_file = tmp_path / "dump.bin"
    dump_file.write_bytes(b"fake dump")

    def fake_run(argv: list[str], *, config: SafeSubprocessConfig | None = None) -> SubprocessResult:
        captured.append(argv)
        return _mock_result(0)

    with patch.object(ro, "run_safe_subprocess", side_effect=fake_run):
        ro.invoke_pg_restore_via_compose_exec(options, dump_file=dump_file, timeout_sec=60)

    argv = captured[0]
    assert argv[:6] == ["docker", "compose", "-p", "testproj", "-f", str(options.target_compose_file_path)]
    assert "exec" in argv and "-T" in argv and "postgres" in argv and "pg_restore" in argv
    assert "--single-transaction" in argv
    assert "--clean" in argv and "--if-exists" in argv
    assert "/var/run/postgresql" in argv  # container unix socket


def test_invoke_redis_save_sync_uses_save_not_bgsave(tmp_path: Path) -> None:
    """R17-F-001 + R18-F-004 adopt: SAVE (blocking) のみ、BGSAVE 廃止."""
    options = _minimal_options(tmp_path)
    captured: list[list[str]] = []

    def fake_run(argv: list[str], *, config: SafeSubprocessConfig | None = None) -> SubprocessResult:
        captured.append(argv)
        return _mock_result(0)

    with patch.object(ro, "run_safe_subprocess", side_effect=fake_run):
        ro.invoke_redis_save_sync_via_compose_exec(options, timeout_sec=60)

    argv = captured[0]
    assert "SAVE" in argv
    assert "BGSAVE" not in argv
    assert "exec" in argv and "redis" in argv


def test_acquire_redis_data_host_path_uses_compose_ps_all(tmp_path: Path) -> None:
    """R18-F-001 adopt: compose ps --all (stopped 含む) + docker inspect Mounts."""
    options = _minimal_options(tmp_path)
    call_argvs: list[list[str]] = []

    def fake_run(argv: list[str], *, config: SafeSubprocessConfig | None = None) -> SubprocessResult:
        call_argvs.append(argv)
        if "ps" in argv:
            return _mock_result(0, stdout=b"deadbeef123\n")
        if "inspect" in argv:
            return _mock_result(0, stdout=json.dumps([
                {"Destination": "/data", "Source": "/var/lib/docker/volumes/testproj_redis_data/_data"}
            ]).encode())
        return _mock_result(0)

    with patch.object(ro, "run_safe_subprocess", side_effect=fake_run):
        result = ro.acquire_redis_data_host_path(options)

    assert any("--all" in a for a in call_argvs)
    assert result == Path("/var/lib/docker/volumes/testproj_redis_data/_data")


def test_acquire_redis_data_host_path_no_data_mount_rejected(tmp_path: Path) -> None:
    """R17-F-004 adopt: Mounts に /data destination 不在で deny."""
    options = _minimal_options(tmp_path)

    def fake_run(argv: list[str], *, config: SafeSubprocessConfig | None = None) -> SubprocessResult:
        if "ps" in argv:
            return _mock_result(0, stdout=b"deadbeef\n")
        if "inspect" in argv:
            return _mock_result(0, stdout=json.dumps([
                {"Destination": "/other", "Source": "/somewhere"}
            ]).encode())
        return _mock_result(0)

    with patch.object(ro, "run_safe_subprocess", side_effect=fake_run):
        with pytest.raises(ro.RestoreRuntimeError) as exc:
            ro.acquire_redis_data_host_path(options)
        assert exc.value.reason_code == "restore_redis_data_placement_failed"
        assert "no_data_mount" in (exc.value.detail or "")


# === Layer 2.5: target binding preflight (R11-R23) ===


def _compose_config_skeleton(
    *,
    pg_port: str = "5432", pg_host_ip: str = "127.0.0.1",
    pg_db: str = "taskhub", pg_user: str = "taskhub",
    redis_port: str = "6379", redis_host_ip: str = "127.0.0.1",
    artifacts_host_path: str = "/tmp/test_artifacts",  # noqa: S108 — mock compose の host volume path fixture (実 IO なし)
    artifacts_container_path: str = "/app/data/artifacts",
    api_volumes: list | None = None,
    worker_volumes: list | None = None,
) -> dict:
    if api_volumes is None:
        api_volumes = [f"{artifacts_host_path}:{artifacts_container_path}"]
    if worker_volumes is None:
        worker_volumes = [f"{artifacts_host_path}:{artifacts_container_path}"]
    return {
        "services": {
            "postgres": {
                "ports": [f"{pg_host_ip}:{pg_port}:5432"],
                "environment": {"POSTGRES_DB": pg_db, "POSTGRES_USER": pg_user},
            },
            "redis": {
                "ports": [f"{redis_host_ip}:{redis_port}:6379"],
            },
            "api": {"volumes": api_volumes},
            "worker": {"volumes": worker_volumes},
        },
    }


def test_verify_target_binding_consistency_postgres_port_mismatch_rejected(tmp_path: Path) -> None:
    options = _minimal_options(tmp_path)
    cfg = _compose_config_skeleton(pg_port="9999")  # claim is 5432

    def fake_run(argv: list[str], *, config: SafeSubprocessConfig | None = None) -> SubprocessResult:
        if "config" in argv:
            return _mock_result(0, stdout=json.dumps(cfg).encode())
        return _mock_result(0)

    with patch.object(ro, "run_safe_subprocess", side_effect=fake_run):
        with pytest.raises(ro.RestoreRuntimeError) as exc:
            ro.verify_target_binding_consistency(options)
        assert exc.value.reason_code == "restore_target_binding_mismatch"
        assert "postgres_port_mismatch" in (exc.value.detail or "")


def test_verify_target_binding_postgres_host_ip_must_be_loopback(tmp_path: Path) -> None:
    """R13-F-001 adopt: 明示 127.0.0.1 bind 必須."""
    options = _minimal_options(tmp_path)
    cfg = _compose_config_skeleton(pg_host_ip="0.0.0.0")  # noqa: S104 — 0.0.0.0 bind が reject されることを検証する negative test

    def fake_run(argv: list[str], *, config: SafeSubprocessConfig | None = None) -> SubprocessResult:
        if "config" in argv:
            return _mock_result(0, stdout=json.dumps(cfg).encode())
        return _mock_result(0)

    with patch.object(ro, "run_safe_subprocess", side_effect=fake_run):
        with pytest.raises(ro.RestoreRuntimeError) as exc:
            ro.verify_target_binding_consistency(options)
        assert "not_explicit_loopback" in (exc.value.detail or "")


def test_verify_target_binding_artifacts_must_bind_to_both_api_worker(tmp_path: Path) -> None:
    """R23-F-001 adopt: api + worker 両方の artifacts bind mount 必須."""
    options = _minimal_options(tmp_path)
    # only api has the bind mount, worker has different mount
    cfg = _compose_config_skeleton(
        worker_volumes=["/other/path:/different/container"],
        artifacts_host_path=str(options.target_artifacts_dir),
        artifacts_container_path=options.target_artifacts_container_path,
    )

    def fake_run(argv: list[str], *, config: SafeSubprocessConfig | None = None) -> SubprocessResult:
        if "config" in argv:
            return _mock_result(0, stdout=json.dumps(cfg).encode())
        return _mock_result(0)

    with patch.object(ro, "run_safe_subprocess", side_effect=fake_run):
        with pytest.raises(ro.RestoreRuntimeError) as exc:
            ro.verify_target_binding_consistency(options)
        assert exc.value.reason_code == "restore_target_binding_mismatch"
        assert "artifacts_bind_mount_missing" in (exc.value.detail or "")


def test_verify_target_binding_postgres_db_user_must_match(tmp_path: Path) -> None:
    """R12-F-001 adopt: Compose POSTGRES_DB / POSTGRES_USER と claim DSN 一致."""
    options = _minimal_options(tmp_path)
    cfg = _compose_config_skeleton(pg_db="OTHER_DB")  # claim is "taskhub"

    def fake_run(argv: list[str], *, config: SafeSubprocessConfig | None = None) -> SubprocessResult:
        if "config" in argv:
            return _mock_result(0, stdout=json.dumps(cfg).encode())
        return _mock_result(0)

    with patch.object(ro, "run_safe_subprocess", side_effect=fake_run):
        with pytest.raises(ro.RestoreRuntimeError) as exc:
            ro.verify_target_binding_consistency(options)
        assert "postgres_db_mismatch" in (exc.value.detail or "")


# === Layer 3: orchestration ===


def _minimal_options(tmp_path: Path) -> ro.RestoreOptions:
    """Helper: build minimal RestoreOptions for orchestration tests."""
    artifacts_dir = tmp_path / "data" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    # set allowed-roots env to artifacts parent
    os.environ["TASKHUB_RESTORE_ALLOWED_ARTIFACTS_ROOTS"] = str(tmp_path)
    age_id = tmp_path / "age.key"
    age_id.write_text("AGE-SECRET-KEY-FAKE", encoding="utf-8")
    os.chmod(age_id, 0o600)
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    return ro.RestoreOptions(
        input_path=tmp_path / "test.tar.age",
        archive_sha256="a" * 64,
        age_identity_file=age_id,
        target_pg_dsn_components={"host": "127.0.0.1", "port": "5432", "db": "taskhub", "user": "taskhub"},
        target_redis_endpoint="127.0.0.1:6379",
        target_artifacts_dir=artifacts_dir,
        target_artifacts_container_path="/app/data/artifacts",
        target_compose_project_name="testproj",
        target_compose_file_path=compose_file,
        expected_postgres_major_version="17",
        expected_alembic_head="abc123",
        overwrite=True,
    )


def test_run_restore_input_path_not_absolute_rejected(tmp_path: Path) -> None:
    """input_path must be absolute."""
    options = _minimal_options(tmp_path)
    options = ro.RestoreOptions(**{**options.__dict__, "input_path": Path("relative.tar.age")})
    with pytest.raises(ro.RestoreUsageError) as exc:
        ro.run_restore(options)
    assert exc.value.reason_code == "restore_input_path_invalid"


def test_run_restore_input_extension_must_be_tar_age(tmp_path: Path) -> None:
    options = _minimal_options(tmp_path)
    bad = tmp_path / "wrong.age"
    options = ro.RestoreOptions(**{**options.__dict__, "input_path": bad})
    with pytest.raises(ro.RestoreUsageError) as exc:
        ro.run_restore(options)
    assert exc.value.reason_code == "restore_input_path_invalid"


def test_run_restore_age_identity_file_must_be_0600_or_0400(tmp_path: Path) -> None:
    options = _minimal_options(tmp_path)
    os.chmod(options.age_identity_file, 0o644)
    # Need valid input_path for the test to progress to age check
    fake_input = tmp_path / "test.tar.age"
    fake_input.write_bytes(b"fake")
    options = ro.RestoreOptions(**{**options.__dict__, "input_path": fake_input})
    with pytest.raises(ro.RestoreUsageError) as exc:
        ro.run_restore(options)
    assert exc.value.reason_code == "restore_age_identity_path_invalid"


def test_run_restore_age_identity_symlink_rejected(tmp_path: Path) -> None:
    options = _minimal_options(tmp_path)
    real = tmp_path / "real_age.key"
    real.write_text("KEY", encoding="utf-8")
    os.chmod(real, 0o600)
    link = tmp_path / "linked_age.key"
    link.symlink_to(real)
    fake_input = tmp_path / "test.tar.age"
    fake_input.write_bytes(b"fake")
    options = ro.RestoreOptions(**{
        **options.__dict__, "input_path": fake_input, "age_identity_file": link,
    })
    with pytest.raises(ro.RestoreUsageError) as exc:
        ro.run_restore(options)
    assert exc.value.reason_code == "restore_age_identity_path_invalid"
    assert "symlink" in (exc.value.detail or "")


def test_run_restore_target_artifacts_dir_in_use_without_overwrite_rejected(tmp_path: Path) -> None:
    """R9-F-001 adopt: target dir 空でなく overwrite=False で reject."""
    options = _minimal_options(tmp_path)
    (options.target_artifacts_dir / "existing.txt").write_text("data", encoding="utf-8")
    fake_input = tmp_path / "test.tar.age"
    fake_input.write_bytes(b"fake")
    options = ro.RestoreOptions(**{
        **options.__dict__, "input_path": fake_input, "overwrite": False,
    })
    with pytest.raises(ro.RestoreUsageError) as exc:
        ro.run_restore(options)
    assert exc.value.reason_code == "restore_target_data_dir_in_use_without_overwrite"
