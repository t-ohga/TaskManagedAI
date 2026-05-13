"""Sprint 7 BL-0074: ResourcePolicy + ResourceCapDenyReason tests."""

from __future__ import annotations

import dataclasses

import pytest

from backend.app.services.runner.resource_cap import (
    RESOURCE_CAP_DENY_REASONS,
    ResourceCapDenyReason,
    ResourcePolicy,
)

EXPECTED_DENY_REASONS: tuple[str, ...] = (
    "cpu_quota_non_positive",
    "cpu_period_non_positive",
    "memory_non_positive",
    "pids_max_non_positive",
    "disk_non_positive",
    "wall_clock_non_positive",
    "output_byte_cap_non_positive",
    "stdout_byte_cap_non_positive",
    "stderr_byte_cap_non_positive",
    "cpu_quota_exceeds_ceiling",
    "memory_exceeds_ceiling",
    "pids_max_exceeds_ceiling",
    "wall_clock_exceeds_ceiling",
    "output_byte_cap_exceeds_ceiling",
    "output_byte_cap_below_stdout",
    "output_byte_cap_below_stderr",
    # Codex R1 F-002 / F-009 adopt
    "cpu_ratio_exceeds_ceiling",
    "output_byte_cap_below_stream_sum",
)


def test_enum_5plus_source_integrity() -> None:
    """ResourceCapDenyReason enum + EXPECTED constants 整合 (5+ source)."""
    actual = {r.value for r in ResourceCapDenyReason}
    expected = set(EXPECTED_DENY_REASONS)
    assert actual == expected, f"drift: only-enum={actual - expected} only-expected={expected - actual}"
    assert RESOURCE_CAP_DENY_REASONS == expected


def test_p0_defaults_valid() -> None:
    """P0 default policy must pass validate()."""
    policy = ResourcePolicy.from_p0_defaults()
    assert policy.validate() == ()


def test_p0_defaults_sane() -> None:
    """P0 default values are within reasonable ranges."""
    policy = ResourcePolicy.from_p0_defaults()
    assert policy.cpu_quota_us == 1_000_000
    assert policy.cpu_period_us == 1_000_000
    assert policy.memory_bytes == 1 * 1024 * 1024 * 1024
    assert policy.pids_max == 512
    assert policy.disk_bytes == 2 * 1024 * 1024 * 1024
    assert policy.wall_clock_seconds == 300.0
    assert policy.output_byte_cap == 16 * 1024 * 1024
    assert policy.stdout_byte_cap == 8 * 1024 * 1024
    assert policy.stderr_byte_cap == 8 * 1024 * 1024


def test_resource_policy_is_frozen() -> None:
    """ResourcePolicy must be frozen (immutability invariant)."""
    policy = ResourcePolicy.from_p0_defaults()
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.cpu_quota_us = 5_000_000  # type: ignore[misc]


@pytest.mark.parametrize(
    ("override_kwargs", "expected_reason"),
    [
        ({"cpu_quota_us": 0}, ResourceCapDenyReason.CPU_QUOTA_NON_POSITIVE),
        ({"cpu_quota_us": -1}, ResourceCapDenyReason.CPU_QUOTA_NON_POSITIVE),
        ({"cpu_period_us": 0}, ResourceCapDenyReason.CPU_PERIOD_NON_POSITIVE),
        ({"memory_bytes": 0}, ResourceCapDenyReason.MEMORY_NON_POSITIVE),
        ({"pids_max": 0}, ResourceCapDenyReason.PIDS_MAX_NON_POSITIVE),
        ({"disk_bytes": 0}, ResourceCapDenyReason.DISK_NON_POSITIVE),
        ({"wall_clock_seconds": 0.0}, ResourceCapDenyReason.WALL_CLOCK_NON_POSITIVE),
        ({"output_byte_cap": 0}, ResourceCapDenyReason.OUTPUT_BYTE_CAP_NON_POSITIVE),
        ({"stdout_byte_cap": 0}, ResourceCapDenyReason.STDOUT_BYTE_CAP_NON_POSITIVE),
        ({"stderr_byte_cap": 0}, ResourceCapDenyReason.STDERR_BYTE_CAP_NON_POSITIVE),
    ],
)
def test_non_positive_values_rejected(
    override_kwargs: dict[str, int | float],
    expected_reason: ResourceCapDenyReason,
) -> None:
    """Non-positive cap values must be rejected with specific reason."""
    base = dataclasses.asdict(ResourcePolicy.from_p0_defaults())
    base.update(override_kwargs)
    policy = ResourcePolicy(**base)  # type: ignore[arg-type]
    violations = policy.validate()
    assert expected_reason in violations


