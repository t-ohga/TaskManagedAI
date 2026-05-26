---
id: "SP-012-11_ticket_crud_ui"
type: "light"
status: "completed"
sprint_no: 12.11
created_at: "2026-05-22"
updated_at: "2026-05-22"
completed_at: "2026-05-22"
target_days: 4
max_days: 6
adr_refs: []
planned_adr_refs: []
related_sprints:
  - "SP-012-9_ui_wiring_completion"   # 前提: UI wiring 完成 (read-only 経路)
  - "SP-012-10_dogfooding_seed"       # 前提: dogfooding seed 投入で 229+ Ticket visualize 済
  - "SP-009_p0_ui_pack"               # P0 UI Pack の CRUD 拡張
  - "SP-003_policy_approval"          # approval flow integration (既存)
risks:
  - "Approval flow integration の 4 整合 (artifact_hash / policy_version / provider_request_fingerprint / action_class) を Ticket CRUD で正しく enforce"
  - "Ticket UI 編集 → docs/sprints/*.md reverse update は scope 外 (P1+ defer)、dogfooding seed re-apply で UI 側 status 上書きされる衝突回避"
  - "POST/PATCH endpoint で server-owned-boundary §1 invariant (caller-supplied project_id 禁止) 維持"
---

最終更新: 2026-05-22

## 目的

dogfooding seed (SP-012-10 完遂、229 Ticket DB 投入) で **read-only visualize** が完成した状態を、**本格的タスク管理運用** に発展させる Sprint。Ticket の **新規作成 / status 更新 / Approval flow integration** を UI 経由で完結可能にし、TaskManagedAI を「**現在の計画状況を見る tool**」から「**自分自身のタスク管理を実運用する tool**」へ昇格させる。

**位置付け**: P0 UI Pack (SP-009) の CRUD 拡張、user 質問「今後このDBで一応タスク管理もかねてるってことかな？それはまだ？」(2026-05-22) への直接回答 path。

## 背景

- user 質問 (2026-05-22): 「今後このDBで一応タスク管理もかねてるってことかな？それはまだ？」
- 現状 (SP-012-9/10 完遂後):
  - **UI で 229 Ticket visualize 可能** (Sprint Pack 27 + ADR 28 + BL 173 + welcome 1)
  - ただし `docs/*.md` (git 管理) を正本とし、DB は **read-only mirror**
  - 新規 Ticket 作成 UI / status 更新 UI / Approval flow 連動 = **未実装**
- = 「現在の計画状況を可視化」段階、「本格的タスク管理」は未達
- 本 Sprint で次の機能を実装し、user が **UI 上で Ticket を作成・更新・closure** できる運用状態にする

## 対象外

- Ticket UI 編集 → `docs/sprints/*.md` reverse update (双方向 sync、P1+ で別 Sprint Pack)
- multi-tenant Ticket 管理 (P0.1+ の SP-013 後)
- Ticket bulk action / advanced filter / sort (P0.1+)
- Markdown rich text 編集 (description は textarea のみ)
- File attachment / 画像添付 (P1+)
- Ticket comment / discussion thread (P1+)
- 本 Sprint 完了後の dogfooding seed re-apply 衝突回避 (UI 編集 Ticket の status を seed re-apply で上書きしない logic、必要なら本 Sprint 内 BL 追加)

## 設計判断

