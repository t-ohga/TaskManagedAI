# task-01: SP-014 batch 0 — orchestrator agent core

**優先**: P0、**計画必須**: 必須 (heavy)、**self-review**: Plan 2 round + Impl 1 round 必須 (§3 Self-Review Protocol)、**想定 effort**: 1.5-2 day

> **重要**: `codex-all-loops` は Claude 専用 skill であり Codex 側からは呼べない。Codex は **§3 Self-Review Protocol** (`00-codex-behavior-guide.md` §3) に従い、自身の 1 session 内で plan-review + impl + adversarial-review を直列に self-execute する。

## 1. 目的

SP-014 orchestrator agent (司令塔) の **batch 0 core 実装**。SP-013 batch 0 で完成した Multi-Agent Foundation core schema の上に、orchestrator service + lease/heartbeat/failover/kill-switch + policy_profile + Tool Registry network enum + remote_agent_gateway deny-only stub + KPI rollup + SecretBroker multi-agent negative + event_type 22→31 拡張 を実装。

## 2. 起動 protocol (必須順序)

### 2.1 Read order (起動時)

1. `docs/codex-handoff/2026-05-22-3day-autonomous/README.md`
2. `docs/codex-handoff/2026-05-22-3day-autonomous/00-codex-behavior-guide.md` (全文必読)
3. `docs/codex-handoff/2026-05-22-3day-autonomous/01-current-state.md`
4. `docs/codex-handoff/2026-05-22-3day-autonomous/02-task-priority-matrix.md`
5. **本 file (task-01-sp014-batch-0-orchestrator.md)**
6. `docs/sprints/SP-014_orchestrator_agent.md` (Sprint Pack 本体、9 tickets + must_ship + 検証手順)
7. `docs/adr/00014_multi_agent_orchestration.md` (accepted、設計判断詳細)
8. `docs/adr/00019_role_taxonomy.md` (accepted、role 分類)
9. `.claude/rules/agentrun-state-machine.md` (event_type 22→31 拡張範囲)
10. `.claude/rules/secretbroker-boundary.md` (multi-agent negative 6 case)
11. `.claude/rules/server-owned-boundary.md` (caller-supplied 経路禁止)
12. `.claude/rules/cross-source-enum-integrity.md` (5+ source enum 整合)
13. `.claude/rules/sprint-pack-adr-gate.md` §12 ADR accepted promotion

### 2.2 worktree 作成

```bash
cd /Users/tohga/repo/TaskManagedAI
git worktree add .claude/worktrees/codex-task-01-sp014-batch-0 origin/main
cd .claude/worktrees/codex-task-01-sp014-batch-0
bash scripts/worktree_setup.sh  # 5-10 min (pnpm install + uv sync + SOPS 復号)
```

### 2.3 env

```bash
export TASKMANAGEDAI_DATABASE_URL='postgresql+asyncpg://taskmanagedai:taskmanagedai_local_smoke_pwd@127.0.0.1:5432/taskmanagedai'
export TASKMANAGEDAI_REDIS_URL='redis://127.0.0.1:6379/0'
export TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET='dummy-host-side-execute-8chars'
export TASKMANAGEDAI_DATABASE_URL_TEST='postgresql+asyncpg://taskmanagedai:taskmanagedai_local_smoke_pwd@127.0.0.1:5432/taskmanagedai_test'
export TASKMANAGEDAI_RUN_DB_TESTS=1
```

## 3. 計画 phase (必須、§3.1 Self-Plan-Review)

`00-codex-behavior-guide.md` §3.1 Self-Plan-Review の手順に従う:

**Round 1 (構造 review)**: docs/sprints/SP-014_orchestrator_agent.md + 関連 ADR + rules を Read、構造論点 (抜け漏れ / 整合性 / 曖昧さ / 依存 / 5+ source enum / cascade pattern リスク) を findings.md に列挙。

