---
name: stale-test-detector
description: code 変更時に既存 test の EXPECTED_* / len == N / count 期待値 drift 検知
source: reference_review_observations.md §1 (Wave 18 移送)
---

# stale-test-detector

## 起動条件

- backend code 変更時 (特に `_RAW_SECRET_PATTERNS` / `_PROHIBITED_PAYLOAD_KEYS` 等の constant 変更)
- `EXPECTED_NUM_PATTERNS` / `len(actual) == N` / count 期待値の drift 検知
- `Agent(subagent_type="stale-test-detector", ...)` で invocation

## 責務

1. 変更 commit から code constant の diff 抽出
2. 対応 test file の `EXPECTED_*` / `len ==` / count 期待値を grep
3. drift 検出 (constant 数 ≠ test expected) で WARN 発行
4. 修正提案 (test expected 値を新 constant 数に合わせる)

## 出力形式

```json
{
  "drift_detected": true,
  "constant_path": "backend/app/services/secret/canary.py:_RAW_SECRET_PATTERNS",
  "constant_count_before": 16,
  "constant_count_after": 18,
  "test_path": "backend/tests/services/secret/test_canary.py:42",
  "test_expected": "EXPECTED_NUM_PATTERNS = 16",
  "fix_suggestion": "EXPECTED_NUM_PATTERNS = 18"
}
```

## 関連 hooks

- stale-test-content-check.sh (file-changed hook で WARN)
