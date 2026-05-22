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

### 0.2 docker compose dev override 適用

本 SOP の全 `docker compose` command は **`-f docker-compose.yml -f docker-compose.dev.yml`** で起動する (base `docker-compose.yml` の `networks.taskmanagedai_internal.internal: true` を dev override で `internal: false` に変更し、host から 127.0.0.1 経由で container に到達可能にするため)。

- base compose: production 向け、`internal: true` で deny-by-default (Tailscale Serve TLS 終端経由のみ external access、ADR-00007 + ADR-00021)
- dev override (`docker-compose.dev.yml`): Mac single-host smoke / development 用、`internal: false` で host (`127.0.0.1`) から port publish 経由で container 到達可能 (ADR-00022 dev_login cookie secure attribute と整合、HTTP loopback 動作)

dev override を忘れて起動した場合: `docker compose ps` で services healthy になっても `docker port api` が空になり、host から `curl http://127.0.0.1:8000/healthz` が `Connection refused` で失敗する (`internal: true` 由来)。

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

### B-1b: backend seed runner 実行 (initial default actor seed、§4 alembic upgrade 後に必要)

新規 fresh DB では `actors` table が空のため、Layer C §6 dev login flow / §7 Eval Dashboard API curl が **HTTP 401 `actor not found`** で失敗する。`backend/app/seeds/runner.py` を実行して default `human:default` actor + tenant + workspace + project 等を seed する (post-merge SOP polish 2026-05-22 追加):

```bash
# Layer B §4 alembic upgrade head 完了後に実行
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local exec -T api uv run --no-sync python -m backend.app.seeds.runner
echo "seed runner exit=$?"
# expected: exit=0 (`actors` / `tenants` / `workspaces` / `projects` / `repositories` / `tickets` / `acceptance_criteria` / `audit_events` table に default record seed)
```

**確認**:
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local exec -T postgres \
  psql -U taskmanagedai -d taskmanagedai -c "SELECT id, actor_type, actor_id FROM actors LIMIT 5;"
# expected: 1 row (`human:default`, type=human)
```

**失敗時**: api container がまだ healthy でない → `docker compose ps` で確認、Layer B §4 alembic upgrade head 完了を再確認

**所要**: 2-5 min

**失敗時**: `.env.example` が存在しない → `git pull origin main`、existing `.env.local` ある → 上書き or 別名 backup

## §2 docker compose build (B-2)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local build 2>&1 | tee /tmp/taskhub-build.log
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
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local up -d

# 全 service の healthy 状態待機 (最長 2 min)
for i in {1..24}; do
  STATUS=$(docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local ps --format json | jq -r '[.[] | .Health] | join(",")')
  echo "[$i/24] service health: $STATUS"
  if [ "$(echo $STATUS | tr ',' '\n' | grep -c -v 'healthy')" = "0" ]; then
    echo "✅ All services healthy"
    break
  fi
  sleep 5
done

docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local ps
# expected: api / worker / postgres / redis / frontend が全て Up (healthy)
```

**所要**: 5-10 min (初回起動、image 起動 + healthcheck)

**失敗時**:
- service unhealthy が 2 分後も残る → `docker compose logs <service-name>` で error 確認
- postgres unhealthy → password mismatch (`.env.local` POSTGRES_PASSWORD と DATABASE_URL の password 一致確認)
- api unhealthy → migration 未適用の可能性、§4 で実施

## §4 alembic upgrade head (B-4)

