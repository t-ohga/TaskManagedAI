---
id: "SP-011-5_operational_hardening"
type: "heavy"
status: "draft"
sprint_no: 11.5
created_at: "2026-05-13"
updated_at: "2026-05-13"
target_days: 5.4
max_days: 7
adr_refs:
  - "[ADR-00003](../adr/00003_api_contract.md) # accepted、Sprint 11.5 batch 0 で /metrics Prometheus exporter endpoint 追加 update note を append (2026-05-17)"
  - "[ADR-00006](../adr/00006_secrets_management.md) # accepted、rotation drill 完成で update"
  - "[ADR-00007](../adr/00007_external_exposure.md) # accepted、private staging Tailscale GitHub Action 確認"
  - "[ADR-00008](../adr/00008_destructive_operation.md) # accepted、rotation drill destructive operation invariant"
  - "[ADR-00011](../adr/00011_github_app_permission_matrix.md) # Sprint 11 で 7/8 unblock review、frontmatter proposed 維持。本 Sprint で BL-Permission-CLI 完成 + 8/8 unblock 達成後に accepted 昇格 (Codex R1/R2/R3 adopt)"
planned_adr_refs: []
related_sprints:
  - "SP-009_p0_ui_pack # carry-over BL-0109a/0110a"
  - "SP-011_eval_harness # ADR-00011 carry-over BL-Permission-CLI"
  - "SP-012_p0_acceptance # P0 Exit verify"
upstream_sprints:
  - "SP-009_p0_ui_pack"
  - "SP-011_eval_harness"
downstream_sprints:
  - "SP-012_p0_acceptance"
risks:
  - "observability stack 起動失敗 (docker-compose profile observability の resource 不足)"
  - "secret rotation drill で active secret_ref を誤って revoke (rollback path 必須)"
  - "a11y axe-core violation 残 (skeleton UI で WCAG 違反 0 達成困難)"
  - "responsive 768/1024/1440px viewport で layout 破壊 (skeleton UI で Tailwind grid 未調整)"
  - "audit export で raw secret 混入 (redaction enforcement 漏れ)"
---

このテンプレの使い方: ADR Gate Criteria #5 MCP/tool 権限 (Observability tool 追加) + #6 Secrets 管理 (rotation drill) + #7 外部公開 (private staging Tailscale) に該当する Sprint。Sprint 0 で defer した運用基盤を P0 Exit 直前で本格化する + Sprint 9 a11y / responsive carry-over + Sprint 11 ADR-00011 BL-Permission-CLI carry-over。

最終更新: 2026-05-13

## 目的

### 本来 scope (Observability、10 BL)

- OpenTelemetry / Prometheus / Loki / Grafana dashboard
- alerting (approval / run_failed / budget_exceeded)
- private staging Tailscale GitHub Action + WAL archiving / PITR prep
- secret rotation drill (rotation 状態遷移 `pending -> active -> deprecated -> revoked`)
- audit export (raw secret 除外 invariant の export-time enforcement)
- `payload_data_class` / `allowed_data_class` dimension on Prometheus metrics

### Sprint 9 carry-over (2 BL)

- BL-0109a: responsive mobile-first design (Tailwind grid + 768/1024/1440px Playwright viewport test)
- BL-0110a: a11y axe-core integration test (WCAG 2.1 AA 違反 0)

### Sprint 11 carry-over (1 BL)

- BL-Permission-CLI: GitHub API current permissions fetch + CI workflow integration (ADR-00011 acceptance condition、final blocker)

## 背景

- Sprint 0 (Bootstrap) で defer した OTel / Prometheus / Loki / Grafana を P0 Exit 直前で本格化 (PRD-01 §運用 / NF-007 / NF-011)
- SP-009 P0 UI Pack の audit (2026-05-13) で responsive / a11y carry-over を defer (BL-0109a / BL-0110a)
- ADR-00011 (本 Sprint 末で accepted 化、Sprint 11 末は 7/8 unblock review のみ) の最後の blocker として BL-Permission-CLI が必要 (CI workflow + GitHub API current permissions fetch、Codex R1 F-R1-004 + R2 F-R2-001 adopt)
- Sprint 12 P0 Acceptance で AC-HARD-04 backup/restore RPO≤24h を verify する前に、WAL archiving + PITR drill prep が必要

