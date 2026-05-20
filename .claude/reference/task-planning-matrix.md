# Task Planning Matrix — 計画必要度の決定マトリクス

最終更新: 2026-05-20 (新規、SP-022 T04 + T07 完了後の運用知見から派生)

> **目的**: Sprint 内タスクごとに「どこまで plan file を作るか」を毎 session 再判断する coordination cost を回避する。
>
> 本 reference は **常時ロードしない (`.claude/reference/` 配下)**、Sprint Pack 起票時 / 着手前判断時に参照する。
> 各 Sprint Pack のタスク一覧で `plan_status` annotation を本マトリクスから引用すると、後続 session が迷わず引き継げる。

## 1. 計画レベル 4 種

| level | symbol | 計画ファイル | codex-plan-review | 適用基準 (どれか 1 つでも当てはまれば) |
|---|---|---|---|---|
| **heavy plan** | 🟥 | `.claude/plans/<slug>.md` 詳細 plan (§1-§13 構造、目的 / scope / 実装範囲 / 検証手順 / リスク / DoD / R{N} adoption log) | **R1-R3 必須** (Phase A 構造 → Phase B 実装可能性 → CRITICAL final) | (a) ADR Gate Criteria 11 種 のいずれか直結<br>(b) 3+ file 横断 (新規 src + test + workflow + docs 等)<br>(c) multi-day scope (5+ file 想定 / 2+ commit batch 必要)<br>(d) CRITICAL invariant 直結 (AgentRun 16 状態 / ContextSnapshot 10 列 / Provider Compliance 13 reason_code / SecretBroker raw secret 非保存 / Tenant boundary / Approval 4 整合 / runner_mutation_gateway / tool_mutating_gateway_stub)<br>(e) 新規 CI 機械検査 / 新規 ハーネス導入<br>(f) Sprint Exit 前最終 batch |
| **light plan** | 🟨 | `.claude/plans/<slug>.md` 軽量 plan (§1-§11 短縮、目的 / scope / 実装範囲 / 検証 / DoD)、`13. R{N} adoption log` は実 finding に応じて | **R1 minimum + 採否判定** (R2-R3 は HIGH+ 残存なら継続、なければ skip 可) | docs-only 1 file / 既存 pattern 沿った定型 / 1-2 file 微変更 / typo より大きいが invariant 直結ではない |
| **plan deferred** | ⛔ | 起票はするが計画着手は **依存解消後** (`blocked_by:` annotation に依存先を明記) | (依存解消後に level 再判定) | (a) 別 Sprint / 別 task の完了依存 (例: SP-013 multi-agent skeleton 完了が前提)<br>(b) 外部リソース依存 (例: 3 host 取得 / 物理 drill 環境)<br>(c) user 介在依存 (例: 認証情報 / SSH key 提供) |
| **plan unnecessary** | ⚪ | 計画ファイル不要、直接実装 | (該当しない) | (a) typo / wording / コメント fix<br>(b) 30 行未満かつ既存 pattern 沿った定型 (import 追加 / type ignore コメント / retry expected count 修正等)<br>(c) lint fix / formatter / linter 自動 fix<br>(d) frontmatter `updated_at` 等 metadata-only 更新<br>(注: Claude 単独 commit 許容条件は `.claude/rules/codex-usage-policy.md §14.2` 参照 |

## 2. 適用例 (SP-022 task の場合)

| Task | plan_status | 理由 |
|---|---|---|
| SP022-T01 (framework intake CI 機械化) | 🟥 heavy (完了済 PR #70) | (a) ADR-00020 acceptance 直結 + (e) 新規 CI 機械検査 (8 verify item) + (b) 4+ file 横断 (script + scanner + workflow + test) |
| SP022-T02 (`taskhub migrate` 自動化) | 🟥 heavy + phase 分割必須 (Phase 1 完了 PR #75 / Phase 2 backup real I/O 完了 PR #77 / Phase 3 restore real I/O 完了済) | (b) 7 subcommand multi-day scope + (a) ADR Gate Criteria #6 (Secrets) + #11 (broad refactor) 直結 + (d) SecretBroker boundary 直結 (age key / Ed25519 signature)。Phase 分割 = Phase 1 CLI scaffold + signed approval / Phase 2 backup real I/O / Phase 3 restore real I/O (24 rounds 58 findings 100% adopt) / Phase 4 freeze-thaw split-brain + rollback standalone real I/O |
| SP022-T03 (半年 drill SOP) | 🟥 heavy (完了済 PR #71) | (e) 新規 CI gate (`check_drill_timer_alert_only.sh`) + (b) 3+ file 横断 (SOP docs + scanner + workflow + tests) + (a) ADR-00021 §14.2 #4 PGA-F-013 直結 |
| SP022-T04 (Phase E trace audit) | 🟥 heavy (完了済 PR #72) | (e) 新規 CI gate (`check_phase_e_trace.sh`) + (b) 4+ file 横断 (scanner + wrapper + tests + workflow + SP-022 matrix update) + (a) ADR-00020 audit-only gate 直結 |
| SP022-T05 (AC-HARD multi-agent re-verify) | ⛔ deferred (`blocked_by: SP-013 multi-agent skeleton`) | (a) SP-013 multi-agent skeleton (P0.1) 依存、本 Sprint 中の着手不可。SP-013 完了後に level 再判定 (heavy 想定) |
| SP022-T06 (KPI baseline 3 host) | 🟨 light + 部分実装可 (host 取得済範囲のみ) | spec は SP-022 line 100 (5 metric median 取得)、Mac 単独でも meaningful baseline、Linux/VPS は (b) 外部リソース依存で deferred、Mac 部分は light で完結可 |
| SP022-T07 (production checklist skeleton) | 🟨 light (完了済 PR #73) | docs-only 1 file、F-R2-005 で本実装禁止 6 項目明示、既存 SP022-T01/T03 SOP pattern 沿った定型 |
| SP022-T08 (SP-012 carry-over 9 件) | 🟥 heavy + batch 分割必須 | (b) taskhub real I/O 10 subcommand + 実 DB write + signed journal CLI + private staging E2E + frontend wiring = 5+ batch 想定 + (a) ADR Gate Criteria #1 (DB schema) + #4 (AI 権限) + #6 (Secrets) + #11 (broad refactor) 直結 + (c) multi-day scope。Batch 分割 = batch 1 CLI foundation / batch 2 backup-restore subcommand / batch 3 migrate-status-verify / batch 4 BL-0149 実 DB write / batch 5 signed journal CLI / batch 6 frontend backend wiring |
| SP022-T09 (実機 host migration drill) | ⛔ deferred (`blocked_by: SP022-T02 + 物理 drill 環境`) | (b) SP022-T02 (taskhub migrate impl) 依存 + (b) 物理 host 2 台 (Mac + VPS) + RTO≤4h 計測必要 + (c) user 介在依存 |

## 3. Sprint Pack frontmatter / タスク一覧への annotation 方式

`docs/sprints/SP-NNN_<slug>.md` の `## 実装チケット` および `## タスク一覧` 内で、各タスクに `plan_status` を inline annotation:

```markdown
## 実装チケット

- **SP022-T02** (`plan_status: 🟥 heavy + phase 分割必須`): `taskhub migrate` 自動化 (rollback / split-brain 防止 / age key 運搬連携)
- **SP022-T05** (`plan_status: ⛔ deferred (blocked_by: SP-013)`): AC-HARD-01〜07 fixture を multi-agent 文脈で再 verify
- **SP022-T06** (`plan_status: 🟨 light + 部分実装可 (Mac 単独可、Linux/VPS deferred)`): KPI baseline 設定
- **SP022-T07** (`plan_status: 🟨 light (完了済 PR #73)`): production 公開準備 checklist draft
- **SP022-T08** (`plan_status: 🟥 heavy + batch 分割必須 (5+ batch)`): SP-012 carry-over 完了
- **SP022-T09** (`plan_status: ⛔ deferred (blocked_by: SP022-T02 + 物理 drill)`): 実機 host migration drill
```

## 4. plan_status の運用ルール

### 4.1 起票時

- Sprint Pack 作成時に **全タスクへ plan_status を付与**する (本マトリクス §1-§2 から選択)
- 判断に迷う場合は `🟥 heavy` 寄りに振る (over-plan は under-plan より安全、品質優先 invariant)

### 4.2 着手前

- 🟥 heavy → `.claude/plans/<slug>.md` plan file 作成 + codex-plan-review R1-R3 + READY 後に実装着手
- 🟨 light → `.claude/plans/<slug>.md` 軽量 plan + codex-plan-review R1 + 採否判定後に実装着手
- ⛔ deferred → 着手前に `blocked_by:` 依存解消を確認、再 level 判定
- ⚪ unnecessary → 直接実装 (Claude 単独 commit 許容条件 `.claude/rules/codex-usage-policy.md §14.2` 遵守)

### 4.3 完了時

- Sprint Pack の `plan_status` を `(完了済 PR #N)` で update (本 reference §2 適用例参照)
- Sprint Pack `## Review` に completion record + codex-plan-review R{N} 累計 finding 集計を追記

### 4.4 plan_status change の trigger

- 依存解消 (SP-N 完了 / 外部リソース取得 / user 介在完了) → `⛔ deferred` から 🟥 heavy / 🟨 light へ再判定
- scope 変更 (Codex review で scope creep 検出 / user 指示で範囲拡大) → 🟨 light → 🟥 heavy へ昇格
- 完了 → 任意の level から `(完了済 PR #N)` annotation 付与

## 5. 関連

- `.claude/rules/sprint-pack-adr-gate.md` (ADR Gate Criteria 11 種、heavy plan 判定の根拠)
- `.claude/rules/codex-usage-policy.md §14.1` (mandatory Codex review gates、heavy plan の codex-plan-review R1-R3 必須 trigger)
- `.claude/rules/codex-usage-policy.md §14.2` (Claude 単独 commit 許容条件、plan unnecessary 適用条件)
- `.claude/rules/instincts.md §1` (Sprint Pack を飛ばさない、本マトリクスの上位原則)
- SP-022 PR #70 / #71 / #72 / #73 (heavy / heavy / heavy / light の確立 pattern)
