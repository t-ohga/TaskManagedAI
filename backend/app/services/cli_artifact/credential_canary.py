"""SP-PHASE0 gate C (ADR-00058 §exit must_ship): CLI 出力 credential canary scan.

host-ambient CLI launcher (codex 等) は credential file (``~/.codex/auth.json`` /
``~/.claude/.credentials.json``) を **CLI 自身が読む** 設計のため、レビュー対象の
diff / prompt は untrusted content で、prompt-injection により CLI 配下の AI/tool
層に ``cat ~/.codex/auth.json`` 等を実行させ credential を stdout / stderr /
artifact へ exfiltrate させ得る (env / argv 非露出・per-agent HOME だけでは閉じない、
ADR-00058 §境界批評 R16 finding-1)。

本 module は **launcher が capture した stdout / stderr (+ output / stream artifact)
に対して credential / secret token pattern を scan** し、検出を ``CredentialCanaryHit``
(raw 値非含、hit 種別のみ) として返す。launcher は hit があれば
``LauncherDenyReason.CREDENTIAL_EXFILTRATION`` の Hard Gate failure として扱う。

scanner 構成 (drift 防止):

- base layer = ``services/security/secret_text_scan.assert_no_secret_in_text``。
  project 共通の broad provider-token + canary 集合 (``sk-`` / ``sk-ant-`` /
  ``ghp_`` 等 + ``CANARY-FIXTURE-*``) を再利用する。これは ticket comment /
  eval anti-gaming scanner と exact-set drift guard で同期されているため、本
  module は **その集合を変更せず** import で再利用する。
- credential layer = 本 module 固有の ``_CREDENTIAL_TOKEN_PATTERNS``。CLI サブスク
  credential file の token 形 (codex の JWT ``id_token`` / ``access_token`` =
  ``eyJ...``、codex / claude の OAuth ``refresh_token`` / ``access_token`` /
  ``accessToken`` / ``refreshToken`` = ``sk-ant-oat`` / ``sk-ant-ort`` 系・OAuth
  bearer) と、credential-file path が出力に echo される exfiltration 兆候を捕捉する。

server-owned-boundary §1 / SecretBroker rules:

- 戻り値 (``CredentialCanaryHit``) は **raw value を一切含まない** (pattern 種別 +
  match count のみ)。raw token / credential は log / artifact / audit / test fixture
  に残さない (rules/secretbroker-boundary.md §11、AC-HARD-02)。

Phase 2 narrow defer (本 module / launcher では実装しない):

- full autonomous な **任意 prompt の実 codex 実行を伴う integration test** (実際に
  codex binary を malicious prompt で動かし、credential が stdout / artifact へ流れ
  ないことを実機確認する) は real codex binary + 実 credential を要し CI 不可。これは
  **大元計画 Phase 2 (CLIAgentAdapter 本体) の integration test** へ narrow defer する
  (ADR-00058 §83 実コード review / §95 accepted HIGH risk)。Phase 0 は本 module の
  unit test (mock した CLI output に fake credential token を流し検出を確認) と launcher
  の canary scan wiring test で control を検証する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.services.cli_artifact.redaction import normalize_for_scan
from backend.app.services.security.secret_text_scan import (
    assert_no_secret_in_text,
)

# CLI サブスク credential file (codex / claude) の token 形 + exfiltration 兆候。
# base scanner (secret_text_scan) が拾う provider-key / canary に **加えて** 適用する
# credential 固有層。raw value は登録しない (pattern のみ)。
_CREDENTIAL_TOKEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # JWT (codex auth.json の id_token / access_token は ``eyJ`` base64url header
    # で始まる 3 segment token)。header.payload.signature の 3 部構成を要求し、
    # 通常文中の base64 風文字列での誤検出を抑える。
    (
        "jwt_credential_token",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    ),
    # Codex refresh_token (auth.json ``tokens.refresh_token``)。実機形式 =
    # ``rt.<digits>.<~330 base64url>`` の opaque 単一 segment。最重要 credential
    # (長命・access_token を無限 mint) だが JWT (3-segment) でも anthropic
    # (sk-ant) でも broad scanner (sk-/ghp_) でもないため、専用 pattern を持つ
    # (Codex adversarial HIGH 1: 全 scanner 素通り経路を物理削除)。
    (
        "codex_refresh_token",
        re.compile(r"\brt\.[0-9]+\.[A-Za-z0-9_-]{40,}\b"),
    ),
    # Anthropic OAuth access / refresh token (claude .credentials.json の
    # claudeAiOauth.accessToken / refreshToken)。``sk-ant-oat01-`` (access) /
    # ``sk-ant-ort01-`` (refresh) 系。base scanner の ``sk-`` でも拾えるが、
    # credential-context を明示するため種別を分けて記録する。
    (
        "anthropic_oauth_token",
        re.compile(r"\bsk-ant-(?:oat|ort|sid)[0-9]{0,4}-[A-Za-z0-9_-]{16,}\b"),
    ),
    # JSON key-name canary (Codex adversarial HIGH 1 + MEDIUM の核心):
    # credential file の JSON key 名が出力に現れたら hit。**token 値の形 / encode
    # に依存せず** credential-dump 兆候を fail-closed に捕捉する (path-echo の
    # value-key 版)。これにより token を base64 / hex で再 encode したり改行で
    # 分断しても、JSON key 構造 (``"refresh_token":`` 等) が残れば検出される。
    (
        "credential_key_name_echo",
        re.compile(
            r'"(?:refresh_token|access_token|id_token|accessToken|refreshToken'
            r"|account_id|OPENAI_API_KEY|ANTHROPIC_API_KEY|client_secret"
            r"|clientSecret|sops_age_key|age_private_key)"
            r'"\s*:'
        ),
    ),
    # credential-file path が出力に echo される exfiltration 兆候 (``cat
    # ~/.codex/auth.json`` の結果ヘッダや path 自体)。**basename 照合** に緩め、
    # custom CODEX_HOME / 別 credential dir 配下の同 file 名も捕捉する (Codex
    # adversarial LOW: hardcoded path のみだと override 経路を見逃す)。path だけ
    # では raw secret ではないが、host-ambient credential file への read 試行の
    # 強い signal。残る制約 (任意 file 名の credential は捕捉外) は ADR-00058
    # §残リスクに記載。
    (
        "credential_file_path_echo",
        re.compile(
            r"(?:/auth\.json\b|\.credentials\.json\b|/\.claude\.json\b"
            r"|/\.aws/credentials\b|/credentials\.json\b"
            r"|\bid_(?:rsa|ed25519|ecdsa|dsa)\b)"
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class CredentialCanaryHit:
    """One credential canary hit (raw value は含まない、metadata のみ)."""

    pattern_kind: str  # e.g. "jwt_credential_token", "broad_secret_pattern"
    match_count: int  # 同種 pattern の hit 集計


@dataclass(frozen=True, slots=True)
class CredentialCanaryResult:
    """Credential canary scan の結果 (raw 値非含)."""

    hit: bool
    hits: tuple[CredentialCanaryHit, ...]

    @property
    def total_match_count(self) -> int:
        return sum(h.match_count for h in self.hits)


# base scanner (broad provider-token + canary + prohibited key) hit を 1 まとめに
# 集約する種別名。raw 値や具体 pattern 名は露出しない。
_BROAD_SCANNER_KIND = "broad_secret_or_canary"


def scan_for_credential_exfiltration(text: str) -> CredentialCanaryResult:
    """CLI 出力 ``text`` を credential / secret token pattern で scan する。

    base layer (``secret_text_scan.assert_no_secret_in_text``: project 共通の broad
    provider-token + canary + prohibited key) と credential layer
    (``_CREDENTIAL_TOKEN_PATTERNS``: CLI サブスク credential file の token 形) を
    両方適用する。

    Returns:
        ``CredentialCanaryResult`` (raw value 非含、hit 種別 + count のみ)。

    Notes:
        SP-PHASE0 gate C (normalization-mismatch fix): scan は **redaction と同一の
        ``normalize_for_scan``** を先に適用する。これにより不可視文字 (U+200B ZWSP /
        ANSI escape / C1 control) を credential に注入して raw-text scan を擦り抜け、
        redaction が同 char を strip して token を再構成する bypass を塞ぐ。scan と
        redaction が同一の正規化テキストを見るため構造的に divergence しない。
    """

    # redaction と同一正規化 (ANSI / control / Cc / Cf strip) を先に適用。
    normalized = normalize_for_scan(text)

    hits: list[CredentialCanaryHit] = []

    # base layer: broad scanner は値検出を例外で返すため、bool に正規化する。
    # raw 値は例外メッセージにも残さない (assert_no_secret_in_text は種別のみ)。
    try:
        assert_no_secret_in_text(normalized, field="cli_output")
    except ValueError:
        hits.append(
            CredentialCanaryHit(pattern_kind=_BROAD_SCANNER_KIND, match_count=1)
        )

    # credential layer: CLI 固有 token 形 (正規化済テキストで照合)。
    for kind, regex in _CREDENTIAL_TOKEN_PATTERNS:
        count = len(regex.findall(normalized))
        if count > 0:
            hits.append(CredentialCanaryHit(pattern_kind=kind, match_count=count))

    return CredentialCanaryResult(hit=bool(hits), hits=tuple(hits))


def scan_streams_for_credential_exfiltration(
    *streams: str,
) -> CredentialCanaryResult:
    """複数 stream (stdout / stderr / output / stream artifact) をまとめて scan。

    各 stream を個別 scan し、hit を pattern_kind 単位で集約する。1 stream でも
    hit があれば ``hit=True``。
    """

    aggregated: dict[str, int] = {}
    for stream in streams:
        for h in scan_for_credential_exfiltration(stream).hits:
            aggregated[h.pattern_kind] = aggregated.get(h.pattern_kind, 0) + h.match_count
    hits = tuple(
        CredentialCanaryHit(pattern_kind=kind, match_count=count)
        for kind, count in sorted(aggregated.items())
    )
    return CredentialCanaryResult(hit=bool(hits), hits=hits)


__all__ = [
    "CredentialCanaryHit",
    "CredentialCanaryResult",
    "_BROAD_SCANNER_KIND",
    "_CREDENTIAL_TOKEN_PATTERNS",
    "scan_for_credential_exfiltration",
    "scan_streams_for_credential_exfiltration",
]
