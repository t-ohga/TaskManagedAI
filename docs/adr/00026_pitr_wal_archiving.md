---
id: ADR-00026
title: "PostgreSQL WAL archiving + PITR adoption (AC-HARD-04 backup_restore_rpo_rto activation)"
status: "accepted"
adopted_on: 2026-05-17
sprint_pack: "SP-011-5"
related_sprints:
  - "SP-011_eval_harness"        # BL-0159 skeleton (Sprint 11 で fixture contract)
  - "SP-012_p0_acceptance"        # BL-0144 で actual RPO/RTO measurement (P0 Exit gate)
adr_refs:
  - "ADR-00006 (Secrets management、既 accepted): WAL backup 暗号化は SOPS age key 経由"
  - "ADR-00008 (Destructive operation、既 accepted): runner scope、本 ADR は backup/restore scope で別途"
  - "ADR-00007 (External exposure、既 accepted): Tailscale staging restore drill は tag:taskhub 内のみ"
gate_criteria:
  - "#8 破壊的操作 / migration / tenant data 移行"   # PITR は data restore 経路
  - "#6 Secrets management"                          # WAL backup 暗号化
break_glass: false  # ADR Gate Criteria 11 種は break-glass 対象外
---

# ADR-00026: PostgreSQL WAL archiving + PITR adoption

## 背景

AC-HARD-04 `backup_restore_rpo_rto` Hard Gate (P0 Exit 必須) を達成するため、PostgreSQL の **WAL archiving + Point-in-Time Recovery (PITR)** を P0 backup 戦略として採用する。

- Sprint 11 BL-0159 で **fixture contract skeleton** (1 drill_kind = `dev_restore`) を完成
- Sprint 11.5 batch 3a (本 ADR 採用 + BL-0137 / BL-0159b) で **3 drill_kinds activation** (`dev_restore` + `private_staging_restore` + `pitr`)
- Sprint 12 BL-0144 で **actual RPO/RTO measurement** (host migration drill 内で integration verify)

PRD-01 line 210 (RPO ≤24h / RTO ≤4h) + Pack SP-011-5 line 148/152 (P0 blocker) を満たすため、本 ADR で WAL archiving + PITR の admin manual + script 経路を accepted 化する。

## 決定対象

P0 backup 戦略として:
1. PostgreSQL `wal_level = replica` + `archive_mode = on` + `archive_command = 'cp %p /var/lib/postgresql/wal_archive/%f'` (filesystem archive)
2. `pg_basebackup` daily cron (JST 02:00、24h RPO 達成)
3. PITR drill weekly (staging Tailscale 経由、`tag:taskhub` 内のみ)
4. WAL archive + base backup の SOPS age key 暗号化 (ADR-00006 既 accepted scope 内)

## 選択肢

### A: WAL archiving + PITR (**採用**)

- ✅ RPO ≤24h 達成 (daily base backup + WAL incremental)
- ✅ RTO ≤4h 達成 (staging restore drill weekly、production VPS で 4h 以内 restore 可)
- ✅ Point-in-time recovery 可能 (任意 timestamp への restore)
- ✅ ADR-00006 SOPS age key 暗号化と整合
- ⚠️ disk usage 増加 (mitigation: 7 day retention + monthly off-site backup)

### B: pg_dump 定期 (**却下**)

- ❌ point-in-time recovery 不可 (snapshot only、WAL replay なし)
- ❌ RPO 24h は achievable だが backup window 内 transaction loss
- ✅ disk usage 小 (pg_basebackup より dump file 小)
- ❌ AC-HARD-04 PITR field を満たせない

### C: Logical replication + standby (**却下**)

- ❌ P0 single-VPS scope に対し overhead 大 (replica VPS 必要、cost + maintenance)
- ✅ RPO 0 達成 (replica streaming)
- ❌ ADR Gate Criteria #7 外部公開 (replica VPS が tailnet 越し) で別途検討必要
- ❌ Sprint 12 host migration drill 範囲外

## 採用案

**A: WAL archiving + PITR** を採用。本 ADR で以下を accepted:

### Configuration (admin manual setup)

```ini
# /etc/postgresql/16/main/postgresql.conf
wal_level = replica
archive_mode = on
archive_command = 'cp %p /var/lib/postgresql/wal_archive/%f'
max_wal_size = 1GB
min_wal_size = 80MB
archive_timeout = 3600  # 1h 内に WAL flush 強制
```

### Cron schedule (daily base backup、weekly PITR drill)

```cron
# /etc/cron.d/taskmanagedai-backup
# daily base backup (JST 02:00 = UTC 17:00)
0 17 * * * postgres /usr/local/bin/pg_basebackup -D /var/lib/postgresql/backups/$(date -u +%Y-%m-%d) -X fetch

# weekly PITR drill (JST Sun 04:00 = UTC Sat 19:00、staging restore)
0 19 * * 6 root /opt/taskmanagedai/scripts/pitr_drill.py --staging --weekly
```

### Retention

