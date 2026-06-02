from __future__ import annotations

import re

from backend.app.db.models.tag import TAG_COLORS, TagColor
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret

# ADR-00044 R7: tag name 専用 secret pattern。project 共通の ``assert_no_raw_secret`` は legacy token
# 集合 (sk-ant-/ghs_/gho_/ghp_/tskey-/age/PEM 等) のみで、modern OpenAI project key
# (``sk-proj-...`` 等 hyphen/underscore 含む) / GitHub fine-grained PAT / ``ghu_`` / ``ghr_`` /
# AWS access key (``AKIA...``) / secret canary を見逃す。tag name は user 自由入力で chip / list /
# filter / audit に露出するため、repo の eval scanner (``services/eval/anti_gaming.py`` /
# ``loader.py`` の ``_RAW_SECRET_VALUE_PATTERNS``) + comment 経路と **同一** の provider-token + canary
# 集合を二重適用する。drift は
# ``tests/api/test_ticket_tags.py::test_tag_name_patterns_cover_eval_scanner`` が検出する。
_TAG_NAME_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("github_pat", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{16,}\b")),
    ("github_fine_grained_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("secret_canary", re.compile(r"CANARY-FIXTURE-[A-Z0-9]{16,}")),
)


def assert_tag_name_safe(name: str) -> None:
    """tag name に raw secret / canary marker が無いか検証する (ADR-00044 R7)。

    project 共通の ``assert_no_raw_secret`` に加え、tag 専用に modern provider token / canary を検出する。
    いずれか hit で ``ValueError`` を raise (REST=422、MCP=error)。tag 作成 / rename の両経路はこの helper を
    通る repository 境界の単一関数経由のため、ここが secret / canary 永続化の単一防御点。

    Raises:
        ValueError: raw secret / canary marker / prohibited token を検出した場合。
    """
    assert_no_raw_secret({"name": name})
    for hit_kind, regex in _TAG_NAME_SECRET_PATTERNS:
        if regex.search(name) is not None:
            raise ValueError(f"tag name contains a forbidden secret pattern ({hit_kind})")


__all__ = [
    "TAG_COLORS",
    "TagColor",
    "assert_tag_name_safe",
    "_TAG_NAME_SECRET_PATTERNS",
]