## 対象外

- SLO 自動化 (P1 へ defer)
- production-grade alerting (PagerDuty / Opsgenie 等、SP-022 で検討)
- Loki retention policy 最適化 (OQ-C-09、Sprint 11.5 で default 7 日 / 30 日 cost-aware)
- ContextSnapshot retention TTL 最適化 (OQ-C-11、SP-022 で検討)

## 設計判断

- **Observability stack は docker-compose profile 経由** (`--profile observability`): default 起動には含めず、Sprint 11.5 で profile off / on を選択可能。
- **OTel auto-instrument**: FastAPI + arq + httpx + SQLAlchemy + Redis を default 自動計装、custom span は cost / approval / runner emit。
- **Prometheus exporter**: `/metrics` endpoint を api / worker 双方で expose、scrape interval 15s。
- **Loki promtail**: container stdout / stderr を JSON parse、`tenant_id` / `actor_id` / `run_id` / `trace_id` / `payload_data_class` を label 化 (cardinality 制御のため `actor_id` は hash prefix 8-char で labelize)。
- **Grafana dashboard**: Hard Gates 7 + KPIs 5 + Provider Compliance + SecretBroker + Runner / RepoProxy / Approval / Audit の 6 panel 構成。
- **secret rotation drill**: dry-run mode (rotation flow を実 secret 値変更なしで simulate) + real rotation (旧 secret_ref を `deprecated` → `revoked`、新 secret_ref を `pending` → `active`)。rollback path として旧 secret_ref を `active` に復元する `taskhub secret rollback-to-version` command。
- **audit export redaction enforcement**: export 時に Pydantic schema で raw secret pattern hit を検出、hit 時は export reject (raw value を export しない invariant)。
- **payload_data_class dimension**: Prometheus histogram labels に `payload_data_class` / `allowed_data_class` / `effective_allowed_data_class` を追加、cardinality は 4 値 × 4 値 × 4 値 = 64 (controlled)。
- **a11y / responsive carry-over**: SP-009 skeleton UI を responsive grid に refactor (Tailwind `md:` / `lg:` / `xl:` breakpoint)、axe-core で WCAG 2.1 AA 違反 0 を Playwright で enforce。
- **BL-Permission-CLI carry-over**: GitHub API `/app/installations/{id}/access_tokens` で current permissions fetch、`config/github_app_permissions.toml` と diff、unknown overreach は fail-closed。CI workflow に `gh api ... | jq` + Python diff check 組み込み。

## 実装チケット

### batch 0: OTel + Prometheus base (正本 BL ID = PLAN-01)

| BL ID | 内容 | depends_on |
|---|---|---|
| BL-0131 | API / worker / runner の OTel instrumentation (auto-instrument FastAPI + arq + httpx + SQLAlchemy + Redis、custom span: cost / approval / runner emit) | BL-0008, BL-0093 |
| BL-0132 | Prometheus metrics exporter (`/metrics` endpoint + scrape target) | BL-0131 |

### batch 1: Loki + Grafana

| BL ID | 内容 |
|---|---|
| BL-0133 | Loki JSON log shipping + promtail config + label (tenant_id / actor_id hash / run_id / trace_id / payload_data_class) + redaction enforcement |
| BL-0134 | Hard Gates / Quality KPI Grafana dashboard (KPI metric は Sprint 12 BL-0164/0165 で生データ取得後に dashboard へ反映、本 Sprint では metric contract と dashboard skeleton 整備) |

### batch 2: Alerting + private staging

