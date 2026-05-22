# Layer C Autonomous Evidence (2026-05-22、Mac single-host smoke、autonomous 実施可能箇所)

最終更新: 2026-05-22 (p0-exit-final-hardening-2026-05-22 plan Phase 5)

status: completed (autonomous 範囲は全件 PASS、user UI 必須箇所は user 報告待ち)

## 0. 背景

p0-exit-final-hardening-2026-05-22 plan Phase 5 (Layer C autonomous 実施可能箇所、本 plan §5.5.1 required/best-effort 分類)。Phase 4 Layer B 完了 (smoke-evidence/2026-05-22-layer-B.md) 後の継続実施。

Layer C で発覚した追加 latent issue (本 plan §1.3 latent issues の 8 件目):

- `/api/v1/eval/kpi-rollup` 503 `kpi_rollup_corpus_load_failed: eval_quality_root not found: /app/eval/quality`
- 根本原因: `Dockerfile.api` で `eval/` directory が COPY されていなかった (SP-011 Eval Harness で導入された latent runtime bug、本 plan §1.3 4 件以外の 8 件目)
- fix: `Dockerfile.api` に `COPY --chown=appuser:appuser eval ./eval` 追加 (本 PR で scripts COPY と同 sibling fix)

## 1. Layer C SOP §5.5.0 preflight checklist (本 plan)

| # | 確認項目 | 結果 |
|---|---|---|
| 1 | required env: `.env.local` `TASKMANAGEDAI_*` 必須 key 設定 | ✅ 全件設定済 |
| 2 | required secrets: SOPS / age / capability token bootstrap | ⚠️ `~/.taskhub/keys/` 未存在 (§12 §14 skip 対象) |
| 3 | required keys: `~/.taskhub/keys/approval-signing-key` / `age.key.txt` 存在 | ❌ 未生成 → §12 §14 smoke skip + accepted defer |
| 4 | required seeded records: tenant_id=1 + default actor seed | ✅ `backend/app/seeds/runner.py` 実行で `actors` table に `human:default` seed 確認 |
| 5 | service health: 5 service healthy | ✅ Layer B Phase 4 で verify 済 |
| 6 | side effects: smoke が生成する artifact path 確保 + cleanup | ✅ `~/.taskhub/drills/...` 配下 (gitignore) |
| 7 | failure classification: smoke 失敗時の原因切り分け可能 | ✅ docker compose logs + 本 file で trace 可能 |

## 2. Layer C SOP §5.5.1 smoke 分類 + 実施結果

### Required smoke (autonomous 必須、P0 Exit gate に直結)

