# Harness Inventory

TaskManagedAI ハーネス構成の一覧。  
rules / reference / agents / hooks / skills / Codex mirror の責務と正本を把握するための ad-hoc 参照。

## 1. 正本レイヤー

| レイヤー | パス | 役割 |
|---|---|---|
| Project guide | `.claude/CLAUDE.md` | Claude Code 側の常時ロード骨格 |
| Codex guide | `AGENTS.md` | Codex 側のプロジェクトスコープ指示 |
| Rules | `.claude/rules/*.md` | 常時制約、採否判断の第一参照 |
| Reference | `.claude/reference/*.md` | 詳細表、routing、commands、contract |
| Agents | `.claude/agents/*.md` | Claude subagent reviewer |
| Codex agents | `.codex/agents/*.toml` | Claude agent の必要分 mirror |
| Hooks | `.claude/hooks/**/*.sh` | Claude hook |
| Codex hooks | `.codex/hooks.json` | Codex で実行可能な shell hook |
| Skills | `.claude/skills/**/SKILL.md` | Claude skill / suite |
| Docs | `docs/**` | PRD / DD / Sprint Pack / ADR 正本 |
| Eval | `eval/**` | Hard Gates / Quality KPIs fixture |

## 2. Rules Inventory

| file | 主目的 | 重要 invariant |
|---|---|---|
| `core.md` | 基本制約 | 型安全、AI 出力境界、deny-by-default |
| `testing.md` | テスト規律 | Vitest / pytest / Playwright / Anti-Gaming |
| `rendering.md` | frontend 方針 | Next.js 16 App Router、Server Components |
| `plan-review.md` | 実装前レビュー | Sprint Pack DoD、ADR Gate Criteria |
| `code-search.md` | 調査手順 | LSP 優先、`rg` fallback、compiler 確認 |
| `instincts.md` | 事故予防 | SecretBroker、AgentRun、Provider、Tailscale |
| `codex-usage-policy.md` | Codex 連携 | 並列禁止、3 失敗停止、adopt/reject/defer |
| `ai-output-boundary.md` | AI 出力境界 | artifact -> validation -> policy -> approval |
| `sprint-pack-adr-gate.md` | Sprint / ADR gate | light/heavy frontmatter、high-risk 判定 |
| `provider-compliance.md` | Provider Matrix | `payload_data_class`、data class ordinal |
| `agentrun-state-machine.md` | AgentRun lifecycle | 16 状態、blocked サブ 3、terminal |
| `secretbroker-boundary.md` | secret 境界 | `secret_ref`、atomic claim、one-time redeem |

## 3. Reference Inventory

| file | 主目的 |
|---|---|
| `harness-inventory.md` | ハーネス全一覧 |
| `agent-routing.md` | Subagent / Skill / Bash / Codex の起動責務 |
| `audit-ownership-matrix.md` | Hard Gates / ADR / OWASP / NIST owner 対応 |
| `governance-cycle.md` | catalog sync、四半期レビュー、deprecate 規約 |
| `dev-commands.md` | local / CI / worker / migration commands |
| `directory-structure.md` | 想定 repository layout |
| `deliverables.md` | docs / eval / sprint / ADR 成果物 |
| `db-schema-notes.md` | DB invariant 早見表 |
| `frontend-strategy.md` | Next.js 16 + Tailwind 最小方針（component library は Sprint 9 の ADR で確定） |
| `provider-compliance-matrix.md` | Matrix contract 詳細 |
| `hard-gates-and-kpis.md` | Hard Gates / KPIs 早見表 |
| `secretbroker-contract.md` | SecretBroker contract 詳細 |
| `skill-lint-banned-terms.md` | skill-lint の禁止語 / 必須 trace 用語 / 再帰起動 pattern レジストリ (machine-readable block 含む) |

### Phase 0 §3.5 missing reference の crosswalk

Phase 0 mapping §3.5 が列挙する新設 reference のうち、以下 3 件は別 file に統合済:

| Phase 0 §3.5 計画 | 実装場所 | 統合理由 |
|---|---|---|
| `taskmanagedai-stack.md` | `dev-commands.md` + `directory-structure.md` | 技術スタックの操作面 (commands) と layout 面 (directory) は別ファイルで管理する方が保守しやすい |
| `agentrun-state-machine.md` (reference) | `rules/agentrun-state-machine.md` (常時ロード) + `db-schema-notes.md` §6-8 (DB invariant) | 16 状態 invariant は常時参照する rules 側に置くのが正本。DB schema 詳細は db-schema-notes に分離 |
| `adr-gate-criteria.md` | `rules/sprint-pack-adr-gate.md` §4 (Criteria 11 種) + `reference/audit-ownership-matrix.md` §4 (Owner 対応) | Gate Criteria は実装前判定として常時参照されるため rules 側。Owner 対応表は reference 側 |

## 4. Claude Agents 想定

| agent | 主責務 | 起動タイミング |
|---|---|---|
| `code-reviewer` | 実装差分レビュー | PR / diff review |
| `plan-reviewer` | Sprint Pack / ADR レビュー | 実装前 |
| `release-auditor` | P0 Exit / release readiness | Sprint 12 / release |
| `security-specialist` | policy / secret / provider / runner | security 変更 |
| `tdd-orchestrator` | テスト設計・追加 | 実装着手時 |
| `sprint-pack-reviewer` | Pack DoD / light-heavy 判定 | Pack 作成時 |
| `provider-compliance-reviewer` | Matrix / ordinal / ZDR 判定 | Provider 変更 |
| `actor-binding-reviewer` | actor / principal / approval | auth / approval |
| `hard-gate-fixture-reviewer` | Eval fixture / anti-gaming | Sprint 11 |
| `agentrun-state-reviewer` | 16 状態 / transition | Agent runtime |
| `tenant-project-isolation-reviewer` | DB boundary | migrations |
| `postgres-specialist` | PostgreSQL / performance / migration | DB 変更 |
| `runner-security-reviewer` | sandbox / command / path | runner 変更 |

## 5. Hooks 想定

| hook | 目的 | 対象 |
|---|---|---|
| `tailscale/check-tailscale-grants.sh` | Tailscale grants / Funnel 警告 | network config |
| `secretbroker/check-secretbroker-ddl.sh` | SecretBroker DDL contract | migrations |
| `agentrun/check-state-enum.sh` | AgentRun status enum drift | backend / frontend |
| `provider/check-payload-data-class.sh` | Provider call preflight / data class | provider code |
| `sprint/check-sprint-pack-frontmatter.sh` | Pack YAML / type / dates | docs/sprints |
| `adr/check-adr-gate.sh` | ADR Gate Criteria 検出 | high-risk paths |
| `runner/check-dangerous-command-fixture.sh` | dangerous command fixture | runner / eval |
| `postgres/check-tenant-boundary-ddl.sh` | tenant / project FK | migrations |

### Hook Coverage: Claude (.claude/settings.json) vs Codex (.codex/hooks.json)

P0 では Claude / Codex で hook coverage を意図的に分ける。Codex は hook 数を抑えてレイテンシ優先、Claude は P0 Hard Gates を含む全 hook を発火。

| カテゴリ | hook | Claude (`.claude/settings.json`) | Codex (`.codex/hooks.json`) | 理由 / Codex 不在時の代替 |
|---|---|---|---|---|
| sprint | `sprint/check-sprint-pack-frontmatter.sh` | ✅ | ✅ | 両方で発火 (Sprint Pack drift 即時検出) |
| adr | `adr/check-adr-gate.sh` | ✅ | ✅ | 両方で発火 (ADR Gate Criteria) |
| provider | `provider/check-payload-data-class.sh` | ✅ | ✅ | 両方で発火 (Provider Compliance) |
| secretbroker | `secretbroker/check-secretbroker-ddl.sh` | ✅ | ✅ | 両方で発火 (raw secret 防御) |
| agentrun | `agentrun/check-state-enum.sh` | ✅ | ❌ | Codex 側は `provider-compliance-audit` skill / `agentrun-state-machine-test` skill で代替確認 |
| postgres | `postgres/check-tenant-boundary-ddl.sh` | ✅ | ❌ | Codex 側は `postgres-boundary-audit` skill で代替確認 |
| runner | `runner/check-dangerous-command-fixture.sh` | ✅ | ❌ | Codex 側は `runner-gateway-audit` skill / `hard-gate-fixture-create` skill で代替確認 |
| tailscale | `tailscale/check-tailscale-grants.sh` | ✅ | ❌ | Codex 側は `security-config-audit` skill で代替確認 |
| file-changed | `file-changed/warn-external-migration-edit.sh` | ✅ | ❌ | Codex 側は AGENTS.md の git 操作慎重原則で human review |
| quality | `quality/check-payload-data-class-on-toml.sh` | ✅ | ❌ | Codex 側は `provider-compliance-audit` skill で代替 |
| system | `system/block-git-add-bulk.sh` | ✅ | ✅ | 両方で発火 (`git add -A` BLOCK) |
| system | `system/sessionstart-detect-worktree.sh` | ✅ (SessionStart) | ❌ | Codex は SessionStart hook をサポートしないため不在 |
| system | `system/pretool-bash-snapshot.sh` + `posttool-bash-file-dispatcher.sh` | ✅ (Bash 経由 file change 検出) | ❌ | Phase 4 残リスク (`PH4-F-001` / `PH4-F-002`) として Sprint 7 で repo 外 trusted wrapper 化。詳細は `docs/設計検討/harness-residual-risks.md` |

