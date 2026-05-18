---
id: "ADR-00021"
title: "Host-Portable Deployment + Data Migration: Mac / Linux / VPS どれでも 1 箇所選択 + taskhub admin CLI (init/backup/restore/migrate) + age key 手動運搬 + Tailscale 閉域維持 + RTO ≤ 4h host migration drill"
# F-PR67-010 + F-PR67-013 P2 adopt (R3 で私が partial reject した判断を撤回、
# R4 で master plan grep 詳細により valid と確認):
#   `docs/設計検討/2026-05-13_p0_exit_master_plan.md:106` で「ADR-00021
#   acceptance | Sprint 12 で host migration drill PASS 後」明示、PRD-01 §523
#   で host migration drill 必須化. SP-012 では skeleton 実装着手済だが実機
#   drill PASS は SP-022 scope なので、acceptance 条件 unmet. accepted 化を
#   撤回し proposed に戻す.
status: "proposed"
date: "2026-05-10"
authors:
  - "t-ohga"
related_sprints:
  - "SP-001_project_foundation"
  - "SP-012_p0_acceptance"
  - "SP-022_framework_intake_hardening"
related_research:
  - "docs/設計検討/phase-c-multi-agent-spec-draft.md §6.5.3 (VPS deployment 前提を本 ADR で host-portable に拡張)"
  - "ADR-00007 (External exposure、Tailscale-only invariant 不変前提)"
supersedes: null
superseded_by: null
# F-PR67-010/013 P2 adopt: master plan で明示された acceptance 条件
# (host migration drill PASS、SP012-T01〜T10 完了) が unmet のため proposed
# 維持. SP-012 で skeleton 実装着手は進めたが、accepted 化は SP-022 で実機
# drill PASS 後.
acceptance_blocked_by:
  - "host migration drill (Mac→VPS) RTO≤4h PASS (SP-022 scope、`docs/設計検討/2026-05-13_p0_exit_master_plan.md:106` 明示)"
  - "SP012-T01〜T10 完了 (SP-012 partial_completed_with_carry_over、P0.1 で残 carry-over 完了)"
  - "ADR-00007 同期 accepted 化条件 (本 ADR の accepted 化と同時、host 中立 invariant)"
acceptance_target_sprint: "SP-022 で host migration drill 自動化完成 + 実機 drill PASS 後"
acceptance_history:
  - "2026-05-10: proposed (Phase G plan-review + adversarial-review clean + Phase H second-opinion で 94 finding closure verify 完了)"
  - "2026-05-18T00:30:00Z: tentative accepted (PR #67 F-PR67-002 P1 adopt として SP-012 で accepted 化試行、SP-012 batch 7 taskhub admin CLI + batch 10 audit_events 実装着手直前 timestamp)"
  - "2026-05-18T09:40:06Z: tentative acceptance 撤回 (Codex PR #67 R4 F-PR67-010/013 P2 valid 確認: master plan + PRD-01 で『Sprint 12 で host migration drill PASS 後』明示、acceptance 条件 unmet のため proposed に restore、`.claude/rules/sprint-pack-adr-gate.md §12` invariant 遵守)"
  - "future: 実機 host migration drill PASS 後 SP-022 scope で再 accepted 化"
---

最終更新: 2026-05-18 (Sprint 12 で proposed → accepted 昇格、§11/§12/§14 が **正本**、§2/§3/§5/§7 は早期 sample で **§11/§12/§14 が後勝ち**)

## 仕様 normative source 序列 (PH-F-004 fix)

本 ADR の本文は段階的に起票されたため、後段で撤回・改定された仕様が前段に残っている。**§11/§12/§14 (Phase G/H reflect 後の仕様) が後勝ちで normative source**:

| §  | 状態 |
|---|---|
| §1 (host 選択抽象化) | normative |
| §2 (docker-compose sample) | **§11.3 / §12.1 / §12.2 で上書き**: postgres:16-alpine@sha256:<digest> + redis:7-alpine@sha256:<digest> + DB/Redis を Docker internal expose のみ + frontend service portable + 127.0.0.1:3000 bind |
| §3 (`taskhub` admin CLI 仕様) | normative |
| §4 (backup file 構造) | normative |
| §5 (age key 安全運搬) | **§11.1 で上書き**: `cat ~/.taskhub/age/key.txt` 表示手順は撤回、secret manager (1Password) default-required、scp/direct write は break-glass 承認付き、`--include-secrets` flag は `--include-sops-env` に rename、age private key は backup file に絶対含めない |
| §6 (Tailscale 閉域維持) | normative |
| §7 (PostgreSQL portability) | **§11.3 で上書き**: postgres:16-alpine、image digest pinning |
| §8 (RTO ≤ 4h) | **§11.4 で上書き**: happy path 3h30m / failure path 4h / 自動化 90m の 3 階層 |
| §9-10 (Sprint と test) | normative |
| §11 (Phase G plan-review patch、HIGH 7) | **正本** |
| §12 (Phase G plan-review patch、MEDIUM 11) | **正本** |
| §13 (Phase G closure summary) | normative |
| §14 (Phase G adversarial Strengthening Catalog 14 件) | **正本** |
| §15 (Phase G review summary) | normative |

## 背景

- 決定対象: TaskManagedAI を **VPS 固定でなく host portable** にし、Mac / Linux / VPS のいずれを「メイン基盤サーバー」に選んでも同一動作するようにする。さらに **データ移行** (Mac で開発 → VPS 運用、または VPS → 別 VPS への乗り換え) を `taskhub` admin CLI で自動化する。本 ADR は (1) host 選択の抽象化、(2) backup/restore/migrate コマンド仕様、(3) age key 安全運搬、(4) Tailscale 閉域維持 invariant、(5) PostgreSQL / Redis / artifacts portability、(6) RTO ≤ 4h host migration drill (AC-HARD-04 拡張) の 6 点を担保.
- 関連 Sprint: SP-001 (`taskhub init` + `taskhub backup` 最小実装、Mac local 起動 verify)、SP-012 (P0 完了時に `taskhub restore` + host migration drill)、SP-022 (host migration 自動化 + 手順書整備).
- 前提 / 制約 (既存 invariant 不変):
  - **Tailscale 閉域維持** (ADR-00007): host を変えても Funnel 不使用、127.0.0.1 bind + Tailscale Serve のみ
  - SecretBroker atomic claim + SOPS + age key (ADR-00006)
  - AC-HARD-04 backup/restore RPO ≤ 24h, RTO ≤ 4h
  - tenant/project boundary 複合 FK (DD-02)
  - Approval Workflow 4 整合 + decider human-only
  - 全 id=uuid + tenant_id=bigint
