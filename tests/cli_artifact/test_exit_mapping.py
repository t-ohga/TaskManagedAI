"""Sprint 6 Batch 2: CLI exit mapping と completed payload の契約テスト。"""

from __future__ import annotations

import hashlib

import pytest

from backend.app.services.cli_artifact.exit_mapping import (
    CliExitOutcome,
    CliProcessCompletedPayload,
    build_cli_process_completed_payload,
    map_launcher_result,
)
from backend.app.services.cli_artifact.launcher import LauncherResult
from backend.app.services.cli_artifact.redaction import (
    RedactionHit,
    RedactionResult,
)


def _launcher_result(
    *,
    exit_code: int | None = 0,
    timeout_reached: bool = False,
    cancelled: bool = False,
    signal: str | None = None,
) -> LauncherResult:
    return LauncherResult(
        agent_name="codex",
        exit_code=exit_code,
        timeout_reached=timeout_reached,
        cancelled=cancelled,
        duration_seconds=1.25,
        stdout_bytes=11,
        stderr_bytes=7,
        signal=signal,
    )


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _redaction(
    label: str,
    *,
    raw_bytes_length: int = 0,
    hits: tuple[RedactionHit, ...] = (),
) -> RedactionResult:
    return RedactionResult(
        redacted_text=f"redacted-{label}",
        redacted_content_hash=_hash(label),
        raw_bytes_length=raw_bytes_length,
        truncated=False,
        hits=hits,
        prohibited_key_hits=(),
    )


def _payload(
    *,
    result: LauncherResult | None = None,
    stdout: RedactionResult | None = None,
    stderr: RedactionResult | None = None,
    outcome: CliExitOutcome = CliExitOutcome.SUCCESS,
) -> CliProcessCompletedPayload:
    return build_cli_process_completed_payload(
        result=result or _launcher_result(),
        stdout_redaction=stdout or _redaction("stdout", raw_bytes_length=11),
        stderr_redaction=stderr or _redaction("stderr", raw_bytes_length=7),
        outcome=outcome,
    )


def test_map_success_exit_code_0_returns_running() -> None:
    decision = map_launcher_result(_launcher_result(exit_code=0))

    assert decision.outcome is CliExitOutcome.SUCCESS
    assert decision.next_status == "running"
    assert decision.blocked_reason is None
    assert decision.is_terminal is False


def test_map_non_zero_exit_returns_failed_terminal() -> None:
    decision = map_launcher_result(_launcher_result(exit_code=2))

    assert decision.outcome is CliExitOutcome.FAILED
    assert decision.next_status == "failed"
    assert decision.blocked_reason is None
    assert decision.is_terminal is True


def test_map_timeout_returns_blocked_runtime_blocked() -> None:
    decision = map_launcher_result(_launcher_result(exit_code=None, timeout_reached=True))

    assert decision.outcome is CliExitOutcome.TIMEOUT
    assert decision.next_status == "blocked"
    assert decision.blocked_reason == "runtime_blocked"
    assert decision.is_terminal is False


def test_map_cancelled_returns_cancelled_terminal() -> None:
    decision = map_launcher_result(_launcher_result(exit_code=None, cancelled=True))

    assert decision.outcome is CliExitOutcome.CANCELLED
    assert decision.next_status == "cancelled"
    assert decision.blocked_reason is None
    assert decision.is_terminal is True


def test_map_priority_cancelled_over_timeout() -> None:
    decision = map_launcher_result(
        _launcher_result(exit_code=2, timeout_reached=True, cancelled=True)
    )

    assert decision.outcome is CliExitOutcome.CANCELLED
    assert decision.next_status == "cancelled"


def test_map_priority_timeout_over_non_zero_exit() -> None:
    decision = map_launcher_result(_launcher_result(exit_code=2, timeout_reached=True))

    assert decision.outcome is CliExitOutcome.TIMEOUT
    assert decision.next_status == "blocked"


def test_cli_exit_outcome_enum_has_4_values() -> None:
    assert {outcome.value for outcome in CliExitOutcome} == {
        "success",
        "failed",
        "timeout",
        "cancelled",
    }


