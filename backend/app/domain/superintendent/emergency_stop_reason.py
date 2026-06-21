"""emergency-stop reason_code enum (SP-PHASE1 B3、ADR-00048 §Amendment A-6)。

emergency-stop の deny / decision を表す **独立した application-level reason_code**。

A-6 の位置づけ (sealed enum を汚さない):
- **(i)** AgentRun ``blocked_reason`` enum (3 種: policy/budget/runtime) には **追加しない**
  (emergency-stop block は ``status='blocked'`` + ``blocked_reason='runtime_blocked'`` を使う)。
- **(ii)** Provider Compliance 13-reason_code にも **追加しない**。
- **(iii)** 本 module の独立 enum + audit payload で 5+source 整合させる
  (cross-source-enum-integrity §1: Python Literal / tuple / pytest EXPECTED で exact-set)。

``emergency_stop_engaged``  : latch engaged 中に新規活動 (spawn / run 作成 / provider 等) を deny した。
``emergency_stop_resumed``  : clear / resume で block 中 run を ``pre_stop_status`` へ復元した。
``emergency_stop_cleared``  : latch を clear (active latch を解除) した。

これらは audit payload の ``reason_code`` field に入る非 secret な application 識別子であり、
``managed_agents.state`` enum や AgentRunEventType (block/resume の **event** witnessing) とは別軸。
event_type ``emergency_stop_engaged`` / ``emergency_stop_resumed`` (B1) は AgentRunEvent の
state transition witness であり、本 reason_code は audit_events 上の decision 識別子である。
"""

from __future__ import annotations

from typing import Literal

EmergencyStopReasonCode = Literal[
    "emergency_stop_engaged",
    "emergency_stop_resumed",
    "emergency_stop_cleared",
]

ALL_EMERGENCY_STOP_REASON_CODES: tuple[EmergencyStopReasonCode, ...] = (
    "emergency_stop_engaged",
    "emergency_stop_resumed",
    "emergency_stop_cleared",
)

#: 新規活動 deny で choke point (B5) / spawn latch (B3 _assert_not_emergency_stopped) が使う code。
DENY_REASON_CODE: EmergencyStopReasonCode = "emergency_stop_engaged"

__all__ = [
    "ALL_EMERGENCY_STOP_REASON_CODES",
    "DENY_REASON_CODE",
    "EmergencyStopReasonCode",
]
