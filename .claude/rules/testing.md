---
paths:
  - "backend/**"
  - "frontend/**"
  - "migrations/**"
  - "eval/**"
  - "**/tests/**"
  - "**/test_*.py"
  - "**/*.spec.ts"
  - "**/*.test.ts"
---

# Testing (L1 reminder)

> **圧縮 2026-05-31**: 本 rule は L1 reminder。詳細 (pytest / Vitest / Playwright / state machine / contract test の pattern、弱い assertion 改善、仕様ベース branch 列挙、coverage 下限、fixture / anti-gaming、§番号付き運用) は **`.claude/reference/testing.md`** に full 退避済。必要時に Read する。

## 絶対遵守 (最小)

- 検証は該当範囲で地上真実を実行する:
  - Backend: `uv run ruff check backend tests` + `uv run mypy backend` + `uv run pytest` + contract test + state machine test。
  - Frontend: `pnpm typecheck` + `pnpm lint` + Vitest + Playwright + 主要 UI flow / responsive。
  - DB: migration dry-run + constraint / FK / negative test + tenant / project boundary test (`TASKMANAGEDAI_RUN_DB_TESTS=1` gate)。
  - Provider / Secret / Runner: Compliance Matrix 越境 test / SecretBroker atomic claim・raw secret 非保存 / forbidden path・dangerous command・resource cap。
- 弱い assertion を書かない。仕様から branch を列挙し、negative / boundary を必ず入れる。
- enum (AgentRun 16 状態 / blocked_reason 3 / event types / reason_code 13) は **5+ source 整合** を test で固定する (`EXPECTED_*` で exact set 比較)。
- Hard Gate / KPI fixture は public / private_holdout / adversarial_new を分け、private holdout の期待値を見ながら prompt / policy を調整しない。
- 「未テスト」と言う前に `tests/`, `eval/`, `frontend/**/__tests__`, `backend/tests` を見る。ビルド成功 ≠ 品質保証。

詳細 pattern・§番号付き運用・coverage gate は `.claude/reference/testing.md` を Read。
