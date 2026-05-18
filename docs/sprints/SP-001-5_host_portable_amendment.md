---
id: "SP-001-5_host_portable_amendment"
type: "heavy"
status: "proposed"
sprint_no: 1.5
created_at: "2026-05-10"
updated_at: "2026-05-18"
target_days: 2
max_days: 3
# F-PR67-010/011/013 P2 adopt (PR #67 R4): ADR-00021 acceptance 条件
# (host migration drill PASS) が master plan で明示、SP-012 では実機 drill
# 未達のため accepted 化不可. R3 で adopt した「SP-012 で accepted 化済 + 
# adr_refs 移動」を撤回、planned_adr_refs に restore. accepted 化 timestamp
# (旧 09:10:00Z は誤、両 ADR 側 00:30:00Z に back-date 後さらに撤回) は ADR
# 側 acceptance_history で記録.
adr_refs: []
planned_adr_refs:
  - "[ADR-00021](../adr/00021_host_portable_deployment.md) # SP-012 で skeleton 実装着手済だが accepted 化は SP-022 で実機 host migration drill PASS 後 (Criteria #2/#6/#7/#8)"
  - "[ADR-00007](../adr/00007_external_exposure.md) # host-portable invariant、ADR-00021 同期 accepted (SP-022 scope)"
related_sprints:
  - "SP-001_project_foundation (既完了、本 SP は amendment)"
  - "SP-012_p0_acceptance"
risks:
  - "PH-F-001 (ADR-00021 lifecycle)"
  - "PH-F-003 (`tm` CLI not yet available at SP-001)"
  - "PH-F-004 (ADR-00021 旧仕様撤回の正本化)"
---

最終更新: 2026-05-10

## 目的

既完了 SP-001 (project foundation) を **汚さずに** Host-Portable Deployment 関連の追加 must_ship を別 Sprint Pack として実施する amendment Sprint。Phase H PH-F-001 fix.

## 背景

