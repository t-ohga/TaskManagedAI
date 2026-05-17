# TaskManagedAI 開発ルール・ワークフロー規約

> 本ファイルは TaskManagedAI の Claude Code プロジェクトスコープ指示です。常時ロードされるワークフロー骨格として、詳細なルール、エージェント、フック、スキル、参照資料は `.claude/rules/` と `.claude/reference/` に分離します。

## 1. このプロジェクトについて

TaskManagedAI は、AI 実装支援を組み込んだ個人向けタスク管理ツールです。Deep Research から実装 PR までを、証拠、判断、承認、実行ログ、コスト、レビュー結果とともに管理し、AI の作業をチャットで消える作業ではなく、再現可能で評価可能な開発プロセスとして扱います。

P0 は個人専用、Tailscale 閉域、単一 VPS、Docker Compose を前提にします。ただし、tenant 境界、workspace / project / repository 境界、actor / principal、policy、approval、artifact、event、secret_ref、ProviderAdapter、ContextSnapshot は将来のチーム運用と商用化へ低コストで移行できる形で初期から維持します。中核は Sprint Pack、ADR、Hard Gates、Provider Compliance Matrix v2、SecretBroker、AgentRun 状態機械です。

## 2. 重要原則

以下は alwaysApply として扱います。実装者、レビュー担当、サブエージェント、外部エージェント出力の採否判断に常に適用してください。

1. **AI 出力直結禁止**
   - AI 出力を直接 command、SQL、workflow、外部 tool 操作へ接続しない。
   - AI は plan、patch、review、evidence、policy decision などの artifact を生成するだけに留める。
   - 採用前に schema validation、policy lint、human approval、runner sandbox、audit event を通す。
   - 禁止例: AI 出力 SQL を DB に適用、AI 出力 workflow を `.github/workflows/**` に書込、AI 出力 tool call をそのまま実行、AI 出力 patch を approval なしに repo push。

2. **deny-by-default**
   - Tailscale、Tool、Repo、Secret、merge、deploy は明示許可がなければ拒否する。
   - Tailscale は Serve / SSH の閉域運用を前提にし、Funnel や public ingress は P0 対象外。`tag:taskhub-ci` も最小 grants のみ許可する。
   - Tool は P0 では `local|stdio` と read-only `search|fetch` 中心。書込系 MCP / 外部 tool は `tool_mutating_gateway_stub` で deny-only。
   - Repo 書込は GitHub App + RepoProxy / Draft PR flow を通し、merge / deploy は P0 常時 deny または明示承認対象。
   - Secret 値は AI、runner、DB、artifact export に渡さない。

3. **Sprint Pack 必須ゲート / ADR Gate Criteria 11 種**
   - すべての機能単位 Sprint は実装前に `docs/sprints/` の Sprint Pack を持つ。
   - 軽量 Pack は目的、対象外、受け入れ条件、検証手順、残リスクを含める。
   - 重量 Pack は背景、設計判断、実装チケット、ADR 参照、レビュー観点、must_ship / defer_if_over_budget を含める。
   - 次の 11 種は実装前 ADR 必須: 認証・認可、DB schema、API 契約、AI エージェント権限、MCP / tool 権限、Secrets 管理、外部公開、破壊的操作、広範囲リファクタ、Provider 追加 / 切替、GitHub App permission 変更。
   - P0 Exit は Hard Gates 7 全件達成かつ Quality KPIs 5 の未達 1 個以下で判定する。

4. **Provider Compliance Matrix v2 機械判定 invariant**
   - Provider 送信可否は `config/provider_compliance.toml` と `docs/基本設計/04_セキュリティ_権限_監査設計.md` を正本にする。
   - `payload_data_class` は request / artifact metadata から事前算出済みで、ProviderAdapter は再算出しない。
   - `allowed_data_class` は caller 入力ではなく Matrix からのみ解決する。
   - `payload_data_class` 未設定、provider / feature 未登録、Matrix 外、`payload_data_class > allowed_data_class` は送信前 deny。
   - `unverified` が残る provider / feature には `payload_data_class >= confidential` を送らない。
   - data class ordinal は `public < internal < confidential < pii` の単一順序で比較し、実装は `{public:0, internal:1, confidential:2, pii:3}` の ordinal map を使う。文字列比較や別順序は禁止。

