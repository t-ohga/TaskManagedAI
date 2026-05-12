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

本プロジェクトでは **Codex を主実装者、Claude を orchestration / 品質評価者** として運用する。本 section は Sprint 1 以降の全実装で適用される永続的 workflow である。

### 6.5.1 役割分担

| 役割 | 担当 | 範囲 |
|---|---|---|
| **実装** | Codex (`codex-task` skill 経由) | コード生成、migration、test 実装、subprocess 操作、refactor |
| **orchestration** | Claude main agent | Sprint Pack 読み込み、Codex prompt 作成、batch 分割、進捗管理、ユーザー確認 |
| **計画レビュー** | Claude (`codex-plan-review` skill / `plan-reviewer` agent) | 実装前計画の Sprint Pack DoD 確認、ADR Gate 判定、rollback 確認 |
| **コードレビュー** | Claude (`review-suite` skill / `code-reviewer` agent) | Codex 出力の `adopt` / `reject` / `defer` 判定、TaskManagedAI 不変条件 trace |
| **品質チェック** | Claude (`quality-suite` skill) | typecheck、lint、test coverage、weak assertion 検出 |
| **セキュリティチェック** | Claude (`security-suite` skill) | Hard Gates 7 / OWASP / Provider Compliance / SecretBroker / Runner |
| **敵対レビュー** | Claude (`codex-adversarial-review` skill) | 重要マイルストーン (Sprint Exit / 高リスク変更 / 残リスク確認) |
| **救援** | Claude (`codex-rescue` skill) | Codex / Claude が 2 回以上失敗した時の問題切り分け |
| **Sprint Exit 判定** | Claude (`release-suite` skill / `release-auditor` agent) | Sprint Review 章生成、Hard Gates / Quality KPIs 集計、defer 移送 |

### 6.5.2 Sprint 内の標準 workflow (8 step)

```text
Step 0: Sprint Pack 確認 (Claude)
  - docs/sprints/SP-NNN_*.md を読み、must_ship / defer / 受け入れ条件 / 検証手順を把握
  - ADR Gate Criteria 該当確認、`planned_adr_refs` で proposed ADR を accepted 化する gate を事前判定
  - 関連 rules / reference / agents を Claude が orchestration 用に整理

Step 1: 計画レビュー (Claude `plan-reviewer` agent + `codex-plan-review` skill)
  - Sprint Pack の light / heavy 区分、frontmatter 完全性、must_ship / defer / rollback / 検証手順
  - 高リスク領域は AskUserQuestion で前提確認

Step 2: 実装 batch 分割 (Claude main agent)
  - Sprint 内のチケット (BL-NNNN) を Codex 1 batch あたり 5-10 ファイル / 1500-3000 行 に分割
  - 各 batch の依存順序を決定 (BL ID + depends_on)

Step 3: Codex 実装 (Codex `codex-task` skill、Claude が prompt 作成)
  - prompt は Sprint Pack / ADR / rules / reference を必読資料として明示
  - 出力形式は `===FILE: <path>===` 区切り
  - sandbox = `read-only` (Codex は repo を直接編集せず、Claude が write back する)

Step 4: コードレビュー (Claude `code-reviewer` agent + `review-suite` skill)
  - Codex 出力の `adopt` / `reject` / `defer` 判定
  - TaskManagedAI 不変条件 trace (AgentRun 16 状態 / Provider Compliance / SecretBroker / tenant boundary 等)
  - 1 batch あたり 3-5 round の review loop が標準

Step 5: 品質チェック (Claude `quality-suite` skill)
  - `pnpm typecheck` / `pnpm lint` / `pnpm test` (frontend)
  - `uv run ruff check` / `uv run mypy` / `uv run pytest` (backend)
  - `uv run alembic check` (migration)
  - 弱い assertion / dead code / type safety を skill で検出

Step 6: セキュリティチェック (Claude `security-suite` skill)
  - Hard Gates 7 / Quality KPIs 5 への trace
  - Provider Compliance / SecretBroker / Runner / forbidden path / dangerous command / prompt injection の関連 fixture 確認
  - 必要時 `codex-adversarial-review` skill で敵対レビュー

Step 7: Sprint Exit 判定 (Claude `release-auditor` agent + `release-suite` skill)
  - Sprint Pack `## Review` section に `changed` / `verified` / `deferred` / `risks` を追記
  - must_ship 達成確認、defer_if_over_budget の対応表更新
  - VPS deploy smoke (Sprint 1 以降は VPS 起動確認を Sprint Exit に含める、§6.5.3 参照)
