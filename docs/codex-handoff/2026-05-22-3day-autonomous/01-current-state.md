# Current State Snapshot (2026-05-22 末尾、Codex handoff base)

本 file は Codex が 3 日間 autonomous 開始時の **現状 snapshot**。Claude が PR #100-#141 で完成させた基盤を踏まえ、Codex が継承する state を明示。

## 1. Sprint 完遂状況

### 1.1 直近完遂 (本 session = 2026-05-22 後半)

| Sprint | status | 完遂 PR | 概要 |
|---|---|---|---|
| SP-013 batch 0 | **completed** (2026-05-22) | PR #132-#141 (10 PR) | Multi-Agent Foundation core schema (10 standard role taxonomy + 3 new tables + agent_runs 8 cols + check_project_role_link trigger + sanitizer_policy_versions v1.0.0) |
| SP-012-11 | completed | PR #128-#131 | Ticket CRUD UI 本格版 (Server Actions + useActionState + project session resolve + dogfooding seed 229 Ticket) |
| SP-012-11.1 | completed | PR #129-#131 | Codex finding cascade fix (description nullable + PATCH detail GET + session resolve) |
| SP-012-10 | completed | PR #112-#127 | tickets API + frontend listing + dev login flow + frontend wiring |
| SP-012-7 | completed | PR #100-#111 | taskhub admin CLI + audit_event 詳細化 + Phase 7a 基盤 |
| SP-022 / P0 Exit | completed | PR #76-#99 | P0 Exit declaration + master plan §10-§11 update + 4 全体 audit |

### 1.2 直近 ADR accepted

| ADR | status | 内容 | accepted PR |
|---|---|---|---|
| ADR-00014 | accepted (2026-05-22) | Multi-Agent Orchestration Foundation | PR #109 |
| ADR-00019 | accepted (2026-05-22) | Role Taxonomy (10 standard roles) | PR #109 |
| ADR-00016 | accepted (2026-05-22) | sanitizer_policy_versions (PH-F-009 fix for SP-013/SP-018 split) | PR #139 関連 |

## 2. ready 状態の Sprint (Codex が着手する)

### 2.1 SP-014 (heavy、最優先 task-01)

