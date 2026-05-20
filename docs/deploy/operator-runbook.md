# Operator Runbook (host migration / drill)

SP022-T02 Phase 4 + T08 batch 4 で導入された operator-side workflow の bootstrap +
approval issue + re-sign migration + remote_hosts signed config + Tailscale SSH known_hosts
の SOP.

## §1 approval signing key bootstrap (R1 F-008 + ADV R1 F-006/F-018 adopt)

raw 32-byte seed format. PEM/DER 中間 file は使用しない (page cache / FS journal 残存リスク回避).

```bash
TASKHUB_HOME="${TASKHUB_HOME:-$HOME/.taskhub}"
mkdir -p "$TASKHUB_HOME/keys" && chmod 0700 "$TASKHUB_HOME/keys"

umask 077
python3 - <<'EOF'
import os
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

priv = Ed25519PrivateKey.generate()
seed = priv.private_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PrivateFormat.Raw,
    encryption_algorithm=serialization.NoEncryption(),
)
pub_bytes = priv.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)

taskhub_home = os.environ.get("TASKHUB_HOME", os.path.expanduser("~/.taskhub"))
key_path = os.path.join(taskhub_home, "keys", "approval-signing-key")
fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
try:
    os.write(fd, seed)
    os.fsync(fd)
finally:
    os.close(fd)

pub_path = os.path.join(taskhub_home, "keys", "approval-verify-key.pub")
fd = os.open(pub_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
try:
    os.write(fd, pub_bytes)
    os.fsync(fd)
finally:
    os.close(fd)

# zeroize seed (best-effort、bytes object lifetime は cryptography library 依存)
del seed
EOF

# fingerprint allowlist 登録
PUB_FP=$(python3 -c "
import hashlib, os
with open(os.path.expandvars('$TASKHUB_HOME/keys/approval-verify-key.pub'), 'rb') as f:
    print(hashlib.sha256(f.read()).hexdigest())
")
echo "$PUB_FP" >> "$TASKHUB_HOME/keys/approval-verify-key-allowlist.txt"
chmod 0600 "$TASKHUB_HOME/keys/approval-verify-key-allowlist.txt"

# target host へ verify-key.pub + allowlist のみ配布 (signing key は operator host 保管)
```

## §2 approval issue 手順 (R1 F-017 + ADV R1 F-008 adopt: per-subcommand)

1 approval = 1 destructive subcommand. drill 全体で 3-4 つの approval を順次発行する.

### §2.1 backup approval (drill 開始時、archive 完成前)

```bash
taskhub approval issue \
  --approval-id drill-2026-07-01-backup-abc1 \
  --decider t-ohga \
  --reason-summary "half-yearly-drill_mac-vps_backup" \
  --drill-kind host_migration_mac_vps \
  --allowed-subcommands backup \
  --target-host t-ohga-vps \
  --ttl-hours 24 \
  --backup-output-path "$HOME/.taskhub/backups/drill-2026-07-01.tar.age" \
  --backup-include-sops-env \
  --backup-age-public-key-fingerprint <sha256 of age.pub>
```

### §2.2 restore approval (backup archive 完成後、archive_sha256 計算後)

```bash
ARCHIVE_SHA256=$(sha256sum "$HOME/.taskhub/backups/drill-2026-07-01.tar.age" | cut -d' ' -f1)
taskhub approval issue \
  --approval-id drill-2026-07-01-restore-bcd2 \
  --decider t-ohga \
  --reason-summary "half-yearly-drill_mac-vps_restore" \
  --drill-kind host_migration_mac_vps \
  --allowed-subcommands restore \
  --target-host t-ohga-vps \
  --ttl-hours 24 \
  --restore-input-path "$HOME/.taskhub/backups/drill-2026-07-01.tar.age" \
  --restore-archive-sha256 "$ARCHIVE_SHA256" \
  --restore-age-public-key-fingerprint <same fingerprint> \
  --restore-target-pg-host 127.0.0.1 \
  --restore-target-pg-port 5432 \
  --restore-target-pg-db taskmanagedai \
  --restore-target-pg-user taskmanagedai \
  --restore-target-redis-endpoint 127.0.0.1:6379 \
  --restore-target-artifacts-dir /var/lib/taskhub/data/artifacts \
  --restore-target-artifacts-container-path /app/data/artifacts \
  --restore-target-compose-project taskmanagedai \
  --restore-target-compose-file /home/moltbot/repo/TaskManagedAI/docker-compose.yml \
  --restore-expected-pg-major 16 \
  --restore-expected-alembic-head <revision id>
```

### §2.3 restore-rollback approval (restore 失敗後、snapshot 存在 confirm 後)

ADV R1 F-001 adopt: rollback approval は **upfront issue 不可**、restore が失敗して
snapshot dir が生成されてから issue する.

