from __future__ import annotations

from pathlib import Path

from backend.app.services.eval.anti_gaming import (
    AntiGamingViolation,
    GitCommit,
    GitLogRunner,
    verify_fixture_commit_separation,
)


def _fake_git_log(commits_by_path: dict[Path, list[GitCommit]]) -> GitLogRunner:
    def _runner(_repo_root: Path, path: Path) -> list[GitCommit]:
        return commits_by_path.get(path, [])

    return _runner


def test_verify_fixture_commit_separation_empty_fixture_paths_is_clean() -> None:
    report = verify_fixture_commit_separation(
        Path("/repo"),
        fixture_paths=[],
        policy_paths=[Path("backend/app/services/policy")],
        git_log_runner=_fake_git_log({}),
    )

    assert report.is_clean()
    assert report.violations == ()


def test_verify_fixture_commit_separation_happy_path_is_clean() -> None:
    fixture_path = Path("eval/security/tenant_isolation/public_regression/case.json")
    policy_path = Path("backend/app/services/policy/decision_service.py")
    report = verify_fixture_commit_separation(
        Path("/repo"),
        fixture_paths=[fixture_path],
        policy_paths=[policy_path],
        window_seconds=3600,
        git_log_runner=_fake_git_log(
            {
                fixture_path: [GitCommit("f" * 40, "Fixture Author", 2_000)],
                policy_path: [GitCommit("p" * 40, "Policy Author", 1_000)],
            }
        ),
    )

    assert report.is_clean()
    assert report.violations == ()


def test_verify_fixture_commit_separation_detects_author_inversion() -> None:
    fixture_path = Path("eval/security/tenant_isolation/public_regression/case.json")
    policy_path = Path("backend/app/services/runner/runner_adapter.py")
    report = verify_fixture_commit_separation(
        Path("/repo"),
        fixture_paths=[fixture_path],
        policy_paths=[policy_path],
        window_seconds=3600,
        git_log_runner=_fake_git_log(
            {
                fixture_path: [GitCommit("f" * 40, "Same Author", 2_000)],
                policy_path: [GitCommit("p" * 40, "Same Author", 2_500)],
            }
        ),
    )

    assert not report.is_clean()
    violation = report.violations[0]
    assert isinstance(violation, AntiGamingViolation)
    assert violation.reason_code == "author_inversion"
    assert violation.path == fixture_path
    assert violation.policy_path == policy_path
    assert "author_inversion" in str(violation)
    assert ("f" * 12) in str(violation)
    assert ("p" * 12) in str(violation)


def test_verify_fixture_commit_separation_detects_timestamp_inversion() -> None:
    fixture_path = Path("eval/security/tenant_isolation/private_holdout/case.json")
    policy_path = Path("backend/app/prompts/policy_prompt.md")
    report = verify_fixture_commit_separation(
        Path("/repo"),
        fixture_paths=[fixture_path],
        policy_paths=[policy_path],
        window_seconds=3600,
        git_log_runner=_fake_git_log(
            {
                fixture_path: [GitCommit("a" * 40, "Fixture Author", 10_000)],
                policy_path: [GitCommit("b" * 40, "Policy Author", 1_000)],
            }
        ),
    )

    assert not report.is_clean()
    violation = report.violations[0]
    assert violation.reason_code == "timestamp_inversion"
    assert violation.path == fixture_path
    assert violation.policy_path == policy_path
    assert "timestamp_inversion" in str(violation)
    assert ("a" * 12) in str(violation)
    assert ("b" * 12) in str(violation)
