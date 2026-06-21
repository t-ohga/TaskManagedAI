"""SP-PHASE1 B3: emergency-stop reason_code の cross-source 整合 test (ADR-00048 §A-6)。

``emergency_stop_engaged`` は **独立した application-level reason_code** (A-6):
- (i) AgentRun ``blocked_reason`` enum (3 種) に追加しない。
- (ii) Provider Compliance 13 reason_code に追加しない。
- (iii) 独立 enum で 5+source 整合 (Python Literal / tuple / pytest EXPECTED /
  ``EmergencyStopEngagedError.reason_code`` / DENY_REASON_CODE)。

cross-source-enum-integrity §1 に従い exact-set 比較で固定し、既存 sealed enum を汚さないこと
(他軸に reason_code が混入していないこと) を negative 方向でも assert する。
"""

from __future__ import annotations

from typing import get_args

from backend.app.domain.agent_runtime.status import ALL_BLOCKED_REASONS
from backend.app.domain.superintendent.emergency_stop_reason import (
    ALL_EMERGENCY_STOP_REASON_CODES,
    DENY_REASON_CODE,
    EmergencyStopReasonCode,
)
from backend.app.services.superintendent.emergency_stop import EmergencyStopEngagedError

# 正本 (ADR-00048 §A-6)。
EXPECTED_EMERGENCY_STOP_REASON_CODES: frozenset[str] = frozenset(
    {
        "emergency_stop_engaged",
        "emergency_stop_resumed",
        "emergency_stop_cleared",
    }
)


def test_literal_and_tuple_match_expected() -> None:
    assert frozenset(get_args(EmergencyStopReasonCode)) == (
        EXPECTED_EMERGENCY_STOP_REASON_CODES
    )
    assert frozenset(ALL_EMERGENCY_STOP_REASON_CODES) == (
        EXPECTED_EMERGENCY_STOP_REASON_CODES
    )


def test_deny_reason_code_is_engaged() -> None:
    assert DENY_REASON_CODE == "emergency_stop_engaged"
    assert DENY_REASON_CODE in EXPECTED_EMERGENCY_STOP_REASON_CODES


def test_engaged_error_reason_code_matches_deny() -> None:
    err = EmergencyStopEngagedError(tenant_id=1)
    assert err.reason_code == "emergency_stop_engaged"
    assert err.reason_code in EXPECTED_EMERGENCY_STOP_REASON_CODES


def test_reason_code_not_in_blocked_reason_enum() -> None:
    """A-6 (i): emergency_stop_engaged は blocked_reason (3 種) に混ぜない (sealed enum 不変)。"""
    blocked_reasons = frozenset(ALL_BLOCKED_REASONS)
    assert blocked_reasons == frozenset({"policy_blocked", "budget_blocked", "runtime_blocked"})
    assert EXPECTED_EMERGENCY_STOP_REASON_CODES.isdisjoint(blocked_reasons)


def test_reason_code_not_in_provider_compliance_reasons() -> None:
    """A-6 (ii): Provider Compliance 13 reason_code に emergency_stop_* を追加しない。"""
    from backend.app.domain.provider.compliance import ALL_COMPLIANCE_REASON_CODES

    provider_reason_codes = frozenset(ALL_COMPLIANCE_REASON_CODES)
    assert EXPECTED_EMERGENCY_STOP_REASON_CODES.isdisjoint(provider_reason_codes)
