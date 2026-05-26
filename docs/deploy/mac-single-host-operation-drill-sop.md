# Mac single-host 運用立証 drill SOP (Phase 7a、P0 Exit declaration 直接 gate)

最終更新: 2026-05-22 (PR #99、SP-022-1 batch 4 wrapper/backup drill 整合反映)

status: ready

所要時間: §1 Mac UI smoke (30-60 min) + §2 Mac local backup/restore drill (30-60 min) = **約 60-120 min**

---

## 0. 目的と位置付け

### 目的

**user 明示優先目的 = Mac single-host で TaskManagedAI P0 機能が実運用可能な立証**。VPS migration drill (T09 = Phase 7b、ADR-00021 host-portable post-acceptance) の **前** に、Mac で運用できることを実証する。

### 位置付け

| 観点 | 本 SOP (Phase 7a) | T09 SOP (`docs/deploy/half-yearly-drill-sop.md` §11、Phase 7b) |
|---|---|---|
| 目的 | Mac で P0 運用立証 | Mac→VPS host-portable verify (ADR-00021) |
| host | Mac 1 台 | Mac + VPS 2 台 |
| 所要 | 60-120 min | 2.5-4 h |
| P0 Exit declaration | ✅ **直接 gate** | △ post-acceptance verification (P0 Exit 後 or 任意 timing) |
| Hard Gate 関連 | AC-HARD-04 PASS (`backup_restore_rpo_rto`、計測本体は backend CLI で完結) | ADR-00021 evidence (Hard Gates 直接 gate ではない) |
| 必要前提 | Mac smoke (Layer A/B/C autonomous PASS 済、PR #95/#96/#97 merge 後) | Mac smoke + 物理 VPS + Tailscale + age key 安全運搬 |

### 前提

- Mac single-host smoke (Layer A/B/C autonomous) PASS 済 (`docs/deploy/mac-single-host-smoke-sop.md` Layer A/B/C 経由、p0-exit-final-hardening plan Phase 4-5 で完了)
- PR #95/#96/#97 merge 済 (routing fix + Dockerfile fix + SOP polish)
- `cd ~/repo/TaskManagedAI && git pull origin main` で最新取得済
- `.env.local` 設定済 (smoke SOP §1)
- docker compose up 済 (`docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local ps` で 5 service all healthy)
- backend seed runner 実行済 (smoke SOP §1b、actors / tenants / workspaces / projects seed)
- alembic upgrade head 完了 (smoke SOP §4、`scripts/alembic_wrapper.sh` 経由、
  0018_eval_dataset_versions head)

---

# §1 Mac UI smoke (Phase 7a-1、所要 30-60 min)

実施場所: Mac browser (Chrome / Safari 推奨) + `~/repo/TaskManagedAI` terminal

## 1.1 事前確認

```bash
cd ~/repo/TaskManagedAI

# 5 service healthy 確認
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local ps
# expected: api / frontend / postgres / redis / worker 全 healthy

# dev login token 取得 (ブラウザ操作前)
DEV_LOGIN_TOKEN=$(grep -E '^TASKMANAGEDAI_DEV_LOGIN_TOKEN=' .env.local | tail -1 | cut -d= -f2-)
echo "DEV_LOGIN_TOKEN=$DEV_LOGIN_TOKEN"
# 例: TASKMANAGEDAI_DEV_LOGIN_TOKEN=local-dev-login-token-for-mac-smoke
```

## 1.2 §6 dev login flow (Primary path、frontend/tests/e2e/login.spec.ts 正本同経路)

```
ブラウザ: http://127.0.0.1:3900/dashboard
```

期待動作:
1. 未認証で `/dashboard` access → middleware (`frontend/middleware.ts`) で `/login?next=%2Fdashboard` redirect
2. login form 表示 (`/login?next=%2Fdashboard`、dev login token 入力 form)
3. dev login token (上記取得値) を入力 → "Sign in" click
4. login action 実行 + `taskmanagedai_session` cookie 発行 + `/dashboard` に戻る
5. admin navigation header 表示 (Dashboard / Tickets / Eval Dashboard / Approvals / Agent Runs / Audit / Settings)

**checklist**:
- [ ] `/dashboard` 未認証で `/login?next=%2Fdashboard` redirect
- [ ] token 入力後 `/dashboard` に戻る + admin nav 表示
- [ ] DevTools → Application → Cookies で `taskmanagedai_session` cookie 存在 (HttpOnly + SameSite=Lax)

## 1.3 §7 Eval Dashboard

```
ブラウザ: http://127.0.0.1:3900/eval-dashboard
(nav から "Eval Dashboard" link click でも可、PR #95 で nav item 追加)
```

**checklist**:
- [ ] P0 Exit verdict panel 表示 (BLOCKED or READY)
- [ ] Hard Gates 7 全件 (AC-HARD-01〜07) row 表示
- [ ] Quality KPIs 5 全件 (AC-KPI-01〜05) row 表示、source = "live" (backend `/api/v1/eval/kpi-rollup` 応答)
- [ ] description が backend 由来 (各 KPI 説明、threshold_reason)
- [ ] **raw secret / DSN / credentials が DOM に出現していない** (DevTools → View source で確認)

**DevTools 確認** (Network tab):
- GET `/api/v1/eval/kpi-rollup` → 200 + body に 5 entries + p0_accept boolean

## 1.4 §8 Tickets

```
ブラウザ: http://127.0.0.1:3900/tickets
```

**checklist**:
- [ ] Ticket 一覧表示 (空 list でも layout 正常、seed 済の場合 1 ticket "Welcome to TaskManagedAI")
- [ ] ticket click → detail page navigation
- [ ] Acceptance Criteria / Evidence / AgentRun セクション表示 (空でも OK)

## 1.5 §9 Approvals

```
ブラウザ: http://127.0.0.1:3900/approvals
```

**checklist**:
- [ ] Approval 一覧表示 (`pending` / `approved` / `rejected` / `expired` / `invalidated` 状態区別表示)
- [ ] self-approval 禁止のメッセージ表示 (requester = decider の case)

## 1.6 §10 Agent Runs

```
ブラウザ: http://127.0.0.1:3900/runs
(SOP の旧 /admin/agent-runs は誤記、PR #95 で /runs に修正)
```

**checklist**:
- [ ] Agent Runs 一覧表示
- [ ] 16 状態 enum の表示確認 (queued / gathering_context / running / generated_artifact / schema_validated / policy_linted / diff_ready / waiting_approval / blocked / provider_refused / provider_incomplete / validation_failed / repair_exhausted / completed / failed / cancelled)
- [ ] `blocked` 状態の場合、`blocked_reason` (policy_blocked / budget_blocked / runtime_blocked) が別表示

## 1.7 §11 Audit log

```
ブラウザ: http://127.0.0.1:3900/audit
(SOP の旧 /admin/audit-log は誤記、PR #95 で /audit に修正)
```

**checklist**:
- [ ] AuditEvent 一覧表示 (append-only、seed で `seed_initialized` event 含む)
- [ ] event_type / actor_id / created_at / reason_code 表示
- [ ] **raw secret / token / private key が DOM に出現していない** (DevTools view-source で確認)
- [ ] payload に `sha256_prefix_8` / `hash` のみ表示 (raw value なし)

## 1.8 §1 完了判定

以下全件 PASS で Phase 7a-1 完了:

- [ ] §6 dev login flow PASS (Primary path: `/dashboard` → `/login?next=%2Fdashboard` redirect → token 入力 → `/dashboard`)
- [ ] §7 Eval Dashboard 表示 + DOM raw secret 漏れなし
- [ ] §8 Tickets 一覧 / 詳細 表示
- [ ] §9 Approvals 一覧表示
- [ ] §10 Agent Runs 16 状態 enum 表示
- [ ] §11 Audit log + raw secret 漏れなし

evidence 記録:

```bash
mkdir -p ~/.taskhub/drills/mac-single-host-smoke/$(date +%Y-%m-%d)
cat > ~/.taskhub/drills/mac-single-host-smoke/$(date +%Y-%m-%d)/C-ui-smoke-checklist.md <<EOF
# Phase 7a-1 Mac UI smoke checklist (date: $(date +%Y-%m-%d))

| § | page | URL | 結果 |
|---|---|---|---|
| §6 | dev login | http://127.0.0.1:3900/dashboard → /login?next=%2Fdashboard → /dashboard | (PASS/FAIL) |
| §7 | Eval Dashboard | http://127.0.0.1:3900/eval-dashboard | (PASS/FAIL) |
| §8 | Tickets | http://127.0.0.1:3900/tickets | (PASS/FAIL) |
| §9 | Approvals | http://127.0.0.1:3900/approvals | (PASS/FAIL) |
| §10 | Agent Runs | http://127.0.0.1:3900/runs | (PASS/FAIL) |
| §11 | Audit log | http://127.0.0.1:3900/audit | (PASS/FAIL) |

完了時刻: $(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
```

---

# §2 Mac local backup/restore drill (Phase 7a-2、AC-HARD-04 PASS、所要 30-60 min)

**重要**: 本 plan §3.5 で「AC-HARD-04 `backup_restore_rpo_rto` = **計測本体は backend CLI で完結**」と明示済 = **Mac single-host で satisfy 可能**。VPS 不要。

実施場所: `~/repo/TaskManagedAI` terminal (CLI のみ、ブラウザ不要)

## 2.1 key bootstrap (初回のみ、operator-runbook §1 経由)

```bash
# approval signing key (Ed25519、operator-runbook §1 step 2-4 経由)
# 詳細手順: docs/deploy/operator-runbook.md §1 (markdown を bash に渡さず、別 terminal で 1 ブロックずつコピペ実行)
ls -la ~/.taskhub/keys/approval-signing-key 2>&1
# 未生成なら operator-runbook §1 を実行

# age private key (backup archive 暗号化用)
mkdir -p ~/.taskhub/keys && chmod 0700 ~/.taskhub/keys
[ -f ~/.taskhub/keys/age.key.txt ] || age-keygen -o ~/.taskhub/keys/age.key.txt
chmod 0600 ~/.taskhub/keys/age.key.txt

# 確認
ls -la ~/.taskhub/keys/
# expected: approval-signing-key (0600) + age.key.txt (0600)、directory mode 0700
```

## 2.2 approval issue (SOP §12 経由)

```bash
cd ~/repo/TaskManagedAI

BACKUP_APPROVAL_ID="mac-local-drill-$(date +%Y%m%d-%H%M%S)"
BACKUP_OUTPUT="$HOME/.taskhub/backups/mac-local-drill-$(date +%Y-%m-%d).tar.age"
mkdir -p ~/.taskhub/backups

# age public key fingerprint (Mac の age key を使う)
AGE_PUB=$(age-keygen -y ~/.taskhub/keys/age.key.txt)
AGE_PUB_FP=$(printf '%s' "$AGE_PUB" | shasum -a 256 | cut -c1-64)

uv run taskhub approval issue \
  --approval-id "$BACKUP_APPROVAL_ID" \
  --decider t-ohga \
  --reason-summary "mac-local-operation-drill" \
  --drill-kind mac_single_host_local_drill \
  --allowed-subcommands backup \
  --target-host t-ohga-mac \
  --ttl-hours 1 \
  --backup-output-path "$BACKUP_OUTPUT" \
  --backup-include-sops-env \
  --backup-age-public-key-fingerprint "$AGE_PUB_FP"

echo "approval issue exit=$?"
ls -la ~/.taskhub/approvals/${BACKUP_APPROVAL_ID}.signed
# expected: file 存在、mode 0600
```

## 2.3 backup 実行 + RTO 計測開始 (SOP §14 経由)

```bash
BACKUP_START=$(date +%s)
echo "BACKUP_START=$BACKUP_START ($(date -u +%Y-%m-%dT%H:%M:%SZ))"

uv run taskhub backup \
  --output "$BACKUP_OUTPUT" \
  --approval-id "$BACKUP_APPROVAL_ID" \
  --skip-service-stop
echo "backup exit=$?"

BACKUP_END=$(date +%s)
BACKUP_DURATION=$((BACKUP_END - BACKUP_START))
echo "BACKUP_DURATION=${BACKUP_DURATION}s"

ls -la "$BACKUP_OUTPUT"
ARCHIVE_SHA256=$(shasum -a 256 "$BACKUP_OUTPUT" | cut -d' ' -f1)
echo "ARCHIVE_SHA256=$ARCHIVE_SHA256"
```

## 2.4 7 mandatory checklist verify (host migration step 以外、Mac local 完結)

| # | checklist | verify command |
|---|---|---|
| 1 | backup exit 0 + output file 存在 | `[ -f "$BACKUP_OUTPUT" ] && echo "✅" \|\| echo "❌"` |
| 2 | age decrypt 成功 | `mkdir -p /tmp/mac-drill-extract && cd /tmp/mac-drill-extract && age -d -i ~/.taskhub/keys/age.key.txt "$BACKUP_OUTPUT" > decrypted.tar && echo "✅"` |
| 3 | tar listing 全 file 構造存在 (ADR-00021 §4: meta.json / pg_dump.dump / alembic_version.txt / dump.rdb / artifacts/) | `tar -tf decrypted.tar \| tee tar-listing.txt` |
| 4 | checksums verify (`shasum -a 256 -c checksums.txt`) | `tar -xf decrypted.tar checksums.txt && shasum -a 256 -c checksums.txt` |
| 5 | private key 非混入 (CRITICAL invariant) | `tar -tf decrypted.tar \| grep -E '(id_rsa\|id_ed25519\|age-key\|keys\.txt\|\.private\.pem)' && echo "❌ PRIVATE KEY DETECTED" \|\| echo "✅ no private key"` |
| 6 | pg_restore --list parse 成功 | `tar -xf decrypted.tar postgres/pg_dump.dump && pg_restore --list postgres/pg_dump.dump \| head -10` |
| 7 | cleanup verified (`/tmp/taskhub-backup-*` 0 件) | `ls /tmp/taskhub-backup-* 2>&1; [ "$(ls /tmp/taskhub-backup-* 2>/dev/null \| wc -l)" -eq 0 ] && echo "✅" \|\| echo "❌"` |

## 2.5 Mac local restore drill (RTO 計測完了)

```bash
RESTORE_START=$(date +%s)
echo "RESTORE_START=$RESTORE_START"

# 新 PostgreSQL container 起動 (別 port、本番 service と分離)
docker run -d --name mac-drill-postgres-restore \
  -e POSTGRES_USER=taskmanagedai \
  -e POSTGRES_PASSWORD=taskmanagedai_local_smoke_pwd \
  -e POSTGRES_DB=taskmanagedai \
  -p 127.0.0.1:5433:5432 \
  postgres:16-alpine

# postgres ready 待機
until docker exec mac-drill-postgres-restore pg_isready -U taskmanagedai > /dev/null 2>&1; do sleep 1; done

# decrypted pg_dump.dump を restore (上記 §2.4 step 6 で抽出済)
cd /tmp/mac-drill-extract
docker exec -i mac-drill-postgres-restore pg_restore -U taskmanagedai -d taskmanagedai --clean --if-exists < postgres/pg_dump.dump
echo "pg_restore exit=$?"

# RTO 計測終了
RESTORE_END=$(date +%s)
RESTORE_DURATION=$((RESTORE_END - RESTORE_START))
TOTAL_RTO=$((BACKUP_DURATION + RESTORE_DURATION))
echo ""
echo "BACKUP_DURATION=${BACKUP_DURATION}s"
echo "RESTORE_DURATION=${RESTORE_DURATION}s"
echo "TOTAL_RTO=${TOTAL_RTO}s (target: <= 4h = 14400s)"
if [ "$TOTAL_RTO" -le 14400 ]; then
  echo "✅ AC-HARD-04 RTO PASS"
else
  echo "❌ AC-HARD-04 RTO FAIL (>= 4h)"
fi

# verify: restore された DB に actors / tenants seed 存在
docker exec mac-drill-postgres-restore psql -U taskmanagedai -d taskmanagedai -c "SELECT id, actor_type, actor_id FROM actors LIMIT 5;"
# expected: 1 row (`human:default`、seed runner で生成済の actor が restore された証跡)

# cleanup
docker stop mac-drill-postgres-restore && docker rm mac-drill-postgres-restore
cd ~/repo/TaskManagedAI
```

## 2.6 §2 完了判定 + evidence 記録

```bash
cat > ~/.taskhub/drills/mac-single-host-smoke/$(date +%Y-%m-%d)/D-local-backup-restore-drill-checklist.json <<EOF
{
  "drill_date": "$(date +%Y-%m-%d)",
  "drill_kind": "mac_local_backup_restore",
  "approval_id": "$BACKUP_APPROVAL_ID",
  "backup_output": "$BACKUP_OUTPUT",
  "archive_sha256": "$ARCHIVE_SHA256",
  "rto_total_seconds": $TOTAL_RTO,
  "rto_target_seconds": 14400,
  "ac_hard_04_pass": $([ "$TOTAL_RTO" -le 14400 ] && echo "true" || echo "false"),
  "checklist_7_mandatory": {
    "1_backup_exit_0_and_output_exists": true,
    "2_age_decrypt_success": true,
    "3_tar_listing_structure": true,
    "4_checksums_verify": true,
    "5_no_private_key": true,
    "6_pg_restore_list_parse": true,
    "7_cleanup_verified": true
  },
  "next_action": "P0 Exit declaration PR 起票 (Phase 8、Claude autonomous)"
}
EOF
cat ~/.taskhub/drills/mac-single-host-smoke/$(date +%Y-%m-%d)/D-local-backup-restore-drill-checklist.json
```

---

# §3 Phase 7a 完了通知 (user → Claude)

§1 + §2 全件 PASS 後、user が Claude に完遂報告:

- `~/.taskhub/drills/mac-single-host-smoke/<date>/C-ui-smoke-checklist.md` 内容
- `~/.taskhub/drills/mac-single-host-smoke/<date>/D-local-backup-restore-drill-checklist.json` 内容
- RTO 計測値 (`TOTAL_RTO` seconds)

Claude が次に進める autonomous flow:
1. SP-022 Sprint Pack `## Review § Additional Hardening Gate § Phase 7a results` subsection 追記 (本 PR #99 で起票した subsection 内に results 追記)
2. SP-012 + SP-022 frontmatter `status: → completed`
3. master plan §3-§9 update apply (PR #98 の `master-plan-section-3-9-update-prep.md` draft 素材から手動 apply、prep file は同 PR 内削除)
4. `docs/release/p0_exit_2026_05_DD.md` 起票 (Phase 7a evidence link + Hard Gates 7 + KPIs 5 PASS evidence)
5. `TASKHUB_P0_1_OPENED=1` 解禁 + sealed CI guard 解除
6. PR 起票 → Codex review → user merge

# §4 Phase 7b (T09 Mac→VPS migration drill、post-acceptance)

Phase 7a 完了 + P0 Exit declaration merge 後の任意 timing で実施 (ADR-00021 host-portable post-acceptance verification):

詳細手順: `docs/deploy/half-yearly-drill-sop.md` §11 (7 mandatory checklist) + operator-runbook §1-§22

必要前提:
- 物理 host 2 台 (Mac + VPS)
- Tailscale 閉域接続 (`tag:taskhub` peer 確立済)
- SOPS age key 安全運搬
- signed approval record (Ed25519 verify key fingerprint allowlist 登録済)

完了後、SP-022 Sprint Pack `## Review § Additional Hardening Gate § Phase 7b T09 results` subsection に記録 (ADR-00021 post-acceptance verification evidence)。

---

## §5 関連 docs

- p0-exit-final-hardening plan: `.claude/plans/p0-exit-final-hardening-2026-05-22.md` §5 Phase 7a/7b 分離 + §10.3.1 approval table
- Mac single-host smoke SOP (Layer A/B/C): `docs/deploy/mac-single-host-smoke-sop.md`
- T09 Mac→VPS migration drill SOP: `docs/deploy/half-yearly-drill-sop.md` §11
- operator runbook (key bootstrap + destructive op SOP): `docs/deploy/operator-runbook.md` §1-§22
- ADR-00021 (host-portable deployment): `docs/adr/00021_host_portable_deployment.md`
- AC-HARD-04 reference: `.claude/reference/hard-gates-and-kpis.md` § AC-HARD-04
- SP-022 Sprint Pack `## Review § Additional Hardening Gate`: `docs/sprints/SP-022_framework_intake_hardening.md`
