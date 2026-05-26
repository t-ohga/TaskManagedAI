---
id: "SP-035_superintendent_agent"
type: "heavy"
status: "completed"
sprint_no: 35
created_at: "2026-05-26"
updated_at: "2026-05-26"
target_days: 10
max_days: 14
adr_refs:
  - "[ADR-00027](../adr/00027_superintendent_agent.md) # accepted 2026-05-26"
planned_adr_refs: []
related_sprints:
  - "SP-013_multi_agent_orchestration"
  - "SP-014_orchestrator_agent"
  - "SP-024_autonomy_policy_profiles"
  - "SP-034_mcp_server_gateway"
risks:
  - "Superintendent が human 権限を超える経路"
  - "Superintendent 自身の暴走 (kill switch 不能)"
  - "delegation policy の設定ミスで意図しない自動承認"
  - "agent spawn 制御の不足で resource 枯渇"
---

## 目的

- 人間 (ユーザー) の **代理 AI (Superintendent)** を導入し、TaskManagedAI の管理運営を委任する
- Superintendent が設定管理、AI agent 起動・停止・role 割当、approval 委任、ワークフロー管理を一元化
- 人間はいつでも Superintendent を停止・上書きでき、merge / deploy / secret 変更は常に human-only

## 背景

- SP-013/014 で multi-agent 基盤 (10 roles, lease, failover, kill switch) 完成
- SP-024 で Autonomy Level L0-L3 導入済
- SP-034 で MCP Server (15 tools) 完成
- 足りないのは「代理 AI が全体を管理する」レイヤー

## 対象外

- multi-tenant での複数 Superintendent (P2)
- Superintendent の自律 merge / deploy (human-only 不変)
- Superintendent が SecretBroker の raw secret にアクセスする経路 (禁止)
- 外部 SaaS 連携 (Slack / Email) での Superintendent 通知 (P2)

## 設計判断

### Superintendent = 特別な actor_type

```
actor_type enum 追加:
  "human" | "service" | "agent" | "provider" | "github_app" | "superintendent"
```

- Superintendent は **1 project に最大 1 体**
- human が明示的に Superintendent を有効化 (設定 UI or CLI)
- **Superintendent は approval_decide 不可** (human-only invariant 維持、R1-CRITICAL-1 fix)
- 低リスク自動処理は **Policy Engine auto-allow** (SP-024 L0-L3 拡張) として実装。`approval_requests` を決裁するのではなく、`policy_decisions` + audit に記録
- merge / deploy / secret_access / provider_call は **常に human-only** (R1-HIGH-1 fix)

### Delegation Policy

```python
@dataclass
class DelegationPolicy:
    max_auto_approve_risk: Literal["none", "low", "medium"]  # L0=none, L1=low, L2=medium
    max_budget_per_run: Decimal  # USD
    max_concurrent_agents: int
    allowed_providers: list[str]  # Provider Compliance Matrix subset
    forbidden_actions: frozenset[str]  # always: {"merge", "deploy", "secret_access", "provider_call", "approval_decide"}
    auto_retry_on_failure: bool
    escalate_to_human_after: int  # consecutive failures
```

- `none`: Superintendent は agent を起動できるが approval は全て human 待ち (L0 相当)
- `low`: 低リスク (task_write, read_only) を自動承認、repo_write / pr_open は human 待ち
- `medium`: repo_write も自動承認、pr_open は human 待ち
- **merge / deploy / secret_access / provider_call / approval_decide は常に forbidden** (policy で変更不可、hardcode)
- delegation policy の write (変更) は **human-only** (Superintendent は read + apply のみ、R1-CRITICAL-3 fix)
- control-domain lineage: Superintendent が spawn/assign した agent の request は auto-allow 対象外 (R1-CRITICAL-2 fix)

### Agent Lifecycle

```
Superintendent → agent_register(role, provider, project) → actor 作成
Superintendent → agent_start(agent_id) → MCP client spawn
Superintendent → agent_assign(agent_id, ticket_id) → AgentRun 作成
Agent → TaskManagedAI MCP → ticket/run/audit
Superintendent → agent_stop(agent_id) → lease revoke + process kill
```

### Superintendent MCP Tools (7 新規)