- ADR Gate Criteria #2 (DB schema migration 整合) + #6 (Secrets management、age key 運搬) + #7 (External exposure、Tailscale 閉域維持) + #8 (破壊的操作、host 切替時の data 移行) 該当.

## 選択肢

| # | 案 | 採否 | 根拠 |
|---|---|---|---|
| **A (採用)** | host-portable + Tailscale 閉域維持 + age key 手動運搬 + `taskhub` admin CLI で backup/restore/migrate | adopt | 既存 ADR-00007 / ADR-00006 invariant 不変、Docker Compose の portability を活かす、安全装置として age key を git/cloud に乗せない |
| B | host = VPS 固定 (現 Phase C draft §6.5.3) | reject | ユーザー要件「Mac で開発初期、VPS で運用」+「他端末への移行容易性」を満たさない |
| C | host = K8s cluster (multi-host 冗長化) | reject | P0 個人 1 user 想定で overkill、運用負荷 increase、Tailscale 閉域 + Docker Compose で十分 |
| D | data sync = active-active replication (PostgreSQL streaming + Redis cluster) | reject | split-brain risk、複雑性 + cost、P0/P0.1 想定外 |

## 採用案

採用: **A: host-portable + Tailscale 閉域維持 + age key 手動運搬 + `taskhub` admin CLI**.

### §1: host 選択の抽象化

| 項目 | 仕様 |
|---|---|
| host 候補 | Mac / Linux / VPS / その他 Docker 動作可能な OS (Windows / WSL2 等は P0.1 以降で検討) |
| 選択原則 | **メイン基盤は 1 箇所** (active-active 不可)、運用フェーズに応じて切替 |
| host 共通 | Docker Compose v2 + Tailscale + age (SOPS) のみ要求 |
| host 別差分 | volume path (Mac は `~/Library/Application Support/taskhub` or `~/.taskhub/`、Linux は `/var/lib/taskhub`、VPS は `/var/lib/taskhub`) は `docker-compose.override.yml` で吸収 |
| Tailscale Serve URL | `taskhub.<host-name>.tail-xxxxx.ts.net` (host が変われば URL も変わる) |
| host 切替時の URL drift | `tm` CLI profile に `backend_url` を新 URL で再登録、refresh credential は新 host から再 issue (ADR-00015 で短命 token なので影響軽微) |

### §2: docker-compose.yml の host-portable 化

```yaml
# docker-compose.yml (全 host 共通、git 管理対象)
version: '3.9'
services:
  api:
    image: ghcr.io/<org>/taskhub-api:${TASKHUB_VERSION:-latest}
    ports:
      - "127.0.0.1:8000:8000"      # 127.0.0.1 bind 維持 (ADR-00007)
    volumes:
      - ${TASKHUB_DATA_DIR:-./data}/artifacts:/app/artifacts
    env_file:
      - ${TASKHUB_ENV_FILE:-.env}
    depends_on: [postgres, redis]
  
  worker:
    image: ghcr.io/<org>/taskhub-worker:${TASKHUB_VERSION:-latest}
    env_file: [${TASKHUB_ENV_FILE:-.env}]
    depends_on: [postgres, redis]
  
  postgres:
    image: postgres:17-alpine                # version pinning (host 移行で drift しない)
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - ${TASKHUB_DATA_DIR:-./data}/postgres:/var/lib/postgresql/data
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-taskhub}
      POSTGRES_DB: ${POSTGRES_DB:-taskhub}
  
  redis:
    image: redis:7-alpine                    # version pinning
    ports:
      - "127.0.0.1:6379:6379"
    volumes:
      - ${TASKHUB_DATA_DIR:-./data}/redis:/data
    command: ["redis-server", "--save", "60", "1", "--appendonly", "yes"]   # RDB + AOF (data 安全性最大)
```

```yaml
# docker-compose.override.yml (host-specific、gitignore 対象)
# Mac 例:
services:
  api:
    extra_hosts: [...]
  postgres:
    platform: linux/arm64                    # Apple Silicon
```

```bash
# .env.example (git 管理)
TASKHUB_VERSION=v0.1.0
TASKHUB_DATA_DIR=./data
TASKHUB_ENV_FILE=.env                        # SOPS 復号後の path
POSTGRES_USER=taskhub
POSTGRES_DB=taskhub
# DB password / SOPS age public key 等は SOPS .env.encrypted で管理
```

### §3: `taskhub` admin CLI 仕様

`tm` (user CLI、ADR-00015) と別の **admin 専用 CLI**:

| command | 動作 | 必要権限 |
|---|---|---|
| `taskhub init --host <name> --tailnet <ts.net>` | 新 host で初回 setup: Docker volume 作成、age key 生成 (existing なら skip)、Tailscale Serve config 設定、`.env.example` から `.env.encrypted` 雛形生成 | local file system + Docker socket |
| `taskhub backup --output <path> [--include-secrets]` | 全 service stop (graceful) → `pg_dump` + Redis BGSAVE + artifacts tar + (option) `.env.encrypted` を tar → age 公開鍵で暗号化 → `<path>.tar.age` 出力 | Docker socket + age public key |
| `taskhub restore --input <path>.tar.age` | age 秘密鍵で復号 → 全 service stop → 既存 volume を `data/_pre-restore-<ts>/` に move (rollback 安全) → `pg_restore` + Redis RDB import + artifacts 配置 → `alembic check` PASS verify → service up + healthcheck PASS verify → 失敗時は元 volume に戻す | Docker socket + age private key |
| `taskhub migrate --target <hostname> [--via tailscale]` | backup → Tailscale file share or scp で転送 → 対象 host で `taskhub restore` 自動実行 → 旧 host 上の `taskhub backup` は別 path に保管 (rollback 用 6 ヶ月保持) | source/target 両 host への ssh または Tailscale tailfs |
| `taskhub status` | 現 host name、Docker service health、data size (PostgreSQL / Redis / artifacts)、last backup 時刻、age key fingerprint、`.env.encrypted` SOPS 整合性、Tailscale Serve URL を表示 | local file system + Docker socket |
| `taskhub age-rotate` | 現 age key を deprecated 化 + 新 age key 生成 + `.env.encrypted` を新 key で SOPS re-encrypt + 旧 key は `~/.taskhub/age/deprecated/` に保管 | local file system |
| `taskhub verify --integrity` | PostgreSQL 全 row count、artifacts file checksum、Redis key count、`.env.encrypted` SOPS validity、age key fingerprint match、`alembic check` を一括 verify | Docker socket |

### §4: backup file 内容 (`.tar.age` 構造)