```bash
# pipefail を ON にして pipe 経由でも失敗を検知 (Codex PR #93 R1 F-004 fix:
# `alembic ... | tail -10` のままだと pipe exit code は tail (0) になり、
# migration 失敗を mask する。)
set -o pipefail

# api container 内で alembic upgrade head 実行
# scripts/alembic_wrapper.sh は host/container の TASKMANAGEDAI_DATABASE_URL / DATABASE_URL
# override を Alembic process から strip し、.env.local + container 内設定を正本にする。
bash scripts/alembic_wrapper.sh current
# expected: revision id (空または未 apply の状態)

# 出力 full 保存 + pipefail で failure mask 防止
bash scripts/alembic_wrapper.sh upgrade head 2>&1 | tee /tmp/taskhub-alembic-upgrade.log
ALEMBIC_EXIT=$?
echo "alembic upgrade head exit code: $ALEMBIC_EXIT"
if [ "$ALEMBIC_EXIT" -ne 0 ]; then
  echo "❌ alembic upgrade head FAILED. See /tmp/taskhub-alembic-upgrade.log for full output."
  exit 1
fi
# 出力 tail 表示 (確認用、exit code は ALEMBIC_EXIT 経由で既に判定済)
tail -10 /tmp/taskhub-alembic-upgrade.log

# expected: 18 migrations apply 成功、ALEMBIC_EXIT=0

bash scripts/alembic_wrapper.sh current
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
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local exec redis redis-cli PING
# expected: PONG

# PostgreSQL connection
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local exec postgres psql -U taskmanagedai -d taskmanagedai -c "select version();" | head -3
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
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local ps > ~/.taskhub/drills/mac-single-host-smoke/$(date +%Y-%m-%d)/B-services.txt
curl -fsS http://127.0.0.1:8000/healthz > ~/.taskhub/drills/mac-single-host-smoke/$(date +%Y-%m-%d)/B-healthz.json
echo "LAYER_B_DONE=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> ~/.taskhub/drills/mac-single-host-smoke/$(date +%Y-%m-%d)/timing.txt
```

---

# Layer C: 機能 smoke (ブラウザ + CLI) (所要 60-120 min)

実施場所: Layer B 完了済前提、引き続き `cd ~/repo/TaskManagedAI`

## §6 dev login flow (C-1、5 min)

実装は `frontend/middleware.ts` で `PUBLIC_PATHS = ["/login", "/api/healthz"]` 以外への未認証アクセスを `/login?next=<original-path>` に redirect、login action 完了後に `next` query param 経由で元 URL に戻す構造 (route group `(admin)` / `(auth)` は URL prefix に含まれない、`/admin` route は存在しない)。`frontend/tests/e2e/login.spec.ts` の dev login flow が正本。

```bash
# 別 terminal で login token 取得 (dev login 用、ブラウザ操作前)
grep TASKMANAGEDAI_DEV_LOGIN_TOKEN .env.local | cut -d= -f2
```

### Primary path (推奨、E2E test 正本と同経路)

```
Mac browser で開く: http://127.0.0.1:3000/dashboard
```

ブラウザ:
1. middleware で未認証検知 → `http://127.0.0.1:3000/login?next=%2Fdashboard` に redirect
2. login form 表示 (`/login?next=%2Fdashboard`、dev login token 入力 form)
3. dev login token を入力 → "Sign in" click → login action 実行 + `taskmanagedai_session` cookie 発行
4. `next` query param 経由で `/dashboard` に戻る + admin navigation 表示
5. cookie の `Secure` attribute は development では false (ADR-00022 spec)

### Alternative path (root landing 経由)

```
Mac browser で開く: http://127.0.0.1:3000/
```

ブラウザ:
1. root landing page 表示 (Login link + Dashboard link 含む landing page)
2. "Dashboard" link click (未認証) → middleware で未認証検知 → `/login?next=%2Fdashboard` redirect
3. 以降は Primary path step 2-5 と同じ

**確認項目** (両 path 共通):
- [ ] `/dashboard` 未認証アクセス時 (Primary) または Dashboard link click 時 (Alternative)、`/login?next=%2Fdashboard` redirect 確認
- [ ] login form (`/login?next=%2Fdashboard`) が表示
- [ ] token 入力後 `/dashboard` に戻る (admin navigation header 表示 + `Dashboard` link が `aria-current=page`)
- [ ] DevTools → Application → Cookies で `taskmanagedai_session` cookie 存在 (HttpOnly + SameSite=Lax)

**失敗時**: dev login mode が enabled でない → `.env.local` の `TASKMANAGEDAI_ENVIRONMENT=development` 再確認

