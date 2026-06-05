"""ADR-00050 (SP-028) webhook event parser の no-DB unit test。

DB を要しない pure logic (allowlist 抽出 / 値レベル redaction / shape validation / enum 整合) を host で
固定する。persist / dedup / read scope の DB-backed 挙動は test_webhook_event_parser_db.py で固定。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.db.models.github_webhook_event import (
    ACTION_MAX_LENGTH,
    EXTERNAL_REF_MAX_LENGTH,
    STATE_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    WEBHOOK_EVENT_KINDS,
    WEBHOOK_EVENT_STATUSES,
    WEBHOOK_QUARANTINE_REASONS,
)
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.services.repoproxy.webhook_event_parser import (
    _clean,
    _extract_fields,
    _parse_body,
    _repo_external_id,
    _sender_login,
)

EXPECTED_EVENT_KINDS = {
    "pull_request",
    "check_run",
    "check_suite",
    "status",
    "push",
}
EXPECTED_STATUSES = {"accepted", "quarantined"}
EXPECTED_QUARANTINE_REASONS = {
    "unregistered_repo",
    "repo_lookup_ambiguous",
    "payload_shape_mismatch",
    "header_event_mismatch",
    "parse_validation_failed",
}

_GITHUB_SECRET_SHAPED = "ghp_" + "A" * 36  # github_personal_token pattern (drop 対象)


# --- enum 整合 (5+ source: Python Literal tuple + pytest EXPECTED + DB CHECK migration string) ---


def test_event_kind_enum_exact_set() -> None:
    assert set(WEBHOOK_EVENT_KINDS) == EXPECTED_EVENT_KINDS


def test_status_enum_exact_set() -> None:
    assert set(WEBHOOK_EVENT_STATUSES) == EXPECTED_STATUSES


def test_quarantine_reason_enum_exact_set() -> None:
    assert set(WEBHOOK_QUARANTINE_REASONS) == EXPECTED_QUARANTINE_REASONS


def test_migration_check_strings_match_enums() -> None:
    """migration の DB CHECK 文字列が Python enum と drift していないことを固定 (5+ source 整合)。"""
    migration = (
        Path(__file__).resolve().parents[1]
        / ".."
        / "migrations"
        / "versions"
        / "0044_sp028_webhook_events.py"
    ).resolve()
    text = migration.read_text(encoding="utf-8")
    for kind in EXPECTED_EVENT_KINDS:
        assert f"'{kind}'" in text, f"event_kind {kind} missing from migration CHECK"
    for status_value in EXPECTED_STATUSES:
        assert f"'{status_value}'" in text
    for reason in EXPECTED_QUARANTINE_REASONS:
        assert f"'{reason}'" in text


# --- 値レベル redaction (R1 F-Q3 / F-007) ---


def test_clean_drops_secret_shaped_value() -> None:
    assert _clean(_GITHUB_SECRET_SHAPED, TITLE_MAX_LENGTH) is None


def test_clean_drops_age_key() -> None:
    assert _clean("AGE-SECRET-KEY-1" + "A" * 55, TITLE_MAX_LENGTH) is None


def test_clean_strips_control_chars_and_normalizes() -> None:
    assert _clean("  hel\x00lo\tworld\n  ", TITLE_MAX_LENGTH) == "helloworld"


def test_clean_truncates_to_max_length() -> None:
    cleaned = _clean("x" * 600, STATE_MAX_LENGTH)
    assert cleaned is not None
    assert len(cleaned) == STATE_MAX_LENGTH


def test_clean_empty_becomes_none() -> None:
    assert _clean("   ", ACTION_MAX_LENGTH) is None
    assert _clean(None, ACTION_MAX_LENGTH) is None


# --- allowlist 抽出 (event_kind 別) ---


def test_extract_pull_request() -> None:
    body = {
        "action": "opened",
        "pull_request": {"number": 42, "state": "open", "title": "Fix bug", "merged": False},
        "sender": {"login": "octocat"},
        "repository": {"id": 123},
    }
    fields = _extract_fields("pull_request", body)
    assert fields is not None
    assert fields.action == "opened"
    assert fields.external_ref == "42"
    assert fields.state == "open"
    assert fields.title == "Fix bug"
    assert fields.sender_login == "octocat"
    assert fields.repo_external_id == "123"


def test_extract_pull_request_merged_state() -> None:
    body = {
        "action": "closed",
        "pull_request": {"number": 7, "state": "closed", "merged": True, "title": "t"},
        "repository": {"id": 1},
    }
    fields = _extract_fields("pull_request", body)
    assert fields is not None
    assert fields.state == "merged"


def test_extract_check_run_uses_conclusion_and_head_sha() -> None:
    body = {
        "action": "completed",
        "check_run": {"id": 9, "status": "completed", "conclusion": "failure", "head_sha": "abc"},
        "repository": {"id": 1},
    }
    fields = _extract_fields("check_run", body)
    assert fields is not None
    assert fields.state == "failure"
    assert fields.external_ref == "abc"


def test_extract_status_requires_state_and_sha() -> None:
    ok = _extract_fields(
        "status",
        {"state": "success", "sha": "deadbeef", "context": "ci/build", "repository": {"id": 1}},
    )
    assert ok is not None
    assert ok.state == "success"
    assert ok.external_ref == "deadbeef"
    assert ok.title == "ci/build"
    # state / sha 欠落 → shape mismatch
    assert _extract_fields("status", {"state": "success", "repository": {"id": 1}}) is None


def test_extract_push_uses_after_and_ref() -> None:
    fields = _extract_fields(
        "push",
        {"ref": "refs/heads/main", "after": "sha1", "repository": {"id": 1}, "sender": {"login": "o"}},
    )
    assert fields is not None
    assert fields.external_ref == "sha1"
    assert fields.title == "refs/heads/main"


def test_extract_shape_mismatch_returns_none() -> None:
    # pull_request header だが pull_request key 欠落
    assert _extract_fields("pull_request", {"repository": {"id": 1}}) is None
    # push header だが ref 欠落
    assert _extract_fields("push", {"after": "x", "repository": {"id": 1}}) is None


def test_extract_drops_secret_in_title() -> None:
    body = {
        "action": "opened",
        "pull_request": {"number": 1, "state": "open", "title": _GITHUB_SECRET_SHAPED},
        "repository": {"id": 1},
    }
    fields = _extract_fields("pull_request", body)
    assert fields is not None
    assert fields.title is None  # secret-shaped title は drop


def test_extracted_fields_contain_no_raw_secret() -> None:
    """抽出 DTO の全 field に secret-shaped 値を注入 → 保存される値に raw secret が残らない。"""
    body = {
        "action": _GITHUB_SECRET_SHAPED,
        "pull_request": {
            "number": 1,
            "state": _GITHUB_SECRET_SHAPED,
            "title": _GITHUB_SECRET_SHAPED,
        },
        "sender": {"login": _GITHUB_SECRET_SHAPED},
        "repository": {"id": 1},
    }
    fields = _extract_fields("pull_request", body)
    assert fields is not None
    assert_no_raw_secret(
        {
            "action": fields.action,
            "external_ref": fields.external_ref,
            "state": fields.state,
            "title": fields.title,
            "sender_login": fields.sender_login,
        }
    )


# --- body parse / helper ---


def test_parse_body_rejects_invalid_json() -> None:
    assert _parse_body(b"{not json") is None
    assert _parse_body(b"\xff\xfe") is None
    assert _parse_body(b'"a string"') is None  # not a dict


def test_repo_external_id_int_only() -> None:
    assert _repo_external_id({"repository": {"id": 55}}) == "55"
    assert _repo_external_id({"repository": {"id": True}}) is None  # bool は除外
    assert _repo_external_id({"repository": {}}) is None
    assert _repo_external_id({}) is None


def test_sender_login_missing() -> None:
    assert _sender_login({"sender": {"login": "x"}}) == "x"
    assert _sender_login({}) is None


def test_max_length_constants_are_consistent() -> None:
    # EXTERNAL_REF は最長 (sha / number)、bound が parser / DB CHECK で同値であること。
    assert EXTERNAL_REF_MAX_LENGTH == 255
    assert STATE_MAX_LENGTH == 32
    assert TITLE_MAX_LENGTH == 512


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
