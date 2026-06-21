"""Sprint 6 BL-0066: stdout / stderr redaction pipeline.

CLI subprocess の stdout / stderr buffer に raw secret / token / canary が含まれ
ていた場合、artifact 化前に **必ず redaction** してから artifact store / audit
event に保存する (SP-006 受け入れ条件: raw 値は DB / artifact / audit / logs /
test snapshot に残らない)。

設計:

- 入力: raw bytes (subprocess pipe から read された buffer)。
- 出力: ``RedactionResult`` (redacted_text + pattern hit metadata + truncation
  flag + content hash)。**raw bytes / raw text は戻り値に含まれない**。
- pattern set は ``backend.app.repositories._payload_secret_scan`` の
  ``_RAW_SECRET_PATTERNS`` と ``_PROHIBITED_PAYLOAD_KEYS`` を共有 (drift 防止)。
- secret canary fixture (Sprint 1 Batch 1 で導入) のロード可能性は本 module の
  scope 外 (fixture loader は別 module)、本 module は **pattern-based scan の
  みを契約**として持つ。
- 上限 byte 数を超えた場合は ``truncated=True`` で末尾を切り、redaction
  pipeline には truncate 後の content だけが流れる (DoS 防御)。

server-owned-boundary §1 不変条件:

- ``redact_stream(raw_bytes, max_bytes)`` は **bytes のみ** 受け取り、caller が
  redacted_text を直接指定する経路は signature レベルに存在しない。
- ``RedactionHit`` は raw value を持たず、pattern 種別 + match count + first
  byte offset (truncation diagnostics 用) のみ保存。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

from backend.app.repositories._payload_secret_scan import (
    _PROHIBITED_PAYLOAD_KEYS,
    _RAW_SECRET_PATTERNS,
)

# Replacement marker (raw value は決して残さない)
_REDACTION_MARKER = "[REDACTED:{kind}]"

# Decoder error mode: replace で raw bytes を保持しない (mojibake は redaction
# pipeline で別 marker `[REDACTED:non-utf8]` に置換)
_DECODE_ERRORS = "replace"
_NON_UTF8_MARKER = "[REDACTED:non-utf8]"
_NON_UTF8_REGEX = re.compile(r"�+")

# Codex SP6B2 R2-001 / R3-001 (CRITICAL) adopt: ANSI escape sequence
# (CSI / OSC) + 未終端 sequence を redaction 前処理で strip し、
# `api_key\x1b[0m=value` や `api_key\x1b]0;=value` のような ANSI 混入で
# `\b<key>\b` boundary が崩れる経路を物理削除。
# 未終端の場合は line-end (改行) まで strip し、secret が untreated raw
# として残らない fail-closed 化。
_ANSI_ESCAPE_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"  # closed CSI
    r"|\x1b\[[^\n]*"  # unterminated CSI → newline
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # closed OSC (BEL or ST)
    r"|\x1b\][^\n]*"  # unterminated OSC → newline
    r"|\x1b[@-Z\\-_]"  # other ESC + single byte
    r"|\x1b"  # bare ESC (fall-through)
)

# Codex SP6B2 R4-001 (CRITICAL) adopt: C0 / C1 control character (newline +
# tab は保持) を strip 前処理で除去。``api_key\x80=value`` のような C1
# 混入で word boundary が崩れる経路を物理削除。`\x09` (tab) / `\x0a` (LF)
# / `\x0d` (CR) は保持 (structural log として有意味)。
_CONTROL_CHAR_RE = re.compile(
    "["
    "\x00-\x08\x0b\x0c\x0e-\x1f"  # C0 (tab/LF/CR 除く)
    "\x7f-\u009f"  # DEL + C1
    "\u034f"  # COMBINING GRAPHEME JOINER (Mn, Default_Ignorable)
    "\u200b-\u200f"  # ZWSP / ZWNJ / ZWJ / LRM / RLM
    "\u2028-\u202e"  # line/paragraph separator + bidi override (LRE-RLO/PDF)
    "\u2060-\u2064"  # word joiner, function application, invisible separator
    "\u2066-\u2069"  # bidi isolate controls (LRI/RLI/FSI/PDI)
    "\ufeff"  # BOM / Zero-width no-break space
    "\ufe00-\ufe0f"  # variation selectors VS1-VS16
    "\U000e0000-\U000e007f"  # Plane 14 tag characters
    "\U000e0100-\U000e01ef"  # Variation Selector Supplement VS17-VS256
    "]"
)


@dataclass(frozen=True, slots=True)
class RedactionHit:
    """One pattern hit (raw value は含まない、metadata のみ)."""

    pattern_kind: str  # e.g. "openai_api_key", "github_installation_token"
    match_count: int  # 同 pattern が複数回 hit した場合の集計値


@dataclass(frozen=True, slots=True)
class RedactionResult:
    redacted_text: str  # raw secret を `[REDACTED:<kind>]` に置換した文字列
    redacted_content_hash: str  # SHA-256 hex of redacted_text (audit trace)
    raw_bytes_length: int  # original raw bytes length (DoS 観測用)
    truncated: bool  # max_bytes 超過で末尾を切ったか
    hits: tuple[RedactionHit, ...] = field(default_factory=tuple)
    prohibited_key_hits: tuple[str, ...] = field(default_factory=tuple)


def normalize_for_scan(text: str) -> str:
    """De-obfuscate text so credential scan / redaction see the SAME bytes.

    SP-PHASE0 gate C (Codex adversarial HIGH, normalization-mismatch fix):
    strips ANSI escapes + residual ``\\x1b`` + C0/C1 control chars + Unicode
    category Cc (Control) / Cf (Format) carpet-bomb (preserving ``\\t`` / ``\\n``
    / ``\\r``). An attacker can inject a single invisible char (U+200B ZWSP,
    ANSI ``\\x1b[0m``, C1 ``\\x85``) inside a credential so a raw-text scan
    misses it while the redactor later strips the char and reassembles the
    token. By normalizing **before** both the canary scan and the regex
    redaction, the two layers cannot diverge: whatever the scan sees is exactly
    what redaction sees, so an obfuscated credential is detected (and withheld)
    rather than reassembled past a narrower pattern set.
    """

    text = _ANSI_ESCAPE_RE.sub("", text)
    # residual bare ESC が regex を抜けた場合の defense-in-depth。
    text = text.replace("\x1b", "")
    # C0 / C1 control strip (tab / LF / CR は保持)。
    text = _CONTROL_CHAR_RE.sub("", text)
    # Unicode Category Cc (Control) + Cf (Format) を per-char carpet-bomb
    # (新 Unicode version の format char も自動 strip、tab / LF / CR のみ保持)。
    return "".join(
        c
        for c in text
        if c in {"\t", "\n", "\r"} or unicodedata.category(c) not in {"Cc", "Cf"}
    )


def redact_stream(
    raw_bytes: bytes,
    *,
    max_bytes: int,
) -> RedactionResult:
    """Redact a raw subprocess stream buffer.

    Args:
        raw_bytes: subprocess pipe から read された生 bytes。
        max_bytes: redaction pipeline が処理する最大 byte 数。超過分は切り捨て。

    Returns:
        ``RedactionResult`` (raw value 非含)。

    Notes:
        - decoder は ``errors="replace"`` で robust 化、bytes 不正は
          ``[REDACTED:non-utf8]`` に置換 (mojibake が log に残らない)。
        - redacted_content_hash は audit 用 (同一 redacted_text の dedup / 検証)。
    """

    if max_bytes < 0:
        raise ValueError(f"max_bytes must be >= 0 (got {max_bytes})")

    raw_len = len(raw_bytes)
    truncated = raw_len > max_bytes
    capped = raw_bytes[:max_bytes] if truncated else raw_bytes

    # decode (raw bytes は保持しない)
    decoded = capped.decode("utf-8", errors=_DECODE_ERRORS)

    # non-utf8 replacement marker → 単一 marker に置換 (raw bytes の hint を残
    # さない)
    decoded = _NON_UTF8_REGEX.sub(_NON_UTF8_MARKER, decoded)

    # ANSI escape / 残留 \x1b / C0・C1 control / Unicode Cc・Cf を strip
    # (`api_key\x1b[0m=value` / `api_key\x80=value` / U+200B 混入で word
    # boundary が崩れる経路を消す、fail-closed)。**canary scan と同一の
    # ``normalize_for_scan`` を共有**することで、scan が見るテキストと redaction
    # が見るテキストが構造的に一致し、obfuscated credential が scan を擦り抜けて
    # redact で再構成される normalization-mismatch bypass を塞ぐ (gate C HIGH)。
    decoded = normalize_for_scan(decoded)

    # Codex SP6B2 R1 F-001 (CRITICAL) adopt: prohibited key の **値** も
    # redact する。free-form text 内の ``key=value`` / ``key: value`` の
    # value 部分を ``[REDACTED:prohibited_key:<key>]`` に置換することで、
    # 8 regex pattern で拾えない短い / 構造化されていない secret 値も
    # raw 値を残さない。order が重要: 最初に prohibited key + value を
    # redact してから regex pattern redaction を行う (regex marker が
    # 直後の value 抽出を阻害しないため、ここでは順序問題は発生しない)。
    hits: dict[str, int] = {}
    prohibited_seen: list[str] = []
    redacted = decoded
    for key in _PROHIBITED_PAYLOAD_KEYS:
        # Codex SP6B2 R2-001 + R4-001 (CRITICAL) adopt: fail-closed
        # redaction。value は次の優先順序で match:
        #   1. closed double / single quoted (escape 対応)
        #   2. unclosed double / single quote → 改行 or `,;` まで
        #   3. unquoted token → 改行 or `,;` まで
        # key と separator の間に non-utf8 marker / control-stripped 残余の
        # noise が入っても match するよう許容範囲を broadening。
        noise_class = r"(?:\s|\[REDACTED:[^\]\n]*\])*"
        pattern = re.compile(
            rf"(?P<key>\b{re.escape(key)}\b){noise_class}"
            rf"(?P<sep>[=:]){noise_class}"
            rf"(?P<value>"
            r'"(?:\\.|[^"\\])*"'  # closed double-quoted string
            r"|'(?:\\.|[^'\\])*'"  # closed single-quoted string
            r'|"[^\n,;]*'  # unclosed double-quote → newline / delimiter
            r"|'[^\n,;]*"  # unclosed single-quote → newline / delimiter
            r"|[^\s,;\n][^\n,;]*"  # unquoted: non-space start, newline/delim end
            r")",
            re.IGNORECASE,
        )

        def _key_repl(match: re.Match[str], _key: str = key) -> str:
            return (
                f"{match.group('key')}{match.group('sep')}"
                f"[REDACTED:prohibited_key:{_key}]"
            )

        new_redacted, count = pattern.subn(_key_repl, redacted)
        if count > 0:
            prohibited_seen.append(key)
        redacted = new_redacted

    for kind, regex in _RAW_SECRET_PATTERNS:
        count = 0

        def _repl(_match: re.Match[str], _kind: str = kind) -> str:
            nonlocal count
            count += 1
            return _REDACTION_MARKER.format(kind=_kind)

        redacted = regex.sub(_repl, redacted)
        if count > 0:
            hits[kind] = count

    # SP-PHASE0 gate C (credential backstop, defense-in-depth): fold the
    # launcher-local credential canary patterns (JWT / codex_refresh_token /
    # anthropic OAuth / credential key-name echo / credential-file path echo)
    # into the redactor as a true backstop. The shared ``_RAW_SECRET_PATTERNS``
    # / ``_SECRET_TEXT_PATTERNS`` sets are intentionally NOT modified (their
    # exact-set drift guards must stay green); these credential patterns live in
    # ``credential_canary`` and are applied here (post-normalization) so a
    # reassembled credential is redacted even if some future path reaches
    # redaction without the canary scan having withheld it. Lazy import breaks
    # the canary→redaction import cycle.
    from backend.app.services.cli_artifact.credential_canary import (  # noqa: PLC0415
        _CREDENTIAL_TOKEN_PATTERNS,
    )

    for kind, regex in _CREDENTIAL_TOKEN_PATTERNS:
        count = 0

        def _cred_repl(_match: re.Match[str], _kind: str = kind) -> str:
            nonlocal count
            count += 1
            return _REDACTION_MARKER.format(kind=_kind)

        redacted = regex.sub(_cred_repl, redacted)
        if count > 0:
            hits[kind] = count

    redacted_content_hash = hashlib.sha256(redacted.encode("utf-8")).hexdigest()
    return RedactionResult(
        redacted_text=redacted,
        redacted_content_hash=redacted_content_hash,
        raw_bytes_length=raw_len,
        truncated=truncated,
        hits=tuple(
            RedactionHit(pattern_kind=k, match_count=v) for k, v in sorted(hits.items())
        ),
        prohibited_key_hits=tuple(sorted(prohibited_seen)),
    )


def summary_payload(result: RedactionResult) -> dict[str, object]:
    """AgentRunEvent / audit event payload 用の dict を返す (raw 値非含)。"""

    return {
        "redacted_content_hash": result.redacted_content_hash,
        "raw_bytes_length": result.raw_bytes_length,
        "truncated": result.truncated,
        "hits": [
            {"pattern_kind": h.pattern_kind, "match_count": h.match_count}
            for h in result.hits
        ],
        "prohibited_key_hints": list(result.prohibited_key_hits),
    }


__all__ = [
    "RedactionHit",
    "RedactionResult",
    "redact_stream",
    "summary_payload",
]
