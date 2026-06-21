"""taskhub secret-create / secret-rotate / secret-revoke CLI wiring tests (no-DB、SP-PHASE0 S3)。

DB e2e (register/rotate/revoke の crash-safe lifecycle) は S4 (DB-gated) suite が担当。本 test は
subparser 配線 + **raw material が argv から物理排除されていること (getpass/stdin のみ)** +
revoke の DESTRUCTIVE approval gate 配線 + helper importability を固める。
"""

from __future__ import annotations

import argparse
from typing import Any

import pytest

from scripts import taskhub_admin
from scripts.taskhub_admin import (
    _build_parser,
    _cmd_secret_create,
    _cmd_secret_revoke,
    _cmd_secret_rotate,
    _read_secret_material,
)
from scripts.taskhub_secret_lifecycle import (
    create_secret,
    revoke_secret,
    rotate_secret,
)
from scripts.taskhub_signed_approval import (
    DESTRUCTIVE_SUBCOMMANDS,
    DRILL_KIND_ALLOWED_SUBCOMMANDS,
)

# --- subparser wiring --------------------------------------------------------


def test_secret_create_subparser_wired() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        [
            "secret-create",
            "--tenant-id", "1",
            "--scope", "project",
            "--name", "github-token",
            "--allowed-consumers", "repo-proxy",
            "--allowed-operations", "repo.push,repo.pr_open",
        ]
    )
    assert args.func is _cmd_secret_create
    assert args.tenant_id == 1
    assert args.scope == "project"
    assert args.name == "github-token"
    assert args.version == "v1"  # default
    assert args.material_stdin is False
    assert args.database_url is None


def test_secret_rotate_subparser_wired() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        [
            "secret-rotate",
            "--tenant-id", "2",
            "--old-secret-ref-id", "11111111-1111-1111-1111-111111111111",
            "--new-version", "v2",
            "--allowed-consumers", "repo-proxy",
            "--allowed-operations", "repo.push",
        ]
    )
    assert args.func is _cmd_secret_rotate
    assert args.tenant_id == 2
    assert args.new_version == "v2"
    assert args.material_stdin is False


def test_secret_revoke_subparser_wired() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        [
            "secret-revoke",
            "--tenant-id", "1",
            "--secret-ref-id", "22222222-2222-2222-2222-222222222222",
        ]
    )
    assert args.func is _cmd_secret_revoke
    assert args.tenant_id == 1
    # signed approval args are attached (destructive gate)
    assert hasattr(args, "approval_id")


def test_secret_create_requires_tenant_scope_name_allowlists() -> None:
    parser = _build_parser()
    for missing in (
        ["secret-create", "--scope", "project", "--name", "x",
         "--allowed-consumers", "c", "--allowed-operations", "o"],
        ["secret-create", "--tenant-id", "1", "--name", "x",
         "--allowed-consumers", "c", "--allowed-operations", "o"],
        ["secret-create", "--tenant-id", "1", "--scope", "project",
         "--allowed-consumers", "c", "--allowed-operations", "o"],
        ["secret-create", "--tenant-id", "1", "--scope", "project", "--name", "x",
         "--allowed-operations", "o"],
        ["secret-create", "--tenant-id", "1", "--scope", "project", "--name", "x",
         "--allowed-consumers", "c"],
    ):
        with pytest.raises(SystemExit):
            parser.parse_args(missing)


def test_secret_create_rejects_unknown_scope() -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "secret-create", "--tenant-id", "1", "--scope", "top_secret",
                "--name", "x", "--allowed-consumers", "c", "--allowed-operations", "o",
            ]
        )


# --- argv 物理排除: raw material flag は存在しない ----------------------------


@pytest.mark.parametrize("subcommand", ["secret-create", "secret-rotate"])
def test_no_material_argv_flag(subcommand: str) -> None:
    """raw secret material を受ける argv flag (--material / --secret / --token) を定義しない。

    argv は ``ps`` / shell history で world-visible になるため、material は getpass/stdin のみ
    (secretbroker-boundary §1)。`--material` を渡すと argparse が unknown-arg で SystemExit。
    """
    parser = _build_parser()
    base = (
        ["secret-create", "--tenant-id", "1", "--scope", "project", "--name", "x",
         "--allowed-consumers", "c", "--allowed-operations", "o"]
        if subcommand == "secret-create"
        else
        ["secret-rotate", "--tenant-id", "1",
         "--old-secret-ref-id", "11111111-1111-1111-1111-111111111111",
         "--new-version", "v2", "--allowed-consumers", "c", "--allowed-operations", "o"]
    )
    for forbidden_flag in ("--material", "--secret", "--token", "--raw-material"):
        with pytest.raises(SystemExit):
            parser.parse_args([*base, forbidden_flag, "supersecret"])


def test_read_secret_material_uses_getpass_not_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    """interactive 経路は getpass.getpass を呼ぶ (TTY echo なし)。argv は参照しない。"""
    called: dict[str, Any] = {}

    def _fake_getpass(prompt: str = "") -> str:
        called["prompt"] = prompt
        return "from-getpass"

    monkeypatch.setattr(taskhub_admin.getpass, "getpass", _fake_getpass)
    args = argparse.Namespace(material_stdin=False)
    material = _read_secret_material(args)
    assert material == b"from-getpass"
    assert "prompt" in called  # getpass was invoked


