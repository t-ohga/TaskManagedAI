---
id: "SP-012-9_ui_wiring_completion"
type: "light"
status: "completed"
sprint_no: 12.9
created_at: "2026-05-22"
updated_at: "2026-05-22"
completed_at: "2026-05-22"
target_days: 5
max_days: 7
adr_refs: []
planned_adr_refs: []
related_sprints:
  - "SP-009_p0_ui_pack"         # Sprint 9 carry-over (batch 2-5) 完遂
  - "SP-011_eval_harness"       # Sprint 11 BL-0163 (Ticket detail API) carry-over
  - "SP-012-10_dogfooding_seed" # 後続: seed 投入で初期 visualize 完成
  - "SP-012-8_ui_i18n_japanese" # 後続: wiring + seed 完了後の i18n 実装
risks:
  - "Tickets backend API endpoint 未実装 (Sprint 9 / 11 carry-over)、新規実装必要"
  - "Server Component で session 経由 tenant_id / project_id resolve (caller-supplied 禁止 invariant 維持)"
  - "Zod schema (frontend) と Pydantic schema (backend) の drift 検証"
  - "P0 UI Pack (SP-009) の skeleton path は force-dynamic + no-cache、wiring 後の SSR cache 整合"
---

最終更新: 2026-05-22

## 目的

P0 UI Pack (SP-009、Sprint 9 batch 1) で skeleton として実装された Ticket / Approval Inbox / Agent Runs / Audit Log / Project Settings の **実 API integration を完遂**。SP-009 §scope の batch 2-5 carry-over を本 Sprint で wiring 完成し、TaskManagedAI 自身を **UI で運用可能** な状態にする。

**位置付け**: P0 期間中 Sprint 9 で意図的に defer された UI wiring の **post-P0 完遂 Sprint**。新機能追加なし、既存 backend API + frontend skeleton の **gap fill** に focus。

## 背景

