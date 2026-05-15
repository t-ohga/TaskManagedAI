---
id: DOC-CLI-README
title: "TaskManagedAI CLI 設計 (ContextResolver state machine + capability matrix + tm/tmai canonical + taskhub host/admin 境界)"
type: design_doc
status: proposed
revision: R0
created_at: "2026-05-15"
updated_at: "2026-05-15"
source_plan_section: "docs/設計検討/修正まとめ統合計画.md §5 QL-F + §3.2 P-05 + §3.2 P-06"
landing_sprint: "SP-016_ui_cli_parity (既存) + ADR-00015 update + ADR-00024 (proposed、project auto-discovery placeholder)"
adr_gate_criteria_trigger:
  - "#3 (API 契約 / event schema、CLI capability matrix で expose する操作)"
  - "#6 (Secrets 管理、CLI 経由 secret_access)"
  - "#7 (外部公開、CLI バイナリ配布)"
related_documents:
  - "../adr/00015_ui_cli_parity.md"
  - "../sprints/SP-016_ui_cli_parity.md"
  - "../sprints/SP-012_p0_acceptance.md (`tm` / `taskhub` 表記)"
  - "../設計検討/修正まとめ統合計画.md §3.2 P-05 + P-06 (CLI canonical 反転 / ContextResolver)"
risks:
  - "CLI canonical `tm` / `tmai` の表記 drift (U-04 で確定後、ADR-00015/SP-016/SP-012/本 doc/test file の一括更新が必要)"
  - "ContextResolver の ambiguous resolution で mutating command が実行される (fail-closed 違反)"
  - "ADR-00024 (project auto-discovery、QL-G で起票予定) と memory boundary が CLI context 経路で混入 (deny-by-default 違反)"
---

# TaskManagedAI CLI 設計

## 0. このドキュメントの扱い

**doc-only design doc**。本 doc 自体は CLI バイナリ実装許可ではない。CLI 実装は SP-016_ui_cli_parity accepted (P0.1 候補) + ADR-00015 update accepted 後の別 run で行う。

本 doc は:

- 修正まとめ統合計画 §5 QL-F の write scope (`ADR-00015 update + SP-016 + 本 docs/cli/README.md + ADR-00024 placeholder`) の core spec
- CLI canonical (`tm` / `tmai`) の選択肢、ContextResolver state machine、13 capability matrix、mode matrix、ambiguous mutating command fail-closed acceptance を doc 化
- **U-04 (CLI canonical 反転 `tm`→`tmai` 採否) は spec 記録のみ、決定は別 run** (User 確定後の ADR-00015/SP-016/SP-012/本 doc/test file 一括更新)
- ADR-00024 (project auto-discovery + memory boundary) placeholder を SP-016 で reserve、QL-G run で実 ADR 起票

## 1. 不変条件 (本 CLI 設計で破ってはならない)

