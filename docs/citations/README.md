# Citations (Framework Pattern Adoption Ledger)

ADR-00020 (Framework Intake Checklist) §1 #2 Attribution の正本格納場所。

## Index

| File | 用途 |
|---|---|
| `framework_pattern_candidates.md` | 候補 framework 10 件の pattern adoption / PoC / 拒否判定 ledger (LangGraph / CrewAI / AutoGen / Semantic Kernel / Dapr Agents / Dify / Flowise / Letta / OpenHands / TaskingAI) |
| `dependency_to_framework_map.json` | PyPI / npm dependency 名 → canonical framework 名 mapping (CI gate `scripts/ci/check_framework_intake.sh` verify item #2 が参照) |

## 新 framework / dependency 追加時の SOP (SP022-T01)

1. **候補 ledger 更新**: `framework_pattern_candidates.md` の表に新 row 追加 (Framework / 種別 / 参考にする pattern / import 禁止項目 / 衝突 invariant / TaskManagedAI 対応 6 列)。`framework_canonical` 名は `| **<name>** |` 形式で書く (`dependency_to_framework_map.json` の `framework_canonical` field と exact match)。
2. **map 更新**: `dependency_to_framework_map.json` の `entries[]` に新 entry を追加。
   - `dependency_name`: PyPI は PEP 503 canonical (lowercase + `[-_.]+` → `-`)、npm は scoped name `@scope/name` をそのまま保持
   - `ecosystem`: `pypi` または `npm`
   - `framework_canonical`: `framework_pattern_candidates.md` 表 header と exact match
3. **PR 起票時の CI gate**: `scripts/ci/check_framework_intake.sh` (diff-gate mode) が 8 verify item を機械検査:
   - #1 License (PyPI のみ、`uv run python -m pip show` 経由)
   - #2 Attribution (本 map に entry なし → `framework_intake_violation_attribution`)
   - #3 No code embed (Python `import` + npm `from '@scope/name'` denylist)
   - #4 Persistence (`sqlite3` / `psycopg.connect`)
   - #5 External network (sentry.io 等 NETWORK_DENYLIST literal URL)
   - #6 Telemetry off (sentry_sdk / @sentry/node 等 import)
   - #7 Secret canary (preflight + tests/security fixture 存在確認)
   - #8 Tenant/project boundary (AC-HARD-03 marker 存在確認)

## 正本 docs

- ADR-00020 (`docs/adr/00020_framework_intake_checklist.md`): 機械検査仕様の正本
- SP-022 (`docs/sprints/SP-022_framework_intake_hardening.md`) SP022-T01 row: 本 CI gate の実装 sprint pack
- `.github/workflows/ci-smoke.yml` `backend-quality` job: CI step 統合点

## 緊急 disable (admin only)

CI gate を緊急 disable する必要がある場合は repository variable `FRAMEWORK_INTAKE_CHECK_DISABLED=1` を admin が設定。PR diff からは設定不可。使用時は 24h 以内に retro Pack 必須 (`docs/sprints/SP-022_framework_intake_hardening.md` `## Review` に disable 日時 / 理由 / 復旧 commit SHA 記録)。

## 改訂履歴

- 2026-05-19 SP022-T01 で本 index 起票 + `dependency_to_framework_map.json` 初期 entries (10 framework × 11 entries) 追加
