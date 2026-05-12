"""Sprint 6 Batch 2: stdout/stderr redaction pipeline の秘匿テスト。"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import pytest

from backend.app.services.cli_artifact.redaction import (
    RedactionResult,
    redact_stream,
    summary_payload,
)


def _repeat(prefix: str, char: str, count: int) -> str:
    return prefix + (char * count)


def _openai_api_key() -> str:
    return _repeat("sk-", "A", 40)


def _anthropic_api_key() -> str:
    return _repeat("sk-ant-", "B", 40)


def _github_installation_token() -> str:
    return _repeat("ghs_", "C", 40)


def _github_oauth_token() -> str:
    return _repeat("gho_", "D", 40)


def _github_personal_token() -> str:
    return _repeat("ghp_", "E", 40)


def _tailscale_auth_key() -> str:
    return "tskey-" + ("a" * 20) + "-" + ("b" * 20)


def _age_private_key() -> str:
    return "AGE-SECRET-KEY-1" + ("F" * 60)


def _pem_private_key() -> str:
    return "-----BEGIN " + "PRIVATE KEY-----"


SECRET_CASES: tuple[tuple[str, Callable[[], str]], ...] = (
    ("openai_api_key", _openai_api_key),
    ("anthropic_api_key", _anthropic_api_key),
    ("github_installation_token", _github_installation_token),
    ("github_oauth_token", _github_oauth_token),
    ("github_personal_token", _github_personal_token),
    ("tailscale_auth_key", _tailscale_auth_key),
    ("age_private_key", _age_private_key),
    ("pem_private_key", _pem_private_key),
)


def _hit_map(result: RedactionResult) -> dict[str, int]:
    return {hit.pattern_kind: hit.match_count for hit in result.hits}


def _redact_text(text: str, *, max_bytes: int = 4096) -> RedactionResult:
    return redact_stream(text.encode("utf-8"), max_bytes=max_bytes)


@pytest.mark.parametrize(("kind", "factory"), SECRET_CASES, ids=[c[0] for c in SECRET_CASES])
def test_redact_secret_replaces_secret_with_marker(
    kind: str, factory: Callable[[], str]
) -> None:
    result = _redact_text("prefix " + factory() + " suffix")

    assert result.redacted_text == f"prefix [REDACTED:{kind}] suffix"


@pytest.mark.parametrize(("kind", "factory"), SECRET_CASES, ids=[c[0] for c in SECRET_CASES])
def test_redact_secret_records_match_count(
    kind: str, factory: Callable[[], str]
) -> None:
    result = _redact_text("prefix " + factory() + " suffix")

    assert _hit_map(result) == {kind: 1}


@pytest.mark.parametrize(("kind", "factory"), SECRET_CASES, ids=[c[0] for c in SECRET_CASES])
def test_redact_secret_does_not_leak_raw_value_in_redacted_text(
    kind: str, factory: Callable[[], str]
) -> None:
    result = _redact_text("prefix " + factory() + " suffix")

    leaked = factory() in result.redacted_text
    assert leaked is False
    assert result.redacted_text == f"prefix [REDACTED:{kind}] suffix"


def test_redact_multiple_same_pattern_increments_count() -> None:
    token = _github_oauth_token()
    result = _redact_text(token + "\n" + token)

    assert _hit_map(result) == {"github_oauth_token": 2}
    assert result.redacted_text.count("[REDACTED:github_oauth_token]") == 2


def test_redact_combines_multiple_pattern_kinds() -> None:
    result = _redact_text(_openai_api_key() + "\n" + _github_personal_token())

    assert _hit_map(result) == {
        "github_personal_token": 1,
        "openai_api_key": 1,
    }


def test_redact_truncates_at_max_bytes() -> None:
    result = redact_stream(b"abcdefghij", max_bytes=5)

    assert result.redacted_text == "abcde"
    assert result.raw_bytes_length == 10
    assert result.truncated is True


def test_redact_truncated_flag_is_false_for_short_input() -> None:
    result = redact_stream(b"short", max_bytes=5)

    assert result.redacted_text == "short"
    assert result.truncated is False


def test_redact_max_bytes_zero_returns_empty() -> None:
    result = redact_stream(b"abc", max_bytes=0)

    assert result.redacted_text == ""
    assert result.raw_bytes_length == 3
    assert result.truncated is True
    assert result.redacted_content_hash == hashlib.sha256(b"").hexdigest()


def test_redact_rejects_negative_max_bytes() -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        redact_stream(b"abc", max_bytes=-1)


def test_redact_invalid_utf8_replaced_with_marker() -> None:
    result = redact_stream(b"ok\xffbad", max_bytes=32)

    assert result.redacted_text == "ok[REDACTED:non-utf8]bad"
    assert "�" not in result.redacted_text


def test_redact_empty_bytes_returns_empty_result() -> None:
    result = redact_stream(b"", max_bytes=1024)

    assert result.redacted_text == ""
    assert result.raw_bytes_length == 0
    assert result.truncated is False
    assert result.hits == ()
    assert result.prohibited_key_hits == ()
    assert result.redacted_content_hash == hashlib.sha256(b"").hexdigest()


def test_redacted_content_hash_is_sha256_hex() -> None:
    result = redact_stream(b"plain text", max_bytes=1024)

    assert len(result.redacted_content_hash) == 64
    assert set(result.redacted_content_hash) <= set("0123456789abcdef")


def test_redacted_content_hash_changes_with_redaction() -> None:
    token = _openai_api_key()
    result = _redact_text(token)
    raw_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    assert result.redacted_content_hash != raw_hash
    assert result.redacted_content_hash == hashlib.sha256(
        b"[REDACTED:openai_api_key]"
    ).hexdigest()


def test_prohibited_key_value_is_redacted_via_equal_sign() -> None:
    """Codex SP6B2 R1 F-001 + R2-001 (CRITICAL) adopt: prohibited key の
    **値** が ``[REDACTED:prohibited_key:<key>]`` に置換される。fail-closed
    redaction で newline / `,` / `;` まで value とみなす。"""

    raw = b"api_key=super-secret-canary-12345\nnext-line"
    result = redact_stream(raw, max_bytes=1024)
    assert "super-secret-canary-12345" not in result.redacted_text
    assert "[REDACTED:prohibited_key:api_key]" in result.redacted_text
    assert "next-line" in result.redacted_text
    assert result.prohibited_key_hits == ("api_key",)


def test_prohibited_key_value_is_redacted_via_colon() -> None:
    raw = b"session_token: abc123def456\nnext"
    result = redact_stream(raw, max_bytes=1024)
    assert "abc123def456" not in result.redacted_text
    assert "[REDACTED:prohibited_key:session_token]" in result.redacted_text
    assert "session_token" in result.prohibited_key_hits


def test_prohibited_key_value_quoted_redaction() -> None:
    raw = b'auth_token = "leaked-bearer-token-xyz"\n'
    result = redact_stream(raw, max_bytes=1024)
    assert "leaked-bearer-token-xyz" not in result.redacted_text
    assert "[REDACTED:prohibited_key:auth_token]" in result.redacted_text


def test_prohibited_key_value_with_spaces_full_redaction() -> None:
    """Codex SP6B2 R2-001: `key=foo bar baz` の **行全体** が redact される
    (fail-closed、whitespace で切らない)。"""

    raw = b"api_key=foo bar baz\n"
    result = redact_stream(raw, max_bytes=1024)
    assert "foo bar baz" not in result.redacted_text
    assert "[REDACTED:prohibited_key:api_key]" in result.redacted_text


def test_prohibited_key_unclosed_quote_redaction() -> None:
    """Codex SP6B2 R2-001: 閉じ quote が無くても行末まで redact。"""

    raw = b'api_key="short-secret-no-close\n'
    result = redact_stream(raw, max_bytes=1024)
    assert "short-secret-no-close" not in result.redacted_text
    assert "[REDACTED:prohibited_key:api_key]" in result.redacted_text


def test_prohibited_key_ansi_escape_strip() -> None:
    """Codex SP6B2 R2-001: ANSI escape を strip 後に redact、`api_key\\x1b[0m=`
    で word boundary が破壊される経路を物理削除。"""

    raw = b"\x1b[31mapi_key\x1b[0m=shortsecret\n"
    result = redact_stream(raw, max_bytes=1024)
    assert "shortsecret" not in result.redacted_text
    assert "\x1b[" not in result.redacted_text
    assert "[REDACTED:prohibited_key:api_key]" in result.redacted_text


def test_prohibited_key_unterminated_osc_strip() -> None:
    """Codex SP6B2 R3-001 (CRITICAL): 未終端 OSC (`\\x1b]0;` で BEL / ST 無し)
    が prohibited key と `=` を分断する経路を物理削除。strip 後 line-end まで
    削除し、後続 `=value` 部分は redaction の対象になる。"""

    raw = b"api_key\x1b]0;=shortsecret\n"
    result = redact_stream(raw, max_bytes=1024)
    assert "shortsecret" not in result.redacted_text
    assert "\x1b" not in result.redacted_text


def test_prohibited_key_malformed_csi_strip() -> None:
    """Codex SP6B2 R3-001 (CRITICAL): malformed CSI (terminator 無し
    `\\x1b[0=...`) でも secret が残らない。"""

    raw = b"api_key\x1b[0=shortsecret\n"
    result = redact_stream(raw, max_bytes=1024)
    assert "shortsecret" not in result.redacted_text
    assert "\x1b" not in result.redacted_text


def test_prohibited_key_c1_control_noise_strip() -> None:
    """Codex SP6B2 R4-001 (CRITICAL): C1 control (`\\u0080-\\u009f`) や
    raw `\\x80` を key と separator の間に挿入する経路が物理削除される。"""

    raw = b"api_key\xc2\x80=shortsecret-c1\n"
    result = redact_stream(raw, max_bytes=1024)
    assert "shortsecret-c1" not in result.redacted_text
    assert "[REDACTED:prohibited_key:api_key]" in result.redacted_text


def test_prohibited_key_c0_control_noise_strip() -> None:
    """Codex SP6B2 R4-001 (CRITICAL): C0 control (`\\x01-\\x08\\x0b\\x0c
    \\x0e-\\x1f\\x7f`) を key と separator の間に挿入する経路を物理削除。"""

    # \x07 BEL を挿入
    raw = b"api_key\x07=shortsecret-bell\n"
    result = redact_stream(raw, max_bytes=1024)
    assert "shortsecret-bell" not in result.redacted_text
    assert "[REDACTED:prohibited_key:api_key]" in result.redacted_text


def test_prohibited_key_combining_grapheme_joiner_strip() -> None:
    """Codex SP6B2 R8-001 (HIGH): COMBINING GRAPHEME JOINER (`\\u034f`、
    Default_Ignorable な Mn) を key 内部に挿入する経路を物理削除。"""

    raw = "api͏_key=shortsecret-cgj\n".encode()
    result = redact_stream(raw, max_bytes=1024)
    assert "shortsecret-cgj" not in result.redacted_text
    assert "[REDACTED:prohibited_key:api_key]" in result.redacted_text


def test_prohibited_key_variation_selector_supplement_strip() -> None:
    """Codex SP6B2 R8-001 (HIGH): Variation Selector Supplement
    (`\\U000E0100`-`\\U000E01EF`、VS17-VS256) を key 内部に挿入する経路を
    物理削除。"""

    for cp in (0xE0100, 0xE0150, 0xE01EF):
        raw = f"api{chr(cp)}_key=shortsecret-{cp:06x}\n".encode()
        result = redact_stream(raw, max_bytes=1024)
        assert f"shortsecret-{cp:06x}" not in result.redacted_text
        assert "[REDACTED:prohibited_key:api_key]" in result.redacted_text


def test_prohibited_key_deprecated_cf_strip() -> None:
    """Codex SP6B2 R7-001 (HIGH): deprecated Cf controls U+206A-U+206F (INH /
    NOH / etc.) を key 内部に挿入する経路を物理削除。Unicode Category Cf
    全体 strip により今後の新規 format char にも自動対応。"""

    for cp in range(0x206A, 0x2070):
        raw = f"api{chr(cp)}_key=shortsecret-{cp:04x}\n".encode()
        result = redact_stream(raw, max_bytes=1024)
        assert f"shortsecret-{cp:04x}" not in result.redacted_text, (
            f"U+{cp:04X} leaked"
        )
        assert "[REDACTED:prohibited_key:api_key]" in result.redacted_text


def test_prohibited_key_unicode_cf_category_universal_strip() -> None:
    """Codex SP6B2 R7-001 (HIGH): unicodedata.category(c) == 'Cf' を満たす
    全 char が strip されることを確認 (carpet-bomb defense)。"""

    import unicodedata

    sample_format_chars = [
        chr(0x00AD),  # SOFT HYPHEN
        chr(0x180E),  # MONGOLIAN VOWEL SEPARATOR (deprecated Cf)
        chr(0x200B),  # ZWSP
        chr(0x2060),  # WORD JOINER
        chr(0xFEFF),  # BOM
    ]
    for c in sample_format_chars:
        if unicodedata.category(c) != "Cf":
            continue
        raw = f"api{c}_key=secret-{ord(c):04x}\n".encode()
        result = redact_stream(raw, max_bytes=1024)
        assert f"secret-{ord(c):04x}" not in result.redacted_text


def test_prohibited_key_bidi_isolate_strip() -> None:
    """Codex SP6B2 R6-001 (HIGH): bidi isolate (LRI `\\u2066`) を key 内部に
    挿入する経路を物理削除。"""

    raw = "api⁦_key=shortsecret-lri\n".encode()
    result = redact_stream(raw, max_bytes=1024)
    assert "shortsecret-lri" not in result.redacted_text
    assert "[REDACTED:prohibited_key:api_key]" in result.redacted_text


def test_prohibited_key_plane14_tag_strip() -> None:
    """Codex SP6B2 R6-001 (HIGH): Plane 14 tag character (`\\U000E0070` = 'p')
    を key 内部に挿入する経路を物理削除。"""

    raw = "api\U000e0070_key=shortsecret-tag\n".encode()
    result = redact_stream(raw, max_bytes=1024)
    assert "shortsecret-tag" not in result.redacted_text
    assert "[REDACTED:prohibited_key:api_key]" in result.redacted_text


def test_prohibited_key_zwj_inside_key_strip() -> None:
    """Codex SP6B2 R5-001 (HIGH): ZWJ (`\\u200d`) を key 内部に挿入する経路
    (`api\\u200d_key=secret`) が strip 前処理で消され、prohibited key
    redaction が発火する。"""

    raw = "api‍_key=shortsecret-zwj\n".encode()
    result = redact_stream(raw, max_bytes=1024)
    assert "shortsecret-zwj" not in result.redacted_text
    assert "[REDACTED:prohibited_key:api_key]" in result.redacted_text


def test_prohibited_key_zwnj_between_key_and_sep_strip() -> None:
    """Codex SP6B2 R5-001 (HIGH): ZWNJ (`\\u200c`) を key と sep の間に
    挿入する経路を物理削除。"""

    raw = "api_key‌=shortsecret-zwnj\n".encode()
    result = redact_stream(raw, max_bytes=1024)
    assert "shortsecret-zwnj" not in result.redacted_text
    assert "[REDACTED:prohibited_key:api_key]" in result.redacted_text


def test_prohibited_key_bom_inside_key_strip() -> None:
    """Codex SP6B2 R5-001 (HIGH): BOM (`\\ufeff`) を key 内部に挿入する
    経路を物理削除。"""

    raw = "api﻿_key=shortsecret-bom-inside\n".encode()
    result = redact_stream(raw, max_bytes=1024)
    assert "shortsecret-bom-inside" not in result.redacted_text
    assert "[REDACTED:prohibited_key:api_key]" in result.redacted_text


def test_prohibited_key_variation_selector_strip() -> None:
    """Codex SP6B2 R5-001 (HIGH): variation selector (VS1 `\\ufe00`) を
    key 内部に挿入する経路を物理削除。"""

    raw = "api︀_key=shortsecret-vs\n".encode()
    result = redact_stream(raw, max_bytes=1024)
    assert "shortsecret-vs" not in result.redacted_text
    assert "[REDACTED:prohibited_key:api_key]" in result.redacted_text


def test_prohibited_key_non_utf8_marker_between_key_and_sep() -> None:
    """Codex SP6B2 R4-001 (CRITICAL): non-utf8 marker
    ``[REDACTED:non-utf8]`` を key と separator の間に挿入する経路でも
    prohibited key redaction が発火。"""

    raw = "api_key��=shortsecret-mojibake\n".encode()
    result = redact_stream(raw, max_bytes=1024)
    assert "shortsecret-mojibake" not in result.redacted_text
    assert "[REDACTED:prohibited_key:api_key]" in result.redacted_text


def test_redact_preserves_tab_and_newline() -> None:
    """tab (`\\x09`) / LF (`\\x0a`) / CR (`\\x0d`) は structural として保持。"""

    raw = b"hello\tworld\nnext line\r\n"
    result = redact_stream(raw, max_bytes=1024)
    assert "hello\tworld" in result.redacted_text
    assert "\n" in result.redacted_text


def test_redact_strips_lone_escape_bytes() -> None:
    """残留 \\x1b を defense-in-depth で全削除する。"""

    raw = b"some\x1bnoise here\n"
    result = redact_stream(raw, max_bytes=1024)
    assert "\x1b" not in result.redacted_text


def test_prohibited_key_comma_delimiter_keeps_following_keys() -> None:
    """`api_key=foo, auth_token=bar` の場合、`foo` のみ redact し、
    `, auth_token=bar` 部分はもう一巡で `bar` 個別 redact (structural log 互換)。"""

    raw = b"api_key=foo, auth_token=bar\n"
    result = redact_stream(raw, max_bytes=1024)
    assert "foo" not in result.redacted_text
    assert "bar" not in result.redacted_text
    assert (
        "[REDACTED:prohibited_key:api_key]" in result.redacted_text
        and "[REDACTED:prohibited_key:auth_token]" in result.redacted_text
    )


def test_prohibited_key_hint_detected_via_equal_sign() -> None:
    result = _redact_text("api_key=value")

    assert result.prohibited_key_hits == ("api_key",)


def test_prohibited_key_hint_detected_via_colon() -> None:
    result = _redact_text("secret: value")

    assert result.prohibited_key_hits == ("secret",)


def test_prohibited_key_hint_case_insensitive() -> None:
    result = _redact_text("API_KEY = value")

    assert result.prohibited_key_hits == ("api_key",)


def test_prohibited_key_hint_does_not_match_substring() -> None:
    result = _redact_text("my_api_key_test=value")

    assert result.prohibited_key_hits == ()


def test_summary_payload_excludes_raw_text() -> None:
    token = _openai_api_key()
    result = _redact_text("prefix " + token)
    payload = summary_payload(result)

    assert "redacted_text" not in payload
    assert "raw_text" not in payload
    contains_raw = token in repr(payload)
    assert contains_raw is False


def test_summary_payload_serializes_hits_as_list_of_dicts() -> None:
    result = _redact_text(_github_installation_token())
    payload = summary_payload(result)

    assert payload["hits"] == [
        {"pattern_kind": "github_installation_token", "match_count": 1}
    ]


def test_summary_payload_includes_redacted_content_hash() -> None:
    result = redact_stream(b"plain", max_bytes=1024)
    payload = summary_payload(result)

    assert payload["redacted_content_hash"] == result.redacted_content_hash


def test_summary_payload_truncated_flag_propagates() -> None:
    result = redact_stream(b"abcdef", max_bytes=3)
    payload = summary_payload(result)

    assert payload["truncated"] is True


def test_redaction_result_dataclass_is_frozen() -> None:
    result = redact_stream(b"plain", max_bytes=1024)

    with pytest.raises(AttributeError):
        result.redacted_text = "mutated"


def test_redact_input_bytes_not_mutated() -> None:
    raw = b"plain text"
    before = bytes(raw)

    redact_stream(raw, max_bytes=1024)

    assert raw == before

