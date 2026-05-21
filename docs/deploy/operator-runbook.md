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

---

## §13 approval verify keyring rotation SOP (SP-012 must_ship)

approval verify keyring (`<config_dir>/approval-verify-keyring.signed.json` + `<config_dir>/approval-verify-keys.d/<sha256-hex>.pub`) の管理 SOP。
plan §9.3 R1 F-001/F-007/F-011 + ADR-00029 で導入された signed manifest + multi-key + revocation tombstone を扱う。

> **CLI 状況**: 本 SOP の `taskhub keyring …` は **SP-013 で実装予定の CLI extension** (SP-012 では `scripts/taskhub_keyring.py` の dataclass + verify helper のみ実装)。本 §13 は spec として記述、operator は `python -m scripts.taskhub_keyring …` または下記直接スクリプト経路を使う。

### §13.0 keyring の canonical 構造

```text
<config_dir>/
├── approval-verify-keyring.signed.json     (signed manifest、root-signed)
├── approval-verify-keyring.generations/    (atomic install 用 generation dir)
│   └── <generation_id>/
├── approval-verify-keys.d/                  (Ed25519 raw 32B pubkey、filename = sha256-hex)
│   └── <fingerprint>.pub                    (permission 0o400)
├── approval_keyring_revocation_tombstone.signed.jsonl  (append-only denylist)
└── approvals/issuance_journal.signed.jsonl  (append-only issuance journal)

/etc/taskhub/
├── approval_keyring_root.pub                (root signer pub key、config_dir 外 pin)
├── approval_keyring_root.pub.fingerprint    (sha256、operator が out-of-band で物理 verify)
└── keyring_state.head.signed                (monotonic state anchor、generation / chain hash 記録)
```

`SignedManifestEntry` 各 entry の field (`scripts/taskhub_keyring.py` 正本):
- `fingerprint`: sha256-hex
- `verify_key`: Ed25519 raw 32 bytes (taskhub1<base64> format)
- `status`: `active` / `deprecated` / `revoked` (`KeyStatus` enum)
- `issued_at` / `expires_at` / `deprecated_at` / `revoked_at`: UTC iso8601
- `incident_id` / `revocation_reason_hash`: revoke 時に attach
- `source`: `legacy_single_key` | `keyring_rotation`

root pub key (`/etc/taskhub/approval_keyring_root.pub`) の fingerprint は **out-of-band で operator が物理 verify** (Slack DM / 物理紙 / 別 host secret manager の独立経路)。

### §13.1 scheduled lifecycle expiry SOP (deprecated 化)

**前提**: `expires_at` が 7 日以内の key を計画的に deprecate (status `active` → `deprecated`)。緊急度: 低。
**所要**: ~30 分 (signed manifest 生成 + 全 host deploy + verify)。
**SP-012 base behavior**: `deprecated` key は **authorization_verify (新規 destructive 用) は無条件 reject**、**audit_verify (historical record 検証用) は `record_signed_at < deprecated_at` のみ pass**。

operator 手順 (SP-013 CLI 実装前):
```bash
# step 1: 現 keyring の状態確認 (jq で直接 manifest 読出し)
jq '.entries[] | {fp: .fingerprint[:16], status, expires_at, deprecated_at}' \
  /etc/taskhub/approval-verify-keyring.signed.json

# step 2: 新 key 生成 (offline、operator hardware token 推奨)
#   重要: private key を絶対に標準出力に print しない (terminal history / session log に残らないため)。
#   PEM encrypted file へ permission 0o400 で書込、operator hardware token / SOPS で保護する。
python3 - <<'PYEOF'
from pathlib import Path
import os
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import hashlib, base64

priv = Ed25519PrivateKey.generate()
pub_raw = priv.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)
fp = hashlib.sha256(pub_raw).hexdigest()

# pub key は audit OK (raw 32B)
print(f"fingerprint (sha256-hex): {fp}")
print(f"public_key (taskhub1...): taskhub1{base64.b64encode(pub_raw).decode()}")

# private key は **絶対 print しない**、permission 0o400 で encrypted file に書込
priv_path = Path("/var/tmp/new_authorization_priv.pem")
priv_bytes = priv.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.BestAvailableEncryption(
        os.environb[b"TASKHUB_NEW_KEY_PASSPHRASE"]  # env var で passphrase 渡し
    ),
)
priv_path.write_bytes(priv_bytes)
priv_path.chmod(0o400)
print(f"private key written (encrypted PKCS8): {priv_path}")
print("→ operator: SOPS encrypt + offsite backup + immediate shred /var/tmp/...")
PYEOF
#   生成後の operator アクション:
#     1. SOPS encrypt: sops --encrypt --age "$RECIPIENTS" /var/tmp/new_authorization_priv.pem > .../priv.sops.pem
#     2. 元 file 削除: shred -u /var/tmp/new_authorization_priv.pem
#     3. fingerprint を out-of-band で record

# step 3: deprecated_at を旧 key の entry に書込、新 entry を append (offline で manifest 編集)
# operator が signed_at / expires_at / generation increment / previous_committed_manifest_hash 更新
# (SP-013 CLI 実装で `taskhub keyring add-key/remove-key --apply` 化予定)

# step 4: root 私 key で再 sign + 全 host に rsync deploy
# (out-of-band で root signing、operator hardware token 経由)

# step 5: 各 host で verify (scripts/taskhub_keyring.py の verify_signed_manifest 直接呼出)
#   重要: scripts/taskhub_keyring.py は top-level `import taskhub_active_registry`
#   (sibling module 直接 import) を行うため、`PYTHONPATH=/opt/taskhub/scripts` を
#   ssh remote env で設定して `from taskhub_keyring import ...` (NOT `from scripts.taskhub_keyring`)
#   する。bash quote 衝突回避のため heredoc + ssh stdin pattern を使う。
#   production deployment 規約: repo は `/opt/taskhub` に配置、`/opt/taskhub/scripts` は PYTHONPATH 必須。
for HOST in vps linux mac; do
  ssh "$HOST" "PYTHONPATH=/opt/taskhub/scripts:/opt/taskhub python3 -" <<'PYEOF'
import sys, json
from pathlib import Path
from taskhub_keyring import verify_signed_manifest, SignedKeyringManifest
manifest_path = Path("/etc/taskhub/approval-verify-keyring.signed.json")
root_path = Path("/etc/taskhub/approval_keyring_root.pub")
manifest = SignedKeyringManifest.from_json(json.loads(manifest_path.read_text()))
root_pub = root_path.read_bytes()
ok, reason = verify_signed_manifest(manifest, root_pub)
print(f"verify: ok={ok} reason={reason}")
sys.exit(0 if ok else 1)
PYEOF
done
```