**Round 2 (敵対視点)**: SP-014 固有の敵対観点で深掘り:
- lease race condition (orchestrator が 2 instance 同時 active になる scenario)
- Tier 2 escape (agent decider が approval_requests に潜り込む経路)
- cascade pattern (policy_profile 14 rows seed の 1 行追加で別 invariant 違反)
- AgentRun status 拡張 (16 + 9 = 25 状態の transition 漏れ)
- SecretBroker multi-agent 6 negative case の reason_code 5+ source 整合
- event_type 22→31 拡張で既存 audit ledger との互換性

**Readiness Gate (Codex 自己判定)**: 採否判定 (adopt/reject/defer) を実施し plan file に反映、残存 CRITICAL=0/HIGH≤2 で `READY`、それ以外は `STOPPED.md` 起票。

### 3.1 計画 phase 確認 checklist

- [ ] SP014-T01〜T09 9 tickets の依存順序 (T01 → T02 → ... or 並行) 確定
- [ ] migration 順序 (`00NN_p0_1_orchestrator.py` + `00NN_p0_1_policy_profile.py`) 確定
- [ ] policy_profile_action_effects 14 rows seed 設計確定 (default + low_risk_auto_allow × 7 action_class)
- [ ] event_type 22→31 拡張 (orchestrator_dispatched + 5 件 等) 確定
- [ ] orchestrator_lease atomic claim SQL pattern 確定 (SP-012 lease pattern 参考、SecretBroker と同様)
- [ ] tier 2 human-only invariant 4 重防御 設計確定 (DB CHECK + service guard + Pydantic + test)
- [ ] ADR-00009 update + Tool Registry network ADR (新規) 起票 path 確定
- [ ] PE-F-014 SecretBroker 6 case (orchestrator agent decider 試行 / Tier 2 escape / actor_type mismatch / role_id mismatch / lease expired / progress lease 違反) reason_code 確定

## 4. 実装 phase (batch 分割)

### 4.1 batch 0a: orchestrator service module (T01)

**scope**: backend/app/services/orchestrator/ 新規 (約 5-8 file)

**Self-Impl-Review (§3.2)**:
- 実装 target: `backend/app/services/orchestrator` (files: `orchestrator.py,lease_manager.py,dispatcher.py,kill_switch.py,progress_lease.py`)
- 実装後 Self-Adversarial-Review 1 round (§3.2 Step 2、invariant 観点全件 check + boundary edge case + regression test)
- Readiness Gate: 残存 CRITICAL=0 で PR 起票可
- local verify (§3.2 Step 4): ruff + mypy + pytest 該当 dir clean

key invariant:
- **lease atomic claim**: SecretBroker と同等 pattern (UPDATE WHERE tenant_id=:t AND id=:r AND lease_token=:old_token AND lease_expires_at > now() RETURNING ...、0 rows = deny)
- **AgentRunEvent append**: lease renew / failover / kill / progress lease event を **同一 transaction で append** (status update と整合)
- **server-owned-boundary**: tenant_id / actor_id / role_id は session resolve、caller-supplied 排除
- **5+ source enum**: lease state (active / expired / kill_engaged) 5+ source (Literal + frozenset + Pydantic + pytest + DB CHECK)

### 4.2 batch 0b: review_artifacts 4 重防御 (T02)

**scope**: migration + backend model + service guard + Pydantic + test

**Self-Impl-Review (§3.2)**:
- 実装 target: `backend/app/db/models` (files: `review_artifact.py`)
- 実装後 Self-Adversarial-Review 1 round (§3.2 Step 2、invariant 観点全件 check + boundary edge case + regression test)
- Readiness Gate: 残存 CRITICAL=0 で PR 起票可
- local verify (§3.2 Step 4): ruff + mypy + pytest 該当 dir clean

4 重防御 enforcement:
1. **DB CHECK constraint**: `ck_review_artifact_action_class IN ('task_write', 'repo_write', 'pr_open', 'secret_access')`
2. **service layer guard**: `validate_review_artifact_for_action_class()` で artifact_hash + action_class 整合 check
3. **Pydantic Field validator**: `extra="forbid"` + action_class enum validate
4. **contract test**: `tests/multi_agent/test_review_artifact_4_defense.py` で 4 layer 全件 reject 確認

