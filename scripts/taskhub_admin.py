#!/usr/bin/env python3
"""taskhub admin CLI (Sprint 12 batch 7、ADR-00021 §3 host-portable deployment).

Sprint 12 batch 7 では **subcommand structure + exit code contract** のみ
確立。real backup / restore / migrate / age-rotate / verify の I/O 実装は
user 物理 drill phase で配備.

Subcommands (ADR-00021 §3 table + §11/§14 hardening + §11.5 multi-agent fixture):
- `taskhub init --host <name> --tailnet <ts.net>`: skeleton (target host bootstrap、§3 line 151)
- `taskhub backup --output <path> [--include-sops-env]`: skeleton (drill 起点、§11.1 PG-F-015
  hardening: SOPS-encrypted env のみ、age private key は絶対含まない、旧 --include-secrets 名は fail)
- `taskhub freeze --reason <text>`: skeleton (split-brain prevention、§11.2 / §14.1、source host
  を signed freeze marker で down、thaw 明示まで再活性化禁止)
- `taskhub thaw [--decommission-target]`: skeleton (2-party-control + active-registry verify、§670)
- `taskhub active-registry`: skeleton (signed local ledger or closed-network shared 状態、
  source/target 同時 active reject contract、§670 PGA-F-003)
- `taskhub restore --input <path> | --rollback <pre-restore-ts>`: skeleton (restore + rollback
  両モード、§290 / §299 rollback 経路)
- `taskhub migrate --target <hostname>`: skeleton (one-shot host migration)
- `taskhub status [--age-safety] [--mac-preflight] [--remote <host>]`: skeleton (host status
  + §14.1 age-safety drill + §14.2 mac-preflight + split-brain remote check)
- `taskhub age-rotate`: skeleton (key rotation + SOPS re-encrypt)
- `taskhub verify [--integrity] [--network-invariant] [--multi-agent]`: skeleton
  (--multi-agent は ADR-00021 §11.5 multi-agent table restore 整合性 fixture)

CRITICAL invariants (本 batch では skeleton message のみで verify):
- closed-network invariant (ADR-00007 参照)
- age key 安全運搬 SOP (ADR-00021 §5 参照、git / cloud / DM 経路禁止)
- service stop -> volume move -> restore -> healthcheck (ADR-00021 §3 flow)
- 失敗時は元 volume に戻す (atomic restore invariant)

Usage:
    uv run python scripts/taskhub_admin.py <subcommand> [args]

Exit code:
    0: clean
    1: skeleton mode (real I/O not implemented in batch 7)
    2: CLI usage error
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# R2-F-001 adopt: dual import (direct-script `python scripts/taskhub_admin.py` と
# console_script `uv run taskhub` の両方で動かす)
# direct-script では sys.path[0]=scripts/ なので、parent (repo root) を append してから再 import
try:
    from scripts.taskhub_signed_approval import (
        emit_audit_event,
        require_approval_for_destructive,
    )
except ModuleNotFoundError:
    _REPO_ROOT = Path(__file__).resolve().parent.parent
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from scripts.taskhub_signed_approval import (  # noqa: E402
        emit_audit_event,
        require_approval_for_destructive,
    )


def _skeleton_message(subcommand: str, details: str = "") -> str:
    """skeleton mode の info message (real I/O は user 物理 drill phase で配備)."""
    lines = [
        f"[SKELETON] taskhub {subcommand}",
        "Sprint 12 batch 7: subcommand structure + exit code contract のみ確立。",
        "Real I/O implementation is deferred to user physical drill phase",
        "(host migration / backup restore drill、ADR-00021 §8 schedule).",
    ]
    if details:
        lines.append("")
        lines.append(f"Details: {details}")
    lines.append("")
    lines.append("Refs:")
    lines.append("  - docs/adr/00021_host_portable_deployment.md §3 (CLI table)")
    lines.append("  - docs/adr/00021_host_portable_deployment.md §5 (age key SOP)")
    lines.append("  - docs/adr/00021_host_portable_deployment.md §8 (drill schedule)")
    return "\n".join(lines)


def _run_approval_gate(
    subcommand: str, args: argparse.Namespace, *, target_host: str | None = None,
) -> tuple[bool, str]:
    """SP022-T02 Phase 1 signed approval pre-execution gate (R1-F-002 + R3-F-001 adopt).

    Default deny for destructive subcommands. Returns (allowed, reason_code) and
    emits redacted audit-line scaffold to stderr.
    """
    approval_id = getattr(args, "approval_id", None)
    from_automation = getattr(args, "from_automation", False)
    allow_unsigned_manual_skeleton = getattr(args, "allow_unsigned_manual_skeleton", False)
    allowed, reason, extras = require_approval_for_destructive(
        subcommand,
        approval_id,
        from_automation,
        allow_unsigned_manual_skeleton,
        target_host=target_host,
    )
    emit_audit_event(reason, extras)
    return allowed, reason


def _cmd_init(args: argparse.Namespace) -> int:
    """`taskhub init --host <name> --tailnet <ts.net>` skeleton (target host bootstrap).

    ADR-00021 §3 line 151 で host migration drill の step 4 (target host で
    `taskhub init`) として明示、新 host 初回 setup の起点 CLI.
    """
    if not args.host:
        print("ERROR: --host <name> is required", file=sys.stderr)  # noqa: T201
        return 2
    if not args.tailnet:
        print("ERROR: --tailnet <ts.net> is required", file=sys.stderr)  # noqa: T201
        return 2
    print(  # noqa: T201
        _skeleton_message(
            "init",
            details=(
                f"Would bootstrap target host {args.host} (tailnet {args.tailnet}). "
                "Real flow: Docker volume 作成 -> age key 生成 (existing なら skip) "
                "-> closed-network serve config 設定 -> .env.example から "
                ".env.encrypted 雛形生成."
            ),
        )
    )
    return 1  # skeleton mode


def _cmd_backup(args: argparse.Namespace) -> int:
    """`taskhub backup --output <path> [--include-sops-env]` skeleton (drill 起点).

    ADR-00021 §11.1 PG-F-015 hardening: 旧 `--include-secrets` を
    `--include-sops-env` に rename. SOPS-encrypted .env のみを含め、age private
    key は絶対含めない (CI test で verify 予定).

    SP022-T02 Phase 1: signed approval pre-execution gate (default deny).
    """
    allowed, reason = _run_approval_gate("backup", args)
    if not allowed:
        print(  # noqa: T201
            f"ERROR: signed approval gate denied (reason={reason})",
            file=sys.stderr,
        )
        return 2
    if not args.output:
        print("ERROR: --output <path> is required", file=sys.stderr)  # noqa: T201
        return 2
    suffix = " (with SOPS-encrypted .env)" if args.include_sops_env else ""
    print(  # noqa: T201
        _skeleton_message(
            "backup",
            details=(
                f"Would create age-encrypted backup at {args.output}{suffix}. "
                "Real flow: graceful service stop -> pg_dump + Redis BGSAVE + "
                "artifacts tar (+ optional SOPS-encrypted .env、age private key は "
                "絶対含まない) -> age 公開鍵で暗号化 -> .tar.age 出力."
            ),
        )
    )
    return 1  # skeleton mode


def _cmd_restore(args: argparse.Namespace) -> int:
    """`taskhub restore --input <path>.tar.age | --rollback <pre-restore-ts>` skeleton.

    ADR-00021 §290 / §299: restore 失敗時に `data/_pre-restore-<ts>/` から旧 volume を
    復旧する rollback mode (`--rollback <pre-restore-ts>`) を併設 (Codex R4 F-PR63-011 adopt).
    `--input` と `--rollback` は排他.

    SP022-T02 Phase 1: signed approval pre-execution gate (default deny).
    Phase 1 では `target_host` claim は未実装 (R2-F-003 adopt、Phase 2 で `--target-host` 追加判断).
    Input validation (mutex / required / missing file) is performed BEFORE the gate
    so that argparse-level usage errors take precedence over approval gate denial.
    """
    if args.input and args.rollback:
        print(  # noqa: T201
            "ERROR: --input と --rollback は排他 (同時指定不可)",
            file=sys.stderr,
        )
        return 2
    if not args.input and not args.rollback:
        print(  # noqa: T201
            "ERROR: --input <path>.tar.age または --rollback <pre-restore-ts> "
            "のいずれかが必須",
            file=sys.stderr,
        )
        return 2

    # CLI usage validation (file-existence check) — gate runs AFTER (R2-F-002 adopt):
    # existing tests expect "input backup file not found" stderr for missing input
    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            print(  # noqa: T201
                f"ERROR: input backup file not found: {input_path}",
                file=sys.stderr,
            )
            return 2

    # signed approval gate (after all input validation)
    allowed, reason = _run_approval_gate("restore", args)
    if not allowed:
        print(  # noqa: T201
            f"ERROR: signed approval gate denied (reason={reason})",
            file=sys.stderr,
        )
        return 2

    if args.rollback:
        print(  # noqa: T201
            _skeleton_message(
                "restore --rollback",
                details=(
                    f"Would rollback to pre-restore snapshot at "
                    f"data/_pre-restore-{args.rollback}/. "
                    "Real flow: service stop -> 旧 volume を data/_pre-restore-<ts>/ "
                    "から現役 path に戻す -> service up + healthcheck."
                ),
            )
        )
        return 1  # skeleton mode

    input_path = Path(args.input)
    print(  # noqa: T201
        _skeleton_message(
            "restore",
            details=(
                f"Would restore from {input_path} (age-encrypted tar). "
                "Real flow: age 復号 -> service stop -> volume move -> "
                "pg_restore + Redis import + artifacts 配置 -> alembic check -> "
                "healthcheck -> 失敗時 rollback."
            ),
        )
    )
    return 1  # skeleton mode


def _cmd_migrate(args: argparse.Namespace) -> int:
    """`taskhub migrate --target <hostname> [--via <transport>]` skeleton.

    SP022-T02 Phase 1: signed approval pre-execution gate (default deny) with
    target_host claim 厳密化 (R2-F-003 adopt: CLI --target と record.target_host 両方
    non-empty + strip 後 exact match).
    """
    # gate は --target argparse 必須 check 前に走る (signature check 統合)
    allowed, reason = _run_approval_gate("migrate", args, target_host=args.target)
    if not allowed:
        print(  # noqa: T201
            f"ERROR: signed approval gate denied (reason={reason})",
            file=sys.stderr,
        )
        return 2
    if not args.target:
        print("ERROR: --target <hostname> is required", file=sys.stderr)  # noqa: T201
        return 2
    print(  # noqa: T201
        _skeleton_message(
            "migrate",
            details=(
                f"Would migrate to {args.target} (via {args.via}). "
                "Real flow: backup -> closed-network transfer -> "
                "target host で taskhub restore -> 旧 host backup 別 path 保管 "
                "(6 ヶ月 rollback)."
            ),
        )
    )
    return 1  # skeleton mode


def _cmd_status(args: argparse.Namespace) -> int:
    """`taskhub status [--age-safety] [--mac-preflight] [--remote <host>]` skeleton.

    ADR-00021 §14.1 PGA-F-001 (age key 安全運搬 drill: `--age-safety`) + §14.2
    PGA-F-006 (Mac runtime preflight: `--mac-preflight`) + §285 split-brain
    prevention (`--remote <old-host>` で旧 host service down 確認) を追加
    (Codex R4 F-PR63-008 adopt).
    """
    extras: list[str] = []
    if args.age_safety:
        extras.append(
            "--age-safety (§14.1 PGA-F-001: FileVault / cloud-sync exclusion / "
            "permission 600 verify)"
        )
    if args.mac_preflight:
        extras.append(
            "--mac-preflight (§14.2 PGA-F-006: pmset -g から sleep / powernap / "
            "wakeonlan setting を hard fail check)"
        )
    if args.remote:
        extras.append(
            f"--remote {args.remote} (§285 split-brain check: 旧 host service down 確認)"
        )

    base_detail = (
        "Would display: host name / Docker service health / data size "
        "(PostgreSQL / Redis / artifacts) / last backup timestamp / "
        "age key fingerprint / SOPS validity / closed-network serve URL."
    )
    detail = base_detail
    if extras:
        detail = f"{base_detail} Additional checks: {', '.join(extras)}"

    print(  # noqa: T201
        _skeleton_message("status", details=detail)
    )
    return 1


def _cmd_freeze(args: argparse.Namespace) -> int:
    """`taskhub freeze --reason <text>` skeleton (split-brain prevention、§11.2).

    SP022-T02 Phase 1: signed approval pre-execution gate (default deny).
    """
    allowed, reason_code = _run_approval_gate("freeze", args)
    if not allowed:
        print(  # noqa: T201
            f"ERROR: signed approval gate denied (reason={reason_code})",
            file=sys.stderr,
        )
        return 2
    if not args.reason:
        print("ERROR: --reason <text> is required", file=sys.stderr)  # noqa: T201
        return 2
    print(  # noqa: T201
        _skeleton_message(
            "freeze",
            details=(
                f"Would create signed freeze marker (reason: {args.reason!r}). "
                "Real flow: service stop + signed freeze marker file 生成 -> "
                "再活性化は明示の `taskhub thaw` のみ (auto thaw なし、§11.2)."
            ),
        )
    )
    return 1  # skeleton mode


def _cmd_thaw(args: argparse.Namespace) -> int:
    """`taskhub thaw [--decommission-target]` skeleton (§670 2-party-control).

    SP022-T02 Phase 1: signed approval pre-execution gate (default deny).
    """
    allowed, reason_code = _run_approval_gate("thaw", args)
    if not allowed:
        print(  # noqa: T201
            f"ERROR: signed approval gate denied (reason={reason_code})",
            file=sys.stderr,
        )
        return 2
    flag = (
        " (--decommission-target に伴う target active marker 削除)"
        if args.decommission_target
        else ""
    )
    print(  # noqa: T201
        _skeleton_message(
            "thaw",
            details=(
                f"Would verify thaw preflight{flag}. "
                "Real flow: target active.signed marker + migration_epoch + "
                "source_host_id + decommission marker verify -> 同時 active なら "
                "default deny (再活性化は --decommission-target + 別 actor approval 必要)、"
                "OK なら freeze marker 解除 + service up."
            ),
        )
    )
    return 1  # skeleton mode


def _cmd_active_registry(args: argparse.Namespace) -> int:
    """`taskhub active-registry` skeleton (signed local ledger、§670 PGA-F-003)."""
    del args
    print(  # noqa: T201
        _skeleton_message(
            "active-registry",
            details=(
                "Would print signed active ledger entries "
                "(host_id / migration_epoch / active.signed marker mtime / "
                "decommission marker). "
                "Contract: source/target 同時 active は reject (split-brain 防止)."
            ),
        )
    )
    return 1  # skeleton mode


def _cmd_age_rotate(args: argparse.Namespace) -> int:
    """`taskhub age-rotate` skeleton.

    CRITICAL: age key rotation は user 物理運搬必須 (ADR-00021 §5 SOP).
    本 skeleton は info message のみ、実 rotation は user drill phase で配備.

    SP022-T02 Phase 1: signed approval pre-execution gate (default deny).
    """
    allowed, reason_code = _run_approval_gate("age-rotate", args)
    if not allowed:
        print(  # noqa: T201
            f"ERROR: signed approval gate denied (reason={reason_code})",
            file=sys.stderr,
        )
        return 2
    print(  # noqa: T201
        _skeleton_message(
            "age-rotate",
            details=(
                "Would rotate age key: 旧 key deprecated 化 -> 新 key 生成 -> "
                ".env.encrypted SOPS re-encrypt -> 旧 key を "
                "~/.taskhub/age/deprecated/ に保管. "
                "User 物理運搬 SOP は ADR-00021 §5 を参照 "
                "(git / cloud / DM 禁止)."
            ),
        )
    )
    return 1


def _cmd_verify(args: argparse.Namespace) -> int:
    """`taskhub verify [--integrity] [--network-invariant] [--multi-agent]` skeleton."""
    checks: list[str] = []
    if args.integrity:
        checks.append("--integrity (row count / checksum / Redis count / alembic check)")
    if args.network_invariant:
        checks.append(
            "--network-invariant (closed-network serve / host-internal bind / "
            "no external ingress per ADR-00007)"
        )
    if args.multi_agent:
        checks.append(
            "--multi-agent (ADR-00021 §11.5 multi-agent table restore 整合性: "
            "inter_agent_messages / memory_retrieval_artifacts / "
            "project_agent_roles / review_artifacts / agent_runs)"
        )
    if not checks:
        print(  # noqa: T201
            "ERROR: at least one of --integrity / --network-invariant / "
            "--multi-agent required",
            file=sys.stderr,
        )
        return 2

    print(  # noqa: T201
        _skeleton_message(
            "verify",
            details=f"Would run: {', '.join(checks)}",
        )
    )
    return 1


def _add_signed_approval_args(parser: argparse.ArgumentParser) -> None:
    """SP022-T02 Phase 1 signed approval CLI args (destructive subcommand 用).

    R1-F-002 + R3-F-001 adopt: default deny + skeleton-only escape (Phase 2 で削除予定).
    """
    parser.add_argument(
        "--approval-id",
        type=str,
        default=None,
        help=(
            "signed approval ID (~/.taskhub/approvals/<id>.signed)。"
            "automation 実行時は必須、手動実行も default deny (escape は "
            "`--allow-unsigned-manual-skeleton`)"
        ),
    )
    parser.add_argument(
        "--from-automation",
        action="store_true",
        help=(
            "automation (cron/systemd/CI) 経由実行を明示。"
            "signed approval ID と組合せ必須"
        ),
    )
    parser.add_argument(
        "--allow-unsigned-manual-skeleton",
        action="store_true",
        help=(
            "(Phase 1 only、Phase 2 削除予定) skeleton mode の手動実行で approval gate を "
            "escape。default deny を override する旨を audit に記録"
        ),
    )


def _build_parser() -> argparse.ArgumentParser:
    # ADR-00021 §3 + SP-012 §128 drill command (`taskhub backup`, `taskhub migrate`,
    # 等) と整合させるため、parser prog 名は console_script entry point の
    # `taskhub` に固定 (Codex R3 F-PR63-005 P3 adopt).
    parser = argparse.ArgumentParser(
        prog="taskhub",
        description=(
            "taskhub admin CLI (Sprint 12 batch 7 skeleton、ADR-00021 §3). "
            "Real I/O is deferred to user physical drill phase."
        ),
    )
    subparsers = parser.add_subparsers(
        dest="subcommand",
        required=True,
        title="subcommands",
    )

    sub_init = subparsers.add_parser(
        "init",
        help="bootstrap target host (Docker volume + age key + serve config)",
    )
    sub_init.add_argument(
        "--host",
        type=str,
        required=True,
        help="host name to bootstrap",
    )
    sub_init.add_argument(
        "--tailnet",
        type=str,
        required=True,
        help="closed-network tailnet domain (e.g. tail-xxxxx.ts.net)",
    )
    sub_init.set_defaults(func=_cmd_init)

    sub_backup = subparsers.add_parser(
        "backup",
        help="create age-encrypted backup tar (drill 起点、ADR-00021 §3)",
    )
    sub_backup.add_argument(
        "--output",
        type=str,
        required=True,
        help="output path for .tar.age backup file",
    )
    sub_backup.add_argument(
        "--include-sops-env",
        action="store_true",
        help=(
            "include SOPS-encrypted .env only (default: false). "
            "ADR-00021 §11.1 PG-F-015: age private key は絶対含めない、"
            "旧 --include-secrets 名は廃止 (fail に分類)"
        ),
    )
    sub_backup.set_defaults(func=_cmd_backup)
    _add_signed_approval_args(sub_backup)

    sub_restore = subparsers.add_parser(
        "restore",
        help="restore from backup file (age-encrypted tar) or rollback pre-restore snapshot",
    )
    # ADR-00021 §290 / §299: --rollback <pre-restore-ts> mode を併設 (--input と排他)
    sub_restore.add_argument(
        "--input",
        type=str,
        default=None,
        help="path to .tar.age backup file (排他: --rollback)",
    )
    sub_restore.add_argument(
        "--rollback",
        type=str,
        default=None,
        help=(
            "rollback to pre-restore snapshot timestamp "
            "(data/_pre-restore-<ts>/ 経路、排他: --input)"
        ),
    )
    sub_restore.set_defaults(func=_cmd_restore)
    _add_signed_approval_args(sub_restore)

    sub_freeze = subparsers.add_parser(
        "freeze",
        help="create signed freeze marker (split-brain prevention、ADR-00021 §11.2)",
    )
    sub_freeze.add_argument(
        "--reason",
        type=str,
        required=True,
        help="reason text for signed freeze marker (audit trail)",
    )
    sub_freeze.set_defaults(func=_cmd_freeze)
    _add_signed_approval_args(sub_freeze)

    sub_thaw = subparsers.add_parser(
        "thaw",
        help="release freeze with 2-party-control + active-registry verify (ADR-00021 §670)",
    )
    sub_thaw.add_argument(
        "--decommission-target",
        action="store_true",
        help=(
            "remove target active marker before thaw "
            "(2-party-control + 別 actor approval が必要)"
        ),
    )
    sub_thaw.set_defaults(func=_cmd_thaw)
    _add_signed_approval_args(sub_thaw)

    sub_active_registry = subparsers.add_parser(
        "active-registry",
        help="print signed active ledger (source/target 同時 active reject contract、§670)",
    )
    sub_active_registry.set_defaults(func=_cmd_active_registry)

    sub_migrate = subparsers.add_parser(
        "migrate",
        help="migrate data to another host (one-shot host migration)",
    )
    sub_migrate.add_argument(
        "--target", type=str, required=True, help="target hostname"
    )
    sub_migrate.add_argument(
        "--via",
        type=str,
        default="tailscale",
        choices=["tailscale", "scp"],
        help="transport (default: tailscale); see ADR-00021 §3 + SP-012 drill section",
    )
    sub_migrate.set_defaults(func=_cmd_migrate)
    _add_signed_approval_args(sub_migrate)

    sub_status = subparsers.add_parser(
        "status",
        help="show host status + service health + data size + last backup",
    )
    sub_status.add_argument(
        "--age-safety",
        action="store_true",
        help=(
            "verify age key safety (FileVault / cloud-sync exclusion / "
            "permission 600) per ADR-00021 §14.1 PGA-F-001"
        ),
    )
    sub_status.add_argument(
        "--mac-preflight",
        action="store_true",
        help=(
            "verify Mac runtime preflight (sleep / powernap / wakeonlan) "
            "per ADR-00021 §14.2 PGA-F-006"
        ),
    )
    sub_status.add_argument(
        "--remote",
        type=str,
        default=None,
        help=(
            "verify remote host service down (split-brain check) "
            "per ADR-00021 §285"
        ),
    )
    sub_status.set_defaults(func=_cmd_status)

    sub_age_rotate = subparsers.add_parser(
        "age-rotate",
        help="rotate age key + SOPS re-encrypt (user 物理運搬 SOP 必須)",
    )
    sub_age_rotate.set_defaults(func=_cmd_age_rotate)
    _add_signed_approval_args(sub_age_rotate)

    sub_verify = subparsers.add_parser(
        "verify",
        help="verify integrity + network invariant",
    )
    sub_verify.add_argument(
        "--integrity",
        action="store_true",
        help="run row count / checksum / Redis count / alembic check",
    )
    sub_verify.add_argument(
        "--network-invariant",
        action="store_true",
        help="verify closed-network serve, host-internal bind, no external ingress",
    )
    sub_verify.add_argument(
        "--multi-agent",
        action="store_true",
        help=(
            "verify multi-agent table restore integrity per ADR-00021 §11.5 "
            "(inter_agent_messages / memory_retrieval_artifacts / "
            "project_agent_roles / review_artifacts / agent_runs)"
        ),
    )
    sub_verify.set_defaults(func=_cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