5. **SecretBroker atomic claim / actor-run-fingerprint binding**
   - P0 の SecretBroker は FastAPI 内 service module とし、DB には secret 値を保存せず `secret_ref` のみ保存する。
   - capability token は短命、one-time、scope / operation bound とする。
   - redeem は check → execute → mark used の逐次処理を禁止し、DB transaction / conditional UPDATE による atomic claim で行う。
   - atomic claim は actor、run、request_fingerprint、operation allowlist を同一文で binding する。token 値が正しくても actor / run / fingerprint が一致しない場合は deny。
   - raw secret、provider key、GitHub installation token、Tailscale auth key、SOPS age 鍵の実値を AI / runner / artifact / log に出さない。

6. **AgentRun 16 状態 + blocked サブ 3**
   - AgentRun status は P0 で次の 16 状態に固定する: `queued`, `gathering_context`, `running`, `generated_artifact`, `schema_validated`, `policy_linted`, `diff_ready`, `waiting_approval`, `blocked`, `provider_refused`, `provider_incomplete`, `validation_failed`, `repair_exhausted`, `completed`, `failed`, `cancelled`。
   - `blocked` は単一 status であり、サブカテゴリは `blocked_reason` で表現する: `policy_blocked`, `budget_blocked`, `runtime_blocked`。
   - terminal state は `completed`, `failed`, `cancelled`, `provider_refused`, `repair_exhausted`。
   - `blocked` と `provider_incomplete` は terminal ではない。policy 更新、approval、budget 調整、resume、retry の余地を残す。
   - 状態は snapshot ではなく AgentRunEvent から説明可能でなければならない。

7. **用語不変条件**
   - `payload_data_class`: 送信 payload / artifact のデータ分類。ProviderAdapter 入口で必須。
   - `allowed_data_class`: Provider Compliance Matrix から解決する最大許可分類。caller 入力として受け取らない。
   - `tool_mutating_gateway_stub`: P0 の MCP / 外部 tool 書込系 deny-only gateway。Sprint 4.5 の read-only tool 境界。
   - `runner_mutation_gateway`: Runner sandbox 内で policy / approval / forbidden path / command gate を通過した patch だけを適用する経路。Sprint 7 の runner 境界。
   - `tool_mutating_gateway_stub` と `runner_mutation_gateway` を混同しない。
   - data class ordinal は常に `public < internal < confidential < pii`。

8. **ContextSnapshot 必須 10 カラム** (PRD-01 F-009 / DD-03 / DD-02)
   AgentRun の再現性 contract として、ContextSnapshot は次の 10 カラムを必ず持つ:
   1. `prompt_pack_version`
   2. `prompt_pack_lock`
   3. `policy_version`
   4. `policy_pack_lock`
   5. `repo_state` (commit SHA / branch / dirty flag / diff hash)
   6. `tool_manifest` (tool registry version + tool allowlist hash)
   7. `evidence_set_hash` (NFC UTF-8 + JCS canonical JSON + claim_id/source_id 昇順 + URL 正規化 + PROV bundle hash)
   8. `provider_continuation_ref` (`{provider, kind, artifact_ref, sha256, expires_at, exportable=false}`、本体は短期 artifact、監査 export から除外)
   9. `provider_request_fingerprint` (model_resolved / api_version / sdk_version / temperature / safety_settings 等)
   10. `snapshot_kind` (input / pre_tool / post_tool / resume / final)
   secret 値や export 不可の provider state を監査 export に露出しない (`exportable=false`)。