### 4.3 batch 0c: policy_profile + 14 rows seed (T03 + T04)

**scope**: migration (policy_profile + policy_profile_action_effects table 追加) + seed (14 rows exact) + ADR-00009 update accepted

**Self-Impl-Review (§3.2)**:
- 実装 target: `migrations/versions` (files: `00NN_p0_1_policy_profile.py`)
- 実装後 Self-Adversarial-Review 1 round (§3.2 Step 2、invariant 観点全件 check + boundary edge case + regression test)
- Readiness Gate: 残存 CRITICAL=0 で PR 起票可
- local verify (§3.2 Step 4): ruff + mypy + pytest 該当 dir clean

14 rows exact seed:
- profile=default × 7 action_class (task_write / repo_write / pr_open / secret_access / merge / deploy / read_only) = 7 rows
- profile=low_risk_auto_allow × 7 action_class = 7 rows
- 合計 14 rows、effect は ADR-00009 update に従う

ADR-00009 update **proposed → accepted 昇格**:
- frontmatter `status: proposed → accepted` + `updated_at: 2026-05-NN`
- Sprint Pack `adr_refs` に移動 (planned_adr_refs から削除)
- accepted promotion gate (`sprint-pack-adr-gate.md` §12): codex-plan-review R1 minimum + 採否判定

### 4.4 batch 0d: Tool Registry network enum + tool_network_policies (T05) + ADR 新規起票

**scope**: 新規 ADR 起票 + accepted promotion + migration + 既存 tool_registry table の network_access enum 化

**Self-Impl-Review (§3.2)**:
- 実装 target: `backend/app/services/tool_registry` (files: `network_policy.py`)
- 実装後 Self-Adversarial-Review 1 round (§3.2 Step 2、invariant 観点全件 check + boundary edge case + regression test)
- Readiness Gate: 残存 CRITICAL=0 で PR 起票可
- local verify (§3.2 Step 4): ruff + mypy + pytest 該当 dir clean

network_access enum:
- `none` (P0 default、web_fetch/docs_search 含む)
- `allowlist` (domain_allowlist 必須、payload_data_class_max + provider_required)
- `internet` (P0 deny、P0.1+ allowlist 経由のみ)

新規 ADR (`docs/adr/00021_tool_registry_network_enum.md`):
- status: `proposed` で起票 → 実装着手前 `accepted` 昇格
- title: "Tool Registry network_access enum + tool_network_policies"
- decision: boolean → enum 3 値 + 別 table

### 4.5 batch 0e: remote_agent_gateway P0.1 deny-only stub (T06)

**scope**: backend/app/services/remote_agent_gateway/ 新規 stub

**Self-Impl-Review (§3.2)**:
- 実装 target: `backend/app/services/remote_agent_gateway` (files: `gateway_stub.py`)
- 実装後 Self-Adversarial-Review 1 round (§3.2 Step 2、invariant 観点全件 check + boundary edge case + regression test)
- Readiness Gate: 残存 CRITICAL=0 で PR 起票可
- local verify (§3.2 Step 4): ruff + mypy + pytest 該当 dir clean

P0.1 stub:
- 全 request を `remote_agent_dispatch_denied` audit_event で deny
- audit payload: `{reason: 'p0_1_stub', tenant_id, actor_id, role_id, requested_remote_role}`
- contract test で stub deny 動作確認

### 4.6 batch 0f: KPI rollup query (T07) + SecretBroker multi-agent negative (T08) + event_type 22→31 (T09)

**scope**: metrics query + SecretBroker test + agent_run_events.event_type 拡張

**Self-Impl-Review (§3.2)**:
- 実装 target: `backend/app/services/metrics` (files: `orchestrator_kpi_rollup.py`)
- 実装後 Self-Adversarial-Review 1 round (§3.2 Step 2、invariant 観点全件 check + boundary edge case + regression test)
- Readiness Gate: 残存 CRITICAL=0 で PR 起票可
- local verify (§3.2 Step 4): ruff + mypy + pytest 該当 dir clean

