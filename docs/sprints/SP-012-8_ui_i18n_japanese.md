---
id: "SP-012-8_ui_i18n_japanese"
type: "light"
status: "completed"
sprint_no: 12.8
created_at: "2026-05-22"
updated_at: "2026-05-22"
completed_at: "2026-05-22"
target_days: 2
max_days: 4
adr_refs: []
planned_adr_refs: []
related_sprints:
  - "SP-009_p0_ui_pack"   # P0 UI Pack の i18n 整備
  - "SP-016_ui_cli_parity" # P0.1 UI/CLI parity の前提
risks:
  - "翻訳の機械化 (Codex 委譲) で文脈不適切な訳語が混入"
  - "技術用語 (action_class / payload_data_class / Hard Gate 等) の日本語訳と原語併記方針の不統一"
  - "Server Component / Client Component 境界での翻訳辞書注入の漏れ (Next.js 16 RSC)"
---

最終更新: 2026-05-22

## 目的

P0 UI Pack (SP-009) で英語のまま残った UI 文言を **日本語化** し、user (日本語話者) の運用負荷を下げる。実装は **codex-all-loops mode=code** で Codex (gpt-5.5 + xhigh) に委譲、Claude が batch 分割 + 採否判定 + 品質ゲート担当。

**前提**: 本 Sprint は P0.1 期間内の **後発 polish** であり、新機能追加なし。UI 文言の機械的置換 + コンポーネント内 hard-coded string 抽出 + i18n 辞書 (server-side 制御、frontend 単独 client-side runtime 切替は不要) 導入。

## 背景

