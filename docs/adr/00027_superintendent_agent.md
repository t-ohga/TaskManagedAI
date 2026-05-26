---
id: "ADR-00027"
title: "Superintendent Agent — AI 代理管理レイヤー"
status: "accepted"
date: "2026-05-26"
accepted_at: "2026-05-26"
deciders:
  - "TaskManagedAI core"
adr_gate_criteria:
  - "4: AI エージェント権限"
  - "6: Secrets 管理方式"
---

## 背景

TaskManagedAI は multi-agent 基盤 (10 roles, lease, failover, kill switch, Autonomy L0-L3, MCP Server) を持つが、人間が全 agent を直接管理する必要がある。Superintendent を導入し、人間の代理として管理運営を委任する。

## 決定対象

- Superintendent の actor_type と権限範囲
- delegation policy による自動承認の範囲
- 安全境界 (human override / kill switch)

## 採用案

### actor_type = "superintendent"

- actor_type enum に `superintendent` を追加
- 1 project に最大 1 Superintendent
- approval_decide 可能 (delegation policy 範囲内のみ)
- **merge / deploy / secret_access は常に deny** (hardcode、policy 変更不可)

### 5 レイヤー防御

1. actor_type gate (merge/deploy/secret deny)
2. delegation policy gate (auto-approve 範囲制限)
3. BudgetGuard (cost cap)
4. kill switch (human 即停止)
5. audit (全操作記録)

### delegation policy 設計

- `max_auto_approve_risk`: none / low / medium
- `forbidden_actions`: {"merge", "deploy", "secret_access"} (不変)
- Superintendent 自身が policy を write 変更不可 (human-only)

## 却下案

1. **Superintendent = human 権限**: human-only 境界が崩壊。merge/deploy を AI が実行可能になる。
2. **Superintendent なし (全 agent 直接管理)**: 管理コストが高い。agent 数が増えると破綻。
3. **Superintendent が delegation policy を自己変更可能**: self-escalation リスク。

## リスク

- delegation policy 設定ミスで意図しない自動承認 → policy templates + conservative default で緩和
- Superintendent 自身の暴走 → kill switch + audit + human override
- agent spawn 制御不足 → max_concurrent_agents + docker resource limit

## Rollback

- Superintendent actor を revoke → 全 agent session も失効
- delegation policy を "none" に → 全 approval が human 待ちに戻る
- SP-034 MCP Server は影響なし (agent 個別接続は維持)