**E2E test との同期化** (routing fix 2026-05-22 で hardening):
- 上記 Primary path は `frontend/tests/e2e/login.spec.ts:28-46` ("dev login proxies through the backend...") と完全一致
- URL pattern `/\/login\?next=%2Fdashboard$/u` (E2E line 28) が SOP §6 と同じ regex で表現される

## §7 Eval Dashboard 実表示 + live KPI rollup (C-2、5-10 min)

ブラウザ: `http://127.0.0.1:3000/eval-dashboard` (route group `(admin)` は URL prefix に含まれない)

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

ブラウザ: `http://127.0.0.1:3000/tickets`

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

ブラウザ: `http://127.0.0.1:3000/approvals`

**確認項目**:
- [ ] Approval 一覧表示 (`pending` / `approved` / `rejected` / `expired` / `invalidated` 状態区別表示)
- [ ] self-approval 禁止のメッセージ表示 (requester = decider の case)
- [ ] approve / reject button (もしあれば、test approval を作成して試行)

## §10 Agent Runs 一覧 (C-5、5 min)

ブラウザ: `http://127.0.0.1:3000/runs` (実 route name は `runs`、SOP の旧 `/admin/agent-runs` は誤記)

**確認項目**:
- [ ] Agent Runs 一覧表示
- [ ] 16 状態 enum の表示確認 (queued / gathering_context / running / generated_artifact / schema_validated / policy_linted / diff_ready / waiting_approval / blocked / provider_refused / provider_incomplete / validation_failed / repair_exhausted / completed / failed / cancelled)
- [ ] `blocked` 状態の場合、`blocked_reason` (policy_blocked / budget_blocked / runtime_blocked) が別表示

## §11 Audit Log (C-6、5 min)

ブラウザ: `http://127.0.0.1:3000/audit` (実 route name は `audit`、SOP の旧 `/admin/audit-log` は誤記)

**確認項目**:
- [ ] AuditEvent 一覧表示 (append-only)
- [ ] event_type / actor_id / created_at / reason_code 表示
- [ ] **raw secret / token / private key が DOM に出現していない** (DevTools view-source で確認)
- [ ] payload に `sha256_prefix_8` / `hash` のみ表示 (raw value なし)

## §12 taskhub approval issue smoke (C-7、10 min)

### 12.0 key bootstrap 早見表 (operator-runbook §1 への参照、post-merge SOP polish 2026-05-22 追加)

§12 / §14 で必要な key の bootstrap 仕様 (詳細手順は `docs/deploy/operator-runbook.md` §1 を参照):

| key | 用途 | path | mode | 生成 command 概要 |
|---|---|---|---|---|
| approval signing key (Ed25519) | `taskhub approval issue` の signed record 生成 (§12) | `~/.taskhub/keys/approval-signing-key` | 0600 | `openssl genpkey -algorithm Ed25519 -out <path>` + fingerprint allowlist 登録 (operator-runbook §1 step 2-4) |
| age private key | `taskhub backup` の archive 暗号化 / decrypt (§14) | `~/.taskhub/keys/age.key.txt` | 0600 | `mkdir -p ~/.taskhub/keys && chmod 0700 ~/.taskhub/keys && age-keygen -o ~/.taskhub/keys/age.key.txt && chmod 0600 ~/.taskhub/keys/age.key.txt` |

