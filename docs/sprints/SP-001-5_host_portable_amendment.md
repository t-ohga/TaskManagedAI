---
id: "SP-001-5_host_portable_amendment"
type: "heavy"
status: "in_progress"
sprint_no: 1.5
created_at: "2026-05-10"
updated_at: "2026-06-10"
target_days: 2
max_days: 3
adr_refs:
  - "[ADR-00021](../adr/00021_host_portable_deployment.md) # accepted 済 (Criteria #2/#6/#7/#8、§11.3/PGA-F-004 = image digest pinning + lock file)、batch-1 着手 gate 充足"
  - "[ADR-00007](../adr/00007_external_exposure.md) # accepted 済 (host-portable invariant)"
planned_adr_refs: []
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
- ADR-00021 (host-portable) は本 amendment Sprint と同時に proposed → accepted
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
  - ⚠️ **DEFERRED**: DB / Redis を Docker internal expose のみ (127.0.0.1 publish 撤回) — **出荷済み restore 契約と矛盾、額面実装禁止** (§Review 🔴 参照)
  - frontend (Next.js) service の `127.0.0.1:3900:3000` host bind + healthcheck
  - volume path を env var で吸収 (`${TASKHUB_DATA_DIR:-./data}`)
- SP015-T02: `cli/taskhub/` 最小実装
  - `cli/taskhub/main.py`
  - `cli/taskhub/commands/{init,backup,status}.py`
  - `cli/setup.py` (`taskhub` entry point、`uv tool install` 経由 install)
- SP015-T03: `docker-compose.override.yml.example` 雛形 (host-specific volume / sleep 制御 hint)
- SP015-T04: `.env.example` 整理 (env var で host 吸収)
- SP015-T05: `docs/deploy/host-setup.md` 雛形作成 (Mac / Linux / VPS の各 host SOP の構造化、本文の詳細は SP-012 で完成)
- SP015-T06: SP-001.5 smoke test (Mac 起動 verify、`tm` を使わない smoke、PH-F-003 fix)
- SP015-T07: ADR-00021 + ADR-00007 update を proposed → accepted

## タスク一覧

- [ ] SP015-T01〜T07 を順次実装
- [ ] migration `00NN_host_portable_compose.py` (もしあれば、env var 関連) PASS
- [ ] Mac で `taskhub init` → `docker compose up -d` → `taskhub status` で smoke (`tm` を使わない、PH-F-003)
- [ ] image digest pinning verify (`postgres:16-alpine@sha256:<digest>` 形式)
- [ ] ⚠️ **DEFERRED** (restore 契約と矛盾、§Review 🔴): ~~DB / Redis が Docker internal のみ expose verify (host から `nc 127.0.0.1 5432` で reject)~~ → 現状 gate は compose config の host_ip が全て `127.0.0.1` (loopback、外部非公開)

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| docker-compose.yml host-portable + image digest pinning | ○ | - |
| `taskhub` CLI (init/backup/status) | ○ | - |
| frontend portable + healthcheck | ○ | - |
| DB/Redis internal-only expose ⚠️ **DEFERRED** (restore 契約と矛盾、§Review 🔴、額面実装禁止) | ○→保留 | - |
| docs/deploy/host-setup.md 雛形 ⏸ host-phase へ defer (本 batch 除外) | ○→保留 | 設計 tension 解決後に別 doc PR |
| `tm` を使わない smoke (PH-F-003) | ○ | - |
| ADR-00021 + ADR-00007 update accepted | ○ | - |
| SP-001 既完了内容変更 | × | (絶対変更しない) |

## 受け入れ条件

- ADR-00021 / ADR-00007 update が proposed → accepted (本 SP-001.5 着手時 gate)
- Mac で `taskhub init` → `docker compose up -d` → `taskhub status` の smoke が `tm` を使わずに成功
- image digest pinning が docker-compose.yml で固定、`postgres:16-alpine@sha256:<digest>`
- ⚠️ **DEFERRED** (restore 契約と矛盾、§Review 🔴、額面実装禁止): ~~DB (`5432`) / Redis (`6379`) が host port で listen していない~~ → 現状契約は `127.0.0.1` loopback bind (tailnet/外部非公開、host loopback は restore tooling が依存)
- frontend (`127.0.0.1:3900`) が healthcheck PASS
- backup (approval-backed destructive flow、command shape は operator-runbook §2.1 / smoke-sop §14 正本) で pg_dump + Redis BGSAVE + artifacts tar + age 暗号化、checksums.txt 整合 (本 Pack では command を規定しない、phase-5 binding 等の実装詳細は SOP 参照)
- SP-001 frontmatter / Review / must_ship が **変更されていない** (既完了維持)

