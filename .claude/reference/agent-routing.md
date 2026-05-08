# Agent Routing

Subagent / Skill / Bash / Codex の起動責務。  
TaskManagedAI 固有 reviewer の使い分けと、再帰・並列・採否判定の境界を整理する。

## 1. 起動経路

| 経路 | 適用場面 | 例 |
|---|---|---|
| メイン会話 | 計画、採否判定、統合判断 | Sprint Pack 判定、ADR 要否 |
| Subagent | 専門視点レビュー、context 分離 | `provider-compliance-reviewer` |
| Skill | 再現可能な手順、suite orchestration | `quality-suite`, `adr-create` |
| Bash | 実コマンド、lint、test、migration check | `uv run pytest` |
| Codex | 別モデル視点、実装委譲、計画レビュー | `codex-plan-review` |

## 2. 原則

- Subagent から Subagent を再帰起動しない。
- Subagent から Codex skill を再帰起動しない。
- Codex chain の並列起動は禁止。
- Bash で destructive operation を実行する前に Sprint Pack / ADR / rollback を確認する。
- Skill は正本ではなく手順。結果は rules / docs と照合する。
- すべての external agent 出力は `adopt` / `reject` / `defer`。
- 採用前に実ファイルと設計 docs を確認する。

## 3. Main Conversation の責務

- ユーザー要求の scope 確定。
- Sprint Pack / ADR Gate 判定。
- high-risk 変更の確認。
- 複数 reviewer の結果統合。
- Codex / Subagent 結果の採否判定。
- rollback / verification の最終確認。
- final report 作成。

## 4. Subagent Routing

| agent | 使う場面 | 主な確認 |
|---|---|---|
| `code-reviewer` | 実装差分全般 | bug、regression、missing tests |
| `plan-reviewer` | 実装前計画 | Sprint Pack DoD、ADR Criteria |
| `release-auditor` | Sprint 12 / P0 Exit | Hard Gates 7、KPIs 5 |
| `security-specialist` | security boundary | deny-by-default、OWASP LLM |
| `tdd-orchestrator` | test design | unit / contract / E2E |
| `sprint-pack-reviewer` | Pack 作成・更新 | light/heavy、frontmatter |
| `provider-compliance-reviewer` | ProviderAdapter / Matrix | ordinal、ZDR、preflight |
| `actor-binding-reviewer` | auth / approval | actor / principal / self-approval |
| `hard-gate-fixture-reviewer` | eval fixtures | Anti-Gaming、holdout |
| `agentrun-state-reviewer` | Agent Runtime | 16 状態、blocked サブ 3 |
| `tenant-project-isolation-reviewer` | DB boundary | 複合 FK、negative test |
| `postgres-specialist` | migration / query | PostgreSQL correctness |
| `runner-security-reviewer` | sandbox / command | forbidden path、dangerous command |

## 5. Skill Routing

| skill / suite | 起動責務 | 代表 output |
|---|---|---|
| `dev-suite` | 実装前後の作業 flow | task breakdown / checks |
| `quality-suite` | lint / type / test | verification report |
| `review-suite` | code review | findings / residual risk |
| `security-suite` | security audit | boundary findings |
| `release-suite` | P0 Exit | release readiness |
| `sprint-pack-create` | Pack draft | `docs/sprints/SP-*.md` |
| `adr-create` | ADR draft | `docs/adr/ADR-*.md` |
| `hard-gate-fixture-create` | eval fixture | `eval/**` fixture |
| `atomic-claim-validator` | SecretBroker review | SQL / contract findings |
| `provider-compliance-audit` | Matrix review | ordinal / ZDR findings |
| `agentrun-state-machine-test` | transition tests | contract test draft |
| `runner-gateway-audit` | runner boundary | forbidden path / command findings |
| `postgres-boundary-audit` | DB boundary | FK / tenant findings |

## 6. Bash Routing

| 用途 | コマンド例 | 注意 |
|---|---|---|
| file search | `rg`, `rg --files` | `grep -R` より優先 |
| JSON | `jq` | 巨大 JSON 丸読み禁止 |
| frontend type | `pnpm typecheck` | 実 compiler を地上真実にする |
| frontend test | `pnpm test` | 弱い assertion を避ける |
| e2e | `pnpm test:e2e` | UI 変更時 |
| backend lint | `uv run ruff check backend tests` | auto-fix 前に diff 確認 |
| backend type | `uv run mypy backend` | type ignore 乱用禁止 |
| backend test | `uv run pytest` | contract / negative を含む |
| migration | `uv run alembic check` | destructive 変更は ADR |
| compose | `docker compose up --build` | public bind に注意 |
| worker | `uv run arq backend.worker.WorkerSettings` | queue / timeout 確認 |

## 7. Codex Routing

| Codex skill | 用途 | 上限 / 注意 |
|---|---|---|
| `codex-task` | bounded implementation | 同時並列禁止 |
| `codex-second-opinion` | 単発レビュー | 採否判定必須 |
| `codex-plan-review` | Sprint Pack / ADR review | high-risk 計画 |
| `codex-adversarial-review` | 敵対レビュー | security / runner / provider |
| `codex-rescue` | 行き詰まり救援 | 失敗 2 回以上目安 |

## 8. High-Risk Routing

| 変更 | 推奨 routing |
|---|---|
| DB schema | `plan-reviewer` + `postgres-specialist` + `tenant-project-isolation-reviewer` |
| Provider | `provider-compliance-reviewer` + `security-specialist` |
| SecretBroker | `security-specialist` + `actor-binding-reviewer` |
| AgentRun | `agentrun-state-reviewer` + `tdd-orchestrator` |
| Runner | `runner-security-reviewer` + `security-specialist` |
| GitHub App | `security-specialist` + `release-auditor` |
| Tailscale / exposure | `security-specialist` + `release-auditor` |
| Sprint Pack / ADR | `plan-reviewer` + `sprint-pack-reviewer` |

## 9. 採否判定 Format

```md
### External Review Decision

- source: <agent-or-skill-or-codex>
- decision: adopt | reject | defer
- reason: <why>
- checked_against:
  - `.claude/rules/<rule>.md`
  - `docs/<source>.md`
- follow_up:
  - <action-or-none>
```

## 10. 失敗時 Routing

| 状況 | 対応 |
|---|---|
| Subagent finding が曖昧 | メイン会話で実ファイル確認 |
| Skill output が古い | rules / docs を正本にして修正 |
| Codex failure 1-2 回 | 原因を整理して retry 可否判断 |
| Codex failure 3 回 | 自動停止、ユーザー確認 |
| reviewer 同士が矛盾 | 正本 docs と tests に戻る |
| high-risk 不明 | 実装せず選択肢を提示 |

## 11. 禁止

- Subagent へ実装全体を丸投げする。
- Codex を複数同時に走らせる。
- Agent / Skill の出力を検証せず final に転記する。
- Bash で destructive command を承認なしに実行する。
- `allowed_data_class` を caller 入力として扱う案を採用する。
- raw secret を含む output を reviewer に渡す。
- private_holdout の期待値を prompt / policy 調整に使う。

