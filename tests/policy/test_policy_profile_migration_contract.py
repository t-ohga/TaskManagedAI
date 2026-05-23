from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_policy_profile_migration_normalizes_legacy_values_before_fk() -> None:
    migration = (
        REPO_ROOT / "migrations" / "versions" / "0027_sp014_policy_profile.py"
    ).read_text(encoding="utf-8")

    assert "policy_profile not in ('default', 'low_risk_auto_allow')" in migration
    assert "projects_policy_profile_fkey" in migration
