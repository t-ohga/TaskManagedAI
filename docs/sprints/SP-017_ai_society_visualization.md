---
id: "SP-017_ai_society_visualization"
type: "heavy"
status: "completed"
sprint_no: 17
created_at: "2026-05-24"
updated_at: "2026-05-24"
completed_at: "2026-05-24"
target_days: 3
max_days: 4
adr_refs: []
planned_adr_refs:
  - "[ADR-00017](../adr/00017_ai_society_visualization.md) # proposed; this Sprint implements only the P1 read-only board subset and keeps character image generation deferred"
related_sprints:
  - "SP-013_multi_agent_orchestration"
  - "SP-014_orchestrator_agent"
  - "SP-015_inter_agent_communication"
  - "SP-016_ui_cli_parity"
risks:
  - "PE-F-009 (P2 character image generation prompt sanitization; explicitly out of scope here)"
  - "UI may imply autonomous authority; board must remain read-only and preserve raw role/status identifiers"
---

最終更新: 2026-05-24 (P1 read-only AI Society board slice 完了)

## 目的

SP-013〜SP-016 で完成した multi-agent / orchestrator / inter-agent / CLI boundary を、Web UI 上で運用者が俯瞰できる **AI 組織ボード** として可視化する。最初の slice では既存 AgentRun read-only API だけを利用し、DB / backend API / provider / image generation は変更しない。

## 対象外

- character image generation / custom role image (SP-021)
- new backend API / DB schema
- role or run mutation
- memory backend / `tm memory` integration (SP-018)
- autonomous approval / decider behavior changes

## 設計判断

- **read-only first**: 既存 `/api/v1/agent_runs` list/detail のみを使い、権限や workflow を増やさない。
- **role taxonomy 5+ source continuation**: frontend role catalog は SP-013 の 10 standard roles と完全一致させ、unit test で drift を検出する。
- **raw identifier preservation**: 日本語ラベルを足しても `role_id` / `role_scope` / `status` / `event_type` は消さない。
- **no generated image**: ADR-00017 の P2 character generation は prompt sanitizer / Provider Compliance Matrix / audit が揃うまで未実装。

## 実装チケット

- SP017-T01: `frontend/lib/domain/role-icon.ts` で 10 standard role catalog + default icon / Japanese label / grouping を固定。
- SP017-T02: `/orchestrator/board` page を追加し、role 別 active/blocked/completed counts と latest run を表示。
- SP017-T03: recent AgentRun detail から `inter_agent_message_sent_ref` / `inter_agent_message_consumed_ref` を ref-only timeline 表示。
- SP017-T04: navigation に AI 組織ボードを追加。
- SP017-T05: unit tests で role catalog drift / navigation route / page rendering を固定。
- SP017-T06: Sprint Pack Review と verification evidence を追記。

## タスク一覧

- [x] SP017-T01 role catalog
- [x] SP017-T02 read-only board page
- [x] SP017-T03 inter-agent event ref timeline
- [x] SP017-T04 navigation route
- [x] SP017-T05 frontend tests
- [x] SP017-T06 Sprint Pack Review

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| 10 standard role catalog + icon | ○ | - |
| board page using existing AgentRun APIs | ○ | - |
| inter-agent ref timeline | ○ | detail fetch 件数を上限 8 に制限 |
| navigation entry | ○ | - |
| responsive/a11y smoke by unit tests | ○ | Playwright visual can run in follow-up if dev server unavailable |
| character image generation | × | SP-021 |
| backend role summary endpoint | × | add only if existing AgentRun APIs become too expensive |

## 受け入れ条件

- 10 standard roles が frontend catalog で exact match。
- `/orchestrator/board` が AgentRun list API 失敗時も fail-closed error state を表示する。
- role card は raw `role_id` と日本語 label を併記し、権限昇格や mutation control を持たない。
- inter-agent timeline は `message_id` / `payload_hash` / `seq_no` など ref-only keys だけを表示し、raw message body を表示しない。
- navigation から `/orchestrator/board` へ到達できる。

## 検証手順

```bash
corepack pnpm@10.18.0 --dir frontend test -- --run frontend/__tests__/ai-society-board.test.tsx frontend/__tests__/lib/domain/role-icon.test.ts frontend/__tests__/navigation.test.tsx
corepack pnpm@10.18.0 --dir frontend typecheck
corepack pnpm@10.18.0 --dir frontend lint
```

## Review

### 2026-05-24 batch 0a: read-only AI Society board

changed:
- `frontend/lib/domain/role-icon.ts`
- `frontend/app/(admin)/orchestrator/board/page.tsx`
- `frontend/components/navigation.tsx`
- `frontend/__tests__/ai-society-board.test.tsx`
- `frontend/__tests__/lib/domain/role-icon.test.ts`
- `frontend/__tests__/navigation.test.tsx`
- `docs/sprints/README.md`
- `docs/sprints/SP-017_ai_society_visualization.md`

implemented:
- 10 standard role catalog with Japanese labels, raw IDs, and static default icons.
- read-only board page using existing AgentRun list/detail APIs.
- bounded detail fetch for latest 8 runs to surface inter-agent sent/consumed ref events.
- fail-closed error state that does not fabricate run/role data.
- navigation link for AI 組織 board.

verified:
- `corepack pnpm@10.18.0 --dir frontend install --frozen-lockfile`
- `corepack pnpm@10.18.0 --dir frontend test -- --run frontend/__tests__/ai-society-board.test.tsx frontend/__tests__/lib/domain/role-icon.test.ts frontend/__tests__/navigation.test.tsx` (frontend suite: 24 files / 95 tests passed)
- `corepack pnpm@10.18.0 --dir frontend typecheck`
- `corepack pnpm@10.18.0 --dir frontend lint`
- `.claude/hooks/sprint/check-sprint-pack-frontmatter.sh docs/sprints/SP-017_ai_society_visualization.md`
- `git diff --check`
- Playwright browser smoke against `http://127.0.0.1:3001/orchestrator/board`: 200 response, exact `AI 組織ボード` heading visible, fail-closed status visible with disconnected backend, console error/warning clean, screenshot `/tmp/sp017-ai-society-board.png`

deferred:
- character image generation remains SP-021.
- backend summary endpoint remains deferred until existing AgentRun APIs are insufficient.
- ADR-00017 remains proposed because the P2 image generation decision is still blocked.