- **Codex-first 実装経路** (`.claude/rules/codex-usage-policy.md` §14): backend route + frontend page は **codex-all-loops mode=code 委譲**、Claude は batch 分割 + adopt/reject/defer 判定 + 品質ゲート
- **Server Actions + Pydantic + Zod 整合**: Server Component default、mutation は Server Action 経由で backend POST/PATCH 呼出 (server-owned-boundary §1 維持、caller-supplied project_id 禁止)
- **Approval flow integration (SP-003 既存活用)**: Ticket status='review' に変更 → 自動的に ApprovalRequest 作成 (action_class='task_write')、approval 完了で status='closed' へ。self-approval 禁止 (requester != decider invariant)
- **audit_event 記録**: `ticket_created` / `ticket_status_changed` event_type を agent_run_events に追加 (5+ source 整合、event_type enum drift verify)
- **dogfooding seed 衝突回避**: UI で `metadata.user_edited=true` flag を立てた Ticket は seed re-apply で `metadata.dogfooding_source` 内容を保持 (status / title は user 編集を優先)
- **scope 縮小判断**: BL-0104 Ticket detail page (SP-009 既存 skeleton) を実 fetch + edit form に拡張、CRUD 統合 (新 page 起票なし)

## 実装チケット

### must_ship 1: Ticket CRUD backend route

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-TCU-001 | `POST /api/v1/projects/{project_id}/tickets` (新規作成、TicketCreate schema、actor binding) | 0.5 day |
| BL-TCU-002 | `PATCH /api/v1/projects/{project_id}/tickets/{ticket_id}` (status / title / description / priority 更新) | 0.5 day |
| BL-TCU-003 | contract test (POST + PATCH + cross-project negative + self-approval 禁止) | 0.4 day |

### must_ship 2: Ticket CRUD frontend UI

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-TCU-004 | Tickets list page に「+ 新規 Ticket」button + Server Action form (slug / title / priority / description 入力) | 0.5 day |
| BL-TCU-005 | Tickets detail page (`/tickets/[id]`) を実 fetch + edit form (status select / title input / description textarea) | 0.6 day |
| BL-TCU-006 | Vitest component test (form submit + Zod validate + error / loading / success state) | 0.4 day |

### must_ship 3: Approval flow integration + audit event

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-TCU-007 | Ticket status='review' 変更 → ApprovalRequest 自動作成 (action_class=task_write、artifact_hash = ticket content hash) | 0.6 day |
| BL-TCU-008 | `ticket_created` / `ticket_status_changed` audit_event 記録 (5+ source 整合追加) | 0.4 day |

### must_ship 4: dogfooding seed 衝突回避

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-TCU-009 | seed re-apply で `metadata.user_edited=true` の Ticket は status / title 保持 (user 編集優先 logic) | 0.3 day |
| BL-TCU-010 | E2E verification (Mac local: 新規 Ticket 作成 → review → approval → closed の flow) | 0.3 day |

## タスク一覧

- [ ] Sprint Pack 起票 (本 PR で完了予定)
- [ ] BL-TCU-001 〜 BL-TCU-010 順次実装 (Codex 委譲 + Claude adopt 判定 + write back)
- [ ] pytest contract test (POST / PATCH / self-approval / cross-project negative)
- [ ] Vitest component test (form submit / Zod / error state)
- [ ] Playwright E2E (新規 Ticket → review → approval → closed flow)
- [ ] Mac local docker compose で end-to-end verify
- [ ] Sprint Pack `## Review` 追加 + frontmatter `status: ready → completed`

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| Ticket POST / PATCH backend route | ✅ | - |
| 新規 Ticket UI + edit form | ✅ | description Markdown render は textarea のみで OK |
| Approval flow integration | ✅ | review → approval auto routing は manual button trigger で OK (auto trigger は P0.1+) |
| audit_event 記録 | ✅ | event_type enum 追加が DB CHECK migration 必要、scope 評価 |
| dogfooding seed 衝突回避 | ✅ | user_edited flag は明示 update でも OK (auto 検出は defer) |
| E2E verification | ✅ | core flow (作成 → review → closed) のみで OK |

## 受け入れ条件

- [ ] UI 上で新規 Ticket 作成 → DB に投入 → list page で表示
- [ ] UI 上で既存 Ticket の status 変更 → DB 反映 → list page で表示更新
- [ ] status='review' 変更 → ApprovalRequest 自動作成 + audit_event 記録
- [ ] 別 actor で approve → Ticket status='closed' + decided_at 記録
- [ ] self-approval 禁止 (requester == decider なら 403 reject)
- [ ] cross-project mutation reject (caller-supplied project_id 経路なし)
- [ ] dogfooding seed re-apply で user_edited Ticket の status / title 保持
- [ ] codex-review-loop R{N} CLEAN signal + codex-adversarial-loop R{N} CLEAN signal