```
backup-<host>-<timestamp>.tar.age
└─ (age 復号後)
    backup-<host>-<timestamp>/
    ├── meta.json                         # version, host, timestamp, postgres_version, redis_version, alembic_head
    ├── postgres/
    │   ├── pg_dump.sql                   # 全 schema + data (custom format)
    │   └── alembic_version.txt           # 現 head revision
    ├── redis/
    │   ├── dump.rdb                      # RDB snapshot
    │   └── appendonly.aof                # AOF (option)
    ├── artifacts/
    │   └── (全 file system content)
    ├── env.encrypted                     # .env.encrypted (SOPS のまま、age key は持たない)
    └── checksums.txt                     # 各 file の sha256
```

**age 暗号化対象**: backup file 全体 (上記 directory を tar → age encrypt)。**age private key は backup に含めない** (key を持たない host では復号不可、安全装置).

### §5: age key 安全運搬手順 (CRITICAL invariant)

age key は **backup file に絶対含めない**。host 移行時は age key を別経路で安全運搬:

| 手順 | 内容 |
|---|---|
| 1 | source host で `taskhub age-rotate` を **必要なら** 実行 (target host 用に新 key 生成、source は deprecated 化) |
| 2 | source host で `cat ~/.taskhub/age/key.txt` を確認、内容を Tailscale 経由 (tailfs / scp / 1Password 等の secret manager) で target host へ運搬 |
| 3 | **禁止経路**: git commit、cloud storage (Dropbox / iCloud / Google Drive)、email、Slack DM、Discord DM、平文 USB |
| 4 | target host で `~/.taskhub/age/key.txt` に置く (chmod 600、root-only readable) |
| 5 | source host の旧 key は **直ちに削除しない** (3 ヶ月保持、`~/.taskhub/age/archived/<date>-key.txt`)、SOPS rotation drill 完了後に削除 |
| 6 | `taskhub status` で target host の age key fingerprint を確認、source と一致確認 (key 改竄なし) |

### §6: Tailscale 閉域維持 invariant (ADR-00007 不変前提)

host が変わっても以下 invariant は **絶対不変**:

| invariant | 強制 |
|---|---|
| 公開 IP からの 22/80/443 deny | UFW (Linux/VPS) / pf (Mac) で deny rule、host 設定の SOP 化 |
| Funnel 不使用 | Tailscale Serve のみ、`tailscale serve --funnel` 禁止 |
| 127.0.0.1 bind | docker-compose.yml で全 service の host port を 127.0.0.1 固定 |
| Tailscale device approval 必須 | tailnet 管理画面で device 承認 + tag:taskhub grants |
| ADR-00007 既存 grants | `tag:taskhub`, `tag:taskhub-ci`, `tag:taskhub-cli` (P0.1 SP-016 で追加) のみ |

host 別の追加考慮:

| host | 公開 IP block 手段 | sleep / shutdown 対策 |
|---|---|---|
| Mac | macOS pf (Packet Filter) で 22/80/443 incoming deny + Tailscale 経由のみ | `caffeinate -i docker compose ...` または `pmset -a sleep 0 disablesleep 1` (電源接続中) |
| Linux (laptop / desktop) | UFW deny | `systemd-inhibit` または `systemctl mask sleep.target suspend.target` |
| VPS | UFW deny + Hostinger console で raw IP block 確認 | (常時稼働、対策不要) |

### §7: PostgreSQL / Redis / artifacts portability

| 要素 | portability 担保 |
|---|---|
| PostgreSQL version | docker image tag で固定 (`postgres:17-alpine`)、host 移行で version drift しない |
| PostgreSQL data | `pg_dump --format=custom` で全 schema + data export、`pg_restore` で完全復元 |
| Redis version | docker image tag で固定 (`redis:7-alpine`) |
| Redis data | RDB + AOF 両方を backup (RDB は snapshot、AOF は append-only log で完全復元) |
| artifacts | tar で全 file system 取得、checksum 検証 |
| alembic migration head | `meta.json` に記録、restore 後に `alembic check` で head 一致 verify |
| Docker volume permission | restore 時に `chown postgres:postgres` 等を service-specific に適用 |
| timezone / locale | `meta.json` に記録、host 間で UTC 固定推奨 |

### §8: RTO ≤ 4h host migration drill (AC-HARD-04 拡張)

既存 AC-HARD-04 (RPO ≤ 24h, RTO ≤ 4h) を host migration drill に拡張:

| step | RTO budget | 内容 |
|---|---|---|
| 1: source host で `taskhub backup` | 30 分 | service stop → pg_dump + Redis BGSAVE + artifacts tar → age encrypt |
| 2: backup file を target host へ転送 | 30 分 | Tailscale file share or scp、size に依存 (1 GB / 30 分目安) |
| 3: age key 安全運搬 | 30 分 | §5 手順、手動 |
| 4: target host で `taskhub init` | 15 分 | Docker volume 作成、Tailscale Serve config |
| 5: target host で `taskhub restore` | 60 分 | age 復号 + pg_restore + Redis import + artifacts 配置 + healthcheck |
| 6: `tm` CLI profile 切替 + 動作確認 | 30 分 | 全機械の `tm` profile に target host URL を設定、`tm ticket list` で動作確認 |
| 7: 整合性 verify | 15 分 | `taskhub verify --integrity` + 全 contract test smoke (`uv run pytest -q --smoke`) |
| **合計** | **3h30 分** | RTO ≤ 4h 内 |

drill は SP-012 (P0 完了) で必須、SP-022 で全自動化 (`taskhub migrate` one-shot で 90 分目標).

### §9: 実装 Sprint と対象ファイル

- **SP-001 (project foundation)**: `taskhub` CLI の `init` + `backup` + `status` 最小実装
  - `cli/taskhub/main.py` (or `scripts/taskhub.sh`)
  - `cli/taskhub/commands/{init,backup,status}.py`
  - `docker-compose.yml` を host-portable 化 (volume / version pinning)
  - `.env.example` を整理 (host-specific は env var で吸収)
  - `docs/deploy/host-setup.md` (各 host の SOP)
- **SP-012 (P0 完了)**: `restore` + `migrate` + `age-rotate` + `verify` 完成 + host migration drill 実施
  - `cli/taskhub/commands/{restore,migrate,age-rotate,verify}.py`
  - `tests/deploy/test_host_migration_drill.py` (Mac → VPS / VPS → 別 VPS の 2 case)
  - `docs/deploy/host-migration.md` (運用手順書)
  - AC-HARD-04 fixture 拡張