@pytest.mark.parametrize(
    ("override_kwargs", "expected_reason"),
    [
        (
            {"cpu_quota_us": 10_000_000},
            ResourceCapDenyReason.CPU_QUOTA_EXCEEDS_CEILING,
        ),
        (
            {"memory_bytes": 64 * 1024 * 1024 * 1024},
            ResourceCapDenyReason.MEMORY_EXCEEDS_CEILING,
        ),
        (
            {"pids_max": 100_000},
            ResourceCapDenyReason.PIDS_MAX_EXCEEDS_CEILING,
        ),
        (
            {"wall_clock_seconds": 3600.0 * 24},
            ResourceCapDenyReason.WALL_CLOCK_EXCEEDS_CEILING,
        ),
        (
            {
                "output_byte_cap": 1024 * 1024 * 1024 * 4,
                "stdout_byte_cap": 1024 * 1024 * 1024 * 2,
                "stderr_byte_cap": 1024 * 1024 * 1024 * 2,
            },
            ResourceCapDenyReason.OUTPUT_BYTE_CAP_EXCEEDS_CEILING,
        ),
    ],
)
def test_ceiling_exceeded_rejected(
    override_kwargs: dict[str, int | float],
    expected_reason: ResourceCapDenyReason,
) -> None:
    """Values exceeding P0 absolute ceiling must be rejected."""
    base = dataclasses.asdict(ResourcePolicy.from_p0_defaults())
    base.update(override_kwargs)
    policy = ResourcePolicy(**base)  # type: ignore[arg-type]
    violations = policy.validate()
    assert expected_reason in violations


def test_output_cap_below_stdout_rejected() -> None:
    """output_byte_cap < stdout_byte_cap is a cross-field violation."""
    base = dataclasses.asdict(ResourcePolicy.from_p0_defaults())
    base["output_byte_cap"] = 1024  # 1 KB
    base["stdout_byte_cap"] = 8 * 1024 * 1024  # 8 MB
    policy = ResourcePolicy(**base)  # type: ignore[arg-type]
    violations = policy.validate()
    assert ResourceCapDenyReason.OUTPUT_BYTE_CAP_BELOW_STDOUT in violations


def test_output_cap_below_stderr_rejected() -> None:
    """output_byte_cap < stderr_byte_cap is a cross-field violation."""
    base = dataclasses.asdict(ResourcePolicy.from_p0_defaults())
    base["output_byte_cap"] = 1024
    base["stderr_byte_cap"] = 8 * 1024 * 1024
    base["stdout_byte_cap"] = 1024  # match output_byte_cap
    policy = ResourcePolicy(**base)  # type: ignore[arg-type]
    violations = policy.validate()
    assert ResourceCapDenyReason.OUTPUT_BYTE_CAP_BELOW_STDERR in violations


def test_multiple_violations_aggregated() -> None:
    """Multiple violations must all be reported, not just the first."""
    policy = ResourcePolicy(
        cpu_quota_us=-1,
        cpu_period_us=-1,
        memory_bytes=-1,
        pids_max=-1,
        disk_bytes=-1,
        wall_clock_seconds=-1.0,
        output_byte_cap=-1,
        stdout_byte_cap=-1,
        stderr_byte_cap=-1,
    )
    violations = policy.validate()
    assert ResourceCapDenyReason.CPU_QUOTA_NON_POSITIVE in violations
    assert ResourceCapDenyReason.MEMORY_NON_POSITIVE in violations
    assert ResourceCapDenyReason.WALL_CLOCK_NON_POSITIVE in violations
    assert len(violations) >= 7


def test_validate_returns_tuple() -> None:
    """validate() returns immutable tuple."""
    policy = ResourcePolicy.from_p0_defaults()
    result = policy.validate()
    assert isinstance(result, tuple)
