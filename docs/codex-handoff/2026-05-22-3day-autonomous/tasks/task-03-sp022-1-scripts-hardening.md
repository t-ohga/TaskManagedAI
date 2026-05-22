# task-03: SP-022-1 — scripts hardening + Layer C SOP polish

**優先**: P1、**計画必須**: 推奨、**self-review**: Plan 1 round + Impl 1 round 推奨 (§3 Self-Review Protocol)、**想定 effort**: 0.7-1 day

> `codex-all-loops` は Claude 専用 skill (`00-codex-behavior-guide.md` §3.0)。Codex は self-review で同等観点を確保。

## 1. 目的

P0 Exit Phase 7a で未対応の **deviation 7 件** を hardening + Layer C operator runbook §1-§9 起票。

## 2. 起動 protocol

### 2.1 Read order

1. `docs/codex-handoff/2026-05-22-3day-autonomous/README.md`
2. `docs/codex-handoff/2026-05-22-3day-autonomous/00-codex-behavior-guide.md`
3. `docs/codex-handoff/2026-05-22-3day-autonomous/01-current-state.md`
4. **本 file**
5. `docs/sprints/SP-022-1_scripts_hardening.md` (新規起票、なければ task 完了時に起票)
6. `docs/deploy/mac-single-host-smoke-sop.md` (既存 SOP)
7. `scripts/backup_orchestrator.py` (hardening target)
8. `compose.yaml` (healthcheck timeout 調整 target)
9. `Dockerfile.eval` (COPY 順序 hardening target)

### 2.2 worktree

```bash
cd /Users/tohga/repo/TaskManagedAI
git worktree add .claude/worktrees/codex-task-03-sp022-1 origin/main
cd .claude/worktrees/codex-task-03-sp022-1
bash scripts/worktree_setup.sh
```

## 3. 計画 phase (推奨、軽い)

**Self-Plan-Review (§3.1) Round 1 のみ**: 構造論点列挙 + 採否判定後着手 (敵対視点 Round 2 は scope 内 adversarial 観点少なめのため省略可)

## 4. 実装 phase (deviation 7 件 + Layer C runbook)

### 4.1 deviation 1: `--mac-mode` flag 実装

**scope**: `scripts/backup_orchestrator.py`

Mac local mode (Linux VPS と区別) flag 追加:
- `--mac-mode`: docker compose stack の Mac 固有 path / port 使用
- `--linux-mode`: Linux VPS デフォルト
- 既存呼び出しは backward compat (`--mac-mode` 未指定 = `--linux-mode`)

### 4.2 deviation 2: `--remote` 引数バリデーション強化

**scope**: `scripts/backup_orchestrator.py` の `--remote` 引数

- Tailscale hostname / FQDN format check (RFC 1123)
- SSH ConnectionTimeout 設定 (default 10s)
- SSH_AUTH_SOCK env allowlist (`SSH_AUTH_SOCK` のみ propagate、それ以外 env は drop)

### 4.3 deviation 3: §13 grep coverage SOP polish

**scope**: `docs/deploy/mac-single-host-smoke-sop.md` §13

- grep coverage 強化 (verify failures + ssh diagnostic 全件 catch)
- §13.1〜§13.6 sub-section 追加 (各 verify step の grep pattern + 期待 output)

### 4.4 deviation 4: compose healthcheck timeout / retries 調整

**scope**: `compose.yaml`

- `postgres` healthcheck: `interval=10s timeout=5s retries=10` (現在 retries=5 で起動遅延時 false fail)
- `redis` healthcheck: 同様
- `fastapi` healthcheck: `start_period=30s` 追加 (alembic upgrade 待ち)

### 4.5 deviation 5: Dockerfile.eval build-time COPY 順序

**scope**: `Dockerfile.eval`

build cache 効率化:
1. `COPY pyproject.toml uv.lock /app/` を先頭付近に
2. `uv sync --frozen` で dependencies 確定
3. `COPY backend /app/backend` を最後付近に (code 変更時の cache 再利用)