**重要**:
- `~/.taskhub/keys/` directory mode は `0700`、各 key file mode は `0600` (T09 drill 7 mandatory checklist の private key 漏洩防止 invariant)
- key 未生成のまま §12 / §14 を実行すると下記 fail-fast check が deny する
- bootstrap は **本 SOP 実行前に operator-runbook §1 を手動コピペ実行** してください (markdown 全体を bash に渡さない、Codex PR #93 R1 F-001 fix 反映済)

### 12.1 approval issue 実行 (key bootstrap 済前提)

別 terminal で:

```bash
cd ~/repo/TaskManagedAI

# §12.0 早見表参照: approval signing key 存在 + mode 確認
if [ ! -f ~/.taskhub/keys/approval-signing-key ]; then
  echo "❌ approval signing key 未生成 (~/.taskhub/keys/approval-signing-key)。"
  echo "   先に operator-runbook.md §1 step 2-4 (Ed25519 key 生成 + fingerprint allowlist 登録) を別 terminal で実行してください。"
  echo "   open docs/deploy/operator-runbook.md  # GUI で開く"
  echo "   または less docs/deploy/operator-runbook.md  # terminal で確認"
  echo "   §1 の \`\`\`bash ... \`\`\` 内 commands を 1 ブロックずつコピペ実行"
  exit 1
fi
# mode check (0600 必須、T09 drill private key 漏洩防止 invariant)
ACTUAL_MODE=$(stat -f "%Mp%Lp" ~/.taskhub/keys/approval-signing-key 2>/dev/null || stat -c "%a" ~/.taskhub/keys/approval-signing-key 2>/dev/null)
if [ "$ACTUAL_MODE" != "600" ]; then
  echo "❌ approval signing key mode は 0600 必須。現状 mode=$ACTUAL_MODE"
  echo "   修正: chmod 0600 ~/.taskhub/keys/approval-signing-key"
  exit 1
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

### §13.1 DATABASE_URL extraction

Pattern:

- source line: `^TASKMANAGEDAI_DATABASE_URL=`
- selector: `tail -n 1`
- host rewrite: `sed 's/postgres:/127.0.0.1:/g'`

```bash
# PR #90 で実装、--from-db mode で実 DB 上の audit_events を verify
# Codex PR #93 R1 F-003 fix (P2): .env.local には §1 で追記された TASKMANAGEDAI_DATABASE_URL
# と .env.example 由来の既存 line (コメント含む) の両方が match する可能性あり、
# 改行を含む不正 URL になる。`^TASKMANAGEDAI_DATABASE_URL=` で行頭固定 + `tail -n 1`
# で最後の未コメント行を 1 件だけ選ぶ。
DATABASE_URL=$(
  grep -E '^TASKMANAGEDAI_DATABASE_URL=' .env.local \
    | tail -n 1 \
    | cut -d= -f2- \
    | sed 's/postgres:/127.0.0.1:/g'
)
echo "DATABASE_URL (sanitized): $(
  printf '%s' "$DATABASE_URL" | sed 's|//[^@]*@|//***@|'
)"
# Codex PR #93 R1 F-003 fix の補正 (post-merge SOP polish 2026-05-22):
# `echo "$X" | grep -q $'\n'` は echo の末尾改行で常 match して常時 ERROR exit 1 になる
# bug 。`printf '%s'` で末尾改行を含めない pure value check に修正.
if [ -z "$DATABASE_URL" ] || printf '%s' "$DATABASE_URL" | grep -q $'\n'; then
  echo "❌ DATABASE_URL が空または改行を含む。.env.local を確認してください。"
  exit 1
fi
```

Expected output:

- sanitized DSN が `//***@` 形式で表示される
- 空文字または改行混入時は `❌ DATABASE_URL` で即 exit 1

### §13.2 Verify command and exit code

Pattern:

- command: `uv run taskhub verify --signed-journal --from-db`
- exit capture: `VERIFY_EXIT=$?`

```bash

# Codex PR #93 R1 F-004 fix の延長で pipefail を ON
set -o pipefail
uv run taskhub verify \
  --signed-journal \
  --from-db \
  --tenant-id 1 \
  --database-url "$DATABASE_URL" \
  2>&1 | tee /tmp/taskhub-verify.log
VERIFY_EXIT=$?
echo "Exit code: $VERIFY_EXIT"
```

Expected output:

- `Exit code: 0`
- `/tmp/taskhub-verify.log` が生成される

### §13.3 Failure grep coverage

Pattern:

- hard failures:
  `ERROR|FAILED|signature_verify_failed|journal_chain_gap|tenant_scope_violation|integrity_failed`
- DSN failures: `database_url|dsn|connection refused|connection timed out`