- **SP-022 (framework intake hardening)**: 全自動化 + 手順書最終化 + Phase E 残リスク closure
  - `taskhub migrate` の error recovery / rollback 完成
  - 半年に 1 回の host migration drill scheduling

### §10: テスト指針

主要 contract / integration test:

| test | 内容 |
|---|---|
| `tests/deploy/test_taskhub_init.py` | 新 host で init → docker volume + age key + .env.encrypted 雛形が正しく生成 |
| `tests/deploy/test_taskhub_backup.py` | backup → meta.json + checksums.txt 検証 + age 暗号化 verify |
| `tests/deploy/test_taskhub_restore.py` | restore → pg_restore + Redis import + artifacts 配置 + alembic head 一致 + healthcheck PASS |
| `tests/deploy/test_taskhub_migrate.py` | source → target で end-to-end、整合性 verify |
| `tests/deploy/test_age_key_safety.py` | backup file に age private key が含まれないこと、SOPS .env.encrypted は age 暗号化のみ |
| `tests/deploy/test_host_migration_drill.py` | RTO ≤ 4h 達成 verify |
| `tests/deploy/test_tailscale_only_post_migration.py` | host 移行後も public IP からの 22/80/443 deny 維持、Funnel 不使用維持 |
| `tests/deploy/test_postgres_version_pin.py` | docker-compose.yml の image tag 固定 verify |
| `tests/deploy/test_split_brain_prevention.py` | 旧 host が動作中に新 host で restore 試行 → reject (file lock or 整合性 check で) |

## 却下案

(B/C/D は §選択肢 表参照).

## リスク / mitigation

| リスク | 検知 | 軽減 |
|---|---|---|
| age key の安全運搬失敗 (key leak) | `taskhub status` で fingerprint mismatch detect | §5 手順厳守、git/cloud 経由 reject、3 ヶ月保持で rotation drill |
| split-brain (旧 host 動作中に新 host で restore) | `tests/deploy/test_split_brain_prevention.py` | restore 時に `taskhub status --remote <old-host>` で旧 host service down 確認、確認なしは reject |
| PostgreSQL version drift | `meta.json` の postgres_version と target host の image tag 比較 | docker image tag pinning + restore 時 version check |
| RTO ≤ 4h 超過 | drill 計測 | SP-022 で `taskhub migrate` の 自動化 + 並列化 (pg_dump + Redis BGSAVE + artifacts tar を background job 並列) |
| Mac sleep / shutdown で service down | `caffeinate` / `pmset` 設定 SOP | `docs/deploy/host-setup.md` に Mac SOP 明記、運用フェーズで VPS 移行 trigger |
| host 移行後の `tm` CLI profile drift | `tm auth login --backend <new-url>` 再 issue | 全機械で profile update を SOP 化 |
| restore 失敗時の data loss | `data/_pre-restore-<ts>/` に旧 volume 保管 | 失敗時は `taskhub restore --rollback <pre-restore-ts>` で復旧 |
| backup file の改竄 | `checksums.txt` + age 認証 | restore 時に sha256 verify、改竄 detect で reject |
| age key compromise (盗難 / leak) | 定期 rotation drill | `taskhub age-rotate` で全 SOPS re-encrypt + 旧 key は 3 ヶ月後削除 |

## rollback 手順

### 運用 rollback (host 移行後に target host で問題発見)

1. target host で `docker compose down`
2. **source host が `data/_pre-restore-<ts>/` に旧 volume 保管している場合**: source host で `taskhub restore --rollback <pre-restore-ts>` で旧 data に復元 + service up
3. 全機械の `tm` CLI profile を source host URL に戻す (`tm auth login --backend <source-url>`)
4. target host の data は `~/.taskhub/data/_failed-restore-<ts>/` に保管 (3 ヶ月後削除)
5. 問題分析後、再度 migration drill を実施 (SP-022 で手順改善 → 再試行)

### Migration rollback (本 ADR 自体の rollback)

1. `taskhub` CLI を deprecated 扱い、SP-001 / SP-012 / SP-022 への影響を rollback
2. host を VPS 固定に戻す (Phase C draft §6.5.3 の VPS 前提に revert)
3. ADR-00007 update を revert
4. 既存 backup/restore 仕様 (AC-HARD-04 既存) のみ維持

## 関連

- ADR-00007 update (External exposure、host-portable 明示化)
- ADR-00006 (Secrets management、age key 運搬手順)
- ADR-00014/15/16 (Multi-Agent vision、host 移行で multi-agent table も自動 portable)
- AC-HARD-04 (backup/restore drill、host migration drill 拡張)
- Phase C draft §6.5.3 (VPS deployment 前提を本 ADR で host-portable に拡張)
- SP-001 / SP-012 / SP-022

---

## Phase G plan-review patch (2026-05-10、18 finding 全件 adopt)

Codex plan-review (R1) で HIGH 7 + MEDIUM 11 = 18 finding。全件 adopt して以下に反映:

### §11: HIGH 7 件 patch

#### §11.1 age key 運搬の SecretBroker 境界整合 (PG-F-002 / PG-F-015 fix)

§5 の `cat ~/.taskhub/age/key.txt` 表示手順は **撤回**。SecretBroker invariant (raw secret 露出禁止) と整合させる安全手順:

| 運搬経路 | 安全手順 |
|---|---|
| 1Password / Bitwarden 等の secret manager | source host で 1Password CLI で age private key を保管 → target host で 1Password CLI で fetch (raw 値は terminal scrollback / shell history / clipboard / screenshot に残らない) |
| Tailscale SSH 経由の direct write | `ssh -t target 'cat > ~/.taskhub/age/key.txt && chmod 600 ~/.taskhub/age/key.txt' < ~/.taskhub/age/key.txt` (source 側 cat のみ、SSH session に閉じる、history 抑制) |
| scp + immediate chmod 600 | `scp ~/.taskhub/age/key.txt target:~/.taskhub/age/key.txt && ssh target 'chmod 600 ~/.taskhub/age/key.txt'` (network 中転送のみ Tailscale 内、ローカル一時ファイルなし) |

**禁止経路 (deny list 拡張)**:
- git commit / cloud storage (Dropbox / iCloud / Google Drive)
- email / Slack DM / Discord DM
- 平文 USB / SD card
- shell history (history 残る方法すべて、`HISTCONTROL=ignorespace` で先頭スペース command のみ許容)
- terminal scrollback
- clipboard (raw 貼り付け禁止)
- screenshot / screen recording
- migration archive / log

**`--include-secrets` flag 改名 (PG-F-015 fix)**: `taskhub backup --include-secrets` を **`--include-sops-env`** に rename. SOPS 暗号化済 .env のみを含む、age private key は **絶対含めない** (CI test で verify):

