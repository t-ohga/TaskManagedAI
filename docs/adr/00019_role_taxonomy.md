---
id: "ADR-00019"
title: "Role Taxonomy + Custom Role Extension: 10 標準 (code enum、reserved namespace) + project_agent_roles + role ⊥ capability + soft-delete + agent_run_project_roles link table option"
status: "proposed"
date: "2026-05-10"
authors:
  - "t-ohga"
related_sprints:
  - "SP-013_multi_agent_orchestration"
  - "SP-017_ai_society_visualization"
related_research:
  - "docs/設計検討/phase-c-multi-agent-spec-draft.md §C-1 + §11.3 PE-F-001/PE-F-012"
acceptance_blocked_by:
  - "ADR-00014 accepted"
  - "P0 完了"
---

最終更新: 2026-05-10 (proposed 起票)

## 背景

- 決定対象: ADR-00014 で導入した 10 標準役職の **DDL 詳細** + **custom role 拡張機構** + **role ⊥ capability authorization invariant** を独立 ADR で固定.
- ADR Gate Criteria #2 (DB schema) + #4 (AI 権限) 該当.

## 採用案

### §1: 標準 10 役職 (code enum、reserved namespace、PE-F-001 fix)

`backend/app/domain/agent_role/taxonomy.py`:

```python
STANDARD_ROLE_IDS: Final[frozenset[str]] = frozenset({
    "orchestrator", "implementer", "reviewer", "tester", "security_agent",
    "researcher", "observer", "curator", "dispatcher", "repair_specialist",
})

# PE-F-001: STANDARD_ROLE_IDS は custom role_id として禁止
def validate_custom_role_id(role_id: str) -> None:
    if role_id in STANDARD_ROLE_IDS:
        raise ValueError(f"role_id '{role_id}' is reserved for standard role")
```

5+ source: Python Literal + Pydantic Field validator + pytest EXPECTED constant + frontend TypeScript enum + DB-side `STANDARD_ROLE_IDS_MIRROR` table (immutable seed for CHECK generated、PE-F-012 採用案).

### §2: project_agent_roles (project-scoped、ADR-00014 §2 共有)

DDL は ADR-00014 §2 参照。`recommended_action_class` 列は **存在しない** (R-009 / S-2 / AP-2 mitigation: role が capability を授与しない).

### §3: role_scope DB 防御 — 2 案 (PE-F-012)

| 案 | 概要 | 採用判断 |
|---|---|---|
| **A: constraint trigger** | `before insert or update of tenant_id, project_id, role_id, role_scope` で trigger 発火、project_agent_roles existence 検証 | SP-013 default 採用 |
| **B: agent_run_project_roles link table** | (tenant_id, project_id, role_id) FK で DB level enforce | SP-013 着手時に再評価、A では検証困難な edge case (例: tenant_id 変更後の role 再 resolve) があれば B に切替 |

`role_scope='global'` は `STANDARD_ROLE_IDS_MIRROR` table (immutable seed、HARD DELETE 不可 trigger) で CHECK generated.

### §4: role ⊥ capability authorization (ADR-00014 §4 共有)

(ADR-00014 §4 参照). authorization の正本は capability token + action_class + 3 gateway + Tool Registry + ProviderAdapter.

### §5: custom role 拡張 + soft-delete

- `(tenant_id, project_id, role_id)` で scope
- soft-delete (`deprecated_at`) のみ、HARD DELETE は ADR Gate Criteria #8 (破壊的操作)
- `agent_runs.role_id='deprecated_role'` の既存 child run は AgentRun 完了まで読み取り可、新規 dispatch は service layer reject
- max_custom_roles per tenant (default 50、tenant_config override 可、絶対上限 ≤200)

### §6: 実装 Sprint と対象ファイル

- SP-013 (table seed + 標準 10 + 5+ source)、SP-017 (frontend viewer)
- `backend/app/db/models/{project_agent_role,standard_role_mirror}.py` / `backend/app/domain/agent_role/{taxonomy,extension}.py` / `backend/app/api/v1/agent_roles.py` / `tests/multi_agent/test_role_taxonomy_enum.py` / `frontend/app/(admin)/agent-roles/page.tsx` (SP-017)

### §7: テスト指針

- 5+ source 整合 test
- reserved namespace test (custom で `orchestrator` 等 reject)
- soft-delete + 既存 child run の参照保護
- cross-tenant + cross-project role reference reject
- role_scope CHECK fail-closed (PD-R3-F-007 / PD-R4-F-002)

## リスク

| リスク | 軽減 |
|---|---|
| recommended_action_class 列の暗黙追加 | DDL に列なし、code review で reject |
| custom role 暴走 | max_custom_roles 上限 |
| role HARD DELETE 試行 | ADR Gate Criteria #8 + service layer + STANDARD mirror trigger |

## rollback

- SP-013 migration rollback: `alembic downgrade -1`
- custom role 暴走: tenant_config で `custom_role_enabled=false`
- standard role drift: `STANDARD_ROLE_IDS_MIRROR` を migration で再 seed (idempotent)

## 関連

- ADR-00014 (Multi-Agent Orchestration Foundation)
- Phase C draft §C-1
