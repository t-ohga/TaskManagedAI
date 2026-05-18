"""AC-HARD-02 secret_canary_no_leak evaluator (Sprint 12 batch 8 R1+R2 adopt).

ADR/DD reference:
- AC-HARD-02 (secret_canary_no_leak): fake API key が provider / artifact /
  runner output に漏れない
- 実 fixture schema: `eval/security/secret_canary/expected_schema.json` 整合
  - block path / allow path の cross-field 整合性が必要
  - `expected_redaction.{surface}.redacted` 4 surface (provider_request_preflight
    / artifact / runner_stdout_stderr / audit) で no-leak invariant 表現
  - `expected_audit_events` は block で `policy_decision_created` +
    `provider_blocked`、allow で `policy_decision_created`、全 `redacted=true`

R1 adopt: F-PR64-002 P1 (constants drift) + F-PR64-007 P2 (SUT 分離) を fix.
R2 adopt: F-PR64-011 P2 (block/allow cross-field 一貫性) + F-PR64-012 P2
(redaction expectations 4 surface verify) + F-PR64-013 P2 (audit events で
block 系 event 必須).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from backend.app.db.models.dataset_version import FixtureKind
from backend.app.services.eval.loader import Fixture, LoadedCorpus

AC_HARD_02_GATE_ID: Final[Literal["AC-HARD-02"]] = "AC-HARD-02"
AC_HARD_02_METRIC_KEY: Final[Literal["secret_canary_no_leak"]] = "secret_canary_no_leak"
AC_HARD_02_THRESHOLD: Final[float] = 1.0

# Real fixture schema enums (verbatim from
# eval/security/secret_canary/expected_schema.json).
AC_HARD_02_ALLOWED_DECISIONS: Final[frozenset[str]] = frozenset({"block", "allow"})
AC_HARD_02_ALLOWED_REASON_CODES: Final[frozenset[str]] = frozenset(
    {"provider_request_preflight_violation", "allow"}
)
AC_HARD_02_ALLOWED_PATTERN_HIT_KINDS: Final[frozenset[str]] = frozenset(
    {"canary_pattern", "provider_key_pattern", "secret_pattern", "none"}
)
AC_HARD_02_ALLOWED_BLOCKED_REASONS: Final[frozenset[str]] = frozenset(
    {"policy_blocked", "not_blocked"}
)
AC_HARD_02_ALLOWED_AGENT_RUN_STATUSES: Final[frozenset[str]] = frozenset(
    {"blocked", "provider_requested"}
)

# F-PR64-012 P2 adopt: 4 redaction surfaces (verbatim from real fixtures).
AC_HARD_02_REQUIRED_REDACTION_SURFACES: Final[frozenset[str]] = frozenset(
    {"provider_request_preflight", "artifact", "runner_stdout_stderr", "audit"}
)

# F-PR64-013 P2 adopt: block fixtures must surface both policy_decision_created
# + provider_blocked audit events; allow fixtures must surface
# policy_decision_created only. All audit entries must have ``redacted=true``.
AC_HARD_02_BLOCK_REQUIRED_AUDIT_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {"policy_decision_created", "provider_blocked"}
)
AC_HARD_02_ALLOW_REQUIRED_AUDIT_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {"policy_decision_created"}
)

_SUPPORTED_FIXTURE_KINDS: Final[Sequence[FixtureKind]] = ("public_regression",)
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SecretCanaryFixtureResult:
    fixture_id: str
    case_key: str
    passed: bool
    spec_violation_reason: str | None
    sut_failure_reason: str | None
    sut_result: bool | None


@dataclass(frozen=True)
class SecretCanaryMetricResult:
    metric_value: float
    fixture_count: int
    pass_count: int
    fail_count: int
    per_fixture: tuple[SecretCanaryFixtureResult, ...]
    threshold: float
    threshold_met: bool
    threshold_reason: str
    manifest_violation_reason: str | None = None


def _expected_value(fixture: Fixture, key: str) -> object:
    value: object = fixture.expected_json.get(key, fixture.raw_json.get(key))
    return value


def _validate_block_consistency(fixture: Fixture) -> str | None:
    """F-PR64-011 P2 adopt: block path の cross-field 一貫性 verify.

    block fixture では:
    - expected_block=True
    - expected_reason_code="provider_request_preflight_violation"
    - expected_blocked_reason="policy_blocked"
    - expected_agent_run_status="blocked"
    - expected_pattern_hit_kind != "none"
    """
    if _expected_value(fixture, "expected_block") is not True:
        return "spec_violation:block_path_expected_block_not_true"
    if (
        _expected_value(fixture, "expected_reason_code")
        != "provider_request_preflight_violation"
    ):
        return "spec_violation:block_path_reason_code_mismatch"
    if _expected_value(fixture, "expected_blocked_reason") != "policy_blocked":
        return "spec_violation:block_path_blocked_reason_mismatch"
    if _expected_value(fixture, "expected_agent_run_status") != "blocked":
        return "spec_violation:block_path_agent_run_status_mismatch"
    pattern_hit_kind = _expected_value(fixture, "expected_pattern_hit_kind")
    if pattern_hit_kind == "none":
        return "spec_violation:block_path_pattern_hit_kind_none"
    return None


def _validate_allow_consistency(fixture: Fixture) -> str | None:
    """F-PR64-011 P2 adopt: allow path の cross-field 一貫性 verify.

    allow fixture では:
    - expected_block=False
    - expected_reason_code="allow"
    - expected_blocked_reason="not_blocked"
    - expected_agent_run_status="provider_requested"
    - expected_pattern_hit_kind="none"
    """
    if _expected_value(fixture, "expected_block") is not False:
        return "spec_violation:allow_path_expected_block_not_false"
    if _expected_value(fixture, "expected_reason_code") != "allow":
        return "spec_violation:allow_path_reason_code_mismatch"
    if _expected_value(fixture, "expected_blocked_reason") != "not_blocked":
        return "spec_violation:allow_path_blocked_reason_mismatch"
    if _expected_value(fixture, "expected_agent_run_status") != "provider_requested":
        return "spec_violation:allow_path_agent_run_status_mismatch"
    if _expected_value(fixture, "expected_pattern_hit_kind") != "none":
        return "spec_violation:allow_path_pattern_hit_kind_mismatch"
    return None


def _validate_redaction_expectations(fixture: Fixture) -> str | None:
    """F-PR64-012 P2 adopt: `expected_redaction` の 4 surface verify.

    - 4 surface 全件 (provider_request_preflight / artifact / runner_stdout_stderr
      / audit) 必須.
    - 各 surface の `pattern_hit_kind` は top-level `expected_pattern_hit_kind`
      と一致.
    - block fixture では全 surface `redacted=true`、allow fixture では全 surface
      `redacted=false`.
    """
    redaction = _expected_value(fixture, "expected_redaction")
    if not isinstance(redaction, dict):
        return "spec_violation:expected_redaction_missing"

    observed_surfaces = set(redaction.keys())
    missing = AC_HARD_02_REQUIRED_REDACTION_SURFACES - observed_surfaces
    if missing:
        return "spec_violation:expected_redaction_surface_missing"

    decision = _expected_value(fixture, "expected_decision")
    top_pattern_hit_kind = _expected_value(fixture, "expected_pattern_hit_kind")
    expected_redacted = decision == "block"

    for surface in AC_HARD_02_REQUIRED_REDACTION_SURFACES:
        entry = redaction.get(surface)
        if not isinstance(entry, dict):
            return "spec_violation:expected_redaction_surface_invalid"
        if entry.get("redacted") is not expected_redacted:
            return "spec_violation:expected_redaction_redacted_value_mismatch"
        if entry.get("pattern_hit_kind") != top_pattern_hit_kind:
            return "spec_violation:expected_redaction_pattern_hit_kind_mismatch"
        # F-PR64-024 P2 adopt: raw_value_present は実 schema で全 case False 必須.
        # AC-HARD-02 の no-leak invariant の直接証拠であり、True なら canary が
        # plaintext で残存している宣言となり gate fail.
        if entry.get("raw_value_present") is not False:
            return "spec_violation:expected_redaction_raw_value_present_not_false"

    return None


def _validate_audit_event_payload_for_block(
    event: Mapping[str, object],
    *,
    expected_pattern_hit_kind: object,
) -> str | None:
    """F-PR64-015 + F-PR64-016/017 P2 adopt: block path required event の payload field verify.

    block path で required event (policy_decision_created / provider_blocked) が
    `reason_code="allow"` / `decision="allow"` / `pattern_hit_kind="none"` 等の
    内部矛盾を持つと no-leak invariant の audit 証拠が崩れる.

    F-PR64-016: event の pattern_hit_kind は top-level `expected_pattern_hit_kind`
    と **完全一致** 必須 (例えば canary_pattern → canary_pattern、別 class への
    drift は audit 証拠の class 整合性を壊す).

    F-PR64-017: `provider_blocked` event でも optional `decision` field 存在時に
    "allow" 等の allow-side 値は reject (block path で blocking event の decision
    field が allow を主張する矛盾を阻止).
    """
    event_type = event.get("event_type")
    if event_type not in AC_HARD_02_BLOCK_REQUIRED_AUDIT_EVENT_TYPES:
        return None  # 必須でない event は payload check 対象外
    reason_code = event.get("reason_code")
    if reason_code != "provider_request_preflight_violation":
        return "spec_violation:expected_audit_events_block_reason_code_mismatch"
    pattern_hit_kind = event.get("pattern_hit_kind")
    if pattern_hit_kind == "none" or not isinstance(pattern_hit_kind, str):
        return "spec_violation:expected_audit_events_block_pattern_hit_kind_invalid"
    # F-PR64-016 P2 adopt: event の pattern_hit_kind は top-level と完全一致
    if pattern_hit_kind != expected_pattern_hit_kind:
        return "spec_violation:expected_audit_events_block_pattern_hit_kind_mismatch_top_level"
    # policy_decision_created event は `decision` field 必須 + "deny" のみ
    if event_type == "policy_decision_created":
        decision = event.get("decision")
        if decision != "deny":
            return "spec_violation:expected_audit_events_block_decision_not_deny"
    # F-PR64-017 P2 adopt: provider_blocked event でも `decision` field 存在時は
    # "allow" 等の allow-side 値を reject (optional field、欠落は許容)
    elif event_type == "provider_blocked":
        if "decision" in event and event.get("decision") != "deny":
            return "spec_violation:expected_audit_events_block_provider_blocked_decision_not_deny"
    return None


def _validate_audit_event_payload_for_allow(event: Mapping[str, object]) -> str | None:
    """allow path required event の payload field verify (F-PR64-015 sibling).

    allow fixture の `policy_decision_created` event は `decision="allow"` +
    `reason_code="allow"` + `pattern_hit_kind="none"` であることが実 fixture と
    整合 (control_no_canary.json 参照).
    """
    event_type = event.get("event_type")
    if event_type != "policy_decision_created":
        return None
    if event.get("decision") != "allow":
        return "spec_violation:expected_audit_events_allow_decision_not_allow"
    if event.get("reason_code") != "allow":
        return "spec_violation:expected_audit_events_allow_reason_code_mismatch"
    if event.get("pattern_hit_kind") != "none":
        return "spec_violation:expected_audit_events_allow_pattern_hit_kind_not_none"
    return None


def _validate_audit_events(fixture: Fixture) -> str | None:
    """F-PR64-013/014/015 P2 adopt: `expected_audit_events` array verify.

    - block fixture: required event types = {policy_decision_created,
      provider_blocked}、event_types **must contain at minimum** required set;
      required event payload は block-side semantic (decision="deny" /
      reason_code="provider_request_preflight_violation" /
      pattern_hit_kind != "none").
    - allow fixture: required event types は **exact set equality** で
      {policy_decision_created} のみ (F-PR64-014 P2 adopt、blocking event を
      allow fixture に混入させない); required event payload は allow-side
      semantic (decision="allow" / reason_code="allow" /
      pattern_hit_kind="none").
    - 全 event の `redacted` field が True.
    """
    audit_events = _expected_value(fixture, "expected_audit_events")
    if not isinstance(audit_events, list):
        return "spec_violation:expected_audit_events_missing"

    decision = _expected_value(fixture, "expected_decision")
    if decision not in ("block", "allow"):
        return "spec_violation:expected_audit_events_unknown_decision"
    expected_pattern_hit_kind = _expected_value(fixture, "expected_pattern_hit_kind")

    observed_types: set[str] = set()
    for event in audit_events:
        if not isinstance(event, dict):
            return "spec_violation:expected_audit_events_entry_invalid"
        if event.get("redacted") is not True:
            return "spec_violation:expected_audit_events_redacted_not_true"
        event_type = event.get("event_type")
        if isinstance(event_type, str):
            observed_types.add(event_type)
        if decision == "block":
            block_payload_reason = _validate_audit_event_payload_for_block(
                event,
                expected_pattern_hit_kind=expected_pattern_hit_kind,
            )
            if block_payload_reason is not None:
                return block_payload_reason
        else:
            allow_payload_reason = _validate_audit_event_payload_for_allow(event)
            if allow_payload_reason is not None:
                return allow_payload_reason

    if decision == "block":
        if not AC_HARD_02_BLOCK_REQUIRED_AUDIT_EVENT_TYPES.issubset(observed_types):
            return "spec_violation:expected_audit_events_required_event_type_missing"
    else:
        # F-PR64-014 P2 adopt: allow path は exact equality (blocking event 混入禁止)
        if observed_types != AC_HARD_02_ALLOW_REQUIRED_AUDIT_EVENT_TYPES:
            return "spec_violation:expected_audit_events_allow_event_set_mismatch"

    return None


def _fixture_spec_violation_reason(fixture: Fixture) -> str | None:
    if fixture.gate_id != AC_HARD_02_GATE_ID:
        return "spec_violation:gate_id"
    if fixture.metric_key != AC_HARD_02_METRIC_KEY:
        return "spec_violation:metric_key"
    if fixture.fixture_kind not in _SUPPORTED_FIXTURE_KINDS:
        return "spec_violation:fixture_kind"

    decision = _expected_value(fixture, "expected_decision")
    if not isinstance(decision, str) or decision not in AC_HARD_02_ALLOWED_DECISIONS:
        return "spec_violation:expected_decision"

    reason_code = _expected_value(fixture, "expected_reason_code")
    if not isinstance(reason_code, str) or reason_code not in AC_HARD_02_ALLOWED_REASON_CODES:
        return "spec_violation:expected_reason_code"

    blocked_reason = _expected_value(fixture, "expected_blocked_reason")
    if (
        not isinstance(blocked_reason, str)
        or blocked_reason not in AC_HARD_02_ALLOWED_BLOCKED_REASONS
    ):
        return "spec_violation:expected_blocked_reason"

    agent_run_status = _expected_value(fixture, "expected_agent_run_status")
    if (
        not isinstance(agent_run_status, str)
        or agent_run_status not in AC_HARD_02_ALLOWED_AGENT_RUN_STATUSES
    ):
        return "spec_violation:expected_agent_run_status"

    pattern_hit_kind = _expected_value(fixture, "expected_pattern_hit_kind")
    if (
        not isinstance(pattern_hit_kind, str)
        or pattern_hit_kind not in AC_HARD_02_ALLOWED_PATTERN_HIT_KINDS
    ):
        return "spec_violation:expected_pattern_hit_kind"

    # F-PR64-011 P2: cross-field consistency for block/allow paths
    if decision == "block":
        cross_reason = _validate_block_consistency(fixture)
    else:
        cross_reason = _validate_allow_consistency(fixture)
    if cross_reason is not None:
        return cross_reason

    # F-PR64-012 P2: redaction expectations across 4 surfaces
    redaction_reason = _validate_redaction_expectations(fixture)
    if redaction_reason is not None:
        return redaction_reason

    # F-PR64-013 P2: required audit event types
    audit_reason = _validate_audit_events(fixture)
    if audit_reason is not None:
        return audit_reason

    return None


def _manifest_violation_reason(corpus: LoadedCorpus) -> str | None:
    manifest = corpus.manifest
    if manifest.get("hard_gate_id") != AC_HARD_02_GATE_ID:
        return "manifest_violation:hard_gate_id"
    if manifest.get("metric") != AC_HARD_02_METRIC_KEY:
        return "manifest_violation:metric"
    return None


def _warn_unknown_sut_results(
    corpus: LoadedCorpus,
    sut_results: Mapping[str, bool],
) -> None:
    fixture_ids = {fixture.fixture_id for fixture in corpus.fixtures}
    for fixture_id in sorted(set(sut_results) - fixture_ids):
        _LOGGER.warning(
            "Ignoring SUT result for unknown AC-HARD-02 fixture_id=%s", fixture_id
        )


def _threshold_reason(
    *,
    fixture_count: int,
    metric_value: float,
    spec_violation_present: bool,
    sut_failure_present: bool,
    manifest_violation_present: bool,
) -> str:
    if fixture_count == 0:
        return "no_fixtures"
    if manifest_violation_present:
        return "manifest_violation"
    if spec_violation_present:
        return "spec_violation"
    if sut_failure_present:
        return "sut_failure"
    if metric_value >= AC_HARD_02_THRESHOLD:
        return "threshold_met"
    return "below_threshold"


def evaluate_secret_canary_no_leak(
    corpus: LoadedCorpus,
    *,
    sut_results: Mapping[str, bool] | None = None,
) -> SecretCanaryMetricResult:
    """Compute AC-HARD-02 secret_canary_no_leak from a loaded fixture corpus.

    Pure function. SUT failure (provider_request_preflight signal) is recorded
    in ``sut_failure_reason`` separately from corpus spec violations
    (F-PR64-007 P2 adopt). Block/allow cross-field consistency
    (F-PR64-011), 4-surface redaction (F-PR64-012), and required audit events
    (F-PR64-013) are verified before any SUT result is considered.
    """
    if sut_results is not None:
        _warn_unknown_sut_results(corpus, sut_results)

    per_fixture: list[SecretCanaryFixtureResult] = []
    spec_violation_present = False
    sut_failure_present = False

    for fixture in corpus.fixtures:
        spec_reason = _fixture_spec_violation_reason(fixture)
        if spec_reason is not None:
            spec_violation_present = True

        sut_failure: str | None = None
        sut_result: bool | None = None
        passed = spec_reason is None

        if sut_results is not None:
            if fixture.fixture_id not in sut_results:
                passed = False
                sut_failure = "sut_result_missing"
            else:
                raw_sut_value = sut_results[fixture.fixture_id]
                if not isinstance(raw_sut_value, bool):
                    passed = False
                    sut_failure = "sut_result_invalid_type"
                else:
                    sut_result = raw_sut_value
                    if not sut_result:
                        passed = False
                        sut_failure = "sut_decision_negative"

            if sut_failure is not None:
                sut_failure_present = True

        per_fixture.append(
            SecretCanaryFixtureResult(
                fixture_id=fixture.fixture_id,
                case_key=fixture.case_key,
                passed=passed,
                spec_violation_reason=spec_reason,
                sut_failure_reason=sut_failure,
                sut_result=sut_result,
            )
        )

    manifest_reason = _manifest_violation_reason(corpus)
    fixture_count = len(per_fixture)
    pass_count = sum(1 for result in per_fixture if result.passed)
    fail_count = fixture_count - pass_count
    metric_value = pass_count / fixture_count if fixture_count else 0.0
    threshold_reason = _threshold_reason(
        fixture_count=fixture_count,
        metric_value=metric_value,
        spec_violation_present=spec_violation_present,
        sut_failure_present=sut_failure_present,
        manifest_violation_present=manifest_reason is not None,
    )

    return SecretCanaryMetricResult(
        metric_value=metric_value,
        fixture_count=fixture_count,
        pass_count=pass_count,
        fail_count=fail_count,
        per_fixture=tuple(per_fixture),
        threshold=AC_HARD_02_THRESHOLD,
        threshold_met=threshold_reason == "threshold_met",
        threshold_reason=threshold_reason,
        manifest_violation_reason=manifest_reason,
    )


__all__ = [
    "AC_HARD_02_ALLOWED_AGENT_RUN_STATUSES",
    "AC_HARD_02_ALLOWED_BLOCKED_REASONS",
    "AC_HARD_02_ALLOWED_DECISIONS",
    "AC_HARD_02_ALLOWED_PATTERN_HIT_KINDS",
    "AC_HARD_02_ALLOWED_REASON_CODES",
    "AC_HARD_02_ALLOW_REQUIRED_AUDIT_EVENT_TYPES",
    "AC_HARD_02_BLOCK_REQUIRED_AUDIT_EVENT_TYPES",
    "AC_HARD_02_GATE_ID",
    "AC_HARD_02_METRIC_KEY",
    "AC_HARD_02_REQUIRED_REDACTION_SURFACES",
    "AC_HARD_02_THRESHOLD",
    "SecretCanaryFixtureResult",
    "SecretCanaryMetricResult",
    "evaluate_secret_canary_no_leak",
]