## 検証手順

### A. batch-1 で実行可能な検証 (前提: configured host)

> **前提**: ① Python は repo 管理の venv (`.venv/bin/python`、PyYAML 同梱) を使う (system `python`/`python3` は
> PyYAML 非同梱の場合あり) ② `docker compose config` は `env_file: .env.local` を hard 要求するため、最低限の
> `.env.local` (`TASKMANAGEDAI_ENVIRONMENT` / `TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET` / `TASKMANAGEDAI_DEV_LOGIN_TOKEN`
> / `POSTGRES_PASSWORD`) が存在すること。本 batch ではこの前提下で下記を実施し PASS を確認した。

```bash
$ cd ~/repo/TaskManagedAI            # (configured worktree。.venv + .env.local あり)
# 1) digest pin の構文整合 (repo venv の PyYAML を使用)
$ .venv/bin/python -c "import yaml; d=yaml.safe_load(open('docker-compose.yml')); print(d['services']['postgres']['image']); print(d['services']['redis']['image'])"
# 2) compose render で host_ip が全て 127.0.0.1 (loopback gate、0.0.0.0/tailnet 公開なし)。.env.local 前提
$ docker compose -f docker-compose.yml --env-file .env.local config --format json \
    | jq -r '.services|to_entries[]|select(.value.ports)|.value.ports[]|.host_ip' | sort -u   # → 127.0.0.1 のみ
# 3) pin した digest が multi-arch か: registry の manifest を取得し mediaType が manifest-list/OCI index で
#    linux/amd64 + linux/arm64 を含むことを確認 (本 batch で registry API で機械検証済、ADR-00021 §11.3)
$ # curl -s -H "Authorization: Bearer <token>" -H "Accept: application/vnd.oci.image.index.v1+json" \
$ #   https://registry-1.docker.io/v2/library/postgres/manifests/sha256:16bc... | jq '[.manifests[].platform|"\(.os)/\(.architecture)"]'

# SP-001 既完了確認 (frontmatter 不変)
$ git log --oneline docs/sprints/SP-001_project_foundation.md
   (本 amendment commit で SP-001.md は変更されない、SP-001 frontmatter 完了状態は維持)
```

### B. full SP-001-5 acceptance (計画、本 batch では **未実装/未作成** につき実行不可)

> 下記は SP-001-5 全体の目標 acceptance。`taskhub init` / `taskhub status` は現状 skeleton (exit 1)、
> `tests/deploy/test_taskhub_init.py` / `test_taskhub_backup.py` / `test_postgres_image_digest_pinning.py` /
> `test_db_redis_internal_only.py` は **未作成**。これらは follow-up batch + host-phase で実装する
> (🔴 design tension の reconciliation 後)。**現時点では実行しない (file-not-found / skeleton)。**

```text
# (計画、未実装 — 実行不可。command shape は規定しない)
- taskhub init / taskhub status         … 現状 skeleton (exit 1)。本実装は別 batch
- backup / restore (approval-backed)    … 正本は operator-runbook §1 (key) + §2.1 (backup approval) /
    smoke-sop §12/§14。approval record は phase-5 で backup_runtime_binding_fingerprint binding を要求するなど
    実装詳細があり、本 Pack では command shape を規定しない (ad-hoc 実行禁止、SOP に従う)
- tests/deploy/test_{taskhub_init,taskhub_backup,postgres_image_digest_pinning,db_redis_internal_only}.py … 未作成
- nc reject は SP-001-5 目標状態だが restore preflight と矛盾 (§Review 🔴)、本 batch では gate にしない
```

## レビュー観点