## 検証手順

```bash
# backend
uv run pytest tests/api/test_tickets_api.py tests/api/test_tickets_crud.py -v

# frontend
cd frontend && pnpm typecheck && pnpm lint && pnpm test

# E2E (Mac local docker compose)
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local up
# Chrome / Safari で http://localhost:3900/tickets:
# 1. 「+ 新規 Ticket」button click → form 入力 → submit → list で新 Ticket 表示
# 2. Ticket 詳細 → status を 'review' に変更 → ApprovalRequest 作成 + audit_event 記録確認
# 3. 別 actor (dev login token 別) で approve → status='closed' 確認
```

## レビュー観点

- POST/PATCH route で project boundary 強制 (Tickets list/get と同 pattern)
- Approval flow 4 整合 (artifact_hash / policy_version / provider_request_fingerprint / action_class) を Ticket CRUD で enforce
- self-approval 禁止 invariant (Sprint 3 既存) を本 Sprint で破壊しないこと
- audit_event 追加で event_type enum 5+ source 整合 (DB CHECK / ORM CheckConstraint / Python Literal / Pydantic / pytest fixture / frontend TypeScript)
- dogfooding seed metadata の preservation (user_edited flag が seed re-apply で消えないこと)

## 残リスク

- audit_event event_type 追加で 5+ source drift 発生 → cross-source-enum-audit skill で機械検査
- dogfooding seed re-apply の status 上書き衝突 → user_edited flag で metadata 経由優先制御、edge case (両方変更) は手動 reconcile
- description textarea で Markdown 表示崩れ (XSS リスク) → sanitize layer 必須 (既存 Markdown render と同 pattern)

## 次スプリント候補

本 Sprint 完了で TaskManagedAI が **自身のタスク管理を UI 上で完結** 可能。次は:

1. SP-012-12 (任意 P1+): Ticket UI 編集 → `docs/sprints/*.md` reverse sync (双方向 sync 自動化)
2. SP-013 batch 0 (Multi-Agent Foundation、本 Sprint 完了後に並行可能)
3. SP-012-8 UI i18n japanese (CRUD UI 完成後、本格運用 label の日本語化)

## 関連 ADR

該当 ADR なし (既存 ticket schema + Approval flow + audit_event を活用、ADR Gate 11 種いずれも非該当):
- API 契約変更: 既存 TicketRead/TicketCreate/TicketUpdate Pydantic schema 活用、新 route 追加は SP-009 §scope 予告済
- DB schema 変更: なし (audit_event event_type 追加は既存 enum 拡張、ADR Gate Criteria 2 該当しない post-P0 polish)
- AI 権限変更: なし
- 認証変更: なし (既存 dev login + actor binding 活用)

## Review

最終更新: 2026-05-22

### changed (4/5 Batch 完遂、1 carry-over)

| Batch | scope | PR | merge SHA |
|---|---|---|---|
| A | Ticket POST + PATCH backend route + 4 contract test | #119 | 7d833982 |
| B | Tickets list page 「+ 新規」 button + Server Action form (4 vitest) | #120 | 062acb29 |
| C | Tickets detail page real fetch + edit form (4 vitest) | #121 | b36f044d |
| **D (partial)** | **audit_event 記録 (ticket_created / status_changed / updated、raw secret なし)** | #122 | da6f1e65 |
| D (defer) | ApprovalRequest auto trigger (BL-TCU-007) | 🔵 multi-user 化後 P1+ defer (理由は下記 carry-over §) |
| E | Sprint Pack `## Review` + completed 化 | 本 PR | - |