| BL ID | 内容 |
|---|---|
| BL-0135 | alerting route を In-App Notification に接続 (approval pending > 4h / budget exceeded / run_failed spike / secret rotation deferred) |
| BL-0136 | Tailscale GitHub Action private staging path 本運用化 (`tag:taskhub-ci` + ephemeral auth key + job 終了後 cleanup + Loki log masking + TCP/443 限定) |

### batch 3: WAL / PITR + secret rotation + audit export

| BL ID | 内容 |
|---|---|
| BL-0137 | WAL archiving / PITR prep (AC-HARD-04 source for SP-012 BL-0144) |
| BL-0138 | secret rotation drill (dry-run + real-rotation + rollback path) + canary preflight 統合 (AC-HARD-02 trace) |
| BL-0139 | audit export JSON Lines daily job (raw secret 除外 invariant の export-time enforcement) + `secret_capability_revoked` event |
| BL-0156 | audit / OTel / Loki に `payload_data_class` と `allowed_data_class` を別 dimension で記録 (合算の `data_class` 単一 dimension で代替しない) |
| BL-0159b | `backup_restore_rpo_rto` fixture を WAL archiving / PITR backup で activate (Sprint 11 BL-0159 で skeleton、本 Sprint で activation) |

### batch 4: Sprint 9 carry-over (a11y / responsive、2 BL)

| BL ID | 内容 |
|---|---|
| BL-0109a | responsive mobile-first design (Tailwind grid + 768/1024/1440px Playwright viewport test) |
| BL-0110a | a11y axe-core integration test (WCAG 2.1 AA 違反 0) |

### batch 5: ADR-00011 carry-over (Permission CLI、1 BL)

| BL ID | 内容 |
|---|---|
| BL-Permission-CLI | GitHub API current permissions fetch (`/app/installations/{id}/access_tokens`) + CI workflow integration + Permission Matrix diff check + unknown overreach fail-closed (Rule 3、Sprint 9 audit R2-F-001 で確立済) |

## タスク一覧

- [ ] batch 0: BL-0131 OTel + BL-0132 Prometheus
- [ ] batch 1: BL-0133 Loki + BL-0134 Grafana dashboard skeleton
- [ ] batch 2: BL-0135 Alerting + BL-0136 private staging Tailscale GitHub Action
- [ ] batch 3: BL-0137 WAL/PITR + BL-0138 rotation drill + BL-0139 audit export + BL-0156 data_class dimension + BL-0159b PITR activation
- [ ] batch 4: BL-0109a responsive + BL-0110a a11y
- [ ] batch 5: BL-Permission-CLI (ADR-00011 acceptance carry-over)
- [ ] Sprint Exit: ADR-00006 update accepted + **ADR-00011 accepted 化** (Sprint 11 末で 7/8 unblock review + BL-Permission-CLI 完成で 8/8 全件 unblock 達成) + Sprint Pack ## Review

## must_ship / defer_if_over_budget 対応表 (Codex R1 F-R1-014 adopt: P0 blocker / P0 operational minimum / P0.1 stretch を分離)

### P0 blocker (P0 Exit 判定に直結、defer 不可)

| 項目 | depends_on |
|---|---|
| BL-0131 OTel instrumentation (Hard Gates / KPI metric 計測の基盤、SP-012 BL-0148 prerequisite) | — |
| BL-0132 Prometheus metrics exporter | BL-0131 |
| BL-0137 WAL archiving / PITR prep (AC-HARD-04 source) | BL-0009 |
| BL-0138 secret rotation drill (AC-HARD-02 trace) | BL-0004, BL-0089 |
| BL-0139 audit export raw secret 除外 enforcement (AC-HARD-02) | BL-0025, BL-0133 |
| BL-0156 payload_data_class / allowed_data_class dimension (DD-04 invariant) | BL-0131 |
| BL-0159b backup_restore_rpo_rto fixture activation (AC-HARD-04 PITR) | BL-0137, BL-0159 |
| BL-0110a a11y axe-core (WCAG 2.1 AA 違反 0、AC-KPI-03 / Sprint 9 carry-over) | — |
| BL-Permission-CLI ADR-00011 acceptance condition (Sprint 11 末で 7/8 unblock → 本 Sprint で 8/8 unblock + accepted) | — |

