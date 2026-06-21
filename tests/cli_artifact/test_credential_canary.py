"""SP-PHASE0 gate C (ADR-00058 §exit must_ship): credential canary scan unit tests.

control 1 (出力 canary scan) の core 検証。mock した CLI output に **fake / canary**
credential token を流し、scanner が credential exfiltration を検出することを確認する。
clean output は pass。raw secret / 実 token は fixture に **一切登録しない** (canary /
明らかに fake な合成値のみ、AC-HARD-02 / rules/secretbroker-boundary.md §11)。

Phase 2 narrow defer: full autonomous な実 codex 実行を伴う integration test (実 codex
binary を malicious prompt で動かし実 credential が流れないことを確認する) は real binary +
実 credential を要し CI 不可。大元計画 Phase 2 (CLIAgentAdapter) の integration test へ defer。
本 unit test は mock output に対する scanner 検出を契約として固定する。
"""

from __future__ import annotations

import pytest

from backend.app.services.cli_artifact.credential_canary import (
    _BROAD_SCANNER_KIND,
    CredentialCanaryHit,
    scan_for_credential_exfiltration,
    scan_streams_for_credential_exfiltration,
)

# fake / canary credential tokens (実 token ではない、合成値のみ)。各値は credential
# file の構造を **模した** ものだが、有効な credential ではない。
# - codex auth.json id_token / access_token = JWT (eyJ... header)
_FAKE_JWT = (
    "eyJhbGciOiJIUzI1NiJ9."
    "eyJzdWIiOiJjYW5hcnktZmFrZS1ub3QtcmVhbCJ9."
    "ZmFrZXNpZ25hdHVyZS1jYW5hcnktMDAwMA"
)
# - codex auth.json tokens.refresh_token = rt.<digits>.<~330 base64url> (opaque
#   単一 segment、最重要 credential)。fake base64url で実形式を模す。
_FAKE_CODEX_REFRESH = "rt.1.AAD" + ("Fakecanary0123456789-_" * 3) + "endFAKE"
# - claude .credentials.json claudeAiOauth.accessToken = sk-ant-oat01-...
_FAKE_ANTHROPIC_OAUTH = "sk-ant-oat01-" + "FAKEcanary0123456789abcdef"
# - generic OpenAI-shaped key (base scanner が拾う)
_FAKE_OPENAI = "sk-proj-FAKEcanary0123456789abcdef"
# - secret canary fixture marker (base scanner が拾う)
_CANARY_MARKER = "CANARY-FIXTURE-ABCDEFGH01234567"
# - credential file path echo (cat ~/.codex/auth.json の兆候)
_CRED_PATH_ECHO = "reading /Users/victim/.codex/auth.json now"


# --- detection (each credential shape must be caught) ------------------------


@pytest.mark.parametrize(
    ("text", "expected_kind"),
    [
        (f"id_token: {_FAKE_JWT}", "jwt_credential_token"),
        (f"refresh_token: {_FAKE_CODEX_REFRESH}", "codex_refresh_token"),
        (f"access_token={_FAKE_ANTHROPIC_OAUTH}", "anthropic_oauth_token"),
        (f"here is a key {_FAKE_OPENAI}", _BROAD_SCANNER_KIND),
        (f"canary {_CANARY_MARKER} leaked", _BROAD_SCANNER_KIND),
        (_CRED_PATH_ECHO, "credential_file_path_echo"),
        ("cat ~/.ssh/id_rsa output: /home/u/.ssh/id_rsa", "credential_file_path_echo"),
        ("aws cred at /home/u/.aws/credentials", "credential_file_path_echo"),
    ],
)
def test_scan_detects_credential_token(text: str, expected_kind: str) -> None:
    result = scan_for_credential_exfiltration(text)
    assert result.hit is True
    assert expected_kind in {h.pattern_kind for h in result.hits}


def test_scan_detects_codex_refresh_token_real_format() -> None:
    """Codex adversarial HIGH 1: codex refresh_token は実形式 (rt.N.<base64url>) を
    専用 pattern で検出する (JWT 代理検証で coverage を偽装しない)。

    refresh_token は最重要 credential (長命・access_token を無限 mint) だが JWT
    (eyJ 3-segment) でも anthropic (sk-ant) でも broad scanner (sk-/ghp_) でもない
    opaque token のため、全 scanner を素通りしていた経路を専用 pattern が閉じる。
    """

    text = f'{{"tokens": {{"refresh_token": "{_FAKE_CODEX_REFRESH}"}}}}'
    result = scan_for_credential_exfiltration(text)
    assert result.hit is True
    kinds = {h.pattern_kind for h in result.hits}
    # 専用 pattern で確実に拾う (JWT 代理ではない)。
    assert "codex_refresh_token" in kinds
    # JSON key-name canary も同時に hit する (encode 非依存の二重防御)。
    assert "credential_key_name_echo" in kinds


@pytest.mark.parametrize(
    "text",
    [
        '{"refresh_token": "redacted"}',
        '{"access_token" : "x"}',
        '{"id_token":"y"}',
        '{"accessToken": "z"}',
        '{"refreshToken": "w"}',
        '{"account_id": "123"}',
        '{"OPENAI_API_KEY": "ENV"}',
        '{"ANTHROPIC_API_KEY": "ENV"}',
        '{"client_secret": "cs"}',
    ],
)
def test_scan_detects_json_key_name_canary(text: str) -> None:
    """Codex adversarial HIGH 1 + MEDIUM: credential file の JSON key 名が出力に
    現れたら token 値の形 / encode に依存せず hit する (credential-dump 兆候の
    fail-closed 捕捉)。token 値を base64/hex 再 encode しても key 構造で捕捉。"""

    result = scan_for_credential_exfiltration(text)
    assert result.hit is True
    assert "credential_key_name_echo" in {h.pattern_kind for h in result.hits}


