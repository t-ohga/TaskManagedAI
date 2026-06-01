"""ADR-00043 (R-2): dev session claims の iat (最終ログイン日時) contract test.

iat は表示専用。auth / expiry 判定には使わず (exp のみ)、HMAC 署名対象で改ざん不可、既存 cookie
(iat 無) は iat=None で後方互換。pure crypto 関数 (DB 不要) を直接検証する。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from backend.app.middleware.dev_actor import (
    DEFAULT_ACTOR_ID,
    DEFAULT_PRINCIPAL_TYPE,
    SESSION_TTL_SECONDS,
    _base64url_encode,
    _sign_payload,
    create_signed_session_cookie,
    verify_signed_session_cookie,
)

_SECRET = "test-session-secret-for-iat-adr00043"


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, 9, 0, 0, tzinfo=UTC)


def test_new_cookie_includes_iat_equal_to_issued_at() -> None:
    now = _fixed_now()
    cookie, expires_at = create_signed_session_cookie(secret=_SECRET, now=now)
    claims = verify_signed_session_cookie(cookie, secret=_SECRET, now=now)
    assert claims is not None
    # iat = login 時刻、exp = iat + TTL。
    assert claims.iat == int(now.timestamp())
    assert claims.exp == int(now.timestamp()) + SESSION_TTL_SECONDS
    assert expires_at == now + timedelta(seconds=SESSION_TTL_SECONDS)


def _sign_old_format_cookie(*, exp: int) -> str:
    # iat 無し (旧 format) の payload を旧来どおり署名する。
    payload = json.dumps(
        {"actor_id": DEFAULT_ACTOR_ID, "exp": exp, "principal_type": DEFAULT_PRINCIPAL_TYPE},
        separators=(",", ":"),
        sort_keys=True,
    )
    segment = _base64url_encode(payload.encode("utf-8"))
    return f"{segment}.{_sign_payload(segment, _SECRET)}"


def test_legacy_cookie_without_iat_is_still_valid_with_none_iat() -> None:
    now = _fixed_now()
    future_exp = int(now.timestamp()) + SESSION_TTL_SECONDS
    cookie = _sign_old_format_cookie(exp=future_exp)
    claims = verify_signed_session_cookie(cookie, secret=_SECRET, now=now)
    # iat 無 cookie は session 有効 (exp 未来) かつ iat=None (後方互換)。
    assert claims is not None
    assert claims.iat is None
    assert claims.exp == future_exp


def test_tampered_iat_fails_signature() -> None:
    now = _fixed_now()
    cookie, _ = create_signed_session_cookie(secret=_SECRET, now=now)
    payload_segment, signature_segment = cookie.split(".")
    # payload を別 iat に差し替え、署名はそのまま (改ざん) → signature mismatch で reject。
    tampered_payload = json.dumps(
        {
            "actor_id": DEFAULT_ACTOR_ID,
            "exp": int(now.timestamp()) + SESSION_TTL_SECONDS,
            "iat": int(now.timestamp()) - 99999,
            "principal_type": DEFAULT_PRINCIPAL_TYPE,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    tampered_segment = _base64url_encode(tampered_payload.encode("utf-8"))
    tampered_cookie = f"{tampered_segment}.{signature_segment}"
    assert tampered_cookie != cookie
    assert verify_signed_session_cookie(tampered_cookie, secret=_SECRET, now=now) is None


def test_expiry_uses_exp_only_not_iat() -> None:
    now = _fixed_now()
    # exp 過去 (iat が未来でも) → reject (iat を有効性に使わない)。
    expired_cookie, _ = create_signed_session_cookie(
        secret=_SECRET, now=now - timedelta(seconds=SESSION_TTL_SECONDS + 10)
    )
    assert verify_signed_session_cookie(expired_cookie, secret=_SECRET, now=now) is None
    # exp 未来 → iat が過去でも有効。
    valid_cookie, _ = create_signed_session_cookie(secret=_SECRET, now=now)
    assert verify_signed_session_cookie(valid_cookie, secret=_SECRET, now=now) is not None