### P0 operational minimum (運用品質の最小ライン)

| 項目 | defer_if_over_budget |
|---|---|
| BL-0133 Loki JSON log shipping + redaction | retention policy 最適化は SP-022 |
| BL-0134 Grafana dashboard skeleton (Hard Gates / KPI panel) | dashboard panel 数の増減は SP-022 |
| BL-0135 alerting route → In-App Notification 接続 | advanced alert routing (PagerDuty 等) は SP-022 |
| BL-0136 private staging Tailscale GitHub Action | 詳細な job permission rotation は SP-022 |
| BL-0109a responsive 768/1024/1440px design | smaller viewport (< 768px) は SP-022 |

### P0.1 stretch (defer 可、SP-022 or P1 へ)

| 項目 | defer |
|---|---|
| SLO 自動化 | P1 |
| production-grade alerting (PagerDuty / Opsgenie 等) | SP-022 |
| Loki retention policy 最適化 (7 日 / 30 日 cost-aware) | SP-022 |
| ContextSnapshot retention TTL 最適化 (OQ-C-11) | SP-022 |
| Grafana panel 詳細 drill-down | SP-022 |

## 受け入れ条件

- 14 BL すべて Codex multi-round で `verdict=clean` (BL-0131〜0139 + BL-0156/0159b + BL-0109a/0110a + BL-Permission-CLI)
- **ADR-00011 (GitHub App Permission Matrix) accepted 化** (Sprint 11 7/8 unblock review + 本 Sprint BL-Permission-CLI 完成で 8/8 全件 unblock 達成)
- Grafana dashboard で AC-HARD 7 + AC-KPI 5 + Provider Compliance + SecretBroker + Runner / RepoProxy / Approval / Audit が可視化
- secret rotation drill が dry-run + real-rotation 双方で成功 (旧 secret_ref `active` → `deprecated` → `revoked`、新 `pending` → `active`)
- audit export で raw secret pattern hit 時 export reject
- private staging CI で 全 contract test + E2E full suite PASS
- a11y axe-core WCAG 2.1 AA 違反 0
- responsive 768/1024/1440px viewport で layout 破壊なし (Playwright)
- BL-Permission-CLI で GitHub API current permissions と `config/github_app_permissions.toml` の diff check、unknown overreach fail-closed

## 検証手順

```bash
# Observability stack
docker compose --profile observability up -d
curl -s http://localhost:9090/metrics | grep -E 'agent_runs_total|payload_data_class|effective_allowed_data_class'
curl -s http://localhost:3000/api/datasources | jq
curl -s http://localhost:3100/ready  # Loki

# alerting
curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[].rules[] | select(.alert)'

# private staging CI/E2E
gh workflow run private-staging-e2e
gh run watch

# WAL / PITR
uv run python -m backend.scripts.wal_archiving_check
uv run pytest tests/deploy/test_wal_pitr_prep.py -q

# secret rotation drill (dry-run)
uv run python -m backend.scripts.secret_rotation_drill --dry-run
# real rotation (drill 用 secret のみ)
uv run python -m backend.scripts.secret_rotation_drill --execute --secret-ref secret://sops/p0/test_rotation#v1
uv run pytest tests/secrets/test_rotation_state_transition.py -q

# audit export
uv run python -m backend.scripts.audit_export --start 2026-05-01 --end 2026-05-13 --output /tmp/audit-export.json
uv run pytest tests/audit/test_audit_export_redaction.py -q  # raw secret pattern hit reject

# a11y / responsive
cd frontend && pnpm exec playwright test --grep '@a11y|@responsive'
cd frontend && pnpm exec axe http://localhost:3000/admin/tickets --rules wcag2aa,wcag21aa

# BL-Permission-CLI
uv run python -m backend.app.services.repoproxy.permission_matrix --check \
              --current-permissions-json $(gh api /app/installations/<id>/access_tokens | jq .permissions)

# lint / type / test (regression)
uv run mypy backend
uv run ruff check backend tests
uv run pytest -q
cd frontend && pnpm exec tsc --noEmit && pnpm exec eslint . --max-warnings=0
```