```bash
VERIFY_FAILURE_PATTERN='ERROR|FAILED|signature_verify_failed'
VERIFY_FAILURE_PATTERN="${VERIFY_FAILURE_PATTERN}|journal_chain_gap"
VERIFY_FAILURE_PATTERN="${VERIFY_FAILURE_PATTERN}|tenant_scope_violation"
VERIFY_FAILURE_PATTERN="${VERIFY_FAILURE_PATTERN}|integrity_failed"
VERIFY_FAILURE_PATTERN="${VERIFY_FAILURE_PATTERN}|database_url|dsn"
VERIFY_FAILURE_PATTERN="${VERIFY_FAILURE_PATTERN}|connection refused|connection timed out"
if grep -Eiq "$VERIFY_FAILURE_PATTERN" /tmp/taskhub-verify.log; then
  echo "❌ signed journal verify failure pattern detected:"
  grep -Ein "$VERIFY_FAILURE_PATTERN" /tmp/taskhub-verify.log
  exit 1
fi
if [ "$VERIFY_EXIT" -ne 0 ]; then
  echo "❌ signed journal verify exited non-zero: $VERIFY_EXIT"
  exit 1
fi
```

Expected output:

- failure pattern がなければ無出力で通過
- failure pattern があれば該当行番号を出して exit 1

### §13.4 Expected pass output grep

Pattern:

- empty chain acceptable: `tenant_scope_empty`
- non-empty chain acceptable: `signed_journal_verify_ok|journal_integrity_ok|verify_completed`

```bash
VERIFY_PASS_PATTERN='tenant_scope_empty|signed_journal_verify_ok|journal_integrity_ok|verify_completed'
if grep -Eiq "$VERIFY_PASS_PATTERN" /tmp/taskhub-verify.log; then
  echo "✅ signed journal verify emitted expected pass marker"
else
  echo "⚠️ signed journal verify exit 0 but no known pass marker was found; inspect /tmp/taskhub-verify.log"
fi
```

Expected output:

- 空 chain の場合 `tenant_scope_empty`
- populated chain の場合 `signed_journal_verify_ok` /
  `journal_integrity_ok` / `verify_completed` のいずれか

### §13.5 SSH / remote diagnostic grep

Pattern:

- SSH diagnostics:
  `ssh:|Permission denied|Host key verification failed|Connection refused|Connection timed out|Could not resolve hostname`

```bash
VERIFY_SSH_PATTERN='ssh:|Permission denied|Host key verification failed'
VERIFY_SSH_PATTERN="${VERIFY_SSH_PATTERN}|Connection refused"
VERIFY_SSH_PATTERN="${VERIFY_SSH_PATTERN}|Connection timed out"
VERIFY_SSH_PATTERN="${VERIFY_SSH_PATTERN}|Could not resolve hostname"
if grep -Eiq "$VERIFY_SSH_PATTERN" /tmp/taskhub-verify.log; then
  echo "❌ SSH / remote diagnostic pattern detected:"
  grep -Ein "$VERIFY_SSH_PATTERN" /tmp/taskhub-verify.log
  exit 1
fi
```

Expected output:

- local DB verify では SSH pattern は 0 件
- remote mode に切り替えた場合も SSH diagnostic は operator action として明示確認

### §13.6 Evidence capture

Pattern:

- evidence file: `/tmp/taskhub-verify.log`
- command echo: `Exit code: 0`

```bash
tail -50 /tmp/taskhub-verify.log
echo "Evidence: /tmp/taskhub-verify.log"
```

**確認項目**:
- [ ] exit 0 (audit_events が空でも tenant_scope check + chain integrity OK で PASS)
- [ ] 空 chain の場合 `tenant_scope_empty` 含む明示 message
- [ ] §13.3 hard failure grep 0 件
- [ ] §13.5 SSH / remote diagnostic grep 0 件

**失敗時**:
- `tenant_scope_empty` raise → backend 未動作 or tenant_id mismatch
- DSN error (sanitized) → `.env.local` の URL を再確認
- SSH diagnostic → local DB verify なのに remote path を踏んでいないか、`DATABASE_URL` と CLI option を再確認