### Hard Gates 7 / Quality KPIs 5

Hard Gates は 1 件でも未達なら P0 承認不可です。

- `policy_block_recall`
- `secret_canary_no_leak`
- `tenant_isolation_negative_pass`
- `backup_restore_rpo_rto`
- `forbidden_path_block`
- `dangerous_command_block`
- `prompt_injection_resist`

Quality KPIs は改善対象であり、未達 1 個以下なら P0 承認可、2 個以上なら改善 Sprint を追加します。

- `acceptance_pass_rate`
- `time_to_merge`
- `approval_wait_ms`
- `citation_coverage`
- `cost_per_completed_task`

## 3. 技術スタック

- Python: FastAPI、Pydantic、arq、pytest、ruff / mypy / pyright 相当の型・品質確認
- TypeScript: Next.js、React、Zod、Vitest / Playwright、pnpm
- Database / Queue: PostgreSQL、Redis
- Runtime: Docker Compose、Docker isolated runner
- Network: Tailscale Serve / SSH、device approval、deny-by-default grants、`tag:taskhub-ci`
- Repo / CI: GitHub App、RepoProxy、Draft PR flow、private staging CI/E2E
- AI: OpenAI / Anthropic / Gemini / Mock Provider Adapter、Structured Outputs、Provider Compliance Matrix
- Secrets: SOPS + age、SecretBroker、`secret_ref`、capability token
- Observability: structured logs、correlation id、OTel / Prometheus / Loki / Grafana は Sprint 11.5 で本格化

## 4. ディレクトリ構造

主要な設計・実装パスだけを示します。存在しないパスは Phase 2 以降で作成される予定のハーネス / 実装パスです。

```text
docs/
  要件定義/
  基本設計/
  実装計画/
  sprints/
  adr/
  設計検討/

.claude/
  CLAUDE.md
  rules/
  agents/
  hooks/
  skills/
  reference/
  scripts/
  local/

.codex/
  config.toml
  hooks.json
  agents/

backend/
frontend/
config/provider_compliance.toml
migrations/
eval/
```

## 5. 重要パス参照

常時判断の正本は `rules/`、必要時参照は `reference/` に分けます。

- `.claude/rules/*.md`
  - 常時ロードされる行動制約。AI 出力境界、Sprint Pack / ADR Gate、Provider Compliance、SecretBroker、AgentRun、code search、testing、plan review、**Codex output contract** をここに置く。
  - 実装・レビュー・外部エージェント出力の採否判定では rules を優先する。
  - 主要 rules:
    - `codex-output-contract.md`: Codex 出力 truncation 防止 (200 KB 上限 / 分割 output mode / Claude 側 fallback / prompt template への必須文言)。全 Codex 連携 skill で適用。

- `.claude/reference/*.md`
  - ad-hoc 参照。ハーネス一覧、agent routing、audit ownership、dev commands、directory structure、Provider Compliance Matrix、Hard Gates / KPIs、SecretBroker contract、AgentRun state machine、ADR Gate Criteria、**MCP DB tools** を置く。
  - 常時ロードしない。該当作業時に必要なファイルだけ読む。
  - 主要 reference:
    - `mcp-db-tools.md`: PostgreSQL MCP (採用) / Prisma MCP (TaskManagedAI では使わない、SQLAlchemy + Alembic 採用) の使い分け、適切な使用タイミング、Codex / Claude Code 共通 wrapper の起動確認手順。

- `.claude/skills/`
  - Claude 側 skill。`dev-suite`, `quality-suite`, `review-suite`, `security-suite`, `release-suite` と TaskManagedAI 固有 skill を置く。
  - `skills.catalog.json` を採用する場合は catalog を機械可読な正本とし、SKILL.md frontmatter と同期する。

- `.claude/agents/`
  - Claude subagent。汎用 reviewer と TaskManagedAI 固有 reviewer を置く。
  - subagent 内から別 subagent / Codex skill を再帰起動しない。必要ならメイン会話に戻して orchestration する。