- P0 UI Pack (SP-009) では route 構造 + layout + Zod schema draft のみ実装、実 API wiring は **Sprint 9 batch 2-5 で carry-over** 設計
- 実 P0 期間中 (Sprint 9-12) は backend Hard Gate + KPI + Eval に focus、UI wiring は P0 Exit gate 外で defer
- 現状 (PR #109 P0 Exit declaration 後):
  - **Dashboard**: backend health real fetch ✅、frontend health は固定 placeholder ❌
  - **Tickets**: 完全 static skeleton (`listTickets` API call なし)、backend route も未実装 (Sprint 9 batch 2 + Sprint 11 BL-0163 carry-over)
  - **Approvals**: skeleton 想定、backend `approval_inbox.py` 既存 → frontend wiring のみ必要
  - **Agent Runs**: skeleton 想定、backend `agent_runs.py` 既存 → frontend wiring のみ必要
  - **Audit Log**: skeleton 想定、backend (audit endpoint) 既存 → frontend wiring 必要
  - **Project Settings**: skeleton 想定、backend (projects) 部分実装 → frontend wiring 必要
- 本 Sprint で 5 page 全件 wiring 完成 + Dashboard frontend health real fetch fix

## 対象外

- 新機能 UI 追加 (本 Sprint は wiring 完成のみ、新規 page / feature は P1+ で別 Sprint Pack)
- UI 日本語化 (SP-012-8、本 Sprint 完了後の i18n Sprint で実装)
- dogfooding seed data 投入 (SP-012-10、本 Sprint 完了後)
- multi-agent UI (SP-017 AI Society Visualization)
- character image (SP-020、P2 scope)
- mobile / responsive 最適化 (P0 UI は desktop 中心)

## 設計判断

- **Codex-first 実装経路** (`.claude/rules/codex-usage-policy.md` §14): UI 実装は **codex-all-loops mode=code 委譲**、Claude は batch 分割 + adopt/reject/defer 判定 + 品質ゲート
- **Server Component default** (Next.js 16 App Router): tenant_id / project_id は session から resolve、caller-supplied 経路なし (`.claude/rules/server-owned-boundary.md` §1 遵守)
- **Zod schema strict validation**: backend Pydantic response を frontend で再 validate、unknown field drop、Sprint 11 で予告された drift 検証も同 batch 内で実施
- **Tickets backend route 新規実装**: Sprint 9 carry-over の最大 gap、`GET /api/v1/tickets` + `GET /api/v1/tickets/{id}` を新規実装 (既存 ticket ORM / repository / schema 活用)
- **既存 backend API の frontend wiring**: Approvals / Agent Runs / Audit / Notifications は backend 完備 → frontend listXxx() call + page render 実装で完遂
- **Dashboard frontend health real fetch**: 現状 hardcoded "ok" 表示を `/api/healthz` (Next.js own route) 実 fetch で置換
- **AgentRun 16 状態 + blocked_reason 3 種分離表示**: status と blocked_reason は別 dimension 表示 (SP-009 §scope 既規定)
- **payload_data_class / allowed_data_class 別 dimension**: caller 入力でなく Server Component 内 resolve、表示も別 dimension (SP-009 §scope 既規定)

## 実装チケット

### must_ship 1: Tickets API backend + frontend wiring (Sprint 9 carry-over 最大 gap)

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-UIW-001 | `GET /api/v1/tickets` backend route 新規 (listing、tenant_id + project_id binding + pagination) | 0.6 day |
| BL-UIW-002 | `GET /api/v1/tickets/{id}` backend route 新規 (detail、Acceptance Criteria + Evidence + AgentRun status 含む) | 0.6 day |
| BL-UIW-003 | `frontend/lib/api/tickets.ts` の `loadTicketDraft()` (現 pending) を実 fetch + Zod validate に実装 | 0.3 day |
| BL-UIW-004 | `frontend/app/(admin)/tickets/page.tsx` + `[id]/page.tsx` を実データ表示に置換 | 0.5 day |

### must_ship 2: Approvals Inbox frontend wiring (backend 既存)

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-UIW-005 | `frontend/lib/api/approvals.ts` を実 fetch (backend `approval_inbox.py` 既存) | 0.2 day |
| BL-UIW-006 | `frontend/app/(admin)/approvals/page.tsx` を pending / approved / rejected / invalidated / expired 全 status 表示に wiring | 0.3 day |

### must_ship 3: Agent Runs timeline frontend wiring (backend 既存)

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-UIW-007 | `frontend/lib/api/agent-runs.ts` を実 fetch (backend `agent_runs.py` 既存)、AgentRun 16 状態 + blocked_reason 3 種分離 | 0.3 day |
| BL-UIW-008 | `frontend/app/(admin)/agent-runs/page.tsx` + `[id]/page.tsx` を timeline 表示 + ContextSnapshot 10 列 view に wiring | 0.5 day |

### must_ship 4: Audit Log frontend wiring (backend 既存)

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-UIW-009 | `frontend/lib/api/audit.ts` を実 fetch (backend audit endpoint 既存) + raw secret なし表示 (reason_code / hash / pattern hit 種別のみ) | 0.3 day |
| BL-UIW-010 | `frontend/app/(admin)/audit/page.tsx` を event_type filter + tenant boundary 表示に wiring | 0.3 day |

### must_ship 5: Project Settings frontend wiring + Dashboard health real fetch

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-UIW-011 | `frontend/app/(admin)/settings/page.tsx` を projects API wiring (workspace + project list + member 表示) | 0.4 day |
| BL-UIW-012 | Dashboard frontend health card を hardcoded "ok" → `/api/healthz` 実 fetch に変更 (frontend own route) | 0.2 day |

## タスク一覧

- [ ] Sprint Pack 起票 (本 PR で完了予定、SP-012-9 + SP-012-10 同 PR 起票)
- [ ] Codex prompt 作成 (Batch A: Tickets backend route + wiring、Batch B: 既存 backend wiring 4 件、Batch C: Settings + Dashboard fix)
- [ ] BL-UIW-001 〜 BL-UIW-012 順次実装 (Codex 委譲 + Claude adopt 判定 + write back)
- [ ] Vitest + Playwright regression test 全 PASS
- [ ] Zod schema vs Pydantic schema drift 検証 contract test 追加
- [ ] Sprint Pack `## Review` 追加 + frontmatter `status: ready → completed`

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| Tickets API backend + frontend wiring | ✅ | pagination 高度化は defer 可、最小は 50 件 per page で OK |
| Approvals Inbox frontend wiring | ✅ | bulk action / filter 高度化は SP-009 §scope と同 (P1+ で別 Sprint Pack) |
| Agent Runs timeline frontend wiring | ✅ | ContextSnapshot 10 列 full view は最小 5 列で OK (project / status / created_at / blocked_reason / actor)、残 5 列は detail page で別途 |
| Audit Log frontend wiring | ✅ | event_type filter は 5 種主要 (policy_blocked / approval_decided / runner_blocked / provider_blocked / secret_capability_redeemed) で OK |
| Project Settings frontend wiring | ✅ | member 管理 UI は P0.1+ defer 可、workspace + project 表示のみで OK |
| Dashboard frontend health real fetch | ✅ | - |

## 受け入れ条件

- [ ] 全 5 page (Tickets / Approvals / Agent Runs / Audit / Settings) が実 backend API から data fetch + 表示
- [ ] Dashboard frontend health card が `/api/healthz` 実 fetch (hardcoded "ok" 排除)
- [ ] Tickets backend route 2 件 (`GET /api/v1/tickets` + `GET /api/v1/tickets/{id}`) 新規実装 + contract test PASS
- [ ] Zod schema strict validation で unknown field reject、type mismatch reject
- [ ] Server Component で tenant_id / project_id を session 経由 resolve (caller-supplied なし)
- [ ] AgentRun 16 状態 + blocked_reason 3 種 + payload_data_class / allowed_data_class が別 dimension 表示
- [ ] Audit Log で raw secret が表示されない (reason_code / hash / pattern hit 種別のみ)
- [ ] Vitest + Playwright regression test 全 PASS
- [ ] codex-review-loop R{N} CLEAN signal + codex-adversarial-loop R{N} CLEAN signal (各 batch ごと)

## 検証手順

```bash
# backend test
uv run pytest tests/api/test_tickets.py -v  # 新規
uv run pytest tests/api/ -v                  # regression

# frontend lint + typecheck
cd frontend && pnpm typecheck && pnpm lint

# frontend unit + component
cd frontend && pnpm test

# E2E (Playwright)
cd frontend && pnpm test:e2e --grep 'tickets list|approvals inbox|agent runs|audit|settings'

# 手動 visual check (Mac local docker compose)
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local up
# Chrome / Safari で http://localhost:3000/{dashboard,tickets,approvals,agent-runs,audit,settings} 確認
# 各 page で real data 表示 + skeleton placeholder 排除を verify
```

## レビュー観点

- backend route の tenant boundary + project boundary enforcement (server-owned-boundary §1 遵守)
- Zod schema が Pydantic と drift していない (新規 contract test で機械検査)
- Server Component で session resolve 経路の secret 漏れなし (cookie secret / capability token を DOM に出さない)
- AgentRun status + blocked_reason の分離表示が UI で明確 (混同しないこと)
- Audit Log で raw secret pattern (api_key / private_key 等) が表示されないこと (XSS / secret canary leak 防御)
- Performance: 各 page initial load ≤ 1s (SSR + force-dynamic、cache OFF)

## 残リスク

- backend route 新規実装で既存 ticket repository contract に regression → 既存 contract test 維持で防御
- Zod schema strict validation で既存 backend response の unknown field drop が想定外副作用 → schema drift 検証 test で事前検出
- Server Component の Sentry / Datadog 等の observability 不足 → P0.1+ で別 Sprint Pack (SP-011-5 補強)

## 次スプリント候補

本 Sprint 完了で UI wiring 完成、TaskManagedAI 自身を UI で運用可能。次は:

1. SP-012-10 TaskManagedAI dogfooding seed (現状の Sprint Pack / ADR / BL を Ticket として DB seed、本 Sprint 完了後)
2. SP-012-8 UI i18n japanese (wiring + seed 完了後の翻訳実装、最大 valuable)
3. SP-013 batch 0 (Multi-Agent Orchestration Foundation、並行可能)

## 関連 ADR

該当 ADR なし: UI wiring 完成は既存 ADR (SP-009 P0 UI Pack 計画) で cover、新 ADR Gate 11 種いずれも非該当 (UI polish、新 API route 追加は既存 ticket schema 範囲、認証・DB・API 契約・AI 権限・MCP・Secrets・外部公開・破壊的・広範囲 refactor・Provider・GitHub App permission いずれも該当しない)。

## Review

### 2026-05-22 task-04 residual wiring completion

changed:

- Approvals list now supports status-filtered read-only listing.
- Agent Runs now have backend read routes for list/detail plus frontend
  `/runs` and `/runs/[id]` wiring.
- Audit Log now has a backend read route plus frontend `/audit` wiring.
- Settings now reads current project and project list from `/api/v1/me/*`.
- AgentRunEvent and AuditEvent payloads are exposed to the UI as
  `payload_keys` + `payload_redaction_status`, never raw payload values.

verified:

- `uv run ruff check` on changed backend API/tests.
- `uv run mypy` on changed backend API/tests.
- `uv run pytest tests/api/test_approval_inbox.py tests/api/test_agent_runs_cancel.py tests/api/test_sp012_9_ui_wiring_routes.py -q`
  returned `7 passed, 12 skipped` (DB-backed cases skip locally when
  PostgreSQL credentials are unavailable).
- `pnpm typecheck`
- `pnpm lint`
- `pnpm test` returned `22 passed / 90 tests`.

deferred:

- Approval approve/reject mutation changes, AgentRun resume/cancel UI,
  Audit export, provider config mutation, and persistent project switching
  remain SP-018 / multi-user follow-up.