key invariant:
- **recursive CTE**: parent_run_id traverse で orchestrator + child agents の totaled metric (time_to_merge / cost_per_completed_task / approval_wait_ms)
- **idempotency dedupe**: 同一 event を二重カウントしない (`distinct on (run_id, event_seq_no)`)
- **正本 source 限定**: eval_runs / eval_scores / agent_run_events.event_type='repo_pr_opened/provider_responded' / claims / evidence_items のみ参照、それ以外参照禁止

PE-F-014 SecretBroker 6 negative case (個別 reason_code):
1. orchestrator agent decider 試行 → `agent_decider_forbidden`
2. Tier 2 escape (agent decider attempt at policy_profile=auto_allow) → `tier_2_agent_decider_attempt`
3. actor_type mismatch (capability token issued for human but redeemed by agent) → `actor_type_mismatch`
4. role_id mismatch → `role_id_mismatch`
5. lease expired → `lease_expired_no_secret_access`
6. progress lease 違反 (no-progress 30 min) → `progress_lease_violated`

event_type 22→31 拡張 (`agentrun-state-machine.md` §6.1 P0.1+ extension):
- 29 `orchestrator_dispatched` / 30 `orchestrator_lease_renewed` / 31 `orchestrator_lease_expired` / 32 `orchestrator_failover_triggered` / 33 `orchestrator_kill_engaged` / 34 `inter_agent_message_sent_ref` / 35 `inter_agent_message_consumed_ref` / 36 `tool_web_fetch_executed` / 37 `tool_docs_search_executed`
- (28 + 9 = 37 統合は SP-014 で実装、29-31 は P0.1 sealed 解除後)
- migration: `00NN_p0_1_event_type_37.py` で `agent_run_events.event_type` CHECK 拡張
- 5+ source 整合: `backend/app/domain/agent_run/event_types.py` の `EVENT_TYPES: frozenset` 28 + 9 = 37 化

## 5. 検証手順 (各 batch 完了時)

### 5.1 全 batch 共通

```bash
# Backend lint + type + test
uv run ruff check backend tests
uv run mypy backend
uv run pytest tests/multi_agent/ -q

# Migration check + apply
uv run alembic check
uv run alembic upgrade head

# SP-014 専用 test
uv run pytest tests/multi_agent/test_orchestrator_lease_failover.py \
              tests/multi_agent/test_progress_lease.py \
              tests/multi_agent/test_max_limits.py \
              tests/multi_agent/test_action_class_3tier.py \
              tests/multi_agent/test_orchestrator_requester_only.py \
              tests/multi_agent/test_review_artifact_4_defense.py \
              tests/security/test_secretbroker_multi_agent_negative.py \
              tests/multi_agent/test_remote_agent_gateway_p0_1_stub.py \
              tests/metrics/test_*_rollup*.py \
              tests/policy/test_action_class_enum.py \
              tests/policy/test_policy_profile_seed.py -q
```

### 5.2 stress test (batch 0a 完了時)

```bash
# 60s heartbeat 失敗 → failover シナリオ
uv run pytest tests/multi_agent/test_orchestrator_lease_failover.py::test_60s_heartbeat_failure_failover -v

# progress lease no-progress 30 min → blocked + runtime_blocked
uv run pytest tests/multi_agent/test_progress_lease.py::test_no_progress_30min_blocked -v
```

## 6. PR 起票 + admin bypass merge

### 6.1 branch + PR

