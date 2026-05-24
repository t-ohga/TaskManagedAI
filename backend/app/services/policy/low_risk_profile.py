from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final, Literal

PayloadDataClass = Literal["public", "internal", "confidential", "pii"]
LowRiskProfileAxis = Literal[
    "payload_data_class",
    "change_scope",
    "forbidden_path",
    "dangerous_command",
    "provider_request_preflight",
    "runner_mutation_gateway",
    "context_snapshot",
]

PAYLOAD_DATA_CLASS_RANK: Final[dict[PayloadDataClass, int]] = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "pii": 3,
}
LOW_RISK_MAX_PAYLOAD_DATA_CLASS: Final[PayloadDataClass] = "internal"
LOW_RISK_MAX_DIFF_LINES: Final[int] = 200
LOW_RISK_MAX_FILE_COUNT: Final[int] = 3

FORBIDDEN_PATH_PREFIXES: Final[tuple[str, ...]] = (
    ".github/workflows/",
    "migrations/",
    "secrets/",
)
FORBIDDEN_PATH_EXACT: Final[frozenset[str]] = frozenset(
    {
        ".env",
        ".git/config",
    }
)
FORBIDDEN_PATH_SUBSTRINGS: Final[tuple[str, ...]] = (
    "/secrets/",
    "/.env",
)
DANGEROUS_COMMAND_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\brm\s+-rf\b"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bchmod\s+777\b"),
    re.compile(r"\bcurl\b.*\|\s*(?:sh|bash)\b"),
    re.compile(r"\bgh\s+pr\s+merge\b"),
    re.compile(r"\bgit\s+push\b"),
    re.compile(r"\bgit\s+reset\s+--hard\b"),
    re.compile(r"\bdocker\s+compose\s+down\b.*\s-v\b"),
    re.compile(r"\balembic\s+downgrade\b"),
)


@dataclass(frozen=True)
class LowRiskProfileInput:
    payload_data_class: PayloadDataClass
    diff_line_count: int
    changed_paths: tuple[str, ...] = field(default_factory=tuple)
    commands: tuple[str, ...] = field(default_factory=tuple)
    provider_request_preflight_passed: bool = True
    runner_mutation_gateway_passed: bool = True
    context_snapshot_passed: bool = True
    max_diff_lines: int = LOW_RISK_MAX_DIFF_LINES
    max_file_count: int = LOW_RISK_MAX_FILE_COUNT


@dataclass(frozen=True)
class LowRiskProfileDecision:
    allowed: bool
    failed_axes: tuple[LowRiskProfileAxis, ...]
    reason_code: str


def evaluate_low_risk_profile(payload: LowRiskProfileInput) -> LowRiskProfileDecision:
    failed_axes: list[LowRiskProfileAxis] = []

    if (
        PAYLOAD_DATA_CLASS_RANK[payload.payload_data_class]
        > PAYLOAD_DATA_CLASS_RANK[LOW_RISK_MAX_PAYLOAD_DATA_CLASS]
    ):
        failed_axes.append("payload_data_class")
    if payload.diff_line_count > payload.max_diff_lines or len(
        payload.changed_paths
    ) > payload.max_file_count:
        failed_axes.append("change_scope")
    if any(_is_forbidden_path(path) for path in payload.changed_paths):
        failed_axes.append("forbidden_path")
    if any(_is_dangerous_command(command) for command in payload.commands):
        failed_axes.append("dangerous_command")
    if not payload.provider_request_preflight_passed:
        failed_axes.append("provider_request_preflight")
    if not payload.runner_mutation_gateway_passed:
        failed_axes.append("runner_mutation_gateway")
    if not payload.context_snapshot_passed:
        failed_axes.append("context_snapshot")

    if failed_axes:
        return LowRiskProfileDecision(
            allowed=False,
            failed_axes=tuple(failed_axes),
            reason_code="low_risk_profile_failed",
        )
    return LowRiskProfileDecision(
        allowed=True,
        failed_axes=(),
        reason_code="low_risk_profile_passed",
    )


def _is_forbidden_path(path: str) -> bool:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    if normalized in FORBIDDEN_PATH_EXACT:
        return True
    if any(normalized.startswith(prefix) for prefix in FORBIDDEN_PATH_PREFIXES):
        return True
    return any(substring in f"/{normalized}" for substring in FORBIDDEN_PATH_SUBSTRINGS)


def _is_dangerous_command(command: str) -> bool:
    return any(pattern.search(command) is not None for pattern in DANGEROUS_COMMAND_PATTERNS)


__all__ = [
    "LOW_RISK_MAX_DIFF_LINES",
    "LOW_RISK_MAX_FILE_COUNT",
    "LOW_RISK_MAX_PAYLOAD_DATA_CLASS",
    "LowRiskProfileAxis",
    "LowRiskProfileDecision",
    "LowRiskProfileInput",
    "PayloadDataClass",
    "evaluate_low_risk_profile",
]
