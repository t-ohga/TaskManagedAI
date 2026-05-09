---
name: cross-source-enum-audit
description: 任意の Literal enum (16 状態 / 22 events 等) の DB CHECK / ORM / Python / migration / test 5+ source drift detection
type: skill
source: feedback_taskmanagedai_invariants.md §1 (Wave 18 移送)
---

# cross-source-enum-audit

## 起動条件

- 新規 enum 追加 / 既存 enum 変更時
- Sprint Exit / PR 前で enum drift 確認
- `Skill(skill="cross-source-enum-audit", args="agent_run_status")` 等で invocation

## 監査範囲

| Source | 確認対象 |
|---|---|
| DB CHECK constraint | `migrations/*.py` の CheckConstraint |
| SQLAlchemy ORM | `backend/app/models/*.py` の CheckConstraint / Enum |
| Python Literal type | `from typing import Literal` 定義 |
| Pydantic | request/response model field validator |
| pytest fixture | `EXPECTED_*` constants / parametrized test |
| (frontend) | TypeScript enum (Sprint 9+) |

## drift 検出手順

1. 5+ source で enum を grep
2. 各 source から enum value set を抽出
3. exact name set 比較 (`set(actual) == set(expected)`)
4. 超過 / 不足とも reject、source ごとに具体的 line で報告

## 関連

- rules: `cross-source-enum-integrity.md` (本 skill の根拠)
- hook: `cross-source-enum-drift-check.sh` (file-changed 時に WARN)
- 実装フェーズ: 本 skeleton から content 充実は別 session で扱う