### 4.6 deviation 6: `scripts/seed_dev_login.py` のエラーハンドリング

**scope**: `scripts/seed_dev_login.py`

- `try: ... except Exception: log + exit 1` で fail-fast
- 既存 user 衝突時の clear エラー message
- DB connection failure 時の retry 3 回 + 5s sleep

### 4.7 deviation 7: Layer C operator runbook §1-§9

**scope**: `docs/deploy/layer-c-operator-runbook.md` (新規起票)

Layer C operator runbook §1-§9:
1. service startup sequence (postgres → redis → fastapi → arq-worker → nextjs)
2. backup orchestrator manual invocation (BackupApprovalClaim 6 field 化)
3. restore orchestrator (RestoreApprovalClaim + verify copy 4 種)
4. canonical fingerprint 15 field 詳細
5. failure detection + alerting
6. drill execution path (Mac local + Linux VPS)
7. rollback procedures (alembic downgrade + service restart)
8. monitoring + log aggregation (P0.1+ Prometheus / Loki / Grafana 接続予定)
9. emergency escalation (3-stage: Tier 1 self-heal / Tier 2 operator / Tier 3 vendor)

## 5. 検証手順

### 5.1 scripts 変更

```bash
# Python lint + type
uv run ruff check scripts/
uv run mypy scripts/

# Backup orchestrator dry-run
python scripts/backup_orchestrator.py --mac-mode --dry-run
python scripts/backup_orchestrator.py --linux-mode --dry-run
```

### 5.2 compose.yaml 変更

```bash
# Validate
docker compose config --quiet

# Build (no run)
docker compose --env-file .env.local build
```

### 5.3 Dockerfile.eval 変更

```bash
# Build with cache verify
docker build -f Dockerfile.eval -t taskmanagedai-eval-test .

# Verify image size (前後比較)
docker images taskmanagedai-eval-test
```

### 5.4 docs 変更

```bash
# SOP markdown lint
markdownlint docs/deploy/*.md  # or 同等の linter
```

## 6. PR 起票 + admin bypass merge

各 deviation で個別 PR、または 2-3 件まとめて 1 PR:

```bash
git push -u origin feat/sp022-1-backup-orchestrator-mac-mode-flag-2026-05-24
gh pr create --base main --head feat/sp022-1-backup-orchestrator-mac-mode-flag-2026-05-24 \
  --title "feat(sp022-1-deviation-1): --mac-mode flag 実装" \
  --body "..."
```

## 7. Codex auto-review baseline (必須)

```bash
sleep 60
.claude/scripts/codex_pr_full_review.sh <PR_NUM> 2>&1 | head -200
```

## 8. DoD checklist

- [ ] deviation 1-6 全件実装 (scripts + compose + Dockerfile + dev login)
- [ ] deviation 7 (Layer C runbook §1-§9) 起票完了
- [ ] script ruff + mypy clean
- [ ] docker compose build PASS
- [ ] Sprint Pack SP-022-1 frontmatter `status: ready → completed` + Review 章追加 (なければ起票)
- [ ] 完了報告 `completion/task-03-completed.md` 起票

## 9. blocker / 緊急停止

- compose.yaml 変更で既存 Mac local stack の startup 失敗 → rollback + STOPPED.md
- backup orchestrator の core logic 変更 (verify copy 4 種 / atomic claim) → ADR Gate Criteria #8 該当の可能性 → STOPPED.md
- Layer C runbook §1-§9 全件起票で想定 effort 超過 → §1-§5 のみ完遂 + §6-§9 を defer

## 10. 関連参照

- `docs/sprints/SP-022_phase_7a_deviation_catalog.md` (deviation 一覧、起票 source)
- `docs/deploy/mac-single-host-smoke-sop.md` (既存 SOP)
- `scripts/backup_orchestrator.py` (hardening target)
- 過去類似 PR: PR #76-#88 (SP-022 T01-T06 実装)