```python
# tests/deploy/test_backup_no_age_key.py
def test_backup_excludes_age_private_key():
    backup = create_backup(include_sops_env=True)
    assert "age private key" not in extract_files(backup)
    assert "key.txt" not in [f.name for f in extract_files(backup)]
    manifest = extract_manifest(backup)
    assert manifest["age_private_key_included"] is False
```

**backup manifest 必須項目**: `age_private_key_included: false` を `meta.json` に明示、raw secret scan を必須化.

#### §11.2 split-brain 防止強化 — freeze/drain marker (PG-F-003 fix)

`taskhub status --remote <old-host>` だけに依存しない、強制的な split-brain 防止:

```bash
# source host で migration 開始時に
$ taskhub freeze --reason "migration to t-ohga-vps at 2026-05-10T10:00Z"
   → ~/.taskhub/freeze.signed が作成される (age 署名 + migration_epoch + source_host_id + freeze 時刻)
   → docker compose の api/worker container を read-only mode に切替 (or 完全停止)
   → freeze 中は新 ticket 受付拒否、`tm` CLI に migration in progress message
   → freeze 解除は明示の `taskhub thaw` のみ (auto thaw なし)

# backup meta.json に以下を記録:
{
  "source_host_id": "uuid",
  "migration_epoch": "2026-05-10T10:00:00Z",
  "freeze_signature": "<age signature of source_host_id + epoch>",
  "backup_started_at": "2026-05-10T10:00:30Z",
  "backup_completed_at": "2026-05-10T10:25:00Z",
  "postgres_txid_xmin": "12345",
  "postgres_checkpoint_lsn": "0/12345678",
  "redis_dump_offset": "0/abc"
}

# target host で restore 時に
$ taskhub restore --input backup.tar.age
   → meta.json の freeze_signature を age public key で verify
   → freeze_signature 不一致なら reject (split-brain 検知)
   → restore 完了後、target host が active marker (~/.taskhub/active.signed) を作成
   → source host は thaw されるまで service down 維持

# split-brain 防止 invariant:
- 同 migration_epoch で 2 つの host が active になることは絶対禁止
- target restore が成功しても、source host は taskhub thaw 明示まで disable
- network partition でどちらが active か不明な場合は、両方 manual intervention 必須 (auto failover なし)
```

#### §11.3 PostgreSQL version 修正 — postgres:16 を正本 (PG-F-004 fix)

現行 docker-compose.yml の `postgres:16-alpine` を正本に固定 (本 ADR §2 sample の `postgres:17-alpine` を撤回):

- P0/P0.1/P1 期間 = `postgres:16-alpine` で portable
- postgres:17 への migration は **別 ADR (proposed)** で起票、`pg_dump --format=custom` → fresh 17 restore → schema/constraint verification の 3 step + rollback 計画

SP-001 の version pin test:

```python
# tests/deploy/test_postgres_version_pin.py
def test_postgres_version_is_16():
    compose = parse_yaml("docker-compose.yml")
    assert compose["services"]["postgres"]["image"] == "postgres:16-alpine"
```

#### §11.4 RTO budget — happy path / failure path 分離 (PG-F-007 fix)

§8 RTO 内訳を 2 path に分離:

| path | budget | 内容 |
|---|---|---|
| **happy path** | 3h30m | §8 既存内訳 (backup → 転送 → age 運搬 → init → restore → profile 切替 → verify) |
| **failure / rollback path** | **4h 内 (gate 対象)** | happy path に加えて: profile drift 修正 +20m / data size 増大 (>5GB) +30m / network interruption 中断 → resume +30m / Mac sleep 復旧 +15m / target healthcheck fail → rollback +60m |
| 改善目標 (SP-022) | **90m 自動化** | `taskhub migrate` one-shot で 90 分目標、追加改善のみ defer 可 |

**SP-012 の AC-HARD-04 拡張**: RTO ≤ 4h は **failure path** で達成必須 (defer 不可)。SP-022 では happy path 90m 達成が新 must_ship.

#### §11.5 multi-agent table restore 整合性 fixture (PG-F-008 fix)

`taskhub verify --integrity --multi-agent` を追加:

| 検証対象 | check |
|---|---|
| inter_agent_messages | seq_no 連続性 (gap detect)、consumed_at / payload_hash 連続性、previous_hash chain validity |
| memory_retrieval_artifacts | sanitizer_version vs current `sanitizer_policy_versions` deprecated_at 確認、stale はそのまま retain (deny on retrieval) |
| project_agent_roles | soft-delete (deprecated_at) と agent_runs.role_id 参照の整合 |
| review_artifacts | parent_run/requester/reviewer FK 整合、reviewer != requester invariant 維持 |
| agent_runs | orchestrator_lease_token / lease_expires_at が host 移行で stale → restore 後に手動 thaw で reset (auto thaw なし、§11.2 invariant) |

SP-012 / SP-022 must_ship に `tests/deploy/test_multi_agent_restore_integrity.py` 追加。`eval/multi_agent/host_migration_dataset/` (public/private/adversarial_new 各 case) を AC-HARD-04 fixture に追加.

#### §11.6 sealed guard path 完全同期 (PG-F-009 fix)

Phase C §1.6 P0 sealed guard / ADR-00013 / ADR-00014 すべての forbidden path リストを統合:

```bash
# Phase C draft §1.6 / ADR-00013 / ADR-00021 共通 forbidden glob (recursive)
forbidden=(
    'backend/app/db/models/project_agent_role.py'
    'backend/app/db/models/inter_agent_message.py'
    'backend/app/db/models/memory_record.py'
    'backend/app/db/models/memory_retrieval_artifact.py'
    'backend/app/db/models/review_artifact.py'
    'backend/app/services/orchestrator/*'
    'backend/app/services/inter_agent/*'
    'backend/app/services/memory/*'
    'backend/app/services/remote_agent_gateway.py'
    'backend/app/adapters/remote_agent/*'                  # PG-F-009 追加
    'backend/app/api/remote_agent_router.py'                # PG-F-009 追加
    'frontend/app/(admin)/agent-roles/*'
    'frontend/app/(admin)/orchestrator/*'
    'frontend/app/remote-agent/*'                            # PG-F-009 追加
    'cli/tm/*'
    'config/remote_agent_compliance.toml'                    # PG-F-009 追加
    'tests/**/remote_agent/*'                                # PG-F-009 追加
    'migrations/versions/*multi_agent*'
    'migrations/versions/*orchestrator*'
    'migrations/versions/*memory*'
    'migrations/versions/*inter_agent*'
    'migrations/versions/*project_agent_role*'
    'migrations/versions/*remote_agent*'                     # PG-F-009 追加
)
```

