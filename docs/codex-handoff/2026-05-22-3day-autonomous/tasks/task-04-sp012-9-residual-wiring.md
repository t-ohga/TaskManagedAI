# task-04: SP-012-9 残 wiring — Approvals / Agent Runs / Audit / Settings

**優先**: P2、**計画必須**: 推奨、**self-review**: Plan 1 round + Impl 1 round 推奨 (§3 Self-Review Protocol)、**想定 effort**: 0.5-1 day

> `codex-all-loops` は Claude 専用 skill (`00-codex-behavior-guide.md` §3.0)。Codex は self-review で同等観点を確保。

## 1. 目的

SP-012-9 で未完了の **Approvals / Agent Runs / Audit / Settings** page wiring (現在 stub / placeholder)。tickets page (SP-012-10/11 で本格実装済) の pattern を流用して read-only listing + detail を完成させる。

**注意**: BL-TCU-007 (ApprovalRequest auto trigger) は **multi-user 化後 deferred**。本 task scope 外。

## 2. 起動 protocol

### 2.1 Read order

1. `docs/codex-handoff/2026-05-22-3day-autonomous/README.md`
2. `docs/codex-handoff/2026-05-22-3day-autonomous/00-codex-behavior-guide.md`
3. `docs/codex-handoff/2026-05-22-3day-autonomous/01-current-state.md`
4. **本 file**
5. `docs/sprints/SP-012-9_admin_page_wiring.md` (Sprint Pack 本体、なければ task 完了時に起票)
6. **既存 pattern 参考**: `frontend/app/(admin)/tickets/page.tsx` + `[id]/page.tsx` (本格実装済)
7. `backend/app/api/approvals.py` / `agent_runs.py` / `audit.py` / `settings.py` (各 endpoint 確認)

### 2.2 worktree

```bash
cd /Users/tohga/repo/TaskManagedAI
git worktree add .claude/worktrees/codex-task-04-sp012-9-residual origin/main
cd .claude/worktrees/codex-task-04-sp012-9-residual
bash scripts/worktree_setup.sh
```

## 3. 計画 phase (推奨、軽い)

**Self-Plan-Review (§3.1) Round 1 のみ**: 構造論点列挙 + 採否判定後着手 (敵対視点 Round 2 は scope 内 adversarial 観点少なめのため省略可)

## 4. 実装 phase

### 4.1 batch 1: Approvals page wiring

**scope**: `frontend/app/(admin)/approvals/` (page.tsx + [id]/page.tsx)

- list endpoint: `GET /api/v1/approvals?status=pending` (server-owned tenant_id + project_id resolve)
- detail endpoint: `GET /api/v1/approvals/{id}`
- mutation (approve/reject) は **defer** (multi-user 化後、SP-018)
- read-only listing + detail のみ実装

key invariant:
- **server-owned-boundary §1**: tenant_id / project_id / actor_id は session 経由 (Depends)
- caller-supplied 経路なし
- pagination: 50 件 fixed (本格 pagination は SP-018)

### 4.2 batch 2: Agent Runs page wiring

**scope**: `frontend/app/(admin)/agent-runs/`

- list endpoint: `GET /api/v1/agent-runs?status=*&role=*`
- detail endpoint: `GET /api/v1/agent-runs/{id}` (status + role + lease + last_progress_at 表示)
- AgentRun 16 状態 全件表示対応 (`agentrun-state-machine.md` §1)
- AgentRunEvent timeline 表示 (`event_type` 22 件、後の P0.1 で 37 件へ)
- resume/cancel mutation は **defer** (SP-018)

### 4.3 batch 3: Audit page wiring

**scope**: `frontend/app/(admin)/audit/`

- list endpoint: `GET /api/v1/audit-events?event_type=*&actor_id=*`
- raw secret なし invariant (audit payload は redacted)
- filter (event_type / actor_id / timestamp range)
- export は **defer** (SP-018)

### 4.4 batch 4: Settings page wiring

**scope**: `frontend/app/(admin)/settings/`

- list endpoint: `GET /api/v1/me/projects` (current actor の project 一覧)
- current project 切替 (cookie-based session 更新)
- provider config 読み出しのみ (mutation は defer、SP-018)

## 5. 検証手順

### 5.1 各 batch 完了時

```bash
cd frontend
pnpm typecheck
pnpm lint
pnpm vitest run

# backend
uv run ruff check backend tests
uv run mypy backend
uv run pytest tests/api/test_approvals.py tests/api/test_agent_runs.py tests/api/test_audit.py tests/api/test_settings.py -q
```

### 5.2 E2E (推奨)

```bash
# Mac local stack で manual smoke
docker compose ps  # 5 services healthy
curl -X GET 'http://localhost:3000/api/v1/approvals?status=pending' \
  -H "Cookie: $(cat .claude/local/dev-cookie.txt)"
# 期待: 200 + JSON array (current state は 0 件 = empty array)
```

## 6. PR 起票 + admin bypass merge

```bash
git push -u origin feat/sp012-9-batch-1-approvals-wiring-2026-05-25
gh pr create --base main --head feat/sp012-9-batch-1-approvals-wiring-2026-05-25 \
  --title "feat(sp012-9-batch-1): Approvals page wiring (read-only listing + detail)" \
  --body "..."
```

## 7. Codex auto-review baseline (必須)

```bash
sleep 60
.claude/scripts/codex_pr_full_review.sh <PR_NUM> 2>&1 | head -200
```

## 8. DoD checklist

- [ ] Approvals / Agent Runs / Audit / Settings 4 page の read-only wiring 完了
- [ ] server-owned-boundary §1: tenant_id / project_id / actor_id は session 経由
- [ ] pagination 50 件 fixed (本格 pagination は SP-018 defer)
- [ ] mutation は **defer** TODO comment + Sprint Pack 残リスクに記録
- [ ] pnpm typecheck + lint + vitest clean
- [ ] uv run ruff + mypy + pytest clean
- [ ] Sprint Pack SP-012-9 frontmatter `status: ready → completed` + Review 章追加
- [ ] 完了報告 `completion/task-04-completed.md` 起票

## 9. blocker / 緊急停止

- agent_runs endpoint 拡張で task-01 (SP-014) と衝突 → task-01 の orchestrator state 追加を先に merge、本 task は base rebase してから wiring 追加
- audit page で raw secret 漏れリスク → STOPPED.md (`secretbroker-boundary.md` §11 audit payload 禁止 fields 確認)

## 10. 関連参照

- `frontend/app/(admin)/tickets/page.tsx` (本格実装済 pattern、流用 source)
- `.claude/rules/server-owned-boundary.md` (caller-supplied 経路禁止)
- `.claude/rules/secretbroker-boundary.md` §11 (audit payload 禁止 fields)
- `.claude/rules/agentrun-state-machine.md` §1 (16 状態) + §6 (event_type)
- 過去類似 PR: PR #128-#131 (tickets CRUD UI 本格版)
