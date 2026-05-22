# Mac single-host smoke SOP (SP022-T09 prep)

最終更新: 2026-05-22 (SP-022 T09 prep)
status: ready
所要時間: Layer B (30-60 min) + Layer C (60-120 min) = 約 90-180 min

---

## 0. 目的

SP022-T09 host migration drill (Mac→VPS) の **前提条件として、Mac single-host 上で TaskManagedAI P0 機能が動作することを実証する**。3 layer に分離:

| Layer | 内容 | 実施者 | 状態 |
|---|---|---|---|
| **A** (autonomous、worktree 内) | static check + regression PASS (pytest / vitest / ruff / mypy / typecheck / eslint / alembic offline) | Claude | ✅ 完了 (2026-05-22、本 PR で merged) |
| **B** (Mac 実機、docker stack) | docker compose stack が動作 (5 service healthy + /healthz + alembic upgrade) | user | ⏳ 本 SOP §1-§5 で実施 |
| **C** (Mac 実機、機能 + CLI) | ブラウザ smoke + taskhub CLI smoke + golden flow | user | ⏳ 本 SOP §6-§15 で実施 |

Layer A 結果は `docs/deploy/smoke-evidence/2026-05-22-layer-A.md` (本 PR で commit) を参照。

## 0.1 前提環境

| 項目 | 確認 |
|---|---|
| Mac OS | Darwin (macOS) 13+ 推奨 |
| Docker Desktop | running (compose v2 利用可) |
| port 自由 | 5432 (postgres) / 6379 (redis) / 8000 (api) / 3000 (frontend) が空いている |
| disk 空き | ≥ 5 GB (docker image + volume + backup archive 用) |
| TaskManagedAI repo | `~/repo/TaskManagedAI` (本実装の cwd) |
| age (key 暗号化) | `brew install age` |
| jq | `brew install jq` |

worktree (`~/repo/TaskManagedAI/.claude/worktrees/*`) ではなく **実 repo (`~/repo/TaskManagedAI`)** で実施。

---

# Layer B: Mac docker compose smoke (所要 30-60 min)

実施場所: `cd ~/repo/TaskManagedAI` (worktree じゃない実 repo)

## §1 .env.local 設定 (B-1)

```bash
cd ~/repo/TaskManagedAI
cp .env.example .env.local

# 最低限の編集 (development case 用)
cat >> .env.local <<'ENV'

# === Mac local development smoke (SP022-T09 prep) ===
TASKMANAGEDAI_ENVIRONMENT=development
POSTGRES_PASSWORD=taskmanagedai_local_smoke_pwd
TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=local-dev-cookie-secret-32bytes-min
TASKMANAGEDAI_DEV_LOGIN_TOKEN=local-dev-login-token-for-mac-smoke
TASKMANAGEDAI_DATABASE_URL=postgresql+asyncpg://taskmanagedai:taskmanagedai_local_smoke_pwd@postgres:5432/taskmanagedai
TASKMANAGEDAI_REDIS_URL=redis://redis:6379/0
ENV

# 検証 (TASKMANAGEDAI_ENVIRONMENT=development 必須)
grep TASKMANAGEDAI_ENVIRONMENT .env.local
# expected: TASKMANAGEDAI_ENVIRONMENT=development
```

**所要**: 2-5 min

**失敗時**: `.env.example` が存在しない → `git pull origin main`、existing `.env.local` ある → 上書き or 別名 backup

## §2 docker compose build (B-2)

```bash
docker compose --env-file .env.local build 2>&1 | tee /tmp/taskhub-build.log
# expected: 全 5 service (api / worker / postgres / redis / frontend) が build 成功、exit 0
echo "Build exit code: $?"
```

**所要**: 5-15 min (初回)、再 build なら 1-2 min

**失敗時**:
- Docker Desktop 未起動 → 起動して retry
- `error: ENOSPC: no space left on device` → `docker system prune -a` で空き作成
- network error → pkg download 失敗、再 retry

## §3 docker compose up + healthy 確認 (B-3)

```bash
# detached mode で起動
docker compose --env-file .env.local up -d

# 全 service の healthy 状態待機 (最長 2 min)
for i in {1..24}; do
  STATUS=$(docker compose --env-file .env.local ps --format json | jq -r '[.[] | .Health] | join(",")')
  echo "[$i/24] service health: $STATUS"
  if [ "$(echo $STATUS | tr ',' '\n' | grep -c -v 'healthy')" = "0" ]; then
    echo "✅ All services healthy"
    break
  fi
  sleep 5
done

docker compose --env-file .env.local ps
# expected: api / worker / postgres / redis / frontend が全て Up (healthy)
```