def test_read_secret_material_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    """--material-stdin は stdin 1 行を読み末尾改行を strip する。"""
    import io

    monkeypatch.setattr(taskhub_admin.sys, "stdin", io.StringIO("tok-from-stdin\n"))
    args = argparse.Namespace(material_stdin=True)
    material = _read_secret_material(args)
    assert material == b"tok-from-stdin"


def test_read_secret_material_empty_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(taskhub_admin.getpass, "getpass", lambda prompt="": "")
    args = argparse.Namespace(material_stdin=False)
    assert _read_secret_material(args) is None


# --- DESTRUCTIVE gate: secret-revoke -----------------------------------------


def test_secret_revoke_in_destructive_subcommands() -> None:
    """secret-revoke は signed approval gate 対象 (Sprint Pack: DESTRUCTIVE_SUBCOMMANDS に追加)。"""
    assert "secret-revoke" in DESTRUCTIVE_SUBCOMMANDS


def test_secret_revoke_has_drill_kind() -> None:
    """signed approval を使う場合の drill_kind が存在する (subcommand allowlist)。"""
    assert "secret-revoke" in DRILL_KIND_ALLOWED_SUBCOMMANDS["secret_revoke"]


def test_secret_revoke_denied_without_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    """approval_id なし + non-automation manual で gate が deny → exit 2 (DESTRUCTIVE default deny)。"""
    # ambient automation env を strip して manual context にする
    for var in (
        "SYSTEMD_INVOCATION_ID", "INVOCATION_ID", "JOURNAL_STREAM", "CRON_INVOCATION",
        "GITHUB_ACTIONS", "CI", "BUILD_ID", "BUILD_NUMBER", "RUN_ID",
        "KUBERNETES_SERVICE_HOST", "container", "BASH_EXECUTION_STRING",
    ):
        monkeypatch.delenv(var, raising=False)
    args = argparse.Namespace(
        tenant_id=1,
        secret_ref_id="22222222-2222-2222-2222-222222222222",
        approval_id=None,
        from_automation=False,
        allow_unsigned_manual_skeleton=False,
        database_url=None,
    )
    rc = _cmd_secret_revoke(args)
    assert rc == 2  # gate denied before any DB work


def test_secret_revoke_skeleton_escape_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Workflow review HIGH: --allow-unsigned-manual-skeleton は secret-revoke で物理 deny → exit 2。

    secret-revoke は real-I/O destructive (revoke + material purge) なので skeleton 専用 escape で
    signed approval gate を bypass できてはならない (backup/restore と同 pattern、DB 到達前に early-reject)。
    """
    for var in (
        "SYSTEMD_INVOCATION_ID", "INVOCATION_ID", "JOURNAL_STREAM", "CRON_INVOCATION",
        "GITHUB_ACTIONS", "CI", "BUILD_ID", "BUILD_NUMBER", "RUN_ID",
        "KUBERNETES_SERVICE_HOST", "container", "BASH_EXECUTION_STRING",
    ):
        monkeypatch.delenv(var, raising=False)
    args = argparse.Namespace(
        tenant_id=1,
        secret_ref_id="22222222-2222-2222-2222-222222222222",
        approval_id=None,
        from_automation=False,
        allow_unsigned_manual_skeleton=True,  # escape を立てても deny
        database_url=None,
    )
    rc = _cmd_secret_revoke(args)
    assert rc == 2  # early-reject before any DB work (approval gate bypass 不可)


def test_require_approval_secret_revoke_escape_physically_denied() -> None:
    """Workflow review HIGH: require_approval_for_destructive が secret-revoke の escape を物理 deny。"""
    from scripts.taskhub_signed_approval import require_approval_for_destructive

    allowed, reason_code, _extras = require_approval_for_destructive(
        "secret-revoke",
        None,  # approval_id なし
        False,  # from_automation
        True,  # allow_unsigned_manual_skeleton (escape)
    )
    assert allowed is False
    assert reason_code == "taskhub_signed_approval_secret_revoke_allow_unsigned_skeleton_rejected"


def test_secret_revoke_invalid_uuid_returns_exit_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """approval gate 通過後でも secret-ref-id が UUID でなければ exit 2 (DB に到達しない)。"""
    monkeypatch.setattr(
        taskhub_admin, "_run_approval_gate", lambda *a, **k: (True, "ok"),
    )
    args = argparse.Namespace(
        tenant_id=1,
        secret_ref_id="not-a-uuid",
        approval_id=None,
        from_automation=False,
        allow_unsigned_manual_skeleton=False,
        database_url=None,
    )
    assert _cmd_secret_revoke(args) == 2


# --- helper importability ----------------------------------------------------


def test_lifecycle_helpers_importable() -> None:
    assert callable(create_secret)
    assert callable(rotate_secret)
    assert callable(revoke_secret)
