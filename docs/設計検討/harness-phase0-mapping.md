# TaskManagedAI ハーネス設計マッピング (Phase 0 提案)

## 1. 全体方針

ieshima-edu のハーネスは「Next.js 16 + Supabase + 学習コンテンツ品質管理」に強く最適化されている。一方、TaskManagedAI は「AI 出力を artifact 化し、Sprint Pack / ADR / policy / approval / runner / provider compliance / audit で安全に実行する」ことが中核である。したがって、コピー中心ではなく、**構造は踏襲し、ドメイン不変条件は TaskManagedAI 用に全面差し替え**る。

Phase 0 の結論:

- `.claude/CLAUDE.md` / `AGENTS.md` / `rules/` / `reference/` の分離方針は踏襲する。
- `hooks/` は ieshima の 69 `.sh` をそのまま増殖させず、最初は **P0 Hard Gates / SecretBroker / Provider Compliance / Sprint Pack / ADR Gate** に絞る。
- `agents/` は ieshima の 16 体制を「汎用レビュー 5 + TaskManagedAI 固有 6-8」に再編する。
- `skills/` は ieshima の suite 構造を踏襲し、`dev-suite` / `quality-suite` / `review-suite` / `security-suite` / `release-suite` を TaskManagedAI 版に作り直す。
- Supabase、学習コンテンツ、タイピング画像、PWA、Vercel、shadcn 固有要素は原則除外する。
- PostgreSQL、FastAPI、arq、Docker Compose、Tailscale、GitHub App、Provider Adapter、SecretBroker、AgentRun 状態機械を新しい正本にする。
- TaskManagedAI の既存 `AGENTS.md` は保持し、`.claude/CLAUDE.md` と `.codex/` を追加する形が安全。

参照根拠:

- ieshima: `.claude/CLAUDE.md`, `.claude/settings.json`, `.claude/hooks/README.md`, `.claude/reference/harness-inventory.md`, `.claude/reference/audit-ownership-matrix.md`, `.codex/migrate-to-codex-report.txt`
- TaskManagedAI: `AGENTS.md`, `docs/要件定義/00_プロダクト要求定義.md`, `docs/要件定義/01_P0要求定義.md`, `docs/基本設計/04_セキュリティ_権限_監査設計.md`, `docs/sprints/_template_light.md`, `docs/sprints/_template_heavy.md`, `docs/adr/_template.md`

## 2. ファイル別マッピング

分類は次の 4 種とする。

| 分類 | 意味 |
|------|------|
| **直接踏襲** | ファイル構造またはスクリプトをほぼコピー可能。パスだけ TaskManagedAI に変更する。 |
| **カスタム化** | ieshima の構造を参考に、本文・対象パス・検査条件を TaskManagedAI 用に書き換える。 |
| **新設** | ieshima には対応物がない。TaskManagedAI 固有 gate / invariant のため追加する。 |
| **除外** | ieshima 固有で TaskManagedAI には不要。 |

### 2.1 settings / 設定系

| ieshima ファイル | 分類 | 理由 / TaskManagedAI 側のファイル名 |
|------|------|------|
| `.claude/CLAUDE.md` | カスタム化 | ワークフロー骨格は踏襲。TaskManagedAI では Sprint Pack、ADR Gate、Provider Compliance、SecretBroker、AgentRun、Tailscale 閉域を正本にする。出力先: `.claude/CLAUDE.md` |
| `.claude/settings.json` | カスタム化 | ieshima は hooks だけを登録し、permissions は local 側。TaskManagedAI では hooks を最小登録し、Claude 固有 `$CLAUDE_PROJECT_DIR` は避ける。 |
| `.claude/settings.local.json` | 最小維持 | 個人許可設定。ieshima の allowlist には Supabase / Codex / dotfiles 作業が混在するためコピー禁止。TaskManagedAI は最小 allow から開始。 |
| `.codex/config.toml` | 既存維持 + 補強 | TaskManagedAI 既存は `xhigh`, `workspace-write`, `network_access=false`, `codex_hooks=true`。project MCP を追加する場合だけ補強。 |
| `.codex/hooks.json` | 新設 / カスタム化 | ieshima Codex hooks は `git add -A` ブロックのみ。TaskManagedAI でもまず同等を入れ、後段で sprint/adr/provider の軽量 hooks を追加。 |
| `.codex/migrate-to-codex-report.txt` | 除外 | 移行作業ログ。TaskManagedAI 側で移行実行した場合だけ生成。 |
| `.worktreeinclude` | カスタム化 | ieshima は `.env.local`, Notion, `.claude/settings.local.json`。TaskManagedAI は `.env.local`, `.env`, `.sops.yaml`, `age` key はコピー禁止寄りに再設計が必要。 |
| `.mcp.json` | カスタム化 | ieshima は `drawio`, `next-devtools`。TaskManagedAI は `drawio` は有用、`next-devtools` は Next UI 実装時のみ。GitHub / context7 は必要なら user/global 側で扱う。 |
| `AGENTS.md` | 既存維持 + 補強 | 既存の AI 出力直結禁止、確認方針、Tailscale/FastAPI/Next.js 前提は良い。`.claude/` と `.codex/` の読み替えルールを追補。 |
| `CLAUDE.md` root | カスタム化 | ieshima は最小常時ロード。TaskManagedAI でも root `CLAUDE.md` は短くし、詳細は `.claude/reference/` に逃がす。 |