**verify 失敗時**: 旧 manifest の `generation - 1` snapshot に rollback (signed_manifest.previous_committed_manifest_hash で chain 復旧可能)。snapshot は `approval-verify-keyring.generations/<old-gen>/` に保存されている。

### §13.2 emergency revocation SOP (revoked 化)

**前提**: key compromise / leak detection / `secret_canary_detected` 等で **即座** に revoke 必要。緊急度: 最高。
**所要**: ~15 分 (signed tombstone 生成 + 全 host push + verify、out-of-band approval 含む)。
**SP-012 base behavior**: `revoked` key は **authorization_verify + audit_verify 両方とも `record_signed_at` 関係なく無条件 reject** (compromise の場合、過去 sign された record も信用しない)。

```bash
# step 1: 即座 freeze (write 停止、source host)
taskhub freeze --reason "key compromise: <fingerprint[:16]>"

# step 2: revoke approval を取得 (operator 二人以上の独立承認、out-of-band)
#   - approval_id 生成 + claim hash + signed approval を取得

# step 3: revocation_tombstone entry を tombstone log に append (append-only)
# (SP-013 CLI 実装で `taskhub keyring revoke-key --apply` 化予定。
#  現状は offline で signed manifest 編集 + tombstone log 追記)
INCIDENT_ID="incident-$(date +%Y%m%d-%H%M)"
EVIDENCE_HASH=$(sha256sum incident-report.md | awk '{print $1}')

# 4-1: signed manifest の対象 entry に revoked_at + incident_id + revocation_reason_hash を書込
# 4-2: approval_keyring_revocation_tombstone.signed.jsonl に新 line を append (root signed)
# 4-3: generation 増分 + previous_committed_manifest_hash 更新 + 再 sign

# step 4: 全 host に revoked keyring を push (Tailscale SSH + rsync allowlist 経由)
for HOST in vps linux mac; do
  rsync -avz --chmod=F0400 /etc/taskhub/approval-verify-keyring.signed.json \
    /etc/taskhub/approval_keyring_revocation_tombstone.signed.jsonl \
    "$HOST:/etc/taskhub/"
  # PYTHONPATH + heredoc pattern (§13.1 step 5 と同 reasoning、bash quote 衝突回避)
  ssh "$HOST" "PYTHONPATH=/opt/taskhub/scripts:/opt/taskhub python3 -" <<'PYEOF'
import sys, json
from pathlib import Path
from taskhub_keyring import verify_signed_manifest, SignedKeyringManifest
manifest_path = Path("/etc/taskhub/approval-verify-keyring.signed.json")
root_path = Path("/etc/taskhub/approval_keyring_root.pub")
manifest = SignedKeyringManifest.from_json(json.loads(manifest_path.read_text()))
root_pub = root_path.read_bytes()
ok, reason = verify_signed_manifest(manifest, root_pub)
print(f"verify: ok={ok} reason={reason}")
sys.exit(0 if ok else 1)
PYEOF
done

# step 5: incident response (§17 参照)
#   - audit log 全件 review (該当 fingerprint 経由 sign された approval / mutation 全件)
#   - 該当 host の DB snapshot 保存 (forensic)
#   - 関連 service の credential rotation
```