- `.claude/hooks/`
  - Claude hook。Phase 1 では skeleton だけ、Phase 4 で P0 Hard Gates に直結する最小 hooks から追加する。
  - hooks を増やす場合は noise、rate limit、誤発火、rollback を Sprint Pack に書く。

- `.codex/`
  - Codex 側 mirror。Claude 専用 env や AskUserQuestion 記法をそのまま移植しない。
  - `.codex/agents/*.toml` は Claude-only field の残留を手動確認する。

## 6. 作業ルール

1. **実装前に Sprint Pack を確認する**
   - 新規実装、計画変更、スコープ変更、risk / defer 判断の前に `docs/sprints/` を確認する。
   - Sprint Pack がない場合は、実装前に light / heavy のどちらが必要か判断する。
   - ADR Gate Criteria に該当する場合は heavy Pack と ADR を先に用意する。

2. **ADR Gate 該当時は ADR 必須**
   - 認証、DB schema、API 契約、AI 権限、MCP / tool 権限、Secrets、外部公開、破壊的操作、広範囲リファクタ、Provider、GitHub App permission は ADR なしに進めない。
   - ADR は背景、選択肢、採用案、却下案、リスク、rollback を含める。
   - 緊急修正で実装を先行した場合も 24h 以内に retro Pack / ADR を作成する。

3. **高リスク変更前に AskUserQuestion で確認する**
   - Claude では AskUserQuestion を使い、前提、選択肢、推奨案、影響、確認したい決定事項を具体化する。
   - Codex では通常のユーザー確認へ読み替える。
   - 高リスク領域では、diff 方針、影響範囲、rollback、検証方法を明示してから着手する。

4. **外部エージェント出力は採否判定する**
   - Codex、Claude、外部エージェント、AI reviewer の出力は鵜呑みにしない。
   - `adopt` / `reject` / `defer` を明示し、採用した変更だけ実装へ反映する。
   - 採用理由と未採用理由は Sprint Review または作業報告に残す。

5. **検証は該当範囲で実行する**
   - Backend: pytest、ruff、mypy / pyright、migration check、contract test、state machine test。
   - Frontend: typecheck、lint、Vitest、Playwright、主要 UI flow / responsive check。
   - DB: migration dry-run、constraint / FK / negative test、tenant boundary test。
   - Provider: provider contract test、Compliance Matrix test、`payload_data_class` / `allowed_data_class` 越境 test。
   - Runner / Tool: forbidden path、dangerous command、resource cap、tool mutating deny test。
   - 未整備の場合は代替確認を実行し、未確認事項を明示する。

6. **秘密情報と外部公開を守る**
   - 実 token、API key、age private key、Tailscale auth key、GitHub private key をドキュメントやログに書かない。
   - `.mcp.json` や `.worktreeinclude` に secret 実値を書かない。
   - Tailscale Funnel、Cloudflare、公衆向け bind、GitHub App permission 変更は ADR Gate 対象。

7. **Git 操作は慎重に行う**
   - commit / push / destructive git 操作はユーザー明示指示がある場合のみ実行する。
   - `git add -A` / `git add .` は禁止。必要なファイルを明示する。
   - main / master への直接コミットは避け、ブランチは `codex/` prefix を基本にする。

## 6.5. 開発 workflow と役割分担 (Sprint 1 以降の永続的基盤)