**所要**: 5-10 min (初回起動、image 起動 + healthcheck)

**失敗時**:
- service unhealthy が 2 分後も残る → `docker compose logs <service-name>` で error 確認
- postgres unhealthy → password mismatch (`.env.local` POSTGRES_PASSWORD と DATABASE_URL の password 一致確認)
- api unhealthy → migration 未適用の可能性、§4 で実施

## §4 alembic upgrade head (B-4)

```bash
# api container 内で alembic upgrade head 実行
docker compose --env-file .env.local exec api uv run alembic current
# expected: revision id (空または未 apply の状態)

docker compose --env-file .env.local exec api uv run alembic upgrade head 2>&1 | tail -10
# expected: 18 migrations apply 成功、exit 0

docker compose --env-file .env.local exec api uv run alembic current
# expected: 0018_eval_dataset_versions (head)
```

**所要**: 1-2 min

**失敗時**:
- revision id 不一致 → alembic_version table の手動 reset (高リスク、原因調査優先)
- migration syntax error → 個別 migration file 確認、Codex review 過去 PR 履歴確認

## §5 /healthz 応答確認 (B-5)

```bash
# API /healthz
curl -fsS http://127.0.0.1:8000/healthz | jq .
# expected: {"status":"ok",...}

# Frontend root
curl -fsS http://127.0.0.1:3000 | head -20
# expected: HTML response、Next.js 16 marker

# Redis ping
docker compose --env-file .env.local exec redis redis-cli PING
# expected: PONG

# PostgreSQL connection
docker compose --env-file .env.local exec postgres psql -U taskmanagedai -d taskmanagedai -c "select version();" | head -3
# expected: PostgreSQL 16.x
```

**所要**: 2-3 min

**失敗時**:
- /healthz 200 以外 → api logs (`docker compose logs api`) で詳細確認、`.env.local` の DEV_LOGIN_COOKIE_SECRET / DEV_LOGIN_TOKEN 32 char 以上か確認
- frontend HTML 不返 → frontend logs 確認、build 段階で error がなかったか

## §B 完了判定

以下全件 PASS で Layer B 完了:

- [ ] B-1 `.env.local` 正常編集、TASKMANAGEDAI_ENVIRONMENT=development 設定済
- [ ] B-2 docker compose build 全 service exit 0
- [ ] B-3 5 service (api / worker / postgres / redis / frontend) 全件 healthy
- [ ] B-4 alembic upgrade head 成功、`0018_eval_dataset_versions` が current head
- [ ] B-5 /healthz 200 OK + frontend HTML + redis PONG + postgres v16.x

完了したら以下を記録:
```bash
mkdir -p ~/.taskhub/drills/mac-single-host-smoke/$(date +%Y-%m-%d)
docker compose --env-file .env.local ps > ~/.taskhub/drills/mac-single-host-smoke/$(date +%Y-%m-%d)/B-services.txt
curl -fsS http://127.0.0.1:8000/healthz > ~/.taskhub/drills/mac-single-host-smoke/$(date +%Y-%m-%d)/B-healthz.json
echo "LAYER_B_DONE=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> ~/.taskhub/drills/mac-single-host-smoke/$(date +%Y-%m-%d)/timing.txt
```

---

# Layer C: 機能 smoke (ブラウザ + CLI) (所要 60-120 min)

実施場所: Layer B 完了済前提、引き続き `cd ~/repo/TaskManagedAI`

## §6 dev login flow (C-1、5 min)

```bash
# Mac browser で開く
open http://127.0.0.1:3000

# 別 terminal で login token 取得 (dev login 用)
grep TASKMANAGEDAI_DEV_LOGIN_TOKEN .env.local | cut -d= -f2
```

ブラウザ:
1. `/` → login page redirect
2. dev login token 入力 → cookie set → `/admin` redirect
3. cookie の `Secure` attribute は development では false (ADR-00022 spec)

**確認項目**:
- [ ] login form が表示
- [ ] token 入力後 `/admin` へ redirect
- [ ] DevTools → Application → Cookies で `taskmanagedai_session` cookie 存在

**失敗時**: dev login mode が enabled でない → `.env.local` の `TASKMANAGEDAI_ENVIRONMENT=development` 再確認

## §7 Eval Dashboard 実表示 + live KPI rollup (C-2、5-10 min)

ブラウザ: `http://127.0.0.1:3000/admin/eval-dashboard`