### 2.2 rules

| ieshima ファイル | 分類 | TaskManagedAI 側 |
|------|------|------|
| `.claude/rules/core.md` | カスタム化 | 型安全、Zod、秘密情報非露出、AI 出力直結禁止、deny-by-default、PostgreSQL invariant、FastAPI boundary に置換。 |
| `.claude/rules/testing.md` | カスタム化 | 仕様ベーステスト、境界値、弱い assertion 禁止は踏襲。Vitest だけでなく pytest / contract test / state machine test を追加。 |
| `.claude/rules/rendering.md` | カスタム化 | Next.js UI があるため一部有用。ただし ieshima の海洋テーマ / Cache Components 固有強制は削る。 |
| `.claude/rules/plan-review.md` | カスタム化 | Sprint Pack、ADR Gate Criteria 11 種、Hard Gates 7、Quality KPIs 5、rollback / audit / provider matrix を計画レビュー必須項目にする。 |
| `.claude/rules/code-search.md` | 直接踏襲 + 軽微カスタム | LSP 優先、`rg` fallback、実コンパイラ確認は有用。Python では pyright / ruff / mypy / pytest を地上真実に追加。 |
| `.claude/rules/instincts.md` | カスタム化 | ieshima の過去事故集は Supabase/学習系が多い。TaskManagedAI では SecretBroker atomic claim、payload data class、AgentRun 遷移、Tailscale grants などの事故予防集として新規作成。 |
| `.claude/rules/codex-usage-policy.md` | カスタム化 | Claude から Codex を呼ぶ前提は弱める。TaskManagedAI では「AI/外部エージェント出力の採否判定」「rate limit 時の停止」「adopt/reject/defer」を残す。 |

新設 rules は 3 章に記載する。

### 2.3 agents

#### `.claude/agents/ieshima-edu/*.md`

| ieshima agent | 分類 | TaskManagedAI 側 |
|------|------|------|
| `code-reviewer.md` | カスタム化 | `code-reviewer.md` として再作成。Phase を TypeScript / Python / FastAPI / PostgreSQL / Redis / arq / Docker / provider / runner / audit に差し替え。 |
| `plan-reviewer.md` | カスタム化 | `plan-reviewer.md`。Sprint Pack / ADR Gate / Hard Gate trace / rollback / verification を主観点にする。 |
| `release-auditor.md` | カスタム化 | `release-auditor.md`。P0 Exit、Hard Gates 7、Quality KPIs 5、backup restore drill、private staging を見る。 |
| `security-specialist.md` | カスタム化 | `security-specialist.md`。Supabase Auth/RLS ではなく Policy Engine、Approval、SecretBroker、Provider Compliance、Tool/Runner gateway を見る。 |
| `supabase-specialist.md` | 除外 / 置換 | `postgres-specialist.md` または `db-invariant-reviewer.md` に置換。PostgreSQL DDL、tenant boundary、複合 FK、RLS 将来化を扱う。 |
| `tdd-orchestrator.md` | カスタム化 | Vitest + pytest + contract test + state machine test の TDD orchestration に変更。 |
| `explanation-*.md` 5 件 | 除外 | 土木過去問解説レビュー専用。TaskManagedAI には不要。 |
| `intro-quiz-*.md` 5 件 | 除外 | イントロクイズ / 画像生成 / 教材設計専用。TaskManagedAI には不要。 |

#### `.codex/agents/*.toml`

ieshima の `.codex/agents` 16 件は `.claude/agents` から機械変換された mirror であり、`migrate-to-codex-report.txt` では全件 `tools`, `color` の manual review required が出ている。TaskManagedAI でも **Claude agent を先に確定し、その後 Codex toml を生成・手動確認**する。