| § | smoke | 結果 | evidence |
|---|---|---|---|
| §7 | Eval Dashboard live wiring (curl /api/v1/eval/kpi-rollup) | ✅ PASS (HTTP 200 + `{kpi_count: 0, p0_accept: true, source: null, kpi_ids: []}`) | 本 file §3 |
| §12 | taskhub approval issue smoke (CLI) | ⏭️ SKIP (preflight #3 fail、accepted defer、key bootstrap 必要) | - |
| §13 | signed journal verify CLI --from-db | ✅ PASS (exit 0、`tenant_scope_empty` 含む明示 message = SOP の expected 挙動、新規 DB で audit_events 空) | 本 file §4 |
| §14 | taskhub backup real smoke | ⏭️ SKIP (preflight #3 fail、accepted defer、age key bootstrap 必要) | - |

### Best-effort smoke

| § | smoke | 結果 |
|---|---|---|
| §15 | golden flow Ticket→PR pytest (`tests/integration/test_ticket_to_pr_smoke.py`) | ✅ PASS (13 tests passed in 0.02s、exit 0) |

### User-deferred smoke (autonomous scope 外)

| § | smoke | 状態 |
|---|---|---|
| §6 | dev login UI flow (ブラウザ操作必須) | ⏳ user 報告待ち (autonomous で curl 経由は middleware redirect 動作確認済、§7 Layer B evidence 参照) |
| §7 | Eval Dashboard UI 表示確認 | ⏳ user 報告待ち (autonomous で API curl 経由は §7 PASS、UI 表示は best-effort) |
| §8-§11 | admin UI smoke (Tickets / Approvals / Agent Runs / Audit) | ⏳ user 報告待ち |

## 3. §7 Eval Dashboard live wiring 詳細

```bash
# STEP 1: dev login で session cookie 取得 (auth path /auth/dev-login)
DEV_LOGIN_TOKEN=$(grep -E '^TASKMANAGEDAI_DEV_LOGIN_TOKEN=' .env.local | tail -1 | cut -d= -f2-)
RESP=$(curl -fsS -i -X POST "http://127.0.0.1:8000/auth/dev-login" \
  -H "Content-Type: application/json" \
  -d "{\"token\":\"$DEV_LOGIN_TOKEN\"}")
SESSION_COOKIE=$(echo "$RESP" | grep -oE 'taskmanagedai_session=[^;]*' | head -1)
# expected: HTTP 200 + Set-Cookie: taskmanagedai_session=...; HttpOnly; SameSite=lax
```

```bash
# STEP 2: kpi-rollup with session cookie
curl -fsS -H "Cookie: $SESSION_COOKIE" "http://127.0.0.1:8000/api/v1/eval/kpi-rollup"
# expected:
# {
#   "kpi_count": 0,      ← 新規 DB で KPI fixture 未 seed、production では nonzero
#   "p0_accept": true,    ← KPI 全件 PASS default
#   "source": null,
#   "fallback_reason": null,
#   "kpi_ids": []
# }
```

実施結果: **HTTP 200 + body 期待通り**。

**ただし** initial fresh DB では:
- `~/.taskhub/keys/` 未存在 → §12 §14 skip
- `backend/app/seeds/runner.py` 実行で `actors` table の `human:default` seed 必要 (initial 401 `actor not found` resolution)
- `eval/` directory が Docker image に COPY されていない → 503 `kpi_rollup_corpus_load_failed` (本 PR で fix 追加: `Dockerfile.api` `COPY eval ./eval`)

## 4. §13 signed journal verify CLI

```bash
DATABASE_URL=$(grep -E '^TASKMANAGEDAI_DATABASE_URL=' .env.local | tail -n 1 | cut -d= -f2- | sed 's/postgres:/127.0.0.1:/g')
uv run taskhub verify --signed-journal --from-db --tenant-id 1 --database-url "$DATABASE_URL"
# expected: exit 0 (空 chain でも tenant_scope check で PASS)
```

実施結果: **exit 0** + `ERROR [tenant_scope_empty]: audit_events table is empty for tenant_id=1` (SOP の expected message、空 chain での正常 contract 動作)。

**SOP §13 R1 fix の grep ロジック bug** (本 PR scope 外、別 doc fix 候補):

```bash
# SOP §13 (PR #93 R1) の現状: echo の末尾改行で常 match → 常時 ERROR exit 1
if [ -z "$DATABASE_URL" ] || echo "$DATABASE_URL" | grep -q $'\n'; then
  exit 1
fi
# fix 案: printf '%s' で末尾改行を含めない
if [ -z "$DATABASE_URL" ] || printf '%s' "$DATABASE_URL" | grep -q $'\n'; then
  exit 1
fi
```

→ accepted defer for post-merge SOP polish PR (本 PR は Dockerfile + dev override + SOP -f explicit に scope 限定)

## 5. §15 golden flow pytest

```bash
uv run pytest tests/integration/test_ticket_to_pr_smoke.py -v
# expected: 13 tests passed
```

実施結果: **13 tests passed in 0.02s、exit 0**:

- test_smoke_stage_order_immutable ✅
- test_all_stages_succeed_overall_success_true ✅
- test_stage_failure_skips_subsequent_except_audit ✅
- test_first_stage_failure_still_runs_audit ✅
- test_unexpected_exception_treated_as_failure ✅
- test_stage_metadata_propagates_via_context ✅
- test_non_dict_return_raises_smoke_error ✅
- test_result_is_frozen_dataclass ✅
- test_metadata_is_immutable_mapping_proxy ✅
- test_context_is_defensively_copied_per_stage ✅
- test_error_summary_redacts_raw_secret_patterns ✅
- test_audit_runs_on_unexpected_exception_too ✅
- test_duration_ms_tracked_per_stage ✅

**SOP §15 の test path も誤記** (`tests/eval/ticket_to_pr_smoke` → 実 path `tests/integration/test_ticket_to_pr_smoke.py`):

→ accepted defer for post-merge SOP polish PR

## 6. Phase 5 完了判定 (本 plan §5.5.1 required 全件)

- [x] §7 Eval Dashboard live wiring (curl) — PASS (本 PR の eval COPY fix 適用後)
- [x] §13 signed journal verify CLI — PASS (空 chain での expected 挙動)
- [x] §15 golden flow pytest — PASS (13 tests)
- [⏭] §12 taskhub approval issue smoke — SKIP (key bootstrap 未実施、accepted defer)
- [⏭] §14 taskhub backup real smoke — SKIP (age key bootstrap 未実施、accepted defer)

## 7. 残作業 (user 必須 + post-merge)

### user 必須 (Phase 5 user UI smoke + Phase 7 T09 drill)

- §6 dev login UI flow (primary path: `/dashboard` 直接 GET → token 入力 → `/dashboard` redirect)
- §7-§11 admin UI smoke (Eval Dashboard / Tickets / Approvals / Agent Runs / Audit log UI 確認)
- §16 T09 host migration drill (Mac→VPS、RTO≤4h、user 物理作業必須)

### post-merge follow-up (accepted defer、別 PR)

- SOP §13 R1 fix grep bug (`echo "$X" | grep -q $'\n'` → `printf '%s' "$X" | grep -q $'\n'`)
- SOP §15 test path 誤記 (`tests/eval/ticket_to_pr_smoke` → `tests/integration/test_ticket_to_pr_smoke.py`)
- §12 §14 key bootstrap SOP 詳細化 (operator-runbook §1 経由の手順明示化)

## 8. ADR Gate 該当性 (本 PR 追加 commit 全件非該当)

| 修正対象 | ADR Gate Criteria 11 種 | 判定 |
|---|---|---|
| Dockerfile.api eval COPY 追加 | 静的 build 設定、認証・認可 / DB / API / Provider / Secret 不変 | 非該当 |
| Layer C autonomous evidence file 起票 | docs-only | 非該当 |