## レビュー観点

- Prometheus label cardinality 制御 (`actor_id` は hash prefix 8-char、`tenant_id` は raw OK)
- Loki log shipping で raw secret が log line に出ない (Sprint 5.5 redaction との 2 重防御)
- Grafana dashboard で Hard Gates / KPIs threshold violations が alert rule と integration
- secret rotation drill が rollback path で旧 secret_ref を `active` 復元可能
- audit export redaction が export 時に Pydantic schema で pattern hit reject (export-time invariant)
- a11y skeleton UI で WCAG 2.1 AA 違反 0 (focus order / contrast / aria-label / heading hierarchy)
- responsive 768/1024/1440px viewport で Sprint 9 5 page (Ticket / Approval / Run / Audit / Settings) すべて layout 破壊なし
- BL-Permission-CLI が unknown permission overreach を fail-closed (Rule 3、Sprint 9 audit R2-F-001 で確立済)
- private staging が Tailscale 内のみ、Funnel / Cloudflare 不使用

## Rollback (per batch)

- batch 0 失敗 (OTel + Prometheus): docker-compose profile observability off で revert、Sprint 12 で SP-012 BL-0148 計測の前提条件 unmet → SP-012 で再 try
- batch 1 失敗 (Loki + Grafana): log shipping 停止、container stdout direct read fallback、dashboard skeleton 削除
- batch 2 失敗 (Alerting + private staging): notification は既存 In-App のみ、private staging は manual `gh run` 経路で代替
- batch 3 失敗 (WAL/PITR + rotation drill + audit export): WAL archiving disable で daily backup のみ、rotation drill skip で existing secret 維持、audit export は manual SQL dump で代替
- batch 4 失敗 (a11y + responsive): WCAG 2.1 AA 違反を SP-022 へ defer (warning 表示)、responsive は desktop-only で SP-022 で改善
- batch 5 失敗 (BL-Permission-CLI): ADR-00011 acceptance を SP-012 へ defer、SP-012 で BL-Permission-CLI 完成 + accepted 化

## Audit Event

新規 event_type / metric (Sprint 11.5 で追加):

- `secret_capability_revoked` (BL-0139、secret rotation drill での旧 secret_ref revoke)
- `wal_archive_rotated` (BL-0137、WAL archiving 完了)
- `pitr_drill_executed` (BL-0159b、PITR drill 完了)
- `axe_violation_detected` (BL-0110a、Playwright a11y test 失敗、CI gate)
- `permission_matrix_drift` (BL-Permission-CLI、GitHub API current permissions と config drift 検出)

audit_events payload に必須 field: `tenant_id` / `actor_id` / `run_id?` / `secret_ref_id?` / `provider?` / `trace_id` / `correlation_id` / `gateway_kind?` / `timestamp` + `payload_data_class` / `allowed_data_class` 別 dimension (BL-0156)。raw secret pattern hit は **pattern 種別 + sha256 16-char prefix のみ** 記録 (AC-HARD-02 invariant 維持)。

## 残リスク

- **Observability stack resource (MEDIUM)**: docker-compose profile observability で Loki / Grafana / Prometheus の resource 不足 (Mac 8 GiB RAM 環境)。docker-compose profile を default off で Sprint 11.5 でのみ on、SP-012 で host migration 時に VPS 側で常時 on 想定。
- **secret rotation drill 誤 revoke (CRITICAL)**: active secret_ref を誤って revoke すると provider call 全停止。dry-run mode + real-rotation 前の `--confirm` 必須、rollback path で旧 secret_ref を `active` 復元可能。
- **a11y axe-core violation 残 (MEDIUM)**: skeleton UI の placeholder text / heading hierarchy / aria-label 不足、Sprint 11.5 で実 backend route 結線時に再 audit。
- **audit export raw secret 混入 (HIGH)**: Sprint 5.5 redaction + audit_export redaction の 2 重防御、ただし新 secret pattern (新 provider 追加) で漏れる可能性 → Sprint 11.5 で pattern registry を Provider Compliance Matrix と同期。