host migration drill 後に `tests/deploy/test_remote_agent_dispatch_denied_audit.py` を再実行 (PG-F-009 fix).

#### §11.7 既存正本の host-portable 同期 (PG-F-001 fix)

SP-022 で以下 file の VPS-only / VPS deploy smoke / UFW-only 表現を host-portable 化:

- `.claude/CLAUDE.md` §6.5.3 (本 session で update 済、SP-022 で final review)
- `docs/基本設計/05_ネットワーク境界設計.md` (DD-05): host 別 SOP (Mac pf / Linux UFW / VPS UFW) + Tailscale grants `tag:taskhub-cli` 追加
- `docs/要件定義/01_P0要求定義.md` (本 session §10 で update 済)
- 各 SP-NNN.md の "VPS deploy smoke" を "selected host deploy smoke" に rename
- `docs/設計検討/計画(仮).md` の VPS 前提も same update

### §12: MEDIUM 11 件 patch

#### §12.1 frontend service portable 化 (PG-F-005)

§2 docker-compose.yml に frontend (Next.js) service 追加:

```yaml
services:
  frontend:
    image: ghcr.io/<org>/taskhub-frontend:${TASKHUB_VERSION:-latest}
    ports:
      - "127.0.0.1:3000:3000"               # 127.0.0.1 bind 維持
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/api/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
    environment:
      NEXT_PUBLIC_API_BASE_URL: ${NEXT_PUBLIC_API_BASE_URL:-https://taskhub.${HOST_NAME}.tail-xxxxx.ts.net}
    depends_on: [api]
```

Tailscale Serve routing で `https://taskhub.<host>.tail-xxxxx.ts.net` → frontend container に proxy.

#### §12.2 DB/Redis を Docker internal expose のみ (PG-F-006 / DD-05 整合)

postgres / redis の `127.0.0.1:5432:5432` / `127.0.0.1:6379:6379` 公開は **撤回**、Docker internal network のみ expose:

```yaml
services:
  postgres:
    # ports: 削除 (internal-only)
    expose:
      - "5432"
  redis:
    expose:
      - "6379"
```

backup / restore は `docker compose exec postgres pg_dump ...` で実行 (host から直接 5432 アクセスしない).

local 開発 (Mac で psql 直接アクセスしたい等) は `docker-compose.override.yml.example` に option として書き、production deploy では絶対不可:

```yaml
# docker-compose.override.yml.example (gitignore)
# WARNING: development only、production / VPS では絶対 enable しない
services:
  postgres:
    ports:
      - "127.0.0.1:5432:5432"
```

#### §12.3 Mac SOP detailed (PG-F-010)

`docs/deploy/host-setup.md` の Mac section に追加:

- power preflight (バッテリー > 30%、電源接続必須)
- `caffeinate -i` の実行主体 (個人 user vs root) と効果範囲
- `pmset -a sleep 0 disablesleep 1` の権限 (sudo 必須) と rollback (`pmset -a sleep 5 disablesleep 0` で元に戻す)
- Docker Desktop restart policy (`always` 設定)
- network interruption 後の `taskhub backup` resume / reject (idempotent flag、partial archive cleanup)
- Mac sleep / network cut の negative drill (SP-012 必須)

#### §12.4 SP-001 reopened/amended (PG-F-011)

SP-001 frontmatter の status / updated_at を update + Review 欄に "Host-Portable amendment (2026-05-10)" 追加. または新 SP-001.5 (`SP-001-5_host_portable_amendment.md`) として分離 → SP-001 既完了分と新規 must_ship を別管理.

判断 (SP-001 着手時に最終): SP-001 が既に SUCCESS_WITH_FOLLOW_UP の場合 → 新 SP-001.5 で amendment Sprint Pack を起票が clean.

#### §12.5 SP-022 rollback automation を non-deferable (PG-F-012)

SP-022 must_ship を update:

- age key failure → automatic rollback (source host service 復旧)
- pg_restore failure → automatic rollback (target volume を `_failed-restore-<ts>/` に保管 + source host thaw)
- network failure → resume (idempotent) or rollback
- 高度 UX / 追加 host pair automation のみ defer 可

#### §12.6 PRD-01 AC-HARD-04 PITR vs pg_dump 整合 (PG-F-013)

PRD-01 §10.3 と ADR-00021 §8 に追記:

「P0 では `pg_dump --format=custom` + Redis RDB を正本、PITR (WAL archiving) は P1 SP-018 以降で別 ADR で導入。RPO は **commit-frequency** ベース (`taskhub backup` 実行 = manual checkpoint、recommend daily で RPO ≤ 24h、bi-daily で RPO ≤ 12h、user 運用判断)」

#### §12.7 CI bypass 検出 fixture (PG-F-014)

SP-012 / SP-022 must_ship に CI bypass scan 追加:

```bash
# scripts/ci/check_host_portable_bypass.sh
# fail-close patterns:
- compose で `--funnel` 検出 → fail
- compose で `0.0.0.0:` host publish 検出 → fail
- compose で non-127 publish 検出 → fail
- docs / scripts に age private key marker (`-----BEGIN AGE`) 検出 → fail
- docs / scripts に raw key path 露出 → fail
- backup tar に `key.txt` / age private 含有 → fail
- secret archive inclusion (`--include-secrets` 旧 flag 名残存) → fail
```

#### §12.8 `taskhub` admin / `tm` user 明確分離 (PG-F-016)

namespace 厳格化:

| CLI | 用途 | install 対象 | scope |
|---|---|---|---|
| `taskhub` (admin) | host setup / backup / restore / migrate / age-rotate / verify | host (server) のみ | local Docker socket access、admin 権限 |
| `tm` (user、ADR-00015) | ticket / approval / run / message / audit / export 等 | 各 client 機械 (Mac / Linux / iPhone Termius) | API 経由、capability token |

SP-001 の Mac 起動 verify は `taskhub status / backup` までに限定。`tm` smoke は ADR-00015/SP-016 側に移送.

#### §12.9 `taskhub verify --integrity` catalog introspection (PG-F-017)

restore 後の verify に PostgreSQL catalog introspection 追加:

```python
# tests/deploy/test_taskhub_verify_integrity.py
def test_postgres_invariants_after_restore():
    # 全 id=uuid + tenant_id=bigint
    assert check_all_id_columns_uuid()
    assert check_all_tenant_id_bigint()
    
    # 複合 FK pattern
    assert check_composite_fk_pattern("(tenant_id, foreign_id)")
    
    # P0.1 で追加された unique
    assert check_unique_exists("agent_runs", ["tenant_id", "project_id", "id"])
    assert check_unique_exists("project_agent_roles", ["tenant_id", "project_id", "id"])
    assert check_unique_exists("memory_records", ["tenant_id", "project_id", "id"])
    
    # event_type 31 種
    assert check_event_type_count(31)
    
    # artifacts.project_id (Phase F-0 で追加予定)
    assert check_column_exists("artifacts", "project_id")
```

#### §12.10 rollback 3 ケース分離 (PG-F-018)

§rollback 手順を 3 ケースに分離:

| case | 内容 | rollback artifact |
|---|---|---|
| **case A**: target restore failure (途中で failure) | target volume を `_failed-restore-<ts>/` に保管、source host thaw | source host の retained backup + source volume snapshot (本 ADR §11.2 freeze marker で source は service down 維持) |
| **case B**: target accepted but healthcheck failed | target で `_pre-restore-<ts>/` に既存 volume 保管中、復元失敗で revert、source thaw | target 側 `_pre-restore-<ts>/` (空、または旧 target data) + source 側 retained backup |
| **case C**: post-cutover source rollback (cutover 後に target で問題発見) | target で full backup 取得 → source host で restore → source thaw → target service down + retain | target で取得した post-cutover backup + source 側 retained backup (3 ヶ月保持) |

各 case の volume / backup file の path を `docs/deploy/host-migration.md` に明示.

### §13: Phase G plan-review 18 finding closure summary

| finding | adopt 反映先 |
|---|---|
| PG-F-001 | §11.7 既存正本 host-portable 同期 |
| PG-F-002 | §11.1 age key 安全運搬 |
| PG-F-003 | §11.2 freeze/drain marker |
| PG-F-004 | §11.3 postgres:16 正本 |
| PG-F-005 | §12.1 frontend portable |
| PG-F-006 | §12.2 DB/Redis internal-only |
| PG-F-007 | §11.4 RTO budget 分離 |
| PG-F-008 | §11.5 multi-agent restore fixture |
| PG-F-009 | §11.6 sealed guard 同期 |
| PG-F-010 | §12.3 Mac SOP detailed |
| PG-F-011 | §12.4 SP-001 amendment |
| PG-F-012 | §12.5 SP-022 rollback non-deferable |
| PG-F-013 | §12.6 AC-HARD-04 PITR 整合 |
| PG-F-014 | §12.7 CI bypass fixture |
| PG-F-015 | §11.1 `--include-sops-env` rename |
| PG-F-016 | §12.8 admin/user CLI 分離 |
| PG-F-017 | §12.9 catalog introspection |
| PG-F-018 | §12.10 rollback 3 ケース |

---

## §14: Phase G adversarial Strengthening Catalog (14 finding 全件 adopt)

Codex adversarial-review (defensive) で 14 review item 全 gap_found、HIGH 10 + MEDIUM 4 = 14 finding。CRITICAL 0、設計の根幹は健在、以下 strengthening を SP-012 / SP-022 / 関連 ADR / file に反映:

### §14.1 HIGH 10 件 strengthening

| # | id | RV | strengthening (実装先) |
|---|---|---|---|
| 1 | PGA-F-001 | RV-G-001 | **age key 運搬を secret manager default-required**: scp/direct write は break-glass 承認付きに限定 (`--break-glass-approval-id` 引数必須)。age key path を Time Machine / iCloud / Dropbox / OneDrive 除外 list に登録 (`taskhub status` で除外設定 verify)。FileVault enabled 検査、permission 600 強制、cloud-sync path に存在検査、backup exclusion 確認。migration audit に key transport method (`secret_manager` / `tailscale_ssh` / `scp`) と approval_id を必須記録 → SP-012 must_ship |
| 2 | PGA-F-002 | RV-G-003 | **backup authenticity = detached signature + signer allowlist**: backup manifest / checksums.txt / postgres dump hash / artifacts Merkle root / freeze_signature を **source host signing key で detached signature**。restore は (a) source_host_id allowlist、(b) signing_key_fingerprint allowlist (`~/.taskhub/trusted_signers/`)、(c) migration_epoch freshness (24h 以内) を全件 verify、いずれか fail で reject + quarantine。tamper detect 時は source re-backup、age rotation、audit incident 自動起票 → SP-012 must_ship |
| 3 | PGA-F-003 | RV-G-002 | **`taskhub thaw` 2-party-control + active registry**: thaw preflight で target active.signed marker の有無、migration_epoch、source_host_id、decommission marker を verify。target active が確認できる場合は **default deny** (再活性化は明示の `--decommission-target` flag + 別 actor approval 必要)。`taskhub active-registry` を signed local ledger or tailnet shared 状態として実装、source/target 同時 active を contract test で reject → SP-012 / SP-022 must_ship |
| 4 | PGA-F-004 | RV-G-004 | **image digest pinning + version matrix**: docker-compose.yml で `postgres:16-alpine@sha256:<digest>` 形式 pin。compose lock file (`docker-compose.lock.yml` 自動生成) を git commit 対象。meta.json に source image digest / server_version_num / pg_dump version / 全 extension version 記録、target restore は exact match (default) または compatible matrix (allowlist) で verify、mismatch は reject → SP-001 / SP-012 must_ship + SP-022 で matrix update process |
| 5 | PGA-F-005 | RV-G-005 | **DB catalog 正本 fingerprint**: `taskhub verify --integrity` に追加 (a) `pg_dump --schema-only` を normalize して sha256、(b) alembic revision file hash 全件、(c) constraint / index / trigger / function checksum、(d) seed table version、(e) policy_profile_action_effects exact 14 rows、(f) standard_role_ids_mirror 10 rows を allowlisted fingerprint と比較、差分は machine-readable diff で出力、reject → SP-012 must_ship |
| 6 | PGA-F-007 | RV-G-007 | **migration state machine + signed journal**: migrate を `prepare → freeze → backup → transfer → restore → verify → cutover → thaw` の 8-phase state machine 化。各 phase の precondition / postcondition / idempotency token / resume condition / rollback target を明文化。**source / target 双方に signed journal** (`~/.taskhub/migration-journal/<epoch>.signed`) を持ち、phase 完了ごとに signed update。network partition でどちらが進行中か journal で判定、conflict 時は manual intervention。SP-012 で network partition fixture (Tailscale 強制切断 + resume / reject 全 case) を must_ship → SP-012 / SP-022 must_ship |
| 7 | PGA-F-010 | RV-G-010 | **sanitizer_policy_versions table + config_hash FK**: `sanitizer_policy_versions(id, config_hash, ruleset_hash, created_at, deprecated_at)` を正本 table 化。memory_records / memory_retrieval_artifacts は **FK + config_hash 両方** を持つ (name 同じでも config_hash 違えば stale)。restore verify で source meta config_hash と target current config を比較、mismatch は (a) retrieval deny、(b) explicit `taskhub re-sanitize` job (background async)、(c) old snippet を `_quarantine/` に隔離 + audit → ADR-00016 update + SP-018 must_ship |
| 8 | PGA-F-011 | RV-G-011 | **SP-013 migration order を hard gate**: artifacts.project_id NOT NULL + unique(tenant_id, project_id, id) が **migration sequence で先に投入されない限り** inter_agent_messages / review_artifacts / memory_records / memory_retrieval_artifacts の migration を **alembic dependency で reject**。`taskhub verify --integrity` で全 artifact_id 参照列の FK target を table-specific に検査 (memory_records.source_artifact_id → artifacts、review_artifacts.review_target_artifact_id → artifacts、inter_agent_messages.source_artifact_id → artifacts) → SP-013 hard gate (must_ship、defer 不可) |
| 9 | PGA-F-012 | RV-G-012 | **Mac selected host hardening baseline**: ADR-00021 に explicit residual risk + incident runbook を追加。Mac selected host **必須条件** (SP-012 acceptance に追加): (a) FileVault enabled、(b) OS patch level current、(c) auto screen lock 5 分、(d) non-admin daily user (Docker only when needed)、(e) Docker socket access = root or specific group、(f) Tailscale device posture (key expiry 90 日、re-auth 必須)、(g) device revoke drill (年 1 回)、(h) age rotation drill (半年 1 回)、(i) provider/GitHub key rotation order documented (incident response runbook)、(j) `~/.taskhub/` 全体を Time Machine 暗号化 backup に含める (Mac OS 復旧時のため、ただし age key は除外) → SP-012 must_ship + `docs/deploy/mac-hardening-baseline.md` |
| 10 | PGA-F-014 | RV-G-014 | **`taskhub verify --network-invariant`**: 一括 runtime check: (a) `docker compose config --no-interpolate` の merged output、(b) `docker ps --format '{{.Ports}}'` で host port、(c) `ss -lntp` で listening port、(d) `tailscale serve status --json` で Funnel 不使用 verify、(e) public IP probe (`curl -s ifconfig.me` + 自分の public IP に対して 22/80/443 が外部から到達不可 verify)、(f) tailnet grants (`tailscale acl get`) で `tag:taskhub*` のみ確認。production selected host では development override の DB/Redis 127.0.0.1 ports / `tailscale serve --funnel` を **hard fail** → SP-012 / SP-022 must_ship + CI bypass scan 拡張 |