- Phase 7a Mac UI smoke (PR #103 §3 Phase 7a-1) で UI 文言が英語のまま (`Tickets` / `Approvals` / `Audit` / `Eval Dashboard` 等の navigation item + Ticket / Approval list の status label + Audit Log の event_type) であることを user 確認
- user 明示: 「UI が英語で分かりづらい点などもあるので codex に修正させる形でいいので /codex-all-loops で直す計画も入れておいてください」(2026-05-22 session)
- 既存実装: `frontend/components/navigation.tsx` (PR #95 で href fix 済) + `frontend/app/(admin)/*/page.tsx` + `frontend/app/(auth)/login/*` 等で英語文言が散在
- P0 期間中 (SP-009 含む) は UI 実装の skeleton + functional correctness を優先、i18n は意図的 defer
- 本 Sprint で日本語化 = user 操作の認知負荷削減 + UI/CLI parity (SP-016) で日本語 CLI message と整合性確保

## 対象外

- 多言語化 framework (next-intl / next-i18next / lingui 等) の本格導入 → P1+ で別 ADR (UI/CLI parity 完成後、多言語化が必要になった時点)
- 英語版 UI の維持 (運用者 1 名 = user = 日本語話者のため英語版維持は P0.1 期間内では scope 外)
- Email / Push notification 文言 (P0 では In-App Notification のみで定型文言なし)
- API error message の日本語化 (API は英語 enum + structured error_code を維持、UI 層で日本語化)
- Audit event payload の日本語化 (raw value 保持、UI 表示時のみ日本語化)
- 技術用語の完全置換 (`payload_data_class` / `allowed_data_class` / `AgentRun` / `ContextSnapshot` 等は原語維持、必要に応じて括弧で日本語併記)

## 設計判断

- **codex-all-loops mode=code 委譲**: 本 Sprint の実装 batch は **Codex に委譲** (CLAUDE.md §6.5.0 + .claude/rules/codex-usage-policy.md §14 = code change 系は Codex first)
  - Claude が batch 分割 (1 batch = 5-10 file / 1500-3000 行) + Codex prompt 作成
  - Codex `codex-task` で background 実装 (read-only sandbox、Claude が write back)
  - Claude が `adopt` / `reject` / `defer` 判定 → adopted のみ Edit/Write で反映
  - Phase 1: codex-review-loop (構造磨き 12 round) → Phase 2: codex-adversarial-loop (敵対視点 12 round)
- **server-side 制御の日本語化** (initial): Next.js 16 RSC + Server Action 前提で、Server Component 内で日本語文言を直接 hard-code (i18n framework 導入なし、polish 優先)。将来の多言語化 (P1+) で `lib/i18n/messages.ja.ts` 等の辞書化を検討
- **技術用語の原語維持 + 括弧併記方針**: `Action class` → 「アクション分類 (action_class)」、`Payload data class` → 「ペイロードデータ分類 (payload_data_class)」、`Hard Gate` → 「Hard Gate (P0 Exit 必須項目)」等、初出に括弧併記、以降は省略
- **enum label の翻訳辞書**: `agent_run.status` 16 種 / `policy_decision.reason_code` 13 種 / `action_class` 7 種 / `event_type` 37 種等の enum 値は **frontend 内の翻訳 dictionary** で英語 → 日本語 mapping、enum 値自体は不変
- **batch 構成**: 5-7 batches で分割、各 batch 完了で PR 起票 + admin bypass merge
  - Batch 1: navigation + layout (3-5 file)
  - Batch 2: Ticket / Approval list + detail (5-8 file)
  - Batch 3: AgentRun list + detail + state machine viewer (5-8 file)
  - Batch 4: Audit Log + Eval Dashboard (4-6 file)
  - Batch 5: Project Settings + login (4-6 file)
  - Batch 6: error / loading / 404 / empty state (3-5 file)
  - Batch 7 (任意): enum 翻訳辞書 + regression test (2-3 file)

## 実装チケット

### must_ship 1: 主要 UI 文言の日本語化 (batch 1-5)

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-UII-001 | navigation + layout (sidebar + topbar + footer) 日本語化 | 0.2 day |
| BL-UII-002 | Ticket / Approval list + detail page 日本語化 | 0.4 day |
| BL-UII-003 | AgentRun list + detail + state machine viewer 日本語化 | 0.4 day |
| BL-UII-004 | Audit Log + Eval Dashboard 日本語化 | 0.3 day |
| BL-UII-005 | Project Settings + login + 設定 page 日本語化 | 0.3 day |

### must_ship 2: error / empty / loading state の日本語化 (batch 6)

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-UII-006 | error / loading / 404 / empty state 日本語化 | 0.2 day |

### must_ship 3: enum 翻訳辞書 + regression test (batch 7)

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-UII-007 | enum 翻訳辞書 (`lib/i18n/enum-labels.ts` 等) + Vitest regression test | 0.3 day |

## タスク一覧

- [x] Sprint Pack 起票
- [x] Codex prompt 作成 (batch 1-7 ごと、必要時に codex-all-loops mode=code 起動)
- [x] BL-UII-001-007 順次実装 (Codex 委譲 + Claude adopt/reject/defer 判定 + write back)
- [x] Vitest regression test PASS (各 batch 内で完結)
- [x] Sprint Pack `## Review` 追加 + frontmatter `status: ready → completed`

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| 主要 UI 文言の日本語化 (batch 1-5) | ✅ | 翻訳粒度を主要 navigation + label 中心に絞る、補助 tooltip / placeholder は defer |
| error / empty / loading state の日本語化 (batch 6) | ✅ | 主要 error path 中心、稀少 path は defer |
| enum 翻訳辞書 + regression test (batch 7) | ✅ | 主要 enum (agent_run.status / action_class / reason_code) 中心、補助 enum は defer |

## 受け入れ条件

- [x] navigation 全 item が日本語
- [x] Ticket / Approval / AgentRun / Audit / Eval Dashboard 主要 page 全 label が日本語 (英語 placeholder / tooltip は除く)
- [x] error / loading / 404 / empty state が日本語
- [x] 技術用語は原語維持 + 括弧で日本語併記 (初出のみ、以降省略)
- [x] enum 値の表示 label は日本語 (enum 値自体は不変)
- [x] Vitest regression test PASS (各 page で日本語 label が表示確認)
- [x] codex-review-loop R{N} CLEAN signal + codex-adversarial-loop R{N} CLEAN signal (各 batch ごと)

## 検証手順

```bash
# typecheck + lint
cd frontend && pnpm typecheck && pnpm lint

# unit + component test
cd frontend && pnpm test

# E2E smoke (Playwright)
cd frontend && pnpm test:e2e --grep '日本語|UI label'

# 手動 visual check (Mac local)
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local up
# Chrome / Safari で http://localhost:3000/ 主要 page 確認
```

## レビュー観点

- 日本語訳の文脈適切性 (技術用語の機械翻訳ではなく自然な日本語)
- 技術用語の原語併記方針の一貫性 (初出 + 括弧併記)
- enum 翻訳辞書の網羅性 (agent_run.status 16 種 / action_class 7 種 / reason_code 13 種 全件 mapping)
- Server Component / Client Component 境界での翻訳辞書注入漏れなし
- 既存 unit / component test の regression なし (英語 label を query している test は日本語 label に追従更新)

## 残リスク

- 翻訳の機械化 (Codex 委譲) で文脈不適切な訳語が混入 → Claude adopt 判定 + 必要時に手動補正
- enum 翻訳の網羅漏れ → 各 batch で `grep -r "agent_run.status\|action_class\|reason_code"` で全 source 横断確認
- 既存 test の query を日本語 label に追従更新する作業量が増加 → batch 7 で regression test 集約 + Vitest snapshot 削減

## 次スプリント候補

本 Sprint 完了で UI 日本語化は終了。次は:

1. SP-016 UI/CLI parity (P0.1) — 日本語化済 UI と CLI message の整合確保
2. (任意 P1+) 多言語化 framework 導入 (next-intl 等)、ja/en 切替実装

## 関連 ADR

- 該当 ADR なし (UI polish、ADR Gate 11 種非該当 = code change ではあるが、認証 / DB schema / API 契約 / AI 権限 / MCP / Secrets / 外部公開 / 破壊的操作 / 広範囲 refactor / Provider / GitHub App permission のいずれにも該当しない)

## Review

### completed 2026-05-22

#### changed

- Batch 1: navigation と admin shell の accessible-name を日本語化。
- Batch 2: Ticket list/detail/create/edit の主要 label、empty/error、status/priority enum 表示を日本語化。
- Batch 3: Approval inbox/detail/decision form の主要 label、action_class/status/risk enum 表示を日本語化。
- Batch 4: AgentRun list/detail/state-machine viewer の主要 label と状態説明を日本語化。
- Batch 5: Audit Log と Eval Dashboard outer shell を日本語化。Hard Gate / KPI / audit contract 名は raw identifier として維持。
- Batch 6: Settings、Dashboard、login、notifications、root page、global loading / 404 / error state を日本語化。
- Batch 7: Research list/detail と research status / evidence relation label を日本語化し、completion record を追加。

#### verified

- `pnpm typecheck`: PASS
- `pnpm lint`: PASS
- `pnpm vitest run`: PASS
- `pnpm build`: PASS
- `git diff --check`: PASS
- Codex baseline review: batch PR ごとに findings 0 を確認。

#### invariants

- 技術識別子は raw value を維持: `Dev login token`, `tenant_id`, `project_id`, `actor_id`, `payload_data_class`, `allowed_data_class`, `event_type`, `reason_code`, `blocked_reason`, `Hard Gate`, `KPI`, `RepoProxy`, `SecretBroker`。
- enum 表示は日本語 label + raw enum value 併記に統一: Ticket、Approval、Research。
- UI 日本語化のみで、API schema / DB schema / auth behavior / policy behavior / route behavior は変更なし。
- raw secret / capability token / provider raw payload は DOM に追加していない。

#### deferred / carry-over

- 本格的な多言語 framework 導入は P1+。P0.1 では日本語 UI 固定。
- Eval Dashboard の metric_key / Hard Gate / KPI key / fallback reason は contract-bound raw identifier として維持。
- Research / PROV の `activities`, `entities`, `agents`, `relations`, `locator`, `relation`, `source` 等は schema 用語として raw identifier を併記・維持。