```bash
PRE_RESTORE_TS=$(ls -1 /var/lib/taskhub/data/_pre-restore-* | sort -r | head -1 | sed 's,.*/_pre-restore-,,')
SNAPSHOT_MANIFEST_SHA256=$(sha256sum "/var/lib/taskhub/data/_pre-restore-${PRE_RESTORE_TS}/snapshot_manifest.json" | cut -d' ' -f1)

taskhub approval issue \
  --approval-id "drill-2026-07-01-rollback-cde3" \
  --decider t-ohga \
  --reason-summary "half-yearly-drill_mac-vps_rollback" \
  --drill-kind host_migration_mac_vps \
  --allowed-subcommands restore-rollback \
  --target-host t-ohga-vps \
  --ttl-hours 24 \
  --rollback-pre-restore-ts "$PRE_RESTORE_TS" \
  --rollback-pre-restore-dir "/var/lib/taskhub/data/_pre-restore-${PRE_RESTORE_TS}" \
  --rollback-snapshot-manifest-sha256 "$SNAPSHOT_MANIFEST_SHA256" \
  --rollback-target-pg-host 127.0.0.1 \
  --rollback-target-pg-port 5432 \
  --rollback-target-pg-db taskmanagedai \
  --rollback-target-pg-user taskmanagedai \
  --rollback-target-redis-endpoint 127.0.0.1:6379 \
  --rollback-target-artifacts-dir /var/lib/taskhub/data/artifacts \
  --rollback-target-artifacts-container-path /app/data/artifacts \
  --rollback-target-compose-project taskmanagedai \
  --rollback-target-compose-file /home/moltbot/repo/TaskManagedAI/docker-compose.yml \
  --rollback-expected-pg-major 16
```

注: reason_summary は `[A-Za-z0-9_-]{1,64}` のみ許可 (空白 / `>` / `<` / `(` / `)` 不可).

## §3 approval revocation (manual)

approval record の revoke CLI は提供しない (ADV R2 F-001 adopt: --force 廃止). 手順:

1. `~/.taskhub/approvals/<approval-id>.signed` を remove (operator host のみ、target host
   には distribution 後の audit copy がある場合は同様に remove)
2. operator log に「revoked: <id> reason: <reason>」を append
3. 新規 approval id (別 8 hex suffix) で再発行

## §4 PR #78 後の既存 approval record migration

本 PR (Phase 4) で `_rfc8785_canonical_payload_bytes` に `restore_rollback_claim` を
sub-record として追加. 既存 PR #75/#77/#78 で生成された approval record (rrc 不在) は:

- migrate / freeze / thaw / age-rotate / backup / restore subcommand では **backward compat 維持** (verify allow)
- restore-rollback subcommand では **deny** (rrc 必須化、`taskhub_signed_approval_restore_rollback_claim_required`)

operator action: rollback approval が必要な drill では §2.3 の手順で新規発行. 既存 record は
保管目的 (audit) で `~/.taskhub/approvals/_archived/` に移動.

## §5 remote_hosts.signed.json bootstrap (R1 F-006/F-007 + ADV R1 F-009/F-011/F-012 + ADV R2 F-003 adopt)

`taskhub status --remote <host>` は `~/.taskhub/remote_hosts.signed.json` を読む.
operator が事前配備 (loader schema + repo helper):

```bash
TASKHUB_HOME="${TASKHUB_HOME:-$HOME/.taskhub}"
MAC_COMPOSE_FILE="$HOME/repo/TaskManagedAI/docker-compose.yml"
MAC_COMPOSE_SHA256=$(sha256sum "$MAC_COMPOSE_FILE" | cut -d' ' -f1)
# Linux / VPS host の compose_file sha256 は secret manager 経由で取得
LINUX_COMPOSE_SHA256="<取得した hex>"
VPS_COMPOSE_SHA256="<取得した hex>"

python3 - <<EOF
import os, json, base64
from scripts.taskhub_signed_approval import canonical_for_signature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

taskhub_home = os.environ.get("TASKHUB_HOME", os.path.expanduser("~/.taskhub"))
key_path = os.path.join(taskhub_home, "keys", "approval-signing-key")

# payload schema = loader schema 完全一致 (ADV R2 F-003 adopt)
payload = {
    "config_version": 1,
    "signed_at": "2026-05-20T10:00:00Z",
    "expires_at": "2026-11-20T10:00:00Z",
    "hosts": {
        "t-ohga-mac": {
            "compose_project": "taskmanagedai",
            "compose_file": "$MAC_COMPOSE_FILE",
            "compose_file_sha256": "$MAC_COMPOSE_SHA256",
            "expected_services": ["api", "worker", "postgres", "redis", "frontend"],
        },
        "t-ohga-linux": {
            "compose_project": "taskmanagedai",
            "compose_file": "/var/lib/taskhub/docker-compose.yml",
            "compose_file_sha256": "$LINUX_COMPOSE_SHA256",
            "expected_services": ["api", "worker", "postgres", "redis", "frontend"],
        },
        "t-ohga-vps": {
            "compose_project": "taskmanagedai",
            "compose_file": "/home/moltbot/repo/TaskManagedAI/docker-compose.yml",
            "compose_file_sha256": "$VPS_COMPOSE_SHA256",
            "expected_services": ["api", "worker", "postgres", "redis", "frontend"],
        },
    },
}

canonical_bytes = canonical_for_signature("remote_hosts.v1", payload)

with open(key_path, "rb") as f:
    priv = Ed25519PrivateKey.from_private_bytes(f.read())
sig = base64.b64encode(priv.sign(canonical_bytes)).decode("ascii")

output = {**payload, "signature": sig}
output_path = os.path.join(taskhub_home, "remote_hosts.signed.json")
fd = os.open(output_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
try:
    os.write(fd, json.dumps(output, indent=2, sort_keys=True).encode("utf-8"))
    os.fsync(fd)
finally:
    os.close(fd)
EOF
```

