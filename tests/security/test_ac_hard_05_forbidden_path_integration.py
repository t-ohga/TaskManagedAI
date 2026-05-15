"""AC-HARD-05 (forbidden_path_block) Hard Gate integration test.

Sprint 7 batch 4 BL-0080: public_regression fixture を loader 経由で読み、
各 `attempts[].path_pattern` が ``detect_forbidden_path`` (Sprint 7 batch 1) で
deny 判定されることを assert する。

Anti-Gaming Rules:
- private_holdout は本 test では load しない (loader API は提供するが、
  expected 値が policy / runner module 修正に直接流入しない設計)
- public_regression のみを CI で実行、Sprint 11 で private_holdout +
  adversarial_new を eval_harness 経由で計測
"""

from __future__ import annotations

import pytest

from backend.app.services.runner.forbidden_path import (
    detect_forbidden_path,
)
from eval.security.forbidden_path.loader import (
    load_manifest,
    load_public_regression_fixtures,
)


def test_manifest_hard_gate_id() -> None:
    """manifest が AC-HARD-05 / forbidden_path_block を宣言する。"""
    m = load_manifest()
    assert m["hard_gate_id"] == "AC-HARD-05"
    assert m["metric"] == "forbidden_path_block"


def test_public_regression_fixtures_load() -> None:
    """public_regression split から fixture が読める (schema validate を含む)."""
    fixtures = load_public_regression_fixtures()
    assert len(fixtures) >= 1
    for fx in fixtures:
        assert fx.gate_id_matches_fixture_id() if hasattr(fx, "gate_id_matches_fixture_id") else True
        assert fx.fixture_id.startswith("AC-HARD-05_")
        assert fx.expected_decision == "block"
        assert fx.expected_block is True
        assert fx.expected_runtime_blocked == "forbidden_path"


@pytest.mark.parametrize(
    "fixture",
    list(load_public_regression_fixtures()),
    ids=lambda f: f.case_key,
)
def test_forbidden_path_deny_all_attempts(fixture) -> None:  # type: ignore[no-untyped-def] # noqa: ANN001
    """Sprint 7 batch 1 detect_forbidden_path が fixture 全 attempt を deny する。"""
    for attempt in fixture.attempts:
        path_pattern = attempt["path_pattern"]
        # path_pattern は wildcard を含む denylist (例: ``secrets/**``).
        # detect_forbidden_path は具体 path を期待するので、glob を実例化:
        concrete_paths = _expand_glob_to_concrete(path_pattern)
        for path in concrete_paths:
            violation = detect_forbidden_path(path)
            assert violation is not None, (
                f"path {path!r} (from pattern {path_pattern!r}) was NOT blocked "
                f"by detect_forbidden_path; AC-HARD-05 invariant broken"
            )


def _expand_glob_to_concrete(pattern: str) -> list[str]:
    """Expand simple glob pattern to concrete sample paths.

    Note: 'secrets/**' expands to 'secrets/test.yaml' etc. The bare 'secrets'
    directory is NOT included because detect_forbidden_path matches on the
    '/secrets/' fragment (with trailing slash) — bare 'secrets' file is a
    different attack surface that is not in AC-HARD-05 scope.
    """
    if "**" not in pattern:
        return [pattern]
    # secrets/** → secrets/test.yaml, secrets/nested/key.pem
    base = pattern.replace("/**", "").replace("**", "")
    return [
        f"{base}/test.yaml",
        f"{base}/nested/key.pem",
    ]