## 次スプリント候補

- Sprint 12 (P0 Acceptance) — P0 Exit 判定

## 関連 ADR

- ADR-00006 (Secrets management) — rotation drill 完成で update
- ADR-00007 (External Exposure) — private staging Tailscale GitHub Action 確認 (host 中立 invariant 維持)
- ADR-00008 (Destructive Operation) — rotation drill destructive operation invariant update
- ADR-00011 (GitHub App Permission Matrix) — BL-Permission-CLI carry-over で final acceptance condition (8/8 blocker 全件解消)、本 Sprint 末で accepted 昇格

## Review

### batch 1 (BL-0133 Loki + BL-0134 Grafana dashboard skeleton / 2026-05-17 session)

#### Changed
- `backend/app/observability/logging.py` 新規 (JsonLinesFormatter + setup_logging + LogRecordFactory injection + `_payload_secret_scan` 経由 raw secret reject)
- `tests/observability/test_structured_logging.py` 新規 (14 件、JSON format / label injection / actor_id_hash / raw secret reject / idempotent setup)
- `docker-compose.observability.yml` 新規 (profile `observability`、Loki + Grafana + promtail + Prometheus services、全 127.0.0.1 bind)
- `config/observability/loki.yml` (retention 7 day、`LOKI_RETENTION_PERIOD` env で override)
- `config/observability/promtail.yml` (Docker socket scrape + JSON parse + 5 label extract)
- `config/observability/prometheus.yml` (api/worker/loki/self scrape)
- `config/observability/grafana/grafana.ini` (anonymous Viewer、disable embedding/external snapshot/analytics)
- `config/observability/grafana/datasources/{loki,prometheus}.yml` (provisioning、`editable: false`)
- `config/observability/grafana/dashboards/provisioning.yml` (`allowUiUpdates: false`)
- `config/observability/grafana/dashboards/taskmanagedai-overview.json` 新規 (6 row skeleton: Hard Gates 7 / Quality KPIs 5 / Provider Compliance 3 別 dimension / SecretBroker logs / Runner+RepoProxy gateway_kind 分離 / Approval+Audit)
- `backend/app/main.py`: `setup_logging("api")` を `setup_otel` より先に call
- `backend/app/workers/main.py`: `setup_logging("worker")` を `on_startup` 先頭で call
- `backend/app/observability/__init__.py`: logging API re-export (setup_logging / JsonLinesFormatter / LOKI_LABEL_FIELDS / hash_actor_id / reset_logging_state)

#### Verified
- BL-0133 acceptance: JSON Lines log shipping + 5 label (tenant_id / actor_id_hash / run_id / trace_id / payload_data_class) + raw secret reject single source ✅
- BL-0134 acceptance: Grafana dashboard skeleton 6 panel (Hard Gates / KPI / Provider Compliance / SecretBroker / Runner+RepoProxy / Approval+Audit)、生データ bind は Sprint 12 BL-0164/0165 ✅
- deny-by-default: 全 service 127.0.0.1 bind / Tailscale 内のみ / Grafana anonymous Viewer ✅
- SecretBroker boundary: `_payload_secret_scan` single source 継承 (batch 0 と同)、raw secret は emit 前 reject ✅
- Provider Compliance 3 dimension: dashboard panel で `payload_data_class` / `allowed_data_class` / `effective_allowed_data_class` 別 dimension 明示、合算禁止 ✅
- cardinality 制御: `actor_id` raw 不可、8-char hex hash prefix のみ (`actor_id_hash` field)、`hash_actor_id` helper ✅
- plan-reviewer R1 → READY (0 BLOCKER / 0 HIGH / 3 MEDIUM cosmetic / 2 LOW、本 batch 内 inline 対応) ✅
- local verification: pytest tests/observability/ → **55 passed** (前 41 + 新規 14) / pytest tests/ → **2960 passed + 348 skipped** (regression なし) / mypy 206 source files clean / ruff clean ✅

