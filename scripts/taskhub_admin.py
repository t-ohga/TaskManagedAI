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
import json
import os
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
    """`taskhub backup --output <path> [--include-sops-env]` real orchestration.

    SP022-T02 Phase 1: signed approval gate (default deny + Phase 1 only escape の
    `--allow-unsigned-manual-skeleton` は backup では物理 deny、R2-F-001 adopt)。
    SP022-T02 Phase 2 / T08 batch 2: real backup orchestration (pg_dump / Redis / age)。
    """
    if not args.output:
        print("ERROR: --output <path> is required", file=sys.stderr)  # noqa: T201
        return 2

    # R2-F-001 adopt: backup では --allow-unsigned-manual-skeleton を物理 deny
    # (gate 内でも deny されるが、early reject で error message を明確化)
    if getattr(args, "allow_unsigned_manual_skeleton", False):
        print(  # noqa: T201
            "ERROR: --allow-unsigned-manual-skeleton is rejected for backup subcommand "
            "(real I/O requires signed approval, no skeleton escape allowed)",
            file=sys.stderr,
        )
        return 2

    # SP022-T02 Phase 2 / T08 batch 2: build BackupOptions + age public key fingerprint
    try:
        from scripts.taskhub_backup_orchestrator import (
            BackupOptions,
            BackupRuntimeError,
            BackupToolNotFoundError,
            BackupUsageError,
            run_backup,
        )
    except ModuleNotFoundError:
        _REPO_ROOT = Path(__file__).resolve().parent.parent
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        from scripts.taskhub_backup_orchestrator import (  # noqa: E402
            BackupOptions,
            BackupRuntimeError,
            BackupToolNotFoundError,
            BackupUsageError,
            run_backup,
        )

    repo_root = Path(__file__).resolve().parent.parent
    output_path = Path(args.output).resolve()
    backup_options = BackupOptions.from_environment(
        output_path=output_path,
        repo_root=repo_root,
        include_sops_env=args.include_sops_env,
        skip_service_stop=getattr(args, "skip_service_stop", False),
        overwrite=getattr(args, "overwrite", False),
    )

    # R2-F-001 adopt: build BackupApprovalClaim only when approval_id given
    # (age public key read を gate より前にしない、test 等で age key 不在の場合 gate 結果を verify するため)
    backup_claim = None
    if args.approval_id:
        from hashlib import sha256
        try:
            age_pub_bytes = backup_options.age_public_key_path.read_bytes()
            age_pub_fingerprint = sha256(age_pub_bytes).hexdigest()
        except OSError:
            print(  # noqa: T201
                f"ERROR: age public key not readable: {backup_options.age_public_key_path}",
                file=sys.stderr,
            )
            return 2
        from scripts.taskhub_signed_approval import BackupApprovalClaim
        backup_claim = BackupApprovalClaim(
            output_path=str(output_path),
            include_sops_env=backup_options.include_sops_env,
            skip_service_stop=backup_options.skip_service_stop,
            overwrite=backup_options.overwrite,
            age_public_key_fingerprint=age_pub_fingerprint,
        )

    # signed approval gate with backup_claim (R2-F-001 adopt)
    from scripts.taskhub_signed_approval import (
        emit_audit_event,
        require_approval_for_destructive,
    )
    allowed, reason, extras = require_approval_for_destructive(
        "backup",
        args.approval_id,
        getattr(args, "from_automation", False),
        getattr(args, "allow_unsigned_manual_skeleton", False),
        backup_claim=backup_claim,
    )
    emit_audit_event(reason, extras)
    if not allowed:
        print(  # noqa: T201
            f"ERROR: signed approval gate denied (reason={reason})",
            file=sys.stderr,
        )
        return 2

    # Real backup orchestration (SP022-T02 Phase 2 / T08 batch 2)
    try:
        result = run_backup(backup_options)
    except (BackupUsageError, BackupToolNotFoundError) as exc:
        print(exc.stderr_message(), file=sys.stderr)  # noqa: T201
        return 2
    except BackupRuntimeError as exc:
        print(exc.stderr_message(), file=sys.stderr)  # noqa: T201
        return 1
    print(json.dumps(result.summary(), sort_keys=True))  # noqa: T201
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    """`taskhub restore --input <path>.tar.age` real I/O orchestration / `--rollback` skeleton.

    SP022-T02 Phase 3 / T08 batch 3: real restore orchestration.
    24 rounds + 58 findings 100% adopt of codex-plan-review (CLAUDE.md §6.5.4).

    R3-F-001 adopt: `--allow-unsigned-manual-skeleton` は restore で物理 deny (signed approval
    + restore_claim 経由のみ).
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

    # R3-F-001 adopt: restore で --allow-unsigned-manual-skeleton は物理 deny
    if getattr(args, "allow_unsigned_manual_skeleton", False):
        print(  # noqa: T201
            "ERROR: --allow-unsigned-manual-skeleton is rejected for restore subcommand "
            "(real I/O requires signed approval + restore_claim, no skeleton escape allowed) "
            "[reason=taskhub_signed_approval_restore_allow_unsigned_skeleton_rejected]",
            file=sys.stderr,
        )
        return 2

    # --rollback は skeleton mode (real I/O は SP022-T02 Phase 4 carry-over)
    if args.rollback:
        # F-PR78-005 adopt: rollback skeleton は "restore-rollback" subcommand を使用
        # (restore_claim 必須化されていない別 subcommand、drill_kind 整合は維持)
        allowed, reason = _run_approval_gate("restore-rollback", args)
        if not allowed:
            print(  # noqa: T201
                f"ERROR: signed approval gate denied (reason={reason})",
                file=sys.stderr,
            )
            return 2
        print(  # noqa: T201
            _skeleton_message(
                "restore --rollback",
                details=(
                    f"Would rollback to pre-restore snapshot at "
                    f"data/_pre-restore-{args.rollback}/. "
                    "Real flow (Phase 4 carry-over): stop_app_services -> postgres-only restart -> "
                    "artifacts/DB/Redis snapshot 戻し -> service start."
                ),
            )
        )
        return 1  # skeleton mode

    # --input: real I/O orchestration
    input_path = Path(args.input)
    if not input_path.exists():
        print(  # noqa: T201
            f"ERROR: input backup file not found: {input_path}",
            file=sys.stderr,
        )
        return 2

    # SP022-T02 Phase 3: build RestoreApprovalClaim from CLI + env, run approval gate, run_restore
    try:
        from scripts.taskhub_restore_orchestrator import (
            RestoreOptions,
            RestoreRuntimeError,
            RestoreUsageError,
            run_restore,
        )
        from scripts.taskhub_signed_approval import (
            RestoreApprovalClaim,
            emit_audit_event,
            require_approval_for_destructive,
        )
    except ModuleNotFoundError:
        _REPO_ROOT = Path(__file__).resolve().parent.parent
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        from scripts.taskhub_restore_orchestrator import (  # noqa: E402
            RestoreOptions,
            RestoreRuntimeError,
            RestoreUsageError,
            run_restore,
        )
        from scripts.taskhub_signed_approval import (  # noqa: E402
            RestoreApprovalClaim,
            emit_audit_event,
            require_approval_for_destructive,
        )

    # CLI 起動時 .tar.age の archive sha256 を再計算 (R6-F-002 + R16-F-002 TOCTOU 排除前段)
    # immutable stage 経由は orchestrator 側で実行、ここでは claim 比較用の hash 取得のみ
    import hashlib
    h = hashlib.sha256()
    try:
        with input_path.open("rb") as f:
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                h.update(chunk)
    except OSError as exc:
        print(  # noqa: T201
            f"ERROR: input file read failed: {exc}",
            file=sys.stderr,
        )
        return 2
    cli_archive_sha256 = h.hexdigest()

    # age identity file (CLI > env)
    age_identity_str = args.age_identity_file or os.environ.get("TASKHUB_BACKUP_AGE_IDENTITY_FILE")
    if not age_identity_str:
        print(  # noqa: T201
            "ERROR: --age-identity-file is required (or set TASKHUB_BACKUP_AGE_IDENTITY_FILE env)",
            file=sys.stderr,
        )
        return 2

    # Restore target identity from env (production deployment specific、本 batch では env 経由)
    target_compose_project = os.environ.get(
        "TASKHUB_RESTORE_COMPOSE_PROJECT", "taskmanagedai",
    )
    repo_root = Path(__file__).resolve().parent.parent
    target_compose_file = Path(os.environ.get(
        "TASKHUB_RESTORE_COMPOSE_FILE", str(repo_root / "docker-compose.yml"),
    ))
    target_pg_host = os.environ.get("TASKHUB_RESTORE_PG_HOST", "127.0.0.1")
    target_pg_port = os.environ.get("TASKHUB_RESTORE_PG_PORT", "5432")
    target_pg_db = os.environ.get("TASKHUB_RESTORE_PG_DB", "taskhub")
    target_pg_user = os.environ.get("TASKHUB_RESTORE_PG_USER", "taskhub")
    target_redis_host = os.environ.get("TASKHUB_RESTORE_REDIS_HOST", "127.0.0.1")
    target_redis_port = os.environ.get("TASKHUB_RESTORE_REDIS_PORT", "6379")
    target_artifacts_dir = Path(os.environ.get(
        "TASKHUB_RESTORE_ARTIFACTS_DIR", str(repo_root / "data" / "artifacts"),
    )).resolve()
    target_artifacts_container_path = os.environ.get(
        "TASKHUB_RESTORE_ARTIFACTS_CONTAINER_PATH", "/app/data/artifacts",
    )
    expected_pg_major = os.environ.get("TASKHUB_RESTORE_EXPECTED_PG_MAJOR", "17")
    expected_alembic_head = os.environ.get("TASKHUB_RESTORE_EXPECTED_ALEMBIC_HEAD", "")

    if not expected_alembic_head:
        print(  # noqa: T201
            "ERROR: TASKHUB_RESTORE_EXPECTED_ALEMBIC_HEAD env required (claim integrity field)",
            file=sys.stderr,
        )
        return 2

    options = RestoreOptions(
        input_path=input_path.resolve(),
        archive_sha256=cli_archive_sha256,
        age_identity_file=Path(age_identity_str).resolve(),
        target_pg_dsn_components={
            "host": target_pg_host, "port": target_pg_port,
            "db": target_pg_db, "user": target_pg_user,
        },
        target_redis_endpoint=f"{target_redis_host}:{target_redis_port}",
        target_artifacts_dir=target_artifacts_dir,
        target_artifacts_container_path=target_artifacts_container_path,
        target_compose_project_name=target_compose_project,
        target_compose_file_path=target_compose_file,
        expected_postgres_major_version=expected_pg_major,
        expected_alembic_head=expected_alembic_head,
        overwrite=getattr(args, "overwrite", False),
    )

    # build RestoreApprovalClaim (CLI が approval issue 時の caller-supplied claim と一致 verify)
    restore_claim = None
    if args.approval_id:
        # age public key fingerprint (backup 整合の verify、operator が approval issue 時に同 hash を claim に書く)
        # F-PR78-001 adopt: silent fallback to "" は claim mismatch 確定 deny を生むため fail-fast に変更
        # `.pub` 探索 path: (a) {identity_file}.pub (e.g. age.key.pub) or env override TASKHUB_BACKUP_AGE_PUBLIC_KEY
        candidate_pub_paths = [
            Path(str(options.age_identity_file) + ".pub"),  # age.key → age.key.pub
            options.age_identity_file.with_suffix(".pub"),  # age.key → age.pub
        ]
        env_pub_override = os.environ.get("TASKHUB_BACKUP_AGE_PUBLIC_KEY")
        if env_pub_override:
            candidate_pub_paths.insert(0, Path(env_pub_override))
        age_pub_bytes: bytes | None = None
        tried_paths: list[Path] = []
        for cand in candidate_pub_paths:
            tried_paths.append(cand)
            try:
                age_pub_bytes = cand.read_bytes()
                break
            except OSError:
                continue
        if age_pub_bytes is None:
            print(  # noqa: T201
                f"ERROR: age public key not readable (claim integrity requires fingerprint). "
                f"Set TASKHUB_BACKUP_AGE_PUBLIC_KEY or ensure {tried_paths[0]} exists. "
                f"Tried: {[str(p) for p in tried_paths]}",
                file=sys.stderr,
            )
            return 2
        age_pub_fingerprint = hashlib.sha256(age_pub_bytes).hexdigest()
        restore_claim = RestoreApprovalClaim(
            input_path=str(options.input_path),
            archive_sha256=cli_archive_sha256,
            age_public_key_fingerprint=age_pub_fingerprint,
            target_pg_dsn_components=dict(options.target_pg_dsn_components),
            target_redis_endpoint=options.target_redis_endpoint,
            target_artifacts_dir=str(options.target_artifacts_dir),
            target_artifacts_container_path=options.target_artifacts_container_path,
            target_compose_project_name=options.target_compose_project_name,
            target_compose_file_path=str(options.target_compose_file_path),
            expected_postgres_major_version=options.expected_postgres_major_version,
            expected_alembic_head=options.expected_alembic_head,
            skip_service_stop=False,  # R3-F-001 物理 deny 済、claim でも False 固定
        )

    # signed approval gate with restore_claim
    allowed, reason, extras = require_approval_for_destructive(
        "restore",
        args.approval_id,
        getattr(args, "from_automation", False),
        getattr(args, "allow_unsigned_manual_skeleton", False),
        restore_claim=restore_claim,
    )
    emit_audit_event(reason, extras)
    if not allowed:
        print(  # noqa: T201
            f"ERROR: signed approval gate denied (reason={reason})",
            file=sys.stderr,
        )
        return 2

    # Real restore orchestration (SP022-T02 Phase 3)
    try:
        result = run_restore(options)
    except RestoreUsageError as exc:
        print(exc.stderr_message(), file=sys.stderr)  # noqa: T201
        return 2
    except RestoreRuntimeError as exc:
        print(exc.stderr_message(), file=sys.stderr)  # noqa: T201
        return 1
    print(json.dumps(result.summary(), sort_keys=True))  # noqa: T201
    return 0


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


def _cmd_verify_signed_journal(args: argparse.Namespace) -> int:
    """SP022-T08 batch 1: signed journal offline JSONL verification mode."""
    # dual import (direct-script + console_script)、R2-F-001 adopt scope
    try:
        from scripts.taskhub_signed_journal_offline import (
            DEFAULT_MAX_ENTRIES,
            DEFAULT_MAX_LINE_BYTES,
            SignedJournalUsageError,
            verify_jsonl_signed_journal,
        )
    except ModuleNotFoundError:
        _REPO_ROOT = Path(__file__).resolve().parent.parent
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        from scripts.taskhub_signed_journal_offline import (  # noqa: E402
            DEFAULT_MAX_ENTRIES,
            DEFAULT_MAX_LINE_BYTES,
            SignedJournalUsageError,
            verify_jsonl_signed_journal,
        )
    if not args.input:
        print(  # noqa: T201
            "ERROR: --signed-journal requires --input <path>.jsonl (or '-' for stdin)",
            file=sys.stderr,
        )
        return 2
    try:
        result = verify_jsonl_signed_journal(
            args.input,
            expected_final_hash=args.expected_final_hash,
            max_entries=args.max_entries if args.max_entries is not None else DEFAULT_MAX_ENTRIES,
            max_line_bytes=args.max_line_bytes if args.max_line_bytes is not None else DEFAULT_MAX_LINE_BYTES,
        )
    except SignedJournalUsageError as exc:
        print(exc.stderr_message(), file=sys.stderr)  # noqa: T201
        return 2
    print(json.dumps(result, sort_keys=True))  # noqa: T201
    if result.get("tamper_detected"):
        return 1
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    """`taskhub verify [--integrity] [--network-invariant] [--multi-agent]` skeleton + signed-journal offline mode."""
    # R2-F-002 adopt: parse-time validation で --signed-journal を skeleton flags と排他化
    # (argparse mutually_exclusive_group は既存 --integrity --network-invariant 併用 test を破壊するため)
    skeleton_flags_present = any([
        args.integrity, args.network_invariant, args.multi_agent,
    ])
    if args.signed_journal and skeleton_flags_present:
        print(  # noqa: T201
            "ERROR: --signed-journal は --integrity / --network-invariant / "
            "--multi-agent と併用不可 (real I/O mode と skeleton mode は排他)",
            file=sys.stderr,
        )
        return 2

    # SP022-T08 batch 1: signed-journal offline mode (real I/O)
    if args.signed_journal:
        return _cmd_verify_signed_journal(args)

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
    # SP022-T02 Phase 2 / T08 batch 2: real I/O 新引数
    sub_backup.add_argument(
        "--skip-service-stop",
        action="store_true",
        help=(
            "skip docker compose service stop step (test/dev env only、"
            "production drill では使用禁止、warning audit に emit)"
        ),
    )
    sub_backup.add_argument(
        "--overwrite",
        action="store_true",
        help="overwrite existing --output file (default False、accidental loss 防止)",
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
            "(data/_pre-restore-<ts>/ 経路、排他: --input、skeleton mode のみ)"
        ),
    )
    # SP022-T02 Phase 3: real I/O restore で必須の追加 args
    sub_restore.add_argument(
        "--age-identity-file",
        type=str,
        default=None,
        help=(
            "absolute path to age private key file (TASKHUB_BACKUP_AGE_IDENTITY_FILE env override 可能)。"
            "file は 0o400 or 0o600 permission + 非 symlink。real I/O restore 必須。"
        ),
    )
    sub_restore.add_argument(
        "--overwrite",
        action="store_true",
        help="overwrite existing artifacts dir (default False、accidental loss 防止)",
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
    # SP022-T08 batch 1: signed journal offline JSONL verification mode (real I/O、非 skeleton)
    sub_verify.add_argument(
        "--signed-journal",
        action="store_true",
        help=(
            "signed journal hash chain verification (SP022-T08 batch 1、"
            "offline JSONL mode、real I/O)"
        ),
    )
    sub_verify.add_argument(
        "--input",
        type=str,
        default=None,
        help="JSONL file path (or '-' for stdin)。--signed-journal と組合せ必須",
    )
    sub_verify.add_argument(
        "--expected-final-hash",
        type=str,
        default=None,
        help=(
            "expected SHA-256 hex (64 chars lowercase、^[0-9a-f]{64}$)。"
            "computed final_hash と比較、不一致なら exit 1 tamper detection"
        ),
    )
    sub_verify.add_argument(
        "--max-entries",
        type=int,
        default=None,
        help="JSONL entries 上限 (default 100000、range 1-100000、DoS 防御)",
    )
    sub_verify.add_argument(
        "--max-line-bytes",
        type=int,
        default=None,
        help="JSONL 1 行最大バイト数 (default 65536、range 1024-1048576、DoS 防御)",
    )
    sub_verify.set_defaults(func=_cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