| Codex agent 群 | 分類 | TaskManagedAI 側 |
|------|------|------|
| `code-reviewer.toml`, `plan-reviewer.toml`, `release-auditor.toml`, `security-specialist.toml`, `tdd-orchestrator.toml` | カスタム化 | 同名または TaskManagedAI 名で生成。 |
| `supabase-specialist.toml` | 除外 / 置換 | `postgres-specialist.toml` に置換。 |
| `explanation-*`, `intro-quiz-*` toml | 除外 | 不要。 |

TaskManagedAI 専用 agent は 3.2 に記載する。

### 2.4 hooks

ieshima は `.claude/hooks/README.md` 上では全 `.sh` 69 件、lib 4 件、settings 登録 63-64 件規模。TaskManagedAI は最初から同数を移さず、**P0 の危険境界に効く hooks だけを先に入れる**。

| カテゴリ | ieshima ファイル | 分類 | TaskManagedAI 方針 |
|------|------|------|------|
| `lib` | `common.sh`, `emit-additional-context.sh`, `emit-hook-event-helper.sh`, `emit-system-message.sh` | 直接踏襲 | JSON emit / common helper は有用。パスと上限文字数だけ確認。 |
| `system` | `block-git-add-bulk.sh` | 直接踏襲 | `git add -A`, `git add .` 禁止は TaskManagedAI でも有用。Codex hook にも入れる。 |
| `system` | `emit-hook-event.sh`, `log-rules-loaded.sh`, `postcompact-log-only.sh`, `postcompact-reinject-instincts.sh`, `sessionstart-detect-worktree.sh`, `snapshot-before-compact.sh` | カスタム化 | session / compact / worktree は有用だが、書込先を TaskManagedAI 用に変更。 |
| `type-safety` | `detect-any-type.sh`, `detect-ts-suppress.sh` | カスタム化 | TS は踏襲。Python は `Any`, `type: ignore`, broad `dict[str, Any]` などを追加するか別 hook 新設。 |
| `quality` | `detect-console-residue.sh`, `detect-unformatted-generated.sh`, `check-tsconfig-baseline.sh` | カスタム化 | TS/Next に加え ruff/mypy/pyproject drift を見る。 |
| `quality` | `detect-csv-manual-build.sh` | 除外 | CSV 要件がない限り不要。 |
| `quality` | `detect-emoji-in-code.sh`, `detect-missing-ja-jp-locale.sh` | 除外 / 任意 | TaskManagedAI には ieshima の絵文字禁止・ja-JP 表示固定が正本化されていない。 |
| `quality` | `detect-legacy-segment-config.sh`, `detect-client-await-params.sh`, `detect-revalidate-tag-single-arg.sh`, `detect-unstable-cache.sh`, `detect-unnecessary-use-client.sh`, `check-page-metadata.sh`, `detect-setstate-updater-sideeffect.sh` | カスタム化 / 一部除外 | Next.js UI が固まってから採用。Cache Components 強制は現時点では保留。 |
| `security` | `detect-client-secret-leak.sh`, `detect-sensitive-console.sh`, `detect-missing-zod-validation.sh`, `detect-xss-raw-html.sh`, `detect-dynamic-href-xss.sh` | カスタム化 | Next/FastAPI 両方の secret / PII / payload leak / XSS / schema validation を見る。 |
| `security` | `detect-sa-missing-checks.sh`, `detect-get-verify-rpc.sh`, `detect-auth-users-direct-sql.sh`, `detect-authenticated-students-insert.sh`, `detect-error-boundary-external-import.sh` | 除外 / 置換 | Server Action / Supabase / 学生 auth 固有。FastAPI endpoint / actor binding / SQL migration hook に置換。 |
| `performance` | `detect-await-waterfall.sh`, `detect-heavy-lib-import.sh`, `detect-img-tag.sh`, `check-async-suspense.sh` | カスタム化 | Frontend には有用。Backend では N+1、blocking IO in async、arq job timeout を別 hook 新設。 |
| `a11y` | 5 件すべて | 直接踏襲 + 軽微カスタム | Next UI に有用。デザイン実装開始後に採用。 |
| `testing` | `detect-weak-assertions.sh`, `detect-weak-assertions-v2.sh` | カスタム化 | Vitest に加え pytest の weak assert / snapshot 過多 / state transition test 欠落を追加。 |
| `bash-diagnostics` | `diagnose-bash-failure.sh` | 直接踏襲 | Bash 失敗時の診断は有用。 |
| `file-changed` | `warn-external-migration-edit.sh` | カスタム化 | `config/provider_compliance.toml`, ADR, Sprint Pack, migrations, `.github/workflows`, Tailscale config 変更時に警告。 |
| `lsp-cache` | `warn-lsp-cache-bash.sh`, `warn-lsp-cache-tsconfig.sh` | カスタム化 | TS に加え `.venv`, pyright/mypy cache, generated OpenAPI types を扱う。 |
| `layout` | `check-flow-layout.sh` | 除外 / 後回し | ieshima UI 固有。TaskManagedAI UI の design system 確定後。 |
| `audio` | `check-audiocontext-running.sh` | 除外 | TaskManagedAI に不要。 |
| `supabase` | 15 件 | 原則除外 / PostgreSQL 部分だけ置換 | Supabase Auth/RLS/Realtime/Storage は不要。`check-fk-index`, `check-function-search-path`, `check-numeric-precision`, `check-jsonb-eq-without-coalesce` は PostgreSQL hook として再構成。 |