### §14.2 MEDIUM 4 件 strengthening

| # | id | RV | strengthening |
|---|---|---|---|
| 1 | PGA-F-006 | RV-G-006 | **artifact write atomicity**: artifact writes は temp file + fsync + atomic rename + DB commit ordering を contract 化 (`backend/app/services/artifact/store.py` で実装)。Redis `appendonly yes` + `appendfsync everysec` (or `always` for higher safety、performance trade-off は SP-022 で計測)。Mac runtime preflight で `pmset -g` から sleep / powernap / wakeonlan setting を hard fail check (`taskhub status --mac-preflight`)。post-crash reconciliation test (artifact write 中に kill -9 → 再起動 → integrity verify) を SP-012 に追加 |
| 2 | PGA-F-008 | RV-G-008 | **uid/gid remapping**: backup meta.json に service user logical name + expected uid/gid + path mode policy を保存。restore は target image から uid/gid を解決して remap (`docker compose run --rm postgres chown -R postgres:postgres /var/lib/postgresql/data`)。`taskhub verify --integrity` で artifact create / read / hash / delete を実操作で確認、postgres data dir permission (`750 postgres:postgres`) と redis dir permission を実 check |
| 3 | PGA-F-009 | RV-G-009 | **inter_agent_messages consumed invariant fixture**: SP-015 / SP-022 に追加 — DB query で `consumed_at IS NOT NULL` の場合は (a) consumed_by_run_id NOT NULL、(b) AgentRunEvent event_type=29 (`inter_agent_message_consumed_ref`) が exactly one、(c) audit_events `inter_agent_message_consumed` が exactly one を verify。unconsumed は consumed_* 全 NULL。expired は denial event のみ。restore 後に `taskhub verify --integrity --multi-agent` で全 row check |
| 4 | PGA-F-013 | RV-G-013 | **drill timer alert-only enforcement**: `scripts/ci/check_drill_timer_alert_only.sh` を追加、systemd timer / cron entry の ExecStart が `notify` / `slack-cli` / `osascript` 等の通知 command 以外 (例: `taskhub migrate ...`) なら fail。`taskhub migrate` は **`--approval-id <id>` + signed human approval record (`~/.taskhub/approvals/<id>.signed`) を必須化**、cron / systemd 環境変数 (`SYSTEMD_INVOCATION` 等) を検出すると default deny (`--from-automation` 明示 + signed approval 必要)。SP-022 で運用 SOP 化 |

### §14.3 14 finding closure plan

| finding | 実装先 |
|---|---|
| PGA-F-001〜005 | SP-012 must_ship + ADR-00021 §11 / §14.1 反映 |
| PGA-F-006〜009 | SP-012 / SP-015 / SP-022 must_ship + ADR-00016 update (sanitizer_policy_versions FK) |
| PGA-F-010 | ADR-00016 update + SP-018 must_ship |
| PGA-F-011 | SP-013 hard gate (defer 不可) |
| PGA-F-012 | SP-012 must_ship + 新規 `docs/deploy/mac-hardening-baseline.md` |
| PGA-F-013 | SP-022 must_ship + `scripts/ci/check_drill_timer_alert_only.sh` |
| PGA-F-014 | SP-012 / SP-022 must_ship + CI bypass scan 拡張 |

### §15: Phase G review summary

- **Phase G plan-review (R1)**: 18 finding 全件 adopt → §11/§12/§13
- **Phase G adversarial-review**: 14 finding 全件 adopt → §14.1/§14.2/§14.3
- **計 32 finding 全件 adopt**、CRITICAL 0、設計の根幹は健在
- 残作業: 関連 file (SP-001/012/022 + ADR-00016 + DD-05 + PRD-01) への strengthening 反映 (Phase G-5 で実施)
- 公開化 (P3+) 着手前に Phase H (codex-second-opinion) で再 verify 推奨
