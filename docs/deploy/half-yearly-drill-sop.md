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
ExecStart=/usr/local/bin/slack-cli chat send --channel taskhub-ops Half-yearly host migration drill due. See docs/deploy/half-yearly-drill-sop.md
```

検証手順 (R1 F-015 adopt):

```bash
# OnCalendar expression の妥当性確認
systemd-analyze calendar '*-01,07-01 09:00:00'
# expected: Next elapse / Iterations 表示
```

## 4. cron 構成例 (Mac / Linux)

`docs/deploy/taskhub-drill-cron.d/drill-alert`:

```cron
# 半年 drill alert (毎年 1/1 と 7/1 9:00)
# !! MAILTO は許可 env、PATH/SHELL/BASH_ENV は drill scheduling では絶対禁止 !!
MAILTO=ops@example.com
0 9 1 1,7 * /usr/bin/osascript -e display notification Half-yearly drill due with title TaskManagedAI
0 9 1 1,7 * /usr/local/bin/slack-cli chat send --channel taskhub-ops Half-yearly drill due
```

`PATH=` を **意図的に省略**: cron は default で `/usr/bin:/bin` を持つ、PATH spoofing 経路を発生させないため (本 SOP では trusted absolute path 推奨)。

## 5. 手動 approval flow (drill 実行時)

1. **通知受領** (Slack / osascript notification): scheduling timer が allowlist command で通知を発火
2. **オペレータ作業開始**: `docs/deploy/half-yearly-drill-sop.md` (本 SOP) を再読、`docs/deploy/host-migration.md` も確認
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

- **drill 完了せず** → オペレータが Slack channel `#taskhub-ops` で escalation 表明、`docs/deploy/host-migration.md` rollback 章を参照
- **rollback 必要** → `taskhub migrate --rollback --approval-id <id>` (SP022-T02 で実装、本 SOP は仕様明文化のみ)
- **approval signature verification 失敗** → drill kick-off reject、SecretBroker audit event 発火 (raw secret なし、SP-004/006 SecretBroker boundary 経由)
- **Tailscale connection lost** → drill abort、source host の service を resume (`taskhub thaw`、SP-012 batch 7 で skeleton)、24h 以内に retro 実施

## 7. (planned contract for SP022-T02、本 SOP では仕様明文化のみ)

> **Note**: 本 §7 は **SP022-T02 (`taskhub migrate` 自動化) で実装される planned contract**、本 SP022-T03 では SOP 内 reference として明文化のみ。normative spec / 受け入れ条件は SP022-T02 ticket に記載される。

T02 で実装される `taskhub migrate` は本 T03 SOP の手動 approval flow と整合するため、以下 invariant が **T02 implementation contract** として想定される:

- `--approval-id <id>` 必須、signed approval record `~/.taskhub/approvals/<id>.signed` の Ed25519 signature verify (Ed25519 key 管理は SOPS age 経由を T02 で決定)
- cron / systemd 環境変数 (`SYSTEMD_INVOCATION` / `CRON_INVOCATION` 等) 検出時は default deny、`--from-automation` 明示 + signed approval 両方必須
- signature verify 失敗 → exit 2 + audit event 発火 (raw secret なし、SecretBroker boundary 経由)

詳細仕様 (signature algorithm 選定、approval record schema、audit event payload format 等) は **SP022-T02 ticket で確定**。本 T03 SOP は T02 完了後に正式 invariant に更新する。

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