- **Local 7 day**: `/var/lib/postgresql/backups/` (daily) + `/var/lib/postgresql/wal_archive/` (WAL)
- **Monthly off-site**: Tailscale `tag:taskhub` 経由で staging VPS に rsync (本 ADR 範囲、SOPS age key 暗号化済 file 転送)

### 3 drill_kinds (BL-0159b activation)

1. **dev_restore**: local dev DB に base backup を restore (Docker volume 経由)
2. **private_staging_restore**: Tailscale staging VPS に base backup を rsync + restore
3. **pitr**: point-in-time recovery (任意 timestamp + WAL replay)

各 drill_kind は `scripts/pitr_drill.py --kind <drill_kind>` で manual run (Sprint 12 host migration drill で integration verify)。

### Actor binding (Codex/plan-reviewer WARN-4 adopt)

- **cron user**: `postgres` system user (base backup) + `root` (PITR drill rsync)
- **manual admin trigger**: `root` のみ (production VPS は Tailscale SSH 経由、admin actor のみ)
- AI / runner / GitHub Actions runner からの trigger 経路は **存在しない** (deny-by-default)

## 却下案

- B: pg_dump (point-in-time recovery 不可)
- C: Logical replication (P0 scope 過大)

## リスク

| risk | mitigation |
|---|---|
| WAL archive disk full | 7 day retention + monthly off-site backup + cron で disk usage alert (BL-0135 batch 2 で確立済 alert kind) |
| restore drill 失敗 | weekly staging drill + Sprint 12 host migration drill で final integration verify |
| WAL archive corruption | `pg_basebackup` daily 取得で base backup から WAL replay 経路 redundancy 確保 |
| SOPS age key 紛失 | ADR-00006 secret rotation drill (batch 3b) で age key rotation path 確認 |

## Rollback

1. `postgresql.conf` revert (`wal_level = minimal` + `archive_mode = off`)
2. `/var/lib/postgresql/wal_archive/` directory を `wal_archive_legacy/` に rename (削除せず evidence 保持)
3. cron job 削除 (`/etc/cron.d/taskmanagedai-backup` revert)
4. ADR-00026 status を `accepted` → `superseded` に変更
5. `_REQUIRED_DRILL_KINDS` を 1 (skeleton `dev_restore` のみ) に戻す (aggregator)
6. fixture `expected_pitr_success` を false に戻す

## 実装対象ファイル (Sprint 11.5 batch 3a)

- `docs/adr/00026_pitr_wal_archiving.md` (本 ADR)
- `scripts/wal_archiving_check.py` (WAL lsn + archive lag report)
- `scripts/pitr_drill.py` (dry-run + real-run + restore verify)
- `docs/設計検討/pitr_runbook.md` (admin manual)
- `backend/app/services/eval/hard_gates/backup_restore.py` (3 drill_kinds activation)
- `eval/ops/backup_restore/manifest.json` + `public_regression/sample.json` (3 drill_kinds + expected_pitr_success)
- `tests/scripts/test_wal_archiving_check.py` + `test_pitr_drill.py` (script logic unit test)
- `tests/eval/test_hard_gates_backup_restore.py` (3 drill_kinds activation test)

## テスト指針

### P0 (Sprint 11.5 batch 3a) — fixture envelope activation のみ

- WAL lsn parse + archive lag computation (unit test)
- PITR drill dry-run plan output (unit test、subprocess mock)
- 3 drill_kinds activation (aggregator skeleton 1 → activation 3、dataset_version bump)
- Pydantic ContextModel validation
- raw secret reject (admin manual に raw secret / Tailscale auth key を書かない invariant、plan-reviewer WARN-3 adopt)

### P0 (Sprint 12 BL-0144) — actual RPO/RTO measurement (defer)

本 ADR の P0 scope では fixture envelope activation のみ、**actual RPO/RTO measurement は Sprint 12 BL-0144 host migration drill で integration verify** (Codex/plan-reviewer WARN-2 adopt)。Sprint 12 で:
- Actual `pg_basebackup` 実行 + WAL replay
- RPO ≤24h / RTO ≤4h measurement (実 timing)
- 3 drill_kinds の each に対する production VPS smoke

### Sprint 11.5 batch 3b 連携

- BL-0138 secret rotation drill が SOPS age key rotation を含む → WAL backup 暗号化 key の rotation cycle 整合 (ADR-00006 secret rotation drill scope 内)

## 関連 Sprint Pack

- SP-011 BL-0159 (skeleton): fixture contract 完成
- SP-011-5 batch 3a (本 ADR + BL-0137 + BL-0159b): activation
- SP-012 BL-0144: actual measurement (host migration drill)
- SP-022: cloud off-site backup (S3 / Backblaze 等、P1 scope)

## 関連 ADR

- ADR-00006 (Secrets management): SOPS age key 暗号化 (本 ADR の WAL/backup 暗号化 path)
- ADR-00007 (External exposure): Tailscale `tag:taskhub` 内のみ staging restore
- ADR-00008 (Destructive operation): runner scope、本 ADR は backup/restore scope で別途