```bash
git push -u origin feat/sp014-batch-0a-orchestrator-lease-manager-2026-05-23
gh pr create --base main --head feat/sp014-batch-0a-orchestrator-lease-manager-2026-05-23 \
  --title "feat(sp014-batch-0a): orchestrator service module + lease_manager (T01)" \
  --body "$(cat <<'EOF'
## Summary
SP-014 batch 0a: orchestrator service module + lease_manager / heartbeat / failover / kill_switch / progress_lease 実装

## self-review verdict (§3 Self-Review Protocol)
- Self-Plan-Review Round 1+2: R{N} clean、{M} findings 100% adopt、Readiness Gate READY
- Self-Impl-Review: R{N} clean、{M} findings 100% adopt

## invariant 遵守
- lease atomic claim: ✅ UPDATE WHERE + RETURNING、0 rows = deny audit
- AgentRunEvent append: ✅ status update と同一 transaction
- server-owned-boundary: ✅ tenant_id / actor_id / role_id は session resolve、caller-supplied なし
- 5+ source enum: ✅ Literal + frozenset + Pydantic + pytest + DB CHECK

## ADR Gate
非該当 (SP-014 batch 0a は既存 ADR-00014 / ADR-00019 の implementation phase、Criteria 11 種いずれも新規該当なし)
EOF
)"
```

### 6.2 merge

`00-codex-behavior-guide.md` §4.4 の admin bypass merge 6 条件を満たす PR のみ merge。

### 6.3 Codex auto-review baseline (必須)

```bash
sleep 60  # Codex auto-review trigger 待ち
.claude/scripts/codex_pr_full_review.sh <PR_NUM> 2>&1 | head -200
```

採否判定 + adopt fix commit (merge 前 or follow-up PR)。

## 7. DoD checklist (本 task 全完了時)

- [ ] SP014-T01〜T09 全 ticket 実装完了
- [ ] policy_profile_action_effects 14 rows exact seed verify
- [ ] orchestrator lease/failover stress test (60s heartbeat 失敗 → failover) PASS
- [ ] max_* 違反全件 reject + 絶対上限 (children≤20/depth≤5/turns≤500/budget≤$50) DB CHECK で破れない
- [ ] Tier 2 で agent decider 経路残存しない (4 重防御 negative test)
- [ ] SecretBroker 6 negative case 個別 reason_code で deny + audit
- [ ] AC-HARD-01 fixture (multi-agent 文脈) 全件 deny
- [ ] ADR-00009 update accepted (`status: accepted`, `updated_at: 2026-05-NN`)
- [ ] Tool Registry network ADR 新規 accepted (`docs/adr/00021_tool_registry_network_enum.md`)
- [ ] event_type 22→31 拡張 5+ source 整合確認
- [ ] migration `00NN_p0_1_*.py` 2 件 Mac local apply + downgrade 動作確認
- [ ] Sprint Pack frontmatter `status: ready → completed` + Review 章追加
- [ ] 完了報告 `completion/task-01-completed.md` 起票
- [ ] handoff memory 1 行追記

## 8. blocker / 緊急停止 trigger

- Codex 3 連続失敗 (rate limit / auth / timeout)
- spec 衝突 (本 file vs 既存 Sprint Pack / ADR)
- **ADR Gate Criteria 11 種に該当する追加変更** (例: GitHub App permission 変更、新規認証 method) → STOPPED.md 起票
- migration rollback 不能 (downgrade で 既存 DB state 破壊リスク)
- 想定 effort 大幅超過 (2 day → 4 day 超え pattern が確実)

## 9. 関連参照

- `docs/sprints/SP-014_orchestrator_agent.md` (Sprint Pack 本体)
- `docs/adr/00014_multi_agent_orchestration.md` (accepted)
- `docs/adr/00019_role_taxonomy.md` (accepted)
- `docs/adr/00004_*.md` (event_type 更新 contract)
- `.claude/rules/agentrun-state-machine.md` §6.1 (event_type 22→31 拡張)
- `.claude/rules/secretbroker-boundary.md` §8 (atomic claim + actor binding)
- `.claude/rules/server-owned-boundary.md` (caller-supplied 経路禁止)
- `.claude/rules/cross-source-enum-integrity.md` (5+ source enum)
- `.claude/rules/codex-usage-policy.md` §14 mandatory Codex review gates
- `.claude/rules/sprint-pack-adr-gate.md` §12 ADR accepted promotion
- 過去類似 batch: PR #133-#140 (SP-013 batch 0、Multi-Agent Foundation core schema)
