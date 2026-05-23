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
    assert "uv run alembic upgrade head" in result.stdout
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
    assert "uv run alembic current" in result.stdout


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
