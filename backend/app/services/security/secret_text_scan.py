"""user 自由入力テキストの broad secret / canary scanner (共有)。

project 共通の ``assert_no_raw_secret`` は legacy ``sk-[A-Za-z0-9]{20,}`` / ``ghp_`` / ``gho_`` /
``ghs_`` 中心で、modern OpenAI project key (``sk-proj-...`` 等 hyphen/underscore 含む) / GitHub
fine-grained PAT / ``ghu_`` / ``ghr_`` / AWS access key / secret canary を見逃す。

user 自由入力 (ticket comment / conflict group title / domain trust rationale / domain など) は
leak risk が高いため、本 module は eval scanner (`services/eval/anti_gaming.py` /
`loader.py` の ``_RAW_SECRET_VALUE_PATTERNS``) + ticket comment scanner
(`services/notifications/ticket_comment.py` の ``_COMMENT_SECRET_PATTERNS``) と **同一の** broad
provider-token + canary 集合を適用する。drift は
``tests/services/security/test_secret_text_scan_drift.py`` が検出する。

SP-032 (ADR-00052) Codex adversarial R2 F-HIGH で導入。
"""

from __future__ import annotations

import re

from backend.app.repositories._payload_secret_scan import assert_no_raw_secret

# broad provider-token + canary patterns (comment / eval scanner と同一集合、drift guard で同期)。
_SECRET_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("github_pat", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{16,}\b")),
    ("github_fine_grained_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("secret_canary", re.compile(r"CANARY-FIXTURE-[A-Z0-9]{16,}")),
)

REDACTED_PLACEHOLDER = "[redacted: 機密情報が検出されたため非表示]"


def assert_no_secret_in_text(text: str, *, field: str = "text") -> None:
    """user 自由入力に raw secret / modern provider token / canary が無いか検証する。

    project 共通の ``assert_no_raw_secret`` (prohibited key + legacy pattern) に加え、broad
    provider-token + canary 集合を適用する。いずれか hit で ``ValueError`` を raise。

    Raises:
        ValueError: raw secret / provider token / canary / prohibited key を検出した場合。
    """
    assert_no_raw_secret({field: text})
    for hit_kind, regex in _SECRET_TEXT_PATTERNS:
        if regex.search(text) is not None:
            raise ValueError(f"{field} contains a forbidden secret pattern ({hit_kind})")


def redact_if_secret(text: str | None) -> str | None:
    """read 経路の defense-in-depth: secret/canary を含むテキストは raw 表示しない。

    write 経路は ``assert_no_secret_in_text`` で reject 済だが、将来 scanner が拡張された場合や
    別経路で保存された値に備え、read でも同一判定で raw 表示を止める (ticket comment の
    ``redact_comment_message`` と同方針)。None は None のまま返す。
    """
    if text is None:
        return None
    try:
        assert_no_secret_in_text(text)
    except ValueError:
        return REDACTED_PLACEHOLDER
    return text


__all__ = [
    "REDACTED_PLACEHOLDER",
    "_SECRET_TEXT_PATTERNS",
    "assert_no_secret_in_text",
    "redact_if_secret",
]
