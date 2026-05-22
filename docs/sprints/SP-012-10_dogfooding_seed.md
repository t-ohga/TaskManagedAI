---
id: "SP-012-10_dogfooding_seed"
type: "light"
status: "completed"
sprint_no: 12.10
created_at: "2026-05-22"
updated_at: "2026-05-22"
completed_at: "2026-05-22"
target_days: 3
max_days: 5
adr_refs: []
planned_adr_refs: []
related_sprints:
  - "SP-012-9_ui_wiring_completion"  # 前提: UI wiring 完成後の seed 投入
  - "SP-012-8_ui_i18n_japanese"      # 後続: seed 完了後の i18n 翻訳
risks:
  - "Sprint Pack / ADR / BL parse 失敗 (markdown frontmatter / 本文 schema drift)"
  - "重複 Ticket 投入 (idempotent seed 必要、re-run で行重複しない設計)"
  - "raw secret canary を seed 内容に含めない (Sprint Pack 本文 sanitize)"
---

最終更新: 2026-05-22

## 目的

TaskManagedAI 自身の **残作業 (現状の Sprint Pack / ADR / BL) を Ticket として DB seed 投入**し、TaskManagedAI を **TaskManagedAI 自身で管理可能** な状態にする (= dogfooding 完成)。SP-012-9 UI wiring 完成後の自然 trigger として、UI 上で全残作業を visualize + track できる運用状態を作る。

**位置付け**: post-P0 polish の **operational maturity Sprint**。新機能追加なし、既存 docs を parse → 既存 ticket schema に変換して DB に seed 投入するだけ。

## 背景

