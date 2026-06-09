"""SP-032 (ADR-00052 R1 F-003): domain 正規化 (server-owned)。

caller-supplied な raw URL / 大文字 / scheme 付き文字列を信頼せず、hostname-level の registrable
domain に正規化する。eTLD+1 畳み込みはしない (exact hostname match)。IDN/punycode は P1 では未対応
(非 ASCII は reject、残リスク記録)。
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

from backend.app.services.security.secret_text_scan import assert_no_secret_in_text

# 各 label: 先頭末尾 hyphen 不可、1-63 chars。全体は service 側で 1-253 chars を確認。
_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

MAX_DOMAIN_LENGTH = 253
MAX_LABEL_LENGTH = 63


class DomainNormalizationError(ValueError):
    """domain 正規化失敗 (reason は str(exc) で参照)。"""


def normalize_domain(raw: str) -> str:
    """raw 入力を hostname-level の正規化済み domain に変換する。

    挙動 (ADR-00052 R1 F-003):
    - NFC 正規化 + lowercase + 前後 trim
    - 末尾 dot は除去
    - scheme / path / query / fragment / userinfo / port / 空白 / 連続 dot を reject
    - 非 ASCII (IDN) は reject (P1 未対応)
    - IPv4 / localhost / 単一 label を reject (registry の対象は 2+ label の hostname)

    Raises:
        DomainNormalizationError: 正規化不能 / 不正 format。
    """
    value = unicodedata.normalize("NFC", raw).strip()
    if not value:
        raise DomainNormalizationError("domain is empty")

    # 非 ASCII (IDN) は P1 未対応
    if not value.isascii():
        raise DomainNormalizationError("non-ascii domain (IDN) is not supported")

    # 内部空白を含むものは reject (trim 後に残る空白)
    if any(ch.isspace() for ch in value):
        raise DomainNormalizationError("domain must not contain whitespace")

    lowered = value.lower()

    # scheme / path / query / fragment / userinfo / port を持つものは reject
    for forbidden in ("://", "/", "?", "#", "@", ":"):
        if forbidden in lowered:
            raise DomainNormalizationError(f"domain must not contain '{forbidden}'")

    # 末尾 dot のみ除去 (FQDN 表記)。先頭 dot / 連続 dot は不正。
    lowered = lowered.rstrip(".")
    if not lowered:
        raise DomainNormalizationError("domain is empty after stripping trailing dot")
    if lowered.startswith("."):
        raise DomainNormalizationError("domain must not start with a dot")
    if ".." in lowered:
        raise DomainNormalizationError("domain must not contain consecutive dots")

    if len(lowered) > MAX_DOMAIN_LENGTH:
        raise DomainNormalizationError(f"domain exceeds {MAX_DOMAIN_LENGTH} chars")

    if _IPV4_RE.match(lowered):
        raise DomainNormalizationError("ip address is not a valid trust domain")

    labels = lowered.split(".")
    if len(labels) < 2:
        # 単一 label (localhost 等) は registry 対象外
        raise DomainNormalizationError("domain must have at least two labels")

    for label in labels:
        if len(label) > MAX_LABEL_LENGTH:
            raise DomainNormalizationError(f"domain label exceeds {MAX_LABEL_LENGTH} chars")
        if not _LABEL_RE.match(label):
            raise DomainNormalizationError(f"invalid domain label: {label!r}")

    # F-SP032-R1/R2 (Codex adversarial HIGH): secret-shaped hostname (例: legacy `sk-aaaa...` /
    # modern `sk-proj-...` / `github_pat_...` / `ghu_...` / canary) は ASCII/hyphen label として
    # 正規化を通過してしまう。write (domain_trust registry + audit) / read (research-advanced
    # enrichment) の **両方の choke point** で broad scanner を適用し reject、token-shaped 値の
    # 永続化・再露出を fail-closed で防ぐ。
    try:
        assert_no_secret_in_text(lowered, field="domain")
    except ValueError as exc:
        raise DomainNormalizationError("domain matches a secret-shaped pattern") from exc

    return lowered


def try_normalize_domain(raw: str | None) -> str | None:
    """正規化を試み、失敗時は None を返す (read-side enrichment で invalid 判定に使う)。"""
    if raw is None:
        return None
    try:
        return normalize_domain(raw)
    except DomainNormalizationError:
        return None


def domain_from_url(raw_url: str | None) -> str | None:
    """canonical_url から hostname を抽出し正規化済み domain を返す (失敗時 None)。

    evidence_sources.canonical_url (full URL) の read-side enrichment 用。urlsplit で hostname を
    取り出し (port / userinfo / path を除去)、``normalize_domain`` で検証する。
    """
    if not raw_url:
        return None
    try:
        parts = urlsplit(raw_url.strip())
    except ValueError:
        return None
    hostname = parts.hostname  # lowercased、port / userinfo 除去済み
    if not hostname:
        return None
    return try_normalize_domain(hostname)


__all__ = [
    "DomainNormalizationError",
    "MAX_DOMAIN_LENGTH",
    "MAX_LABEL_LENGTH",
    "domain_from_url",
    "normalize_domain",
    "try_normalize_domain",
]
