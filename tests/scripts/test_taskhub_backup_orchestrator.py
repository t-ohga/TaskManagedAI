"""SP022-T02 Phase 2 / T08 batch 2 — backup orchestrator unit tests.

R1 14 + R2 2 + R3 1 = 17 plan-review findings adopt 反映後の verification。

Layer 1 (pure functions): meta.json / checksums.txt / temp layout / archive allowlist
Layer 2 (subprocess mocks): pg_dump / redis-cli / age via unittest.mock + fake tool fixtures
Layer 3 (orchestration): run_backup full sequence with mocked subprocesses
Layer 4 (integration stubs): real tool path → SP022-T09 carry-over (`tests/deploy/`)
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import taskhub_backup_orchestrator as bo
from scripts.taskhub_subprocess_runner import SubprocessResult

# --- Layer 1: pure functions ---


def test_build_meta_json_includes_required_fields() -> None:
    """R2-F-005 PR #77 retro-fix: field name 統一 (host→host_name, timestamp→timestamp_utc,
    backup_format_version→format_version)."""
    ts = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
    meta = bo.build_meta_json(
        host_name="t-ohga-mac",
        timestamp_utc=ts,
        postgres_version="17.0",
        redis_version="7.4",
        alembic_head="abc123def456",
    )
    assert meta["host_name"] == "t-ohga-mac"
    assert meta["timestamp_utc"] == "2026-05-20T12:00:00Z"
    assert meta["postgres_version"] == "17.0"
    assert meta["redis_version"] == "7.4"
    assert meta["alembic_head"] == "abc123def456"
    assert meta["format_version"] == "1.0"
    # 旧 field 名 (host / timestamp / backup_format_version) は absence verify
    assert "host" not in meta
    assert "timestamp" not in meta
    assert "backup_format_version" not in meta


def test_build_checksums_text_deterministic(tmp_path: Path) -> None:
    f1 = tmp_path / "a.txt"
    f1.write_text("hello", encoding="utf-8")
    f2 = tmp_path / "b.txt"
    f2.write_text("world", encoding="utf-8")
    text = bo.build_checksums_text({"a.txt": f1, "b.txt": f2})
    # sha256sum 互換 format: "<hex>  <path>\n"
    assert text == (
        f"{hashlib.sha256(b'hello').hexdigest()}  a.txt\n"
        f"{hashlib.sha256(b'world').hexdigest()}  b.txt\n"
    )


def test_build_checksums_text_excludes_self(tmp_path: Path) -> None:
    f = tmp_path / "x.txt"
    f.write_text("data", encoding="utf-8")
    cf = tmp_path / "checksums.txt"
    cf.write_text("ignored", encoding="utf-8")
    text = bo.build_checksums_text({"x.txt": f, "checksums.txt": cf})
    assert "checksums.txt" not in text  # self excluded
    assert "x.txt" in text


def test_build_checksums_text_byte_lex_sort(tmp_path: Path) -> None:
    files = {}
    for name in ["zebra.txt", "alpha.txt", "beta.txt"]:
        f = tmp_path / name
        f.write_text(name, encoding="utf-8")
        files[name] = f
    text = bo.build_checksums_text(files)
    lines = text.strip().split("\n")
    paths_in_order = [line.split("  ", 1)[1] for line in lines]
    assert paths_in_order == ["alpha.txt", "beta.txt", "zebra.txt"]


def test_resolve_backup_temp_layout_creates_0700(tmp_path: Path) -> None:
    """R2-F-002 + F-002 adopt: mode=0o700 verify."""
    layout = bo.resolve_backup_temp_layout(parent_dir=tmp_path)
    actual_mode = stat.S_IMODE(layout.stat().st_mode)
    assert actual_mode == 0o700
    shutil.rmtree(layout)


def test_check_archive_allowed_rejects_id_rsa(tmp_path: Path) -> None:
    """F-001 adopt: SSH private key filename reject."""
    f = tmp_path / "id_rsa"
    f.write_bytes(b"ssh-rsa private key content")
    allowed, reason = bo.check_archive_allowed("artifacts/secret/id_rsa", f)
    assert not allowed
    assert "id_rsa" in reason or "filename_pattern" in reason


def test_check_archive_allowed_rejects_age_secret_content(tmp_path: Path) -> None:
    """F-001 adopt: AGE-SECRET-KEY- content prefix reject."""
    f = tmp_path / "innocent_name.txt"
    f.write_bytes(b"AGE-SECRET-KEY-1ABCDEF12345...")
    allowed, reason = bo.check_archive_allowed("artifacts/innocent_name.txt", f)
    assert not allowed
    assert "content_prefix" in reason or "AGE-SECRET-KEY" in reason


def test_check_archive_allowed_rejects_openssh_content(tmp_path: Path) -> None:
    f = tmp_path / "harmless.txt"
    f.write_bytes(b"-----BEGIN OPENSSH PRIVATE KEY-----\nfake content")
    allowed, reason = bo.check_archive_allowed("artifacts/harmless.txt", f)
    assert not allowed
    assert "content_prefix" in reason


def test_check_archive_allowed_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("data", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    allowed, reason = bo.check_archive_allowed("artifacts/link.txt", link)
    assert not allowed
    assert "symlink" in reason


def test_check_archive_allowed_rejects_not_in_allowlist(tmp_path: Path) -> None:
    f = tmp_path / "random.txt"
    f.write_text("hello", encoding="utf-8")
    allowed, reason = bo.check_archive_allowed("some/random/path.txt", f)
    assert not allowed
    assert "not_in_allowlist" in reason


def test_check_archive_allowed_accepts_normal_artifacts(tmp_path: Path) -> None:
    f = tmp_path / "normal.txt"
    f.write_text("Hello, world!", encoding="utf-8")
    allowed, reason = bo.check_archive_allowed("artifacts/normal.txt", f)
    assert allowed
    assert reason == ""


def test_backup_options_from_environment_uses_defaults(tmp_path: Path) -> None:
    """F-007 adopt: defaults precedence (no env override)."""
    # clean specific env vars
    for var in [
        "TASKHUB_BACKUP_PG_HOST", "TASKHUB_BACKUP_PG_PORT",
        "TASKHUB_BACKUP_REDIS_HOST", "TASKHUB_BACKUP_REDIS_PORT",
    ]:
        os.environ.pop(var, None)
    options = bo.BackupOptions.from_environment(
        output_path=tmp_path / "out.tar.age",
        repo_root=tmp_path,
    )
    assert options.pg_host == "127.0.0.1"
    assert options.pg_port == 5432
    assert options.redis_host == "127.0.0.1"
    assert options.redis_port == 6379


def test_backup_options_from_environment_uses_env_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """F-007 adopt: env override precedence."""
    monkeypatch.setenv("TASKHUB_BACKUP_PG_HOST", "db.example.com")
    monkeypatch.setenv("TASKHUB_BACKUP_PG_PORT", "9999")
    options = bo.BackupOptions.from_environment(
        output_path=tmp_path / "out.tar.age",
        repo_root=tmp_path,
    )
    assert options.pg_host == "db.example.com"
    assert options.pg_port == 9999


# --- Layer 2: subprocess mocks ---


def _mock_subprocess_result(returncode: int = 0, stdout: bytes = b"") -> SubprocessResult:
    return SubprocessResult(
        command_name="mock",
        arg_count=1,
        returncode=returncode,
        stdout=stdout,
        stderr_sanitized="",
        duration_sec=0.0,
        sanitized_flags=(),
    )


def test_acquire_postgres_version_parses_output() -> None:
    """F-008 adopt: pg_dump --version 出力 parse."""
    with patch.object(bo, "run_safe_subprocess") as mock_run:
        mock_run.return_value = _mock_subprocess_result(
            returncode=0,
            stdout=b"pg_dump (PostgreSQL) 17.0\n",
        )
        version = bo.acquire_postgres_version()
        assert version == "17.0"


def test_acquire_postgres_version_parse_failed_raises() -> None:
    with patch.object(bo, "run_safe_subprocess") as mock_run:
        mock_run.return_value = _mock_subprocess_result(
            returncode=0,
            stdout=b"unexpected version banner",
        )
        with pytest.raises(bo.BackupRuntimeError) as exc_info:
            bo.acquire_postgres_version()
        assert exc_info.value.reason_code == "backup_meta_json_acquisition_failed"


def test_acquire_redis_version_parses_output() -> None:
    """F-008 adopt: redis-cli INFO server parse."""
    with patch.object(bo, "run_safe_subprocess") as mock_run:
        mock_run.return_value = _mock_subprocess_result(
            returncode=0,
            stdout=b"# Server\r\nredis_version:7.4.2\r\nother:foo\r\n",
        )
        version = bo.acquire_redis_version("127.0.0.1", 6379)
        assert version == "7.4.2"


def test_invoke_age_encrypt_argv_uses_public_key_only(tmp_path: Path) -> None:
    """F-001 adopt: age subprocess argv に public key のみ、private key path を含まない."""
    pub_key_path = tmp_path / "age.pub"
    pub_key_path.write_text("age1example_public_key_content", encoding="utf-8")
    input_path = tmp_path / "input.tar"
    input_path.write_bytes(b"fake")
    output_path = tmp_path / "out.tar.age"
    captured_argv: list[list[str]] = []

    def fake_run(argv: list[str], *, config: object) -> SubprocessResult:
        captured_argv.append(argv)
        # simulate age writing output
        output_path.write_bytes(b"encrypted")
        return _mock_subprocess_result(returncode=0)

    with patch.object(bo, "run_safe_subprocess", side_effect=fake_run):
        result = bo.invoke_age_encrypt(
            input_path=input_path,
            output_path=output_path,
            public_key_path=pub_key_path,
            timeout_sec=60,
        )
    assert result.returncode == 0
    assert captured_argv
    argv = captured_argv[0]
    # argv: ["age", "-r", "<public_key>", "-o", "<output>", "<input>"]
    assert "age" in argv[0]
    assert "-r" in argv
    assert "age1example_public_key_content" in argv
    # No "decrypt" / "-i" (identity/private key) flag
    assert "-i" not in argv
    assert "--identity" not in argv


def test_invoke_age_encrypt_public_key_missing_raises(tmp_path: Path) -> None:
    pub_key_path = tmp_path / "nonexistent.pub"
    input_path = tmp_path / "input.tar"
    input_path.write_bytes(b"fake")
    output_path = tmp_path / "out.tar.age"
    with pytest.raises(bo.BackupRuntimeError) as exc_info:
        bo.invoke_age_encrypt(
            input_path=input_path,
            output_path=output_path,
            public_key_path=pub_key_path,
            timeout_sec=60,
        )
    assert exc_info.value.reason_code == "backup_age_encrypt_failed"
    assert "public_key_not_found" in exc_info.value.detail


def test_invoke_pg_dump_tool_not_found_raises(tmp_path: Path) -> None:
    """F-009 adopt: tool not found → BackupToolNotFoundError exit 2."""
    from scripts.taskhub_subprocess_runner import SubprocessNotFoundError

    with patch.object(
        bo, "run_safe_subprocess",
        side_effect=SubprocessNotFoundError("pg_dump"),
    ):
        with pytest.raises(bo.BackupToolNotFoundError) as exc_info:
            bo.invoke_pg_dump(
                pg_host="localhost", pg_port=5432, pg_user="u", pg_db="d",
                output_path=tmp_path / "x.dump",
                pgpassfile=None, timeout_sec=60,
            )
        assert exc_info.value.reason_code == "backup_pg_dump_tool_not_found"


def test_invoke_pg_dump_custom_format_omits_single_transaction(tmp_path: Path) -> None:
    """SP-022-1: pg_dump custom format must not pass --single-transaction."""
    with patch.object(
        bo,
        "_run_subprocess_with_tool_check",
        return_value=_mock_subprocess_result(),
    ) as mock_run:
        bo.invoke_pg_dump(
            pg_host="localhost",
            pg_port=5432,
            pg_user="u",
            pg_db="d",
            output_path=tmp_path / "x.dump",
            pgpassfile=None,
            timeout_sec=60,
        )

    argv = mock_run.call_args.args[0]
    assert "--format=custom" in argv
    assert "--single-transaction" not in argv


def test_invoke_pg_dump_via_compose_exec_omits_single_transaction(tmp_path: Path) -> None:
    """SP-022-1: compose-exec pg_dump custom format omits --single-transaction too."""
    options = bo.BackupOptions(
        output_path=tmp_path / "out.tar.age",
        host_name="host",
        include_sops_env=False,
        skip_service_stop=False,
        overwrite=False,
        age_public_key_path=tmp_path / "age.pub",
        pg_host="localhost",
        pg_port=5432,
        pg_user="taskmanagedai",
        pg_db="taskmanagedai",
        redis_host="localhost",
        redis_port=6379,
        artifacts_dir=tmp_path / "artifacts",
        sops_env_path=tmp_path / ".env.local",
    )
    with (
        patch.object(bo, "_compose_argv_prefix", return_value=["docker", "compose"]),
        patch.object(
            bo,
            "_run_subprocess_with_tool_check",
            return_value=_mock_subprocess_result(),
        ) as mock_run,
    ):
        bo.invoke_pg_dump_via_compose_exec(
            options,
            output_path=tmp_path / "x.dump",
            timeout_sec=60,
        )

    argv = mock_run.call_args.args[0]
    assert "--format=custom" in argv
    assert "--single-transaction" not in argv


def test_backup_source_path_allowlist_accepts_repo_etc_var_lib(tmp_path: Path) -> None:
    """SP-022-1: backup source binding allowlist is shared and explicit."""
    repo_root = tmp_path / "repo"
    expected_repo_root = repo_root.resolve(strict=False)
    assert bo.backup_path_allowed_roots(repo_root) == (
        expected_repo_root,
        Path("/etc"),
        Path("/var/lib"),
    )

    bo.validate_backup_source_path_allowed(
        path=expected_repo_root / "docker-compose.yml",
        repo_root=repo_root,
        field_name="target_compose_file_path",
    )
    bo.validate_backup_source_path_allowed(
        path=Path("/etc/taskmanagedai/.env.local"),
        repo_root=repo_root,
        field_name="env_file_path",
    )
    bo.validate_backup_source_path_allowed(
        path=Path("/var/lib/taskmanagedai/.env.local"),
        repo_root=repo_root,
        field_name="env_file_path",
    )


def test_backup_source_path_allowlist_rejects_unlisted_root(tmp_path: Path) -> None:
    """SP-022-1: backup source binding rejects roots outside repo_root/etc/var/lib."""
    with pytest.raises(bo.BackupUsageError) as exc_info:
        bo.validate_backup_source_path_allowed(
            path=Path("/srv/evil/docker-compose.yml"),
            repo_root=tmp_path,
            field_name="target_compose_file_path",
        )

    assert exc_info.value.reason_code == "backup_output_path_invalid"
    detail = exc_info.value.detail or ""
    assert "repo_root / /etc / /var/lib" in detail


# --- Layer 3: orchestration with full mocks ---


def _setup_mock_backup_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict:
    """Common fixture: mock all subprocess wrappers + age pub key + paths."""
    age_pub = tmp_path / "age.pub"
    age_pub.write_text("age1mockedpublickey", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "data.txt").write_text("artifact data", encoding="utf-8")
    output = tmp_path / "backup.tar.age"

    # F-PR77-003 adopt: pgpassfile は run_backup 必須 invariant (0600 + 通常 file)
    pgpass = tmp_path / ".pgpass"
    pgpass.write_text("127.0.0.1:5432:taskhub:taskhub:fakepw\n", encoding="utf-8")
    os.chmod(pgpass, 0o600)

    return {
        "age_pub": age_pub,
        "artifacts": artifacts,
        "output": output,
        "pgpass": pgpass,
    }


def test_run_backup_full_sequence_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Layer 3: orchestration success path with full mocks."""
    env = _setup_mock_backup_env(monkeypatch, tmp_path)

    def fake_acquire_pg() -> str:
        return "17.0"

    def fake_acquire_redis(host: str, port: int) -> str:
        return "7.4"

    def fake_acquire_alembic(repo_root: Path | None = None) -> str:
        return "abc123"

    def fake_invoke_pg_dump(**kwargs: object) -> SubprocessResult:
        # Pre-place the output file
        output_path = kwargs["output_path"]
        assert isinstance(output_path, Path)
        output_path.write_bytes(b"fake pg dump custom format")
        return _mock_subprocess_result(returncode=0)

    def fake_invoke_redis_rdb(**kwargs: object) -> SubprocessResult:
        output_path = kwargs["output_path"]
        assert isinstance(output_path, Path)
        output_path.write_bytes(b"fake rdb")
        return _mock_subprocess_result(returncode=0)

    def fake_invoke_age_encrypt(**kwargs: object) -> SubprocessResult:
        output_path = kwargs["output_path"]
        assert isinstance(output_path, Path)
        output_path.write_bytes(b"fake age encrypted output")
        return _mock_subprocess_result(returncode=0)

    monkeypatch.setattr(bo, "acquire_postgres_version", fake_acquire_pg)
    monkeypatch.setattr(bo, "acquire_redis_version", fake_acquire_redis)
    monkeypatch.setattr(bo, "acquire_alembic_head", fake_acquire_alembic)
    monkeypatch.setattr(bo, "invoke_pg_dump", fake_invoke_pg_dump)
    monkeypatch.setattr(bo, "invoke_redis_rdb", fake_invoke_redis_rdb)
    monkeypatch.setattr(bo, "invoke_age_encrypt", fake_invoke_age_encrypt)

    options = bo.BackupOptions.from_environment(
        output_path=env["output"],
        repo_root=tmp_path,
    )
    # override age_public_key_path / artifacts_dir to test fixtures
    options = bo.BackupOptions(**{
        **options.__dict__,
        "age_public_key_path": env["age_pub"],
        "artifacts_dir": env["artifacts"],
        "pgpassfile_path": env["pgpass"],
    })

    result = bo.run_backup(options)
    assert result.reason_code == "backup_completed"
    assert result.postgres_version == "17.0"
    assert result.redis_version == "7.4"
    assert result.alembic_head == "abc123"
    assert result.output_path == env["output"]
    assert env["output"].exists()


