"""Policy Pack + repair_policy integration (Sprint 5.5 BL-0064).

These tests confirm that the runtime upper bound is the
``config/policy_pack.toml`` value (not the legacy hardcoded constant) and
that all callers (``repair_policy.should_repair``, ``decide_repair``,
``resolve_repair_retry_max_attempts``) agree.

SP55-B1-F-002 fix: ``policy_pack_lock`` is the SHA-256 hex digest of the
TOML bytes and is the value recorded into ContextSnapshot — separate
from the human-readable ``policy_version``.

SP55-B1-F-003 fix: missing required sections / keys must fail-closed
with ``ValueError`` (no silent defaults).
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from backend.app.db.models.agent_run import AgentRun
from backend.app.services.agent_runtime.repair_policy import (
    resolve_repair_retry_max_attempts,
    should_repair,
)
from backend.app.services.output_validator.core import decide_repair
from backend.app.services.policy_pack.loader import (
    DEFAULT_POLICY_PACK_PATH,
    PolicyPack,
    load_policy_pack,
)

_FULL_TOML = (
    '[meta]\npolicy_version = "vTEST"\n\n'
    "[output_validator]\nrepair_retry_max_attempts = 3\n\n"
    "[input_trust]\n"
    "trust_level_promotion_to_trusted_instruction_requires_human_approval = true\n"
)


def _run() -> AgentRun:
    from uuid import uuid4

    return AgentRun(
        tenant_id=1,
        project_id=uuid4(),
        status="validation_failed",
    )


def test_default_policy_pack_loads_repair_retry_max_attempts_three() -> None:
    pack = load_policy_pack()
    assert pack.repair_retry_max_attempts == 3
    assert pack.policy_version.startswith("v1.")
    assert (
        pack.trust_level_promotion_to_trusted_instruction_requires_human_approval is True
    )


def test_default_policy_pack_path_resolves_under_config_dir() -> None:
    assert DEFAULT_POLICY_PACK_PATH.name == "policy_pack.toml"
    # The default path must point inside the project ``config/`` directory.
    assert DEFAULT_POLICY_PACK_PATH.parent.name == "config"


def test_resolve_repair_retry_max_attempts_matches_default_toml() -> None:
    assert resolve_repair_retry_max_attempts() == 3


def test_should_repair_and_decide_repair_agree_on_policy_bound() -> None:
    """When budget is unlimited, the two helpers agree on the policy bound."""

    pack = PolicyPack(
        policy_version="test-vN.N",
        policy_pack_lock="0" * 64,
        repair_retry_max_attempts=4,
        trust_level_promotion_to_trusted_instruction_requires_human_approval=True,
    )

    for retry_count in range(0, 6):
        helper_allows = should_repair(_run(), retry_count, policy_pack=pack)
        decision = decide_repair(
            retry_count=retry_count,
            repair_budget_remaining=Decimal("1000"),
            policy_pack=pack,
        )
        assert helper_allows == (decision.outcome == "retry")


# --- SP55-B1-F-002: policy_pack_lock is sha256 hex 64, distinct from version ---


_SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def test_default_policy_pack_lock_is_sha256_hex_64() -> None:
    """policy_pack_lock must satisfy ContextSnapshot.policy_pack_lock DB CHECK.

    The Artifact / ContextSnapshot ORM enforces ``policy_pack_lock ~
    '^[0-9a-f]{64}$'``; if Sprint 5.5 records the human-readable
    ``policy_version`` there, the constraint fails. The loader is required
    to compute a separate sha256 digest.
    """

    pack = load_policy_pack()
    assert _SHA256_HEX_PATTERN.match(pack.policy_pack_lock) is not None
    assert pack.policy_pack_lock != pack.policy_version


def test_policy_pack_lock_changes_when_toml_content_changes(tmp_path: Path) -> None:
    a = tmp_path / "a.toml"
    a.write_text(_FULL_TOML, encoding="utf-8")
    b = tmp_path / "b.toml"
    b.write_text(_FULL_TOML.replace("3", "5"), encoding="utf-8")

    pack_a = load_policy_pack(a)
    pack_b = load_policy_pack(b)
    assert pack_a.policy_pack_lock != pack_b.policy_pack_lock
    assert _SHA256_HEX_PATTERN.match(pack_a.policy_pack_lock) is not None
    assert _SHA256_HEX_PATTERN.match(pack_b.policy_pack_lock) is not None


# --- SP55-B1-F-003: missing required section / key must fail-closed ----------


def test_load_policy_pack_rejects_missing_meta_section(tmp_path: Path) -> None:
    bad = tmp_path / "policy_pack.toml"
    bad.write_text(
        "[output_validator]\nrepair_retry_max_attempts = 3\n\n"
        "[input_trust]\n"
        "trust_level_promotion_to_trusted_instruction_requires_human_approval = true\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"missing required section \[meta\]"):
        load_policy_pack(bad)


def test_load_policy_pack_rejects_missing_output_validator_section(tmp_path: Path) -> None:
    bad = tmp_path / "policy_pack.toml"
    bad.write_text(
        '[meta]\npolicy_version = "vTEST"\n\n'
        "[input_trust]\n"
        "trust_level_promotion_to_trusted_instruction_requires_human_approval = true\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ValueError,
        match=r"missing required section \[output_validator\]",
    ):
        load_policy_pack(bad)


def test_load_policy_pack_rejects_missing_input_trust_section(tmp_path: Path) -> None:
    bad = tmp_path / "policy_pack.toml"
    bad.write_text(
        '[meta]\npolicy_version = "vTEST"\n\n'
        "[output_validator]\nrepair_retry_max_attempts = 3\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ValueError,
        match=r"missing required section \[input_trust\]",
    ):
        load_policy_pack(bad)


def test_load_policy_pack_rejects_missing_policy_version_key(tmp_path: Path) -> None:
    bad = tmp_path / "policy_pack.toml"
    bad.write_text(
        "[meta]\n\n"
        "[output_validator]\nrepair_retry_max_attempts = 3\n\n"
        "[input_trust]\n"
        "trust_level_promotion_to_trusted_instruction_requires_human_approval = true\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ValueError,
        match=r"\[meta\] missing required key 'policy_version'",
    ):
        load_policy_pack(bad)


def test_load_policy_pack_rejects_missing_repair_retry_max_attempts(tmp_path: Path) -> None:
    bad = tmp_path / "policy_pack.toml"
    bad.write_text(
        '[meta]\npolicy_version = "vTEST"\n\n'
        "[output_validator]\n\n"
        "[input_trust]\n"
        "trust_level_promotion_to_trusted_instruction_requires_human_approval = true\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ValueError,
        match=(
            r"\[output_validator\] missing required key 'repair_retry_max_attempts'"
        ),
    ):
        load_policy_pack(bad)


def test_load_policy_pack_rejects_missing_human_approval_key(tmp_path: Path) -> None:
    bad = tmp_path / "policy_pack.toml"
    bad.write_text(
        '[meta]\npolicy_version = "vTEST"\n\n'
        "[output_validator]\nrepair_retry_max_attempts = 3\n\n"
        "[input_trust]\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ValueError,
        match=(
            r"\[input_trust\] missing required key "
            r"'trust_level_promotion_to_trusted_instruction_requires_human_approval'"
        ),
    ):
        load_policy_pack(bad)


# --- existing key-value validation tests (still required, full TOML now) -----


def test_load_policy_pack_rejects_invalid_max_attempts(tmp_path: Path) -> None:
    bad = tmp_path / "policy_pack.toml"
    bad.write_text(
        '[meta]\npolicy_version = "vTEST"\n\n'
        "[output_validator]\nrepair_retry_max_attempts = 0\n\n"
        "[input_trust]\n"
        "trust_level_promotion_to_trusted_instruction_requires_human_approval = true\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="repair_retry_max_attempts"):
        load_policy_pack(bad)


def test_load_policy_pack_rejects_non_bool_human_approval_flag(tmp_path: Path) -> None:
    bad = tmp_path / "policy_pack.toml"
    bad.write_text(
        '[meta]\npolicy_version = "vTEST"\n\n'
        "[output_validator]\nrepair_retry_max_attempts = 3\n\n"
        "[input_trust]\n"
        "trust_level_promotion_to_trusted_instruction_requires_human_approval = 1\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ValueError,
        match=(
            "trust_level_promotion_to_trusted_instruction_requires_human_approval"
        ),
    ):
        load_policy_pack(bad)


def test_load_policy_pack_rejects_empty_policy_version(tmp_path: Path) -> None:
    bad = tmp_path / "policy_pack.toml"
    bad.write_text(
        '[meta]\npolicy_version = "   "\n\n'
        "[output_validator]\nrepair_retry_max_attempts = 3\n\n"
        "[input_trust]\n"
        "trust_level_promotion_to_trusted_instruction_requires_human_approval = true\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="policy_version"):
        load_policy_pack(bad)


def test_load_policy_pack_rejects_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "absent.toml"
    with pytest.raises(FileNotFoundError, match="policy_pack TOML not found"):
        load_policy_pack(missing)
