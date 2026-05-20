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
    ts = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
    meta = bo.build_meta_json(
        host_name="t-ohga-mac",
        timestamp_utc=ts,
        postgres_version="17.0",
        redis_version="7.4",
        alembic_head="abc123def456",
    )
    assert meta["host"] == "t-ohga-mac"
    assert meta["timestamp"] == "2026-05-20T12:00:00Z"
    assert meta["postgres_version"] == "17.0"
    assert meta["redis_version"] == "7.4"
    assert meta["alembic_head"] == "abc123def456"
    assert "backup_format_version" in meta


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


# --- Layer 3: orchestration with full mocks ---


def _setup_mock_backup_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict:
    """Common fixture: mock all subprocess wrappers + age pub key + paths."""
    age_pub = tmp_path / "age.pub"
    age_pub.write_text("age1mockedpublickey", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "data.txt").write_text("artifact data", encoding="utf-8")
    output = tmp_path / "backup.tar.age"

    return {
        "age_pub": age_pub,
        "artifacts": artifacts,
        "output": output,
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
    options = bo.BackupOptions(
        **{**options.__dict__, "age_public_key_path": env["age_pub"], "artifacts_dir": env["artifacts"]}
    )

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
    options = bo.BackupOptions(
        **{**options.__dict__, "age_public_key_path": age_pub, "artifacts_dir": artifacts}
    )

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
    options = bo.BackupOptions(
        **{**options.__dict__, "age_public_key_path": env["age_pub"], "artifacts_dir": env["artifacts"]}
    )
    with pytest.raises(bo.BackupRuntimeError) as exc_info:
        bo.run_backup(options)
    assert exc_info.value.reason_code == "backup_pg_dump_failed"
    # final output should not exist
    assert not env["output"].exists()
    # part file should not exist
    part_path = env["output"].with_name(env["output"].name + ".part")
    assert not part_path.exists()