#### Deferred (batch 2+ / Sprint 11.5 後続)
- alerting routes (approval pending > 4h / budget exceeded / run_failed spike) → **batch 2 (BL-0135)**
- private staging Tailscale GitHub Action → **batch 2 (BL-0136)**
- WAL/PITR + secret rotation drill + audit export → **batch 3 (BL-0137/0138/0139/0156/0159b)**
- a11y / responsive (Sprint 9 carry-over) → **batch 4 (BL-0109a/0110a)**
- BL-Permission-CLI (ADR-00011 acceptance carry-over) → **batch 5**
- KPI metric 生データ bind to dashboard panel → **Sprint 12 BL-0164/0165**
- worker `/metrics` endpoint (本 batch では prometheus scrape skip、batch 2+ で追加可)
- production-grade alerting (PagerDuty 等) → SP-022
- Loki retention 7 day → 30 day 最適化 → SP-022

#### Risks
- **resource impact**: Loki + Grafana + Prometheus + promtail で +500MB-1GB RAM。`--profile observability` off で resource 不要。
- **promtail Docker socket scrape**: rootless Docker / Podman で privilege 問題、Mac dev では `/var/run/docker.sock` perm 確認必須 (Sprint 12 host migration drill で final verify)。
- **Grafana provisioning drift**: `editable: false` + `allowUiUpdates: false` で UI 編集を block、ファイル更新のみで dashboard 更新可能。
- **runtime overhead measurement (batch 0 L-2)**: 引き続き batch 2 で perf measurement 必須 (本 batch では未測定)。

#### SP-011-5 受け入れ条件 contribution
- line 178 (14 BL すべて Codex multi-round clean): BL-0133 + BL-0134 はこの PR (累計 **4/14**)
- line 180 (Grafana dashboard で AC-HARD/KPI visualisation): **dashboard skeleton 達成** (生データ bind は Sprint 12)
- must_ship table P0 operational minimum line 160-161: BL-0133 + BL-0134 **達成** (skeleton)

### batch 0 (BL-0131 OTel + BL-0132 Prometheus / 2026-05-17 session)

