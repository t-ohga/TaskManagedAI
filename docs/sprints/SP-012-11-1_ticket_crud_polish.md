---
id: "SP-012-11-1_ticket_crud_polish"
type: "light"
status: "ready"
sprint_no: 12.111
created_at: "2026-05-22"
updated_at: "2026-05-22"
target_days: 3
max_days: 5
adr_refs: []
planned_adr_refs: []
related_sprints:
  - "SP-012-11_ticket_crud_ui"        # 前提: 本 Sprint で carry-over
  - "SP-012-10_dogfooding_seed"       # BL-TCU-009 seed merge logic 対象
  - "SP-013_multi_agent_orchestration" # BL-TCU-007 multi-actor 化前提
risks:
  - "useActionState migration での既存 vitest test (4 件 each form) regression"
  - "dogfooding seed user_edited merge logic で existing 229 Ticket の status 上書き衝突"
  - "Playwright E2E spec で Mac local docker compose stack 起動前提 (CI 環境 OFF、local only test)"
---

最終更新: 2026-05-22

## 目的

SP-012-11 (Ticket CRUD UI、PR #118-#123 + Codex P1 fix PR #124/#125/#126) で `partial_completed_with_carry_over` 状態となった **carry-over 4 件 + Codex P2 useActionState migration** を完遂し、SP-012-11 Sprint Pack を真の `completed` に昇格させる polish Sprint。

**位置付け**: SP-012-11 の **defer 部分回収 Sprint**。新機能追加なし、既存 Ticket CRUD の品質 + UX 向上に focus。

## 背景

SP-012-11 完遂時の Carry-over (SP-012-11 `## Review` §deferred、本 Sprint の対象):

1. **BL-TCU-007 ApprovalRequest auto trigger** (deferred from SP-012-11 Batch D):
   - 現状: single-user mode (`human:default` actor のみ) で self-approval 禁止 invariant と衝突
   - 本 Sprint で実装可能 path: SP-013 multi-agent foundation 完了後 (agent actor 追加で別 actor 利用可) または external reviewer actor 追加 → status='review' 変更時に ApprovalRequest 自動作成

2. **BL-TCU-009 dogfooding seed user_edited merge logic** (deferred from SP-012-11 Batch D):
   - 現状: backend POST/PATCH endpoint で `metadata.user_edited=true` 立て済 (PR #119)
   - 必要: `backend/app/cli/dogfooding_seed.py` で existing ticket の `metadata.user_edited=true` 検出時に status/title/description を seed 値で **上書きせず preserve** する merge logic 追加

3. **BL-TCU-010 Playwright E2E spec** (deferred from SP-012-11 Batch E):
   - 必要: `frontend/tests/e2e/ticket-crud-flow.spec.ts` で 新規 Ticket 作成 → status 変更 → audit 確認 flow

4. **Codex PR #121 P1#2/#3 multi-project hardcode 解除** (deferred from PR #125 fix):
   - 現状: `DEFAULT_PROJECT_ID` hardcode (frontend tickets.ts + tickets/[id]/actions.ts + tickets/[id]/page.tsx)
   - 必要: session 経由 current project_id resolve (`/api/v1/me/projects` 等の helper API or session cookie 経由 + Server Component context)

加えて **Codex PR #120 P2 useActionState migration** (PR #126 で startTransition async pattern fix 適用済、React 19 ideal pattern への完全 migration は本 Sprint scope):
   - 現状: startTransition + useState (PR #126 async 化で functional issue 解消)
   - 必要: `useActionState` (React 19 standard form pattern) への migration、ideal pattern + form action 直接接続 + automatic pending tracking

## 対象外

- 新機能 UI (本 Sprint は SP-012-11 polish のみ、新 page / 新 button は P1+ 別 Sprint)
- multi-tenant Ticket 管理 (SP-013 後)
- Ticket UI → docs/sprints/*.md reverse sync (P1+ 別 Sprint Pack)
- Markdown rich render (description は textarea のみ、P1+)

## 設計判断

- **Codex-first 実装経路** (`.claude/rules/codex-usage-policy.md` §14): backend service + frontend form refactor は **codex-all-loops mode=code 委譲推奨**、Claude は orchestrator + adopt/reject/defer 判定 + 品質ゲート
- **SP-013 完了後着手判定**: BL-TCU-007 ApprovalRequest auto trigger は SP-013 multi-agent foundation 完了後 (agent actor 利用可) に着手、本 Sprint 内で着手判断は SP-013 状態確認後
- **dogfooding seed user_edited merge**: backend cli 側で既存 ticket query + `metadata.user_edited=true` 検出 → status/title/description は seed 値で上書きしない (idempotent merge logic 拡張)
- **multi-project hardcode 解除**: backend 側で `/api/v1/me/current_project` 等の helper endpoint 新規 or session cookie に project_id 含める、frontend は Server Component で session 経由 resolve
- **Playwright E2E**: Mac local docker compose stack 起動前提、CI off (CI で docker compose 起動 scope 大)、Sprint Exit 時 manual run で verify

## 実装チケット

### must_ship 1: dogfooding seed user_edited merge logic (BL-TCU-009)

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-TCU-011 | `backend/app/cli/dogfooding_seed.py` seed_sprint_packs / seed_adrs / seed_bls 拡張: 既存 ticket の `metadata.user_edited=true` 検出時に status/title/description 上書きせず | 0.4 day |
| BL-TCU-012 | contract test (re-apply で user_edited ticket 保持 verify) | 0.3 day |

### must_ship 2: multi-project hardcode 解除 (PR #121 P1#2/#3 carry-over)

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-TCU-013 | backend `GET /api/v1/me/current_project` helper endpoint (session 経由 current project resolve) | 0.4 day |
| BL-TCU-014 | frontend `lib/api/session.ts` 新規 `getCurrentProjectId()` + Tickets list / detail / actions で hardcode を session resolve に置換 | 0.6 day |
| BL-TCU-015 | regression test (frontend Vitest + backend contract test) | 0.4 day |

### must_ship 3: useActionState migration (PR #120 P2 carry-over)

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-TCU-016 | new-ticket-form.tsx / edit-ticket-form.tsx を `useActionState` (React 19) に migration | 0.5 day |
| BL-TCU-017 | 既存 vitest test 4+4=8 件を新 pattern に追従更新 | 0.3 day |

### must_ship 4: Playwright E2E (BL-TCU-010)

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-TCU-018 | `frontend/tests/e2e/ticket-crud-flow.spec.ts` 新規 (新規作成 → 編集 → status 変更 → audit 確認 flow) | 0.5 day |
| BL-TCU-019 | playwright config + Mac local docker compose stack 起動前提 docs | 0.2 day |

### defer (本 Sprint scope 外、SP-013 完了後 trigger)

- **BL-TCU-007 ApprovalRequest auto trigger**: SP-013 multi-agent foundation 完了後の別 Sprint Pack で着手。本 Sprint 完遂時に SP-013 完了状態を確認 → 完了済なら本 Sprint 内 BL に追加可、未完了なら別 Sprint Pack に carry-over

## タスク一覧

- [ ] Sprint Pack 起票 (本 PR で完了予定)
- [ ] BL-TCU-011-019 順次実装 (Codex 委譲 + Claude adopt 判定 + write back)
- [ ] **各 PR で Codex auto-review baseline 確認 + 採否判定** (品質担保 path 復元 invariant、`feedback_codex_review_must_use_full_helper.md` 遵守)
- [ ] pytest + Vitest + Playwright E2E 全 PASS
- [ ] Mac local docker compose stack で end-to-end verify
- [ ] Sprint Pack `## Review` 追加 + frontmatter `status: ready → completed` (+ SP-012-11 status も `partial_completed_with_carry_over → completed` 連動昇格 if 全 carry-over 完遂)

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| dogfooding seed user_edited merge | ✅ | - |
| multi-project hardcode 解除 | ✅ | session helper API 形式は backend `/me` endpoint で OK、frontend resolve は Server Component context で簡潔 |
| useActionState migration | ✅ | edit-ticket-form は new-ticket-form と同 pattern で複製、test 追従 |
| Playwright E2E | ✅ | core flow (作成 → 編集) のみ必須、status / audit verify は best effort |
| BL-TCU-007 (defer) | × | SP-013 後別 Sprint Pack で着手 |

## 受け入れ条件

- [ ] dogfooding seed re-apply で `metadata.user_edited=true` ticket の status/title/description が保持される
- [ ] backend `/api/v1/me/current_project` endpoint で session 経由 project resolve 動作
- [ ] frontend tickets pages で hardcode 排除、session 経由 project_id 取得で動作
- [ ] new-ticket-form + edit-ticket-form が `useActionState` で動作、pending state 完璧、二重 submit 防止
- [ ] Playwright E2E (Mac local) で 新規 Ticket → 編集 → status 変更 → audit verify flow PASS
- [ ] **本 Sprint 内 全 PR で Codex auto-review baseline 確認 + adopt/reject/defer 判定** (recurring 防止)
- [ ] codex-review-loop R{N} CLEAN signal (各 batch、品質担保完成)

## 検証手順

```bash
# backend
uv run pytest tests/api/test_tickets_api.py tests/cli/test_dogfooding_seed.py -v

# frontend
cd frontend && pnpm typecheck && pnpm lint && pnpm test

# Mac local docker compose で end-to-end
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local up -d
docker compose exec api uv run python -m backend.app.cli.dogfooding_seed --apply  # idempotent confirm
cd frontend && pnpm test:e2e --grep 'ticket-crud-flow'
```

## レビュー観点

- dogfooding seed merge logic で `metadata.dogfooding_source` の preservation (re-apply で dogfooding_source 消えないこと)
- multi-project resolve で session cookie の project_id が strict validate (caller-supplied 排除、server-owned-boundary §1)
- useActionState で error / loading / success state が確実に reflect (既存 vitest pattern 追従)
- Playwright E2E が Mac local stack の login flow (dev login token) を経由できること

## 残リスク

- BL-TCU-007 ApprovalRequest auto trigger は SP-013 完了後 = 本 Sprint 完遂後の trigger、SP-013 batch 数 (5-7) に依存
- useActionState migration で既存 vitest mock pattern (`createTicketAction(idle, formData)` 直接呼出) は そのまま動く想定、test refactor 不要
- Playwright E2E は Mac local docker compose 起動前提 = CI で自動実行不可、Sprint Exit 時 manual run + evidence 記録

## 次スプリント候補

本 Sprint 完了で SP-012-11 全 carry-over 解消、SP-012-11 を真の `completed` に昇格可能。次は:

1. **SP-013 batch 0 着手** (Multi-Agent Foundation、heavy Sprint Pack、本 Sprint と並行可能だが Codex first 推奨)
2. **SP-012-12 (P1+ defer)**: Ticket UI → docs/sprints/*.md reverse sync 自動化 (双方向 sync)
3. **SP-012-8 UI i18n japanese** (CRUD UI 完成後の最大価値 timing、codex-all-loops mode=code 委譲)

## 関連 ADR

該当 ADR なし: SP-012-11 polish、既存 schema + ADR で cover、ADR Gate 11 種いずれも該当しない。

## Review

(本 Sprint 完了時に追記: changed / verified / deferred / risks)