def test_key_name_canary_catches_reencoded_token_via_structure() -> None:
    """MEDIUM: token 値を base64 で再 encode しても JSON key 構造が残れば検出。"""

    # token 値を base64 風に再 encode (value-pattern は擦り抜けるが key 構造は残る)。
    text = '{"refresh_token": "cmVlbmNvZGVkLWZha2UtYmxvYg=="}'
    result = scan_for_credential_exfiltration(text)
    assert result.hit is True
    assert "credential_key_name_echo" in {h.pattern_kind for h in result.hits}


def test_scan_detects_custom_codex_home_path_echo() -> None:
    """Codex adversarial LOW: custom CODEX_HOME 配下の auth.json basename も捕捉。"""

    text = "reading /run/cli-home/codex-agent/auth.json now"
    result = scan_for_credential_exfiltration(text)
    assert result.hit is True
    assert "credential_file_path_echo" in {h.pattern_kind for h in result.hits}


# --- clean output passes -----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "ordinary review summary: the diff looks correct",
        "function foo() returns bar; refactor suggestion",
        "eyJ short notreal",  # not a full 3-segment JWT
        "the word access_token appears but no value follows here.",
        "https://example.com/path is fine",
    ],
)
def test_scan_passes_clean_output(text: str) -> None:
    result = scan_for_credential_exfiltration(text)
    assert result.hit is False
    assert result.hits == ()


# --- no raw value in result --------------------------------------------------


def test_result_does_not_contain_raw_token() -> None:
    """hit metadata に raw token / credential が混入しないこと (AC-HARD-02)。"""

    result = scan_for_credential_exfiltration(f"access_token={_FAKE_ANTHROPIC_OAUTH}")
    assert result.hit is True
    for hit in result.hits:
        assert _FAKE_ANTHROPIC_OAUTH not in hit.pattern_kind
        assert "sk-ant" not in hit.pattern_kind
        # CredentialCanaryHit only carries kind + count, never raw value.
        assert isinstance(hit, CredentialCanaryHit)
        assert isinstance(hit.match_count, int)


# --- multi-stream aggregation ------------------------------------------------


def test_scan_streams_aggregates_hits() -> None:
    """stdout / stderr / output / stream をまとめて scan し hit 集約する。"""

    result = scan_streams_for_credential_exfiltration(
        "clean stdout",
        f"stderr leak: {_FAKE_JWT}",
        f"output artifact: {_FAKE_ANTHROPIC_OAUTH}",
        "",
    )
    assert result.hit is True
    kinds = {h.pattern_kind for h in result.hits}
    assert "jwt_credential_token" in kinds
    assert "anthropic_oauth_token" in kinds


def test_scan_streams_all_clean_passes() -> None:
    result = scan_streams_for_credential_exfiltration(
        "clean a", "clean b", "clean c", ""
    )
    assert result.hit is False
    assert result.hits == ()


# --- obfuscation bypass (normalization-mismatch HIGH fix) --------------------
# 攻撃者が credential に不可視文字 (U+200B ZWSP / ANSI escape / C1 control) を
# 注入して raw-text scan を擦り抜け、redaction が同 char を strip して token を
# 再構成する bypass を塞いだことを固定する。scan と redaction は同一の
# normalize_for_scan を共有するため構造的に divergence しない。

from backend.app.services.cli_artifact.redaction import (  # noqa: E402
    normalize_for_scan,
    redact_stream,
)

_OBFUSCATORS = [
    ("zwsp", "​"),       # zero-width space (Cf)
    ("ansi_reset", "\x1b[0m"),  # ANSI escape
    ("c1", "\x85"),            # C1 control (NEL)
    ("bom", "﻿"),        # zero-width no-break space (Cf)
]


@pytest.mark.parametrize("tok_label,tok", [("jwt", _FAKE_JWT), ("refresh", _FAKE_CODEX_REFRESH)])
@pytest.mark.parametrize("obf_label,obf", _OBFUSCATORS)
def test_obfuscated_credential_is_detected(
    tok_label: str, tok: str, obf_label: str, obf: str
) -> None:
    """不可視文字を注入した credential も scan が検出する (normalization 統一)。"""

    obfuscated = f"id_token: {tok[:5]}{obf}{tok[5:]}"
    result = scan_for_credential_exfiltration(obfuscated)
    assert result.hit, f"{tok_label}/{obf_label} obfuscation escaped the scan"
    # raw token (前半 8 文字) が hit metadata に混入しない (AC-HARD-02)。
    for h in result.hits:
        assert tok[:8] not in h.pattern_kind


@pytest.mark.parametrize("tok_label,tok", [("jwt", _FAKE_JWT), ("refresh", _FAKE_CODEX_REFRESH)])
@pytest.mark.parametrize("obf_label,obf", _OBFUSCATORS)
def test_redact_stream_backstop_strips_obfuscated_credential(
    tok_label: str, tok: str, obf_label: str, obf: str
) -> None:
    """redact_stream backstop が再構成された credential を raw で残さない。"""

    obfuscated = f"id_token: {tok[:5]}{obf}{tok[5:]}"
    redacted = redact_stream(obfuscated.encode("utf-8"), max_bytes=10_000)
    # 再構成後の raw token prefix が redacted_text / content_hash 経由で残らない。
    assert tok[:12] not in redacted.redacted_text


def test_normalize_for_scan_strips_invisible_but_keeps_visible() -> None:
    """normalize_for_scan は不可視文字のみ除去し visible 文字は保持する。"""

    assert normalize_for_scan("a​b\x85c\x1b[0md") == "abcd"
    assert normalize_for_scan("line1\nline2\tend") == "line1\nline2\tend"