- P0 Exit declaration (PR #103) + SP-012-9 UI wiring 完成 (前 Sprint) で TaskManagedAI 機能は完備
- ただし DB は空 (fresh schema、actor seed のみ)、UI 上で見える Ticket / Approval / AgentRun が 0 件
- user 明示: 「現在の計画で残ってるものなどもいれてこの UI で管理できるようにもできますか？」(2026-05-22 session)
- 既存 docs (Sprint Pack / ADR / BL) を Ticket として DB に seed 投入 = **TaskManagedAI が自分自身を管理する operational state 確立**
- これは production 公開準備の prerequisite + 開発フロー dogfooding (実際に UI で運用してフィードバック得る)

### dogfooding seed 対象 docs

| カテゴリ | 場所 | 想定 件数 | Ticket 変換方針 |
|---|---|---:|---|
| Sprint Pack (heavy / light) | `docs/sprints/*.md` | 約 30 (SP-001 〜 SP-022-1) | 各 Sprint Pack = 1 Ticket (status = frontmatter status から map、Acceptance Criteria = 受け入れ条件、Evidence = `## Review` § ) |
| ADR | `docs/adr/*.md` | 約 25 (ADR-00001 〜 ADR-00029) | 各 ADR = 1 Ticket (status = frontmatter status から map、ADR Gate Criteria reference) |
| BL (P0 backlog) | `docs/実装計画/P0_バックログ.md` | 約 170 BL (BL-0001 〜 BL-0166 + α) | 各 BL = 1 Ticket (Sprint Pack の child、parent_ticket_id で link) |
| P0.1+ backlog | `docs/実装計画/00_ロードマップ.md` | 約 50 BL | 各 BL = 1 Ticket (P0.1 fence 内) |

合計 約 275 Ticket を seed 投入 (idempotent、re-run で重複しない設計)。

## 対象外

- Sprint Pack / ADR の機械的内容変更 (本 Sprint は parse + 投入のみ、Sprint Pack 自体は不変)
- 自動更新 cron (Sprint Pack `## Review` 章 update → Ticket status 自動同期は P0.1+ 別 Sprint Pack)
- ticket → Sprint Pack reverse update (Ticket UI 編集 → docs/sprints/ 書き換えは scope 外、Sprint Pack は git 管理のみ)
- multi-agent (SP-013) seed (multi-agent foundation 完了後の別 seed Sprint で実装)
- character image / AI Society viz (P1+/P2)

## 設計判断

- **idempotent seed**: seed CLI を re-run しても重複 row 投入しない (`ON CONFLICT DO UPDATE` or `unique (tenant_id, dogfooding_source_id)` 設計)
- **dogfooding_source_id field**: tickets に `metadata.dogfooding_source` (例: `{"type": "sprint_pack", "id": "SP-013_multi_agent_orchestration"}`) を持たせて re-run idempotency 保証
- **Sprint Pack parse は markdown frontmatter + 本文 regex**: heavy / light template の共通 fields (`id`, `status`, `sprint_no`, `target_days`, `max_days`, `adr_refs`, `related_sprints`, `risks`) を抽出
- **status mapping**: Sprint Pack frontmatter status → Ticket status の table
  - `draft` → `open`
  - `ready` → `open` (kickoff 待ち)
  - `in_progress` → `in_progress`
  - `completed` → `closed`
  - `proposed` (ADR) → `open` (review 中)
  - `accepted` (ADR) → `closed`
  - `superseded` (ADR) → `cancelled`
- **CLI**: `backend/app/cli/dogfooding_seed.py` 新規、`uv run python -m backend.app.cli.dogfooding_seed --dry-run / --apply` 経由実行
- **raw secret canary sanitize**: Sprint Pack 本文に test fixture canary pattern が含まれる場合 (例: `'AKIA' + 16 chars`)、seed 投入前に redact (audit / artifact と同 redaction layer 経由)

## 実装チケット

### must_ship 1: Sprint Pack seed (約 30 件)

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-DOG-001 | `backend/app/cli/dogfooding_seed.py` 新規 + Sprint Pack parser (frontmatter + 本文 §目的 / §受け入れ条件 / §Review 抽出) | 0.7 day |
| BL-DOG-002 | Ticket status mapping (Sprint Pack frontmatter status → ticket status enum) + Sprint Pack → Ticket 変換ロジック | 0.4 day |
| BL-DOG-003 | idempotent seed (dogfooding_source_id metadata + ON CONFLICT DO UPDATE) + re-run regression test | 0.4 day |

### must_ship 2: ADR seed (約 25 件)

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-DOG-004 | ADR parser (frontmatter status / acceptance_blocked_by / acceptance_resolved_by 抽出 + 本文 §背景 / §選択肢 / §採用案 抽出) | 0.5 day |
| BL-DOG-005 | ADR → Ticket 変換 + parent Sprint Pack Ticket と link (`ticket_relations` で `related_to`) | 0.3 day |

### must_ship 3: BL (P0 backlog) seed (約 170 件)

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-DOG-006 | BL parser (`docs/実装計画/P0_バックログ.md` 表 parse) + Sprint Pack child として `parent_ticket_id` link | 0.5 day |
| BL-DOG-007 | P0.1+ backlog (`docs/実装計画/00_ロードマップ.md`) parser + seed | 0.3 day |

### must_ship 4: 運用 SOP + verification

| BL | 内容 | 想定 effort |
|---|---|---|
| BL-DOG-008 | `docs/deploy/dogfooding-seed-sop.md` 新規 (re-run timing + drift 検出 + cleanup 手順) | 0.3 day |
| BL-DOG-009 | E2E verification (Mac local docker compose で seed apply → UI 上で 275 Ticket 表示確認) | 0.3 day |

## タスク一覧

- [ ] Sprint Pack 起票 (本 PR で完了予定、SP-012-9 + SP-012-10 同 PR 起票)
- [ ] BL-DOG-001 〜 BL-DOG-009 順次実装
- [ ] pytest contract test (CLI dry-run / apply / re-run idempotency / sanitize)
- [ ] Mac local docker compose で seed apply E2E
- [ ] Sprint Pack `## Review` 追加 + frontmatter `status: ready → completed`

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| Sprint Pack seed (約 30 件) | ✅ | parse 漏れあれば残 5 件まで defer 可、主要 SP-001 〜 SP-022-1 は必須 |
| ADR seed (約 25 件) | ✅ | proposed 全件必須、accepted 全件必須、superseded は defer 可 |
| BL (P0 backlog) seed (約 170 件) | ✅ | BL 全件投入、ただし P0.1+ backlog は first 30 件で OK (残は seed CLI で incremental 投入) |
| 運用 SOP + verification | ✅ | E2E verification は 5 page 主要 path で OK |

## 受け入れ条件

- [ ] dogfooding_seed CLI で `--dry-run` / `--apply` 動作 + idempotent re-run
- [ ] Sprint Pack 30 件 + ADR 25 件 + BL 170 件 = 約 275 Ticket が DB に投入
- [ ] UI (SP-012-9 wiring 完成後) 上で 275 Ticket が visualize される
- [ ] Sprint Pack frontmatter `status: completed` の Ticket が UI 上で `closed` 表示
- [ ] ADR `status: accepted` の Ticket が UI 上で `closed` 表示
- [ ] BL は parent Sprint Pack Ticket と `ticket_relations` で `parent_of` link
- [ ] raw secret canary が seed 内容に含まれない (sanitize layer 経由)
- [ ] codex-review-loop R{N} CLEAN signal + codex-adversarial-loop R{N} CLEAN signal

## 検証手順

```bash
# CLI dry-run (DB 変更なし)
uv run python -m backend.app.cli.dogfooding_seed --dry-run

# CLI apply (DB に投入)
uv run python -m backend.app.cli.dogfooding_seed --apply

# idempotency 確認 (再 apply で重複なし)
uv run python -m backend.app.cli.dogfooding_seed --apply
# expected: rows_added=0, rows_updated=N (frontmatter 変更分のみ)

# pytest contract test
uv run pytest tests/cli/test_dogfooding_seed.py -v

# E2E (Mac local docker compose)
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local up
docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.local exec api \
  uv run python -m backend.app.cli.dogfooding_seed --apply
# Chrome / Safari で http://localhost:3000/tickets で 275 Ticket 表示確認
```

## レビュー観点

- Sprint Pack / ADR / BL parse の robust 性 (frontmatter drift / 本文 schema 変更で fail-fast vs fail-soft 設計)
- Ticket status mapping の semantic 正確性 (`completed` Sprint → `closed` Ticket / `proposed` ADR → `open` review)
- idempotent seed の re-run regression (同 source 同 status で row 重複なし、status update のみ反映)
- raw secret canary sanitize の網羅性 (test fixture pattern + 22 prohibited keys 全件)
- parent / child link の正確性 (`ticket_relations` invariant 維持、cross-project / cross-tenant reference なし)

## 残リスク

- Sprint Pack frontmatter schema drift で parse 失敗 → fail-fast + drift 検出 log、手動修正
- BL parse の table 構造変更で全件失敗 → schema バリデーション + 部分 success 許容
- raw secret canary sanitize 漏れ → audit / artifact と同 redaction layer 経由で防御
- 275 Ticket 投入後の UI performance → pagination 設計 (SP-012-9 BL-UIW-001 で確保)

## 次スプリント候補

本 Sprint 完了で dogfooding 完成、TaskManagedAI 自身を UI で完全管理可能。次は:

1. SP-012-8 UI i18n japanese (seed 投入後の Ticket label 日本語化、最大 valuable)
2. SP-013 batch 0 (Multi-Agent Orchestration Foundation、並行可能)
3. (P1+ 任意) Ticket UI 編集 → docs/sprints/ reverse update 自動化 (現状は read-only seed のみ)

## 関連 ADR

該当 ADR なし: dogfooding seed は data 投入のみ、ticket schema 不変、新 ADR Gate 11 種いずれも非該当 (CLI 新規だが ADR Gate 11 種は CLI 自体に該当しない、認証 / DB schema / API 契約 / AI 権限 / MCP / Secrets / 外部公開 / 破壊的 / 広範囲 refactor / Provider / GitHub App permission いずれも不変)。

## Review

最終更新: 2026-05-22

### changed (3 Batch 完遂)

| Batch | scope | PR | merge SHA |
|---|---|---|---|
| A | Sprint Pack parser + seed CLI 新規 (27 件) | #113 | 413cf10e |
| B | ADR parser + seed 拡張 (29 件) | #114 | 152fc982 |
| C | BL parser + seed 拡張 (211 件) | #116 | 30957519 |
| D | 運用 SOP (`docs/deploy/dogfooding-seed-sop.md`) + Sprint Pack completed 化 | 本 PR | - |

### verified

- 累計 27 + 29 + 211 = **267 件 Ticket DB 投入 ready**
- pytest 19 contract test PASS (Sprint Pack 8 + ADR 6 + BL 5)
- 全 Sprint Pack frontmatter parse 成功 (parse failures 0 件)
- 全 ADR frontmatter parse 成功 (parse failures 0 件)
- 全 BL row id format `BL-NNNN[a-z]?` integrity verify
- idempotent re-run 設計 (slug 一意性 + `metadata.dogfooding_source.id` 識別)
- ruff + mypy clean (239 source files)

### deferred

- BL → Sprint Pack の `ticket_relations` parent/child link 投入 (現状は `metadata` 内表現、本格 link は P0.1+ で別 Sprint Pack)
- Sprint Pack `## Review` 章 change-log を `audit_events` に投入 (履歴 visualize、P0.1+)
- Ticket UI 編集 → docs/sprints/*.md reverse update 自動化 (現状は read-only seed のみ、P1+)
- P0.1+ backlog (`docs/実装計画/00_ロードマップ.md`) 別 file から seed 投入 (P0.1+ 着手時)

### risks (residual)

- Sprint Pack frontmatter schema drift: 本格運用で frontmatter 変更時に parse 失敗の可能性 (fail-fast 設計、test integrity verify でカバー)
- 267 Ticket 投入後の UI performance: pagination (limit=200) で対応、SP-012-9 BL-UIW-001 で frontend wiring 完成
- production deployment 前の dogfooding seed cleanup: SOP §6 で SQL cleanup 手順明記

### next

- SP-012-10 完遂で dogfooding 運用試験完成
- 次は SP-013 batch 0 (Multi-Agent Orchestration Foundation) 着手可能
- 並行で SP-012-9 残 batch (Approvals は完成済確認 + Agent Runs / Audit / Settings backend route 必要時に拡張)
- SP-012-8 UI i18n japanese は seed + wiring 完了後の最大価値 timing で着手