- SP-001 既完了の Review section / frontmatter status が変更されていない (audit clean)
- ADR-00021 lifecycle (proposed → SP-001.5 着手で accepted) が ADR Gate Criteria に沿う
- `tm` 言及が SP-001.5 smoke から完全削除 (PH-F-003 fix)
- image digest pinning が CI で verify 可能
- ⚠️ **DEFERRED** (§Review 🔴): ~~DB/Redis internal-only expose が DD-05 と整合 (PH-F-007/§12.2)~~ → 出荷済み restore 契約 (loopback bind 必須) と矛盾、設計 reconciliation を host-phase/ADR で決定

## 残リスク

- `taskhub restore/migrate` 本実装は SP-012 まで未提供、SP-001.5 完了時点では Mac 単独運用のみ
- Mac sleep / shutdown SOP の本文詳細は SP-012 で完成 (本 amendment では雛形のみ)
- ADR-00021 §11.7 (既存正本 host-portable 同期) のうち DD-05 / 計画(仮).md の本文 update は SP-022 で実施

## 次スプリント候補

- SP-002 (core data model) — SP-001 既完了に続く正規 P0 順序
- (並行可能なら) SP-022 で DD-05 / 計画(仮).md 本文 update

## 関連 ADR

- ADR-00021 (Host-Portable Deployment + Data Migration、SP-001.5 着手時 proposed → accepted)
- ADR-00007 update (host-portable invariant、同期 accepted)

## Review

(2026-06-04 台帳監査) **`proposed` 維持 (ADR gate 未達)**。本 amendment は ADR-00021 (Host-Portable Deployment) + ADR-00007 update の **accepted 化を着手 gate** とするが、canonical ADR (`docs/adr/00021_host_portable_deployment.md` / `docs/adr/00007_external_exposure.md`) は **現在も `status: "proposed"`** で、本 Pack frontmatter も `adr_refs: []` / ADR は `planned_adr_refs` 止まり。よって completed にはできず `proposed` を維持する (Codex App F-L2)。**別 drift 注意**: P0 Exit declaration (`docs/release/p0_exit_2026_05_22.md`) は SP-022 T00 で ADR-00021/00007 を accepted 化したと記載するが、canonical ADR 側が proposed のまま追従しておらず矛盾。ADR 正本の status 整合は別途要確認 (本 doc PR scope 外、報告に記録)。

(2026-06-10 batch-1、`in_progress` 化) **ADR gate 充足を確認**: canonical ADR-00021 / ADR-00007 はいずれも現在 `status: "accepted"` (2026-06-10 確認)。2026-06-04 note の drift (canonical proposed) は解消済のため `planned_adr_refs` → `adr_refs` へ移動し、着手 gate を充足した。digest pinning の設計根拠は **ADR-00021 §11.3 / PGA-F-004** (image digest pinning + version matrix + `docker-compose.lock.yml`)。※ ADR-00011 (GitHub App Permission Matrix) は digest pinning と無関係なため adr_refs から除外 (adv R7 F-2 fix、誤引用訂正)。

**batch-1 で実施した内容 (digest pin のみ、scope を最小化)**:
- ✅ **image digest pinning**: `docker-compose.yml` の `postgres:16-alpine` / `redis:7-alpine` を tag + manifest-list digest 併記に固定 (`@sha256:...`、ADR-00021 §11.3 / PGA-F-004)。digest は Docker Hub registry API (daemon 不要) で取得し、**両 digest が OCI image index で `linux/amd64` + `linux/arm64` を含むことを registry API で機械検証済** (pin 時点、arm64 Mac / amd64 Linux/VPS 両対応)。`docker compose config` render で全 host_ip が `127.0.0.1` (loopback、0.0.0.0/tailnet 公開なし) + YAML parse で構文整合を確認。**compose の network 契約は変更しない** (DB/Redis の `127.0.0.1:5432`/`:6379` loopback bind を維持。これは出荷済み restore preflight `verify_target_binding_consistency` が要求する contract)。
- ✅ adversarial R1-R8 で 1 つの誤りを是正: ADR-00011 (GitHub App Permission Matrix) を digest pinning 根拠に誤引用していた → **ADR-00021 §11.3 / PGA-F-004 に訂正** (R7 F-2)。
- ✅ committed lock file (`docker-compose.lock.yml`) + CI digest verification test は **defer** (ADR-00021 PGA-F-004 evidence、follow-up batch)。

