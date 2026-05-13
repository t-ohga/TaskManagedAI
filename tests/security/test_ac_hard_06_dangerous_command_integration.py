"""AC-HARD-06 (dangerous_command_block) Hard Gate integration test.

Sprint 7 batch 4 BL-0081: public_regression fixture を loader 経由で読み、
各 `test_cases[].normalized_command` が ``detect_dangerous_command`` (Sprint 7
batch 1, multi-round Codex review 済) で deny 判定されることを assert する。
"""

from __future__ import annotations

import shlex

import pytest

from backend.app.services.runner.dangerous_command import (
    detect_dangerous_command,
)
from eval.security.dangerous_command.loader import (
    load_manifest,
    load_public_regression_fixtures,
)


def test_manifest_hard_gate_id() -> None:
    """manifest が AC-HARD-06 / dangerous_command_block を宣言する。"""
    m = load_manifest()
    assert m["hard_gate_id"] == "AC-HARD-06"
    assert m["metric"] == "dangerous_command_block"


def test_public_regression_fixtures_load() -> None:
    """public_regression split から fixture が読める (schema validate を含む)."""
    fixtures = load_public_regression_fixtures()
    assert len(fixtures) >= 1
    for fx in fixtures:
        assert fx.fixture_id.startswith("AC-HARD-06_")
        assert fx.expected_decision == "block"
        assert fx.expected_block is True
        assert fx.expected_runtime_blocked == "dangerous_command"


@pytest.mark.parametrize(
    "fixture",
    list(load_public_regression_fixtures()),
    ids=lambda f: f.case_key,
)
def test_dangerous_command_deny_all_cases(fixture) -> None:  # type: ignore[no-untyped-def] # noqa: ANN001
    """Sprint 7 batch 1 detect_dangerous_command が fixture 全 case を deny する。"""
    for test_case in fixture.test_cases:
        cmd_str = test_case["normalized_command"]
        command_class = test_case["command_class"]

        if command_class == "fork_bomb":
            # fork_bomb は shell function definition で argv 直接 表現は困難
            # → INLINE_EXEC で sh/bash 経由は deny されることを別 case で verify
            argv = ("/bin/sh", "-c", ":(){ :|:& };:")
        else:
            # Codex SP7 audit F-SP7-007 adopt: shlex.split 不能な fixture は
            # silent continue ではなく **fail-loud** にする (anti-gaming:
            # malformed fixture を黙って未検証にすると Hard Gate が嘘になる)
            try:
                argv = tuple(shlex.split(cmd_str))
            except ValueError as exc:
                raise AssertionError(
                    f"fixture {fixture.fixture_id!r} contains shlex.split-incompatible "
                    f"command {cmd_str!r} (class={command_class}); fix fixture to use "
                    f"argv tuple or provide canonical_argv field instead. "
                    f"Codex SP7 audit F-SP7-007 invariant: AC-HARD-06 fixture は "
                    f"必ず executable command として shlex 経由で argv 化できる必要がある。"
                ) from exc

        assert argv, (
            f"fixture {fixture.fixture_id!r} produced empty argv for {cmd_str!r}; "
            f"AC-HARD-06 invariant broken (Codex F-SP7-007 adopt)"
        )

        violation = detect_dangerous_command(argv)
        assert violation is not None, (
            f"command {cmd_str!r} (class={command_class}) was NOT blocked by "
            f"detect_dangerous_command; AC-HARD-06 invariant broken. argv={argv!r}"
        )
