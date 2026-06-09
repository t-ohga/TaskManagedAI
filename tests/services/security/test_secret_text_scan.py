from __future__ import annotations

import pytest

from backend.app.services.security.secret_text_scan import (
    _SECRET_TEXT_PATTERNS,
    REDACTED_PLACEHOLDER,
    assert_no_secret_in_text,
    redact_if_secret,
)


@pytest.mark.parametrize(
    "text",
    [
        "sk-proj-abcdefghijklmnopqrstuvwxyz012345",  # modern OpenAI project key
        "sk-aaaaaaaaaaaaaaaaaaaa",  # legacy OpenAI key
        "ghp_aaaaaaaaaaaaaaaaaaaa",  # GitHub PAT
        "ghu_bbbbbbbbbbbbbbbbbbbb",  # GitHub user-to-server token
        "ghr_cccccccccccccccccccc",  # GitHub refresh token
        "github_pat_11ABCDEFGHIJKLMNOPQRST",  # GitHub fine-grained PAT
        "AKIAIOSFODNN7EXAMPLE",  # AWS access key
        "CANARY-FIXTURE-ABCDEFGH01234567",  # secret canary marker
        "値に sk-proj-abcdefghijklmnopqrstuvwxyz012345 が混入",  # embedded
    ],
)
def test_assert_rejects_modern_secrets(text: str) -> None:
    with pytest.raises(ValueError, match="forbidden secret pattern|prohibited|secret pattern"):
        assert_no_secret_in_text(text, field="domain")


@pytest.mark.parametrize(
    "text",
    ["example.com", "政府機関の一次情報源", "arxiv.org の論文", "ordinary rationale text", ""],
)
def test_assert_allows_clean_text(text: str) -> None:
    assert_no_secret_in_text(text, field="rationale")  # does not raise


def test_redact_if_secret() -> None:
    assert redact_if_secret(None) is None
    assert redact_if_secret("clean text") == "clean text"
    assert redact_if_secret("sk-proj-abcdefghijklmnopqrstuvwxyz012345") == REDACTED_PLACEHOLDER


def test_drift_guard_matches_comment_scanner() -> None:
    """ticket comment scanner と同一 broad pattern 集合 (drift 防止、N-1 convention 準拠)。"""
    from backend.app.services.notifications.ticket_comment import _COMMENT_SECRET_PATTERNS

    ours = {regex.pattern for _name, regex in _SECRET_TEXT_PATTERNS}
    comment = {regex.pattern for _name, regex in _COMMENT_SECRET_PATTERNS}
    assert ours == comment


def test_drift_guard_covers_eval_scanner() -> None:
    """eval scanner (anti_gaming の _RAW_SECRET_VALUE_PATTERNS) を broad pattern が covers する。"""
    from backend.app.services.eval.anti_gaming import _RAW_SECRET_VALUE_PATTERNS

    ours = {regex.pattern for _name, regex in _SECRET_TEXT_PATTERNS}
    eval_patterns = {regex.pattern for _name, regex in _RAW_SECRET_VALUE_PATTERNS}
    assert eval_patterns <= ours
