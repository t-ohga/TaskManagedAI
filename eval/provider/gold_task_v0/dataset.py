from __future__ import annotations

from typing import Any

from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.services.agent_runtime.provider_result_mapping import ProviderResultKind

# F-PR36-001 (Codex R1 P1) adopt: bump dataset version when corpus changes.
# Sprint 5 (2026-05-09) had 3 cases (simple_request / structured_output /
# safety_refusal). Sprint 11 batch 5h (2026-05-17) expanded to 30 cases.
# Per Anti-Gaming dataset_version_id contract, any corpus change requires
# a bump so EvalResult / ContextSnapshot trace stays unambiguous.
DATASET_VERSION_ID = "gold-task-v0-2026-05-17"

_SIMPLE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["answer"],
    "properties": {
        "answer": {"type": "string", "minLength": 1},
    },
    "additionalProperties": False,
}

_STRUCTURED_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary", "risk_score", "next_actions"],
    "properties": {
        "summary": {"type": "string", "minLength": 1},
        "risk_score": {"type": "number", "minimum": 0, "maximum": 1},
        "next_actions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["title", "priority"],
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}


_ALLOWED_PAYLOAD_DATA_CLASSES: tuple[str, ...] = (
    "public",
    "internal",
    "confidential",
    "pii",
)
_ALLOWED_SANITIZATION_STATUSES: tuple[str, ...] = (
    "clean",       # already sanitized, no PII / secret leakage
    "redacted",    # had original PII / secret, scrubbed before commit
    "synthetic",   # generated, no human-source content
)