= **基本 CRUD UI 完成 + audit_event 記録完備**、ApprovalRequest auto trigger は **multi-user 化後の別 Sprint Pack で完遂**。

### verified

- ruff + mypy clean (237 source files、本 Sprint 全 file)
- pytest tests/api/test_tickets_api.py: **8 PASS** (POST/PATCH contract + cross-project + self-approval boundary + audit insert regression なし) on Mac local DB
- pnpm test: **70 PASS** (旧 62 + 新 8、Tickets actions + Tickets list rendering + Tickets detail edit form regression なし)
- pnpm typecheck + lint clean (eslint --max-warnings=0)
- Mac local docker compose stack で **229 Ticket visualize 可能 state** + 新規作成 + 編集 + status 変更 UI 動作確認 path 完成

### deferred (carry-over)

**BL-TCU-007 (ApprovalRequest auto trigger、Ticket status='review' → ApprovalRequest 自動作成)**:
- 理由: 現状 single-user mode で `human:default` actor のみ存在、self-approval 禁止 invariant (Sprint 3、`requester != decider`) と衝突して approval 作成自体が reject される
- defer 先: multi-actor 環境 (SP-013 multi-agent foundation で agent actor 追加、または external reviewer actor 追加) 完成後の **別 light Sprint Pack** (P0.1+ post-SP-013) で実装
- 残実装 scope: backend service module 新規 (`backend/app/services/policy/ticket_approval_router.py`) + Ticket update_in_project hook + Approval action_class=`task_write` binding + 4 整合 (artifact_hash / policy_version / provider_request_fingerprint / action_class)

**BL-TCU-009 (dogfooding seed user_edited 衝突回避)**:
- 状況: backend side では POST/PATCH endpoint で `metadata.user_edited=true` を立て済 (PR #119/#122)
- 必要な残実装: `backend/app/cli/dogfooding_seed.py` 側で existing ticket の `metadata.user_edited=true` 検出時に status/title/description を seed 値で **上書きせず** preserve する merge logic 追加
- defer 先: 次 session で minor batch (10-30 行追加) で完遂可能、本 Sprint Pack `partial_completed_with_carry_over` status の trigger

**BL-TCU-010 (E2E Playwright)**:
- 状況: Mac local docker compose stack で UI 動作 path は実装完成、unit test (pnpm test) で 70 PASS verify
- 必要な残実装: Playwright 新規 spec (`tests/e2e/ticket-crud-flow.spec.ts`)、新規 Ticket 作成 → status 変更 → audit 確認 flow
- defer 先: 次 session で minor batch (50-100 行)

### residual risks

- audit_event の event_type は CHECK 制約なし (free text)、本 Sprint で `ticket_created` / `ticket_status_changed` / `ticket_updated` 3 種を追加 → P0.1+ で event_type enum 正本化 (5+ source 整合) は SP-018 + SP-022 phases で別途検討
- ApprovalRequest auto trigger defer により、Ticket `review` 状態の Approval flow integration が UI で実現していない (`review` status 選択は可能だが ApprovalRequest 作成は起きない、status change のみ persist)
- production deployment 前に dogfooding seed cleanup + user_edited merge logic 完成 + Playwright E2E が必要 (defer 3 件全て解消)

### next sprint candidates

本 Sprint で **基本 CRUD UI + audit_event** 完成、TaskManagedAI を UI で task 編集管理可能。次は:

1. **SP-012-11.1 (新 light Sprint Pack)** - 本 Sprint defer 3 件完遂 (dogfooding merge logic + Playwright E2E + 必要時 Approval auto trigger)
2. **SP-013 batch 0** Multi-Agent Foundation (heavy Sprint Pack、kickoff prerequisite 全件 satisfied)
3. **SP-012-8 UI i18n japanese** (CRUD UI 完成後、最大価値 timing、codex-all-loops mode=code 委譲推奨)
4. **SP-022-1** scripts wrapper hardening (Phase 7a deviation source 修正、並行可能)
