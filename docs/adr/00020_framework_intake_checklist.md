---
id: "ADR-00020"
title: "Framework Intake Checklist: license / attribution / no embed / persistence / external network / telemetry / secret canary / tenant boundary 8 verify + scripts/ci/check_framework_intake.sh"
status: "accepted"
date: "2026-05-10"
updated_at: "2026-05-19"
authors:
  - "t-ohga"
related_sprints:
  - "SP-022_framework_intake_hardening"
related_research:
  - "Phase B-2 R-007 (Polyform Shield) + R-008 (full embed scope creep)"
  - "Phase E PE-F-010 (framework intake CI 機械化)"
# F-PLAN-R2-001 + F-ADV-R5-001 + F-005 + F-R2-002 adopt (master plan §10-§11 update PR #68 +
# SP022-T00 PR): 旧 acceptance_blocked_by ["ADR-00014/16 accepted", "P0 完了"] は SP022-T00 で
# 再解釈 + 削除。Framework Intake Checklist は P0 全体方針として独立 acceptable (CI 機械検査 +
# 8 verify item は multi-agent implementation に依存しない)、ADR-00014 (multi-agent
# orchestration) / ADR-00016 (hermes integration) の P0.1+ accepted を待たずに SP022-T00
# pre-implementation gate で simultaneous accept. acceptance_blocked_by key は accepted 後
# 削除 (status: accepted と active blocker key の同居を回避、F-005 + F-R2-002 adopt 一貫).
# 完了事実は acceptance_history に移送.
acceptance_target_sprint: "SP022-T00 pre-implementation gate (SP-022 着手 PR で acceptance 完了、master plan §10-§11 update PR #68 で acceptance lifecycle 正本化済、§1.3 / §5 整合)"
acceptance_history:
  - "2026-05-10: proposed (Phase B-2 R-007 Polyform Shield + R-008 full embed scope creep + Phase E PE-F-010 起票)"
  - "2026-05-19: accepted at SP022-T00 pre-implementation gate. 旧 acceptance_blocked_by ['ADR-00014/16 accepted', 'P0 完了'] は SP022-T00 で blocker 再解釈し削除 (Framework Intake Checklist は P0 全体方針として独立 acceptable、multi-agent ADR-00014/00016 から独立 accept、F-PLAN-R2-001 + F-005 + F-R2-002 adopt: status accepted と active blocker key の同居を回避). ADR-00021/00007 と simultaneous acceptance、common SP022-T00 gate trigger で promotion 完了."
---

最終更新: 2026-05-19 (SP022-T00 pre-implementation gate で accepted promotion、blocker 完全削除完了、ADR-00021/00007 と simultaneous acceptance)

## 背景

- 決定対象: 新 module / framework / external library 取り込み時の **machine-checkable checklist** を固定。本 ADR は 8 verify + CI script + violation reason_code を担保.
- ADR Gate Criteria #4 (AI 権限) + #5 (MCP/tool 権限) 並列 ADR-00010 (Provider intake).

## 採用案

### §1: 8 verify item (PE-F-010 fix で機械化)

| # | verify | machine check |
|---|---|---|
| 1 | License | source LICENSE / NOTICE 文字列 scan、Polyform Shield / RUS / 商用制限 license は deny |
| 2 | Attribution | `docs/citations/<framework>_adoption.md` に commit hash + file path + concept 説明を記録、CI で citation file 存在確認 |
| 3 | No code embed | `import <framework_module>` を CI で denylist、from-scratch 再実装のみ許容 |
| 4 | Persistence | 独自 SQLite / 独自 PostgreSQL connection を持ち込まない、CI で `import sqlite3` / `psycopg.connect` (TaskManagedAI 既存以外) denylist |
| 5 | External network | external API endpoint denylist (cloud SaaS の domain list)、CI で URL pattern scan |
| 6 | Telemetry off | telemetry endpoint denylist (sentry.io / datadog / honcho 等)、TaskManagedAI 既存 audit_events に統合 |
| 7 | Secret canary scan | memory store / retrieve / artifact 経路で provider-compliance §8 と同等の canary 実装、test fixture で fake API key deny verify |
| 8 | tenant/project boundary | DB 複合 FK + service layer 4 重防御、cross-tenant / cross-project negative test を fixture で全件 deny verify |