#### Changed
- `pyproject.toml`: opentelemetry-api/sdk/exporter-otlp-proto-grpc + opentelemetry-instrumentation-{fastapi,httpx,sqlalchemy,redis} (pin `<0.52`) + prometheus-client (`<1.0`) 追加
- `backend/app/observability/__init__.py` 新規 (public re-exports)
- `backend/app/observability/config.py` 新規 (`ObservabilitySettings` + `ALLOWED_METRICS_BIND_NETWORKS`)
- `backend/app/observability/otel.py` 新規 (TracerProvider + auto-instrument 5 + custom span helpers + `_payload_secret_scan` import で redaction single source)
- `backend/app/observability/prometheus.py` 新規 (`PrometheusRegistry` + `/metrics` route helper + `PrometheusMetricsAccessGuard` middleware + 3 別 data class dimension)
- `backend/app/main.py`: `setup_otel("api")` + `setup_prometheus()` + `/metrics` mount + `PrometheusMetricsAccessGuard` middleware
- `backend/app/workers/main.py`: `setup_otel("worker")` (FastAPI instrumentor skip)
- `tests/observability/` 4 file 新規 (`test_otel_setup.py` 14 件 / `test_prometheus_metrics.py` 14 件 / `test_data_class_dimension.py` 9 件 + `__init__.py`、計 37 件 PASS)
- `docs/adr/00003_api_contract.md`: `## Sprint 11.5 batch 0 update note` section append (`/metrics` endpoint contract、break-glass #3 対象外で実装着手前 accepted)
- `docs/sprints/SP-011-5_operational_hardening.md`: adr_refs に ADR-00003 追加 + 本 ## Review batch 0 section

#### Verified
- BL-0131 acceptance: OTel TracerProvider + auto-instrument (FastAPI / httpx / SQLAlchemy / Redis) + 3 custom span helpers (cost / approval / runner) ✅
- BL-0132 acceptance: Prometheus `/metrics` endpoint + 5 metric definitions + IP allowlist 2 layer 防御 (127.0.0.0/8 + ::1/128 + 100.64.0.0/10) ✅
- deny-by-default (`core.md §6`): 127.0.0.1 bind + middleware IP allowlist で production 0.0.0.0 regression 防御 ✅
- SecretBroker boundary: span attribute / metric label / description に raw secret 含めない、`_payload_secret_scan` single source (AC-HARD-02 整合) ✅
- Provider Compliance 3 dimension: `payload_data_class` / `allowed_data_class` / `effective_allowed_data_class` を別 label (合算禁止)、`DATA_CLASS_ORDINAL` ordinal 順序 5+ source 整合 ✅
- 5+ source enum integrity: `gateway_kind` (tool / runner) は `ai-output-boundary.md §9` source 整合 ✅
- plan-reviewer R1 → R2 READY (R1 全 8 件 adopt: H-1 IP allowlist + H-2 ordinal 5+ source + H-3 redaction single source + M-1 ADR-00003 update note + M-2 dependency pin `<0.52` + M-3 gateway_kind 5+ source + L-1 tests/__init__.py + L-2 runtime overhead measurement defer) ✅
- local verification: `uv run pytest tests/observability/ -q` → 37 passed / `uv run mypy backend` → 205 source files clean / `uv run ruff check backend tests` → All checks passed / `uv run pytest tests/ -q -x` → 2942 passed + 348 skipped (regression なし) ✅

#### Deferred (batch 1+ / Sprint 11.5 後続)
- `docker-compose.observability.yml` profile (Loki + Grafana skeleton 含む) → **batch 1 (BL-0133/0134)**
- alerting routes (approval pending > 4h / budget exceeded / run_failed spike) → **batch 2 (BL-0135)**
- private staging Tailscale GitHub Action 本運用化 → **batch 2 (BL-0136)**
- WAL/PITR + secret rotation drill + audit export → **batch 3 (BL-0137/0138/0139/0156/0159b)**
- a11y / responsive (Sprint 9 carry-over) → **batch 4 (BL-0109a/0110a)**
- BL-Permission-CLI (ADR-00011 acceptance carry-over) → **batch 5**
- **runtime overhead perf measurement** (5-10% production 実測例、本 batch では deferred、L-2 adopt) → **batch 1**
- KPI metric の生データ取得は **Sprint 12 BL-0164/0165 (AC-KPI-01〜05 final verify)** で完成、本 batch は metric contract + emit foundation のみ

#### Risks
- **dependency pin `<0.52`**: opentelemetry-instrumentation-* は beta `0.51b0` のため、stable 1.x への upgrade 時に API 変更可能性 → batch 1 で re-evaluation
- **runtime overhead (L-2)**: production 環境で 5-10% 実測の community report、本 batch では measurement deferred、batch 1 で perf measurement 必須
- **GitHub Actions CI billing infrastructure issue**: 前 Sprint 11 session 後半で全 CI job 1-3 秒即 fail 症状、本 batch では local pytest / mypy / ruff で同等 verification 済、CI 復旧は user 側で確認必要

#### SP-011-5 受け入れ条件 contribution
- line 178 (14 BL すべて Codex multi-round clean): BL-0131 + BL-0132 はこの PR (累計 2/14)
- line 180 (Grafana dashboard で AC-HARD/KPI visualisation): foundation 提供、dashboard 本実装は batch 1
- must_ship table P0 blocker line 146-147: BL-0131 + BL-0132 **達成**

(Sprint 11.5 全 batch 完遂時に親 summary を追記)