優先して新設する hooks は 3.3 に記載する。

### 2.5 skills

ieshima `.claude/skills` は 55 ディレクトリ、84 ファイル。TaskManagedAI では次のグループ単位で扱う。

| ieshima skill 群 | 対象 | 分類 | TaskManagedAI 方針 |
|------|------|------|------|
| Suite | `dev-suite`, `quality-suite`, `review-suite`, `security-suite`, `release-suite` | カスタム化 | suite 構造は踏襲。中身は Sprint Pack / FastAPI / Next / PostgreSQL / Provider / SecretBroker / Hard Gates に差し替え。 |
| Shim | `dev-story`, `quality-check`, `code-review`, `security-audit`, `release-check` | カスタム化 / 任意 | 旧名互換が必要なら TaskManagedAI でも shim を作る。初期は suite 直名だけでもよい。 |
| Quality | `quality-type-safety`, `quality-test-coverage`, `quality-perf-static`, `quality-dead-code`, `type-safety-baseline-audit` | カスタム化 | TS + Python + Docker + arq の品質 gate に拡張。 |
| Quality / Next | `quality-cache-components`, `testing-browser-mode` | 除外 / 後回し | Next 16 方針が固まるまで保留。UI 実装が始まったら再評価。 |
| Review | `review-type-safety`, `review-security`, `review-a11y`, `review-db`, `review-nextjs-rendering`, `review-ui-design-system`, `review-state-zustand` | カスタム化 | `review-db` は PostgreSQL、`review-state-zustand` は状態管理採用時のみ。UI/design は後回し可。 |
| Security | `security-config-audit`, `security-server-actions`, `privacy-pii-audit`, `security-owasp-2025`, `supply-chain-audit`, `secure-design-threat-model-audit`, `exception-resilience-audit` | カスタム化 | Server Actions を FastAPI / worker / runner に置換。OWASP LLM / MCP / provider compliance を追加。 |
| Supabase | `security-supabase-auth`, `supabase-patterns`, `db-performance-audit` | 除外 / 置換 | Supabase 固有は除外。`db-performance-audit` は PostgreSQL EXPLAIN / index / slow query 監査に置換。 |
| API / ADR / Observability | `api-contract-audit`, `adr-audit`, `observability-audit` | カスタム化 | FastAPI OpenAPI、ADR Gate Criteria 11 種、OTel/Loki/Prom/Grafana へ変更。 |
| Accessibility | `a11y-wcag22-aa` | 直接踏襲 + 軽微カスタム | UI 実装時に採用。 |
| Testing docs | `testing-patterns` | カスタム化 | Vitest + pytest + Playwright + state machine contract test に変更。 |
| Frontend patterns | `nextjs-16-patterns`, `shadcn-components`, `zustand-patterns` | 除外 / 後回し | TaskManagedAI の frontend stack 詳細が確定するまで保留。Next だけ軽量版を作ってもよい。 |
| PWA / Vercel / Email / Legal | `pwa-patterns`, `pwa-release-audit`, `vercel-firewall-audit`, `email-deliverability-audit`, `legal-compliance-audit` | 除外 / P1 | P0 は Tailscale 閉域、外部通知は対象外。 |
| Content / Game | `content-explanation-review`, `content-intro-quiz-review`, `ieshima-game-ui-patterns`, `typing-word-expansion`, `codex-image-gen` | 除外 | ieshima 学習プラットフォーム専用。 |
| Governance | `skill-lint` | カスタム化 | `skills.catalog.json` を TaskManagedAI でも採用するなら重要。catalog path と metadata を変更。 |

