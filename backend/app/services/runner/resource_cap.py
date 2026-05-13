"""Sprint 7 BL-0074: ResourcePolicy + ResourceCap enforcement.

ADR-00008 §resource_cap: Docker isolated runner で fork bomb / zip bomb /
unbounded output / wall-clock leak を多層防御する。

P0 design:

- ``ResourcePolicy`` frozen dataclass で cap 値を caller 不変として保持。
  caller-supplied 経路は signature レベルで pass-through (server が
  policy DB から resolve、Sprint 8 で server-owned ID 化)。
- Docker integration は Sprint 11 で ``DockerRunnerAdapter`` が
  ``--cpus`` / ``--memory`` / ``--pids-limit`` / ``--ulimit`` で適用。
- ``MockRunnerAdapter`` は wall_clock (timeout) + output_byte_cap のみ
  enforce (in-process)。CPU / memory / pids / disk は Docker でしか
  確実な isolation が取れないため Mock では assert のみ。

fail-closed:

- ``ResourcePolicy.validate()`` で全 cap 値が ``> 0`` を強制。
- ``ResourcePolicy.from_p0_defaults()`` で安全側に倒した default 提供。
- output_byte_cap 超過時は ``RunnerCommandResult.output_cap_exceeded=True``
  + process group SIGTERM/SIGKILL escalation。

server-owned-boundary §1:

- ``policy_id`` field なし (Sprint 8 で server-owned ID 化)。caller は
  ``ResourcePolicy`` instance を直接渡せるが、orchestrator は P0 default
  を server-resolve することで pass-through 経路を持たない。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class ResourceCapDenyReason(StrEnum):
    """ResourcePolicy validation deny reason (note: per Codex R1 F-010, this
    enum is currently 2-source (enum + pytest EXPECTED). DB / ORM / Pydantic
    integration is deferred to Sprint 8 batch 3 when ResourcePolicy connects
    to audit_events / API payload).
    """

    CPU_QUOTA_NON_POSITIVE = "cpu_quota_non_positive"
    CPU_PERIOD_NON_POSITIVE = "cpu_period_non_positive"
    MEMORY_NON_POSITIVE = "memory_non_positive"
    PIDS_MAX_NON_POSITIVE = "pids_max_non_positive"
    DISK_NON_POSITIVE = "disk_non_positive"
    WALL_CLOCK_NON_POSITIVE = "wall_clock_non_positive"
    OUTPUT_BYTE_CAP_NON_POSITIVE = "output_byte_cap_non_positive"
    STDOUT_BYTE_CAP_NON_POSITIVE = "stdout_byte_cap_non_positive"
    STDERR_BYTE_CAP_NON_POSITIVE = "stderr_byte_cap_non_positive"
    CPU_QUOTA_EXCEEDS_CEILING = "cpu_quota_exceeds_ceiling"
    MEMORY_EXCEEDS_CEILING = "memory_exceeds_ceiling"
    PIDS_MAX_EXCEEDS_CEILING = "pids_max_exceeds_ceiling"
    WALL_CLOCK_EXCEEDS_CEILING = "wall_clock_exceeds_ceiling"
    OUTPUT_BYTE_CAP_EXCEEDS_CEILING = "output_byte_cap_exceeds_ceiling"
    OUTPUT_BYTE_CAP_BELOW_STDOUT = "output_byte_cap_below_stdout"
    OUTPUT_BYTE_CAP_BELOW_STDERR = "output_byte_cap_below_stderr"
    # Codex R1 F-002 adopt: CPU quota / period 比率で 4 CPU 超過を deny
    CPU_RATIO_EXCEEDS_CEILING = "cpu_ratio_exceeds_ceiling"
    # Codex R1 F-009 adopt: stdout + stderr 合計が output_byte_cap を超える policy を deny
    OUTPUT_BYTE_CAP_BELOW_STREAM_SUM = "output_byte_cap_below_stream_sum"


# 全 enum 値 (5+ source 整合検証用、`set(EXPECTED) == set(enum)` で test)
RESOURCE_CAP_DENY_REASONS: Final[frozenset[str]] = frozenset(
    r.value for r in ResourceCapDenyReason
)

# P0 absolute ceiling (これを超えるとどんな caller も deny)
_CEILING_CPU_QUOTA_US: Final[int] = 4_000_000  # 4 CPU cores at period=1_000_000
_CEILING_CPU_RATIO: Final[float] = 4.0  # Codex R1 F-002: quota/period <= 4 CPU
_CEILING_MEMORY_BYTES: Final[int] = 8 * 1024 * 1024 * 1024  # 8 GiB
_CEILING_PIDS_MAX: Final[int] = 4096
_CEILING_WALL_CLOCK_SECONDS: Final[float] = 30 * 60.0  # 30 min
_CEILING_OUTPUT_BYTE_CAP: Final[int] = 256 * 1024 * 1024  # 256 MiB


@dataclass(frozen=True, slots=True)
class ResourcePolicy:
    """Per-run resource cap policy.

    P0 default (``from_p0_defaults``):
    - cpu_quota_us / cpu_period_us: 1 CPU (1_000_000 / 1_000_000)
    - memory_bytes: 1 GiB
    - pids_max: 512
    - disk_bytes: 2 GiB (tmpfs / overlay)
    - wall_clock_seconds: 300.0 (5 min)
    - output_byte_cap: 16 MiB (stdout + stderr 合計)
    - stdout_byte_cap / stderr_byte_cap: 8 MiB ずつ
    """

    cpu_quota_us: int
    cpu_period_us: int
    memory_bytes: int
    pids_max: int
    disk_bytes: int
    wall_clock_seconds: float
    output_byte_cap: int
    stdout_byte_cap: int
    stderr_byte_cap: int

    @classmethod
    def from_p0_defaults(cls) -> ResourcePolicy:
        """ADR-00008 で承認された P0 safe defaults。"""
        return cls(
            cpu_quota_us=1_000_000,
            cpu_period_us=1_000_000,
            memory_bytes=1 * 1024 * 1024 * 1024,
            pids_max=512,
            disk_bytes=2 * 1024 * 1024 * 1024,
            wall_clock_seconds=300.0,
            output_byte_cap=16 * 1024 * 1024,
            stdout_byte_cap=8 * 1024 * 1024,
            stderr_byte_cap=8 * 1024 * 1024,
        )

    def validate(self) -> tuple[ResourceCapDenyReason, ...]:
        """Return tuple of violations (empty if valid)."""
        violations: list[ResourceCapDenyReason] = []

        if self.cpu_quota_us <= 0:
            violations.append(ResourceCapDenyReason.CPU_QUOTA_NON_POSITIVE)
        elif self.cpu_quota_us > _CEILING_CPU_QUOTA_US:
            violations.append(ResourceCapDenyReason.CPU_QUOTA_EXCEEDS_CEILING)

        if self.cpu_period_us <= 0:
            violations.append(ResourceCapDenyReason.CPU_PERIOD_NON_POSITIVE)

        if self.memory_bytes <= 0:
            violations.append(ResourceCapDenyReason.MEMORY_NON_POSITIVE)
        elif self.memory_bytes > _CEILING_MEMORY_BYTES:
            violations.append(ResourceCapDenyReason.MEMORY_EXCEEDS_CEILING)

        if self.pids_max <= 0:
            violations.append(ResourceCapDenyReason.PIDS_MAX_NON_POSITIVE)
        elif self.pids_max > _CEILING_PIDS_MAX:
            violations.append(ResourceCapDenyReason.PIDS_MAX_EXCEEDS_CEILING)

        if self.disk_bytes <= 0:
            violations.append(ResourceCapDenyReason.DISK_NON_POSITIVE)

        if self.wall_clock_seconds <= 0:
            violations.append(ResourceCapDenyReason.WALL_CLOCK_NON_POSITIVE)
        elif self.wall_clock_seconds > _CEILING_WALL_CLOCK_SECONDS:
            violations.append(ResourceCapDenyReason.WALL_CLOCK_EXCEEDS_CEILING)

        if self.output_byte_cap <= 0:
            violations.append(ResourceCapDenyReason.OUTPUT_BYTE_CAP_NON_POSITIVE)
        elif self.output_byte_cap > _CEILING_OUTPUT_BYTE_CAP:
            violations.append(ResourceCapDenyReason.OUTPUT_BYTE_CAP_EXCEEDS_CEILING)

        if self.stdout_byte_cap <= 0:
            violations.append(ResourceCapDenyReason.STDOUT_BYTE_CAP_NON_POSITIVE)
        if self.stderr_byte_cap <= 0:
            violations.append(ResourceCapDenyReason.STDERR_BYTE_CAP_NON_POSITIVE)

        # cross-field invariants (only check if individual values are valid)
        if (
            self.output_byte_cap > 0
            and self.stdout_byte_cap > 0
            and self.output_byte_cap < self.stdout_byte_cap
        ):
            violations.append(ResourceCapDenyReason.OUTPUT_BYTE_CAP_BELOW_STDOUT)
        if (
            self.output_byte_cap > 0
            and self.stderr_byte_cap > 0
            and self.output_byte_cap < self.stderr_byte_cap
        ):
            violations.append(ResourceCapDenyReason.OUTPUT_BYTE_CAP_BELOW_STDERR)

        # Codex R1 F-009 adopt: stdout + stderr 合計が output_byte_cap を超える
        # と stream-level cap 通過しても total が超える policy が成立してしまう
        if (
            self.output_byte_cap > 0
            and self.stdout_byte_cap > 0
            and self.stderr_byte_cap > 0
            and self.stdout_byte_cap + self.stderr_byte_cap > self.output_byte_cap
        ):
            violations.append(ResourceCapDenyReason.OUTPUT_BYTE_CAP_BELOW_STREAM_SUM)

        # Codex R1 F-002 adopt: CPU quota / period 比率で 4 CPU 超過を deny
        if (
            self.cpu_quota_us > 0
            and self.cpu_period_us > 0
            and self.cpu_quota_us / self.cpu_period_us > _CEILING_CPU_RATIO
        ):
            violations.append(ResourceCapDenyReason.CPU_RATIO_EXCEEDS_CEILING)

        return tuple(violations)


__all__ = [
    "RESOURCE_CAP_DENY_REASONS",
    "ResourceCapDenyReason",
    "ResourcePolicy",
]
