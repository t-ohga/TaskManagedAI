#!/usr/bin/env python3
"""taskhub admin CLI (Sprint 12 batch 7、ADR-00021 §3 host-portable deployment).

Sprint 12 batch 7 では **subcommand structure + exit code contract** のみ
確立。real backup / restore / migrate / age-rotate / verify の I/O 実装は
user 物理 drill phase で配備.

Subcommands (ADR-00021 §3 table + §11.5 multi-agent fixture):
- `taskhub backup --output <path> [--include-secrets]`: skeleton (drill 起点)
- `taskhub restore --input <path>`: skeleton
- `taskhub migrate --target <hostname>`: skeleton (one-shot host migration)
- `taskhub status`: skeleton (host status / service health / data size)
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


def _cmd_backup(args: argparse.Namespace) -> int:
    """`taskhub backup --output <path> [--include-secrets]` skeleton (drill 起点)."""
    if not args.output:
        print("ERROR: --output <path> is required", file=sys.stderr)  # noqa: T201
        return 2
    suffix = " (with .env.encrypted)" if args.include_secrets else ""
    print(  # noqa: T201
        _skeleton_message(
            "backup",
            details=(
                f"Would create age-encrypted backup at {args.output}{suffix}. "
                "Real flow: graceful service stop -> pg_dump + Redis BGSAVE + "
                "artifacts tar (+ optional .env.encrypted) -> age 公開鍵で暗号化 "
                "-> .tar.age 出力."
            ),
        )
    )
    return 1  # skeleton mode


def _cmd_restore(args: argparse.Namespace) -> int:
    """`taskhub restore --input <path>.tar.age` skeleton."""
    if not args.input:
        print("ERROR: --input <path>.tar.age is required", file=sys.stderr)  # noqa: T201
        return 2
    input_path = Path(args.input)
    if not input_path.exists():
        print(  # noqa: T201
            f"ERROR: input backup file not found: {input_path}",
            file=sys.stderr,
        )
        return 2
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
    """`taskhub migrate --target <hostname> [--via <transport>]` skeleton."""
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
    """`taskhub status` skeleton."""
    del args
    print(  # noqa: T201
        _skeleton_message(
            "status",
            details=(
                "Would display: host name / Docker service health / data size "
                "(PostgreSQL / Redis / artifacts) / last backup timestamp / "
                "age key fingerprint / SOPS validity / closed-network serve URL."
            ),
        )
    )
    return 1


def _cmd_age_rotate(args: argparse.Namespace) -> int:
    """`taskhub age-rotate` skeleton.

    CRITICAL: age key rotation は user 物理運搬必須 (ADR-00021 §5 SOP).
    本 skeleton は info message のみ、実 rotation は user drill phase で配備.
    """
    del args
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskhub_admin",
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
        "--include-secrets",
        action="store_true",
        help="include .env.encrypted in backup (default: false)",
    )
    sub_backup.set_defaults(func=_cmd_backup)

    sub_restore = subparsers.add_parser(
        "restore",
        help="restore from backup file (age-encrypted tar)",
    )
    sub_restore.add_argument(
        "--input",
        type=str,
        required=True,
        help="path to .tar.age backup file",
    )
    sub_restore.set_defaults(func=_cmd_restore)

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

    sub_status = subparsers.add_parser(
        "status",
        help="show host status + service health + data size + last backup",
    )
    sub_status.set_defaults(func=_cmd_status)

    sub_age_rotate = subparsers.add_parser(
        "age-rotate",
        help="rotate age key + SOPS re-encrypt (user 物理運搬 SOP 必須)",
    )
    sub_age_rotate.set_defaults(func=_cmd_age_rotate)

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
