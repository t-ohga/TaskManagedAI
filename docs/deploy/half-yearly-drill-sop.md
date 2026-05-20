# 半年 drill scheduling SOP (ADR-00021 §14.2 #4 PGA-F-013)

最終更新: 2026-05-19 (SP022-T03)

## 1. 目的

TaskManagedAI host migration drill (Mac↔VPS / Linux↔VPS / VPS↔VPS 等) を半年 1 回 **手動実施** するための **scheduling 通知 SOP**。本 SOP の cron / systemd timer は **通知のみ** 担当し、実際の `taskhub migrate` 等 destructive operation は **手動 approval flow** で人間オペレータが kick-off する。

## 2. CI 機械検査 (本 SOP の cron / systemd timer は本 SP-022 で確立した CI gate を通過必須)

`scripts/ci/check_drill_timer_alert_only.sh` (`backend-quality` CI job 内) が以下を機械検査:

- systemd `.timer` file (drill 名 / `docs/deploy/` / `deploy/` / `ops/` 配下のみ scope)
- paired `.service` file (`[Timer] Unit=<X>` で解決、未配置時は **fail-closed**)
- 全 `Exec*=` directive (`ExecStartPre`, `ExecStart`, `ExecStartPost`, `ExecReload`, `ExecStop`, `ExecStopPost`, `ExecCondition`)
- cron file (`crontab` / `**/cron.d/**` / `**/crontabs/**`)
- cron env line (`PATH=` / `SHELL=` / `BASH_ENV=` / `ENV=` / `LD_PRELOAD=` / `LD_LIBRARY_PATH=` / `DYLD_INSERT_LIBRARIES=` は **fail-closed**)

allowlist (notification command head): `notify-send` / `osascript` / `slack-cli` / `slack` / `discord-cli` / `discord` / `mail` / `sendmail` / `echo` / `printf` / `logger`。

**重要 (R1 F-001 adopt)**: `curl` は本 SP022-T03 では allowlist に含まれない (`curl http://target/destroy?id=1` 等 destructive endpoint POST が pass する risk のため)。webhook 用途は `slack-cli` / `discord-cli` / `mail` を採用、curl は post-T03 SP-022.X で URL allowlist + method 制限の安全な拡張を判断。

denylist (defense-in-depth、絶対禁止): `taskhub migrate/restore/age-rotate/backup` / `docker compose down|stop|kill|rm` / `docker volume rm|prune` / `kubectl delete|scale` / `pg_dump|restore|basebackup|drop` / `dropdb` / `createdb` / `psql ... DROP|TRUNCATE|DELETE` / `redis-cli flushall|flushdb` / `rm -rf` / `find ... -delete` / `unlink` / `dd` / `mkfs` / `truncate` / `kill -9` / `pkill -9` / `systemctl stop|restart|kill|disable|poweroff|reboot` / `shutdown` / `reboot` / `poweroff` / `halt`。

shell composition (絶対禁止): `$(...)` / backtick / `;` / `&&` / `||` / `|` / `>` / `>>` / `<` (input redirect) / `<<` / `<<<` / `&` / 改行。

path spoofing (絶対禁止): command path に `/` を含む場合は `TRUSTED_PATH_PREFIXES` (`/usr/bin/`, `/usr/local/bin/`, `/bin/`, `/usr/sbin/`, `/sbin/`, `/opt/homebrew/bin/`, `/opt/local/bin/`) のいずれかで始まる絶対 path のみ pass。`./` / `~/` / `/tmp/` / `/home/<user>/...` は fail-closed。

## 3. systemd timer 構成例 (Linux 環境)

`docs/deploy/taskhub-drill-alert.timer`:

```ini
[Unit]
Description=Half-yearly host migration drill alert

[Timer]
# 毎年 1/1 と 7/1 9:00 (systemd.time(7) calendar event 形式)
# 検証コマンド: systemd-analyze calendar '*-01,07-01 09:00:00'
OnCalendar=*-01,07-01 09:00:00
Persistent=true
Unit=taskhub-drill-alert.service

[Install]
WantedBy=timers.target
```

`docs/deploy/taskhub-drill-alert.service`:

```ini
[Unit]
Description=Half-yearly drill alert sender

[Service]
Type=oneshot
# !! allowlist 内 command + trusted absolute path のみ !!
# !! taskhub migrate / restore は絶対禁止、shell composition も禁止 !!
ExecStart=/usr/local/bin/slack-cli chat send --channel taskhub-ops "Half-yearly host migration drill due. See docs/deploy/half-yearly-drill-sop.md"
```

検証手順 (R1 F-015 adopt):

```bash
# OnCalendar expression の妥当性確認
systemd-analyze calendar '*-01,07-01 09:00:00'
# expected: Next elapse / Iterations 表示
```

## 4. cron 構成例 (Mac / Linux)

> **Note (PR #71 R1-003 adopt)**: 本 SOP 内の cron file example path は scanner の `SCAN_CRON_GLOBS` (`**/cron.d/**`) が match する命名規則と一致させる必要あり。dir name は必ず `cron.d` (e.g., `docs/deploy/cron.d/`)。`taskhub-drill-cron.d/` 等 prefix 付き dir は scanner glob で match しないため使用禁止。

`docs/deploy/cron.d/drill-alert`:

```cron
# 半年 drill alert (毎年 1/1 と 7/1 9:00)
# !! MAILTO は許可 env、PATH/SHELL/BASH_ENV は drill scheduling では絶対禁止 !!
# !! PR71 R3-001 adopt: cron.d directory 配下は system-crontab 形式 (5 schedule + user + cmd)。
#    本 example は `root` を user として明示、5-field user crontab と区別する。
MAILTO=ops@example.com
# PR71 R4-004 adopt: osascript の -e は 1 つの statement 引数を要求、AppleScript 全体を quote 必須
# PR71 R4-005 (P1) adopt: scanner が `-e` payload を `display notification ...` 限定 verify
0 9 1 1,7 * root /usr/bin/osascript -e 'display notification "Half-yearly drill due" with title "TaskManagedAI"'
0 9 1 1,7 * root /usr/local/bin/slack-cli chat send --channel taskhub-ops Half-yearly drill due
```

`PATH=` を **意図的に省略**: cron は default で `/usr/bin:/bin` を持つ、PATH spoofing 経路を発生させないため (本 SOP では trusted absolute path 推奨)。

## 5. 手動 approval flow (drill 実行時)

1. **通知受領** (Slack / osascript notification): scheduling timer が allowlist command で通知を発火
2. **オペレータ作業開始**: 本 SOP (`docs/deploy/half-yearly-drill-sop.md`) を再読、`docs/adr/00021_host_portable_deployment.md` §3 (admin CLI) / §8 (RTO≤4h drill table) / §11 (split-brain prevention) も確認 (PR71 R1-006 adopt: 旧 `docs/deploy/host-migration.md` reference は repo に未配置のため ADR-00021 と Sprint Pack に置換)
3. **approval ID 生成**:
   ```bash
   taskhub approval issue --reason "half-yearly drill 2026-07-01" --decider <human-name>
   # → output: approval_id=drill-2026-07-01-<sha8>
   ```
4. **signed approval record 作成** (`~/.taskhub/approvals/drill-2026-07-01-<sha8>.signed`):
   - 内容: `approval_id` / `decider` / `reason` / `signed_at` (UTC) / `drill_kind` (`host_migration_mac_vps` 等) / `signature` (Ed25519 signing key、SOPS age で管理)
   - 詳細 schema は SP022-T02 で確定 (本 SOP は planned contract、§6 参照)
5. **drill kick-off** (手動 shell invoke):
   ```bash
   taskhub migrate --target t-ohga-vps --approval-id drill-2026-07-01-<sha8> --from-automation
   ```
   - `--from-automation` 明示で、cron / systemd 環境変数 (`SYSTEMD_INVOCATION` 等) 経由でない (手動 shell invoke) ことを confirm
6. **drill 実行**: `taskhub migrate` が approval ID + signed record verify、Tailscale 経由で backup → restore → smoke → RTO 計測
7. **drill 完了報告**: Slack channel に結果投稿、`~/.taskhub/drills/<date>/result.json` に記録 (`rto_minutes` / `rollback_invoked` / `errors` 等)

## 6. 異常時 escalation

- **drill 完了せず** → オペレータが Slack channel `#taskhub-ops` で escalation 表明、ADR-00021 §3 / §11 rollback 経路 (`taskhub freeze` / `taskhub thaw` で split-brain prevention、source host service resume) を参照 (PR71 R1-006 adopt)
- **rollback 必要** → `taskhub migrate --rollback --approval-id <id>` (SP022-T02 で実装、本 SOP は仕様明文化のみ)
- **approval signature verification 失敗** → drill kick-off reject、SecretBroker audit event 発火 (raw secret なし、SP-004/006 SecretBroker boundary 経由)
- **Tailscale connection lost** → drill abort、source host の service を resume (`taskhub thaw`、SP-012 batch 7 で skeleton)、24h 以内に retro 実施

## 7. signed approval Ed25519 verify (SP022-T02 Phase 1 で normative 化、F-R1-006 + R3 adopt: 節分割)

### 7.1 normative invariants (SP022-T02 Phase 1 で実装完了、`scripts/taskhub_signed_approval.py`)

以下は **normative spec** (`scripts/ci/check_phase_e_trace.sh` / `tests/scripts/test_taskhub_signed_approval.py` で機械検査済):

- `--approval-id <id>` (`~/.taskhub/approvals/<id>.signed`) の Ed25519 signature verify (RFC 8785 strict JCS canonical JSON、原 datetime 文字列保持)
- approval_id allowlist (`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`) + path traversal deny + record-CLI ID 一致 verify
- destructive subcommand 6 件 (`backup` / `restore` / `migrate` / `freeze` / `thaw` / `age-rotate`) の **default deny** (manual exec も含む、Phase 1 では `--allow-unsigned-manual-skeleton` skeleton-only escape あり、Phase 2 で削除予定)
- automation detection (`SYSTEMD_INVOCATION_ID` / `CRON_INVOCATION` / `GITHUB_ACTIONS` / `CI` / `BUILD_ID` 等 12 env var matrix + TTY absence)、検出時に `--from-automation` 明示 + `--approval-id` 両方必須
- approval record fields: `approval_id` / `decider` / `reason_summary` (allowlist) / `signed_at` (strict UTC `Z`) / `expires_at` (strict UTC `Z`、48h max_ttl) / `drill_kind` (8 enum) / `allowed_subcommands` (drill_kind 上限照合) / `target_host` (migrate で non-empty + exact match 必須) / `signature` (strict base64 + 64-byte)
- Ed25519 verify key (`~/.taskhub/keys/approval-verify-key.pub`) の owner/mode permission check + repo-internal SHA-256 fingerprint allowlist (`.taskhub/approval-verify-key-fingerprints.allowlist`) hard fail verify
- audit event payload allowlist 方式 (raw signing key / raw signature / raw `reason` 不在)、reason_code 24 種、stderr scaffold (Phase 2 で SecretBroker-mediated audit sink に置換予定)

### 7.2 planned (Phase 2-4 carry-over)

以下は **planned**、SP022-T02 Phase 2-4 で実装:

- 実 backup / restore / migrate / freeze / thaw / age-rotate I/O 配置 (Phase 2-4)
- SecretBroker-mediated audit sink integration (Phase 2)
- approval consumption ledger (one-time approval marker、Phase 2)
- age key rotation 自動化 (Phase 2-3)
- process tree-based automation detection (Phase 2 ADR Gate 判断)
- `--allow-unsigned-manual-skeleton` escape flag 削除 (Phase 2 実 I/O 配置時に削除、Phase 1 のみ存在)
- `restore` subcommand の `target_host` claim (Phase 2 で `--target-host` argument 追加判断)

## 8. retro Pack (drill 完了後 24h 以内)

drill 完了 (success / failure / abort) 後 24h 以内に retro Pack を `docs/sprints/SP-022_framework_intake_hardening.md` `## Review` に追記:

- drill 日時 (UTC)
- drill_kind (`host_migration_mac_vps` 等)
- approval_id
- rto_minutes (実測)
- rollback_invoked (true / false)
- errors / lessons_learned
- next_drill_target_date (半年後)

## 9. emergency disable (CI gate disable、admin only)

`scripts/ci/check_drill_timer_alert_only.sh` を緊急 disable する場合:

1. admin が GitHub Settings → Variables で `DRILL_TIMER_ALERT_ONLY_CHECK_DISABLED=1` を設定 (PR diff から author 任意 disable 不可)
2. workflow step `if:` 条件で primary skip + shell defense-in-depth で二重 check
3. 設定すると CI log に `audit_marker: emergency_disable=true` / `audit_marker: requires_retro_pack_within_24h=true` / `audit_marker: ADR_PGA=ADR-00021-§14.2-#4-PGA-F-013` が stderr 出力
4. **24h 以内に retro Pack 必須** (`docs/sprints/SP-022_framework_intake_hardening.md` `## Review` に disable 日時 / 理由 / 復旧 commit SHA 記録)

## 10. 関連 ADR / docs

- ADR-00021 §3 / §8 / §14.2 #4 (Host-Portable Deployment + PGA-F-013 drill timer alert-only enforcement)
- ADR-00007 (External Exposure invariant、Tailscale 閉域維持、本 drill 中も不変)
- ADR-00026 (PITR drill、`scripts/pitr_drill.py` で別 drill_kind を確立済)
- SP-022_framework_intake_hardening.md Phase G PGA-F-013 (本 task scope)
- SP022-T02 (`taskhub migrate` 自動化、`--approval-id` 実装、本 SOP §7 で planned contract 明文化)
- SP022-T09 (実機 host migration drill Mac→VPS RTO≤4h PASS、本 SOP を実機 drill 実施時に使用)
- `scripts/ci/check_drill_timer_alert_only.sh` (本 SP022-T03 で実装)
- `tests/deploy/test_drill_timer_alert_only.py` (本 SP022-T03 で 23 pytest fixtures 完備)

## 11. SP022-T09 mandatory drill checklist (SP022-T02 Phase 2 / T08 batch 2 で正本化、F-014 adopt)

`taskhub backup` real I/O orchestration (SP022-T02 Phase 2 / T08 batch 2 PR #77) の actual tool 実行 validation は **SP022-T09 実機 host migration drill で必須実施**。autonomous test session では subprocess mock のみで test 済、real validation は本 checklist が cover。

T09 drill 完了時に以下 7 項目を **全件 PASS** で確認、いずれかが fail なら drill 全体を fail (T09 完了不可):

1. **Actual `taskhub backup` 実行**: signed approval record (Ed25519 verify key fingerprint allowlist 登録済) を準備 + `taskhub backup --output <path>.tar.age --approval-id <id>` で real backup を生成、exit code 0 + output file 存在を verify
2. **Age decrypt dry-run**: `age -d -i ~/.taskhub/keys/age.key.txt <path>.tar.age` で age 復号成功を verify、復号後 tar file が tar listing で parse 可能
3. **Tar listing 確認**: `tar -tf <decrypted>.tar` 出力に ADR-00021 §4 file structure (meta.json / checksums.txt / postgres/pg_dump.dump / postgres/alembic_version.txt / redis/dump.rdb / artifacts/...) が全件存在
4. **Checksums verify**: `cd <extract> && sha256sum -c checksums.txt` で全 file の sha256 が一致 PASS
5. **pg_restore 互換確認**: `pg_restore --list <pg_dump.dump>` で custom format binary が parse 可能、actual `pg_restore --create -d <new_db>` 実行 (T02 Phase 3 restore 実装後に full verify、本 T09 では list parse のみ)
6. **Private key 非混入確認**: `tar -tf <decrypted>.tar | grep -E '(id_rsa|id_ed25519|age-key|keys\.txt|\.private\.pem)'` で 0 件、`tar -xOf <decrypted>.tar ... | head -c 1024 | grep -E '(BEGIN OPENSSH PRIVATE|AGE-SECRET-KEY-)'` で 0 件 (CRITICAL invariant、F-001 adopt 検証)
7. **Cleanup verify**: backup 完了後に `ls /tmp/taskhub-backup-*` で 0 件 (tmp dir cleanup 確実、F-002 adopt 検証)、`ls <output>.tar.age.part` で 0 件 (partial output 非残存、F-005 adopt 検証)

各項目の結果は `~/.taskhub/drills/<date>/checklist-results.json` に記録、retro Pack で SP-022 `## Review` に追記。
