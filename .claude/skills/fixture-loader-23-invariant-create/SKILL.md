---
name: fixture-loader-23-invariant-create
description: Hard Gate / KPI fixture loader を Sprint 2 Batch 4 / Sprint 3 Batch 4 / Sprint 4 Batch 4 の 23 invariant pattern で生成
type: skill
source: feedback_taskmanagedai_invariants.md §5 (Wave 18 移送)
---

# fixture-loader-23-invariant-create

## 起動条件

- Hard Gate / KPI fixture (AC-HARD-01〜07 / AC-KPI-01〜05) の loader 作成時
- `Skill(skill="fixture-loader-23-invariant-create", args="AC-HARD-01")` 等で invocation

## 23 invariant pattern (Sprint 2/3/4 Batch 4 で確立)

各 fixture loader は次の 23 invariant を満たす:

1. dataset_version (versioned schema、append-only)
2. fixture kind (`public_regression` / `private_holdout` / `adversarial_new`)
3. expected_decision (allow / deny / blocked)
4. anti-gaming rule (private holdout 期待値漏洩防止)
5. parametrized test (pytest.mark.parametrize)
6. EXPECTED_* constants (5+ source 整合)
7. weak assertion 禁止 (toBeDefined / toBeTruthy etc 不可)
8. raw_secret_assert_no_raw (audit payload に raw secret 含まない)
9. structured error_code 検証 (string 検索ではなく enum 比較)
10-23. (省略、Sprint 2/3/4 batch 4 fixture から抽出)

## 出力

`backend/tests/fixtures/<ac_id>/loader.py` + `backend/tests/fixtures/<ac_id>/<kind>/*.json` skeleton

## 関連

- skill: `hard-gate-fixture-create` (Sprint 2 で確立、本 skill は loader pattern 担当)
- rules: `cross-source-enum-integrity.md`、`testing.md`