### §5.1 期限切れ再 issue 手順 (ADV R2 F-003 adopt)

1. 新 expires_at で payload 再生成
2. `~/.taskhub/remote_hosts.signed.json` を `~/.taskhub/remote_hosts.signed.json.expired-<date>` に rename (archive、削除しない)
3. 新 signed config を §5 Python helper で生成
4. 全 target host へ secret manager 経由 push
5. `taskhub status --remote <host>` で smoke test、`remote_status_config_expired` が出なくなることを確認

## §6 SecretBroker boundary 限界 (ADV R1 F-019 adopt)

private key を扱う code path で zeroize 保証:

- raw 32-byte seed は `bytearray` で読み込み、`Ed25519PrivateKey.from_private_bytes()` 後即時 overwrite
- cryptography library 内部 (Ed25519PrivateKey object) の memory 上書きは **library lifecycle 依存** (Python では確実な zeroize 保証なし)
- best-effort: object scope を最小化 (関数内 local 変数のみ)、log / stdout / stderr / artifact に key 由来 bytes を一切出さない
- audit event は fingerprint hash (sha256) のみ含める

## §7 Tailscale SSH 接続 bootstrap (ADV R1 F-016 adopt: known_hosts)

`taskhub status --remote <host>` は `StrictHostKeyChecking=yes` で起動するため、known_hosts
に host entry がない場合 `remote_status_ssh_host_key_untrusted` で fail-closed.

初回 bootstrap:

```bash
# 1. Tailscale で target host が到達可能か確認
tailscale ping t-ohga-vps

# 2. 1 回 manual ssh で host key を fetch (この時だけ accept new)
ssh -o StrictHostKeyChecking=accept-new t-ohga-vps echo OK

# 3. ~/.ssh/known_hosts に entry 追加されたことを verify
grep "t-ohga-vps" ~/.ssh/known_hosts

# 4. 以後は StrictHostKeyChecking=yes で動作
taskhub status --remote t-ohga-vps
```

host key fingerprint mismatch (`@@@@@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!`) の
場合は別途 incident response (operator が `ssh-keygen -R <host>` で除去 → 再 bootstrap).

## §8 destructive operation lock (R3 F-002 + ADV R1 F-002 adopt)

backup / restore / restore-rollback は host-level destructive lock を取得する.

- lock path = `$HOME/.taskhub/locks/destructive-operation.lock` (default)
- env override = `TASKHUB_LOCK_DIR` (multi-user host 対応、e.g., `/var/lock/taskhub/`)
- mode 0o600 + parent dir 0o700 必須
- 同 host 上の 2 並列 destructive subcommand は 2 番目が `destructive_lock_busy` で reject

stale lock 復旧 (lock holder が OS kill / system reboot 等で release 不能になった場合):

```bash
# lock file 内 pid が dead か確認
PID=$(jq -r .pid ~/.taskhub/locks/destructive-operation.lock 2>/dev/null)
ps -p "$PID" || rm -f ~/.taskhub/locks/destructive-operation.lock
```

## §9 key rotation (T09 unblock 前 SP-012 carry-over、ADV R2 F-004 adopt)

approval signing key の rotation SOP (本 PR では single-key 前提、keyring 化は SP-012):

1. new pubkey 生成 (§1 と同手順、別 path で)
2. 全 target host へ new pubkey + 新 fingerprint allowlist を secret manager 経由 push
3. overlap 期間 (1-7 日) は old + new 両方 trust (allowlist に両 fingerprint 登録)
4. remote_hosts.signed.json を new signing key で再 sign + 配布
5. 各 host で `taskhub status --remote <host>` smoke test
6. all clear で old key revoke (allowlist から削除)

本 PR は keyring multi-key support 未実装、上記は **operator 手動 single-key 置換** で対応.
overlap 期間中の dual-trust は SP-012 carry-over.
