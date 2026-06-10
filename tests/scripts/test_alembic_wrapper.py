"""SP-022-1 alembic wrapper and SOP regression tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "alembic_wrapper.sh"
SMOKE_SOP = REPO_ROOT / "docs" / "deploy" / "mac-single-host-smoke-sop.md"
LAYER_C_RUNBOOK = REPO_ROOT / "docs" / "deploy" / "layer-c-operator-runbook.md"


def test_alembic_wrapper_dry_run_strips_host_database_env() -> None:
    env = dict(os.environ)
    env["TASKMANAGEDAI_DATABASE_URL"] = "postgresql://secret@example/db"
    env["DATABASE_URL"] = "postgresql://secret2@example/db"

    result = subprocess.run(  # noqa: S603
        ["/bin/bash", str(WRAPPER), "--dry-run", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "env -u TASKMANAGEDAI_DATABASE_URL -u DATABASE_URL" in result.stdout
    assert "docker compose" in result.stdout
    assert "exec -T api" in result.stdout
    # B-4 fix: ro mount で egg-info Permission denied を避けるため --no-sync を付与
    # (base compose api/worker と整合)。
    assert "uv run --no-sync alembic upgrade head" in result.stdout
    # B-4 fix (PR #336 再検証 FAIL): env strip は host 側 (docker compose 起動前) の 1 回のみ。
    # container 内で TASKMANAGEDAI_DATABASE_URL を unset すると Alembic が default password の
    # _DEV_DATABASE_URL に fallback し InvalidPasswordError になる。container 内 (.env.local 由来、
    # 実行中 api と同一) の env を正本として alembic を直接実行する。
    assert result.stdout.count("env -u TASKMANAGEDAI_DATABASE_URL") == 1
    assert "exec -T api uv run --no-sync alembic" in result.stdout
    assert "secret@example" not in result.stdout
    assert "secret2@example" not in result.stdout


def test_alembic_wrapper_dry_run_defaults_to_current() -> None:
    result = subprocess.run(  # noqa: S603
        ["/bin/bash", str(WRAPPER), "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "uv run --no-sync alembic current" in result.stdout


def test_alembic_wrapper_fails_closed_when_env_file_lacks_database_url(
    tmp_path: Path,
) -> None:
    # R3 (Codex adversarial MEDIUM): env file に TASKMANAGEDAI_DATABASE_URL が無い場合、
    # preflight は docker を呼ぶ前に exit 3 で fail-closed する (expected/actual が空同士で
    # 一致扱いになり、Alembic が Settings の default URL へ fallback したまま migration する
    # 経路の封鎖)。docker 不要で決定的に検証できる。
    env_file = tmp_path / "no-db-url.env"
    env_file.write_text("POSTGRES_USER=taskmanagedai\n", encoding="utf-8")
    env = dict(os.environ)
    env["TASKHUB_ALEMBIC_ENV_FILE"] = str(env_file)

    result = subprocess.run(  # noqa: S603
        ["/bin/bash", str(WRAPPER), "current"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 3
    assert "TASKMANAGEDAI_DATABASE_URL" in result.stderr
    assert "fail-closed" in result.stderr


def test_smoke_sop_uses_alembic_wrapper_and_documents_env_strip() -> None:
    text = SMOKE_SOP.read_text(encoding="utf-8")

    assert "bash scripts/alembic_wrapper.sh current" in text
    assert "bash scripts/alembic_wrapper.sh upgrade head" in text
    assert "TASKMANAGEDAI_DATABASE_URL / DATABASE_URL" in text


def test_smoke_sop_signed_journal_verify_has_grep_coverage_sections() -> None:
    text = SMOKE_SOP.read_text(encoding="utf-8")

    for section in ("§13.1", "§13.2", "§13.3", "§13.4", "§13.5", "§13.6"):
        assert section in text
    assert "VERIFY_FAILURE_PATTERN" in text
    assert "VERIFY_PASS_PATTERN" in text
    assert "VERIFY_SSH_PATTERN" in text
    assert "signature_verify_failed" in text
    assert "Host key verification failed" in text


def test_layer_c_operator_runbook_sections_one_to_nine_exist() -> None:
    text = LAYER_C_RUNBOOK.read_text(encoding="utf-8")

    for section in range(1, 10):
        assert f"## §{section} " in text
    assert "BackupApprovalClaim" in text
    assert "RestoreApprovalClaim" in text
    assert "backup_runtime_binding_fingerprint" in text


def test_layer_c_operator_runbook_defines_drill_path_variables() -> None:
    text = LAYER_C_RUNBOOK.read_text(encoding="utf-8")

    assert 'export DATABASE_URL="' in text
    assert 'export BACKUP_APPROVAL_ID="' in text
    assert 'export BACKUP_PATH="' in text
    assert 'export TARGET_HOST="' in text