TaskManagedAI 専用 skill は 3.4 に記載する。

### 2.6 reference

| ieshima file | 分類 | TaskManagedAI 側 |
|------|------|------|
| `.claude/reference/harness-inventory.md` | カスタム化 | TaskManagedAI ハーネス一覧の正本。agents / hooks / skills / rules / Codex mirror を一覧化。 |
| `.claude/reference/agent-routing.md` | カスタム化 | Subagent / Skill / Bash / Codex の起動責務。TaskManagedAI 固有 reviewer の routing を定義。 |
| `.claude/reference/audit-ownership-matrix.md` | カスタム化 | OWASP + Hard Gates + ADR Gate + Provider Compliance の owner matrix に変更。 |
| `.claude/reference/governance-cycle.md` | カスタム化 | catalog sync、四半期レビュー、deprecate 規約は踏襲。 |
| `.claude/reference/dev-commands.md` | カスタム化 | `pnpm`, `uv` or `pip`, `pytest`, `ruff`, `mypy`, `docker compose`, DB migration, arq worker に変更。 |
| `.claude/reference/directory-structure.md` | カスタム化 | TaskManagedAI の `backend/`, `frontend/`, `docs/`, `config/`, `migrations/`, `eval/` 想定で作成。 |
| `.claude/reference/deliverables.md` | カスタム化 | `docs/sprints`, `docs/adr`, `docs/要件定義`, `docs/基本設計`, `docs/実装計画`, eval fixtures を正本化。 |
| `.claude/reference/db-schema-notes.md` | カスタム化 | PostgreSQL tenant boundary、actors/principals、AgentRun、ContextSnapshot、SecretBroker、Provider Matrix invariant を記載。 |
| `.claude/reference/rendering-strategy.md` | 除外 / 後回し | Next UI 実装が始まるまでは最小。必要なら `frontend-strategy.md` として新規。 |

### 2.7 scripts

| ieshima file | 分類 | TaskManagedAI 側 |
|------|------|------|
| `.claude/scripts/skills-catalog-lint.sh` | カスタム化 | catalog 管理を採用するなら必須。TaskManagedAI の `.claude/skills`, `.agents/skills`, catalog path に変更。Python/YAML/TOML metadata validation も追加候補。 |

## 3. TaskManagedAI 専用 新設リスト

### 3.1 新設 rules

- `rules/ai-output-boundary.md`
  - 目的: AI 出力直結禁止を常時ロード化する。
  - 入出力: AI artifact、policy decision、approval、runner sandbox の境界を定義。
  - 想定実装: `AGENTS.md` と PRD の原則を短く抽出し、command / SQL / workflow / external tool 直結禁止を明文化。

- `rules/sprint-pack-adr-gate.md`
  - 目的: Sprint Pack 必須 gate と ADR Gate Criteria 11 種を実装前条件にする。
  - 入出力: `docs/sprints/*.md`, `docs/adr/*.md`, high-risk change 判定。
  - 想定実装: light/heavy template の必須 frontmatter、ADR refs、risk / rollback / verification の必須化。

- `rules/provider-compliance.md`
  - 目的: Provider Compliance Matrix v2 の機械判定 invariant を常時参照させる。
  - 入出力: `config/provider_compliance.toml`, `payload_data_class`, `allowed_data_class`, ordinal map。
  - 想定実装: `public < internal < confidential < pii`、未設定 deny、Matrix 外 deny、unverified provider の confidential 以上 deny。

- `rules/agentrun-state-machine.md`
  - 目的: AgentRun 16 状態 + blocked サブ 3 の遷移を正本化する。
  - 入出力: AgentRun / AgentRunEvent / Artifact / Budget。
  - 想定実装: terminal state、repair exhaustion、provider refused/incomplete、event ordering を列挙。

- `rules/secretbroker-boundary.md`
  - 目的: secret 値非露出、`secret_ref`、capability token、atomic claim を常時制約にする。
  - 入出力: SecretBroker issue/redeem event、`secret_capability_tokens`、audit。
  - 想定実装: raw secret DB 保存禁止、AI/runner 直渡し禁止、one-time redeem と TTL を明記。

### 3.2 新設 agents