**確認項目** (PR #91 で実装、live wiring):
- [ ] P0 Exit verdict panel 表示 (BLOCKED or READY)
- [ ] Hard Gates 7 全件 (AC-HARD-01〜07) row 表示、各 threshold_met=true
- [ ] Quality KPIs 5 全件 (AC-KPI-01〜05) row 表示、source = "live"
  - source=live: backend `/api/v1/eval/kpi-rollup` 応答 ← 正常
  - source=skeleton_fallback: backend 5xx/Zod mismatch ← outage
  - source=fetch_error: 4xx/config error ← auth or config 不備
- [ ] description が backend 由来 (各 KPI 説明、threshold_reason)
- [ ] **raw secret / DSN / credentials が DOM に出現していない** (DevTools → View source で確認)

**DevTools 確認**:
```js
// Network tab: /api/v1/eval/kpi-rollup
// status 200 + 5 entries + p0_accept boolean が response body にある
// もし 503 / 501 fallback なら source=skeleton_fallback、500 系 fallback reason に sanitized status code
```

**失敗時**:
- source=skeleton_fallback → backend KPI rollup endpoint 動作不全、`docker compose logs api` 確認
- source=fetch_error + reason=auth_error → session cookie 失効、§6 dev login 再実施
- DOM に raw error message → R3 F-001 fix が動いていない、別途 fix PR

## §8 Ticket 一覧 / 詳細 (C-3、10 min)

ブラウザ: `http://127.0.0.1:3000/admin/tickets`

**確認項目**:
- [ ] Ticket 一覧表示 (空 list でも layout 正常)
- [ ] "New Ticket" / 作成 button (もしあれば) クリック → form
- [ ] 1 ticket 作成 → detail page navigation
- [ ] Acceptance Criteria / Evidence / AgentRun セクション表示 (空でも OK)

DevTools Network tab で:
- GET /api/v1/tickets → 200
- POST /api/v1/tickets → 201 (作成時)

**失敗時**: 500 が出る → `docker compose logs api` で stacktrace 確認

## §9 Approval Inbox (C-4、10 min)

ブラウザ: `http://127.0.0.1:3000/admin/approvals`

**確認項目**:
- [ ] Approval 一覧表示 (`pending` / `approved` / `rejected` / `expired` / `invalidated` 状態区別表示)
- [ ] self-approval 禁止のメッセージ表示 (requester = decider の case)
- [ ] approve / reject button (もしあれば、test approval を作成して試行)

## §10 Agent Runs 一覧 (C-5、5 min)

ブラウザ: `http://127.0.0.1:3000/admin/agent-runs`

**確認項目**:
- [ ] Agent Runs 一覧表示
- [ ] 16 状態 enum の表示確認 (queued / gathering_context / running / generated_artifact / schema_validated / policy_linted / diff_ready / waiting_approval / blocked / provider_refused / provider_incomplete / validation_failed / repair_exhausted / completed / failed / cancelled)
- [ ] `blocked` 状態の場合、`blocked_reason` (policy_blocked / budget_blocked / runtime_blocked) が別表示

## §11 Audit Log (C-6、5 min)

ブラウザ: `http://127.0.0.1:3000/admin/audit-log`

**確認項目**:
- [ ] AuditEvent 一覧表示 (append-only)
- [ ] event_type / actor_id / created_at / reason_code 表示
- [ ] **raw secret / token / private key が DOM に出現していない** (DevTools view-source で確認)
- [ ] payload に `sha256_prefix_8` / `hash` のみ表示 (raw value なし)

## §12 taskhub approval issue smoke (C-7、10 min)

別 terminal で:

```bash
cd ~/repo/TaskManagedAI

# §1 approval signing key bootstrap (初回のみ、operator-runbook §1 参照)
if [ ! -f ~/.taskhub/keys/approval-signing-key ]; then
  bash docs/deploy/operator-runbook.md  # 手動で §1 commands を実行
fi

# smoke approval issue (試行用、actual destructive op には使わない)
SMOKE_APPROVAL_ID="mac-smoke-$(date +%Y%m%d-%H%M%S)"
uv run taskhub approval issue \
  --approval-id "$SMOKE_APPROVAL_ID" \
  --decider t-ohga \
  --reason-summary "mac-single-host_smoke" \
  --drill-kind host_migration_mac_vps \
  --allowed-subcommands backup \
  --target-host t-ohga-mac \
  --ttl-hours 1 \
  --backup-output-path /tmp/smoke.tar.age \
  --backup-include-sops-env \
  --backup-age-public-key-fingerprint "0000000000000000000000000000000000000000000000000000000000000000"
echo "Exit code: $?"

# signed record verify
ls -la ~/.taskhub/approvals/${SMOKE_APPROVAL_ID}.signed
# expected: file 存在、mode 0600
```

**確認項目**:
- [ ] CLI exit 0
- [ ] signed record file 0600 mode 生成
- [ ] file 内容に approval_id / decider / signed_at / signature が JSON form 含まれる

**失敗時**: §1 key bootstrap 未実施 → `operator-runbook.md §1` を実行

## §13 signed journal verify CLI (C-8、5 min)

```bash
# PR #90 で実装、--from-db mode で実 DB 上の audit_events を verify
DATABASE_URL=$(grep TASKMANAGEDAI_DATABASE_URL .env.local | cut -d= -f2- | sed 's/postgres:/127.0.0.1:/g')
uv run taskhub verify --signed-journal --from-db --tenant-id 1 --database-url "$DATABASE_URL" 2>&1 | tail -10
echo "Exit code: $?"
```

**確認項目**:
- [ ] exit 0 (audit_events が空でも tenant_scope check + chain integrity OK で PASS)
- [ ] 空 chain の場合 `tenant_scope_empty` 含む明示 message

**失敗時**:
- `tenant_scope_empty` raise → backend 未動作 or tenant_id mismatch
- DSN error (sanitized) → `.env.local` の URL を再確認

## §14 taskhub backup real smoke (small DB) (C-9、20 min)

```bash
# §2.1 backup approval issue (operator-runbook §2.1)
BACKUP_APPROVAL_ID="mac-smoke-backup-$(date +%Y%m%d-%H%M%S)"
BACKUP_OUTPUT="$HOME/.taskhub/backups/mac-smoke-$(date +%Y-%m-%d).tar.age"
mkdir -p ~/.taskhub/backups

# age public key fingerprint (Mac の age key を使う)
AGE_PUB_FP=$(age-keygen -y ~/.taskhub/keys/age.key.txt 2>/dev/null | sha256sum | cut -c1-64)
echo "AGE_PUB_FP=$AGE_PUB_FP"

uv run taskhub approval issue \
  --approval-id "$BACKUP_APPROVAL_ID" \
  --decider t-ohga \
  --reason-summary "mac-smoke_real-backup" \
  --drill-kind host_migration_mac_vps \
  --allowed-subcommands backup \
  --target-host t-ohga-mac \
  --ttl-hours 1 \
  --backup-output-path "$BACKUP_OUTPUT" \
  --backup-include-sops-env \
  --backup-age-public-key-fingerprint "$AGE_PUB_FP"

# real backup 実行
uv run taskhub backup --output "$BACKUP_OUTPUT" --approval-id "$BACKUP_APPROVAL_ID"
echo "Exit code: $?"

# T09 mandatory checklist 7 項目 verify
ls -la "$BACKUP_OUTPUT"
ARCHIVE_SHA256=$(sha256sum "$BACKUP_OUTPUT" | cut -d' ' -f1)
echo "ARCHIVE_SHA256=$ARCHIVE_SHA256"

mkdir -p /tmp/mac-smoke-extract && cd /tmp/mac-smoke-extract
age -d -i ~/.taskhub/keys/age.key.txt "$BACKUP_OUTPUT" > decrypted.tar
tar -tf decrypted.tar | tee tar-listing.txt
# expected: meta.json / checksums.txt / postgres/pg_dump.dump / postgres/alembic_version.txt / redis/dump.rdb / artifacts/

# private key 非混入 (CRITICAL invariant)
tar -tf decrypted.tar | grep -E '(id_rsa|id_ed25519|age-key|keys\.txt|\.private\.pem)' && echo "❌ PRIVATE KEY DETECTED" || echo "✅ no private key in archive"

# pg_restore --list 互換確認
tar -xf decrypted.tar postgres/pg_dump.dump
pg_restore --list postgres/pg_dump.dump | head -10
echo "Exit code: $?"

cd ~/repo/TaskManagedAI
```

**確認項目** (T09 7 mandatory checklist の subset):
- [ ] backup exit 0、output file 存在
- [ ] age decrypt 成功
- [ ] tar listing 全 file 構造存在 (ADR-00021 §4)
- [ ] checksums verify (`cd extract && sha256sum -c checksums.txt`)
- [ ] private key 非混入
- [ ] pg_restore --list parse 成功
- [ ] /tmp/taskhub-backup-* cleanup verified (`ls /tmp/taskhub-backup-* 2>&1`、0 件 expected)

**失敗時**:
- destructive_lock_busy → 他 destructive op 進行中、operator-runbook §8 で復旧
- pg_dump fail → docker compose で postgres healthy 確認

## §15 golden flow Ticket→PR smoke (C-10、15-30 min)

BL-0140a の Research → Ticket → Plan → Approval → Runner → Draft PR の 12 step flow。本 SOP では skeleton smoke として:

```bash
# 12 step gold flow eval test を実行
uv run pytest tests/eval/ticket_to_pr_smoke -v 2>&1 | tail -20
echo "Exit code: $?"
```

または ブラウザで:
1. Research task 作成 → Decision/Generated Ticket → Plan artifact → Approval request → Runner execution → Draft PR mock の sequence
2. 各 step で event chain (research_id / source_set_hash / generated_ticket_hash / plan_artifact_hash / approval_id / pr_artifact_hash) が AuditEvent に append される

**確認項目**:
- [ ] 12 step 全件 PASS
- [ ] hash chain 完全 (各 step output が次 step input にバインド)
- [ ] secret 値 / DSN が AuditEvent payload に含まれない

**所要**: 15-30 min

**失敗時**:
- step 単位で fail がある場合、`docker compose logs api worker` で詳細確認
- skeleton smoke なので 1 ticket の e2e が動けば OK

## §C 完了判定

- [ ] C-1 dev login flow 動作 + cookie set
- [ ] C-2 Eval Dashboard 実表示 + live KPI rollup (source=live)
- [ ] C-3 Ticket 一覧 / 詳細 動作
- [ ] C-4 Approval Inbox 動作
- [ ] C-5 Agent Runs 一覧 + 16 状態表示
- [ ] C-6 Audit Log + raw secret 漏れ無し
- [ ] C-7 taskhub approval issue smoke 成功
- [ ] C-8 signed journal verify CLI 動作 (--from-db)
- [ ] C-9 taskhub backup real smoke + 7 mandatory checklist subset PASS
- [ ] C-10 golden flow Ticket→PR smoke PASS

完了したら以下を記録:
```bash
cat > ~/.taskhub/drills/mac-single-host-smoke/$(date +%Y-%m-%d)/result.json <<EOF
{
  "smoke_date": "$(date +%Y-%m-%d)",
  "smoke_kind": "mac_single_host",
  "layer_a_pass": true,
  "layer_b_pass": true,
  "layer_c_pass": true,
  "approval_ids": {
    "smoke_approval": "$SMOKE_APPROVAL_ID",
    "backup_approval": "$BACKUP_APPROVAL_ID"
  },
  "archive_sha256": "$ARCHIVE_SHA256",
  "checklist_item_6_no_private_key": true,
  "errors": [],
  "next_action": "SP022-T09 host migration drill (Mac→VPS)"
}
EOF
cat ~/.taskhub/drills/mac-single-host-smoke/$(date +%Y-%m-%d)/result.json
```

---

# §16 残作業 + escalation

## Mac smoke 後の残作業 (T09 host migration drill 着手前)

| # | task | 実施者 | 所要 |
|---|---|---|---|
| 1 | Mac smoke result を私 (Claude) に報告 | user | 1 min |
| 2 | result.json + Layer B/C log を持って T09 drill 開始判断 | Claude + user | - |
| 3 | T09 host migration drill (Mac→VPS) 実施 | user (本 session 内で手順提示済) | 2.5-4 h |
| 4 | T09 drill retro Pack + ADR-00021/00007 accepted 化 | Claude (drill PASS 後) | 30 min |
| 5 | SP-012 + SP-022 frontmatter `completed` 化 | Claude | 10 min |
| 6 | P0 Exit declaration PR + TASKHUB_P0_1_OPENED=1 解禁 | Claude | 30 min |
| 7 | SP-013 multi-agent orchestration 着手 | Claude | post-P0 |

## escalation 経路

- Layer B 失敗 → `docker compose logs` で原因確認、`.env.local` 設定 review
- Layer C 失敗 → 該当 endpoint の backend log 確認、frontend DevTools Network
- private key 混入検出 → CRITICAL incident、archive 即削除、bug PR 起票
- 全 layer 完了 + smoke OK → T09 drill 着手 (前 session 内で詳細手順提示済)

## 関連 docs

- ADR-00021 (host-portable deployment、本 SOP は drill 前提条件)
- ADR-00020 (framework intake checklist、CI 機械化済 SP022-T01)
- `docs/deploy/operator-runbook.md` (§1-§22、approval signing / backup / restore / migration / runtime SOP)
- `docs/deploy/half-yearly-drill-sop.md` §11 (T09 mandatory drill checklist 7 項目正本)
- `.claude/plans/sp022-t09-prep-mac-smoke.md` (本 SOP の plan、light、ADR Gate 非該当)
- `docs/deploy/smoke-evidence/2026-05-22-layer-A.md` (Layer A 結果 evidence)
