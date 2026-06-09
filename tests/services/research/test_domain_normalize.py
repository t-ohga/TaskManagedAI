from __future__ import annotations

import pytest

from backend.app.services.research.domain_normalize import (
    DomainNormalizationError,
    domain_from_url,
    normalize_domain,
    try_normalize_domain,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("example.com", "example.com"),
        ("EXAMPLE.COM", "example.com"),
        ("  Example.Com  ", "example.com"),
        ("example.com.", "example.com"),  # 末尾 dot 除去
        ("www.example.com", "www.example.com"),  # subdomain は保持 (exact match)
        ("a.b.example.co.jp", "a.b.example.co.jp"),
        ("xn--example.com", "xn--example.com"),  # 既に punycode 化済みは ASCII なので許可
        ("sub-domain.example-site.org", "sub-domain.example-site.org"),
    ],
)
def test_normalize_domain_valid(raw: str, expected: str) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "https://example.com",  # scheme
        "example.com/path",  # path
        "example.com?q=1",  # query
        "example.com#frag",  # fragment
        "user@example.com",  # userinfo
        "example.com:8080",  # port
        "exam ple.com",  # 内部空白
        "example..com",  # 連続 dot
        ".example.com",  # 先頭 dot
        "localhost",  # 単一 label
        "example",  # 単一 label
        "192.168.0.1",  # IPv4
        "exämple.com",  # 非 ASCII (IDN)
        "-example.com",  # label 先頭 hyphen
        "example-.com",  # label 末尾 hyphen
        "a" * 64 + ".com",  # label 過長
    ],
)
def test_normalize_domain_rejects(raw: str) -> None:
    with pytest.raises(DomainNormalizationError):
        normalize_domain(raw)


def test_normalize_domain_rejects_over_253() -> None:
    long_domain = ".".join(["abc"] * 80) + ".com"  # > 253 chars
    assert len(long_domain) > 253
    with pytest.raises(DomainNormalizationError):
        normalize_domain(long_domain)


def test_try_normalize_domain_returns_none_on_invalid() -> None:
    assert try_normalize_domain("https://bad/x") is None
    assert try_normalize_domain(None) is None
    assert try_normalize_domain("Example.COM") == "example.com"


# Codex adversarial R1 HIGH (F-1/F-2): secret-shaped hostname を write/read 両方で reject。
@pytest.mark.parametrize(
    "raw",
    [
        "sk-aaaaaaaaaaaaaaaaaaaa.example.com",  # legacy OpenAI key shaped label
        "sk-proj-abcdefghijklmnopqrstuvwxyz012345.example.com",  # modern OpenAI project key (R2)
        "github_pat_11abcdefghijklmnopqrst.example.com",  # GitHub fine-grained PAT (R2)
        "ghp_aaaaaaaaaaaaaaaaaaaa.example.com",  # GitHub PAT shaped label
        "ghu_bbbbbbbbbbbbbbbbbbbb.example.org",  # GitHub user-to-server token (R2)
        "ghs_bbbbbbbbbbbbbbbbbbbb.example.org",  # GitHub installation token shaped
    ],
)
def test_normalize_domain_rejects_secret_shaped(raw: str) -> None:
    with pytest.raises(DomainNormalizationError):
        normalize_domain(raw)
    assert try_normalize_domain(raw) is None


def test_domain_from_url_extracts_and_normalizes() -> None:
    assert domain_from_url("https://www.example.com/path?q=1") == "www.example.com"
    assert domain_from_url("http://EXAMPLE.COM:8080/x") == "example.com"  # port stripped by urlsplit
    assert domain_from_url(None) is None
    assert domain_from_url("not a url") is None
    assert domain_from_url("https://localhost/x") is None  # single label rejected


def test_domain_from_url_rejects_secret_shaped_host() -> None:
    """read-side enrichment が secret-shaped host を再露出しない (F-2)。"""
    assert domain_from_url("https://sk-aaaaaaaaaaaaaaaaaaaa.example.com/path") is None