- `sprint-pack-reviewer`
  - Sprint Pack light/heavy の Documentation DoD、frontmatter、ADR refs、must_ship/defer を検証。
  - 出力は PASS/WARN/BLOCK + 欠落 checklist。

- `provider-compliance-reviewer`
  - Provider Compliance Matrix の enum、ordinal、unverified 条件、data class 越境を検証。
  - `payload_data_class` と `allowed_data_class` の信頼境界混在を重点確認。

- `actor-binding-reviewer`
  - `actors/principals`、approval self-approval 禁止、SecretBroker atomic claim の設計を検証。
  - P0 個人運用でも将来 multi-tenant に耐えるかを見る。

- `hard-gate-fixture-reviewer`
  - AC-HARD-01〜07 fixture、public regression / private holdout、anti-gaming rule を検証。
  - fixture 作成者と policy/prompt 修正者の分離も確認。

- `agentrun-state-reviewer`
  - AgentRun 16 状態 + `blocked` サブ 3 + terminal state + repair retry の遷移を検証。
  - contract test と migration enum の整合を見る。

- `tenant-project-isolation-reviewer`
  - workspace/project/repository/tenant 境界、複合 FK、negative test、将来 RLS 化余地を検証。
  - P0 個人運用でも boundary を崩していないかを見る。

- `postgres-specialist`
  - PostgreSQL DDL、migration、index、constraint、transaction、locking、JSONB、EXPLAIN を支援。
  - ieshima の `supabase-specialist` の置換。

- `runner-security-reviewer`
  - Docker isolated runner、forbidden path、dangerous command、resource cap、runner mutation gateway を検証。
  - AC-HARD-05 / 06 / 07 の実装前後レビューに使う。

### 3.3 新設 hooks

- `tailscale/check-tailscale-grants.sh`
  - PreToolUse / PostToolUse: Tailscale Serve / grants / Funnel / public exposure 変更を検出。
  - `Funnel` や公開 bind を見つけたら ADR 必須を通知。

- `secretbroker/check-secretbroker-ddl.sh`
  - PostToolUse: `secret_refs`, `secret_capability_tokens`, redeem / claim DDL の整合を検出。
  - TTL、one-time、atomic update、raw secret column 混入を確認。

- `agentrun/check-state-enum.sh`
  - PostToolUse: AgentRun status enum が 16 状態から逸脱していないか検出。
  - blocked_reason 3 種、terminal state、event ordering migration を確認。

- `provider/check-payload-data-class.sh`
  - PreToolUse / PostToolUse: provider call 実装に `payload_data_class` 必須チェックがあるか検出。
  - `allowed_data_class` を caller 入力として受け取る実装を BLOCK 候補にする。

- `sprint/check-sprint-pack-frontmatter.sh`
  - PostToolUse: `docs/sprints/*.md` の frontmatter YAML、type light/heavy、status、target_days/max_days を検証。
  - heavy で `adr_refs` が空なら警告。

- `adr/check-adr-gate.sh`
  - PostToolUse: ADR Gate Criteria 該当変更時に `docs/adr/ADR-NNNNN` 参照があるか検出。
  - 認証、DB schema、API 契約、AI 権限、MCP、Secrets、外部公開、破壊的操作、広範囲リファクタ、Provider、GitHub App permission を対象。

- `runner/check-dangerous-command-fixture.sh`
  - PostToolUse: runner command allowlist / denylist 変更時に AC-HARD-06 fixture 更新を促す。
  - `rm -rf`, `curl | sh`, `chmod 777`, fork bomb など。

- `postgres/check-tenant-boundary-ddl.sh`
  - PostToolUse: project/tenant/workspace 境界を持つ table の FK / constraint / negative test 欠落を検出。
  - AC-HARD-03 と連動。

### 3.4 新設 skills

- `sprint-pack-create`
  - 目的: 軽量/重量 Pack の起票補助。
  - 入出力: feature 名、risk class、ADR Gate 該当有無、`docs/sprints/SP-*.md` 草案。
  - 想定実装: template selection、frontmatter 生成、must_ship/defer table の該当 sprint 抽出。

- `adr-create`
  - 目的: ADR テンプレから proposed を作成。
  - 入出力: Gate 種別、関連 Sprint、選択肢、rollback、`docs/adr/ADR-NNNNN_*.md` 草案。
  - 想定実装: 11 Criteria のどれに該当するかを明記し、accepted 化前提の checklist を出す。