### §2: scripts/ci/check_framework_intake.sh

```bash
#!/usr/bin/env bash
# 新 dependency 追加時の framework intake checklist 機械検査
set -euo pipefail

CHANGED_DEPS=$(git diff --name-only origin/main...HEAD pyproject.toml uv.lock package.json pnpm-lock.yaml)
[ -z "$CHANGED_DEPS" ] && { echo "no dependency changes"; exit 0; }

# license scan
LICENSE_DENYLIST=("polyform-shield" "polyform-perimeter" "polyform-noncommercial" "rus license" "sspl")
# external API endpoint denylist
NETWORK_DENYLIST=("api.honcho.dev" "api.mem0.ai" "api.supermemory.ai" "sentry.io" "api.datadoghq.com")
# telemetry import denylist
TELEMETRY_DENYLIST=("sentry_sdk" "datadog" "newrelic" "honcho")

violations=()

# 1: license check (新 dependency の LICENSE / pypi metadata から)
for license_pattern in "${LICENSE_DENYLIST[@]}"; do
    if grep -ri "$license_pattern" "$(uv pip show <new_pkg> 2>/dev/null || true)" 2>/dev/null; then
        violations+=("license:$license_pattern")
    fi
done

# 3: import denylist
for module in "${TELEMETRY_DENYLIST[@]}"; do
    if grep -rE "^\s*(import|from)\s+$module" backend/app frontend src 2>/dev/null; then
        violations+=("telemetry_import:$module")
    fi
done

# 4: persistence (独自 SQLite 等)
if grep -rE "^\s*import\s+sqlite3" backend/app/{services,adapters,db} 2>/dev/null \
   | grep -v "tests/" 2>/dev/null; then
    violations+=("persistence:sqlite3")
fi

# 5: external network endpoint
for endpoint in "${NETWORK_DENYLIST[@]}"; do
    if grep -rE "https?://[^\"\s]*$endpoint" backend/app frontend src config 2>/dev/null; then
        violations+=("external_network:$endpoint")
    fi
done

# 2: citation file (新 dependency に対応する citation を要求)
# (実装は Sprint 22 で対応 framework list と照合)

if [ ${#violations[@]} -gt 0 ]; then
    echo "Framework intake violation:"
    printf '  %s\n' "${violations[@]}"
    exit 1
fi
echo "Framework intake checklist passed."
```

CI で `pull_request` event ごとに実行、violation 検出で fail.

### §3: violation reason_code

`framework_intake_violation_*` (license / attribution / code_embed / persistence / external_network / telemetry / secret_canary / tenant_boundary) を audit / CI failure log に記録.

### §4: ADR-00010 (Provider intake) との並列性

| ADR | 対象 |
|---|---|
| ADR-00010 | AI Provider 追加 (OpenAI / Anthropic / Gemini / Mock) の Compliance Matrix |
| ADR-00020 | 一般 framework / library 追加の intake checklist |

両 ADR は新 dependency 追加時に **両方** 通過必須 (Provider なら ADR-00010 + ADR-00020、それ以外は ADR-00020 のみ).

### §5: 適用 Sprint

- SP-022 (framework intake hardening、target 3/max 5 days、accepted 化 + CI script 完備)
- 既存 dependency に retrofit verify は SP-022 で実施

### §6: テスト

- `tests/scripts/test_check_framework_intake.sh` (positive: 違反 dependency で fail / negative: 安全 dependency で pass)
- `tests/citations/test_citation_completeness.py` (新 dependency のうち pattern adopted ものに citation file 存在)
- `eval/multi_agent/framework_intake_violation/` (各 violation 種別の fixture)

## リスク / rollback

| リスク | 軽減 |
|---|---|
| CI script の false positive | denylist tuning + exception 機構 (SP-022 で運用 review) |
| denylist 漏れ | 半年 1 回 license database / external API list を update + 半年 1 回 audit |
| citation 形骸化 | citation file の必須項目 (commit hash + file path + concept 説明) を Pydantic schema で validate |

rollback: CI script を maintenance mode (`exit 0` で skip)、半年内に強化版 deploy.

## 関連

- ADR-00010 / ADR-00016 / Phase E PE-F-010
- `docs/citations/hermes_pattern_adoption.md` (SP-018 着手時に作成)
