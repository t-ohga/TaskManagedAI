"""BL-0129 Anti-Gaming Rules CI gate — real-git invocation.

F-PR28-R3-003 P1 partial adopt:
The Codex multi-round R3 review pointed out that ``verify_fixture_commit_separation``
is only exercised by mocked unit tests, so the actual fixture-vs-policy
commit-separation invariant is never enforced against the real git history. This
module wires the real-git invocation into pytest so the gate is exercised end to
end whenever the test is enabled.

Activation:
- Set ``TASKMANAGEDAI_RUN_ANTI_GAMING_GATE=1`` to opt in (default skip).
- The gate is opt-in for P0 because TaskManagedAI is currently a single-author
  repository; ``author_inversion`` would otherwise fire on every commit pair
  authored by ``t-ohga`` within ``window_seconds``. Multi-actor scenarios that
  unblock the gate are tracked in Sprint 11.5+ (multi-agent orchestration).

When activated, the test asserts that the most recent policy/runner/prompt
commit was NOT authored shortly **after** the fixture creation commit by the
**same** stable contributor identity (name<email>) within ``window_seconds``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from backend.app.services.eval.anti_gaming import verify_fixture_commit_separation

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_ROOT = _REPO_ROOT / "eval/security/tenant_isolation/public_regression"
_POLICY_PATHS = (
    _REPO_ROOT / "backend/app/services/policy",
    _REPO_ROOT / "backend/app/services/runner",
)

_OPT_IN_ENV_VAR = "TASKMANAGEDAI_RUN_ANTI_GAMING_GATE"


def _opt_in_enabled() -> bool:
    return os.environ.get(_OPT_IN_ENV_VAR) == "1"


@pytest.mark.skipif(
    not _opt_in_enabled(),
    reason=f"Set {_OPT_IN_ENV_VAR}=1 to run the real-git anti-gaming gate.",
)
def test_real_git_fixture_policy_commit_separation_is_clean() -> None:
    if shutil.which("git") is None:
        pytest.skip("git binary not available on PATH; cannot run real-git anti-gaming gate.")
    if not (_REPO_ROOT / ".git").exists():
        pytest.skip(f"{_REPO_ROOT} is not a git repository; cannot run real-git anti-gaming gate.")

    fixture_paths = sorted(_FIXTURE_ROOT.glob("*.json"))
    if not fixture_paths:
        pytest.skip(f"No fixture files under {_FIXTURE_ROOT}.")
    policy_paths = [path for path in _POLICY_PATHS if path.exists()]
    if not policy_paths:
        pytest.skip("No policy paths found; nothing to compare against.")

    report = verify_fixture_commit_separation(
        _REPO_ROOT,
        fixture_paths=fixture_paths,
        policy_paths=policy_paths,
        window_seconds=3600,
    )
    if not report.is_clean():
        formatted = "\n".join(
            f"  - {violation}" for violation in report.violations
        )
        pytest.fail(
            f"BL-0129 anti-gaming gate detected violations:\n{formatted}"
        )