- `hard-gate-fixture-create`
  - 目的: AC-HARD-NN fixture 雛形生成。
  - 入出力: Hard Gate ID、public/private split、expected decision、dataset version。
  - 想定実装: `eval/security/...` 配下の fixture schema と anti-gaming rule を生成。

- `atomic-claim-validator`
  - 目的: SecretBroker redeem の atomic claim 設計検証。
  - 入出力: DDL / service code / transaction boundary。
  - 想定実装: `claimed_at is null` 条件付き update、TTL、one-time、audit event をチェック。

- `provider-compliance-audit`
  - 目的: Compliance Matrix TOML 全行検証。
  - 入出力: `config/provider_compliance.toml`、provider adapter call sites。
  - 想定実装: enum validation、ordinal validation、unverified condition downgrade、last_verified_at presence。

- `agentrun-state-machine-test`
  - 目的: 16 状態 + blocked サブ 3 の遷移 contract test 生成。
  - 入出力: status enum、transition table、pytest test。
  - 想定実装: valid/invalid transitions、terminal state immutability、repair exhaustion を fixtures 化。

- `runner-gateway-audit`
  - 目的: runner mutation gateway と tool mutating gateway stub の混同を検出。
  - 入出力: runner code、tool registry、policy decisions。
  - 想定実装: gateway_kind、approval、forbidden path、dangerous command、resource cap の検査。

- `postgres-boundary-audit`
  - 目的: tenant/project/workspace isolation DDL と negative test の監査。
  - 入出力: migrations、models、pytest DB tests。
  - 想定実装: composite FK、tenant_id consistency、cross-project negative fixtures を確認。

### 3.5 新設 reference

- `reference/taskmanagedai-stack.md`
  - Tailscale / FastAPI / arq / PostgreSQL / Redis / SOPS+age / GitHub App / Provider Adapter の技術スタックメモ。
  - 公式仕様が変わる項目は `last_verified_at` を持たせる。

- `reference/provider-compliance-matrix.md`
  - data class ordinal、Matrix 列、runtime downgrade、ADR 必須条件、audit payload の概念整理。
  - `config/provider_compliance.toml` と同期。

- `reference/hard-gates-and-kpis.md`
  - Hard Gates 7 / Quality KPIs 5 / Eval Harness / dashboard metric の早見表。
  - AC-HARD と AC-KPI の owner skill / agent / fixture path を対応付ける。

- `reference/secretbroker-contract.md`
  - `secret_ref`, capability token, atomic claim, one-time redeem, audit event, raw secret 禁止を整理。
  - DDL と service 実装の両方に trace する。

- `reference/agentrun-state-machine.md`
  - AgentRun 16 状態、blocked サブ 3、terminal state、provider result mapping、repair policy。
  - contract test の正本。

- `reference/adr-gate-criteria.md`
  - ADR Gate Criteria 11 種と、該当する docs / backlog / agent / hook の対応表。
  - Sprint Pack heavy template と同期。

## 4. 作成順序提案

| Phase | 成果物 | 内容 | Codex 推定所要時間 |
|------|------|------|------|
| Phase 1: Skeleton | `.claude/CLAUDE.md`, root `CLAUDE.md`, `AGENTS.md` 追補, `.mcp.json`, `.worktreeinclude` | 最小ハーネス入口を作る。既存 `AGENTS.md` は壊さない。 | 45-75 分 |
| Phase 2: Rules / Reference | `rules/*.md`, `reference/*.md` | AI 出力境界、Sprint Pack、Provider Compliance、SecretBroker、AgentRun、Hard Gates を正本化。 | 2-3 時間 |
| Phase 3: Agents | `.claude/agents/taskmanagedai/*.md` | 汎用 5 + 固有 6-8 agent を作成。出力 format を YAML/Markdown で固定。 | 2-3 時間 |
| Phase 4: Hooks minimal | `.claude/hooks/lib`, `system`, `sprint`, `adr`, `provider`, `secretbroker`, `agentrun`, `postgres`, `runner` | まず 12-18 hooks に絞る。`settings.json` に登録。 | 2-4 時間 |
| Phase 5: Skills / Suites | `dev-suite`, `quality-suite`, `review-suite`, `security-suite`, `release-suite`, 固有 skills | ieshima suite 構造を TaskManagedAI に移植。shell prelude と output JSON を統一。 | 4-6 時間 |
| Phase 6: Codex mirror | `.codex/config.toml`, `.codex/hooks.json`, `.codex/agents/*.toml`, `.agents/skills/*` | Codex 側に必要最小限を mirror。Claude 専用 env を持ち込まない。 | 1.5-2.5 時間 |
| Phase 7: Integration check | `harness-inventory.md`, `agent-routing.md`, `audit-ownership-matrix.md`, lint script, smoke | 件数、settings JSON、hook shellcheck、skill frontmatter、Codex hooks を検証。 | 2-3 時間 |