**変更時のルール**: Claude / Codex どちらかに hook を追加した場合、本表を必ず更新する。Codex 側を意図的に外す場合は「代替確認手順」を明記する。

## 6. Skills 想定

| skill | 目的 |
|---|---|
| `dev-suite` | 実装前後の開発 orchestration |
| `quality-suite` | lint / type / test / coverage |
| `review-suite` | code / design / regression review |
| `security-suite` | OWASP / provider / secret / runner audit |
| `release-suite` | P0 Exit / release readiness |
| `sprint-pack-create` | Sprint Pack 作成 |
| `adr-create` | ADR 作成 |
| `hard-gate-fixture-create` | Hard Gate fixture 作成 |
| `atomic-claim-validator` | SecretBroker atomic claim 検証 |
| `provider-compliance-audit` | Matrix / data class audit |
| `agentrun-state-machine-test` | 16 状態 contract test |
| `runner-gateway-audit` | runner mutation gateway audit |
| `postgres-boundary-audit` | tenant / project boundary audit |

## 7. Codex Mirror

| file | 方針 |
|---|---|
| `.codex/config.toml` | Codex 実行設定。Claude-only env を持ち込まない |
| `.codex/hooks.json` | 実行可能な shell hook のみ |
| `.codex/agents/*.toml` | 必要 agent だけ mirror |
| `.codex/migrate-to-codex-report.txt` | 変換時の manual review 記録 |

手動確認:

- Claude-only field なし。
- Claude-only tool 名なし。
- `$CLAUDE_PROJECT_DIR` なし。
- AskUserQuestion 前提なし。
- Skill 再帰起動前提なし。
- 存在しない path なし。
- hook が shell command として実行可能。

## 8. Control Flow

1. User request。
2. `.claude/CLAUDE.md` / `AGENTS.md` で基本方針確認。
3. `.claude/rules/*.md` で常時制約確認。
4. 必要なら `.claude/reference/*.md` を読む。
5. Sprint Pack / ADR Gate を判定。
6. 実装・テスト・自己レビュー。
7. Hard Gates / Quality KPIs への trace を確認。
8. Review 欄、ADR、reference を必要に応じて更新。
9. Codex / external agent 出力は `adopt` / `reject` / `defer`。

## 9. Drift Detection

| drift | 確認方法 |
|---|---|
| AgentRun status drift | DB / API / frontend / eval enum 比較 |
| Provider Matrix drift | TOML / docs / tests / audit payload 比較 |
| SecretBroker drift | DD-02 / DD-06 / migration / tests 比較 |
| ADR Criteria drift | heavy template / rules / backlog 比較 |
| Hook drift | shell 実行可否 / path 存在確認 |
| Codex mirror drift | Claude-only field / path / tool 名確認 |

## 10. 更新ルール

- rules を変えたら関連 reference と `.claude/CLAUDE.md` の重複 drift を確認する。
- reference を変えたら正本 docs との整合を確認する。
- agents / hooks / skills を追加したら inventory と routing を更新する。
- Provider Matrix を変えたら ADR、TOML、reference、test を同期する。
- SecretBroker contract を変えたら DD-06、DD-02、migration、test を同期する。
- AgentRun 状態を変える場合は P0 contract 破壊として ADR 必須。

