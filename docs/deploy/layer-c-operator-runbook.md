# Layer C Operator Runbook

Date: 2026-05-22
Scope: Mac single-host functional smoke and CLI drill handoff for SP-022-1.

This runbook complements `docs/deploy/mac-single-host-smoke-sop.md` Layer C.
It is operator-facing and intentionally keeps destructive actions behind signed
approval records.

## §1 Service Startup Sequence

Start services in dependency order:

1. `postgres`
2. `redis`
3. `api`
4. `worker`
5. `frontend`

Command:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.yml \
  --env-file .env.local \
  up -d postgres redis api worker frontend
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.yml \
  --env-file .env.local \
  ps
```

Expected:

- `postgres` and `redis` are healthy before `api` and `worker`.
- `api` responds on `http://127.0.0.1:8000/healthz`.
- `frontend` responds on `http://127.0.0.1:3900`.

## §2 Backup Orchestrator Manual Invocation

Backup requires a signed `BackupApprovalClaim`; unsigned skeleton escape is
rejected. Use operator-runbook §2.1 to issue the approval record first.

Command:

```bash
uv run taskhub backup \
  --approval-id "$BACKUP_APPROVAL_ID" \
  --output "$HOME/.taskhub/backups/layer-c-smoke.tar.age" \
  --include-sops-env \
  --skip-service-stop
```

Expected:

- `backup_runtime_binding_fingerprint` is present in the signed record.
- Missing `.env.encrypted` is reported as `backup_sops_env_skipped`, not as a
  plaintext secret inclusion.
- Archive contains `meta.json`, `checksums.txt`, `postgres/pg_dump.dump`,
  `postgres/alembic_version.txt`, `redis/dump.rdb`, and `artifacts/`.

## §3 Restore Orchestrator Manual Invocation

Restore requires a signed `RestoreApprovalClaim` after archive SHA-256 is known.
Use operator-runbook §2.2 to issue the restore approval.

Command:

```bash
ARCHIVE_SHA256=$(
  shasum -a 256 "$HOME/.taskhub/backups/layer-c-smoke.tar.age" | cut -d' ' -f1
)
uv run taskhub restore \
  --approval-id "$RESTORE_APPROVAL_ID" \
  --input "$HOME/.taskhub/backups/layer-c-smoke.tar.age"
```

Expected:

- restore verifies archive checksum before applying.
- compose/env/artifacts verified-copy bindings are used for Phase 5 paths.
- `verify_alembic_head_in_db` matches the signed restore claim.

## §4 Canonical Fingerprint Fields

Backup runtime binding fingerprint includes:

- `target_compose_project_name`
- `target_compose_file_realpath`
- `target_compose_file_sha256`
- `target_compose_project_directory`
- `artifacts_dir_realpath`
- `artifacts_dir_manifest_sha256`
- `sops_env_path_realpath`
- `sops_env_sha256`
- `env_file_realpath`
- `env_file_sha256`
- `compose_config_canonical_sha256`
- `pg_user`
- `pg_db`
- `postgres_service_name`
- `redis_service_name`

Operator rule: never hand-edit these fields. Re-issue the signed approval when
any source binding changes.

## §5 Failure Detection And Alerting

Treat these reason codes as immediate operator action:

- `backup_claim_mismatch`
- `backup_compose_binding_not_initialized`
- `backup_payload_source_tampered`
- `backup_artifacts_staging_tampered`
- `restore_alembic_head_mismatch`
- `destructive_lock_busy`

Collect:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.yml \
  --env-file .env.local \
  logs --tail=200 api worker
tail -200 /tmp/taskhub-verify.log 2>/dev/null || true
```

## §6 Drill Execution Path

Mac local path:

```bash
export DATABASE_URL="postgresql://taskmanagedai:taskmanagedai@127.0.0.1:5432/taskmanagedai"
export BACKUP_APPROVAL_ID="<issued-backup-approval-id>"
export BACKUP_PATH="/tmp/taskhub-backup-$(date +%Y%m%d-%H%M%S).tar"

bash scripts/alembic_wrapper.sh current
uv run taskhub verify \
  --signed-journal \
  --from-db \
  --tenant-id 1 \
  --database-url "$DATABASE_URL"
uv run taskhub backup \
  --approval-id "$BACKUP_APPROVAL_ID" \
  --output "$BACKUP_PATH" \
  --skip-service-stop
```

Linux/VPS path:

```bash
export TARGET_HOST="taskhub-vps"

ssh "$TARGET_HOST" \
  'cd /var/lib/taskhub/TaskManagedAI && bash scripts/alembic_wrapper.sh current'
ssh "$TARGET_HOST" 'cd /var/lib/taskhub/TaskManagedAI && uv run taskhub status'
```

## §7 Rollback Procedures

Rollback requires explicit operator decision. Prefer application-level restore
rollback first; Alembic downgrade is a last resort.

Order:

1. Stop frontend and worker.
2. Preserve logs and `/tmp/taskhub-*.log` evidence.
3. If restore failed after pre-restore snapshot creation, issue
   restore-rollback approval and run `taskhub restore --rollback`.
4. If migration rollback is required, run:

```bash
bash scripts/alembic_wrapper.sh downgrade -1
docker compose \
  -f docker-compose.yml \
  -f docker-compose.dev.yml \
  --env-file .env.local \
  restart api worker frontend
```

## §8 Monitoring And Log Aggregation

For Layer C, local evidence is sufficient:

- `docker compose logs --tail=200 api worker frontend`
- `/tmp/taskhub-alembic-upgrade.log`
- `/tmp/taskhub-verify.log`
- backup command JSON summary

P0.1+ may add Prometheus, Loki, and Grafana. Until then, do not block Layer C on
external observability services.

## §9 Emergency Escalation

Escalation has three stages:

1. Tier 1 self-heal: restart unhealthy non-database services and rerun health
   checks.
2. Tier 2 operator: stop destructive operation, preserve evidence, and re-issue
   approval if source bindings changed.
3. Tier 3 vendor/platform: investigate Docker Desktop, filesystem, Tailscale,
   or GitHub availability issues.

Stop immediately if a secret-bearing temp directory remains after backup or
restore cleanup. Preserve the path, do not upload its contents, and rotate
affected keys after incident review.