def test_exit_mapping_decision_is_frozen() -> None:
    decision = map_launcher_result(_launcher_result())

    with pytest.raises(AttributeError):
        decision.next_status = "failed"


def test_build_payload_includes_required_keys() -> None:
    payload = _payload()

    assert set(payload.keys()) == {
        "agent_name",
        "exit_code",
        "signal",
        "duration_seconds",
        "timeout_reached",
        "cancelled",
        "stdout_bytes",
        "stderr_bytes",
        "stdout_redacted_hash",
        "stderr_redacted_hash",
        "redaction_hit_count",
        "outcome",
    }


def test_build_payload_redaction_hit_count_sums_stdout_stderr_hits() -> None:
    stdout = _redaction(
        "stdout",
        raw_bytes_length=11,
        hits=(RedactionHit(pattern_kind="openai_api_key", match_count=2),),
    )
    stderr = _redaction(
        "stderr",
        raw_bytes_length=7,
        hits=(
            RedactionHit(pattern_kind="github_oauth_token", match_count=3),
            RedactionHit(pattern_kind="pem_private_key", match_count=1),
        ),
    )

    payload = _payload(stdout=stdout, stderr=stderr)

    assert payload["redaction_hit_count"] == 6


def test_build_payload_redaction_hit_count_zero_when_no_hits() -> None:
    payload = _payload()

    assert payload["redaction_hit_count"] == 0


def test_build_payload_does_not_include_raw_stdout_or_stderr() -> None:
    payload = _payload()

    assert "stdout" not in payload
    assert "stderr" not in payload
    assert "raw_stdout" not in payload
    assert "raw_stderr" not in payload


def test_build_payload_stdout_redacted_hash_propagates() -> None:
    stdout = _redaction("stdout-special", raw_bytes_length=13)

    payload = _payload(stdout=stdout)

    assert payload["stdout_redacted_hash"] == stdout.redacted_content_hash


def test_build_payload_stderr_redacted_hash_propagates() -> None:
    stderr = _redaction("stderr-special", raw_bytes_length=17)

    payload = _payload(stderr=stderr)

    assert payload["stderr_redacted_hash"] == stderr.redacted_content_hash


@pytest.mark.parametrize("outcome", tuple(CliExitOutcome), ids=lambda o: o.value)
def test_build_payload_outcome_field_matches_decision(
    outcome: CliExitOutcome,
) -> None:
    payload = _payload(outcome=outcome)

    assert payload["outcome"] == outcome.value


@pytest.mark.parametrize("signal", ["SIGTERM", "SIGKILL"])
def test_build_payload_signal_propagates(signal: str) -> None:
    payload = _payload(result=_launcher_result(exit_code=None, signal=signal))

    assert payload["signal"] == signal


def test_build_payload_exit_code_none_for_cancelled() -> None:
    payload = _payload(
        result=_launcher_result(exit_code=None, cancelled=True),
        outcome=CliExitOutcome.CANCELLED,
    )

    assert payload["exit_code"] is None
    assert payload["cancelled"] is True


def test_typed_dict_payload_is_dict_at_runtime() -> None:
    payload = _payload()

    assert isinstance(payload, dict)
    assert payload["agent_name"] == "codex"


def test_map_zero_exit_with_timeout_returns_timeout() -> None:
    decision = map_launcher_result(_launcher_result(exit_code=0, timeout_reached=True))

    assert decision.outcome is CliExitOutcome.TIMEOUT
    assert decision.next_status == "blocked"
    assert decision.blocked_reason == "runtime_blocked"


@pytest.mark.parametrize(
    ("result", "expected_reason"),
    [
        (_launcher_result(exit_code=0), None),
        (_launcher_result(exit_code=9), None),
        (_launcher_result(exit_code=None, cancelled=True), None),
        (_launcher_result(exit_code=None, timeout_reached=True), "runtime_blocked"),
    ],
)
def test_blocked_reason_is_none_unless_timeout(
    result: LauncherResult, expected_reason: str | None
) -> None:
    decision = map_launcher_result(result)

    assert decision.blocked_reason == expected_reason