```

### 6.5.3 Host-Portable deployment 前提 (Sprint 1 以降の全実装で考慮、ADR-00021 で正式化)

**ADR-00021 (Host-Portable Deployment + Data Migration、2026-05-10 起票)** により、TaskManagedAI backend は **Mac / Linux / VPS のいずれか 1 箇所** をメイン基盤として選択可能 (旧 VPS 固定前提から拡張).

| 運用フェーズ | 推奨 host | 理由 |
|---|---|---|
| 開発初期 (Sprint 1-N) | **Mac (`t-ohga-mac`)** | docker-compose をそのまま起動、修正サイクル早い、他端末から Tailscale 経由でアクセス可 |
| 開発中盤〜後半 | Mac か Linux 24/7 機 | sleep 制御 + SOP 整備で安定稼働、本番想定の検証 |
| 運用フェーズ (P0.1+) | **VPS (`t-ohga-vps`、Hostinger)** | 24/7 安定、専用環境、出先可用性 |
| host 切替時 | `taskhub migrate --target <host>` | data + secret 込みで自動移行 (ADR-00021 §3) |

最終的な実行環境候補は **Hostinger VPS (`t-ohga-vps`、Tailscale 内 IP `100.115.27.116`)** だが、Sprint 1 では **Mac で起動して動作確認**、Sprint 12 で **host migration drill** を実施して VPS 移行を verify する流れとする (AC-HARD-04 拡張).

Sprint 1 以降のすべての実装で以下を前提にする:

- **Network boundary** (DD-05 / ADR-00007 準拠):
  - VPS は Tailscale 閉域のみ public ingress なし (`tag:taskhub` -> TCP/443、`tag:taskhub-ci` -> TCP/443 の 2 系統のみ)
  - host publish の bind は `127.0.0.1` に固定する。例: `docker-compose.yml` の ports は `"127.0.0.1:8000:8000"` / `"127.0.0.1:3000:3000"` / `"127.0.0.1:5432:5432"` / `"127.0.0.1:6379:6379"`
  - container process bind は Docker internal network 経由でのみ到達させる。container 内の `0.0.0.0` listen (例: uvicorn `--host 0.0.0.0`、Next.js `--hostname 0.0.0.0`) は Docker bridge 経由通信のためにのみ許容し、ホスト到達は host publish mapping を経由する
  - public IP からの 22/tcp / 80/tcp / 443/tcp は UFW で deny (Tailscale 経由のみ)
  - Tailscale Funnel / Cloudflare Tunnel は ADR Gate Criteria #7 該当、P0 では deny
  - device approval は必須有効 (未承認 device は到達不可)
- **Runtime stack**:
  - Docker Compose (single-VPS、`api` / `worker` / `postgres` / `redis` の 4 service)
  - Sprint 1: minimum compose で起動可能、Sprint 2 以降で migration / actor / SecretBroker schema を追加
  - Sprint 7 で Docker isolated runner、`runner_mutation_gateway`、forbidden path / dangerous command を完成
- **Secrets**:
  - Sprint 0-3: `.env.local` (gitignore) を dev / staging で許容、production VPS には SOPS + age を Sprint 4 で本実装
  - SOPS age key は VPS にのみ保管 (developer machine からは Tailscale SSH で deploy script 実行)
  - VPS の secrets path: `~/.taskmanagedai-secrets/` (root 600 / age key は別 path)
- **Deploy flow**:
  - Sprint 1: 手動 `docker compose up -d` (Tailscale SSH 経由で VPS に接続)
  - Sprint 8: GitHub Draft PR + RepoProxy + private staging CI/E2E (Tailscale GitHub Action)
  - Sprint 11.5: secret rotation drill / structured logs / Loki / Grafana
  - Sprint 12: P0 Acceptance + backup/restore drill (RPO ≤24h / RTO ≤4h)
- **Health check / observability**:
  - Sprint 1: 各 service に `/healthz` endpoint、docker-compose healthcheck
  - Sprint 11.5: OTel + Prometheus + Loki + Grafana

### 6.5.4 Codex multi-round review が標準

Phase 0-8 で確立した「Codex multi-round review で clean 達成」の workflow を Sprint 1 以降も継続する。

- **1 round**: Codex に実装 / 修正を投げる
- **2 round以降**: Codex に adversarial review (`finding-schema.json` 形式) を投げ、findings を Claude が `adopt` / `reject` / `defer` 判定して fix
- **clean 判定**: review round で `findings: []` が出るまでループ
- **3 連続失敗 / rate limit / 100 bytes 未満応答**: 自動停止し AskUserQuestion で継続可否確認
- **CRITICAL / HIGH defer**: `harness-residual-risks.md` の PH<N>-F-NNN 形式で記録、対応 Sprint を明記

### 6.5.5 Skill 起動 priority (Sprint 内の判断)

各 step で Skill を直接起動する場合の優先順位:

| 状況 | 優先 Skill |
|---|---|
| Sprint 着手 | `dev-suite` (orchestration の 6 step pipeline) |
| 計画 review | `codex-plan-review` (user global) |
| Codex 実装 | `codex-task` (user global) |
| code review | `review-suite` (TaskManagedAI 用、Sprint Pack / ADR / 不変条件 trace) |
| 品質チェック | `quality-suite` (typecheck / lint / test / coverage / state machine contract) |
| セキュリティチェック | `security-suite` (Hard Gates / OWASP / Provider / Secret / Runner) |
| Sprint Exit | `release-suite` (Sprint Review 章 + KPI / Hard Gate 集計 + defer 移送) |
| 敵対レビュー (高リスク) | `codex-adversarial-review` (user global) |
| 救援 (2 回失敗) | `codex-rescue` (user global) |

Suite は Main Agent orchestration として動き、内部から Skill / Agent を直接起動しない。Claude main agent が順次呼ぶ。

### 6.5.6 ADR Gate accepted 化のタイミング

各 Sprint の `adr_refs` に列挙された ADR は **実装着手の直前に proposed → accepted** に昇格する。

- **昇格手順**: ADR の `status: "proposed"` → `accepted` に変更、`updated_at` を当日に更新
- **昇格条件**: Sprint Pack の `must_ship` 受け入れ条件と矛盾しない、関連 rules / reference / DD と整合、`planned_adr_refs` の対象なら `adr_refs` に移動
- **failed-fast**: ADR と実装が drift した場合、ADR を update してから実装を再開する
- **breakdown**: 1 ADR が 1 Sprint 内で proposed → accepted を跨ぐ場合は Sprint Pack `## Review` に accepted 化日を記録