推奨順序は **Rules/Reference を先に固定し、その後 agents/hooks/skills を作る**こと。ieshima の経験上、suite や hooks を先に増やすと、正本不在の drift が起きやすい。

## 5. 成果物総量見積

ieshima 参考対象の実測:

- `.claude/hooks`: `.sh` 69 件、README 1 件
- `.claude/skills`: 55 skill ディレクトリ、84 ファイル
- `.claude/agents`: 16 件
- `.codex/agents`: 16 件
- `.claude/rules`: 7 件
- `.claude/reference`: 9 件
- `.claude/scripts`: 1 件
- root / settings / MCP / Codex config 系: 約 10 件

TaskManagedAI Phase 1-7 の目標規模:

| 種別 | 作成 / カスタム化 | 直接踏襲 | 除外 | 目安 |
|------|------:|------:|------:|------|
| settings / root | 8 | 0-1 | 1 | 既存を壊さず追補 |
| rules | 8-10 | 1 | 0 | ieshima 7 + TaskManagedAI 新設 3-5 |
| agents | 11-14 | 0 | 11 | Codex mirror を含めると倍 |
| hooks | 18-28 | 5-8 | 35+ | P0 は 12-18 から開始推奨 |
| skills | 28-38 | 1-2 | 20+ | suite 5 + specialty 20 前後 |
| reference | 10-13 | 0 | 1 | 新設 reference 多め |
| scripts | 1-3 | 0 | 0 | catalog lint + hook smoke |
| Codex mirror | 15-25 | 1 | 0 | agents / hooks / config / skills mirror |

概算:

- Phase 1 最小: 20-30 ファイル、80-140KB
- Phase 1-4 実用最小: 55-75 ファイル、220-380KB
- Phase 1-7 ieshima 同規模: 100-130 ファイル、450-750KB
- 除外する ieshima 固有物: content / intro-quiz / typing / Supabase / Vercel / PWA / shadcn で 70-90 ファイル相当

## 6. リスクと注意点

- **ieshima 固有 skill を誤踏襲する罠**
  - `typing-word-expansion`, `ieshima-game-ui-patterns`, `content-explanation-review`, `content-intro-quiz-review`, `codex-image-gen` は強いドメイン依存がある。TaskManagedAI へコピーしない。

- **Supabase 前提の混入**
  - `auth.uid()`, `RLS`, `service_role`, `signInAnonymously`, Supabase Storage / Realtime は TaskManagedAI の P0 前提とズレる。PostgreSQL 一般 invariant だけ抽出する。

- **Claude 専用 env の Codex への混入**
  - ieshima の `.claude/settings.json` は `$CLAUDE_PROJECT_DIR` を使うが、Codex hooks では `$PWD` など Codex-safe path に変える必要がある。

- **hooks 過多**
  - ieshima は 60+ hooks。TaskManagedAI で最初から同規模にすると rate limit / noise / 誤発火対応が重くなる。P0 Hard Gates に直結するものから始める。

- **Codex rate limit との折衷**
  - review-suite / security-suite / release-suite から毎回深い Codex chain を呼ぶと重い。TaskManagedAI では `--quick`, `--scope=changed`, `--no-external-agent` 相当を用意する。

- **Phase 7 統合チェックで露呈しやすい不整合**
  - rules と AGENTS.md の重複 drift
  - skills catalog と SKILL.md frontmatter の不一致
  - `.claude/settings.json` の hook path 不一致
  - `.codex/agents/*.toml` の Claude-only field 残留
  - ADR Gate Criteria と Sprint Pack heavy template の refs 不一致
  - Provider Matrix の docs と TOML の列定義不一致

- **P0 個人運用と SaaS 前提のズレ**
  - TaskManagedAI は P0 個人専用 / Tailscale 閉域だが、将来商用化のため tenant boundary を残す設計。ieshima は学校向け Web SaaS / Supabase Auth 前提。認証・公開・通知・法務・DB 境界の前提を混ぜない。

- **AI 出力直結禁止の弱体化**
  - TaskManagedAI の競争力は「AI に広い権限を渡すこと」ではなく、artifact、schema validation、policy、approval、runner sandbox、audit を挟むこと。ハーネスもこの思想を最優先にする。