- SP-001 は SUCCESS_WITH_FOLLOW_UP として既完了 (frontmatter status / Review 既存)
- ADR-00021 (host-portable) acceptance は SP-022 で実機 host migration drill PASS 後 (PR #67 R4 F-PR67-010/013/017 P2 adopt、本 SP-001.5 では skeleton 実装の参照 ADR として draft 状態で進行)
- `taskhub` admin CLI 最小実装 (init / backup / status) は既存 SP-001 の must_ship に **後付けで追加するのではなく**、本 SP-001.5 で独立に提供
- 既存 SP-001 完了時の docker-compose / FastAPI / migration / dev login flow はそのまま、host-portable 化のみ amendment

## 対象外

- SP-001 既完了内容の変更 (DB schema / API / frontend boundary 等は不変)
- `tm` user CLI (ADR-00015 / SP-016 の P0.1 範囲)
- `taskhub restore` / `migrate` / `age-rotate` / `verify --integrity` 本実装 (SP-012 の P0 完了 acceptance 範囲)
- multi-agent 機能 (P0.1 SP-013+)

## 設計判断

- **既完了 SP-001 を汚さない**: SP-001 frontmatter / Review section / must_ship list を変更しない、本 SP-001.5 で independent に新規 must_ship を提供
- **`taskhub` admin CLI を P0 で導入**: P0 期間中の Mac 起動運用 + Sprint 12 host migration drill の prerequisite
- **`tm` user CLI は P0.1 で初登場**: SP-001/SP-001.5 の smoke は `tm` を使わず、`taskhub status` + HTTP `/healthz` + `docker compose health` + `curl` ベース (PH-F-003 fix)
- **docker-compose.yml host-portable 化**: volume path env var、PostgreSQL/Redis image digest pinning、frontend service portable 化

## 実装チケット

- SP015-T01: docker-compose.yml host-portable 化 (PH-F-002 / PH-F-004)
  - PostgreSQL `postgres:16-alpine@sha256:<digest>` digest pinning
  - Redis `redis:7-alpine@sha256:<digest>` digest pinning
  - DB / Redis を Docker internal expose のみ (127.0.0.1 publish 撤回)
  - frontend (Next.js) service の `127.0.0.1:3000:3000` host bind + healthcheck
  - volume path を env var で吸収 (`${TASKHUB_DATA_DIR:-./data}`)
- SP015-T02: `cli/taskhub/` 最小実装
  - `cli/taskhub/main.py`
  - `cli/taskhub/commands/{init,backup,status}.py`
  - `cli/setup.py` (`taskhub` entry point、`uv tool install` 経由 install)
- SP015-T03: `docker-compose.override.yml.example` 雛形 (host-specific volume / sleep 制御 hint)
- SP015-T04: `.env.example` 整理 (env var で host 吸収)
- SP015-T05: `docs/deploy/host-setup.md` 雛形作成 (Mac / Linux / VPS の各 host SOP の構造化、本文の詳細は SP-012 で完成)
- SP015-T06: SP-001.5 smoke test (Mac 起動 verify、`tm` を使わない smoke、PH-F-003 fix)
- SP015-T07: ADR-00021 + ADR-00007 update accepted 化は **SP-022 carry over** (F-PR67-010/013/017 P2 adopt、acceptance 条件 = 実機 host migration drill PASS が SP-022 scope のため、SP-001.5 では skeleton 実装着手のみ進める)

## タスク一覧

- [ ] SP015-T01〜T07 を順次実装
- [ ] migration `00NN_host_portable_compose.py` (もしあれば、env var 関連) PASS
- [ ] Mac で `taskhub init` → `docker compose up -d` → `taskhub status` で smoke (`tm` を使わない、PH-F-003)
- [ ] image digest pinning verify (`postgres:16-alpine@sha256:<digest>` 形式)
- [ ] DB / Redis が Docker internal のみ expose verify (host から `nc 127.0.0.1 5432` で reject 確認)

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| docker-compose.yml host-portable + image digest pinning | ○ | - |
| `taskhub` CLI (init/backup/status) | ○ | - |
| frontend portable + healthcheck | ○ | - |
| DB/Redis internal-only expose | ○ | - |
| docs/deploy/host-setup.md 雛形 | ○ | 本文詳細は SP-012 で完成 |
| `tm` を使わない smoke (PH-F-003) | ○ | - |
| ADR-00021 + ADR-00007 update accepted | ✗ (SP-022 carry over) | F-PR67-010/013/017 P2 adopt: acceptance 条件 = 実機 host migration drill PASS が SP-022 scope、本 SP-001.5 は skeleton 実装着手のみ |
| SP-001 既完了内容変更 | × | (絶対変更しない) |

## 受け入れ条件

- ADR-00021 / ADR-00007 update は **proposed のまま** (SP-001.5 着手時 gate ではなく、acceptance は SP-022 で実機 drill PASS 後、F-PR67-017 P2 adopt)
- Mac で `taskhub init` → `docker compose up -d` → `taskhub status` の smoke が `tm` を使わずに成功
- image digest pinning が docker-compose.yml で固定、`postgres:16-alpine@sha256:<digest>`
- DB (`5432`) / Redis (`6379`) が host port で listen していない (Docker internal のみ)
- frontend (`127.0.0.1:3000`) が healthcheck PASS
- `taskhub backup` で pg_dump + Redis BGSAVE + artifacts tar + age 暗号化、checksums.txt 整合
- SP-001 frontmatter / Review / must_ship が **変更されていない** (既完了維持)

## 検証手順

```bash
$ cd ~/repo/TaskManagedAI
$ taskhub init --host t-ohga-mac --tailnet tail-xxxxx.ts.net
$ docker compose up -d
$ docker compose ps                                     # 全 service health
$ curl -s http://127.0.0.1:8000/healthz                  # api healthcheck (tm 不要)
$ curl -s http://127.0.0.1:3000/api/healthz              # frontend healthcheck
$ nc -z 127.0.0.1 5432 || echo "DB not exposed (expected)"   # internal-only verify
$ nc -z 127.0.0.1 6379 || echo "Redis not exposed (expected)" # internal-only verify
$ taskhub status                                         # all green + age fingerprint 表示
$ taskhub backup --output /tmp/sp001-5-backup.tar.age    # backup 成功
$ uv run pytest tests/deploy/test_taskhub_init.py tests/deploy/test_taskhub_backup.py \
                tests/deploy/test_postgres_image_digest_pinning.py \
                tests/deploy/test_db_redis_internal_only.py -q

# SP-001 既完了確認 (frontmatter 不変)
$ git log --oneline docs/sprints/SP-001_project_foundation.md
   (本 amendment commit で SP-001.md は変更されない、Phase G で追記した host-portable section は SP-001.md 末尾に独立 section、SP-001 frontmatter 完了状態は維持)
```

## レビュー観点

- SP-001 既完了の Review section / frontmatter status が変更されていない (audit clean)
- ADR-00021 lifecycle (proposed → **SP-022 で実機 drill PASS 後 accepted**) が ADR Gate Criteria に沿う (F-PR67-010/017 P2 adopt、master plan line 106 整合)
- `tm` 言及が SP-001.5 smoke から完全削除 (PH-F-003 fix)
- image digest pinning が CI で verify 可能
- DB/Redis internal-only expose が DD-05 と整合 (PH-F-007/§12.2 fix)

## 残リスク

- `taskhub restore/migrate` 本実装は SP-012 まで未提供、SP-001.5 完了時点では Mac 単独運用のみ
- Mac sleep / shutdown SOP の本文詳細は SP-012 で完成 (本 amendment では雛形のみ)
- ADR-00021 §11.7 (既存正本 host-portable 同期) のうち DD-05 / 計画(仮).md の本文 update は SP-022 で実施

## 次スプリント候補

- SP-002 (core data model) — SP-001 既完了に続く正規 P0 順序
- (並行可能なら) SP-022 で DD-05 / 計画(仮).md 本文 update

## 関連 ADR

- ADR-00021 (Host-Portable Deployment + Data Migration、SP-022 で実機 drill PASS 後 accepted、本 SP-001.5 は skeleton 実装着手の参照 ADR)
- ADR-00007 update (host-portable invariant、ADR-00021 同期 acceptance = SP-022 scope)

## Review

(SP-001.5 完了時に追記)