- status: `ready` (2026-05-22 昇格、PR #141)
- target_days: 4 / max_days: 6
- adr_refs: ADR-00014 (accepted)
- planned_adr_refs: ADR-00009 update / Tool Registry network ADR (新規)
- 9 tickets (SP014-T01〜T09)
- kickoff_readiness: 全 prerequisite ✅ satisfied
- recommended_execution: **codex-all-loops mode=code 委譲**

### 2.2 SP-012-8 (medium、task-02)

- status: `ready` (本 session で SP-012-7 完遂後 ready)
- scope: UI 日本語化 (frontend/app/(admin)/**/*.tsx)
- ファイル数: ~25 frontend file
- batch 分割推奨: batch 1-7 (navigation / tickets / approvals / agent_runs / audit / settings / common)
- recommended_execution: codex-all-loops mode=code

### 2.3 SP-022-1 (small-medium、task-03)

- scope: Phase 7a deviation 7 件 (scripts hardening + Layer A/B/C SOP polish)
- 既知 deviation:
  1. `scripts/backup_orchestrator.py` の `--mac-mode` flag 未実装
  2. `scripts/backup_orchestrator.py` の `--remote` 引数バリデーション弱い
  3. `mac-single-host-smoke-sop.md` §13 grep coverage 強化
  4. `compose.yaml` healthcheck timeout / retries 調整
  5. `Dockerfile.eval` build-time COPY 順序 (Dockerfile build cache 効率)
  6. `scripts/seed_dev_login.py` のエラーハンドリング
  7. Layer C operator runbook §1-§9 (BackupApprovalClaim 6 field 化 + canonical fingerprint 15 field)
- recommended_execution: codex-all-loops mode=code (scope 中)

### 2.4 SP-012-9 残 (small、task-04)

- 既知未完了 (PR #119-#131 で多くは解消、残:)
  - Approvals page wiring (現在 stub)
  - Agent Runs page wiring (現在 placeholder)
  - Audit page wiring (現在 stub)
  - Settings page wiring (現在 stub)
- BL-TCU-007 (ApprovalRequest auto trigger) は **multi-user 化後** に deferred (本 task scope 外)
- recommended_execution: codex-all-loops mode=code (UI wiring 中心)

## 3. Mac local stack 状態 (継続起動中)

### 3.1 docker compose stack (5 services healthy)

```bash
docker compose ps
# postgres / redis / fastapi / nextjs / arq-worker = healthy
```

### 3.2 alembic head

```
0024_multi_agent_foundation_e (PR #140、check_project_role_link CREATE OR REPLACE で project + standard role accept)
```

### 3.3 DB seed 状況

| table | rows | seed source |
|---|---|---|
| `tenants` | 1 | tenant_id=1 (tenant-one) default |
| `projects` | 1 | DEFAULT_PROJECT_ID 確認済 |
| `actors` | N | dev login 経由生成 |
| `tickets` | 229 | dogfooding_seed.py (BL-DCS-001 全 BL + carry-over) |
| `standard_role_ids_mirror` | 10 | migration 0020 bulk_insert (immutable seed) |
| `project_agent_roles` | 0 | (custom role 未投入、SP-014 で利用) |
| `sanitizer_policy_versions` | 1 | v1.0.0 (migration 0023 seed) |

### 3.4 multi_agent contract test (30 件 PASS)

```bash
uv run pytest tests/multi_agent/ -q
# test_role_taxonomy_enum.py (13 件)
# test_standard_role_seed.py (3 件)
# test_agent_runs_role_columns.py (4 件)
# test_check_project_role_trigger.py (6 件)
# test_sanitizer_policy_versions.py (4 件)
# = 30 件 PASS
```

### 3.5 frontend test (累計 70+ vitest PASS)

```bash
cd frontend && pnpm vitest run
# Tickets CRUD form / list / detail components 70+ test PASS
```

## 4. Codex finding 状況 (cascade 終結確認)

### 4.1 本 session で close した finding

| PR | finding | severity | cascade depth | close PR |
|---|---|---|---|---|
| #119 | create_ticket_endpoint commit 抜け | P1 | 1 | #124 |
| #119 | update_ticket_endpoint commit 抜け | P1 | 1 | #124 |
| #121 | nonEmpty で PATCH explicit clear 無効 | P1 | 1 | #125 (clearableField helper) |
| #121 | DEFAULT_PROJECT_ID hardcode PATCH | P1 | 1 | #129 (session resolve) |
| #121 | DEFAULT_PROJECT_ID hardcode detail GET | P1 | 1 | #129 |
| #133 | validate_role_scope project + is_custom=False 不正 accept | P1 | 1→ | #135 |
| #135 | global + is_custom=True 不正 accept (cascade) | P1 | →2→ | #137 (matrix-based fix で cascade 終結) |
| #138 | trigger function で project + standard role reject | P1 | 1 | #140 (CREATE OR REPLACE で fix) |

### 4.2 cascade pattern 教訓 (Codex 厳守、`00-codex-behavior-guide.md` §6.4)

- PR #133 → #135 → #137 で **shallow `if a and b` fix が別 invariant 違反** を引き起こす cascade を体験
- **matrix-based logic** (`if scope == X: if not condition: raise`) で全 case 明示 enforce が cascade 終結 path
- Codex finding fix は **regression test を case ごと別 test function で追加** (1 case 1 test)

## 5. CLAUDE.md / .claude/rules/ 状態

### 5.1 直近更新 rules

- `.claude/rules/codex-usage-policy.md` §14 mandatory Codex review gates (Codex F-PR44-001/002 統合)
- `.claude/rules/sprint-pack-adr-gate.md` §12 ADR accepted promotion (Codex F-PR44-004 統合)
- `.claude/rules/branch-and-pr-workflow.md` (Phase D 圧縮 30 行 L1 reminder + `.claude/skills/branch-pr-workflow/SKILL.md` 移送)
- `.claude/rules/server-owned-boundary.md` (caller-supplied 経路禁止)
- `.claude/rules/cross-source-enum-integrity.md` (5+ source enum drift 防止)

### 5.2 直近更新 reference

- `.claude/reference/codex-multi-round-workflow.md` (Phase C で rules → reference 移送済)
- `.claude/reference/codex-output-contract.md`

## 6. branch / PR base

- **base branch**: `main` (origin/main HEAD `f10bef8a` = PR #141 merge SHA)
- 本 handoff PR から派生: Codex は **`origin/main` から直接 worktree 作成** (PR #141 後の state)

## 7. unresolved issue (Claude 戻り時の next action 候補)

### 7.1 deferred / carry-over

| 項目 | 移送先 | 理由 |
|---|---|---|
| BL-TCU-007 (ApprovalRequest auto trigger) | multi-user 化後 | self-approval 禁止 (Sprint 3) 違反、現状 1 actor のため意味なし |
| memory FK | SP-018 | memory backend 未着手 |
| 5 検証項目 backup drill | SP-018 / SP-022 | 物理 drill 必要 |
| orchestrator agent 本体 | **SP-014 (本 handoff task-01)** | SP-013 batch 0 で foundation のみ完成 |

### 7.2 既知 minor issue (Codex が判断で fix or defer 可)

- `frontend/app/(admin)/tickets/[id]/page.tsx` の loading state 未実装 (Suspense 想定)
- `frontend/app/(admin)/tickets/page.tsx` の pagination 未実装 (現在 1 page で 50 件 fixed)
- `frontend/app/(admin)/tickets/new/page.tsx` の form validation error message 表示位置 (現在 inline、toast 化検討)
- `backend/app/api/tickets.py` の `update_ticket_endpoint` で 404 vs 409 (concurrent update) のレース戦略 (現在 last-write-wins)

## 8. Claude 戻り時の next session entry path

3 日間後 (2026-05-25 夕方) に Claude が戻ったときの想定 path:

1. **本 handoff の `03-claude-verification-checklist.md` Read** (5 min)
2. **Codex 完了報告 `completion/task-NN-completed.md` 全件 Read** (15 min)
3. **`COMPLETION_REPORT.md` Read** (5 min)
4. **`STOPPED.md` 存在確認** (1 min、もしあれば緊急対応)
5. **Mac local stack 状態確認** (`docker compose ps` + alembic head + multi_agent test、5 min)
6. **Codex finding 採否判定 + fix PR 起票** (必要時、1-3 hour)
7. **Sprint Pack frontmatter `completed` 化確認** (10 min)
8. **次 Sprint (SP-015 / SP-016 / SP-018 等) kickoff 判断** (`02-task-priority-matrix.md` 参照、30 min)