> **Phase A 圧縮 (2026-05-17、PR #42 stage 1)**: 本 § は最低限の summary + link、詳細は各 rules/ 正本に統合済 (重複削除 -約 580 行)。drift 防止のため本 § で重複を維持しない。

### 絶対教訓 (2026-05-13 ユーザー明示、永続保持)

> 「急がなくていい。それぞれ品質重視で codex をしっかり使い完璧にお願いします。時間よりも品質です。」

このプロジェクトの **絶対教訓**。Sprint 進行 / batch 完了 / review round 数において **速度を品質の上に置いてはならない**。具体運用は `.claude/rules/codex-usage-policy.md` + `.claude/reference/codex-multi-round-workflow.md` 参照。

### §6.5 各 subsection の正本 link

| 旧 § | 内容 | 正本 |
|---|---|---|
| §6.5.0 Codex-first ポリシー | Codex (gpt-5.5 + xhigh) を第一実装エンジンとし、Claude を orchestrator + 微修正 + 採否判定 + 品質ゲートに専念。token/cost 最適化、品質向上、CRITICAL invariant 直結変更は Codex review 経由必須、3 連続失敗保護、採否判定 3 分類 (adopt/reject/defer)、`workspace-write` 承認条件 | → `.claude/rules/codex-usage-policy.md` (全体) |
| §6.5.1 役割分担 | Codex = 主実装、Claude = orchestration + 採否判定 + 品質 gate + Sprint Exit 判定 | → `.claude/rules/codex-usage-policy.md` §1 |
| §6.5.2 Sprint 内標準 workflow (8 step) | Sprint Pack 確認 → 計画 review → 実装 batch 分割 → Codex 実装 → コード review → 品質チェック → セキュリティチェック → Sprint Exit 判定 | → `.claude/skills/dev-suite/SKILL.md` |
| §6.5.3 Host-Portable deployment | Mac/Linux/VPS のいずれか 1 箇所をメイン基盤として選択可。Network boundary (Tailscale 閉域、host publish は 127.0.0.1 bind 固定)、deny-by-default Funnel/Cloudflare Tunnel、SOPS+age secrets、Docker Compose 4 service | → ADR-00021 + DD-05 + DD-06 |
| §6.5.4 Codex multi-round review + codex-all-loops 3 phase pattern | review-loop → impl-loop → adversarial-loop の chain で R{N} clean 達成 (CRITICAL=0 / HIGH≤2)、CRITICAL invariant 直結 code は mode=code (3 phase)、heavy plan/ADR は mode=plan (2 phase)、doc-only future spec は PR Codex auto-review + 軽い polish | → `.claude/reference/codex-multi-round-workflow.md` (Phase C で rules → reference 移送済) + `.claude/reference/codex-output-contract.md` + `.claude/rules/codex-usage-policy.md` |
| §6.5.5 Skill 起動 priority | dev-suite (Sprint pipeline) / quality-suite (品質) / review-suite (PR 前) / security-suite (Hard Gates) / release-suite (Sprint Exit) + codex-task / codex-plan-review / codex-adversarial-review / codex-rescue | → `.claude/rules/codex-usage-policy.md` §2 |
| §6.5.6 ADR Gate accepted 化タイミング | 実装着手直前に proposed → accepted 昇格、retro Pack/ADR 24h 以内、break-glass 例外運用条件 | → `.claude/rules/sprint-pack-adr-gate.md` §6-10 |
| §6.5.7 Worktree 利用 (TaskManagedAI 固有事情) | `bash scripts/worktree_setup.sh` で setup 自動化 (pnpm install + uv sync + SOPS 復号、約 10 分)、`.worktreeinclude` で gitignored 個人設定を worktree に copy。並列 bg job scope 分割 (backend / frontend / docs / read-only)、同 branch 2 worktree checkout 時の取り込み手順 | 判断フロー本体: → `~/.claude/CLAUDE.md` Git Worktree 利用判断ルール / 詳細: → `docs/設計検討/bg-job-worktree-workflow.md` |
| §6.5.8 PR 起票・merge 責務分離 | Claude が PR 起票 + Codex review 採否判定 + fix push、user が PR merge 直接 (Claude classifier reject 経路、`gh api -X PUT pulls/N/merge` API 経路は user 明示指示時)、user 手元作業の代理処理 path | → `.claude/skills/branch-pr-workflow/SKILL.md` (Phase D で L3-auto skill 化、`disable-model-invocation: false`、PR 起票 / worktree 操作で auto invoke) + `.claude/rules/branch-and-pr-workflow.md` (Phase D 圧縮 30 行 L1 reminder、1 週間移行期間後削除予定) |
| §6.5.9 Codex auto-review 確認義務 | `.claude/scripts/codex_pr_full_review.sh` で `pulls/N/comments` (inline) + `issues/N/comments` (conversation) + `reviews` (top-level) 3 endpoint × paginated × Codex bot filter 全件取得必須。**baseline 内容確認必須** (delta +0 を真の 0 件と誤判定しない、PR #42/#44 で再発) | → `.claude/scripts/codex_pr_full_review.README.md` (Phase C で rules → scripts/ 移送済) + `.claude/scripts/codex_pr_full_review.sh` |

詳細は各正本を参照。本 § で重複を維持しない (drift 防止、F-CRA-NNN findings 由来)。

## 7. Codex 連携

Claude 側から Codex を使う場合は、Claude 側 Skill 経由で以下を起動します。

- `codex-task`
- `codex-second-opinion`
- `codex-plan-review`
- `codex-adversarial-review`
- `codex-rescue`

運用ルール:

- Codex chain の並列起動は禁止。1 つの Codex 連携が完了し、採否判定してから次に進む。
- 3 連続失敗、rate limit、schema invalid、空応答、100 bytes 未満の実質無効応答では自動停止し、AskUserQuestion で継続可否を確認する。
- Codex 出力は `adopt` / `reject` / `defer` で採否判定する。採用前に TaskManagedAI rules と対象 docs に照らす。
- Claude 専用の hook / env / Skill 記法を Codex 側へそのまま移植しない。Codex では `.codex/config.toml`, `.codex/hooks.json`, `.codex/agents/*.toml` の実行可能性を別途確認する。
- Codex が実行主体のときは Codex 自身をさらに呼び出す chain を作らず、同等の観点を通常レビューとして扱う。

## 8. 既存資料への参照

実装前に関連資料を確認してください。すべてを丸読みせず、作業範囲に応じて必要な章を読む方針です。

- `AGENTS.md`
  - Codex 用プロジェクト方針。Claude 側でもプロジェクト判断の補助として参照する。
- `docs/設計検討/harness-phase0-mapping.md`
  - **本ハーネスの正本マッピング**。Phase 0 提案で、既存プロジェクト参照ファイルに対する 4 分類 (直接踏襲 / カスタム化 / 新設 / 除外) と TaskManagedAI 専用の新設 rules / agents / hooks / skills / reference の具体名 (§3.1〜3.5) を持つ。Phase 2 以降で作成される `.claude/rules/*.md` / `.claude/reference/*.md` / `.claude/agents/*` / `.claude/hooks/*` / `.claude/skills/*` の根拠は本文書を参照する。
- `docs/設計検討/harness-residual-risks.md`
  - ハーネス整備 (Phase 4 hooks / Phase 5 skills) で意図的に defer した残リスクの正本。
    - Phase 4 hooks の **CRITICAL 2 件 (`PH4-F-001` dispatcher 自己改ざん耐性 / `PH4-F-002` snapshot state 改ざん耐性)** を Sprint 7 の `repo 外 trusted wrapper` 設計まで defer。P0 容認条件と ADR-00012 (Hook Trust Boundary) の対応方針を含む。**Phase namespace prefix で PRD feature ID (F-NNN) と区別する**。
    - Phase 5 skills の **LOW 1 件 (`PH5-F-004`: Suite 5 件で DRY_RUN / 採否判定 / 逐次実行の orchestration boilerplate 整合)** を Sprint 0-1 の運用試験フィードバック後に標準化。
  - Bash tool 経由の hook 改ざん攻撃や Suite skill 標準化に関わる作業時に参照する。
  - 主な新設 rules: `ai-output-boundary.md`, `sprint-pack-adr-gate.md`, `provider-compliance.md`, `agentrun-state-machine.md`, `secretbroker-boundary.md`
  - 主な新設 agents: `sprint-pack-reviewer`, `provider-compliance-reviewer`, `actor-binding-reviewer`, `hard-gate-fixture-reviewer`, `agentrun-state-reviewer`, `tenant-project-isolation-reviewer`, `postgres-specialist`, `runner-security-reviewer`
  - 主な新設 hooks: `tailscale/check-tailscale-grants.sh`, `secretbroker/check-secretbroker-ddl.sh`, `agentrun/check-state-enum.sh`, `provider/check-payload-data-class.sh`, `sprint/check-sprint-pack-frontmatter.sh`, `adr/check-adr-gate.sh`, `runner/check-dangerous-command-fixture.sh`, `postgres/check-tenant-boundary-ddl.sh`
  - 主な新設 skills: `sprint-pack-create`, `adr-create`, `hard-gate-fixture-create`, `atomic-claim-validator`, `provider-compliance-audit`, `agentrun-state-machine-test`, `runner-gateway-audit`, `postgres-boundary-audit`
  - 主な新設 reference (実装対応):
    - `provider-compliance-matrix.md` (実装済 / そのまま)
    - `hard-gates-and-kpis.md` (実装済 / そのまま)
    - `secretbroker-contract.md` (実装済 / そのまま)
    - `taskmanagedai-stack.md` → 実装は `dev-commands.md` + `directory-structure.md` に分散統合
    - `agentrun-state-machine.md` (reference) → 内容は `rules/agentrun-state-machine.md` に統合 (rules 側が常時ロードされる正本のため。reference 側は必要なら `db-schema-notes.md` §6-8 を参照)
    - `adr-gate-criteria.md` → 内容は `rules/sprint-pack-adr-gate.md` §4 + `reference/audit-ownership-matrix.md` §4 に統合 (Gate Criteria は ADR 必須判定として常時参照されるため rules 側に置く)
    - 追加で `skill-lint-banned-terms.md` (Phase 5 で追加された禁止語レジストリ。`harness-inventory.md` の inventory にも追加済)
- `docs/設計検討/計画(仮).md`
  - v2 計画書。P0 Scope Decision、Hard Gates、Quality KPIs、Sprint 方針、Provider / Secret / Network の前提を確認する。
- `docs/要件定義/00_プロダクト要求定義.md`
  - PRD-00。プロダクト vision、P0 到達点、安全な AI 実行の原則、成功指標を確認する。
- `docs/要件定義/01_P0要求定義.md`
  - PRD-01。P0 scope、機能要求、Acceptance Criteria、Provider Compliance Matrix 依存を確認する。
- `docs/基本設計/00_全体アーキテクチャ.md`
  - DD-00。FastAPI / Next.js / PostgreSQL / Redis / Tailscale / SecretBroker / ProviderAdapter の全体境界を確認する。
- `docs/基本設計/04_セキュリティ_権限_監査設計.md`
  - DD-04。Provider Compliance、Hard Gates、OWASP / NIST、policy / approval / audit 境界を確認する。
- `docs/基本設計/05_ネットワーク境界設計.md`
  - DD-05。Tailscale Serve、Funnel 不使用、`tag:taskhub-ci`、private staging の grants 方針を確認する。
- `docs/基本設計/06_秘密管理設計.md`
  - DD-06。SOPS + age、SecretBroker、atomic claim、secret inventory、canary、rotation を確認する。
- `docs/実装計画/`
  - Roadmap、P0 backlog、Sprint 実装順序、must_ship / defer_if_over_budget を確認する。
- `docs/sprints/`
  - Sprint Pack templates と各 Sprint Pack。
- `docs/adr/`
  - ADR template と採用済み / proposed ADR。