### 6.5.7 Worktree 利用 (TaskManagedAI 固有事情、2026-05-12 追記)

判断フロー / 使う・使わない判断軸 / main 作業時の注意は **user-global `~/.claude/CLAUDE.md` §「Git Worktree 利用判断ルール（全プロジェクトで厳守、bg job 含む）」を正本** として参照する。本節では TaskManagedAI 固有事情のみ記録する。

- **setup script**: worktree を「使う」と判断 + code (backend / frontend) を触る場合、`bash scripts/worktree_setup.sh` で setup 自動化 (pnpm install + uv sync + SOPS 復号、約 10 分)。doc-only 作業なら skip 可。
- **`.worktreeinclude`**: gitignored 個人設定 (`settings.local.json` / SOPS 設定 / age key pointer) を worktree に自動 copy。**DD-06 SecretBroker 原則準拠で `.env.local` は意図的に copy 禁止**、各 worktree で SOPS 経由 (setup script 内) で生成。
- **並列 bg job の scope 分割**: backend (`backend/` + `tests/` + `migrations/`) / frontend (`frontend/`) / docs (`docs/`) / read-only 調査 の 4 軸で job を分けると conflict ほぼゼロ。
- **共通 file** (`CLAUDE.md` / `AGENTS.md` / `README.md` / `.worktreeinclude`) を触る job は同時に 1 つに制限。
- **Codex 並列起動禁止** (`.claude/rules/codex-usage-policy.md`)。
- **同 branch を 2 worktree で checkout する場合**: worktree 側で push → 別 worktree (main / codex/... checkout 中) で `git fetch origin && git merge --ff-only origin/<branch>` で取り込む (2026-05-12 Phase A で実演済)。
- **詳細運用 doc**: `docs/設計検討/bg-job-worktree-workflow.md` + AI 用 memory `~/.claude/projects/-Users-tohga-repo-TaskManagedAI/memory/reference_fleetview_worktree_workflow.md`。

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

