"""Sprint 6 Batch 3: CLI decision record / payload 境界の契約テスト。"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

import pytest

from backend.app.services.cli_artifact.decision import (
    CliDecisionActorType,
    CliDecisionRecord,
    CliDecisionVerdict,
    build_cli_decision_audit_payload,
    build_cli_decision_event_payload,
    record_decision,
)

TENANT_ID = "tenant_1"
RUN_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ACTOR_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
ARTIFACT_CONTENT = b"cli result summary bytes"
ARTIFACT_HASH = hashlib.sha256(ARTIFACT_CONTENT).hexdigest()
POLICY_VERSION = "sp6.batch3"
REASON = "human reviewed the CLI result summary"


class _UnknownVerdict(StrEnum):
    UNKNOWN = "unknown"


def _record(
    *,
    tenant_id: str = TENANT_ID,
    run_id: str = RUN_ID,
    actor_id: str = ACTOR_ID,
    actor_type: CliDecisionActorType | str = CliDecisionActorType.HUMAN,
    verdict: CliDecisionVerdict | str = CliDecisionVerdict.ADOPT,
    artifact_content: bytes = ARTIFACT_CONTENT,
    policy_version: str = POLICY_VERSION,
    reason: str = REASON,
    now: datetime | None = None,
) -> CliDecisionRecord:
    return record_decision(
        tenant_id=tenant_id,
        run_id=run_id,
        actor_id=actor_id,
        actor_type=actor_type,
        verdict=verdict,
        artifact_content=artifact_content,
        policy_version=policy_version,
        reason=reason,
        now=now,
    )


def _assert_value_error(match: str) -> pytest.ExceptionInfo[ValueError]:
    return pytest.raises(ValueError, match=match)


def test_record_decision_returns_frozen_record() -> None:
    """record_decision は frozen dataclass record を返す。"""

    record = _record()

    assert isinstance(record, CliDecisionRecord)
    assert dataclasses.is_dataclass(record) is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.reason = "mutated"


def test_record_decision_generates_uuid_decision_id() -> None:
    """decision_id は caller 入力ではなく uuid4 hex として生成される。"""

    record = _record()
    parsed = uuid.UUID(hex=record.decision_id)

    assert parsed.hex == record.decision_id
    assert parsed.version == 4


def test_record_decision_default_decided_at_is_utc_now() -> None:
    """now 未指定時の decided_at は aware UTC の現在時刻になる。"""

    before = datetime.now(tz=UTC)
    record = _record()
    after = datetime.now(tz=UTC)

    assert record.decided_at.tzinfo is UTC
    assert before <= record.decided_at <= after


def test_record_decision_accepts_explicit_now() -> None:
    """test 用の明示 now はそのまま decided_at に反映される。"""

    explicit_now = datetime(2026, 5, 13, 12, 34, 56, tzinfo=UTC)

    record = _record(now=explicit_now)

    assert record.decided_at == explicit_now
    assert record.decided_at.tzinfo is UTC


def test_record_decision_accepts_human_actor_type_string() -> None:
    """actor_type は human 文字列だけを採否判定 actor として許可する。"""

    record = _record(actor_type="human")

    assert record.actor_id == ACTOR_ID
    assert record.verdict is CliDecisionVerdict.ADOPT


def test_record_decision_accepts_human_actor_type_enum() -> None:
    """actor_type は CliDecisionActorType.HUMAN enum でも指定できる。"""

    record = _record(actor_type=CliDecisionActorType.HUMAN)

    assert record.actor_id == ACTOR_ID
    assert record.reason == REASON


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        ("adopt", CliDecisionVerdict.ADOPT),
        ("reject", CliDecisionVerdict.REJECT),
        ("defer", CliDecisionVerdict.DEFER),
    ],
)
def test_record_decision_accepts_str_verdict(
    verdict: str,
    expected: CliDecisionVerdict,
) -> None:
    """文字列 verdict は固定 3 値だけ enum に coerce される。"""

    record = _record(verdict=verdict)

    assert record.verdict is expected
    assert record.verdict.value == verdict


def test_record_decision_rejects_unknown_verdict_string() -> None:
    """未知の文字列 verdict は fail-closed で拒否される。"""

    with _assert_value_error("verdict"):
        _record(verdict="approve")


def test_record_decision_rejects_unknown_verdict_enum_value() -> None:
    """別 enum による未知 verdict 値も CliDecisionVerdict として扱わない。"""

    unknown = cast(CliDecisionVerdict, _UnknownVerdict.UNKNOWN)

    with _assert_value_error("verdict"):
        _record(verdict=unknown)


@pytest.mark.parametrize("actor_type", ["agent", "service", "system"])
def test_record_decision_rejects_non_human_actor_type(actor_type: str) -> None:
    """agent / service / system actor による自己承認経路は拒否する。"""

    with _assert_value_error("actor_type"):
        _record(actor_type=actor_type)


def test_record_decision_rejects_invalid_actor_type_string() -> None:
    """human 以外の actor_type 文字列は allowlist 外として拒否する。"""

    with _assert_value_error("actor_type"):
        _record(actor_type="Human")


@pytest.mark.parametrize("tenant_id", ["", "..", ";rm"])
def test_record_decision_rejects_invalid_tenant_id(tenant_id: str) -> None:
    """tenant_id は allowlist 形式以外を拒否する。"""

    with _assert_value_error("tenant_id"):
        _record(tenant_id=tenant_id)


@pytest.mark.parametrize("run_id", ["1234567", "zzzzzzzz"])
def test_record_decision_rejects_invalid_run_id(run_id: str) -> None:
    """run_id は 8-64 文字の hex / uuid 形式だけを受け付ける。"""

    with _assert_value_error("run_id"):
        _record(run_id=run_id)


@pytest.mark.parametrize("actor_id", ["", "actor;rm", "zzzzzzzz"])
def test_record_decision_rejects_invalid_actor_id(actor_id: str) -> None:
    """actor_id は server-owned id 形式以外を拒否する。"""

    with _assert_value_error("actor_id"):
        _record(actor_id=actor_id)


def test_record_decision_rejects_empty_artifact_content() -> None:
    """artifact_content は空 bytes を artifact として受け付けない。"""

    with _assert_value_error("artifact_content"):
        _record(artifact_content=b"")


def test_record_decision_rejects_non_bytes_artifact_content() -> None:
    """artifact_content は bytes 以外の caller 入力を拒否する。"""

    with _assert_value_error("artifact_content"):
        _record(artifact_content=cast(bytes, "not bytes"))


def test_record_decision_artifact_hash_is_server_computed() -> None:
    """artifact_hash は caller 供給値ではなく artifact_content から内部計算する。"""

    content = b"server-side hash source content"
    caller_supplied_hash = "b" * 64

    record = _record(artifact_content=content)

    assert record.artifact_hash == hashlib.sha256(content).hexdigest()
    assert record.artifact_hash != caller_supplied_hash

    legacy_record_decision = cast(Any, record_decision)
    with pytest.raises(TypeError, match="artifact_hash"):
        legacy_record_decision(
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            actor_id=ACTOR_ID,
            actor_type="human",
            verdict=CliDecisionVerdict.ADOPT,
            artifact_content=content,
            artifact_hash=caller_supplied_hash,
            policy_version=POLICY_VERSION,
            reason=REASON,
        )


@pytest.mark.parametrize("policy_version", ["", "sp6 batch3", "v" * 65])
def test_record_decision_rejects_invalid_policy_version(
    policy_version: str,
) -> None:
    """policy_version は空、空白入り、64 文字超を拒否する。"""

    with _assert_value_error("policy_version"):
        _record(policy_version=policy_version)


def test_record_decision_rejects_too_long_reason() -> None:
    """reason は 4096 文字を超えたら拒否される。"""

    with _assert_value_error("reason"):
        _record(reason="x" * 4097)


def test_record_decision_rejects_non_str_reason() -> None:
    """reason は str のみ許可し、非 JSON 型の混入を早期拒否する。"""

    with _assert_value_error("reason"):
        record_decision(
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            actor_id=ACTOR_ID,
            actor_type="human",
            verdict=CliDecisionVerdict.ADOPT,
            artifact_content=ARTIFACT_CONTENT,
            policy_version=POLICY_VERSION,
            reason=cast(str, 123),
        )


def test_record_decision_rejects_naive_datetime_now() -> None:
    """now は tzinfo を持つ aware datetime だけを許可する。"""

    naive_now = datetime(2026, 5, 13, 12, 34, 56)

    with _assert_value_error("timezone-aware"):
        _record(now=naive_now)


def test_record_decision_rejects_reason_with_openai_token() -> None:
    """reason 内の OpenAI 形式 canary は raw secret として拒否する。"""

    raw_token = "sk-" + ("A" * 40)

    with _assert_value_error("openai_api_key"):
        _record(reason="leaked token: " + raw_token)


def test_record_decision_rejects_reason_with_anthropic_token() -> None:
    """reason 内の Anthropic 形式 canary は raw secret として拒否する。"""

    raw_token = "sk-ant-" + ("B" * 40)

    with _assert_value_error("anthropic_api_key"):
        _record(reason="leaked token: " + raw_token)


def test_record_decision_rejects_reason_with_github_token() -> None:
    """reason 内の GitHub installation token 形式 canary は拒否する。"""

    raw_token = "ghs_" + ("C" * 40)

    with _assert_value_error("github_installation_token"):
        _record(reason="leaked token: " + raw_token)


def test_record_decision_rejects_reason_with_prohibited_key_value() -> None:
    """reason 内の prohibited key=value 形式は短い値でも拒否する。"""

    with _assert_value_error("prohibited key 'api_key'"):
        _record(reason="api_key=foo")


def test_record_decision_redaction_pipeline_blocks_ansi_smuggled_secret() -> None:
    """ANSI 混入で api_key を分断した reason も redaction pipeline で拒否する。"""

    with _assert_value_error("redaction pipeline"):
        _record(reason="api\x1b[0m_key=secret")


def test_record_decision_accepts_redacted_reason_marker() -> None:
    """redaction 済み marker は raw secret ではないため保存できる。"""

    record = _record(reason="[REDACTED:api_key]")

    assert record.reason == "[REDACTED:api_key]"


def test_record_decision_record_decision_id_is_uuid_hex_32_chars() -> None:
    """record の decision_id は 32 文字 lowercase hex として保持される。"""

    record = _record()

    assert len(record.decision_id) == 32
    assert set(record.decision_id) <= set("0123456789abcdef")
    assert uuid.UUID(hex=record.decision_id).hex == record.decision_id


def test_record_decision_record_decided_at_is_aware_utc() -> None:
    """record の decided_at は naive datetime ではなく aware UTC になる。"""

    record = _record()

    assert record.decided_at.tzinfo is UTC
    assert record.decided_at.utcoffset().total_seconds() == 0


def test_build_event_payload_excludes_raw_reason() -> None:
    """AgentRunEvent payload は raw reason を含めず hash のみ持つ。"""

    reason = "this raw reason must stay out of the event payload"
    record = _record(reason=reason)

    payload = build_cli_decision_event_payload(record)

    assert "reason" not in payload
    assert reason not in repr(payload)
    assert reason not in payload.values()


def test_build_event_payload_includes_reason_hash() -> None:
    """AgentRunEvent payload は reason_hash を含む。"""

    record = _record(reason="adopt after manual review")

    payload = build_cli_decision_event_payload(record)

    assert payload["reason_hash"] == hashlib.sha256(
        b"adopt after manual review"
    ).hexdigest()


def test_build_event_payload_reason_hash_is_sha256_hex() -> None:
    """reason_hash は SHA-256 lowercase hex の 64 文字になる。"""

    record = _record(reason="hash me")

    reason_hash = build_cli_decision_event_payload(record)["reason_hash"]

    assert len(reason_hash) == 64
    assert set(reason_hash) <= set("0123456789abcdef")


def test_build_event_payload_includes_required_keys() -> None:
    """event payload は外部公開してよい最小キーだけを含む。"""

    record = _record()

    payload = build_cli_decision_event_payload(record)

    assert set(payload) == {
        "decision_id",
        "actor_id",
        "verdict",
        "artifact_hash",
        "policy_version",
        "decided_at",
        "reason_hash",
    }
    assert payload["decision_id"] == record.decision_id
    assert payload["actor_id"] == ACTOR_ID
    assert payload["verdict"] == "adopt"
    assert payload["artifact_hash"] == ARTIFACT_HASH
    assert payload["policy_version"] == POLICY_VERSION
    assert payload["decided_at"] == record.decided_at.isoformat()


def test_build_audit_payload_includes_raw_reason() -> None:
    """audit payload は内部監査用に raw reason を保持する。"""

    record = _record(reason="audit-only rationale")

    payload = build_cli_decision_audit_payload(record)

    assert payload["reason"] == "audit-only rationale"


def test_build_audit_payload_includes_tenant_id_and_run_id() -> None:
    """audit payload は tenant / run 境界を追跡できる。"""

    record = _record()

    payload = build_cli_decision_audit_payload(record)

    assert payload["tenant_id"] == TENANT_ID
    assert payload["run_id"] == RUN_ID
    assert payload["decision_id"] == record.decision_id


def test_cli_decision_verdict_enum_3_values() -> None:
    """CliDecisionVerdict は adopt / reject / defer の 3 値固定とする。"""

    assert tuple(verdict.value for verdict in CliDecisionVerdict) == (
        "adopt",
        "reject",
        "defer",
    )


def test_cli_decision_actor_type_enum_human_only() -> None:
    """CliDecisionActorType は self-approval 防止のため human だけに固定する。"""

    assert tuple(actor_type.value for actor_type in CliDecisionActorType) == (
        "human",
    )


def test_decision_record_dataclass_is_frozen() -> None:
    """CliDecisionRecord は append-only 前提の immutable record とする。"""

    record = _record()

    assert dataclasses.is_dataclass(CliDecisionRecord) is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.verdict = CliDecisionVerdict.REJECT


def test_decision_record_dataclass_has_slots() -> None:
    """CliDecisionRecord は __dict__ を持たない slots dataclass とする。"""

    record = _record()

    assert CliDecisionRecord.__slots__ == (
        "decision_id",
        "tenant_id",
        "run_id",
        "actor_id",
        "verdict",
        "artifact_hash",
        "policy_version",
        "reason",
        "decided_at",
    )
    assert hasattr(record, "__dict__") is False


def test_decision_id_is_uniq_per_call() -> None:
    """decision_id は 100 回連続生成しても重複しない。"""

    decision_ids = {_record().decision_id for _ in range(100)}

    assert len(decision_ids) == 100
    assert all(len(decision_id) == 32 for decision_id in decision_ids)