**`status=deprecated` と `status=revoked` の違い** (`scripts/taskhub_keyring.py:KeyStatus` enum 正本):
- `deprecated`: scheduled lifecycle expiry、authorization_verify は無条件 reject、`audit_verify` は `record_signed_at < deprecated_at` の record のみ pass (PR #75-#80 で署名済 record の verify 継続用)。reason_code = `taskhub_signed_approval_keyring_key_expired`
- `revoked`: tombstone log に append、authorization_verify + audit_verify 両方とも無条件 reject (`record_signed_at` 関係なし)。reason_code = `taskhub_signed_approval_keyring_key_revoked`

### §13.3 legacy approval verify_key migration

PR #78 以前の approval record (single-key、`<config_dir>/approval-verify-key.pub`) を multi-key keyring に migrate。`scripts/taskhub_keyring.py` の loader は **read-only normalize して decode** (ファイル自体は書き換えない)、本 SOP で migration を別途実施。

```bash
# step 1: legacy single key を keyring の initial entry として import (source = legacy_single_key)
# 既存 single pubkey file を読み、KeyringRotationApprovalClaim.bootstrap で signed manifest を生成
# (SP-013 CLI 実装で `taskhub keyring bootstrap --legacy-not-before <date>` 化予定)

# step 2: legacy_not_before 必須 (§9.4 R2 F-004):
#   - 既存 single-key で sign された全 approval record の signed_at min を計算
#   - LEGACY_NOT_BEFORE=<min signed_at>
#   - 新 manifest の legacy_single_key entry に legacy_not_before を記録

# step 3: 新 manifest を root sign + deploy (§13.1 step 3-5 と同手順)

# step 4: state head update (initialized=true、legacy_fallback_disabled_at は未設定 = legacy fallback 継続)
# (head deploy の詳細は §19.3 参照)
```

---

## §14 active-registry split-brain check + partial commit recovery SOP

active-registry の cutover (source freeze → decommission → target active) 中に interrupt が発生した場合の recovery。plan §9.4 R2 F-002 + §9.10 R10 F-001 で導入された 2PC PrepareMarker/CommitMarker 経路。

### §14.0 2PC state machine 全体図

```
SOURCE                                   TARGET
─────────────────────────────────────────────────────────
[active]  ── freeze ──>  [frozen]
                                          [pending]
                                              │
[frozen]  ── decommission ──>  [decommissioned]
                                              │
                                          PrepareMarker ──>  [prepare_pending]
                                              │
                       ────── CommitMarker ──>  [active]
```

各 marker file:
- source: `freeze.signed`, `decommission.signed` (`<config_dir>/active_registry/`)
- target: `active.signed`, `prepare.pending`, `commit.signed` (同上)

### §14.1 partial commit detection (片側 pending のまま 24h 経過)

```bash
# step 1: 各 host の marker state を確認
for HOST in vps linux mac; do
  echo "=== $HOST ==="
  ssh "$HOST" 'ls -la /etc/taskhub/active_registry/ 2>/dev/null'
done

# step 2: prepare_pending state が 24h 以上 stale なら recovery 必要
ssh "$TARGET_HOST" 'stat -c "%Y %n" /etc/taskhub/active_registry/prepare.pending 2>/dev/null' | \
  awk '{ if (systime() - $1 > 86400) print "STALE prepare: " $2 }'
```

### §14.2 manual recovery (commit interrupt)

interrupt scenario:
- A: source は decommissioned、target は prepare_pending (cutover Phase α 完了、Phase β interrupt)
- B: source は frozen のみ、target は何も無し (Phase α 着手前)
- C: 両 side 完了済みだが `.signed` rename 失敗 (atomic boundary 内 fsync 失敗)

> **CLI 状況**: `taskhub cutover …` subcommand は **SP-013 で実装予定**。SP-012 では `scripts/taskhub_active_registry.py` の dataclass (PrepareMarker / CommitMarker / verify_commit_marker_invariants) のみ実装。本 SOP は spec として記述、operator は manual marker file 操作 + scripts 直接呼出を使う。

```bash
# Scenario A: rollback cutover (source 復活、target 廃棄)
#  - operator 二人以上の cutover-rollback approval を out-of-band で取得
#  - target host で prepare.pending を archive (削除ではなく archive、後の forensic 用)
ssh "$TARGET_HOST" 'mv /etc/taskhub/active_registry/prepare.pending \
  /etc/taskhub/active_registry/.archive/prepare.pending.aborted.$(date +%s)'
#  - source host で freeze.signed のみ残し、decommission.signed を archive (rollback で active 復活)
ssh "$SOURCE_HOST" 'mv /etc/taskhub/active_registry/decommission.signed \
  /etc/taskhub/active_registry/.archive/decommission.signed.aborted.$(date +%s)'
# `thaw` は `--reason` を持たない (`--decommission-target` flag のみ、approval args 必須)
# rollback では target を decommission せずに source を復活させるため flag なし
ssh "$SOURCE_HOST" "taskhub thaw --approval-id '$THAW_APPROVAL_ID'"

# Scenario B: cleanup (source freeze 解除、target 何もしない)
ssh "$SOURCE_HOST" "taskhub thaw --approval-id '$THAW_APPROVAL_ID'"

# Scenario C: replay commit (signed_manifest の hash が両 side で一致を前提に、final rename を再実行)
# CommitMarker.canonical_payload() を root signed manifest で再構築し、両 side で atomic rename
# (SP-013 CLI 実装まで、operator が `python -m scripts.taskhub_active_registry` を直接呼出)
```

### §14.3 split-brain detection (両 active 状態)

最悪 scenario: source も target も `active.signed` を持つ (network partition + 強制 commit)。

> **CLI 状況**: `taskhub active-registry` は SP-012 では skeleton (subcommand なし、help のみ)。verify は下記の `python3 -c` inline で `scripts.taskhub_active_registry_gate.evaluate_gate` helper を直接 invoke する (`python3 -m` 経路は `__main__` 未実装のため動作しない)。

```bash
# active marker chain 検証: `evaluate_gate()` を直接 invoke (signature + freeze/decommission + fleet 全件 fail-closed verify)
#   PYTHONPATH + heredoc pattern (§13.1 step 5 参照)、HOST loop var は env var で remote に渡す
for HOST in vps linux mac; do
  ssh "$HOST" "EXPECTED_HOST_ID='$HOST' \
    PYTHONPATH=/opt/taskhub/scripts:/opt/taskhub python3 -" <<'PYEOF'
import json, os, sys
from pathlib import Path
from taskhub_active_registry_gate import (
    build_file_based_public_key_resolver, evaluate_gate,
)

config_dir = Path("/etc/taskhub")
host_id = os.environ["EXPECTED_HOST_ID"]
resolver = build_file_based_public_key_resolver(config_dir)
outcome = evaluate_gate(
    config_dir,
    expected_host_id=host_id,
    gate_kind="api_write",  # gate_kind は audit/observability 用、決定論理に影響しない
    public_key_resolver=resolver,
)
result = {
    "host": host_id,
    "gate_passed": outcome.passed,
    "reason_code": outcome.reason_code,
    "active_marker_present": outcome.state.active_marker_present,
    "freeze_marker_present": outcome.state.freeze_marker_present,
    "decommission_marker_present": outcome.state.decommission_marker_present,
    "fleet_loaded": outcome.state.fleet_loaded,
    "fleet_host_status": outcome.state.fleet_host_status,
    "signature_verified": outcome.state.active_marker_signature_verified,
}
print(json.dumps(result))
sys.exit(0 if outcome.passed else 1)
PYEOF
done
# 複数 host で gate_passed=true → split-brain (両側 active state)
# 1 host のみ gate_passed=true → 正常 (single active fleet)
```

split-brain 検出時:
1. **全 host で個別 freeze を実行** (`--all-hosts` flag は未実装、operator が host loop で順次)
   `taskhub freeze` は destructive のため `--approval-id` 必須 (Codex R3 F-R3-002 fix):
   ```bash
   # pre-issued split-brain freeze approval (2-party-control で out-of-band 取得)
   SB_APPROVAL_ID="split-brain-freeze-$(date +%Y%m%d-%H%M)"
   # operator が taskhub approval issue で APPROVAL_ID を事前生成
   for HOST in vps linux mac; do
     ssh "$HOST" "taskhub freeze \
       --reason 'split-brain detected: <fleet generation N+1 conflict>' \
       --approval-id '$SB_APPROVAL_ID'"
   done
   ```
2. fleet membership snapshot を operator が手動 review
3. 正しい active host を選定 (`active.signed` の `migration_epoch` 最大 + `activated_at` 最新 + approval chain で判断)
4. 不正な active marker を持つ host で active.signed を `.archive/` へ move (削除ではなく archive、forensic 保全)
5. fleet membership 再 sign + deploy + 各 host で再 verify (上記 step 3 と同 `python3 -c` inline pattern で `evaluate_gate` 直接 invoke)

---

## §15 ReasonCode 60 件 reason table + sub-cause expansion

plan §4.5 ReasonCode 表 + ADV2 R2 F-002 sub-cause expansion。各 reason_code は audit event payload + structured log に必ず含める (raw secret は含めない)。

| # | reason_code | trigger | sub-cause | operator action |
|---|---|---|---|---|
| 1 | `taskhub_active_registry_active_marker_absent` | active.signed file 不在 | - | §14.2 manual recovery |
| 2 | `taskhub_active_registry_fleet_membership_unavailable` | fleet.signed.json 不在 | - | fleet deploy 実行 |
| 3 | `taskhub_active_registry_host_id_mismatch` | active.host_id != local_host_id | - | active marker 再 sign |
| 4 | `taskhub_active_registry_freeze_marker_present_write_blocked` | freeze.signed 存在 | - | §14.2 freeze release |
| 5 | `taskhub_active_registry_decommission_marker_present_write_blocked` | decommission.signed 存在 | - | §14.2 cutover rollback |
| 6 | `taskhub_active_registry_fleet_membership_violation` | host が fleet 不在 | - | fleet membership 更新 |
| 7 | `taskhub_active_registry_host_revoked_or_retired` | fleet.host.status != active | - | host 復活 / quarantine |
| 8 | `taskhub_active_registry_host_lifecycle_expired` | host.valid_to 過ぎ / clock skew | clock_skew_exceeded | NTP sync + clock attest |
| 9 | `taskhub_active_registry_signer_not_in_allowlist` | marker.signer_fp が allowlist 不在 | - | keyring rotation |
| 10 | `taskhub_active_registry_role_demoted_in_current_fleet` | marker_kind がhost.allowed_kinds 不在 | - | fleet membership 更新 |
| 11 | `taskhub_active_registry_signer_public_key_unavailable` | signers/<sha256>.pub 不在 | - | signer pubkey deploy |
| 12 | `taskhub_active_registry_signature_verify_failed` | Ed25519 verify fail | prepare_marker_in_active_path_rejected / commit_certificate_missing / fingerprint_mismatch | §17 incident response |
| 13 | `taskhub_active_registry_gate_not_configured` | app.state.gate_config 不在 | - | configure_active_registry_gate_from_settings call |
| 14 | `taskhub_active_registry_gate_malformed_config` | gate_config dict 部分 attach | - | settings 修正 |
| 15 | `taskhub_active_registry_write_rejected_by_gate` | L1 gate fail (HTTP layer) | underlying reason_code | underlying check |
| 16 | `taskhub_active_registry_worker_startup_aborted` | worker startup gate fail | - | restart worker after fix |
| 17 | `taskhub_active_registry_worker_dequeue_rejected_by_gate` | worker dequeue gate fail | - | fresh re-enqueue (自動) |
| 18 | `taskhub_active_registry_db_commit_rejected_by_gate` | L3 SQLAlchemy commit fail | - | session rollback + fix |
| 19 | `taskhub_active_registry_epoch_counter_tampered` | epoch counter sha256 mismatch | - | §17 forensic |
| 20 | `taskhub_active_registry_epoch_replay_or_lower` | epoch monotonicity violation | - | journal replay debug |
| 21 | `taskhub_signed_approval_keyring_key_revoked` | keyring entry status=revoked (`scripts/taskhub_keyring.py`) | - | use different key |
| 22 | `taskhub_signed_approval_keyring_key_expired` | keyring entry status=deprecated / expires_at 経過 | - | §13.1 lifecycle rotation |
| 23 | `taskhub_signed_approval_keyring_no_valid_key` | manifest 内 active key 不在 / signed_at に valid key 無し | - | §13.1 immediate rotation |
| 24 | `taskhub_signed_approval_keyring_generation_replay_or_lower` | manifest generation chain break | - | §13 force regenerate |
| 25 | `taskhub_signed_approval_keyring_manifest_signature_invalid` | root signature invalid (`approval_keyring_root.pub` mismatch / sig invalid) | - | root key forensic |
| 26 | `taskhub_signed_approval_keyring_manifest_tampered` | previous_committed_manifest_hash drift / commit_log_chain_hash drift / entry tamper | - | chain repair |
| 27 | `taskhub_approval_issuance_journal_monotonic_regression_detected` | wall-clock or monotonic regression (`scripts/taskhub_approval_issuance.py`) | clock_rollback / monotonic_skip | §20 clock + §21 attest |
| 28 | `taskhub_approval_issuance_journal_monotonic_sequence_skip_detected` | sequence non-monotonic | - | journal forensic |
| 29 | `taskhub_approval_issuance_journal_entry_signature_invalid` | journal entry Ed25519 verify fail | - | §17 incident response |
| 30 | `taskhub_approval_issuance_journal_chain_hash_mismatch` | previous_entry_hash drift | - | journal forensic |
| 31 | `taskhub_approval_issuance_monotonic_clock_source_unavailable` | Mode A/B/C 全不可 | - | §21 mode 切替 |
| 32 | `taskhub_approval_signed_after_key_expired_per_journal` | journal entry の signed_at が key expired 後 | - | revocation chain forensic |
| 33 | `taskhub_approval_caller_supplied_signed_at_rejected` | caller-supplied signed_at が server-owned schema 違反 | - | client implementation fix |
| 34-60 | (cutover lease / signed manifest / fleet roster / canary / SOPS / etc.) | plan §4.5 参照 | - | per-context SOP |

**※ 60 件 reason_code list は plan §4.5 で予定された **total** であり、SP-012 で実装済の reason_code は上記 34 件 (`scripts/taskhub_active_registry.py` + `scripts/taskhub_keyring.py` + `scripts/taskhub_active_registry_gate.py` + `scripts/taskhub_approval_issuance.py`)**。残 26 件 (cutover lease / signed manifest 拡張 / fleet roster 完全化 / canary detection 等) は SP-013 以降で追加実装予定。CI script `.claude/scripts/check_reason_code_coverage.sh` が `REASON_CODES` constant の 5+ source 整合を gate (plan §9.5/§9.6 で予定、SP-013 で本格運用)。

---

## §16 ADR-00028/00029 accepted 化 SOP

SP-012 must_ship に対応する ADR (`ADR-00028` split-brain second line / `ADR-00029` keyring rotation) の proposed → accepted 移行手順。`.claude/rules/sprint-pack-adr-gate.md §12 ADR accepted promotion` 準拠。

### §16.1 promotion 前提条件 checklist

- [ ] Sprint Pack の `must_ship` 受け入れ条件と矛盾しない
- [ ] 関連 rules (`.claude/rules/*.md`) と整合
- [ ] 関連 reference (`.claude/reference/*.md`) と整合
- [ ] 関連 DD (`docs/基本設計/*.md`) と整合
- [ ] `planned_adr_refs` から `adr_refs` へ移動済
- [ ] codex-plan-review R1 minimum + 採否判定 通過済

### §16.2 promotion 手順

```bash
# step 1: ADR frontmatter edit
# status: "proposed" → "accepted"
# updated_at: <implementation start date>

# step 2: Sprint Pack の adr_refs 更新
# (heavy Pack の場合: planned_adr_refs → adr_refs に移動)

# step 3: Sprint Pack の "## Review" 章に accepted_at 記録
# 「ADR-00028 accepted_at: 2026-05-22」

# step 4: commit + PR + Codex review
git add docs/adr/00028_*.md docs/adr/00029_*.md docs/sprints/SP-012_*.md
git commit -m "adr+plan: ADR-00028/00029 proposed→accepted (SP-012 must_ship 実装前 gate)"
```

### §16.3 break-glass 例外運用 (緊急修正で先行した場合)

`.claude/rules/sprint-pack-adr-gate.md §10` 準拠:
- ユーザー承認が事前取得済
- 最小 patch (影響 1-2 ファイル)
- rollback 手順を patch 適用前に決定
- 24h 以内に retro Pack / ADR を作成、`proposed` 起点 → 通常レビュー → `accepted`
- ADR Gate Criteria 11 種は break-glass 対象外 (常に実装前 ADR 必須)

---

## §17 revocation incident response SOP

key compromise / `secret_canary_detected` / unauthorized signature verify event 検出時の初動 + 復旧 SOP。

### §17.1 P0 検出時の初動 (15 min 以内)

> **CLI 状況**: `taskhub audit …` / `taskhub approval list` subcommand は **SP-013 で実装予定**。SP-012 では audit log は structured JSON (Loki shipping format) を grep / jq で直接読む。issuance journal は append-only JSONL で `scripts/taskhub_approval_issuance.py` の verifier で読む。

```bash
# step 1: 即時全 host freeze (write 停止、host loop で順次)
#   重要: `taskhub freeze` は destructive operation のため `--approval-id` 必須 (default deny)。
#   incident response 用の pre-issued approval を operator が事前準備、または
#   `--allow-unsigned-manual-skeleton` を手動 escape (audit 必須、後続 retro Pack)。
APPROVAL_ID="incident-freeze-$(date +%Y%m%d-%H%M)"
# pre-issue freeze approval (taskhub approval issue で作成、out-of-band 2-party)
for HOST in vps linux mac; do
  ssh "$HOST" "taskhub freeze \
    --reason 'incident-<ticket-id>: P0 freeze for revocation' \
    --approval-id '$APPROVAL_ID'"
done

# step 2: incident ticket 起票 (Notion / 内部 issue tracker)
#   - 検出時刻 (UTC iso8601)
#   - 検出経路 (canary / audit anomaly / external report)
#   - 影響範囲 (fingerprint / approval_id list)

# step 3: audit log の forensic dump (該当時間帯 ±2h)
#   ARQ / API の structured log は journalctl 経由で抽出
INCIDENT_START="2026-05-21T12:00:00Z"
journalctl -u taskhub-api -u taskhub-worker \
  --since "$(date -d "$INCIDENT_START - 2 hours" '+%F %T')" \
  --until "$(date -d "$INCIDENT_START + 2 hours" '+%F %T')" \
  --output=json > "./incident-<ticket-id>-audit.jsonl"
#   structured log を JSON parse + reason_code / signer_fingerprint で filter
#   注意: reason_code field 不在の log 行も混じるため、`has()` で guard してから startswith
jq 'select((has("reason_code")) and (.reason_code | type == "string") and (.reason_code | startswith("taskhub_signed_approval_keyring")))' \
  "./incident-<ticket-id>-audit.jsonl"

# step 4: 該当 fingerprint で sign された approval を全 list
#   approval issuance journal を JSONL で read、key_fingerprint_at_issue で filter
jq --arg fp "<compromised-fp>" \
  'select(.key_fingerprint_at_issue == $fp) | {approval_id, issued_at, claim_hash}' \
  /etc/taskhub/approvals/issuance_journal.signed.jsonl \
  > "./incident-<ticket-id>-approvals.json"
```

### §17.2 revocation execution (1 hour 以内)

```bash
# step 1: §13.2 emergency revocation SOP を実行
#   (SP-013 CLI 実装まで、operator が offline で manifest 編集 + root sign + deploy)

# step 2: rotation key 配備 (§18 Mode M manual mode)

# step 3: 全 host で revoked keyring 反映 confirm (verify_signed_manifest 直接呼出)
#   PYTHONPATH + heredoc pattern (§13.1 step 5 参照)
for HOST in vps linux mac; do
  ssh "$HOST" "PYTHONPATH=/opt/taskhub/scripts:/opt/taskhub python3 -" <<'PYEOF'
import sys, json
from pathlib import Path
from taskhub_keyring import verify_signed_manifest, SignedKeyringManifest
manifest_path = Path("/etc/taskhub/approval-verify-keyring.signed.json")
root_path = Path("/etc/taskhub/approval_keyring_root.pub")
manifest = SignedKeyringManifest.from_json(json.loads(manifest_path.read_text()))
root_pub = root_path.read_bytes()
ok, reason = verify_signed_manifest(manifest, root_pub)
print(f"verify: ok={ok} reason={reason}")
sys.exit(0 if ok else 1)
PYEOF
done

# step 4: audit event の verify (`taskhub verify` は SP-012 で実装済、`--since` 未対応)
#   actual flags: --integrity / --network-invariant / --multi-agent / --signed-journal --input <jsonl>
#   時間範囲 filter は SP-013 で実装予定。SP-012 期間中は --signed-journal で全件 verify、
#   時間範囲は journalctl + jq で別途 filter する (step 3 と同 pattern)。
for HOST in vps linux mac; do
  ssh "$HOST" 'taskhub verify --integrity --network-invariant --signed-journal \
    --input /etc/taskhub/approvals/issuance_journal.signed.jsonl'
done
```

### §17.3 post-incident (24-72 hours)

- Incident review meeting (operator + security lead)
- root cause analysis docs を Notion に保存
- 関連 service の credential rotation (DB / Redis / GitHub App / Tailscale)
- evidence 保全 (forensic image / log dump を WORM storage に)
- preventive measure (CI hook / alerting / runbook update) を ticket 化

---

## §18 rotation key 配備 2 mode

`<config_dir>/approval-verify-keyring.signed.json` を全 host に deploy する 2 mode。

### §18.1 Mode M (manual、operator 手動 ssh)

**前提**: small fleet (< 5 host)、operator が各 host に直接 ssh する。
**所要**: 5-15 分 / host。

```bash
# step 1: 新 keyring を operator workstation で生成 (§13)
# step 2: 各 host へ rsync (Tailscale SSH 経由、allowlist 制限内)
for HOST in vps linux mac; do
  rsync -avz --chmod=F0400 \
    /tmp/approval-verify-keyring.signed.json \
    "$HOST:/etc/taskhub/approval-verify-keyring.signed.json"
  # tombstone log も同 deploy (append-only、existing 後ろに追記が安全)
  rsync -avz --chmod=F0400 --append \
    /tmp/approval_keyring_revocation_tombstone.signed.jsonl \
    "$HOST:/etc/taskhub/approval_keyring_revocation_tombstone.signed.jsonl"
done

# step 3: 各 host で verify (scripts/taskhub_keyring.py 直接呼出)
#   PYTHONPATH + heredoc pattern (§13.1 step 5 参照)
for HOST in vps linux mac; do
  ssh "$HOST" "PYTHONPATH=/opt/taskhub/scripts:/opt/taskhub python3 -" <<'PYEOF'
import sys, json
from pathlib import Path
from taskhub_keyring import verify_signed_manifest, SignedKeyringManifest
manifest_path = Path("/etc/taskhub/approval-verify-keyring.signed.json")
root_path = Path("/etc/taskhub/approval_keyring_root.pub")
manifest = SignedKeyringManifest.from_json(json.loads(manifest_path.read_text()))
root_pub = root_path.read_bytes()
ok, reason = verify_signed_manifest(manifest, root_pub)
print(f"verify: ok={ok} reason={reason}")
sys.exit(0 if ok else 1)
PYEOF
done
```

### §18.2 Mode A (automated、CI/CD pipeline)

**前提**: medium-large fleet (5+ host)、CI/CD pipeline で配備。
**所要**: ~3 分 (parallel deploy)。

> **CLI 状況**: `taskhub fleet list` / `taskhub keyring fetch` subcommand は **SP-013 で実装予定**。Mode A は SP-013 以降の adoption が前提、SP-012 期間中は Mode M (manual) のみ実用。

```yaml
# GitHub Actions example (SP-013 以降の想定形)
- name: deploy approval keyring
  run: |
    # SP-013 CLI 実装後: taskhub fleet list / keyring fetch
    # SP-012 期間中の暫定: fleet.signed.json を jq で直接 read
    for HOST in $(jq -r '.hosts[] | select(.status == "active") | .host_id' \
                  /etc/taskhub/active_registry/active_registry_fleet.signed.json); do
      tailscale ssh "$HOST" 'rsync --inplace --append \
        rsync://ci.internal/taskhub/approval-verify-keyring.signed.json \
        /etc/taskhub/'
    done
```

CI/CD 経路は `tag:taskhub-ci` Tailscale grant を最小限に保つ。`approval-verify-keyring.signed.json` の deploy 専用 grant (read 限定 + push 専用 dir) を ADR-00007 で別途規定。

### §18.3 deploy verification

```bash
# 全 host で keyring fingerprint が一致を確認
for HOST in vps linux mac; do
  ssh "$HOST" 'sha256sum /etc/taskhub/approval-verify-keyring.signed.json' | head -1
done
# 全 host で同 sha256 → OK
```

---

## §19 SOPS encrypted backup + remote quorum + head deploy SOP

approval_keyring の backup 戦略。SOPS encrypted で remote quorum copy を保持 (P0 single-host 想定では SOPS encrypted を別 disk + offsite に保存)。

### §19.1 SOPS encrypted backup (daily)

```bash
# step 1: daily cron (operator host or backup orchestrator)
DATE=$(date +%Y%m%d)
sops --encrypt --age $TASKHUB_BACKUP_AGE_RECIPIENTS \
  --input-type json --output-type yaml \
  /etc/taskhub/approval-verify-keyring.signed.json \
  > /var/backups/taskhub/approval-verify-keyring.${DATE}.sops.yaml
# tombstone log + state head も別 file で backup
sops --encrypt --age $TASKHUB_BACKUP_AGE_RECIPIENTS \
  /etc/taskhub/approval_keyring_revocation_tombstone.signed.jsonl \
  > /var/backups/taskhub/tombstone.${DATE}.sops.jsonl
sops --encrypt --age $TASKHUB_BACKUP_AGE_RECIPIENTS \
  /etc/taskhub/keyring_state.head.signed \
  > /var/backups/taskhub/keyring_state_head.${DATE}.sops.json

# step 2: offsite copy (例: rclone to encrypted S3-compatible storage)
rclone copy /var/backups/taskhub/ \
  encrypted-offsite:taskhub-backups/keyring/${DATE}/
```

### §19.2 remote quorum copy

multi-host 環境では 3+ host に分散保存 (1 host crash でも 2/3 quorum で復旧可能):

```bash
# step 1: 各 backup host へ encrypted copy を push
for BACKUP_HOST in backup-vps backup-linux backup-cloud; do
  rsync -avz /var/backups/taskhub/approval-verify-keyring.${DATE}.sops.yaml \
    "$BACKUP_HOST:/var/backups/taskhub/"
done

# step 2: quorum verify (3 host 中 2 host で hash 一致を確認)
for BACKUP_HOST in backup-vps backup-linux backup-cloud; do
  ssh "$BACKUP_HOST" "sha256sum /var/backups/taskhub/approval-verify-keyring.${DATE}.sops.yaml"
done | sort | uniq -c | sort -rn | head -1
# 期待値: "3 <sha256>" or "2 <sha256>" (quorum 達成)
```

### §19.3 head deploy SOP (`/etc/taskhub/keyring_state.head.signed`)

head file は `latest_manifest_generation` + `latest_manifest_content_sha256` + `latest_commit_log_chain_hash` + `latest_tombstone_chain_hash` + `latest_active_registry_epoch` + `latest_fleet_membership_generation` + `latest_approval_issued_at` + `latest_monotonic_sequence` + `latest_monotonic_clock_attestation_value` + `latest_approval_issuance_journal_chain_hash` を持ち、approval issuance の最後の state snapshot を root-signed で永続化。

head 不在環境 (head deploy 前の初期環境): legacy fallback 許可 (新規 install のみ)。`initialized=true` + `legacy_fallback_disabled_at=<UTC>` で legacy fallback を明示 disable (mid-life upgrade 後)。

> **CLI 状況**: `taskhub keyring init-head` / `update-head` は SP-013 で実装予定。SP-012 では `scripts/taskhub_keyring.py` の `KeyringStateHead` dataclass + canonical_payload helper を直接呼出して manual で生成 + root sign する。

```bash
# step 1: initial deploy (new install)
#   PYTHONPATH 設定 + heredoc pattern (§13.1 step 5 参照、from taskhub_keyring に統一)。
#   operator が approval_keyring_root の私 key で sign + atomic install。
PYTHONPATH=/opt/taskhub/scripts:/opt/taskhub python3 - <<'PYEOF' > /tmp/head.unsigned.json
from taskhub_keyring import KeyringStateHead
import json
head = KeyringStateHead(
    initialized=True,
    legacy_fallback_disabled_at=None,
    latest_manifest_generation=1,
    latest_manifest_content_sha256="<sha256>",
    # ... 他 field (詳細は scripts/taskhub_keyring.py の KeyringStateHead dataclass 参照)
)
print(json.dumps(head.canonical_payload(), indent=2))
PYEOF
# operator が root signing token で sign + /etc/taskhub/keyring_state.head.signed に install

# step 2: rotation 時の head update (同パターンで content_sha256 更新 + generation +1 + 再 sign)

# step 3: head fingerprint を out-of-band verify (operator 物理紙)
sha256sum /etc/taskhub/keyring_state.head.signed
```

---

## §20 clock skew tolerance ε regulation

active-registry CommitMarker / approval issuance journal の wall-clock validation で許容する clock skew ε。

### §20.1 SP-012 実装値 (固定 5 seconds for issuance journal、60 seconds for active-registry)

backend gate / signature verify path で `now - issued_at < ε` を期待値とする (clock rollback 攻撃検出に使用):
- `<= ε`: 許容 (NTP synchronization の小幅な差を吸収)
- `> ε`: deny (`taskhub_approval_issuance_journal_monotonic_regression_detected`)

**SP-012 で固定された ε** (`scripts/taskhub_approval_issuance.py:WALL_CLOCK_SKEW_TOLERANCE_SECONDS = 5`):
- approval issuance journal: ε = 5 seconds (固定)
- active-registry CommitMarker (`scripts/taskhub_active_registry.py:COMMIT_TIME_CLOCK_SKEW_TOLERANCE_SECONDS = 60`): ε = 60 seconds (固定)

### §20.2 ε 調整 SOP (SP-013 で env override 化予定)

> **CLI 状況**: SP-012 では ε は constants として hard-coded、environment variable override は未実装。`TASKHUB_CLOCK_SKEW_TOLERANCE_SECONDS` env による override は **SP-013 で実装予定**。SP-012 期間中は ε 調整が必要な場合は constant を patch + redeploy (forensic 観点で audit log に必ず記録)。

```bash
# SP-013 以降の想定形 (env var override):
echo "TASKHUB_CLOCK_SKEW_TOLERANCE_SECONDS=120" >> /etc/taskhub/active_registry.env
systemctl restart taskhub-api taskhub-worker

# SP-012 期間中の暫定 (constant patch + redeploy):
#   1. scripts/taskhub_approval_issuance.py:WALL_CLOCK_SKEW_TOLERANCE_SECONDS を編集 (PR 経由)
#   2. ADR で「ε 変更の根拠」を明示 (clock rollback 攻撃の検出窓拡大のため)
#   3. PR merge + 全 host redeploy
```

**警告**: ε を 300s 超に設定する場合は ADR 必須 (clock rollback 攻撃の検出窓を大きく開けるため)。

### §20.3 NTP sync 必須前提

- chrony or systemd-timesyncd で NTP 同期を `tracking` 状態に保持
- `chronyc tracking` で `Stratum != 0` + `System time offset < 1s` を週 1 回確認
- 異常 detect 時は §21 trusted time attestation の Mode A を有効化

---

## §21 trusted time attestation 3 mode

`monotonic_clock_attestation` の source を 3 mode から選択 (plan §9.10 R10 F-002)。

### §21.1 Mode A: Linux CLOCK_MONOTONIC + NTP (P0 default)

**前提**: single-host VPS、NTP sync 済。
**長所**: 追加 hardware 不要、CPU monotonic counter 直読。
**短所**: host reboot で reset (再 boot 後の最初の issue で reboot detection 必要)。

```python
# implementation excerpt
import ctypes
clock_gettime = ctypes.CDLL("libc.so.6", use_errno=True).clock_gettime
# CLOCK_MONOTONIC = 1
ts = (ctypes.c_long * 2)()
clock_gettime(1, ts)
value = ts[0] * 10**9 + ts[1]  # nanoseconds
```

reboot 後の最初の issue は head の `latest_monotonic_sequence` reset を伴うため、operator が `KeyringStateHead` の `latest_monotonic_clock_attestation_value` を新 boot 後値で再 sign + atomic install して明示承認する (SP-013 では `taskhub approval issuance reboot-attest` CLI として automation 化予定)。

### §21.2 Mode B: TPM clock + signed attestation

**前提**: TPM 2.0 chip 搭載 host。
**長所**: host reboot 耐性 (TPM monotonic counter は reboot で reset されない)。
**短所**: TPM hardware + tpm2-tools dependency が必要。

```bash
# TPM monotonic counter を attestation 経由で取得
tpm2_clockinit
tpm2_readclock | jq '.clock.tpm_uptime' # nanoseconds-equivalent
```

### §21.3 Mode C: Remote trusted time service

**前提**: network 接続 + roughtime / TLSdate 等の外部 trusted time service が利用可能。
**長所**: 最も robust (3rd party signed attestation で改ざん検出)。
**短所**: network 依存 + 外部 service の availability に影響される。

```bash
# roughtime (Cloudflare 等) で signed time attestation を取得
roughtime-client --query "https://roughtime.cloudflare.com" --raw-attestation
```

### §21.4 mode 切替 SOP

> **CLI 状況**: SP-012 では mode switch は env var で未実装 (Mode A `linux_clock_monotonic` のみ実装、Mode B/C は plan-level の future spec)。SP-013 で env var `TASKHUB_MONOTONIC_CLOCK_MODE` + `taskhub approval issuance reboot-attest` CLI を実装予定。

```bash
# SP-013 以降の想定形:
# /etc/taskhub/active_registry.env で mode 指定
echo "TASKHUB_MONOTONIC_CLOCK_MODE=tpm_clock" >> /etc/taskhub/active_registry.env
# mode 切替時は head の attestation_value も reset (operator 明示承認必須)
taskhub approval issuance reboot-attest --mode-change --apply

# SP-012 期間中: Mode A 固定、reboot detection は manual operator 介入
#   - reboot 後の最初の approval issue 前に head の latest_monotonic_clock_attestation_value を
#     確認し、新 boot 後の clock_gettime(CLOCK_MONOTONIC) と乖離が極端なら reboot 発生と判断。
#   - operator が `KeyringStateHead` の `latest_monotonic_clock_attestation_value` を新 boot 後値で
#     再 sign + atomic install (§19.3 と同手順)。
```

---

## §22 backend gate L1+L2+L3 operator SOP (PR #85 wiring)

PR #85 で実装した 3 layer defense-in-depth backend gate の operator 視点 SOP。

### §22.1 production deployment 前提

```bash
# step 1: env vars 設定 (.env.production)
cat <<EOF >> /etc/taskhub/.env.production
TASKMANAGEDAI_ACTIVE_REGISTRY_GATE_ENABLED=true
TASKMANAGEDAI_TASKHUB_HOST_ID=vps  # local host id (fleet membership と一致)
TASKMANAGEDAI_TASKHUB_CONFIG_DIR=/etc/taskhub
EOF

# step 2: signers/ deploy (PR #85 §9.10 R4 F-R4-002 fix)
# fingerprint -> sha256(fp).hex.pub の filename で配備
mkdir -p /etc/taskhub/active_registry/signers
chmod 0700 /etc/taskhub/active_registry/signers
# 各 signer pub key を deploy:
FP="<base64-first-32-chars>"
SAFE_NAME=$(echo -n "$FP" | sha256sum | awk '{print $1}')
cp <signer-public-key.raw> "/etc/taskhub/active_registry/signers/${SAFE_NAME}.pub"
chmod 0400 "/etc/taskhub/active_registry/signers/${SAFE_NAME}.pub"

# step 3: fleet membership + active marker deploy (§14.0 参照)

# step 4: api server + worker restart
systemctl restart taskhub-api taskhub-worker
```

### §22.2 gate behavior matrix

| 状態 | L1 (FastAPI middleware) | L2 (ARQ worker) | L3 (SQLAlchemy before_commit) |
|---|---|---|---|
| gate disabled (env=false) | no-op | no-op | no-op |
| active_marker absent | 503 fail-closed | startup abort or per-job re-enqueue | IntegrityError (commit reject) |
| freeze.signed 存在 | 503 fail-closed | per-job re-enqueue | IntegrityError |
| decommission.signed 存在 | 503 fail-closed | per-job re-enqueue | IntegrityError |
| signature verify failed | 503 fail-closed | startup abort | IntegrityError |
| read-only request / commit | 通過 (GET / DML 無し commit は exempt) | 通過 | exempt (`_session_has_mutations` で skip) |

exempt path (L1 only):
- `/health` / `/metrics` / `/auth/*` (operator が gate 修復のために必要)

### §22.3 monitoring + alerting

> **Metric 状況**: SP-012 では gate は structured log event (`active_registry_write_rejected_by_middleware` / `worker_dequeue_rejected_re_enqueued` / `active_registry_db_commit_rejected_by_gate`) を logger.warning で発出する形式。Prometheus Counter での expose は **SP-013 で実装予定** (`backend/app/observability/prometheus.py` で gate-specific counter 追加予定)。SP-012 期間中の monitoring は Loki LogQL (structured log query) で行う。

```logql
# Loki LogQL 例 (L1 middleware reject rate、structured log 経由)
sum by (host_id_expected) (rate({service_role="api"} |~ "active_registry_write_rejected_by_middleware" [5m]))

# L2 worker re-enqueue rate
sum by (host_id_expected) (rate({service_role="worker"} |~ "worker_dequeue_rejected_re_enqueued" [5m]))

# L3 commit reject rate (SQLAlchemy)
sum by (host_id_expected) (rate({service_role="api"} |~ "active_registry_db_commit_rejected_by_gate" [5m]))
```

(SP-013 で Prometheus Counter 化された後は同等 PromQL query: `rate(active_registry_write_rejected_by_middleware_total[5m])` 等)

alert rules:
- L1 reject rate > 10/min for 5 min: PagerDuty "gate triggered, investigate"
- L2 re-enqueue rate > 60/min for 10 min: "worker backlog building, fix gate"
- L3 commit reject rate > 1/min: "service-layer DB write blocked"

### §22.4 troubleshooting

```bash
# gate enabled だが 503 が返ってこない場合 (gate disabled state 確認)
# 注意: /health は gate exempt path (middleware bypass) なので gate 動作確認に使えない。
# 必ず mutation endpoint (/api/<*>) に POST/PUT/PATCH/DELETE で確認する。
curl -s -X POST http://localhost:8000/api/tickets -d '{}' -H 'Content-Type: application/json'
# 期待値 (gate enabled + active marker absent): 503 + reason_code = "taskhub_active_registry_write_rejected_by_gate"
# 期待値 (gate disabled、env var false): 401 (dev-login 不在) or validation error

# app.state.active_registry_gate_config を Python REPL で確認 (PYTHONPATH 設定必須)
PYTHONPATH=/opt/taskhub:/opt/taskhub/scripts python3 - <<'PYEOF'
from backend.app.main import app
print(getattr(app.state, "active_registry_gate_config", None))
PYEOF

# gate failure reason_code を audit log から確認
journalctl -u taskhub-api --since "5 min ago" | grep active_registry_write_rejected
```

### §22.5 emergency gate disable (incident response)

incident で gate を一時的に disable する場合 (operator 明示判断のみ):
```bash
# step 1: env で disable
sed -i 's/TASKMANAGEDAI_ACTIVE_REGISTRY_GATE_ENABLED=true/TASKMANAGEDAI_ACTIVE_REGISTRY_GATE_ENABLED=false/' /etc/taskhub/.env.production

# step 2: API + worker restart
systemctl restart taskhub-api taskhub-worker

# step 3: incident ticket 起票 + post-mortem 必須
#   - なぜ disable したか
#   - 影響範囲 (disable 期間中の write は L1/L2/L3 bypass されている)
#   - 再有効化 timeline
```

**警告**: gate disable は **split-brain second line of defense を喪失** する状態。incident response の絶対最終手段とし、24h 以内に再有効化 + retro Pack/ADR 必須。

---

## 関連 reference

- ADR-00028: split-brain second line of defense (active-registry 4 marker chain + 2PC)
- ADR-00029: approval keyring rotation (signed manifest + multi-key + tombstone)
- plan: `.claude/plans/sp012-split-brain-keyring.md` §9.3-§9.10 hardening contract
- rules: `.claude/rules/secretbroker-boundary.md` / `cross-source-enum-integrity.md` / `server-owned-boundary.md`
- scripts: `scripts/taskhub_active_registry.py` / `scripts/taskhub_keyring.py` / `scripts/taskhub_approval_issuance.py` / `scripts/taskhub_active_registry_gate.py`
- backend: `backend/app/api/dependencies/active_registry_gate.py` / `backend/app/workers/active_registry_worker_gate.py` / `backend/app/db/active_registry_mutation_gate.py`