class GoldTaskMetadata(BaseModel):
    """Per-task provenance + sanitization metadata.

    F-PR36-003 (Codex R1 P2) adopt: BL-0006 「Gold Task Seed v0 の
    保存 schema と除外基準」 + BL-0163 「payload_data_class 付与」
    carry-over. Each Sprint 11 batch 5h+ gold task must record:

    * ``source``: origin trace (e.g., "BL-0163 batch 5h synthetic",
      "BL-0006 Sprint 5 original").
    * ``domain``: task category for stratified coverage analysis.
    * ``payload_data_class``: per-task data classification (must be
      one of the 4 canonical Provider Compliance ordinals).
    * ``sanitization_status``: how this task was prepared for inclusion
      (synthetic / clean / redacted).
    * ``exclusion_basis``: reason this task is **NOT** excluded (P0
      Gold Task Seed v0 includes all 30 cases; SP-022 will introduce
      formal exclusion criteria).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(..., min_length=1)
    domain: str = Field(..., min_length=1)
    payload_data_class: str
    sanitization_status: str
    exclusion_basis: str | None = None

    @field_validator("payload_data_class")
    @classmethod
    def _validate_data_class(cls, value: str) -> str:
        if value not in _ALLOWED_PAYLOAD_DATA_CLASSES:
            raise ValueError(
                f"payload_data_class {value!r} must be one of "
                f"{_ALLOWED_PAYLOAD_DATA_CLASSES}"
            )
        return value

    @field_validator("sanitization_status")
    @classmethod
    def _validate_sanitization(cls, value: str) -> str:
        if value not in _ALLOWED_SANITIZATION_STATUSES:
            raise ValueError(
                f"sanitization_status {value!r} must be one of "
                f"{_ALLOWED_SANITIZATION_STATUSES}"
            )
        return value


class GoldTaskCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(..., min_length=1)
    request_template: dict[str, Any]
    expected_status: ProviderResultKind
    expected_artifact_shape: dict[str, Any]
    expected_redacted_summary_shape: dict[str, Any] | None = None
    # F-PR36-003 (Codex R1 P2) adopt: per-task provenance + sanitization
    # metadata (BL-0006 schema + 除外基準 / BL-0163 「payload_data_class
    # 付与」 carry-over). Sprint 5 originals leave this None for
    # backwards compat; Sprint 11 batch 5h+ entries should populate.
    task_metadata: GoldTaskMetadata | None = None
    # F-PR36-002 (Codex R1 P2) adopt: optional task-specific output
    # oracle keywords. Downstream evaluators (SP-012 real-provider
    # runs) check that the returned ``answer`` / ``summary`` contains
    # at least one of these substrings (case-insensitive). P0 mock
    # tests do NOT enforce these keywords; the field is corpus
    # metadata only. Empty tuple = no keyword oracle (generic
    # schema-shape validation suffices).
    task_oracle_keywords: tuple[str, ...] = ()

    @field_validator("request_template")
    @classmethod
    def _request_template_must_have_contract_fields(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        required = {
            "messages",
            "structured_output_schema",
            "model_resolved_by_provider",
            "payload_data_class_by_provider",
            "provider_compliance_matrix_version",
            "context_snapshot_trace",
        }
        missing = sorted(required.difference(value))
        if missing:
            raise ValueError(f"request_template missing required keys: {missing}")

        trace = value.get("context_snapshot_trace")
        if not isinstance(trace, dict):
            raise ValueError("request_template.context_snapshot_trace must be an object")
        if trace.get("dataset_version_id") != DATASET_VERSION_ID:
            raise ValueError("context_snapshot_trace.dataset_version_id mismatch")
        return value

    @field_validator("expected_artifact_shape", "expected_redacted_summary_shape")
    @classmethod
    def _expected_shapes_must_be_json_schema(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        try:
            validator_for(value).check_schema(value)
        except SchemaError as exc:
            raise ValueError("expected shape must be a valid JSON Schema") from exc
        return value


def _artifact_shape(output_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        **output_schema,
    }


def _success_redacted_summary_shape(
    output_schema: dict[str, Any],
    required_keys: tuple[str, ...],
) -> dict[str, Any]:
    metadata_branch: dict[str, Any] = {
        "type": "object",
        "required": [
            "provider",
            "api_or_feature",
            "structured_output_schema_hash",
            "structured_output_sha256",
            "structured_output_top_level_keys",
        ],
        "properties": {
            "provider": {"type": "string", "minLength": 1},
            "api_or_feature": {"type": "string", "minLength": 1},
            "structured_output_schema_hash": {
                "type": "string",
                "pattern": "^[a-f0-9]{64}$",
            },
            "structured_output_sha256": {
                "type": "string",
                "pattern": "^[a-f0-9]{64}$",
            },
            "structured_output_top_level_keys": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "additionalProperties": True,
        "allOf": [
            {
                "properties": {
                    "structured_output_top_level_keys": {
                        "contains": {"const": key},
                    }
                }
            }
            for key in required_keys
        ],
    }
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "anyOf": [_artifact_shape(output_schema), metadata_branch],
    }


_SAFETY_REFUSAL_RESULT_SHAPE: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "anyOf": [
        {
            "type": "object",
            "required": ["mock_status"],
            "properties": {
                "mock_status": {"const": "safety_refusal"},
            },
            "additionalProperties": True,
        },
        {
            "type": "object",
            "required": ["provider", "api_or_feature", "structured_output_schema_hash"],
            "properties": {
                "provider": {"type": "string", "minLength": 1},
                "api_or_feature": {"type": "string", "minLength": 1},
                "structured_output_schema_hash": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$",
                },
                "finish_reason": {"type": "string"},
                "status": {"type": "string"},
            },
            "additionalProperties": True,
        },
    ],
}


def _base_template(
    *,
    case_id: str,
    messages: list[dict[str, Any]],
    structured_output_schema: dict[str, Any],
) -> dict[str, Any]:
    return {
        "messages": messages,
        "structured_output_schema": structured_output_schema,
        "tenant_id": 1,
        "model_resolved_by_provider": {
            "mock": "mock-model",
            "openai": "gpt-5.5",
            "anthropic": "claude-opus-4-7",
            "gemini": "gemini-2.5",
        },
        "payload_data_class_by_provider": {
            "mock": "internal",
            "openai": "internal",
            "anthropic": "internal",
            "gemini": "public",
        },
        "secret_capability_token_by_provider": {
            "openai": "cap-token-openai-gold-task",
            "anthropic": "cap-token-anthropic-gold-task",
            "gemini": "cap-token-gemini-gold-task",
        },
        "provider_compliance_matrix_version": "v2026.05.09-p0-skeleton",
        "max_tokens": 256,
        "temperature": 0,
        "safety_settings": {
            "mode": "gold_task_v0",
            "dataset_version_id": DATASET_VERSION_ID,
            "case_id": case_id,
        },
        "context_snapshot_trace": {
            "dataset_version_id": DATASET_VERSION_ID,
            "fixture_id": case_id,
            "snapshot_kind": "input",
        },
    }


def _simple_success_case(
    *,
    case_id: str,
    user_prompt: str,
    domain: str,
    payload_data_class: str = "internal",
    task_oracle_keywords: tuple[str, ...] = (),
) -> GoldTaskCase:
    """Factory: build a SUCCESS gold task using the simple answer schema.

    BL-0163 batch 5h expansion. The task expects strict JSON with a
    single ``answer`` field, exercising the basic provider contract
    (structured_output_schema_hash + Anti-Gaming determinism). Used
    across diverse domains to cover the Gold Task Seed v0 must_ship
    30-case minimum from SP-011 line 171.

    F-PR36-002 / F-PR36-003 (Codex R1 P2) adopt:
    * ``domain`` records stratified coverage axis.
    * ``payload_data_class`` follows the canonical Provider Compliance
      ordinal (defaults to ``"internal"`` to match the synthetic
      ``messages`` + ``payload_data_class_by_provider`` envelope).
    * ``task_oracle_keywords`` provides corpus metadata for SP-012
      real-provider runs to check ``answer`` contains at least one;
      P0 mock tests do not enforce this.
    """

    return GoldTaskCase(
        case_id=case_id,
        request_template=_base_template(
            case_id=case_id,
            messages=[
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": user_prompt},
            ],
            structured_output_schema=_SIMPLE_OUTPUT_SCHEMA,
        ),
        expected_status="success",
        expected_artifact_shape=_artifact_shape(_SIMPLE_OUTPUT_SCHEMA),
        expected_redacted_summary_shape=_success_redacted_summary_shape(
            _SIMPLE_OUTPUT_SCHEMA,
            ("answer",),
        ),
        task_metadata=GoldTaskMetadata(
            source="BL-0163 batch 5h synthetic",
            domain=domain,
            payload_data_class=payload_data_class,
            sanitization_status="synthetic",
        ),
        task_oracle_keywords=task_oracle_keywords,
    )


def _structured_success_case(
    *,
    case_id: str,
    user_prompt: str,
    domain: str,
    payload_data_class: str = "internal",
    task_oracle_keywords: tuple[str, ...] = (),
) -> GoldTaskCase:
    """Factory: build a SUCCESS gold task using the structured output
    schema (summary + risk_score + next_actions).

    BL-0163 batch 5h expansion. See ``_simple_success_case`` for the
    common ``domain`` / ``payload_data_class`` / ``task_oracle_keywords``
    metadata semantics (F-PR36-002 / F-PR36-003 adopt).
    """

    return GoldTaskCase(
        case_id=case_id,
        request_template=_base_template(
            case_id=case_id,
            messages=[
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": user_prompt},
            ],
            structured_output_schema=_STRUCTURED_OUTPUT_SCHEMA,
        ),
        expected_status="success",
        expected_artifact_shape=_artifact_shape(_STRUCTURED_OUTPUT_SCHEMA),
        expected_redacted_summary_shape=_success_redacted_summary_shape(
            _STRUCTURED_OUTPUT_SCHEMA,
            ("summary", "risk_score", "next_actions"),
        ),
        task_metadata=GoldTaskMetadata(
            source="BL-0163 batch 5h synthetic",
            domain=domain,
            payload_data_class=payload_data_class,
            sanitization_status="synthetic",
        ),
        task_oracle_keywords=task_oracle_keywords,
    )


GOLD_TASK_V0_CASES: tuple[GoldTaskCase, ...] = (
    # Sprint 5 era cases (3 original)
    GoldTaskCase(
        case_id="simple_request",
        request_template=_base_template(
            case_id="simple_request",
            messages=[
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": "Summarize the fixture task in one sentence."},
            ],
            structured_output_schema=_SIMPLE_OUTPUT_SCHEMA,
        ),
        expected_status="success",
        expected_artifact_shape=_artifact_shape(_SIMPLE_OUTPUT_SCHEMA),
        expected_redacted_summary_shape=_success_redacted_summary_shape(
            _SIMPLE_OUTPUT_SCHEMA,
            ("answer",),
        ),
    ),
    GoldTaskCase(
        case_id="structured_output",
        request_template=_base_template(
            case_id="structured_output",
            messages=[
                {"role": "system", "content": "Return strict JSON only."},
                {
                    "role": "user",
                    "content": "Return a risk summary and at least one next action.",
                },
            ],
            structured_output_schema=_STRUCTURED_OUTPUT_SCHEMA,
        ),
        expected_status="success",
        expected_artifact_shape=_artifact_shape(_STRUCTURED_OUTPUT_SCHEMA),
        expected_redacted_summary_shape=_success_redacted_summary_shape(
            _STRUCTURED_OUTPUT_SCHEMA,
            ("summary", "risk_score", "next_actions"),
        ),
    ),
    GoldTaskCase(
        case_id="safety_refusal",
        request_template=_base_template(
            case_id="safety_refusal",
            messages=[
                {"role": "system", "content": "Return strict JSON only."},
                {
                    "role": "user",
                    "content": (
                        "__mock_force_safety_refusal__ This case must exercise the "
                        "provider safety refusal mapping without exposing unsafe content."
                    ),
                },
            ],
            structured_output_schema=_SIMPLE_OUTPUT_SCHEMA,
        ),
        expected_status="safety_refusal",
        expected_artifact_shape=_artifact_shape(_SIMPLE_OUTPUT_SCHEMA),
        expected_redacted_summary_shape=_SAFETY_REFUSAL_RESULT_SHAPE,
    ),
    # BL-0163 batch 5h expansion: simple-schema diverse success cases (15)
    _simple_success_case(
        case_id="explain_dataclass_purpose",
        user_prompt="Explain in one sentence why we use Pydantic models for fixture validation.",
        domain="explain",
        task_oracle_keywords=("validate", "validation", "schema", "pydantic"),
    ),
    _simple_success_case(
        case_id="classify_log_severity",
        user_prompt="Classify the severity of this log line as info, warning, error, or critical.",
        domain="classify",
        task_oracle_keywords=("info", "warning", "error", "critical"),
    ),
    _simple_success_case(
        case_id="extract_function_name",
        user_prompt="Extract the function name from the python signature def evaluate_kpi(corpus):",
        domain="extract",
        task_oracle_keywords=("evaluate_kpi",),
    ),
    _simple_success_case(
        case_id="summarize_pull_request",
        user_prompt="Summarize the pull request changes in one sentence.",
        domain="summarize",
        task_oracle_keywords=("pull request", "change"),
    ),
    _simple_success_case(
        case_id="translate_error_message",
        user_prompt="Translate the Japanese error message into a one-sentence English summary.",
        domain="translate",
        task_oracle_keywords=("error", "message"),
    ),
    _simple_success_case(
        case_id="answer_yes_no_question",
        user_prompt="Answer yes or no: does PostgreSQL 16 support partial unique indexes?",
        domain="qa_yes_no",
        # F-PR36-R2-002 P2 (LOW) adopt: domain-anchored discriminative
        # keywords so the oracle is not satisfied by generic English
        # words containing "no" / "yes" as substrings.
        task_oracle_keywords=(
            "yes",
            "no",
            "partial unique",
            "partial index",
            "postgres",
        ),
    ),
    _simple_success_case(
        case_id="identify_test_failure_cause",
        user_prompt="Given a failing pytest output, identify the most likely root cause in one phrase.",
        domain="diagnose",
        task_oracle_keywords=("fail", "error", "assertion", "exception", "root"),
    ),
    _simple_success_case(
        case_id="paraphrase_commit_message",
        user_prompt="Paraphrase the commit message in one sentence preserving the semantic intent.",
        domain="paraphrase",
        task_oracle_keywords=("commit", "change"),
    ),
    _simple_success_case(
        case_id="suggest_variable_name",
        user_prompt="Suggest a descriptive variable name for the loop counter that iterates pull requests.",
        domain="naming",
        task_oracle_keywords=("pull_request", "pr_index", "pr_counter", "_counter", "_idx"),
    ),
    _simple_success_case(
        case_id="explain_sql_intent",
        user_prompt="Explain the intent of SELECT COUNT(*) FROM tickets WHERE status='open' in one sentence.",
        domain="explain_sql",
        task_oracle_keywords=("count", "ticket", "open"),
    ),
    _simple_success_case(
        case_id="describe_unit_test_assertion",
        user_prompt="Describe in one sentence what assert result.threshold_met is True verifies.",
        domain="explain_test",
        task_oracle_keywords=("threshold", "met", "kpi", "metric"),
    ),
    _simple_success_case(
        case_id="characterize_log_pattern",
        user_prompt="Characterize the log pattern Connection refused: localhost:5432 in one sentence.",
        domain="diagnose_network",
        task_oracle_keywords=("connection", "refused", "postgres", "database"),
    ),
    _simple_success_case(
        case_id="identify_design_principle",
        user_prompt="Identify the design principle behind separating spec_violation_reason from sut_failure_reason.",
        domain="design_principle",
        task_oracle_keywords=("separation", "concerns", "isolation", "spec", "sut"),
    ),
    _simple_success_case(
        case_id="recommend_logging_level",
        user_prompt="Recommend the appropriate logging level for a deferred ratio sanity warning.",
        domain="recommend_logging",
        task_oracle_keywords=("warning", "info", "log", "level"),
    ),
    _simple_success_case(
        case_id="describe_anti_gaming_invariant",
        user_prompt="Describe in one sentence why expected_aggregate must be used only as a drift oracle.",
        domain="explain_invariant",
        task_oracle_keywords=("drift", "oracle", "recompute", "anti-gaming", "anti_gaming"),
    ),
    # BL-0163 batch 5h expansion: structured-schema diverse success cases (12)
    _structured_success_case(
        case_id="risk_assessment_for_database_migration",
        user_prompt=(
            "Summarize the risks of a Postgres NOT NULL column addition "
            "with backfill and list at least one mitigation action."
        ),
        domain="risk_assessment_db",
        task_oracle_keywords=("backfill", "lock", "downtime", "migration"),
    ),
    _structured_success_case(
        case_id="incident_postmortem_outline",
        user_prompt="Summarize the incident root cause and list at least one follow-up action priority.",
        domain="postmortem",
        task_oracle_keywords=("incident", "root cause", "follow-up"),
    ),
    _structured_success_case(
        case_id="api_contract_change_review",
        user_prompt="Summarize the breaking change in the API contract and list at least one client-side update task.",
        domain="api_contract",
        task_oracle_keywords=("api", "breaking", "client", "contract"),
    ),
    _structured_success_case(
        case_id="dependency_upgrade_evaluation",
        user_prompt=(
            "Summarize the impact of upgrading the SQLAlchemy major version "
            "and list at least one regression test action."
        ),
        domain="dependency_upgrade",
        task_oracle_keywords=("sqlalchemy", "upgrade", "regression", "test"),
    ),
    _structured_success_case(
        case_id="performance_regression_triage",
        user_prompt="Summarize the performance regression hypothesis and list at least one profiling action.",
        domain="performance",
        task_oracle_keywords=("performance", "regression", "profile", "latency"),
    ),
    _structured_success_case(
        case_id="security_advisory_response",
        user_prompt="Summarize the security advisory impact and list at least one patch deployment action.",
        domain="security",
        task_oracle_keywords=("security", "advisory", "patch", "deploy"),
    ),
    _structured_success_case(
        case_id="provider_outage_handling_plan",
        user_prompt="Summarize the provider outage handling approach and list at least one fallback action.",
        domain="incident_response",
        task_oracle_keywords=("provider", "outage", "fallback", "retry"),
    ),
    _structured_success_case(
        case_id="rate_limit_handling_strategy",
        user_prompt="Summarize the rate limit handling strategy and list at least one queue management action.",
        domain="rate_limit",
        task_oracle_keywords=("rate limit", "queue", "backoff", "retry"),
    ),
    _structured_success_case(
        case_id="data_migration_rollback_plan",
        user_prompt="Summarize the data migration rollback plan and list at least one verification action.",
        domain="rollback",
        task_oracle_keywords=("rollback", "verify", "backup", "restore"),
    ),
    _structured_success_case(
        case_id="feature_flag_rollout_plan",
        user_prompt="Summarize the feature flag rollout plan and list at least one canary verification action.",
        domain="feature_flag",
        task_oracle_keywords=("feature", "flag", "canary", "rollout"),
    ),
    _structured_success_case(
        case_id="approval_workflow_redesign",
        user_prompt=(
            "Summarize the approval workflow redesign impact "
            "and list at least one stakeholder communication action."
        ),
        domain="workflow_redesign",
        task_oracle_keywords=("approval", "workflow", "stakeholder", "communication"),
    ),
    _structured_success_case(
        case_id="audit_log_retention_policy",
        user_prompt=(
            "Summarize the audit log retention policy change "
            "and list at least one compliance verification action."
        ),
        domain="compliance",
        task_oracle_keywords=("audit", "log", "retention", "compliance"),
    ),
)

__all__ = [
    "DATASET_VERSION_ID",
    "GOLD_TASK_V0_CASES",
    "GoldTaskCase",
    "GoldTaskMetadata",
]