| Tool | 内容 | human override |
|---|---|---|
| `superintendent_agent_register` | agent 登録 + role 割当 | human kill switch |
| `superintendent_agent_start` | agent process spawn | human kill switch |
| `superintendent_agent_stop` | agent 停止 | human override |
| `superintendent_agent_list` | 登録 agent roster | read-only |
| `superintendent_delegation_show` | delegation policy 確認 (read-only) | — |
| `superintendent_dispatch` | ticket → agent 割当 + run 開始 | delegation policy gate |

### Workflow Orchestration

```
1. Superintendent がチケット一覧を確認 (ticket_list)
2. チケットを sub-task に分解 (ticket_create × N)
3. 各 sub-task に適切な role の agent を割当 (superintendent_dispatch)
4. Agent が実行、Superintendent が進捗監視 (run_show polling)
5. 低リスク approval は自動承認 (delegation policy)
6. 高リスク approval は human に escalate
7. 全 sub-task 完了 → 親チケット close
8. KPI チェック → 基準未達なら re-dispatch
```

### 安全境界 (5 レイヤー防御)

1. **actor_type gate**: Superintendent ≠ human。merge/deploy/secret は actor_type check で deny
2. **delegation policy gate**: auto-approve は policy 範囲内のみ。範囲外は human escalate
3. **BudgetGuard**: agent ごと + 全体の cost cap
4. **kill switch**: human がいつでも Superintendent + 全 agent を即停止
5. **audit**: Superintendent の全操作を audit_events に記録

### Policy Templates (プラスアルファ)

| template | auto_approve | budget | agents | use case |
|---|---|---|---|---|
| `conservative` | none | $1/run | 2 | 初めて使う、リスク低 |
| `balanced` | low | $5/run | 5 | 通常開発 |
| `aggressive` | medium | $20/run | 10 | sprint 追い込み |

### Agent Performance Report (プラスアルファ)

- agent ごとの: 完了 task 数、成功率、平均コスト、平均 time_to_complete
- provider ごとの: call 数、cost、error rate
- Superintendent decision log: auto-approve / escalate / retry の比率

## 実装チケット

| BL | 内容 |
|---|---|
| BL-0400 | actor_type="superintendent" 追加 (migration + enum) |
| BL-0401 | DelegationPolicy model + policy_templates seed |
| BL-0402 | Superintendent session + long-lived token |
| BL-0403 | Agent lifecycle API (register/start/stop/list) |
| BL-0404 | Superintendent approval delegation engine |
| BL-0405 | Workflow dispatch (ticket → agent → run) |
| BL-0406 | 7 Superintendent MCP tools |
| BL-0407 | Settings UI (delegation policy + agent roster) |
| BL-0408 | Policy templates + performance report |
| BL-0409 | E2E test + negative test + closeout |

## タスク一覧

- [ ] batch 0: ADR-00027 起票 + accepted
- [ ] batch 1: BL-0400 + BL-0401 (DB migration + delegation model)
- [ ] batch 2: BL-0402 + BL-0403 (session + agent lifecycle)
- [ ] batch 3: BL-0404 + BL-0405 (approval delegation + workflow dispatch)
- [ ] batch 4: BL-0406 (7 MCP tools)
- [ ] batch 5: BL-0407 + BL-0408 (UI + templates + report)
- [ ] batch 6: BL-0409 (E2E + closeout)

## must_ship / defer_if_over_budget

| must_ship | defer_if_over_budget |
|---|---|
| Superintendent actor + delegation policy + agent lifecycle + dispatch + MCP tools | UI page / templates / performance report / auto-scaling / learning loop |

## 受け入れ条件

- [ ] Superintendent が MCP 経由で agent 登録 → role 割当 → dispatch → 進捗確認ができる
- [ ] delegation policy に基づき低リスク approval を自動承認できる
- [ ] merge / deploy / secret_access は Superintendent でも deny
- [ ] human がいつでも kill switch で Superintendent + 全 agent を停止できる
- [ ] Superintendent の全操作が audit_events に記録される
- [ ] agent ごとの budget cap が enforce される
- [ ] max_concurrent_agents を超える spawn が deny される
- [ ] Superintendent が self-escalate (自身の policy を変更) できない

## 検証手順

```bash
uv run pytest tests/superintendent/ -q
uv run ruff check backend/app/services/superintendent/
uv run mypy backend/app/services/superintendent/
```

## 残リスク

- Superintendent が delegation policy を「変更」する権限の粒度 (read は OK、write は human-only?)
- multi-Superintendent 環境での競合 (P2)
- agent spawn の resource limit (docker container 数上限)
- Superintendent session の TTL 管理 (長命だが無期限ではない)