## §14 taskhub backup real smoke (small DB) (C-9、20 min)

```bash
# pipefail を ON にして command 失敗を mask しない (Codex PR #93 R1 F-002/004/005 fix)
set -o pipefail

# macOS 標準 hash command の wrapper (Codex PR #93 R1 F-002 fix: macOS には sha256sum
# 標準で含まれない、`shasum -a 256` が標準。coreutils 入れている場合は sha256sum 経由 OK)
sha256_hex() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$@"
  else
    shasum -a 256 "$@"
  fi
}

# Codex PR #93 R1 F-005 fix (P2): age key 未生成時 fail-fast (旧 `age-keygen -y ... 2>/dev/null`
# は空入力 SHA256 を生成して進行、原因不明で backup 拒否される)
AGE_KEY_PATH="$HOME/.taskhub/keys/age.key.txt"
if [ ! -f "$AGE_KEY_PATH" ]; then
  echo "❌ age key 未生成: $AGE_KEY_PATH が存在しません。"
  echo "   先に SOPS 用 age key を生成してください:"
  echo "   mkdir -p ~/.taskhub/keys && chmod 0700 ~/.taskhub/keys"
  echo "   age-keygen -o ~/.taskhub/keys/age.key.txt && chmod 0600 ~/.taskhub/keys/age.key.txt"
  exit 1
fi

# §2.1 backup approval issue (operator-runbook §2.1)
BACKUP_APPROVAL_ID="mac-smoke-backup-$(date +%Y%m%d-%H%M%S)"
BACKUP_OUTPUT="$HOME/.taskhub/backups/mac-smoke-$(date +%Y-%m-%d).tar.age"
mkdir -p ~/.taskhub/backups

# age public key fingerprint (Mac の age key を使う、F-R1-002/005 fix で hash + key existence guard)
AGE_PUB=$(age-keygen -y "$AGE_KEY_PATH" 2>&1)
AGE_KEYGEN_EXIT=$?
if [ "$AGE_KEYGEN_EXIT" -ne 0 ] || [ -z "$AGE_PUB" ]; then
  echo "❌ age-keygen -y 失敗 (exit=$AGE_KEYGEN_EXIT)、$AGE_KEY_PATH が読めない or 形式不正"
  exit 1
fi
AGE_PUB_FP=$(printf '%s' "$AGE_PUB" | sha256_hex | cut -c1-64)
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
ARCHIVE_SHA256=$(sha256_hex "$BACKUP_OUTPUT" | cut -d' ' -f1)
echo "ARCHIVE_SHA256=$ARCHIVE_SHA256"

mkdir -p /tmp/mac-smoke-extract && cd /tmp/mac-smoke-extract
age -d -i "$AGE_KEY_PATH" "$BACKUP_OUTPUT" > decrypted.tar
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
- [ ] checksums verify (`cd extract && shasum -a 256 -c checksums.txt` on macOS、または coreutils 入れて `sha256sum -c`)
- [ ] private key 非混入
- [ ] pg_restore --list parse 成功
- [ ] /tmp/taskhub-backup-* cleanup verified (`ls /tmp/taskhub-backup-* 2>&1`、0 件 expected)

**失敗時**:
- destructive_lock_busy → 他 destructive op 進行中、operator-runbook §8 で復旧
- pg_dump fail → docker compose で postgres healthy 確認

## §15 golden flow Ticket→PR smoke (C-10、15-30 min)

BL-0140a の Research → Ticket → Plan → Approval → Runner → Draft PR の 12 step flow。本 SOP では skeleton smoke として:

```bash
# 12 step gold flow eval test を実行 (post-merge SOP polish 2026-05-22:
# 実 path は tests/integration/test_ticket_to_pr_smoke.py、SOP の旧 path
# tests/eval/ticket_to_pr_smoke は誤記)
uv run pytest tests/integration/test_ticket_to_pr_smoke.py -v 2>&1 | tail -20
echo "Exit code: $?"
# expected: 13 tests passed (0.02s 程度)
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