**本 batch で意図的に scope 外とした項目 (over-claim 回避)**:
- ⏸ **operational docs (`docs/deploy/host-setup.md` / 運用開始ガイド) の authoring を本 PR から除外**。adversarial R1-R8 で、これらが「検証できない運用コマンド」(base-only production 起動 / migration wrapper / **backup approval の phase-5 `backup_runtime_binding_fingerprint` binding** など) を繰り返し誤記することが判明。正確な記述には ① 下記 🔴 design tension の解決 ② backup approval 実装 (phase-5 binding) の深い読解 が必要なため、**設計判断後に別 doc PR で正しく書く**。host-setup.md 雛形 (SP015-T05 / must_ship) も同様に host-phase へ defer。
- ⏳ `taskhub status` (local) / `taskhub init` 本実装、production 経路の実機検証 = 別 batch / 実 host 必須 (master plan host-phase)。

→ digest pinning (multi-arch 検証付) は満たすが、host-setup.md 雛形 + `taskhub init→up→status` smoke + 実機検証 + committed lock file/CI test + 下記 🔴 reconciliation が残るため **`completed` にはせず `in_progress` 維持**。

(2026-06-21 SP-PHASE0 batch-2/3 連携 note) PLAN-10 Phase 0 で **host-setup.md (Mac runbook、`docs/deploy/host-setup.md`、PR #353)** が着地し、`taskhub init/status --local` (alembic head runtime / loopback DSN) + `taskhub secret-create/rotate/revoke` が実装された。loopback bind 正本化は **SP-PHASE0 S4 の `test_compose_loopback_binding` regression guard test** (本 batch-3) で機械検証する (compose host_ip が全て 127.0.0.1、ports 撤回 = restore 契約破壊の地雷を CI で防止)。**ただし `completed` には依然しない**: ① host-setup.md の **clean Mac 実機検証は user が 2026-06-21 に実施済 (基盤機能 全 pass、operator 詰まり 2 点は #355 で fix)** ② committed lock file / 上記 🔴 DB/Redis internal-only vs restore 契約 reconciliation は未決 (host-phase の user/ADR 決定事項) のため `in_progress` 維持 (over-claim 警戒、SP-PHASE0 §127)。

### 🔴 DEFERRED: 未解決の設計 contradiction (host-phase で要 user/ADR 決定)

> ⚠️ **本 Pack の internal-only DB/Redis 系 acceptance は出荷済み restore 契約と矛盾しており DEFERRED。実装者は受け入れ条件の「127.0.0.1 publish 撤回 / `nc` reject / host port で listen しない」を額面通り実装してはならない (ports 削除 = restore/rollback recovery 破壊)。**

本 Pack の複数箇所 (実装チケット SP015-T01、タスク一覧、must_ship 表「DB/Redis internal-only expose」、受け入れ条件、検証手順 §nc block、レビュー観点「DD-05 §12.2 / PH-F-007」) が **「DB/Redis を host に publish しない」を目標状態**とするが、**出荷済み restore preflight (`scripts/taskhub_restore_orchestrator.py` の `verify_target_binding_consistency`) は逆に `127.0.0.1:5432:5432` / `127.0.0.1:6379:6379` の explicit loopback binding を必須**とする。両者は **直接矛盾**。

- 現状は restore 契約に従い **loopback publish を維持** (Pack 目標状態は未達)。
- 「internal-only (host 非到達)」へ進めるには **restore orchestrator を `docker compose exec` 経由へ変更する設計判断 + 実 host restore drill** が要る。**どちらの design を採るか = user/ADR 決定事項**。本 batch では決めない。
- それまでの正しい network gate は「nc reject」ではなく **compose config の host_ip が全て `127.0.0.1` であること** (tailnet/外部非公開かつ host loopback のみ)。
- 上記目標状態を assert する planned test (`tests/deploy/test_db_redis_internal_only.py` 等) は **未作成**。
- 経緯: adv R1 で「internal-only = host 非到達」と誤解し base から ports 削除→restore 破壊を招いたが R2 で revert (F2-1)。
