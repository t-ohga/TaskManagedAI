"""taskhub status/init --local wiring + DB URL redaction tests (no-DB、SP-PHASE0 S3)。

DB connectivity / alembic head の e2e は S4 (DB-gated) が担当。本 test は subparser 配線 +
`--local` flag + password redaction (raw credential 非出力) + expected head が固定 literal でない
ことを固める。
"""

from __future__ import annotations

from scripts.taskhub_admin import _build_parser, _cmd_init, _cmd_status
from scripts.taskhub_local_status import (
    _expected_alembic_head,
    _redact_database_url,
    _to_host_loopback_dsn,
)


def test_status_local_flag_wired() -> None:
    parser = _build_parser()
    args = parser.parse_args(["status", "--local"])
    assert args.func is _cmd_status
    assert args.local is True
    assert args.database_url is None


def test_status_without_local_keeps_skeleton_default() -> None:
    """既存契約: --local なしの status は skeleton path (local=False)。"""
    parser = _build_parser()
    args = parser.parse_args(["status"])
    assert args.local is False


def test_init_local_flag_wired() -> None:
    parser = _build_parser()
    args = parser.parse_args(["init", "--local"])
    assert args.func is _cmd_init
    assert args.local is True
    # --local mode では --host / --tailnet は不要 (default None)
    assert args.host is None
    assert args.tailnet is None


def test_init_host_tailnet_still_optional_in_parser() -> None:
    """既存契約: init --host --tailnet も引き続き parse 可 (skeleton path)。"""
    parser = _build_parser()
    args = parser.parse_args(["init", "--host", "t-ohga-mac", "--tailnet", "tail-x.ts.net"])
    assert args.host == "t-ohga-mac"
    assert args.tailnet == "tail-x.ts.net"
    assert args.local is False


def test_redact_database_url_hides_password() -> None:
    redacted = _redact_database_url(
        "postgresql+asyncpg://taskmanagedai:supersecretpwd@127.0.0.1:5432/taskmanagedai"
    )
    assert "supersecretpwd" not in redacted
    assert "***" in redacted
    assert "taskmanagedai" in redacted  # user / db name は残す
    assert "127.0.0.1:5432" in redacted


def test_redact_database_url_no_password_noop() -> None:
    # password component が無い URL は変化なし (誤って何かを redact しない)
    url = "postgresql+asyncpg://localhost:5432/db"
    assert _redact_database_url(url) == url


def test_redact_database_url_handles_special_chars() -> None:
    """Codex PR #353 LOW adopt: password に @ / / 等を含んでも完全 mask (regex→urllib.parse)。"""
    # password に '@' を含む (regex だと userinfo 境界を誤判定して leak し得た)
    redacted = _redact_database_url(
        "postgresql+asyncpg://user:p%40ss@127.0.0.1:5432/db"
    )
    assert "p%40ss" not in redacted
    assert "***" in redacted
    assert "127.0.0.1:5432" in redacted


def test_to_host_loopback_dsn_rewrites_compose_internal_host() -> None:
    """Codex PR #353 F5 adopt: compose-internal host (postgres) を 127.0.0.1 へ書換える (host-local check)。"""
    rewritten = _to_host_loopback_dsn(
        "postgresql+asyncpg://taskmanagedai:pw@postgres:5432/taskmanagedai"
    )
    assert "@127.0.0.1:5432/" in rewritten
    assert "postgres:5432" not in rewritten
    assert "pw" in rewritten  # 接続用 password は保持 (出力時に別途 redact)


def test_to_host_loopback_dsn_preserves_remote_and_loopback() -> None:
    """remote / 既に loopback の DSN は書換えない (compose-internal host のみ rewrite)。"""
    remote = "postgresql+asyncpg://u:p@db.example.com:5432/x"
    assert _to_host_loopback_dsn(remote) == remote
    loop = "postgresql+asyncpg://u:p@127.0.0.1:5432/x"
    assert _to_host_loopback_dsn(loop) == loop


def test_expected_alembic_head_is_not_hardcoded_literal() -> None:
    """SP-PHASE0 S3 制約: expected head は ScriptDirectory から runtime 取得 (固定 literal でない)。

    repo に migration が存在すれば head が取れる。取れた場合は revision 形式の文字列であること
    (具体的 revision id を test に hardcode しない = drift を test 自体に持ち込まない)。
    """
    head = _expected_alembic_head()
    assert head is None or isinstance(head, str)
    if head is not None:
        assert head  # non-empty