| # | 不変条件 | 根拠 |
|---:|---|---|
| 1 | CLI ContextResolver の **ambiguous / unresolved 状態では mutating command を実行しない** (fail-closed) | `.claude/CLAUDE.md §2 #10` (cross-project memory boundary deny-by-default) の延長、CLI 経由でも同 invariant |
| 2 | CLI canonical `tm` / `tmai` の選択 (U-04 確定) 後、**ADR-00015 + SP-016 + SP-012 + 本 doc + CLI test file** を **同一 PR で doc-only 一括更新** (実装 file の更新は反転実装 Sprint Pack accepted 後の別 run) | R29 plan §5 QL-F 重要制約 |
| 3 | `taskhub` (host / admin) と `tm`/`tmai` (project user) の **CLI 境界明示**、admin CLI から project mutating command を invoke する path は restricted | R29 plan §3.2 P-05 + R5 F-R5-002 反映 |
| 4 | CLI 経由の `secret_access` / `merge` / `deploy` / `provider_call` は **全 autonomy_level で human approval 必須** (ADR-00025 §不変条件 #1 と整合) | ADR-00025 §10.3 不変条件 #1 |
| 5 | CLI memory backend (history / preference / cache) と project / repo context の **boundary 物理分離** (cross-project retrieval deny-by-default) | ADR-00024 候補 (QL-G で起票)、`.claude/CLAUDE.md §2 #10` |
| 6 | 本 doc 自体は doc-only、CLI バイナリ実装は SP-016 accepted + ADR-00015 update accepted 後の別 run | R29 plan §5 QL-F 重要制約 |

## 2. CLI canonical の選択肢 (U-04 で確定)

R29 plan P-05 で提案された CLI canonical `tm` → `tmai` 反転を spec 化:

| 選択肢 | 概要 | 利点 | 欠点 |
|---|---|---|---|
| A (現状維持): `tm` canonical | 既存 `tm` をそのまま使う、ADR-00015 / SP-016 / SP-012 が現状の `tm` 表記のまま | reverse 不要、既存 SP / ADR の wording 修正不要 | `tm` は short suffix で global namespace 衝突可能性 (`tmux` 等)、`taskmanagedai` の semantic alignment 弱い |
| B (反転): `tmai` canonical | `tm` → `tmai` に rename、既存 `tm` alias を soft deprecation (1 sprint period) | global namespace 衝突回避、`taskmanagedai` semantic alignment 強い | ADR-00015 / SP-016 / SP-012 / 本 doc / CLI test file の一括更新必要、user CLI history breaking change |

U-04 確定: User 確認待ち、本 run では spec 記録のみ。確定後の選択肢:

- **A safe (Recommended)**: 現状維持 (`tm` canonical sticks)、reverse コスト回避
- **B aggressive**: `tmai` 反転 + 既存 `tm` を 1 sprint alias deprecation、ADR-00015 update + 全 doc 一括 PR

## 3. ContextResolver state machine

R29 plan P-06 で提案された ContextResolver state machine spec (CLI 起動時の project context 解決順序):

```
Entry: CLI command invocation (e.g., `tm ticket list` or `tm decision approve <id>`)

State 1: explicit_arg
  - --project <project_id> 等 explicit CLI flag が指定されている → resolve_complete
  - 指定なし → next State 2

State 2: env
  - `TASKMANAGEDAI_PROJECT_ID` 等 env var が設定されている → resolve_complete
  - 設定なし → next State 3

State 3: cwd_git_remote
  - 現在 cwd の git remote URL から project_id を auto-discovery
  - 解決 success (一意な project が見つかった) → resolve_complete
  - 解決 failure (no remote / multiple project candidates / auth error) → next State 4

State 4: profile
  - user profile (`~/.taskmanagedai/profile.yaml`) の `default_project_id` が設定されている → resolve_complete
  - 設定なし → next State 5

State 5: interactive_or_fail
  - terminal が interactive (stdout=tty) → interactive prompt で user に project 選択を要求
  - terminal が non-interactive (CI / pipe) → **fail-closed**
  - non-interactive で mutating command (task_write / repo_write / pr_open / secret_access 等) なら fail-closed: 「ambiguous project, specify --project explicitly」
  - non-interactive で read-only command (task list / status show 等) なら fall-through with empty project context warning

resolve_complete: project_id 確定、command 実行
fail-closed: error exit (CLI exit code 2)、command 実行しない
```

### 3.1 不変条件 (ContextResolver fail-closed)

- **mutating command + ambiguous/unresolved context = fail-closed**: `task_write` / `repo_write` / `pr_open` / `secret_access` / `merge` / `deploy` / `provider_call` 全 7 action_class で、ContextResolver が State 5 で interactive fallback できない場合は fail-closed (本 doc §1 #1 不変条件)
- **read-only command + unresolved context = best-effort warning**: read-only operation は project context なしでも fall-through 可能、ただし「project_id 未解決」warning を stderr に出力

## 4. 13 capability matrix (CLI 経由 capability の一覧)

P0 で CLI から呼べる capability を 13 種に固定 (本 doc §1 #2 不変条件で、U-04 確定後の一括更新対象):

| # | capability | command 例 | action_class | autonomy_level human approval |
|---:|---|---|---|---|
| 1 | task_list | `tm ticket list` | (read-only、no action_class) | 不要 |
| 2 | task_show | `tm ticket show <id>` | (read-only) | 不要 |
| 3 | task_write | `tm ticket update <id> --acceptance-criteria "..."` | task_write | L0=approval / L1-L3=auto-allow (low_risk_profile 通過時) |
| 4 | task_create | `tm ticket create --title "..."` | task_write | 同上 |
| 5 | approval_list | `tm approval list --status pending` | (read-only) | 不要 |
| 6 | approval_decide | `tm approval approve <id> --rationale "..."` (decider human-only) | (approval flow 自体、action_class なし) | **全 level で human only** |
| 7 | repo_status | `tm repo status` | (read-only) | 不要 |
| 8 | repo_push | `tm repo push --branch ...` | repo_write | L0/L1=approval / L2-L3=auto-allow (docs only diff / file count <= 3) |
| 9 | pr_open | `tm pr open --base main --head feat/foo --draft` | pr_open | L0-L2=approval / L3=auto-allow (Draft PR + low_risk_profile、ただし SecretBroker capability 内包は除外) |
| 10 | secret_resolve | `tm secret use <secret_ref>` | secret_access | **全 level で human approval 必須** (ADR-00025 §不変条件 #1) |
| 11 | run_show | `tm run show <agent_run_id>` | (read-only) | 不要 |
| 12 | run_cancel | `tm run cancel <agent_run_id>` | (cancel action、approval なしで OK if requester==operator) | requester==operator なら approval 不要、それ以外は approval 必須 |
| 13 | provider_call | `tm provider call --provider openai --feature chat_completion ...` | provider_call | **全 level で human approval 必須** (ADR-00025 §不変条件 #1) |

merge / deploy は P0 deny (ADR-00009 §採用案準拠)、CLI からも invoke 不可。

## 5. mode matrix (interactive / non-interactive / agent-mode)

CLI 実行 mode を 3 種に分離:

| mode | 条件 | mutating command の挙動 |
|---|---|---|
| interactive | stdout=tty AND --no-interactive 不指定 | ContextResolver State 5 で prompt 表示可能、approval 要 command は interactive confirm |
| non-interactive | stdout=pipe OR --no-interactive 指定 (CI / script context) | ContextResolver State 5 で fail-closed、approval 要 command も fail-closed (CI script で approval を簡略化させない) |
| agent-mode | --agent-mode 指定 (AI agent からの subprocess invocation) | 全 mutating command が **fail-closed**、agent からの CLI invocation は直接 mutation 経路を作らない (AI 出力直結禁止 invariant `.claude/CLAUDE.md §2 #1` の延長)、AI agent は AgentRun 経由でのみ mutation を要求する |

## 6. ambiguous mutating command fail-closed acceptance

本 doc §3.1 + §5 の延長として、以下の fail-closed acceptance spec を SP-016 acceptance に cross-reference:

- ContextResolver で project_id が **未解決** (State 1-4 全 fail) + mutating command 指定時 → **fail-closed**、CLI exit code 2、stderr に「ambiguous project context, specify --project explicitly」
- ContextResolver で project_id が **複数候補** (cwd git remote が multi-project の monorepo) + mutating command 指定時 → **fail-closed**、stderr に候補一覧 + 「specify --project explicitly」
- agent-mode で mutating command 指定時 → **fail-closed** (上記 §5)
- non-interactive + approval 要 command (capability matrix #6 / #10 / #13 等) → **fail-closed** (CI script で approval を簡略化させない)

## 7. taskhub host/admin CLI 境界

`taskhub` (host / admin) と `tm`/`tmai` (project user) の CLI 境界:

| CLI | scope | 想定 user | mutating command |
|---|---|---|---|
| `taskhub` | host / admin operation (Sprint Pack / ADR / tenant 設定 / SOPS rotation 等) | host admin (個人運用の場合 user 自身、tenant 運用の場合 admin role) | admin scope (`tenant_create` / `sprint_pack_admin_close` / `sops_rotate` 等)、project mutating command (`task_write` / `repo_write` 等) は **invoke 不可** |
| `tm` / `tmai` | project user operation (ticket / approval / repo / agent run / provider 等) | project user | 上記 13 capability matrix のみ、admin scope は **invoke 不可** |

`taskhub` 経由で project mutating command を直接 invoke する path は **restricted** (本 doc §1 #3 不変条件)。

## 8. CLI test file 一括更新 future spec

U-04 確定 (B 反転採用) 後の同一 PR 一括更新対象:

- ADR-00015 update (canonical `tm`→`tmai` decision + 反転実装 Sprint Pack の reference)
- SP-016_ui_cli_parity (capability matrix table の `tm` → `tmai` 一括)
- SP-012_p0_acceptance (`tm` / `taskhub` 表記の整合)
- 本 docs/cli/README.md (canonical `tmai` 全置換)
- `taskmanagedai-cli/tests/**/*.test.ts` (CLI test file の `tm` → `tmai` 一括 rename + alias deprecation test 追加)

ただし、**本 QL-F run では test file 変更しない** (R29 plan §5 QL-F 重要制約)、test file 更新は反転実装 Sprint Pack accepted 後の別 run。

## 9. ADR-00024 placeholder (project auto-discovery memory boundary)

SP-016 で `<!-- ADR-00024 placeholder -->` marker を置く位置を spec:

- SP-016 §設計判断 / §関連 ADR で「project auto-discovery + memory boundary の deny-by-default は ADR-00024 (proposed、QL-G で起票予定) で扱う」と明示
- ADR-00024 実起票は QL-G run、SP-016 placeholder は marker のみで本 QL-F run では実 ADR 起票しない (本 doc §1 #5 不変条件)

## 10. QL-D 教訓適用

本 doc は `.claude/CLAUDE.md §6.5.0` (PR #14 で追加) の **「doc-only future spec と code 変更の品質追求は別軸」教訓** を適用。本質目的 (CLI canonical 選択肢 + ContextResolver state machine + 13 capability matrix + mode matrix + fail-closed acceptance + taskhub host/admin 境界 + ADR-00024 placeholder spec) は本 run の Phase 0 で達成済、R1-R3 軽い polish で merge ready 判断。残 wording polish は U-04 確定後の反転実装 Sprint Pack accepted 時に再議論する。

## 11. 関連 ADR / Sprint Pack

- ADR-00015 (UI/CLI parity、accepted) update: 本 QL-F run で `## QL-F update` section を末尾に追加、CLI canonical 選択肢 + ContextResolver state machine spec を cross-reference
- ADR-00024 (project auto-discovery + memory boundary、proposed、QL-G で起票): 本 doc §1 #5 + §9 で placeholder reference
- ADR-00025 (autonomy policy profiles、proposed、QL-B PR #12 で起票済): 本 doc §4 capability matrix の autonomy_level column と整合
- SP-016_ui_cli_parity (既存): 本 QL-F run で `## QL-F update` section を末尾に追加、本 doc §4 13 capability matrix + §7 taskhub 境界を cross-reference
- SP-012_p0_acceptance: `tm` / `taskhub` 表記の整合 (U-04 確定後の同一 PR 更新対象)

## 12. 関連資料

- `docs/設計検討/修正まとめ統合計画.md §5 QL-F` (R29 plan、本 doc の source)
- `docs/設計検討/修正まとめ統合計画.md §3.2 P-05 + P-06` (CLI canonical 反転 + ContextResolver state machine)
- `.claude/CLAUDE.md §6.5.0` (doc-only spec と code 変更の品質追求は別軸、本 doc に適用)