def test_run_backup_output_already_exists_without_overwrite_rejected(
    tmp_path: Path,
) -> None:
    """F-005 + output_already_exists invariant."""
    env_setup = _setup_mock_backup_env(pytest.MonkeyPatch(), tmp_path)
    env_setup["output"].write_bytes(b"existing")
    options = bo.BackupOptions.from_environment(
        output_path=env_setup["output"],
        repo_root=tmp_path,
        overwrite=False,
    )
    options = bo.BackupOptions(
        **{**options.__dict__, "age_public_key_path": env_setup["age_pub"], "artifacts_dir": env_setup["artifacts"]}
    )
    with pytest.raises(bo.BackupUsageError) as exc_info:
        bo.run_backup(options)
    assert exc_info.value.reason_code == "backup_output_already_exists"


def test_run_backup_invalid_extension_rejected(tmp_path: Path) -> None:
    """output_path invalid extension."""
    options = bo.BackupOptions.from_environment(
        output_path=tmp_path / "wrong.txt",  # not .tar.age
        repo_root=tmp_path,
    )
    with pytest.raises(bo.BackupUsageError) as exc_info:
        bo.run_backup(options)
    assert exc_info.value.reason_code == "backup_output_path_invalid"


def test_run_backup_archive_allowlist_violation_in_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """F-001 adopt: artifacts/ 配下に private key → reject."""
    age_pub = tmp_path / "age.pub"
    age_pub.write_text("age1mockedpublickey", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    # plant a private key in artifacts/
    (artifacts / "id_rsa").write_bytes(b"-----BEGIN OPENSSH PRIVATE KEY-----\nfake")
    # F-PR77-003 adopt: pgpassfile 必須
    pgpass = tmp_path / ".pgpass"
    pgpass.write_text("127.0.0.1:5432:taskhub:taskhub:fakepw\n", encoding="utf-8")
    os.chmod(pgpass, 0o600)

    monkeypatch.setattr(bo, "acquire_postgres_version", lambda: "17.0")
    monkeypatch.setattr(bo, "acquire_redis_version", lambda h, p: "7.4")
    monkeypatch.setattr(bo, "acquire_alembic_head", lambda r=None: "abc")
    monkeypatch.setattr(bo, "invoke_pg_dump",
                        lambda **kw: (kw["output_path"].write_bytes(b"x"), _mock_subprocess_result(0))[1])
    monkeypatch.setattr(bo, "invoke_redis_rdb",
                        lambda **kw: (kw["output_path"].write_bytes(b"x"), _mock_subprocess_result(0))[1])

    options = bo.BackupOptions.from_environment(
        output_path=tmp_path / "out.tar.age", repo_root=tmp_path,
    )
    options = bo.BackupOptions(**{
        **options.__dict__,
        "age_public_key_path": age_pub,
        "artifacts_dir": artifacts,
        "pgpassfile_path": pgpass,
    })

    with pytest.raises(bo.BackupRuntimeError) as exc_info:
        bo.run_backup(options)
    assert exc_info.value.reason_code == "backup_archive_allowlist_violation"


def test_run_backup_pg_dump_failure_cleans_tmp_and_no_partial_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """F-002 + F-005 adopt: pg_dump 失敗で tmp cleanup + .part / final 出力なし."""
    env = _setup_mock_backup_env(monkeypatch, tmp_path)
    monkeypatch.setattr(bo, "acquire_postgres_version", lambda: "17.0")
    monkeypatch.setattr(bo, "acquire_redis_version", lambda h, p: "7.4")
    monkeypatch.setattr(bo, "acquire_alembic_head", lambda r=None: "abc")
    # pg_dump fails
    monkeypatch.setattr(bo, "invoke_pg_dump",
                        lambda **kw: _mock_subprocess_result(returncode=1))

    options = bo.BackupOptions.from_environment(
        output_path=env["output"], repo_root=tmp_path,
    )
    options = bo.BackupOptions(**{
        **options.__dict__,
        "age_public_key_path": env["age_pub"],
        "artifacts_dir": env["artifacts"],
        "pgpassfile_path": env["pgpass"],
    })
    with pytest.raises(bo.BackupRuntimeError) as exc_info:
        bo.run_backup(options)
    assert exc_info.value.reason_code == "backup_pg_dump_failed"
    # final output should not exist
    assert not env["output"].exists()
    # part file should not exist
    part_path = env["output"].with_name(env["output"].name + ".part")
    assert not part_path.exists()


# --- F-PR77-003 fail-closed invariant tests ---


def test_run_backup_rejects_when_pgpassfile_not_provided(tmp_path: Path) -> None:
    """F-PR77-003 adopt: pgpassfile_path=None で run_backup は fail-closed (~/.pgpass 暗黙 fallback 禁止)."""
    age_pub = tmp_path / "age.pub"
    age_pub.write_text("age1mocked", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    options = bo.BackupOptions.from_environment(
        output_path=tmp_path / "out.tar.age", repo_root=tmp_path,
    )
    # explicitly set pgpassfile_path to None (no env, no override)
    options = bo.BackupOptions(
        **{**options.__dict__, "age_public_key_path": age_pub, "artifacts_dir": artifacts, "pgpassfile_path": None}
    )
    with pytest.raises(bo.BackupUsageError) as exc_info:
        bo.run_backup(options)
    assert exc_info.value.reason_code == "backup_output_path_invalid"
    assert "pgpassfile_path required" in (exc_info.value.detail or "")


def test_run_backup_rejects_pgpassfile_with_world_readable_permissions(
    tmp_path: Path,
) -> None:
    """F-PR77-003 adopt: pgpassfile permission != 0600/0400 → reject."""
    age_pub = tmp_path / "age.pub"
    age_pub.write_text("age1mocked", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    # bad permissions: world readable
    pgpass = tmp_path / ".pgpass"
    pgpass.write_text("127.0.0.1:5432:taskhub:taskhub:fakepw\n", encoding="utf-8")
    os.chmod(pgpass, 0o644)

    options = bo.BackupOptions.from_environment(
        output_path=tmp_path / "out.tar.age", repo_root=tmp_path,
    )
    options = bo.BackupOptions(
        **{**options.__dict__, "age_public_key_path": age_pub, "artifacts_dir": artifacts, "pgpassfile_path": pgpass}
    )
    with pytest.raises(bo.BackupUsageError) as exc_info:
        bo.run_backup(options)
    assert exc_info.value.reason_code == "backup_output_path_invalid"
    assert "permission" in (exc_info.value.detail or "")


def test_run_backup_rejects_symlink_pgpassfile(tmp_path: Path) -> None:
    """F-PR77-003 adopt: pgpassfile が symlink → reject (TOCTOU + symlink follow 防止)."""
    age_pub = tmp_path / "age.pub"
    age_pub.write_text("age1mocked", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    real_pgpass = tmp_path / ".pgpass.real"
    real_pgpass.write_text("127.0.0.1:5432:taskhub:taskhub:fakepw\n", encoding="utf-8")
    os.chmod(real_pgpass, 0o600)
    symlink_pgpass = tmp_path / ".pgpass"
    symlink_pgpass.symlink_to(real_pgpass)

    options = bo.BackupOptions.from_environment(
        output_path=tmp_path / "out.tar.age", repo_root=tmp_path,
    )
    options = bo.BackupOptions(**{
        **options.__dict__,
        "age_public_key_path": age_pub,
        "artifacts_dir": artifacts,
        "pgpassfile_path": symlink_pgpass,
    })
    with pytest.raises(bo.BackupUsageError) as exc_info:
        bo.run_backup(options)
    assert exc_info.value.reason_code == "backup_output_path_invalid"
    assert "symlink" in (exc_info.value.detail or "")


# --- F-PR77-004 env port int parse tests ---


def test_backup_options_rejects_non_integer_env_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """F-PR77-004 adopt: env port が非数値なら BackupUsageError (ValueError 漏れない)."""
    monkeypatch.setenv("TASKHUB_BACKUP_PG_PORT", "not_a_number")
    with pytest.raises(bo.BackupUsageError) as exc_info:
        bo.BackupOptions.from_environment(
            output_path=tmp_path / "out.tar.age", repo_root=tmp_path,
        )
    assert exc_info.value.reason_code == "backup_output_path_invalid"
    assert "TASKHUB_BACKUP_PG_PORT" in (exc_info.value.detail or "")


def test_backup_options_rejects_env_port_out_of_range(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """F-PR77-004 adopt: env port が範囲外なら BackupUsageError."""
    monkeypatch.setenv("TASKHUB_BACKUP_REDIS_PORT", "99999")
    with pytest.raises(bo.BackupUsageError) as exc_info:
        bo.BackupOptions.from_environment(
            output_path=tmp_path / "out.tar.age", repo_root=tmp_path,
        )
    assert exc_info.value.reason_code == "backup_output_path_invalid"
    assert "TASKHUB_BACKUP_REDIS_PORT" in (exc_info.value.detail or "")


# --- F-PR77-002 strict .tar.age extension check ---


def test_run_backup_rejects_age_only_extension(tmp_path: Path) -> None:
    """F-PR77-002 adopt: .age 単独拡張子は .tar.age チェーン違反として reject."""
    options = bo.BackupOptions.from_environment(
        output_path=tmp_path / "wrong.age",  # .tar が欠落
        repo_root=tmp_path,
    )
    with pytest.raises(bo.BackupUsageError) as exc_info:
        bo.run_backup(options)
    assert exc_info.value.reason_code == "backup_output_path_invalid"
    assert ".tar.age" in (exc_info.value.detail or "")


# --- SP022-T02 Phase 5 unit tests (codex-all-loops 75 findings 100% adopt 後の core invariants) ---


def test_phase5_validate_age_recipient_bytes_accepts_valid_age1() -> None:
    """ADV R3 F-001 + ADV2 R1 F-006: 有効な age1 prefix + 58 chars bech32 → accept."""
    # age v1 仕様: "age1" + 58 chars bech32 base32 (total 62 chars)
    valid_recipient = "age1" + "a" * 58
    assert len(valid_recipient) == 62  # "age1" + 58 chars = 62
    result = bo.validate_age_recipient_bytes(valid_recipient.encode("ascii"))
    assert result == valid_recipient


def test_phase5_validate_age_recipient_bytes_rejects_non_ascii() -> None:
    """ADV2 R1 F-006: non-ASCII bytes → backup_age_recipient_invalid."""
    with pytest.raises(bo.BackupRuntimeError) as exc_info:
        bo.validate_age_recipient_bytes(b"\xff\xfeage1invalid")
    assert exc_info.value.reason_code == "backup_age_recipient_invalid"


def test_phase5_validate_age_recipient_bytes_rejects_multiline() -> None:
    """ADV2 R1 F-006: multi-line content → backup_age_recipient_invalid."""
    multiline = b"age1qrs0t9u8v7w6x5y4z3a2b1c0defghijklmnopqrstuvwxyz0123456789ab\nextra"
    with pytest.raises(bo.BackupRuntimeError) as exc_info:
        bo.validate_age_recipient_bytes(multiline)
    assert exc_info.value.reason_code == "backup_age_recipient_invalid"


def test_phase5_validate_age_recipient_bytes_rejects_wrong_prefix() -> None:
    """ADV R3 F-001: age1 prefix 以外 → backup_age_recipient_invalid."""
    with pytest.raises(bo.BackupRuntimeError) as exc_info:
        bo.validate_age_recipient_bytes(b"ssh-rsa AAAAB3...")
    assert exc_info.value.reason_code == "backup_age_recipient_invalid"


def test_phase5_validate_age_recipient_bytes_rejects_oversized() -> None:
    """ADV2 R1 F-006: 200 chars 超 → backup_age_recipient_invalid."""
    oversized = b"age1" + b"a" * 250
    with pytest.raises(bo.BackupRuntimeError) as exc_info:
        bo.validate_age_recipient_bytes(oversized)
    assert exc_info.value.reason_code == "backup_age_recipient_invalid"


def test_phase5_compose_argv_prefix_requires_verified_bind(tmp_path: Path) -> None:
    """ADV R7 F-001: verified_compose_execution_input 未 bind 時は fail-closed."""
    monkeypatch_env_for_phase5(tmp_path)
    options = bo.BackupOptions.from_environment(
        output_path=tmp_path / "out.tar.age", repo_root=tmp_path,
    )
    # verified copy 未 bind 状態で _compose_argv_prefix 呼出 → fail-closed
    with pytest.raises(bo.BackupRuntimeError) as exc_info:
        bo._compose_argv_prefix(options)
    assert exc_info.value.reason_code == "backup_compose_binding_not_initialized"


def monkeypatch_env_for_phase5(tmp_path: Path) -> None:
    """Helper: Phase 5 用 test env を準備 (compose file + env_file 作成)."""
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  postgres:\n    image: postgres:16\n", encoding="utf-8",
    )
    (tmp_path / ".env.local").write_text("FOO=bar\n", encoding="utf-8")
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "artifacts").mkdir(exist_ok=True)


def test_phase5_compute_artifacts_dir_manifest_sha256_lstat_mode(tmp_path: Path) -> None:
    """ADV2 R6 F-003 + R7 F-003: regular file + directory のみ accept、source mode を canonical entry に."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "foo.txt").write_text("hello", encoding="utf-8")
    (artifacts / "sub").mkdir()
    (artifacts / "sub" / "bar.txt").write_text("world", encoding="utf-8")
    sha = bo._compute_artifacts_dir_manifest_sha256(artifacts, mode_source="lstat")
    # deterministic (sorted by path + canonical JSON)
    sha_again = bo._compute_artifacts_dir_manifest_sha256(artifacts, mode_source="lstat")
    assert sha == sha_again
    assert len(sha) == 64  # SHA-256 hex


def test_phase5_compute_artifacts_dir_manifest_sha256_rejects_symlink(tmp_path: Path) -> None:
    """ADV2 R6 F-003 + R11 F-002: symlink → backup_artifacts_source_unsupported_file_type."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    target = tmp_path / "external_target.txt"
    target.write_text("external", encoding="utf-8")
    (artifacts / "link").symlink_to(target)
    with pytest.raises(bo.BackupRuntimeError) as exc_info:
        bo._compute_artifacts_dir_manifest_sha256(artifacts, mode_source="lstat")
    assert exc_info.value.reason_code == "backup_artifacts_source_unsupported_file_type"


def test_phase5_compute_artifacts_dir_manifest_sha256_rejects_reserved_name(tmp_path: Path) -> None:
    """ADV2 R8 F-002: source tree に reserved name → backup_artifacts_source_reserved_name."""
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "_artifacts_source_mode.json").write_text("{}", encoding="utf-8")
    with pytest.raises(bo.BackupRuntimeError) as exc_info:
        bo._compute_artifacts_dir_manifest_sha256(artifacts, mode_source="lstat")
    assert exc_info.value.reason_code == "backup_artifacts_source_reserved_name"


def test_phase5_verified_copy_tree_no_follow_creates_staging(tmp_path: Path) -> None:
    """ADV2 R5 F-002: source tree を no-follow walk + O_NOFOLLOW で dst に copy."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "data.txt").write_text("hello", encoding="utf-8")
    (src / "sub").mkdir()
    (src / "sub" / "nested.txt").write_text("world", encoding="utf-8")
    dst = tmp_path / "dst"
    sidecar = tmp_path / "sidecar.json"
    root_anchor = os.lstat(str(src))
    bo._verified_copy_tree_no_follow(
        src=src, dst=dst, root_lstat_anchor=root_anchor,
        source_mode_sidecar_path=sidecar,
    )
    assert (dst / "data.txt").read_text(encoding="utf-8") == "hello"
    assert (dst / "sub" / "nested.txt").read_text(encoding="utf-8") == "world"
    # ADV2 R8 F-002: sidecar が staging tree の外 (tmp_path 直下) に書出されている
    assert sidecar.exists()
    assert not (dst / "_artifacts_source_mode.json").exists()


def test_phase5_verified_copy_tree_no_follow_rejects_oversized_file(tmp_path: Path) -> None:
    """ADV2 R6 F-003: per-file 256 MiB 超 → backup_artifacts_file_too_large."""
    src = tmp_path / "src"
    src.mkdir()
    big = src / "huge.bin"
    # 模擬 256 MiB+1 byte file (sparse file で時間短縮)
    with big.open("wb") as f:
        f.seek(bo.MAX_ARTIFACT_FILE_BYTES)
        f.write(b"x")
    dst = tmp_path / "dst"
    sidecar = tmp_path / "sidecar.json"
    with pytest.raises(bo.BackupRuntimeError) as exc_info:
        bo._verified_copy_tree_no_follow(
            src=src, dst=dst,
            root_lstat_anchor=os.lstat(str(src)),
            source_mode_sidecar_path=sidecar,
        )
    assert exc_info.value.reason_code == "backup_artifacts_file_too_large"


def test_phase5_compute_full_fingerprint_issue_redeem_algorithm_canonical(tmp_path: Path) -> None:
    """ADV2 R3 F-001 + R7 F-001: single full-helper が canonical schema で deterministic.

    issue / redeem 両 mode が同 BackupOptions + 同 content で **同じ fingerprint** を返す
    (mock 経由で docker compose config を bypass、source path 直接読込 path の deterministic 確認)。
    """
    monkeypatch_env_for_phase5(tmp_path)
    options = bo.BackupOptions.from_environment(
        output_path=tmp_path / "out.tar.age", repo_root=tmp_path,
    )
    # docker compose config は本 test では mock (helper の canonical 部分のみ verify)
    fp1 = bo.compute_backup_runtime_binding_fingerprint(
        options,
        compose_file_sha256="aa" * 32,
        sops_env_sha256=None,
        compose_config_canonical_sha256="bb" * 32,
        env_file_sha256="cc" * 32,
        artifacts_dir_manifest_sha256="dd" * 32,
    )
    fp2 = bo.compute_backup_runtime_binding_fingerprint(
        options,
        compose_file_sha256="aa" * 32,
        sops_env_sha256=None,
        compose_config_canonical_sha256="bb" * 32,
        env_file_sha256="cc" * 32,
        artifacts_dir_manifest_sha256="dd" * 32,
    )
    assert fp1 == fp2
    assert len(fp1) == 64


def test_phase5_compute_full_fingerprint_changes_with_compose_sha(tmp_path: Path) -> None:
    """ADV2 R3 F-002: compose_file_sha256 が変われば fingerprint も変わる (binding 完全性)."""
    monkeypatch_env_for_phase5(tmp_path)
    options = bo.BackupOptions.from_environment(
        output_path=tmp_path / "out.tar.age", repo_root=tmp_path,
    )
    fp_a = bo.compute_backup_runtime_binding_fingerprint(
        options, compose_file_sha256="aa" * 32, sops_env_sha256=None,
        compose_config_canonical_sha256="bb" * 32, env_file_sha256=None,
        artifacts_dir_manifest_sha256="dd" * 32,
    )
    fp_b = bo.compute_backup_runtime_binding_fingerprint(
        options, compose_file_sha256="ee" * 32, sops_env_sha256=None,  # changed
        compose_config_canonical_sha256="bb" * 32, env_file_sha256=None,
        artifacts_dir_manifest_sha256="dd" * 32,
    )
    assert fp_a != fp_b


def test_phase5_run_backup_phase_5_mode_requires_record_claim(tmp_path: Path) -> None:
    """ADV2 R13 F-001: phase_5_mode=True で record_backup_claim 必須."""
    monkeypatch_env_for_phase5(tmp_path)
    options = bo.BackupOptions.from_environment(
        output_path=tmp_path / "out.tar.age", repo_root=tmp_path,
    )
    with pytest.raises(bo.BackupRuntimeError) as exc_info:
        bo.run_backup(options, phase_5_mode=True, record_backup_claim=None, verified_temp_dir=None)
    assert exc_info.value.reason_code == "backup_compose_binding_not_initialized"


def test_phase5_run_backup_rejects_legacy_5field_claim(tmp_path: Path) -> None:
    """ADV2 R14 F-002 CRITICAL: phase_5_mode=True で fingerprint=None claim → legacy reject."""
    from scripts.taskhub_signed_approval import BackupApprovalClaim
    monkeypatch_env_for_phase5(tmp_path)
    options = bo.BackupOptions.from_environment(
        output_path=tmp_path / "out.tar.age", repo_root=tmp_path,
    )
    legacy_claim = BackupApprovalClaim(
        output_path=str(tmp_path / "out.tar.age"),
        include_sops_env=False, skip_service_stop=False, overwrite=False,
        age_public_key_fingerprint="a" * 64,
        # backup_runtime_binding_fingerprint=None (legacy 5-field)
    )
    verified_temp = tmp_path / "verified"
    verified_temp.mkdir(mode=0o700)
    with pytest.raises(bo.BackupRuntimeError) as exc_info:
        bo.run_backup(
            options, phase_5_mode=True,
            record_backup_claim=legacy_claim,
            verified_temp_dir=verified_temp,
        )
    assert exc_info.value.reason_code == "backup_claim_legacy_runtime_binding_unsupported"


def test_phase5_parse_compose_ps_healthy_service_field_primary_key() -> None:
    """ADV2 R2 F-005: Service field が primary key (Name は container name と乖離する)."""
    stdout = b'[{"Name":"taskmanagedai-api-1","Service":"api","Health":"healthy"},' \
             b'{"Name":"taskmanagedai-worker-1","Service":"worker","Health":"healthy"}]'
    assert bo._parse_compose_ps_healthy(stdout, {"api", "worker"}) is True


def test_phase5_parse_compose_ps_healthy_rejects_starting() -> None:
    """ADV2 R1 F-010 + R2 F-005: Health=starting は healthy ではない."""
    stdout = b'[{"Name":"x-api-1","Service":"api","Health":"starting"},' \
             b'{"Name":"x-worker-1","Service":"worker","Health":"healthy"}]'
    assert bo._parse_compose_ps_healthy(stdout, {"api", "worker"}) is False


def test_phase5_parse_compose_ps_healthy_jsonlines_fallback() -> None:
    """ADV2 R1 F-010: JSON-lines 形式 fallback (compose v2 出力形式 fluctuation)."""
    stdout = (
        b'{"Name":"x-api-1","Service":"api","Health":"healthy"}\n'
        b'{"Name":"x-worker-1","Service":"worker","Health":"healthy"}\n'
    )
    assert bo._parse_compose_ps_healthy(stdout, {"api", "worker"}) is True


def test_phase5_redact_compose_env_values_removes_value() -> None:
    """ADV2 R1 F-003: docker compose config 出力で secret env value を redact."""
    yaml_text = '    environment:\n      DEV_LOGIN_COOKIE_SECRET: "supersecret"\n'
    redacted = bo._redact_compose_env_values(yaml_text)
    assert "supersecret" not in redacted
    assert "<redacted>" in redacted


def test_phase5_backup_options_phase5_fields_default_none(tmp_path: Path) -> None:
    """SP022-T02 Phase 5: BackupOptions 新 fields は default None (PR #77 互換)."""
    monkeypatch_env_for_phase5(tmp_path)
    options = bo.BackupOptions.from_environment(
        output_path=tmp_path / "out.tar.age", repo_root=tmp_path,
    )
    # Phase 5 verified copy fields は CLI 起動直後は None (lock 内で bind される)
    assert options.verified_age_recipient is None
    assert options.verified_source_project_dir is None
    assert options.verified_compose_execution_input is None
    assert options.verified_compose_metadata_snapshot is None
    assert options.verified_env_file_execution_input is None
    assert options.verified_artifacts_staging_dir is None
    assert options.artifacts_dir_realpath_snapshot is None
    # ただし compose binding と env_file は from_environment で server-owned に解決済
    assert options.target_compose_project_name == "taskmanagedai"
    assert options.target_compose_file_path == (tmp_path / "docker-compose.yml").resolve()
    assert options.env_file_path == (tmp_path / ".env.local").resolve()
    # pg_user / pg_db default は taskmanagedai (docker-compose.yml 整合)
    assert options.pg_user == "taskmanagedai"
    assert options.pg_db == "taskmanagedai"


def test_phase5_backup_options_rejects_compose_file_outside_allowlist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """ADV R2 F-001: target_compose_file_path が allowlist (repo_root/etc/var/lib) 外 → reject."""
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("FOO=bar\n", encoding="utf-8")
    # /srv 配下は allowlist 外
    monkeypatch.setenv("TASKHUB_BACKUP_COMPOSE_FILE", "/srv/evil/docker-compose.yml")
    with pytest.raises(bo.BackupUsageError) as exc_info:
        bo.BackupOptions.from_environment(
            output_path=tmp_path / "out.tar.age", repo_root=tmp_path,
        )
    assert exc_info.value.reason_code == "backup_output_path_invalid"
    assert "not in allowed root" in (exc_info.value.detail or "")


def test_phase5_backup_options_rejects_invalid_compose_project_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """ADV R1 F-004: target_compose_project_name が regex 違反 → reject."""
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("FOO=bar\n", encoding="utf-8")
    monkeypatch.setenv("TASKHUB_BACKUP_COMPOSE_PROJECT", "INVALID-Upper")  # uppercase 禁止
    with pytest.raises(bo.BackupUsageError) as exc_info:
        bo.BackupOptions.from_environment(
            output_path=tmp_path / "out.tar.age", repo_root=tmp_path,
        )
    assert exc_info.value.reason_code == "backup_output_path_invalid"
    assert "target_compose_project_name invalid" in (exc_info.value.detail or "")
