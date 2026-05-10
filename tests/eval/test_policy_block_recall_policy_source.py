"""AC-HARD-01 policy_block_recall policy source contract test (Sprint 3 Batch 4)."""

from __future__ import annotations

from pathlib import Path

from backend.app.seeds.initial_policy_matrix import INITIAL_POLICY_MATRIX
from eval.security.policy_block.loader import (
    discover_fixtures,
    load_manifest,
    load_public_regression_fixtures,
)

_BASE_PATH = Path(__file__).resolve().parents[2] / "eval" / "security" / "policy_block"


def _extract_reason_codes_from_initial_seed() -> frozenset[str]:
    """Extract reason_code values from the canonical initial policy matrix seed.

    Replaces the legacy regex-parser of migrations/versions/0005_policy_rules.py
    source text, which is brittle against migration source refactors. The new source
    of truth is `backend.app.seeds.initial_policy_matrix.INITIAL_POLICY_MATRIX`.
    Migration 0005 SQL VALUES MUST stay in sync with this constant (see docstring
    of initial_policy_matrix.py).
    """
    return frozenset(seed["reason_code"] for seed in INITIAL_POLICY_MATRIX)


def test_policy_block_manifest_gate_id_and_metric() -> None:
    manifest = load_manifest(_BASE_PATH / "manifest.json")
    assert manifest["hard_gate_id"] == "AC-HARD-01"
    assert manifest["metric"] == "policy_block_recall"


def test_policy_block_public_regression_fixture_loads() -> None:
    fixtures = load_public_regression_fixtures(_BASE_PATH)
    assert len(fixtures) == 1


def test_policy_block_reason_code_subset_in_adr_and_seed() -> None:
    """AC-HARD-01 fixture reason_code is a subset of ADR-00009 + migration 0005 seed."""

    fixtures = load_public_regression_fixtures(_BASE_PATH)
    fixture_reasons = {fixture.expected_reason_code for fixture in fixtures}

    seed_reasons = _extract_reason_codes_from_initial_seed()
    adr_extra_reasons = frozenset(
        {
            "unknown_action_class_denied",
            "provider_not_in_matrix",
            "dangerous_command_denied",
            "unknown_resource_ref_denied",
        }
    )
    allowed = seed_reasons | adr_extra_reasons

    unknown = fixture_reasons - allowed
    assert not unknown, (
        "AC-HARD-01 fixture has reason codes outside ADR-00009 / migration 0005 seed: "
        f"{sorted(unknown)}"
    )


def test_policy_block_action_class_in_seven_canonical() -> None:
    fixtures = load_public_regression_fixtures(_BASE_PATH)

    canonical_action_classes = frozenset(
        {
            "task_write",
            "repo_write",
            "pr_open",
            "secret_access",
            "merge",
            "deploy",
            "provider_call",
        }
    )

    for fixture in fixtures:
        action_class = fixture.input.get("action_class")
        assert action_class in canonical_action_classes, (
            f"fixture {fixture.fixture_id} has action_class {action_class!r} "
            "outside ADR-00009 canonical 7"
        )


def test_policy_block_discover_fixtures_returns_three_splits() -> None:
    splits = discover_fixtures(_BASE_PATH)
    assert set(splits.keys()) == {"public_regression", "private_holdout", "adversarial_new"}
    assert len(splits["public_regression"]) == 1
    assert len(splits["private_holdout"]) == 0
    assert len(splits["adversarial_new"]) == 0

