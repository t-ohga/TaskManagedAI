# SP022-T02 Phase 4 + T08 batch 4 — `--rollback` standalone real I/O + `status --remote` split-brain detection + `taskhub approval issue` real I/O

## メタデータ

- **slug**: sp022-t02p4-t08b4-rollback-splitbrain-approval
- **base**: origin/main (`7cfcac9` post-PR #78)
- **owning sprint**: SP-022 framework intake hardening (T02 Phase 4 + T08 batch 4)
- **related ADRs**: ADR-00021 §11.2 (split-brain freeze/drain marker) / §14.1 PGA-F-002 / PGA-F-003 (active registry + trusted_signers) / §14.1 PGA-F-013 (drill timer alert-only + signed approval required)
- **risk_classification**: CRITICAL invariant 直結 (SecretBroker raw secret 非保存 / OperationContext fingerprint server-owned binding / approval 4 整合 / docker compose exec ホスト TCP 排除 / split-brain default deny)
- **must_ship**:
  1. `--rollback <pre-restore-ts>` real I/O (既存 `rollback_from_pre_restore_snapshot` への CLI entry path、approval gate + `RestoreRollbackApprovalClaim` signature 束縛 verify + snapshot manifest verify)
  2. `taskhub status --remote <host>` real I/O (Tailscale SSH 経由旧 host service down 確認、host-specific signed config による compose project/file binding、split-brain default deny)
  3. `taskhub approval issue` real I/O CLI subcommand (operator が approval record を生成、Ed25519 sign + restore_claim 12 field 完全 mapping + drill_kind enum 整合 + canonical payload sub-record binding)
  4. PR #75/#77/#78 既存 approval record の re-sign migration SOP docs (canonical payload extension で signature_invalid 化、operator は revoke + 新規 issue)
- **defer_if_over_budget**:
  - 全 must_ship は本 PR scope 内で完遂 (R1 F-012 adopt: T09 unblock condition の hard gate を §11 に明記)
  - backup_orchestrator pg_dump compose exec 切替 (R14-F-001 retro-fix for backup direction、PR #77 後 carry-over) → **本 PR scope 外**、Phase 5 別 PR で対応 (`SP022-T02 Phase 5`)
  - active registry signed local ledger (PGA-F-003 full) → SP-012 must_ship carry-over (本 batch では active.signed marker existence check のみ)
  - trusted_signers / source_host_id allowlist (PGA-F-002 full) → SP-012 / SP-022 後続 batch
- **rollback**: 本 PR を revert すると `--rollback` は skeleton mode (exit 1) に戻る + `--remote` も skeleton に戻る + approval issue / restore-rollback claim verify が消える。既存の Phase 3 restore は影響を受けない (新規 path のみ追加、`RestoreRollbackApprovalClaim` は新 dataclass、`require_approval_for_destructive(subcommand="restore-rollback", ...)` の挙動は revert 後既存 verify_signed_approval flow に戻る)。approval issue は別 file 新規追加なので revert で消える。

---

## §1 目的

PR #78 (Phase 3 restore real I/O) で skeleton として残した 3 path を real I/O 化し、Sprint Pack §Phase 3 carry-over 7 件のうち 4 件を closure する:

1. `taskhub restore --rollback <pre-restore-ts>`: pre-restore snapshot 戻し real I/O + 新 `RestoreRollbackApprovalClaim` (12 field、approval 4 整合) + snapshot manifest verify
2. `taskhub status --remote <host>`: Tailscale SSH 経由で旧 host の docker compose service down 確認 + host-specific signed config による compose project/file binding + split-brain default deny
3. `taskhub approval issue --subcommand <name> ...`: operator が approval record を Ed25519 sign で発行する CLI (restore_claim 12 field 完全 mapping + drill_kind enum 既存 dict 参照)
4. 既存 approval record の re-sign SOP: PR #78 で `_rfc8785_canonical_payload_bytes` が `backup_claim` / `restore_claim` を sub-record として含めるよう拡張 (本 PR で `restore_rollback_claim` も追加)、PR #75/#77/#78 で生成された approval record は **signature_invalid** 化。operator は revoke + 新規 issue 必須。本 PR で SOP を `docs/deploy/operator-runbook.md` に明記。

### 1.1 Sprint Pack carry-over 7 件 trace (R1 F-013 adopt)

| # | Sprint Pack carry-over | 本 PR 内 status |
|---|---|---|
| 1 | `--rollback <pre-restore-ts>` standalone real I/O | ✅ this PR closure (Batch A) |
| 2 | split-brain remote detection (`taskhub status --remote`) | ✅ this PR closure (Batch B) |
| 3 | `taskhub approval issue` real I/O subcommand | ✅ this PR closure (Batch C) |
| 4 | age 秘密鍵 SecretBroker integration | ❌ explicit out-of-scope (P0 manual 運搬で OK、SP-022 carry-over batch 5) |
| 5 | actual pg_restore/age/redis-cli tool execution validation | ❌ blocked_by SP022-T09 physical drill (本 PR は mock subprocess、実機 drill phase mandatory) |
| 6 | backup_orchestrator pg_dump compose exec 切替 | ❌ next PR carry-over (`SP022-T02 Phase 5`)、本 PR scope 外、**T09 unblock の hard gate (§11)** |
| 7 | 既存 PR #75/#77 approval record の re-sign migration | ✅ this PR closure (Batch D docs SOP) |

count: this PR closure = 4 件 (#1, #2, #3, #7) / explicit out-of-scope = 1 件 (#4) / blocked_by SP022-T09 = 1 件 (#5) / next PR carry-over = 1 件 (#6)。

---

## §2 背景 / 制約

### 2.1 ADR-00021 §11.2 split-brain default deny invariant

ADR-00021 §11.2 (PG-F-003 fix):

> 同 migration_epoch で 2 つの host が active になることは絶対禁止
> target restore が成功しても、source host は taskhub thaw 明示まで disable
> network partition でどちらが active か不明な場合は、両方 manual intervention 必須 (auto failover なし)

`taskhub status --remote` は **target host が restore する前に source host が freeze 済か service down か** を verify する **single gate** ではなく、split-brain prevention の **first line of defense**。second line は §11.2 の freeze.signed + active.signed marker chain (本 PR scope 外、SP-012 must_ship)。

### 2.2 ADR-00021 §14.1 PGA-F-013 drill timer alert-only enforcement

`taskhub migrate` / `restore` / `restore --rollback` / `age-rotate` / `freeze` / `thaw` は **signed human approval record (`~/.taskhub/approvals/<id>.signed`)** 必須。本 PR は approval record を発行する `taskhub approval issue` CLI を追加 (現状は test fixture でしか作れない)。`restore-rollback` は **新 `RestoreRollbackApprovalClaim` を canonical payload sub-record として binding** (R1 F-001 adopt)。

### 2.3 SecretBroker boundary (rules/secretbroker-boundary.md)

approval issue は signing key (Ed25519 private key) を扱う:
- private key は `~/.taskhub/keys/approval-signing-key` (chmod 0o600 必須) に operator が manual 配置
- approval issue process は private key を **`bytearray` raw buffer に read** → `Ed25519PrivateKey.from_private_bytes()` で load → sign → `bytearray` を即時 overwrite (best-effort zeroize、R1 F-019 adopt)。cryptography library object 内部の memory は library lifecycle 依存 (Python immutable bytes の完全消去保証なし、plan 上の limit を明記)。DB 保存 / log / artifact / audit に raw bytes を含めない
- approval issue は SecretBroker capability token を redeem する path ではなく、operator-controlled offline signing (P0 では DB 経由 SecretBroker は未実装、approval signing は CLI offline ledger)

### 2.4 server-owned boundary (rules/server-owned-boundary.md)

`taskhub approval issue` で生成される claim (backup_claim / restore_claim / restore_rollback_claim) は **operator が CLI 引数で指定する**が、CLI 内部で **canonical payload を再計算** (operator-supplied fingerprint を bypass しない)。signature 対象 payload に operator-supplied claim を含めるが、CLI が schema strict validation + canonical 整形を実施。verify side は同 canonical payload を独立に再計算して signature 検証。

### 2.5 既存 module 整合 (R1 F-008/F-009/F-011 adopt)

| 既存 constant / regex | location | 本 plan 整合 |
|---|---|---|
| `DEFAULT_MAX_TTL = timedelta(hours=48)` | `taskhub_signed_approval.py:83` | issue CLI `--ttl-hours` default=24、max=48 (`sa.DEFAULT_MAX_TTL` を import)、F-009 adopt |
| `APPROVAL_ID_REGEX = ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` | `taskhub_signed_approval.py:77` | issue CLI も同 regex を strict 適用、operator-runbook example も適合 (drill-YYYY-MM-DD-<8hex> は既存 regex の subset)、F-017 adopt |
| `REASON_SUMMARY_REGEX = ^[A-Za-z0-9_-]{1,64}$` | `taskhub_signed_approval.py:78` | runbook example を `half-yearly-drill_mac-vps` 等 underscores + dashes に修正、F-017 adopt |
| `DRILL_KIND_ALLOWED_SUBCOMMANDS` (8 entries) | `taskhub_signed_approval.py:106-115` | argparse `choices=sorted(DRILL_KIND_ALLOWED_SUBCOMMANDS)` から直接派生、`age_rotate`/`backup_only`/`freeze_only`/`thaw_only` 含む全 8 種、F-011 adopt |
| `_load_verify_key_and_fingerprint` 受容 format = raw 32 bytes or base64-decoded 32 bytes | `taskhub_signed_approval.py:539-550` | operator-runbook で **raw 32-byte seed** を生成する Python helper を提供、DER/PEM は不採用 (verify side が受け付けない)、F-008 adopt |
| `_pre-restore-{ts}` ts format = `%Y%m%dT%H%M%S` | `taskhub_restore_orchestrator.py:1265 / 1503` | rollback CLI `args.rollback` 引数 regex = `^\d{8}T\d{6}(?:-\d+)?$`、F-003 adopt |

---

## §3 scope (4 batches)

### Batch A: `--rollback <pre-restore-ts>` standalone real I/O + `RestoreRollbackApprovalClaim` + 共有 destructive lock

#### 3.A.-1 host-level destructive operation lock (R3 F-002 + ADV R1 F-002 adopt、CRITICAL)

**ADV R1 F-002 adopt**: lock path は `$HOME/.taskhub/locks/destructive-operation.lock` を default とするが、**`TASKHUB_LOCK_DIR` env override** をサポートし、multi-user host では `/var/lock/taskhub/` 等 host-global path に設定可能。本 PR scope では TaskManagedAI が single-host single-user (operator) 運用前提のため HOME 配下で十分、ただし plan / runbook で multi-user 制約を明記。stale lock cleanup (pid dead detection) も追加。

新規 helper module `scripts/taskhub_destructive_lock.py` を追加:

```python
"""SP022-T02 Phase 4: host-level destructive operation lock (R3 F-002 adopt).

backup / restore / restore-rollback / migrate / freeze / thaw が同時実行されないことを
fcntl.flock(LOCK_EX | LOCK_NB) で保証. lock file 不在 → create + lock. 取得失敗 → deny.

Lock file: ~/.taskhub/locks/destructive-operation.lock (mode 0o600)
Payload (lock acquired 後に write): {subcommand, approval_id, pid, started_at_utc}
"""

import fcntl, json, os, sys, time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Literal

LockReasonCode = Literal[
    "destructive_lock_acquired",
    "destructive_lock_busy",          # 別 process が保持中
    "destructive_lock_dir_missing",   # ~/.taskhub/locks/ 自動作成失敗
    "destructive_lock_dir_permission", # parent dir mode 0o700 ではない
    "destructive_lock_file_permission", # lock file mode 0o600 ではない (race を弾く)
    "destructive_lock_payload_error", # busy 時に payload read 失敗
]


@contextmanager
def acquire_destructive_lock(
    subcommand: str, approval_id: str | None,
) -> Iterator[tuple[bool, LockReasonCode, dict | None]]:
    """destructive operation lock を context manager で取得.

    Returns:
        (acquired: bool, reason_code: LockReasonCode, blocker_payload: dict | None)
        acquired=True なら with block 内で operation 実行可、exit 時に lock release.
        acquired=False なら blocker_payload に保持者の {subcommand, approval_id, pid, started_at_utc}.
    """
    # ADV R1 F-002 adopt: env override で multi-user host 対応 (default は HOME 配下、single-user 前提)
    lock_dir_str = os.environ.get("TASKHUB_LOCK_DIR")
    if lock_dir_str:
        lock_dir = Path(lock_dir_str)
    else:
        lock_dir = Path.home() / ".taskhub" / "locks"
    try:
        lock_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    except OSError:
        yield False, "destructive_lock_dir_missing", None
        return
    dir_mode = lock_dir.stat().st_mode & 0o777
    if dir_mode != 0o700:
        yield False, "destructive_lock_dir_permission", None
        return

    lock_path = lock_dir / "destructive-operation.lock"
    # mode 0o600 で create or open (O_NOFOLLOW で symlink reject)
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
    try:
        fd = os.open(str(lock_path), flags, 0o600)
    except OSError as e:
        yield False, "destructive_lock_file_permission", None
        return

    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # busy — payload を read してから caller に返す
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                data = os.read(fd, 4096).decode("utf-8")
                blocker = json.loads(data) if data.strip() else None
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                blocker = None
            yield False, "destructive_lock_busy", blocker
            return

        # lock acquired — payload write
        payload = json.dumps({
            "subcommand": subcommand,
            "approval_id": approval_id,
            "pid": os.getpid(),
            "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }, sort_keys=True)
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)

        try:
            yield True, "destructive_lock_acquired", None
        finally:
            # release (close fd で自動 release も、明示的に LOCK_UN)
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
```

#### 3.A.0 新 `RestoreRollbackApprovalClaim` + loader/parser/matcher (R1 F-001 / R2 F-002 adopt)

新規 dataclass + 既存 strict loader 拡張を `scripts/taskhub_signed_approval.py` に追加。**R2 F-002 adopt**: 既存 `_load_approval_record` の `allowed_keys` set に `restore_rollback_claim` を追加しないと extra-key として `record_malformed` で reject される。新規 `_parse_restore_rollback_claim_dict` + `_restore_rollback_claims_match` + `ApprovalRecord` constructor 拡張を同時に plan に含める。

新規 dataclass:

```python
# SP022-T02 Phase 4 / T08 batch 4: restore_rollback_claim
@dataclass(frozen=True)
class RestoreRollbackApprovalClaim:
    """Restore-rollback-specific approval claim.

    Phase 3 restore_claim と異なり archive_sha256 / age public key 不要 (snapshot 内 data
    が正本)、代わりに pre_restore_dir + snapshot_manifest_sha256 で snapshot binding を確立。
    """

    pre_restore_ts: str  # snapshot timestamp (`^\d{8}T\d{6}(?:-\d+)?$`)、CLI `args.rollback` 一致
    pre_restore_dir: str  # absolute normpath of snapshot directory (`<data_dir>/_pre-restore-<ts>`)
    snapshot_manifest_sha256: str  # 64-char hex sha256 of snapshot_manifest.json (R1 F-004 adopt)
    target_pg_dsn_components: dict[str, str]  # {host, port, db, user} 4-tuple (rollback では現運用先)
    target_redis_endpoint: str
    target_artifacts_dir: str
    target_artifacts_container_path: str
    target_compose_project_name: str
    target_compose_file_path: str
    expected_postgres_major_version: str  # rollback でも DB major mismatch reject
```

`ApprovalRecord` dataclass を拡張:

```python
@dataclass(frozen=True)
class ApprovalRecord:
    # ... existing fields ...
    backup_claim: BackupApprovalClaim | None = None      # PR #77 / Phase 2
    restore_claim: RestoreApprovalClaim | None = None    # PR #78 / Phase 3
    restore_rollback_claim: RestoreRollbackApprovalClaim | None = None  # 本 PR / Phase 4
```

`_rfc8785_canonical_payload_bytes` を拡張 (sub-record として含める、F-PR78 R2-F-001 retro-fix pattern を踏襲):

```python
def _rfc8785_canonical_payload_bytes(record: ApprovalRecord) -> bytes:
    payload: dict[str, object] = {
        "approval_id": record.approval_id,
        "decider": record.decider,
        "reason_summary": record.reason_summary,
        "signed_at": record.signed_at_str,
        "expires_at": record.expires_at_str,
        "drill_kind": record.drill_kind,
        "allowed_subcommands": list(record.allowed_subcommands),
        "target_host": record.target_host,
    }
    if record.backup_claim is not None:
        payload["backup_claim"] = {...}  # 既存
    if record.restore_claim is not None:
        payload["restore_claim"] = {...}  # 既存
    if record.restore_rollback_claim is not None:
        rrc = record.restore_rollback_claim
        payload["restore_rollback_claim"] = {
            "pre_restore_ts": rrc.pre_restore_ts,
            "pre_restore_dir": rrc.pre_restore_dir,
            "snapshot_manifest_sha256": rrc.snapshot_manifest_sha256,
            "target_pg_dsn_components": dict(sorted(rrc.target_pg_dsn_components.items())),
            "target_redis_endpoint": rrc.target_redis_endpoint,
            "target_artifacts_dir": rrc.target_artifacts_dir,
            "target_artifacts_container_path": rrc.target_artifacts_container_path,
            "target_compose_project_name": rrc.target_compose_project_name,
            "target_compose_file_path": rrc.target_compose_file_path,
            "expected_postgres_major_version": rrc.expected_postgres_major_version,
        }
    return _jcs_canonicalize(payload)
```

`verify_signed_approval` を拡張:

```python
def verify_signed_approval(
    approval_id: str,
    subcommand: str,
    target_host: str | None = None,
    backup_claim: BackupApprovalClaim | None = None,
    restore_claim: RestoreApprovalClaim | None = None,
    restore_rollback_claim: RestoreRollbackApprovalClaim | None = None,  # 本 PR で追加
) -> ...:
    # ... 既存 ...
    # 本 PR で追加
    if subcommand == "restore-rollback":
        if restore_rollback_claim is None:
            return False, "taskhub_signed_approval_restore_rollback_claim_required", extras
        record_rrc = record.restore_rollback_claim
        if record_rrc is None:
            # Phase 1/2/3 record (restore_rollback_claim 不在) は restore-rollback では deny
            return False, "taskhub_signed_approval_restore_rollback_claim_required", extras
        if not _restore_rollback_claims_match(restore_rollback_claim, record_rrc):
            extras["expected_rrc_pre_restore_ts"] = record_rrc.pre_restore_ts
            extras["actual_rrc_pre_restore_ts"] = restore_rollback_claim.pre_restore_ts
            return False, "taskhub_signed_approval_restore_rollback_claim_mismatch", extras
```

`require_approval_for_destructive` も `restore_rollback_claim` parameter + `subcommand == "restore-rollback" and allow_unsigned_manual_skeleton` hard deny を追加 (R1 F-002 adopt):

```python
def require_approval_for_destructive(
    subcommand: str,
    approval_id: str | None,
    from_automation: bool,
    allow_unsigned_manual_skeleton: bool,
    target_host: str | None = None,
    backup_claim: BackupApprovalClaim | None = None,
    restore_claim: RestoreApprovalClaim | None = None,
    restore_rollback_claim: RestoreRollbackApprovalClaim | None = None,
) -> ...:
    # ... 既存 ...
    # R1 F-002 adopt: restore-rollback も backup/restore と同じく allow_unsigned_manual_skeleton 物理 deny
    if subcommand == "restore-rollback" and allow_unsigned_manual_skeleton:
        return False, "taskhub_signed_approval_restore_rollback_allow_unsigned_skeleton_rejected", extras
```

新規 ReasonCode 3 種を追加 (signed_approval.py の ReasonCode Literal に):
- `taskhub_signed_approval_restore_rollback_claim_required`
- `taskhub_signed_approval_restore_rollback_claim_mismatch`
- `taskhub_signed_approval_restore_rollback_allow_unsigned_skeleton_rejected`

**R2 F-002 adopt: 既存 strict loader 拡張 (`_load_approval_record` + `ApprovalRecord` constructor + parser/matcher)**

```python
# scripts/taskhub_signed_approval.py 内 _load_approval_record の allowed_keys に追加
allowed_keys = {
    "approval_id", "decider", "reason_summary", "signed_at", "expires_at",
    "drill_kind", "allowed_subcommands", "target_host", "signature",
    "backup_claim",
    "restore_claim",
    "restore_rollback_claim",  # 本 PR で追加 (R2 F-002 adopt)
}

# 同 module 内、_parse_restore_claim_dict と並列 pattern で
def _parse_restore_rollback_claim_dict(rrc: object) -> RestoreRollbackApprovalClaim | None:
    """schema strict: 10 field exact, ADV R1 F-010 adopt: per-field type/format validate."""
    if not isinstance(rrc, dict):
        return None
    expected_keys = frozenset({
        "pre_restore_ts", "pre_restore_dir", "snapshot_manifest_sha256",
        "target_pg_dsn_components", "target_redis_endpoint",
        "target_artifacts_dir", "target_artifacts_container_path",
        "target_compose_project_name", "target_compose_file_path",
        "expected_postgres_major_version",
    })
    if set(rrc.keys()) != expected_keys:
        return None
    # ADV R1 F-010 adopt: per-field non-empty str / type / format validate
    str_fields = ["pre_restore_ts", "pre_restore_dir", "snapshot_manifest_sha256",
                  "target_redis_endpoint", "target_artifacts_dir", "target_artifacts_container_path",
                  "target_compose_project_name", "target_compose_file_path",
                  "expected_postgres_major_version"]
    for f in str_fields:
        v = rrc[f]
        if not isinstance(v, str) or not v:
            return None
    # snapshot_manifest_sha256: 64-char lowercase hex
    if not re.fullmatch(r"^[0-9a-f]{64}$", rrc["snapshot_manifest_sha256"]):
        return None
    # absolute normalized paths
    for f in ["pre_restore_dir", "target_artifacts_dir",
              "target_artifacts_container_path", "target_compose_file_path"]:
        if not rrc[f].startswith("/"):
            return None
    # postgres_major_version: ADV R1 F-016 adopt regex
    if not re.fullmatch(r"^[1-9][0-9]*$", rrc["expected_postgres_major_version"]):
        return None
    # target_pg_dsn_components: dict[str, str], keys = {host, port, db, user}
    dsn = rrc["target_pg_dsn_components"]
    if not isinstance(dsn, dict):
        return None
    if set(dsn.keys()) != {"host", "port", "db", "user"}:
        return None
    for k, v in dsn.items():
        if not isinstance(v, str) or not v:
            return None
    # port must be digit-only
    if not re.fullmatch(r"^[1-9][0-9]*$", dsn["port"]):
        return None
    return RestoreRollbackApprovalClaim(
        pre_restore_ts=rrc["pre_restore_ts"],
        pre_restore_dir=rrc["pre_restore_dir"],
        snapshot_manifest_sha256=rrc["snapshot_manifest_sha256"],
        target_pg_dsn_components=dict(rrc["target_pg_dsn_components"]),
        target_redis_endpoint=rrc["target_redis_endpoint"],
        target_artifacts_dir=rrc["target_artifacts_dir"],
        target_artifacts_container_path=rrc["target_artifacts_container_path"],
        target_compose_project_name=rrc["target_compose_project_name"],
        target_compose_file_path=rrc["target_compose_file_path"],
        expected_postgres_major_version=rrc["expected_postgres_major_version"],
    )

# 同 module 内、_restore_claims_match と並列 pattern で
def _restore_rollback_claims_match(
    a: RestoreRollbackApprovalClaim, b: RestoreRollbackApprovalClaim,
) -> bool:
    """10 field strict compare (dict は sorted items 比較)."""
    return (
        a.pre_restore_ts == b.pre_restore_ts
        and a.pre_restore_dir == b.pre_restore_dir
        and a.snapshot_manifest_sha256 == b.snapshot_manifest_sha256
        and dict(sorted(a.target_pg_dsn_components.items())) == dict(sorted(b.target_pg_dsn_components.items()))
        and a.target_redis_endpoint == b.target_redis_endpoint
        and a.target_artifacts_dir == b.target_artifacts_dir
        and a.target_artifacts_container_path == b.target_artifacts_container_path
        and a.target_compose_project_name == b.target_compose_project_name
        and a.target_compose_file_path == b.target_compose_file_path
        and a.expected_postgres_major_version == b.expected_postgres_major_version
    )

# _load_approval_record 内、parser dispatch に追加
rrc_raw = data.get("restore_rollback_claim")
record_restore_rollback_claim = _parse_restore_rollback_claim_dict(rrc_raw) if rrc_raw is not None else None
# (rrc_raw is not None だが parse 失敗 → record_malformed reason_code)
if rrc_raw is not None and record_restore_rollback_claim is None:
    return None, "taskhub_signed_approval_record_malformed"

# ApprovalRecord(..., restore_rollback_claim=record_restore_rollback_claim) constructor 拡張
```

#### 3.A.1 snapshot_manifest.json (R1 F-004 + R2 F-004 + F-006 adopt)

`create_pre_restore_snapshot` (`scripts/taskhub_restore_orchestrator.py:1245`) を拡張: snapshot dir 内に `snapshot_manifest.json` を atomic write (`.tmp` → rename)。**書込タイミング**: artifacts move → register_dir() → pg_dump finalize → redis SAVE finalize → **最後に manifest atomic write** (全 component の hash が揃った後)。これにより partial fail で manifest が存在しない state を保証 (manifest 不在 → rollback verify reject `restore_rollback_snapshot_manifest_missing`)。

**R2 F-004 adopt**: component schema は `{present: bool, sha256: string|null, skipped_reason: string|null}` per-component (partial snapshot 許容)、既存 rollback semantics (DB / Redis 不在で warning + continue) と整合。

**R2 F-006 adopt**: `alembic_head_at_snapshot` は **docker compose exec + container 内 unix socket 経由のみ** で取得 (既存 `verify_alembic_head_in_db` パターンに揃える、`scripts/taskhub_restore_orchestrator.py:1198-1226` 参照)、host TCP 経由禁止。新規 helper `read_alembic_head_via_compose_exec(options)` を追加。

```json
{
  "manifest_version": 1,
  "snapshot_id": "<ts>" or "<ts>-<attempt>",
  "created_at_utc": "2026-05-20T10:30:00Z",
  "target_compose_project_name": "taskmanagedai",
  "target_compose_file_path": "/abs/path/docker-compose.yml",
  "target_pg_dsn_components": {"host": "...", "port": "...", "db": "...", "user": "..."},
  "target_redis_endpoint": "127.0.0.1:6379",
  "target_artifacts_dir": "/abs/path/data/artifacts",
  "target_artifacts_container_path": "/app/data/artifacts",
  "postgres_major_version": "16",
  "alembic_head_at_snapshot": "<revision id>",
  "components": {
    "pre_restore_pg_dump.dump": {
      "present": true, "sha256": "...", "skipped_reason": null
    },
    "pre_restore_dump.rdb": {
      "present": false, "sha256": null, "skipped_reason": "redis_save_failed_at_snapshot_time"
    },
    "artifacts": {
      "present": true, "sha256": "...", "skipped_reason": null
    }
  }
}
```

`rollback_from_pre_restore_snapshot` 内で manifest verify:
1. `snapshot_manifest.json` 存在 + sha256 計算 → `restore_rollback_claim.snapshot_manifest_sha256` と一致 verify
2. manifest 内の `target_*` field と現 RestoreOptions binding 一致 verify (mismatch = `restore_rollback_snapshot_manifest_target_mismatch`)
3. 各 component file の handling:
   - `present=true`: file 存在 verify + sha256 計算 → manifest 内 expected と一致 verify (mismatch = `restore_rollback_snapshot_component_hash_mismatch`)
   - `present=false`: file 不在 OK、`skipped_reason` を warnings に積む (既存 partial snapshot semantics 維持)
   - `present=true` + file 不在 = `restore_rollback_snapshot_component_missing` reason_code

新規 ReasonCode (restore_orchestrator.py に):
- `restore_rollback_snapshot_manifest_missing`
- `restore_rollback_snapshot_manifest_invalid_json`
- `restore_rollback_snapshot_manifest_target_mismatch`
- `restore_rollback_snapshot_component_hash_mismatch`
- `restore_rollback_snapshot_component_missing` (R2 F-004 adopt)
- `restore_rollback_snapshot_id_mismatch`
- `restore_rollback_snapshot_manifest_unsupported_version` (ADV R1 F-017 adopt: manifest_version != 1 reject)
- `restore_rollback_snapshot_manifest_toctou_mismatch` (R5 F-001 adopt: lock 取得後 manifest sha256 mismatch)

**ADV R1 F-017 adopt**: `verify_snapshot_manifest_binding` 内で `manifest.get("manifest_version") == 1` を最初に check、unsupported version → `restore_rollback_snapshot_manifest_unsupported_version` で reject。将来 v2 migration 時は v1 reader を残し、v1 / v2 dual-parser を providing。

**ADV R1 F-016 adopt**: `expected_postgres_major_version` は `^[1-9][0-9]*$` regex で strict validate (issue CLI / runtime env 両方)、`"16.0"` / `"16 "` (trailing space) / `"016"` (leading zero) は reject、normalization (strip / semver 矯正) は行わない。manifest 内 `postgres_major_version` と claim の比較も同 normalized string。

**R2 F-006 adopt: alembic head reader (compose exec 経由のみ)**

```python
# scripts/taskhub_restore_orchestrator.py 内
def read_alembic_head_via_compose_exec(options: RestoreOptions) -> str | None:
    """snapshot 作成時に alembic head を取得 (compose exec + container unix socket 経由のみ).

    Returns None if alembic_version table が存在しない / connect 失敗 (snapshot 自体は OK).
    """
    argv = (
        _compose_argv_prefix(options)
        + ["exec", "-T", "postgres", "psql"]
        + [f"--username={options.target_pg_dsn_components['user']}"]
        + [f"--dbname={options.target_pg_dsn_components['db']}"]
        + ["-h", "/var/run/postgresql", "--no-password",
           "-c", "select version_num from alembic_version", "-t", "-A"]
    )
    try:
        result = run_safe_subprocess(argv, config=SafeSubprocessConfig(timeout_sec=30))
    except (SubprocessNotFoundError, SubprocessTimeoutError):
        return None  # snapshot 作成時の DB unreachable は warning、後続 rollback で binding 不一致を検出
    if result.returncode != 0:
        return None
    head = result.stdout.decode("utf-8").strip()
    return head if head else None
```

#### 3.A.2 CLI 変更 (`scripts/taskhub_admin.py`)

`_cmd_restore` (`scripts/taskhub_admin.py:242-297`) の `--rollback` 分岐を skeleton → real I/O:

```python
# 現状 (skeleton)
if args.rollback:
    allowed, reason = _run_approval_gate("restore-rollback", args)
    if not allowed:
        ...
    print(_skeleton_message("restore --rollback", ...))
    return 1  # skeleton mode

# 変更後 (real I/O、R1 F-001/F-002/F-003/F-004/F-005 adopt)
if args.rollback:
    # R1 F-003 adopt: pre-restore ts pattern strict
    PRE_RESTORE_TS_REGEX = re.compile(r"^\d{8}T\d{6}(?:-\d+)?$")
    if not PRE_RESTORE_TS_REGEX.fullmatch(args.rollback):
        print(f"ERROR: --rollback ts format invalid: {args.rollback!r} (expected YYYYMMDDTHHMMSS or YYYYMMDDTHHMMSS-N)", file=sys.stderr)
        return 2

    # data dir 解決 + resolve(strict=True) で symlink resolve + 物理存在 verify
    repo_root = Path(__file__).resolve().parent.parent
    target_data_dir_str = os.environ.get("TASKHUB_RESTORE_DATA_DIR", str(repo_root / "data"))
    try:
        target_data_dir = Path(target_data_dir_str).resolve(strict=True)
    except (OSError, FileNotFoundError):
        print(f"ERROR: target_data_dir not found: {target_data_dir_str}", file=sys.stderr)
        return 2
    # rollback では target_artifacts_dir.parent が data_dir に相当 (既存 create_pre_restore_snapshot
    # では options.target_artifacts_dir.parent / f"_pre-restore-{ts}{suffix}")
    pre_restore_dir_raw = target_data_dir / f"_pre-restore-{args.rollback}"
    try:
        pre_restore_dir = pre_restore_dir_raw.resolve(strict=True)
    except (OSError, FileNotFoundError):
        print(f"ERROR: pre-restore snapshot not found: {pre_restore_dir_raw}", file=sys.stderr)
        return 2
    if pre_restore_dir.is_symlink() or pre_restore_dir_raw.is_symlink():
        print(f"ERROR: pre-restore path must not be symlink: {pre_restore_dir}", file=sys.stderr)
        return 2
    # path traversal verify (resolve 後 data_dir 配下)
    try:
        pre_restore_dir.relative_to(target_data_dir)
    except ValueError:
        print(f"ERROR: pre-restore path escapes data_dir: {pre_restore_dir}", file=sys.stderr)
        return 2

    # R1 F-002 adopt: --allow-unsigned-manual-skeleton restore-rollback 物理 deny
    if getattr(args, "allow_unsigned_manual_skeleton", False):
        print(
            "ERROR: --allow-unsigned-manual-skeleton is rejected for restore-rollback subcommand "
            "(real I/O requires signed approval + restore_rollback_claim, no skeleton escape allowed) "
            "[reason=taskhub_signed_approval_restore_rollback_allow_unsigned_skeleton_rejected]",
            file=sys.stderr,
        )
        return 2

    # snapshot_manifest.json 読込 + sha256 計算
    manifest_path = pre_restore_dir / "snapshot_manifest.json"
    if not manifest_path.is_file():
        print(f"ERROR: snapshot_manifest.json not found in {pre_restore_dir}", file=sys.stderr)
        return 2
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    try:
        manifest_data = json.loads(manifest_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("ERROR: snapshot_manifest.json invalid JSON", file=sys.stderr)
        return 2

    # RestoreOptions for_rollback_mode construct (target binding は env から取得、claim と一致 verify)
    repo_root = Path(__file__).resolve().parent.parent
    target_compose_project = os.environ.get("TASKHUB_RESTORE_COMPOSE_PROJECT", "taskmanagedai")
    target_compose_file = Path(os.environ.get(
        "TASKHUB_RESTORE_COMPOSE_FILE", str(repo_root / "docker-compose.yml"),
    ))
    target_pg_host = os.environ.get("TASKHUB_RESTORE_PG_HOST", "127.0.0.1")
    target_pg_port = os.environ.get("TASKHUB_RESTORE_PG_PORT", "5432")
    target_pg_db = os.environ.get("TASKHUB_RESTORE_PG_DB", "taskmanagedai")
    target_pg_user = os.environ.get("TASKHUB_RESTORE_PG_USER", "taskmanagedai")
    target_redis_host = os.environ.get("TASKHUB_RESTORE_REDIS_HOST", "127.0.0.1")
    target_redis_port = os.environ.get("TASKHUB_RESTORE_REDIS_PORT", "6379")
    target_artifacts_dir = Path(os.environ.get(
        "TASKHUB_RESTORE_ARTIFACTS_DIR", str(repo_root / "data" / "artifacts"),
    )).resolve()
    target_artifacts_container_path = os.environ.get(
        "TASKHUB_RESTORE_ARTIFACTS_CONTAINER_PATH", "/app/data/artifacts",
    )
    expected_pg_major = os.environ.get("TASKHUB_RESTORE_EXPECTED_PG_MAJOR", "16")

    options = RestoreOptions.for_rollback_mode(
        pre_restore_dir=pre_restore_dir,
        target_pg_dsn_components={
            "host": target_pg_host, "port": target_pg_port,
            "db": target_pg_db, "user": target_pg_user,
        },
        target_redis_endpoint=f"{target_redis_host}:{target_redis_port}",
        target_artifacts_dir=target_artifacts_dir,
        target_artifacts_container_path=target_artifacts_container_path,
        target_compose_project_name=target_compose_project,
        target_compose_file_path=target_compose_file,
        expected_postgres_major_version=expected_pg_major,
    )

    # build RestoreRollbackApprovalClaim (R1 F-001 adopt)
    rrc = RestoreRollbackApprovalClaim(
        pre_restore_ts=args.rollback,
        pre_restore_dir=str(pre_restore_dir),
        snapshot_manifest_sha256=manifest_sha256,
        target_pg_dsn_components=dict(options.target_pg_dsn_components),
        target_redis_endpoint=options.target_redis_endpoint,
        target_artifacts_dir=str(options.target_artifacts_dir),
        target_artifacts_container_path=options.target_artifacts_container_path,
        target_compose_project_name=options.target_compose_project_name,
        target_compose_file_path=str(options.target_compose_file_path),
        expected_postgres_major_version=options.expected_postgres_major_version,
    )

    # signed approval gate with restore_rollback_claim (R1 F-001 adopt)
    # NOTE: pre-lock で archive_sha256 / manifest_sha256 を計算するのは claim 比較のため必須 (R5 F-001 adopt:
    # claim verify は approval signature の commitment、lock 内で再計算しても claim は不変)
    allowed, reason, extras = require_approval_for_destructive(
        "restore-rollback",
        args.approval_id,
        getattr(args, "from_automation", False),
        getattr(args, "allow_unsigned_manual_skeleton", False),
        restore_rollback_claim=rrc,
    )
    emit_audit_event(reason, extras)
    if not allowed:
        print(f"ERROR: signed approval gate denied (reason={reason})", file=sys.stderr)
        return 2

    # R3 F-002 + R4 F-001 + R5 F-001 adopt: destructive lock を approval gate 直後に取得
    # **R5 F-001 fix**: lock 取得を target binding / manifest / component hash verify の前に移動、
    # lock 内で manifest sha256 / target binding / component hash を **再計算** + verify (TOCTOU 排除).
    # **R4 F-001 adopt**: rollback だけでなく `--input` (Phase 3 既存) にも lock を統合.
    from scripts.taskhub_destructive_lock import acquire_destructive_lock
    with acquire_destructive_lock("restore-rollback", args.approval_id) as (acquired, lock_reason, blocker):
        if not acquired:
            blocker_summary = ""
            if blocker:
                blocker_summary = f" blocker={blocker.get('subcommand')} pid={blocker.get('pid')} started_at={blocker.get('started_at_utc')}"
            print(
                f"ERROR: destructive operation lock not acquired "
                f"(reason={lock_reason}){blocker_summary}",
                file=sys.stderr,
            )
            return 2

        warnings: list[WarningCode] = []

        # R5 F-001 adopt: lock 取得後に manifest / target binding / component hash を **再計算 + verify**
        # (TOCTOU 排除、pre-lock の sha256 と lock 内 sha256 が異なれば snapshot が他 process に move されたことを検知)
        try:
            manifest_bytes_inlock = (pre_restore_dir / "snapshot_manifest.json").read_bytes()
            manifest_sha256_inlock = hashlib.sha256(manifest_bytes_inlock).hexdigest()
            if manifest_sha256_inlock != manifest_sha256:
                print(
                    f"ERROR: snapshot_manifest.json was modified between approval gate and lock acquisition "
                    f"(pre-lock sha256={manifest_sha256[:16]}, in-lock sha256={manifest_sha256_inlock[:16]}). "
                    "Possible concurrent destructive operation race or snapshot tampering "
                    "[reason=restore_rollback_snapshot_manifest_toctou_mismatch]",
                    file=sys.stderr,
                )
                return 2
            manifest_data_inlock = json.loads(manifest_bytes_inlock.decode("utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            print("ERROR: snapshot_manifest.json unreadable after lock acquisition (concurrent removal?)",
                  file=sys.stderr)
            return 2

        # target binding consistency preflight (Phase 3 既存 8-check を rollback でも適用、lock 内で実施)
        try:
            verify_target_binding_consistency(options)
        except RestoreUsageError as exc:
            print(exc.stderr_message(), file=sys.stderr)
            return 2

        # snapshot manifest 整合 verify (R1 F-004 adopt、orchestrator 内 helper を呼ぶ、lock 内で実施)
        try:
            verify_snapshot_manifest_binding(manifest_data_inlock, options, rrc)
        except RestoreUsageError as exc:
            print(exc.stderr_message(), file=sys.stderr)
            return 2

        # component file hashes verify (R1 F-004 + R2 F-004 adopt、lock 内で実施、partial OK)
        try:
            verify_snapshot_component_hashes(pre_restore_dir, manifest_data_inlock, warnings)
        except RestoreRuntimeError as exc:
            print(exc.stderr_message(), file=sys.stderr)
            return 1

        # R1 F-005 adopt: 例外集合を拡張、rollback 実行
        try:
            rollback_from_pre_restore_snapshot(pre_restore_dir, options, warnings)
        except RestoreUsageError as exc:
            print(exc.stderr_message(), file=sys.stderr)
            return 2
        except (RestoreRuntimeError, OSError, shutil.Error,
                subprocess.SubprocessError, SubprocessTimeoutError,
                SubprocessNotFoundError) as exc:
            print(
                f"ERROR: rollback failed: {type(exc).__name__}: {exc}. "
                f"Manual recovery: docker compose -p {target_compose_project} -f {target_compose_file} ps | "
                f"snapshot at {pre_restore_dir}",
                file=sys.stderr,
            )
            return 1

        summary = {
            "subcommand": "restore-rollback",
            "pre_restore_dir": str(pre_restore_dir),
            "snapshot_manifest_sha256": manifest_sha256[:16],
            "warnings": warnings,
            "status": "completed",
        }
        print(json.dumps(summary, sort_keys=True))
        return 0
```

#### 3.A.2.5 `_cmd_restore --input` 分岐の lock 統合 (R6 F-001 adopt、CRITICAL)

`_cmd_restore` の `--input` 分岐 (existing Phase 3 real I/O、`scripts/taskhub_admin.py:299-487`) にも同じ destructive lock を追加し、`run_restore(options)` 全体を lock 内に入れる。`--rollback` と相互排他 (lock file は単一 = `~/.taskhub/locks/destructive-operation.lock`、`acquire_destructive_lock(subcommand="restore")` で payload に subcommand 記録)。

```python
# scripts/taskhub_admin.py _cmd_restore (--input 分岐、既存 Phase 3 code を lock で wrap)

    # signed approval gate (既存 Phase 3 code は変更なし、approval gate 成功直後に lock 取得)
    allowed, reason, extras = require_approval_for_destructive(
        "restore",
        args.approval_id,
        getattr(args, "from_automation", False),
        getattr(args, "allow_unsigned_manual_skeleton", False),
        restore_claim=restore_claim,
    )
    emit_audit_event(reason, extras)
    if not allowed:
        print(f"ERROR: signed approval gate denied (reason={reason})", file=sys.stderr)
        return 2

    # R4 F-001 + R6 F-001 adopt: --input にも destructive lock 統合 (rollback と cross-subcommand mutual exclusion)
    from scripts.taskhub_destructive_lock import acquire_destructive_lock
    with acquire_destructive_lock("restore", args.approval_id) as (acquired, lock_reason, blocker):
        if not acquired:
            blocker_summary = ""
            if blocker:
                blocker_summary = f" blocker={blocker.get('subcommand')} pid={blocker.get('pid')} started_at={blocker.get('started_at_utc')}"
            print(
                f"ERROR: destructive operation lock not acquired "
                f"(reason={lock_reason}){blocker_summary}",
                file=sys.stderr,
            )
            return 2

        # Real restore orchestration (SP022-T02 Phase 3、lock 内で実行)
        try:
            result = run_restore(options)
        except RestoreUsageError as exc:
            print(exc.stderr_message(), file=sys.stderr)
            return 2
        except RestoreRuntimeError as exc:
            print(exc.stderr_message(), file=sys.stderr)
            return 1
        print(json.dumps(result.summary(), sort_keys=True))
        return 0
```

#### 3.A.2.6 `rollback_from_pre_restore_snapshot` の boundary (R6 F-002 adopt、CRITICAL)

**`rollback_from_pre_restore_snapshot` 自体は manifest verify を行わない**。Manifest / target binding / component hash verify は **CLI standalone path (3.A.2 内、lock 内)** でのみ実施。

理由 (R6 F-002): `run_restore()` の auto-rollback 経路 (Phase 3 既存) は `create_pre_restore_snapshot()` 中に pg_dump / Redis SAVE が失敗した場合、`rollback_from_pre_restore_snapshot()` を呼んで artifacts を戻す設計 (`run_restore`:1582-1600 範囲)。この auto-rollback 時に **manifest 不在の可能性が高い** (snapshot 作成中に失敗、manifest は最後に書く)。`rollback_from_pre_restore_snapshot` 内で manifest 必須 verify を追加すると、auto-rollback が manifest missing で止まり、artifacts が戻らず data path loss する。

実装方針:
- `rollback_from_pre_restore_snapshot(pre_restore_dir, options, warnings)` の **signature 変更なし**
- 内部は既存 partial snapshot semantics 維持 (pre_db_dump 不在 → warning、artifacts move、Redis snapshot 不在 → warning)
- Manifest / target binding / component hash verify は **CLI rollback 分岐 (§3.A.2 内、lock 内)** で `verify_snapshot_manifest_binding()` / `verify_snapshot_component_hashes()` 経由のみ実施
- `run_restore()` の auto-rollback 経路は manifest verify を skip (`rollback_from_pre_restore_snapshot` を直接呼ぶ、その内部に manifest verify が無いため自然に skip)

新規 test:
- `test_run_restore_auto_rollback_without_manifest_recovers_artifacts` (R6 F-002 adopt): `create_pre_restore_snapshot` で pg_dump 失敗 mock → `run_restore` 内で `rollback_from_pre_restore_snapshot` が呼ばれる → manifest 不在でも artifacts が戻る (既存 Phase 3 regression を防御)

#### 3.A.2.7 _cmd_restore 構造変更後の全体 flow

`_cmd_restore` の構造は本 PR で以下になる:

```
_cmd_restore(args):
  if args.input and args.rollback: return 2 (exclusive)
  if not args.input and not args.rollback: return 2 (one required)
  if allow_unsigned_manual_skeleton (restore のみ既存物理 deny): return 2
  
  if args.rollback:
    # §3.A.2 path (本 PR 新規)
    1. ts pattern validate
    2. data_dir resolve + pre_restore_dir resolve(strict=True) + symlink reject + path traversal verify
    3. allow_unsigned_manual_skeleton restore-rollback 物理 deny
    4. manifest read + sha256 計算 (claim 用)
    5. RestoreOptions.for_rollback_mode construct
    6. RestoreRollbackApprovalClaim construct
    7. require_approval_for_destructive (gate)
    8. acquire_destructive_lock("restore-rollback") 取得
       8a. manifest 再読込 + sha256 再計算 + TOCTOU verify
       8b. verify_target_binding_consistency
       8c. verify_snapshot_manifest_binding (claim vs manifest)
       8d. verify_snapshot_component_hashes (manifest vs actual files)
       8e. rollback_from_pre_restore_snapshot (artifacts/DB/Redis 復旧)
       8f. release lock
    9. exit 0 with summary
  
  if args.input:
    # §3.A.2.5 path (Phase 3 既存 + lock 追加)
    1-6. archive sha256 / age identity / RestoreOptions / RestoreApprovalClaim (既存)
    7. require_approval_for_destructive (gate、既存)
    8. acquire_destructive_lock("restore") 取得 (本 PR 新規)
       8a. run_restore(options) (既存 Phase 3 real I/O、auto-rollback 含む)
       8b. release lock
    9. exit 0 with summary
```

#### 3.A.3 `RestoreOptions.for_rollback_mode()` classmethod (`scripts/taskhub_restore_orchestrator.py`、R2 F-005 adopt)

**R2 F-005 adopt: `run_restore()` には rollback_mode を導入しない**。CLI rollback 分岐は **`rollback_from_pre_restore_snapshot` を直接呼ぶ**ため、`run_restore()` 内の `.tar.age` suffix / age identity / archive_sha256 validation を bypass する必要はない (そもそも `run_restore()` 経由しない)。`for_rollback_mode` は CLI で `rollback_from_pre_restore_snapshot` に渡す **subset RestoreOptions** を生成する classmethod として実装するが、`run_restore()` に渡しても **意図的に suffix check で fail** する設計 (defense-in-depth: rollback option を restore に誤って渡したら確実に止まる)。

`RestoreOptions` dataclass に `rollback_mode: bool = False` を追加しない (R2 F-005 reject prior 設計、簡潔性優先)。

```python
@classmethod
def for_rollback_mode(
    cls, *,
    pre_restore_dir: Path,
    target_pg_dsn_components: dict[str, str],
    target_redis_endpoint: str,
    target_artifacts_dir: Path,
    target_artifacts_container_path: str,
    target_compose_project_name: str,
    target_compose_file_path: Path,
    expected_postgres_major_version: str,
) -> RestoreOptions:
    """rollback 用 RestoreOptions (subset、CLI rollback branch から `rollback_from_pre_restore_snapshot`
    + target binding verify + manifest verify でのみ使用、`run_restore()` には渡さない)."""
    return cls(
        input_path=pre_restore_dir,  # sentinel: dir、`run_restore()` に渡すと意図的に fail
        archive_sha256="",  # not used in rollback
        age_identity_file=Path("/dev/null"),
        target_pg_dsn_components=target_pg_dsn_components,
        target_redis_endpoint=target_redis_endpoint,
        target_artifacts_dir=target_artifacts_dir,
        target_artifacts_container_path=target_artifacts_container_path,
        target_compose_project_name=target_compose_project_name,
        target_compose_file_path=target_compose_file_path,
        expected_postgres_major_version=expected_postgres_major_version,
        expected_alembic_head="",  # not used
        overwrite=True,
    )
```

新規 helper:
- `verify_snapshot_manifest_binding(manifest: dict, options: RestoreOptions, rrc: RestoreRollbackApprovalClaim) -> None` (RestoreUsageError raise on mismatch)
- `verify_snapshot_component_hashes(pre_restore_dir: Path, manifest: dict, warnings: list[WarningCode]) -> None` (R2 F-004 adopt: present=false の skipped_reason は warnings に追加、RestoreRuntimeError raise on present=true mismatch / missing)

#### 3.A.4 test fixtures (`tests/scripts/test_taskhub_admin.py` + `tests/scripts/test_taskhub_restore_orchestrator.py` + `tests/scripts/test_taskhub_signed_approval.py`)

| # | test name | scope |
|---|---|---|
| 1 | `test_cli_rollback_ts_pattern_invalid_returns_exit_2` | `--rollback foo-bar` で regex mismatch → exit 2 |
| 2 | `test_cli_rollback_missing_snapshot_dir_returns_exit_2` | snapshot dir 不在で exit 2 |
| 3 | `test_cli_rollback_path_traversal_rejected` | `--rollback ../../../etc` 形式 ts で reject |
| 4 | `test_cli_rollback_pre_restore_dir_symlink_rejected` | snapshot dir が symlink で reject (resolve 前 path) |
| 5 | `test_cli_rollback_target_data_dir_unresolvable_rejected` | TASKHUB_RESTORE_DATA_DIR 不在 / FS error で exit 2 |
| 6 | `test_cli_rollback_approval_missing_returns_exit_2` | `--approval-id` 未指定で exit 2 |
| 7 | `test_cli_rollback_approval_invalid_signature_returns_exit_2` | signed record の signature が invalid (key mismatch) で exit 2 |
| 8 | `test_cli_rollback_allow_unsigned_manual_skeleton_rejected` (R1 F-002) | `--allow-unsigned-manual-skeleton` で reason_code=restore_rollback_allow_unsigned_skeleton_rejected |
| 9 | `test_cli_rollback_drill_kind_mismatch_returns_exit_2` | drill_kind=age_rotate + subcommand=restore-rollback で reject |
| 10 | `test_cli_rollback_restore_rollback_claim_missing_returns_exit_2` (R1 F-001) | approval record の restore_rollback_claim 不在で reject |
| 11 | `test_cli_rollback_restore_rollback_claim_mismatch_returns_exit_2` (R1 F-001) | rrc の pre_restore_ts 等が CLI 計算値と不一致で reject |
| 12 | `test_cli_rollback_snapshot_manifest_missing_returns_exit_2` (R1 F-004) | snapshot_manifest.json 不在で reject |
| 13 | `test_cli_rollback_snapshot_manifest_invalid_json_returns_exit_2` | manifest 壊れ JSON で reject |
| 14 | `test_cli_rollback_snapshot_manifest_sha256_tampered_rejected` (R1 F-001 + F-004) | manifest content 書換で claim sha256 mismatch reject |
| 15 | `test_cli_rollback_snapshot_manifest_target_mismatch_rejected` (R1 F-004) | manifest 内 target_pg_db が現 options と不一致で reject |
| 16 | `test_cli_rollback_snapshot_component_hash_mismatch_rejected` (R1 F-004) | manifest 内 component hash と実 file sha256 が不一致で reject |
| 17 | `test_for_rollback_mode_construct_returns_minimal_options` (R2 F-005 adopt) | RestoreOptions.for_rollback_mode() の field 値が dataclass default 完全一致 + input_path が pre_restore_dir + overwrite=True + expected_alembic_head="" |
| 18 | `test_create_pre_restore_snapshot_writes_manifest` (R1 F-004) | Phase 3 既存 snapshot 作成で manifest.json も atomic write される |
| 19 | `test_rollback_from_snapshot_artifacts_only_restored` | pre_db_dump 不在で warnings 記録 + artifacts のみ復旧 |
| 20 | `test_rollback_from_snapshot_oserror_caught` (R1 F-005) | shutil.move OSError mock で CLI broad except catch + exit 1 |
| 21 | `test_rollback_from_snapshot_subprocess_timeout_caught` (R1 F-005) | pg_restore SubprocessTimeoutError で exit 1 |
| 22 | `test_cli_rollback_success_returns_exit_0_with_summary_json` | rollback 成功で stdout に JSON summary print + exit 0 |
| 23 | `test_cli_rollback_target_binding_mismatch_returns_exit_2` | TASKHUB_RESTORE_PG_DB が docker-compose と不一致で reject |
| 24 | `test_signed_approval_verify_restore_rollback_record_allows` (R1 F-001) | RestoreRollbackApprovalClaim 完全一致で verify allow |
| 25 | `test_signed_approval_verify_restore_rollback_phase1_record_denied` (R1 F-001) | Phase 1 record (restore_rollback_claim 不在) は restore-rollback で deny |
| 26 | `test_destructive_lock_acquire_success` (R3 F-002) | initial state で lock 取得 + payload write + release |
| 27 | `test_destructive_lock_busy_returns_blocker_payload` (R3 F-002) | 2 process が同時に取得試行で 2 番目は reason=destructive_lock_busy + blocker payload に subcommand/pid/started_at |
| 28 | `test_destructive_lock_dir_world_readable_rejected` (R3 F-002) | parent dir mode 0o755 で reason=destructive_lock_dir_permission |
| 29 | `test_destructive_lock_file_symlink_rejected` (R3 F-002) | lock file が symlink で reason=destructive_lock_file_permission (O_NOFOLLOW) |
| 30 | `test_cli_rollback_concurrent_busy_returns_exit_2` (R3 F-002) | 2 並列 `taskhub restore --rollback` で 2 番目が exit 2 + blocker info stderr |
| 31 | `test_cli_restore_input_acquires_destructive_lock` (R4 F-001) | `_cmd_restore --input` も lock 取得、--input 中の --rollback は busy reject |
| 32 | `test_cli_restore_input_and_rollback_concurrent_busy` (R4 F-001) | --input running + 並列 --rollback で 2 番目が busy reject (cross-subcommand mutual exclusion) |
| 33 | `test_cli_rollback_toctou_manifest_modified_rejected` (R5 F-001) | approval gate 後 + lock 取得前に manifest.json を書き換え → lock 内再計算で sha256 mismatch reject (`restore_rollback_snapshot_manifest_toctou_mismatch`) |
| 34 | `test_cli_rollback_toctou_manifest_removed_rejected` (R5 F-001) | approval gate 後 + lock 取得前に manifest.json を削除 → lock 内 OSError catch + exit 2 |
| 35 | `test_cli_restore_input_acquires_lock_then_runs_restore` (R6 F-001) | --input branch で require_approval_for_destructive 成功 → acquire_destructive_lock("restore") 取得 → run_restore() 全体が lock 内で実行 |
| 36 | `test_run_restore_auto_rollback_without_manifest_recovers_artifacts` (R6 F-002) | run_restore() の create_pre_restore_snapshot で pg_dump 失敗 mock → auto-rollback 経路で manifest 不在でも artifacts が戻る (rollback_from_pre_restore_snapshot は manifest verify 行わない契約) |

### Batch B: `taskhub status --remote <host>` Tailscale SSH split-brain detection

#### 3.B.1 新規 file `scripts/taskhub_remote_status.py`

```python
"""SP022-T02 Phase 4: `taskhub status --remote <host>` Tailscale SSH-based service down verify.

ADR-00021 §11.2 + §285 split-brain prevention first line of defense.
旧 host で docker compose ps 経由 service down 確認、Tailscale 閉域経由のみ。

Security invariants:
- ssh は Tailscale SSH (`-o ProxyCommand="tailscale serve ssh ..."` または直接 `ssh <host>`)
  に限定、ssh_config に Host alias 経由 (rules/secretbroker-boundary.md: raw key 非保存)
- ssh option 強制:
  - StrictHostKeyChecking=yes (Tailscale ACL で device 認証済の前提)
  - UserKnownHostsFile=~/.ssh/known_hosts (custom path 禁止)
  - BatchMode=yes (interactive prompt 全 reject)
  - ConnectTimeout=10s
  - ServerAliveInterval=5 / ServerAliveCountMax=2 (15s で切断検知)
- subprocess は scripts.taskhub_subprocess_runner 経由 (timeout / OOM 防護同等)
- 受信 stdout は max 64 KiB 制限 (rogue host 経由の amplification 攻撃防止)
- output schema strict (docker compose ps JSON のみ受容、free-form text reject)
- R1 F-007 adopt: compose project / file は per-host signed config に固定、env override は
  host-bound (TASKHUB_REMOTE_HOST_CONFIGS_PATH 経由の signed JSON)
- R1 F-006 adopt: expected_services は host-config に exact set 定義、wrong project/file で
  empty JSON は safe ではなく remote_status_remote_identity_unverified で deny
- R1 F-016 adopt: known_hosts 未登録は別 reason_code (remote_status_ssh_host_key_untrusted) で reject、
  operator-runbook に bootstrap 手順記載
"""
```

ReasonCode (16 種、R1 + R2 + ADV R1 adopt 後):

```python
ReasonCode = Literal[
    "remote_status_ok_down",                            # 全 service exited/dead (split-brain 安全)
    "remote_status_partial_up",                         # 一部 service up (deny)
    "remote_status_all_up",                             # 全 service up (deny)
    "remote_status_state_unknown",                      # ADV R1 F-003: transitional/unknown state 混在 (deny)
    "remote_status_ssh_failed",
    "remote_status_ssh_timeout",
    "remote_status_ssh_auth_failed",
    "remote_status_ssh_host_key_untrusted",             # R1 F-016
    "remote_status_compose_unavailable",
    "remote_status_invalid_host",                       # host が signed config に不在
    "remote_status_remote_identity_unverified",         # R1 F-006: services exact set mismatch
    "remote_status_stdout_oversize",
    "remote_status_compose_output_malformed",
    "remote_status_config_missing",                     # ADV R1 F-014: signed config 不在
    "remote_status_config_permission_unsafe",           # ADV R1 F-014: signed config mode != 0o600
    "remote_status_config_signature_invalid",           # ADV R1 F-014: signed config signature mismatch
    "remote_status_config_malformed",                   # ADV R1 F-014: signed config JSON parse 失敗
    "remote_status_config_expired",                     # ADV R1 F-011: signed config expires_at 超過
    "remote_status_config_unsupported_version",         # ADV R1 F-011: config_version unsupported
]
```

#### 3.B.2 host-specific signed config (R1 F-006/F-007 adopt)

新規 file `~/.taskhub/remote_hosts.signed.json` (operator が事前配備、Ed25519 sign 済、本 PR は **read + verify のみ**、issue は operator-runbook で記載):

```json
{
  "signature": "<base64 Ed25519 sig of canonical_for_signature('remote_hosts.v1', payload)>",
  "config_version": 1,
  "signed_at": "2026-05-20T10:00:00Z",
  "expires_at": "2026-11-20T10:00:00Z",
  "hosts": {
    "t-ohga-mac": {
      "compose_project": "taskmanagedai",
      "compose_file": "/Users/tohga/repo/TaskManagedAI/docker-compose.yml",
      "compose_file_sha256": "<64-char hex lowercase>",
      "expected_services": ["api", "worker", "postgres", "redis", "frontend"]
    },
    "t-ohga-linux": {
      "compose_project": "taskmanagedai",
      "compose_file": "/var/lib/taskhub/docker-compose.yml",
      "compose_file_sha256": "<64-char hex lowercase>",
      "expected_services": ["api", "worker", "postgres", "redis", "frontend"]
    },
    "t-ohga-vps": {
      "compose_project": "taskmanagedai",
      "compose_file": "/home/moltbot/repo/TaskManagedAI/docker-compose.yml",
      "compose_file_sha256": "<64-char hex lowercase>",
      "expected_services": ["api", "worker", "postgres", "redis", "frontend"]
    }
  }
}
```

(R1 F-006 adopt: `frontend` service を expected_services に含める、docker-compose.yml:33-61 整合)
(ADV R1 F-009 adopt: `compose_file_sha256` を追加、remote host で `sha256sum <compose_file>` 経由整合 verify)
(ADV R1 F-011 adopt: `config_version` + `expires_at` 追加、stale config / unsupported version reject)
(ADV R1 F-012 + ADV R2 F-002 adopt: signature root は **shared canonicalizer** `canonical_for_signature(domain, payload)` を経由、approval record と remote_hosts で domain tag を分離)

**ADV R2 F-002 adopt: `canonical_for_signature` byte layout 仕様 (remote_hosts only、backward compat 配慮)**

```python
# scripts/taskhub_signed_approval.py 内 (新規 helper、approval record の既存 layout は変更しない)
def canonical_for_signature(domain: Literal["remote_hosts.v1"], payload: dict) -> bytes:
    """domain-separated RFC 8785 JCS canonical JSON encoder for non-approval signature roots.

    layout: jcs_canonical({"domain": domain, "payload": payload})

    本 PR では domain = "remote_hosts.v1" のみ採用。
    approval record (ApprovalRecord) は **既存 _rfc8785_canonical_payload_bytes(record) の layout
    を変更しない** (PR #75/#77/#78 で発行された record の backward compat 維持)、
    本 PR は restore_rollback_claim sub-record の追加のみ。
    """
    wrapped = {"domain": domain, "payload": payload}
    return _jcs_canonicalize(wrapped)


# 既存 _rfc8785_canonical_payload_bytes は **変更なし** (本 PR では restore_rollback_claim
# sub-record を payload dict に追加するのみ、top-level layout は不変)
def _rfc8785_canonical_payload_bytes(record: ApprovalRecord) -> bytes:
    payload: dict[str, object] = {
        "approval_id": record.approval_id,
        "decider": record.decider,
        "reason_summary": record.reason_summary,
        "signed_at": record.signed_at_str,
        "expires_at": record.expires_at_str,
        "drill_kind": record.drill_kind,
        "allowed_subcommands": list(record.allowed_subcommands),
        "target_host": record.target_host,
    }
    if record.backup_claim is not None:
        payload["backup_claim"] = {...}  # 既存 PR #77
    if record.restore_claim is not None:
        payload["restore_claim"] = {...}  # 既存 PR #78
    if record.restore_rollback_claim is not None:
        payload["restore_rollback_claim"] = {...}  # 本 PR 追加
    return _jcs_canonicalize(payload)  # 既存 layout 維持 (domain wrap なし)
```

**Backward compat**: 既存 PR #75/#77/#78 record (rrc 不在) は _rfc8785 で **同 byte sequence** を生成、verify allow。本 PR の rrc 付き record は **新規 layout** だが既存 record と互換 (rrc field がない場合は old behavior)。

**migration scope**: PR #75/#77/#78 record の re-sign 不要 (rrc 不在で verify allow)、本 PR で生成する新 record の verify path は新規追加分のみ。runbook §4 は backup_claim / restore_claim 追加時 (PR #77/#78) の archive SOP を維持、本 PR では migration は不要。

golden vector test:
- `test_rfc8785_approval_record_without_rrc_unchanged_layout` (PR #75/#77/#78 backward compat)
- `test_rfc8785_approval_record_with_rrc_includes_subrecord`
- `test_canonical_for_signature_remote_hosts_v1_reference_vector`

config 読込時 (ADV R1 F-014 adopt: reason_code 別個に):
1. file 存在 + chmod 0o600 verify (mode != 0o600 → `remote_status_config_permission_unsafe`)
2. JSON parse (失敗 → `remote_status_config_malformed`)
3. `config_version != 1` → `remote_status_config_unsupported_version`
4. `expires_at < now()` → `remote_status_config_expired` (ADV R1 F-011)
5. signature field 取出 → `canonical_for_signature("remote_hosts.v1", payload_without_signature)` を Ed25519 verify (verify key は approval-verify-key.pub を流用、本 PR では single-key 運用、SP-012 で separation of duties)
6. signature 不正 → `remote_status_config_signature_invalid`
7. CLI が指定した `--remote <host>` を hosts dict から lookup、host 不在 → `remote_status_invalid_host`
8. SSH 経由で remote host の compose_file の sha256 計算 → config の `compose_file_sha256` と一致 verify (ADV R1 F-009 adopt、mismatch → `remote_status_remote_identity_unverified`)

これにより compose_project / compose_file (content hash 含む) / expected_services / config 期限 / config version が **per-host で固定** され、env 経由の上書きは不可。

#### 3.B.3 SSH command 構成 (R1 F-007 adopt)

```python
def _build_ssh_argv(host: str, compose_project: str, compose_file: str, timeout_sec: int) -> list[str]:
    """SSH command を vector で構築、shell injection 完全排除.

    docker compose -p <project> -f <file> ps --format json を実行、
    全引数は固定 + per-host signed config からのみ。
    """
    import unicodedata
    # compose_project / compose_file は signed config から取得、env から取得しない
    PROJECT_REGEX = re.compile(r"^[a-z][a-z0-9_-]*$")
    if not PROJECT_REGEX.fullmatch(compose_project):
        raise ValueError(f"compose_project invalid: {compose_project}")
    # ADV R1 F-013 adopt: Unicode NFC 正規化 + Cc/Cf (control chars) / bidi override reject
    compose_file_nfc = unicodedata.normalize("NFC", compose_file)
    if compose_file_nfc != compose_file:
        raise ValueError(f"compose_file must be in NFC form: {compose_file!r}")
    if not compose_file.startswith("/") or "\x00" in compose_file or "\n" in compose_file:
        raise ValueError(f"compose_file must be absolute path without NUL/newline: {compose_file}")
    for ch in compose_file:
        cat = unicodedata.category(ch)
        # Cc = control, Cf = format (zero-width, bidi override)
        if cat in ("Cc", "Cf"):
            raise ValueError(f"compose_file contains control/format character: U+{ord(ch):04X}")

    return [
        "ssh",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "UserKnownHostsFile=" + str(Path.home() / ".ssh" / "known_hosts"),
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={timeout_sec}",
        "-o", "ServerAliveInterval=5",
        "-o", "ServerAliveCountMax=2",
        "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "GSSAPIAuthentication=no",
        "-o", "PreferredAuthentications=publickey",
        "--",
        host,
        # remote command: ssh argv は shell に渡るが、固定 string なので injection 不可
        f"docker compose -p {shlex.quote(compose_project)} -f {shlex.quote(compose_file)} ps --format json",
    ]
```

`shlex.quote()` で project_name と file_path を quote (defense-in-depth、上記 regex 通過後も適用)。known_hosts 未登録時の ssh exit code は stderr pattern (`Host key verification failed`) から `remote_status_ssh_host_key_untrusted` に分岐。

#### 3.B.4 query_remote_compose_status 実装

```python
@dataclass(frozen=True)
class RemoteHostConfig:
    compose_project: str
    compose_file: str
    expected_services: tuple[str, ...]

@dataclass(frozen=True)
class RemoteStatusOptions:
    remote_host: str
    ssh_timeout_sec: int = 10
    # host-specific config は __post_init__ 後に signed config loader から注入される
    # (CLI で env override 不可、operator が事前配備)

@dataclass(frozen=True)
class RemoteStatusResult:
    reason_code: ReasonCode
    host: str
    services_up: tuple[str, ...]
    services_down: tuple[str, ...]
    raw_stdout_size_bytes: int  # actual size (sample 用、raw stdout は audit logged only)
    split_brain_safe: bool


def query_remote_compose_status(opts: RemoteStatusOptions) -> RemoteStatusResult:
    # 1. allowlist + signed config load
    config_loader_result = load_remote_hosts_signed_config()
    if config_loader_result.reason_code != "config_ok":
        return RemoteStatusResult(reason_code="remote_status_invalid_host", host=opts.remote_host, ...)
    if opts.remote_host not in config_loader_result.hosts:
        return RemoteStatusResult(reason_code="remote_status_invalid_host", ...)
    host_config: RemoteHostConfig = config_loader_result.hosts[opts.remote_host]

    # 2. ssh exec via taskhub_subprocess_runner (R2 F-001 adopt: 既存 API に合わせる)
    argv = _build_ssh_argv(opts.remote_host, host_config.compose_project, host_config.compose_file, opts.ssh_timeout_sec)
    try:
        result = run_safe_subprocess(
            argv,
            config=SafeSubprocessConfig(timeout_sec=opts.ssh_timeout_sec + 5),  # network + buffer
        )
    except SubprocessTimeoutError:
        return RemoteStatusResult(reason_code="remote_status_ssh_timeout", ...)
    except SubprocessNotFoundError:
        return RemoteStatusResult(reason_code="remote_status_ssh_failed", ...)

    # R2 F-001 adopt: stdout 64 KiB 上限は post-read check (subprocess_runner は自前 cap せず full bytes を返す)
    if len(result.stdout) > 64 * 1024:
        return RemoteStatusResult(reason_code="remote_status_stdout_oversize", host=opts.remote_host,
            services_up=(), services_down=(), raw_stdout_size_bytes=len(result.stdout),
            split_brain_safe=False)

    # 3. exit code 解釈 (R1 F-016 adopt)
    # 既存 SubprocessResult は stderr_sanitized: str (redacted)、bytes-level access は stderr_sanitized で str match
    stderr_text = result.stderr_sanitized
    if result.returncode == 255:
        if "Host key verification failed" in stderr_text or "REMOTE HOST IDENTIFICATION HAS CHANGED" in stderr_text:
            return RemoteStatusResult(reason_code="remote_status_ssh_host_key_untrusted", ...)
        if "Permission denied" in stderr_text or "publickey" in stderr_text:
            return RemoteStatusResult(reason_code="remote_status_ssh_auth_failed", ...)
        return RemoteStatusResult(reason_code="remote_status_ssh_failed", ...)
    if result.returncode == 127:
        return RemoteStatusResult(reason_code="remote_status_compose_unavailable", ...)
    if result.returncode != 0:
        return RemoteStatusResult(reason_code="remote_status_ssh_failed", ...)

    # 4. docker compose ps --format json output parse
    try:
        # docker compose ps --format json は JSONL (NDJSON) or JSON array、both 対応
        services_data = _parse_compose_ps_json(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return RemoteStatusResult(reason_code="remote_status_compose_output_malformed", ...)

    # 5. expected_services と突き合わせ (R1 F-006 adopt: empty = remote identity unverified)
    if not services_data:
        return RemoteStatusResult(reason_code="remote_status_remote_identity_unverified", ...)

    actual_services = {s.get("Service") or s.get("Name") for s in services_data}
    actual_services.discard(None)  # docker compose ps schema 違反 fallback
    expected_set = set(host_config.expected_services)

    # R2 F-003 adopt: identity verify は exact set 一致を要求 (partial overlap で safe 判定不可)
    if actual_services != expected_set:
        return RemoteStatusResult(reason_code="remote_status_remote_identity_unverified",
            host=opts.remote_host,
            services_up=(), services_down=tuple(sorted(expected_set)),
            raw_stdout_size_bytes=len(result.stdout),
            split_brain_safe=False)

    # ADV R1 F-003 adopt: docker compose state は running / exited / paused / restarting / created /
    # dead / removing 等 multi-state。safe-down は **exited / dead のみ** terminal stopped、それ以外は
    # transitional として fail-closed (partial_up or state_unknown).
    SAFE_DOWN_STATES = frozenset({"exited", "dead"})
    RUNNING_STATE = "running"
    KNOWN_TRANSITIONAL_STATES = frozenset({"paused", "restarting", "created", "removing"})

    services_by_state: dict[str, set[str]] = {"running": set(), "safe_down": set(), "transitional": set(), "unknown": set()}
    for s in services_data:
        name = s.get("Service") or s.get("Name")
        state = s.get("State", "").lower()
        if state == RUNNING_STATE:
            services_by_state["running"].add(name)
        elif state in SAFE_DOWN_STATES:
            services_by_state["safe_down"].add(name)
        elif state in KNOWN_TRANSITIONAL_STATES:
            services_by_state["transitional"].add(name)
        else:
            services_by_state["unknown"].add(name)

    running_services = tuple(sorted(services_by_state["running"]))
    safe_down_services = tuple(sorted(services_by_state["safe_down"]))

    # transitional / unknown が混在する場合は state_unknown で fail-closed (ADV R1 F-003 adopt)
    if services_by_state["transitional"] or services_by_state["unknown"]:
        return RemoteStatusResult(
            reason_code="remote_status_state_unknown",
            host=opts.remote_host,
            services_up=running_services, services_down=safe_down_services,
            raw_stdout_size_bytes=len(result.stdout),
            split_brain_safe=False,
        )

    if not running_services and len(safe_down_services) == len(expected_set):
        # ADV R1 F-003 adopt: 全 service が exited/dead で確定して down のみ split_brain_safe=True
        return RemoteStatusResult(
            reason_code="remote_status_ok_down",
            services_up=running_services, services_down=safe_down_services,
            raw_stdout_size_bytes=len(result.stdout),
            split_brain_safe=True,
        )
    if len(running_services) == len(expected_set):
        return RemoteStatusResult(reason_code="remote_status_all_up", split_brain_safe=False,
            host=opts.remote_host, services_up=running_services, services_down=(),
            raw_stdout_size_bytes=len(result.stdout))
    return RemoteStatusResult(reason_code="remote_status_partial_up", split_brain_safe=False,
        host=opts.remote_host, services_up=running_services, services_down=safe_down_services,
        raw_stdout_size_bytes=len(result.stdout))
```

#### 3.B.5 CLI 変更 (`scripts/taskhub_admin.py`)

`_cmd_status` の `--remote` 分岐を skeleton → real I/O:

```python
def _cmd_status(args: argparse.Namespace) -> int:
    if args.remote:
        from scripts.taskhub_remote_status import (
            RemoteStatusOptions,
            query_remote_compose_status,
        )
        opts = RemoteStatusOptions(
            remote_host=args.remote,
            ssh_timeout_sec=int(os.environ.get("TASKHUB_REMOTE_SSH_TIMEOUT_SEC", "10")),
            # compose project / file / services は signed config から取得 (env 不可)
        )
        try:
            result = query_remote_compose_status(opts)
        except Exception as exc:
            print(f"ERROR: remote status query failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({
            "remote_host": opts.remote_host,
            "reason_code": result.reason_code,
            "services_up": list(result.services_up),
            "services_down": list(result.services_down),
            "split_brain_safe": result.split_brain_safe,
        }, sort_keys=True))
        return 0 if result.split_brain_safe else 1

    # 既存 skeleton path (--age-safety / --mac-preflight) ...
```

#### 3.B.6 test fixtures (`tests/scripts/test_taskhub_remote_status.py`)

| # | test name | scope |
|---|---|---|
| 1 | `test_load_remote_hosts_config_ok` | signed config 正常 load + signature OK |
| 2 | `test_load_remote_hosts_config_signature_invalid` | signature 改ざんで reject |
| 3 | `test_load_remote_hosts_config_chmod_world_readable_rejected` | config file mode 0o644 で reject (0o600 必須) |
| 4 | `test_validate_remote_host_unknown_rejected` | config に存在しない host で reason_code=invalid_host |
| 5 | `test_build_ssh_argv_project_pattern_invalid_raises` | compose_project に `; rm -rf /` 等で ValueError raise (defense-in-depth、本来 signed config が gating するが二重防御) |
| 6 | `test_build_ssh_argv_compose_file_nul_byte_rejected` | compose_file に \x00 で ValueError raise |
| 7 | `test_build_ssh_argv_compose_file_newline_rejected` | compose_file に newline で ValueError raise |
| 8 | `test_build_ssh_argv_strict_options_present` | ssh argv に StrictHostKeyChecking=yes / BatchMode=yes / ConnectTimeout 等 expected option exact match |
| 9 | `test_query_ssh_timeout_reason_code` | mock subprocess timeout で reason_code=ssh_timeout |
| 10 | `test_query_ssh_host_key_untrusted_reason_code` (R1 F-016) | exit 255 + stderr "Host key verification failed" で reason_code=ssh_host_key_untrusted |
| 11 | `test_query_ssh_auth_failed_reason_code` | exit 255 + stderr "Permission denied" で auth_failed |
| 12 | `test_query_all_services_down_split_brain_safe` | 全 service exited で services_up=() + split_brain_safe=True |
| 13 | `test_query_partial_up_split_brain_unsafe` | api running + worker exited で partial_up + False |
| 14 | `test_query_all_up_split_brain_unsafe` | 全 service running で all_up + False |
| 15 | `test_query_compose_unavailable_returns_reason_code` | exit 127 で compose_unavailable |
| 16 | `test_query_remote_identity_unverified_empty_json` (R1 F-006) | docker compose ps が empty JSON で reason_code=remote_identity_unverified |
| 17 | `test_query_remote_identity_unverified_wrong_services` (R1 F-006) | expected_services と 1 件も一致しない service set で reason_code=remote_identity_unverified |
| 17a | `test_query_remote_identity_unverified_partial_overlap` (R2 F-003) | expected={api, worker, postgres, redis, frontend} で actual={api, postgres} (subset 部分一致) → identity_unverified (exact set 不一致は safe ではない) |
| 17b | `test_query_remote_identity_unverified_extra_unexpected_service` (R2 F-003) | expected={api, worker, postgres, redis, frontend} に加え actual に `foo_service` が混入 → identity_unverified |
| 17c | `test_query_compose_ps_schema_name_field_alternate` (R2 F-003) | docker compose ps schema が `Service` ではなく `Name` field 使用時の handling |
| 17d | `test_query_state_unknown_restarting_partial` (ADV R1 F-003) | docker compose ps で 1 service が `restarting` state → reason_code=state_unknown + split_brain_safe=False |
| 17e | `test_query_state_unknown_paused_partial` (ADV R1 F-003) | `paused` state 含む → state_unknown |
| 17f | `test_query_state_unknown_unknown_state` (ADV R1 F-003) | docker version 差異で未知 state (e.g., `migrating`) → state_unknown |
| 17g | `test_query_safe_down_only_exited_and_dead_split_brain_safe` (ADV R1 F-003) | 全 service が `exited` or `dead` のみ → split_brain_safe=True (それ以外は不可) |
| 17h | `test_load_config_missing_returns_reason_code` (ADV R1 F-014) | signed config file 不在 → reason_code=config_missing |
| 17i | `test_load_config_permission_unsafe_returns_reason_code` (ADV R1 F-014) | mode 0o644 → config_permission_unsafe |
| 17j | `test_load_config_signature_invalid_returns_reason_code` (ADV R1 F-014) | signature 改ざんで config_signature_invalid (分離 reason_code) |
| 17k | `test_load_config_expired_returns_reason_code` (ADV R1 F-011) | expires_at < now() で config_expired |
| 17l | `test_load_config_unsupported_version_rejected` (ADV R1 F-011) | config_version=2 で unsupported_version reject |
| 17m | `test_query_remote_compose_file_sha256_mismatch_rejected` (ADV R1 F-009) | remote の compose_file sha256 が config と不一致で remote_identity_unverified |
| 17n | `test_build_ssh_argv_unicode_rtl_override_rejected` (ADV R1 F-013) | compose_file に U+202E (RTL override) で raise ValueError |
| 17o | `test_build_ssh_argv_unicode_control_char_rejected` (ADV R1 F-013) | compose_file に U+0007 (BEL) / U+200B (zero-width space) で raise ValueError |
| 18 | `test_query_stdout_oversize_rejected` | mock stdout > 64 KiB で reason_code=stdout_oversize |
| 19 | `test_query_compose_output_malformed_rejected` | output が JSON 不正で compose_output_malformed |
| 20 | `test_query_ssh_argv_no_shell_metacharacters_remote_command` | 構築された argv の remote command 部分に shell metacharacter (unescaped) が混入していない |
| 21 | `test_cli_status_remote_success_returns_exit_0` | split_brain_safe=True で CLI exit 0 + JSON summary |
| 22 | `test_cli_status_remote_unsafe_returns_exit_1` | split_brain_safe=False で CLI exit 1 |

### Batch C: `taskhub approval issue` real I/O CLI subcommand

#### 3.C.1 新規 file `scripts/taskhub_approval_cli.py`

```python
"""SP022-T08 batch 4: `taskhub approval issue` Ed25519-signed approval record generation.

operator が CLI で approval record を発行、Ed25519 sign + claim 付与 + raw 32-byte seed
private key (`bytearray` buffer 経由) で sign + 即時 overwrite zeroize.

Security invariants:
- private key path は ~/.taskhub/keys/approval-signing-key (0o600 必須、symlink reject、
  parent dir 0o700 必須)、format = raw 32-byte seed file (PEM/DER 不採用、R1 F-008 adopt)
- approval_id pattern は既存 sa.APPROVAL_ID_REGEX `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` (R1 F-017 adopt)
- reason_summary pattern は既存 sa.REASON_SUMMARY_REGEX `^[A-Za-z0-9_-]{1,64}$` (R1 F-017 adopt)
- drill_kind choices は既存 sa.DRILL_KIND_ALLOWED_SUBCOMMANDS dict keys (8 entries) から派生
  (R1 F-011 adopt)
- canonical payload は既存 sa._rfc8785_canonical_payload_bytes() を再利用 (operator-supplied
  fingerprint を bypass しない、R1 F-001 / server-owned boundary 遵守)
- output file は .signed atomic rename (.tmp → final、partial file 防止)
- **chmod 0o600** (ADV R1 F-004 adopt: claim 内 DSN components / paths は機密、world-readable 禁止)
- **tmp file は `os.open(O_CREAT|O_EXCL|O_NOFOLLOW, 0o600)`** (ADV R1 F-005 adopt: race / symlink attack 防御、predictable path への先回り create 防御)
- stderr / stdout に raw private key bytes / signature_bytes (raw) を一切出さない
- TTL max は sa.DEFAULT_MAX_TTL=48h (R1 F-009 adopt)、default 24h
"""

from datetime import UTC, datetime, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import argparse, base64, json, os, re, stat, sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# import shared types from existing module
from scripts.taskhub_signed_approval import (
    APPROVAL_ID_REGEX,
    REASON_SUMMARY_REGEX,
    DEFAULT_MAX_TTL,
    ApprovalRecord,
    BackupApprovalClaim,
    RestoreApprovalClaim,
    RestoreRollbackApprovalClaim,
    DESTRUCTIVE_SUBCOMMANDS,
    DRILL_KIND_ALLOWED_SUBCOMMANDS,
    _rfc8785_canonical_payload_bytes,
)


ReasonCode = Literal[
    # success
    "approval_issue_ok",
    # signing key
    "approval_issue_signing_key_missing",
    "approval_issue_signing_key_permission",
    "approval_issue_signing_key_symlink",
    "approval_issue_signing_key_dir_permission",
    "approval_issue_signing_key_invalid_format",
    # approval_id / collision
    "approval_issue_approval_id_collision",
    "approval_issue_approval_id_malformed",
    # schema
    "approval_issue_reason_summary_malformed",
    "approval_issue_drill_kind_subcommand_mismatch",
    "approval_issue_target_host_required",
    # claim
    "approval_issue_backup_claim_required",
    "approval_issue_backup_claim_field_missing",
    "approval_issue_restore_claim_required",
    "approval_issue_restore_claim_field_missing",
    "approval_issue_restore_rollback_claim_required",
    "approval_issue_restore_rollback_claim_field_missing",
    # TTL
    "approval_issue_signed_at_expires_inversion",
    "approval_issue_ttl_exceeded",
    # output
    "approval_issue_output_path_collision",
    "approval_issue_output_path_invalid",
]
```

reason_code count: **22 種** (R1 F-014 adopt: exact count、success 1 + signing key 5 + id 2 + schema 3 + claim 6 + TTL 2 + output 2 + non-success 21 + success 1 = 22)

#### 3.C.2 restore_claim 12 field 完全 1:1 mapping (R1 F-010 adopt)

argparse args ↔ `RestoreApprovalClaim` dataclass field の完全 mapping:

| # | dataclass field (type) | CLI arg | required iff | normalizer | canonical JSON key |
|---|---|---|---|---|---|
| 1 | `input_path: str` | `--restore-input-path` | "restore" in allowed_subcommands | absolute path string, normpath | `input_path` |
| 2 | `archive_sha256: str` | `--restore-archive-sha256` | "restore" in subcommands | 64-char lowercase hex | `archive_sha256` |
| 3 | `age_public_key_fingerprint: str` | `--restore-age-public-key-fingerprint` | 同上 | 64-char lowercase hex | `age_public_key_fingerprint` |
| 4 | `target_pg_dsn_components: dict[str, str]` | `--restore-target-pg-host`, `-pg-port`, `-pg-db`, `-pg-user` | 同上 | dict({host, port, db, user}) | `target_pg_dsn_components` (sorted) |
| 5 | `target_redis_endpoint: str` | `--restore-target-redis-endpoint` (or `--restore-target-redis-host` + `-port`) | 同上 | `<host>:<port>` literal | `target_redis_endpoint` |
| 6 | `target_artifacts_dir: str` | `--restore-target-artifacts-dir` | 同上 | absolute normpath | `target_artifacts_dir` |
| 7 | `target_artifacts_container_path: str` | `--restore-target-artifacts-container-path` | 同上 | absolute path (Linux container) | `target_artifacts_container_path` |
| 8 | `target_compose_project_name: str` | `--restore-target-compose-project` | 同上 | docker compose project regex | `target_compose_project_name` |
| 9 | `target_compose_file_path: str` | `--restore-target-compose-file` | 同上 | absolute normpath | `target_compose_file_path` |
| 10 | `expected_postgres_major_version: str` | `--restore-expected-pg-major` | 同上 | digit string | `expected_postgres_major_version` |
| 11 | `expected_alembic_head: str` | `--restore-expected-alembic-head` | 同上 | alembic revision id (non-empty) | `expected_alembic_head` |
| 12 | `skip_service_stop: bool` | `--restore-skip-service-stop` (action="store_true") | 同上 | False 強制 (CLI deny) or claim 値 | `skip_service_stop` |

各 field の missing → `approval_issue_restore_claim_field_missing` (extras に missing field name)、type/format mismatch → 適切な reason_code。`skip_service_stop=True` を CLI で渡すと **物理 deny** (本 PR scope ではない、Phase 5 carry-over)。

`RestoreRollbackApprovalClaim` 10 field も同様の 1:1 mapping (R1 F-010 同等):

| # | dataclass field | CLI arg | required iff | canonical JSON key |
|---|---|---|---|---|
| 1 | `pre_restore_ts` | `--rollback-pre-restore-ts` | "restore-rollback" in subcommands | `pre_restore_ts` |
| 2 | `pre_restore_dir` | `--rollback-pre-restore-dir` | 同上 | `pre_restore_dir` |
| 3 | `snapshot_manifest_sha256` | `--rollback-snapshot-manifest-sha256` | 同上 | `snapshot_manifest_sha256` |
| 4 | `target_pg_dsn_components` | `--rollback-target-pg-host`, etc. | 同上 | (sorted dict) |
| 5-10 | ... 同上 (Batch A §3.A.0 表参照) | ... | ... | ... |

#### 3.C.3 admin CLI subparser 追加 (`scripts/taskhub_admin.py`)

```python
sub_approval = subparsers.add_parser(
    "approval", help="approval record management (issue / list / verify)",
)
approval_sub = sub_approval.add_subparsers(dest="approval_subcommand", required=True)

issue_parser = approval_sub.add_parser("issue", help="issue Ed25519-signed approval record")
issue_parser.add_argument("--approval-id", required=True)
issue_parser.add_argument("--decider", required=True)
issue_parser.add_argument("--reason-summary", required=True)

# R1 F-011 adopt: 既存 dict から choices 派生 (typo `age_rotation` 不可、`age_rotate` のみ allow)
issue_parser.add_argument("--drill-kind", required=True,
    choices=sorted(DRILL_KIND_ALLOWED_SUBCOMMANDS.keys()))

# R1 F-011 adopt: allowed_subcommands も existing DESTRUCTIVE_SUBCOMMANDS から
issue_parser.add_argument("--allowed-subcommands", required=True, nargs="+",
    choices=sorted(DESTRUCTIVE_SUBCOMMANDS))

issue_parser.add_argument("--target-host", default=None)

# R1 F-009 adopt: default 24h, max は DEFAULT_MAX_TTL.total_seconds()/3600 = 48h
issue_parser.add_argument("--ttl-hours", type=int, default=24)

# backup_claim fields (5 個、ADV R1 F-007 adopt: 既存 BackupApprovalClaim 完全一致、archive_sha256 含めない)
# 既存 BackupApprovalClaim = {output_path, include_sops_env, skip_service_stop, overwrite, age_public_key_fingerprint}
issue_parser.add_argument("--backup-output-path", default=None)
issue_parser.add_argument("--backup-age-public-key-fingerprint", default=None)
issue_parser.add_argument("--backup-include-sops-env", action="store_true")
issue_parser.add_argument("--backup-skip-service-stop", action="store_true")
issue_parser.add_argument("--backup-overwrite", action="store_true")

# restore_claim fields (12 個、required iff "restore" in subcommands、§3.C.2 表参照)
issue_parser.add_argument("--restore-input-path", default=None)
issue_parser.add_argument("--restore-archive-sha256", default=None)
issue_parser.add_argument("--restore-age-public-key-fingerprint", default=None)
issue_parser.add_argument("--restore-target-pg-host", default=None)
issue_parser.add_argument("--restore-target-pg-port", default=None)
issue_parser.add_argument("--restore-target-pg-db", default=None)
issue_parser.add_argument("--restore-target-pg-user", default=None)
issue_parser.add_argument("--restore-target-redis-endpoint", default=None)
issue_parser.add_argument("--restore-target-artifacts-dir", default=None)
issue_parser.add_argument("--restore-target-artifacts-container-path", default=None)
issue_parser.add_argument("--restore-target-compose-project", default=None)
issue_parser.add_argument("--restore-target-compose-file", default=None)
issue_parser.add_argument("--restore-expected-pg-major", default=None)
issue_parser.add_argument("--restore-expected-alembic-head", default=None)
issue_parser.add_argument("--restore-skip-service-stop", action="store_true")

# restore_rollback_claim fields (10 個、required iff "restore-rollback" in subcommands)
issue_parser.add_argument("--rollback-pre-restore-ts", default=None)
issue_parser.add_argument("--rollback-pre-restore-dir", default=None)
issue_parser.add_argument("--rollback-snapshot-manifest-sha256", default=None)
issue_parser.add_argument("--rollback-target-pg-host", default=None)
# ... 残り 6 field (target_redis_endpoint / artifacts_dir / artifacts_container_path /
#                   compose_project / compose_file / expected_pg_major)

# ADV R2 F-001 adopt: --force 廃止 (collision は manual remove + new approval_id flow)
issue_parser.set_defaults(func=_cmd_approval_issue)
```

#### 3.C.4 zeroize timing (R1 F-019 adopt、明確化)

```python
def issue_approval_record(opts: ApprovalIssueOptions) -> tuple[bool, ReasonCode, Path | None]:
    # ... validation ...

    # private key load (zeroize 用 bytearray)
    seed_buf = bytearray(opts.signing_key_path.read_bytes())
    if len(seed_buf) != 32:
        # raw 32-byte format 不一致 (R1 F-008 adopt: PEM/DER も reject)
        # zeroize before return
        for i in range(len(seed_buf)):
            seed_buf[i] = 0
        return False, "approval_issue_signing_key_invalid_format", None

    try:
        priv = Ed25519PrivateKey.from_private_bytes(bytes(seed_buf))
    finally:
        # bytearray を即時 overwrite (Python immutable bytes ではない、確実に上書き可能)
        for i in range(len(seed_buf)):
            seed_buf[i] = 0
        del seed_buf

    # 注: priv object 内部の memory 上書きは cryptography library lifecycle 依存
    # (Python では確実な zeroize 保証なし、SecretBroker boundary plan の limit を runbook §6 で明記)

    # build record + canonical payload + sign
    record = ApprovalRecord(...)
    payload = _rfc8785_canonical_payload_bytes(record)
    signature_bytes = priv.sign(payload)
    signature_b64 = base64.b64encode(signature_bytes).decode("ascii")

    # signed record write atomic
    record = ApprovalRecord(..., signature_b64=signature_b64)
    record_dict = ...  # build dict same as _rfc8785_canonical_payload_bytes layout

    # ADV R1 F-005 + F-015 + ADV R2 F-001 adopt: final path に直接 O_CREAT|O_EXCL|O_NOFOLLOW
    # で no-replace create (tmp path + rename は POSIX で既存 final を黙って overwrite するため race window あり)
    final_path = output_dir / f"{opts.approval_id}.signed"
    fd = None
    try:
        fd = os.open(
            str(final_path),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
            0o600,  # ADV R1 F-004 adopt: 0o600
        )
        content = json.dumps(record_dict, indent=2, sort_keys=True).encode("utf-8")
        os.write(fd, content)
        os.fsync(fd)
    except FileExistsError:
        # ADV R2 F-001 adopt: --force 廃止、collision は必ず revoke (manual remove) → new approval_id
        return False, "approval_issue_output_path_collision", None
    except OSError as e:
        # cleanup attempt
        try:
            os.unlink(str(final_path))
        except OSError:
            pass
        return False, "approval_issue_output_path_invalid", None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    # parent dir fsync (ADV R1 F-015 adopt)
    try:
        parent_fd = os.open(str(output_dir), os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except OSError:
        pass  # parent fsync failure は warning として扱う、approval は既に flush 済

    return True, "approval_issue_ok", final_path
```

**ADV R2 F-001 adopt: `--force` flag 廃止**。collision は必ず operator が manual remove (runbook §3) + new approval_id で再発行する flow。test #34c で `--force` argparse 不在を確認。

#### 3.C.5 test fixtures (`tests/scripts/test_taskhub_approval_cli.py`)

| # | test name | scope |
|---|---|---|
| 1 | `test_issue_success_writes_signed_file` | 全 field 完備で signed file 生成 + exit 0 |
| 2 | `test_issue_signing_key_missing_returns_exit_2` | private key file 不在で reason_code=signing_key_missing |
| 3 | `test_issue_signing_key_world_readable_returns_exit_2` | chmod 644 のキーで reason_code=signing_key_permission |
| 4 | `test_issue_signing_key_symlink_rejected` | symlink で reason_code=signing_key_symlink |
| 5 | `test_issue_signing_key_dir_world_readable_returns_exit_2` | parent dir chmod 755 で reason_code=signing_key_dir_permission |
| 6 | `test_issue_signing_key_invalid_format_rejected` (R1 F-008) | key file が 32 bytes 以外 (PEM/DER 等) で reason_code=signing_key_invalid_format |
| 7 | `test_issue_approval_id_collision_without_force_rejected` | 既存 file かつ --force なしで exit 2 |
| 8 | `test_issue_approval_id_malformed_rejected` (R1 F-017) | APPROVAL_ID_REGEX 違反で approval_id_malformed |
| 9 | `test_issue_reason_summary_malformed_rejected` (R1 F-017) | REASON_SUMMARY_REGEX 違反 (空白 `>` 等含む) で reason_summary_malformed |
| 10 | `test_issue_drill_kind_age_rotate_typo_rejected` (R1 F-011) | `--drill-kind age_rotation` (typo) で argparse choices reject |
| 11 | `test_issue_drill_kind_subcommand_mismatch_rejected` | drill_kind=age_rotate + allowed_subcommands=[restore] で mismatch |
| 12 | `test_issue_backup_claim_required_when_backup_in_subcommands` | allowed_subcommands=[backup] かつ --backup-* なしで reason_code=backup_claim_required |
| 13 | `test_issue_restore_claim_all_12_field_missing_rejected` (R1 F-010) | restore in subcommands で 12 field のいずれか missing で field_missing reason_code |
| 14 | `test_issue_restore_rollback_claim_required_when_in_subcommands` (R1 F-001) | restore-rollback in subcommands で claim missing で reason_code=restore_rollback_claim_required |
| 15 | `test_issue_restore_rollback_claim_all_10_field_missing_rejected` (R1 F-001) | RestoreRollbackApprovalClaim 10 field 順次 missing 確認 |
| 16 | `test_issue_signed_at_after_expires_at_rejected` | signed_at > expires_at で signed_at_expires_inversion |
| 17 | `test_issue_ttl_default_24h_passes` (R1 F-009) | --ttl-hours 24 で issue OK |
| 18 | `test_issue_ttl_max_48h_passes` (R1 F-009) | --ttl-hours 48 で issue OK (DEFAULT_MAX_TTL 境界) |
| 19 | `test_issue_ttl_exceeds_48h_rejected` (R1 F-009) | --ttl-hours 49 で reason_code=ttl_exceeded |
| 20 | `test_issue_canonical_payload_matches_signing_root` | 発行された file を verify_signed_approval で読み戻し、signature OK |
| 21 | `test_issue_canonical_payload_includes_backup_claim` | backup_claim 付き record の signature が backup_claim を含む payload で検証可能 |
| 22 | `test_issue_canonical_payload_includes_restore_claim` | restore_claim 付き record も同上 |
| 23 | `test_issue_canonical_payload_includes_restore_rollback_claim` (R1 F-001) | restore_rollback_claim 付き record も同上 |
| 24 | `test_issue_canonical_payload_backup_claim_tamper_rejected` (R1 F-015) | issue 後 file の backup_claim.output_path を書き換え → verify_signed_approval reject (signature_invalid) |
| 25 | `test_issue_canonical_payload_restore_claim_archive_tampered_rejected` (R1 F-015) | issue 後 restore_claim.archive_sha256 書き換えで signature_invalid |
| 26 | `test_issue_canonical_payload_restore_rollback_claim_pre_ts_tampered_rejected` (R1 F-015) | issue 後 rrc.pre_restore_ts 書き換えで signature_invalid |
| 27 | `test_issue_canonical_payload_allowed_subcommands_tampered_rejected` (R1 F-015) | allowed_subcommands 書き換えで signature_invalid |
| 28 | `test_issue_canonical_payload_target_host_tampered_rejected` (R1 F-015) | target_host 書き換えで signature_invalid |
| 29 | `test_issue_atomic_rename_on_failure_leaves_no_partial` | 書込中 OSError mock で .tmp file が残らない |
| 30 | `test_issue_no_raw_private_key_in_stderr` (R1 F-019) | stderr / stdout / log / generated artifact に private key bytes / signature raw を出さない |
| 31 | `test_issue_zeroize_bytearray_overwritten` (R1 F-019) | seed_buf.__class__ == bytearray + load 後 全 byte 0x00 確認 (white-box test) |
| 32 | `test_issue_output_chmod_0644` | 生成 file の mode が 0o644 |
| 33 | `test_issue_output_path_traversal_rejected` | --approval-id に `..` 含む値で reject |
| 34a | `test_issue_output_chmod_0o600` (ADV R1 F-004) | 生成 .signed file が 0o600 (旧 0o644 期待を上書き) |
| 34b | `test_issue_atomic_open_o_excl_o_nofollow` (ADV R1 F-005) | tmp file が O_CREAT|O_EXCL|O_NOFOLLOW で create、symlink 先 create attempt は OSError |
| 34c | `test_issue_atomic_collision_returns_reason_code` (ADV R1 F-005) | tmp file 既存で reason_code=output_path_collision |
| 34d | `test_issue_no_backup_archive_sha256_arg` (ADV R1 F-007) | argparse choices に --backup-archive-sha256 が **存在しない**ことを confirm (CLI -h 出力 grep) |
| 34e | `test_issue_canonical_payload_remote_hosts_canonical_helper_shared` (ADV R1 F-012) | canonical_for_signature("remote_hosts.v1", ...) と canonical_for_signature("approval_record.v1", ...) が domain prefix で分離 |

### Batch D: docs/deploy/operator-runbook.md 更新 (re-sign migration SOP)

#### 3.D.1 `docs/deploy/operator-runbook.md` (新規)

```markdown
# Operator Runbook (host migration / drill)

## §1 approval signing key bootstrap (R1 F-008 + ADV R1 F-006 / F-018 adopt: 中間 PEM file 不要)

**ADV R1 F-006 adopt**: `/tmp/ed25519_pem` を経由する旧手順は **page cache / FS journal に残存** する risk があるため撤回。Python cryptography で raw 32-byte seed を **直接 final path に 0o600 で作成**。

**ADV R1 F-018 adopt**: hard-coded `/Users/tohga/` path は廃止、`$HOME` 経由で operator-portable に。

```bash
# 1. directory 準備 (parent 0o700)
TASKHUB_HOME="${TASKHUB_HOME:-$HOME/.taskhub}"
mkdir -p "$TASKHUB_HOME/keys" && chmod 0700 "$TASKHUB_HOME/keys"

# 2. raw 32-byte seed 生成 (Python cryptography 直接出力、中間 PEM file なし)
umask 077  # safety net for python -c file writes
python3 - <<EOF
import os, stat
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

# O_CREAT|O_EXCL|O_NOFOLLOW で race / symlink 排除 + atomic create
key_path = os.path.expandvars("$TASKHUB_HOME/keys/approval-signing-key")
fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
try:
    os.write(fd, seed)
    os.fsync(fd)
finally:
    os.close(fd)

pub_path = os.path.expandvars("$TASKHUB_HOME/keys/approval-verify-key.pub")
fd = os.open(pub_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
try:
    os.write(fd, pub_bytes)
    os.fsync(fd)
finally:
    os.close(fd)

# zeroize seed in this process (best-effort)
del seed
EOF

# 3. fingerprint allowlist 登録
PUB_FP=$(python3 -c "
import hashlib, os
with open(os.path.expandvars('$TASKHUB_HOME/keys/approval-verify-key.pub'), 'rb') as f:
    print(hashlib.sha256(f.read()).hexdigest())
")
echo "$PUB_FP" >> "$TASKHUB_HOME/keys/approval-verify-key-allowlist.txt"
chmod 0600 "$TASKHUB_HOME/keys/approval-verify-key-allowlist.txt"

# 4. target host へ public key + allowlist + signing key (operator host のみ保管、target host 不要) を secret manager 経由運搬
# target host には verify-key.pub + verify-key-allowlist.txt のみ配布
# 旧版に書いた `openssl genpkey ... -outform PEM` + tmp file 経由は撤回 (page cache / FS journal 残存リスク)
```

## §2 approval issue 手順 (R1 F-017 + ADV R1 F-001 / F-007 / F-008 adopt: per-subcommand 分離)

**ADV R1 F-008 adopt**: 1 approval = 1 destructive subcommand (1 つの drill 全体で 4 つの approval を順次発行する)。本 PR では `multi-subcommand approval` は廃止、後続 SP-022 batch で per-subcommand claim dataclass 拡張 (migrate / freeze / thaw 用) を整備。

### §2.1 backup approval issue (drill 開始時 1 件目)

backup は output file が存在しない状態で issue するため、`output_path` (operator host 上の絶対 path) + age public key fingerprint のみ binding。`archive_sha256` は既存 BackupApprovalClaim には含めない (ADV R1 F-007 adopt、PR #77 invariant 維持)。

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

### §2.2 restore approval issue (drill 中、backup archive 完成後)

backup 完了後、operator が `sha256sum backup.tar.age` で archive_sha256 を計算してから issue:

```bash
taskhub approval issue \
  --approval-id drill-2026-07-01-restore-bcd2 \
  --decider t-ohga \
  --reason-summary "half-yearly-drill_mac-vps_restore" \
  --drill-kind host_migration_mac_vps \
  --allowed-subcommands restore \
  --target-host t-ohga-vps \
  --ttl-hours 24 \
  --restore-input-path "$HOME/.taskhub/backups/drill-2026-07-01.tar.age" \
  --restore-archive-sha256 <sha256sum of above> \
  --restore-age-public-key-fingerprint <same fingerprint> \
  ...
```

### §2.3 restore-rollback approval issue (restore 失敗後、snapshot 存在 confirm 後)

**ADV R1 F-001 adopt: restore-rollback は upfront approval 不可、必ず post-snapshot で issue**。restore が失敗してから rollback approval を作る:

1. restore 失敗 → snapshot dir `$DATA_DIR/_pre-restore-<ts>/` 存在 confirm
2. operator が manifest_sha256 計算: `sha256sum $DATA_DIR/_pre-restore-<ts>/snapshot_manifest.json`
3. approval issue:

```bash
taskhub approval issue \
  --approval-id drill-2026-07-01-rollback-cde3 \
  --decider t-ohga \
  --reason-summary "half-yearly-drill_mac-vps_rollback" \
  --drill-kind host_migration_mac_vps \
  --allowed-subcommands restore-rollback \
  --target-host t-ohga-vps \
  --ttl-hours 24 \
  --rollback-pre-restore-ts <ts> \
  --rollback-pre-restore-dir "$DATA_DIR/_pre-restore-<ts>" \
  --rollback-snapshot-manifest-sha256 <computed> \
  ...
```

注: reason_summary は `[A-Za-z0-9_-]{1,64}` のみ許可、空白 / `>` / `<` / `(` / `)` は使えない。`$HOME` / `$DATA_DIR` は shell variable として展開され、approval issue 内で **resolve 後の絶対 path が canonical payload に入る**。CLI が path normalization (Path(...).resolve()) を実施。

## §3 approval revocation (manual)

approval record の revoke は CLI 提供しない (本 PR 範囲外、R1 F-018 adopt)。手順:
1. `~/.taskhub/approvals/<approval-id>.signed` を remove
2. 必要であれば operator log に「revoked: <id> reason: <reason>」を append
3. 新規 approval id (別 8 hex suffix) で再発行

`scripts/taskhub_approval_cli.py` には `issue_revoke_record()` stub を **置かない** (public surface に出さない、import 利用で誤動作する経路を最小化)。

## §4 PR #78 後の既存 approval record re-sign migration

PR #78 (SP022-T02 Phase 3 + R2-F-001 retro-fix) で
`_rfc8785_canonical_payload_bytes` が `backup_claim` / `restore_claim` を
sub-record として含めるよう拡張された。**本 PR (Phase 4) で `restore_rollback_claim` も追加**。

**PR #75/#77/#78 期間中に発行された approval record (~/.taskhub/approvals/*.signed) は signature_invalid 化**:
- PR #75 期間: backup_claim/restore_claim 不在の record
- PR #77 期間: backup_claim あり、restore_claim 不在の record
- PR #78 期間: backup_claim + restore_claim あり、restore_rollback_claim 不在の record

operator は migration 着手前に:
1. `~/.taskhub/approvals/` 内の全 .signed を `~/.taskhub/approvals/_archived-pre-pr<N>/` に移動 (PR# は適切に書き換え)
2. drill 着手時に `taskhub approval issue` で **新規 approval を必須発行**
3. archive 内 record は audit 目的でのみ保持 (verify で必ず signature_invalid)

## §5 remote_hosts.signed.json bootstrap (R1 F-006/F-007 + ADV R1 F-009/F-011/F-012 + ADV R2 F-003 adopt)

`taskhub status --remote <host>` は `~/.taskhub/remote_hosts.signed.json` を読む。operator が事前配備、**loader schema と完全一致** (ADV R2 F-003 adopt: 手書き json.dumps ではなく repo helper 経由):

```bash
TASKHUB_HOME="${TASKHUB_HOME:-$HOME/.taskhub}"
# 0. compose_file の sha256 を各 host で計算
MAC_COMPOSE_FILE="$HOME/repo/TaskManagedAI/docker-compose.yml"
MAC_COMPOSE_SHA256=$(sha256sum "$MAC_COMPOSE_FILE" | cut -d' ' -f1)
# 同様に Linux / VPS host で compose_file の sha256 を取得 (operator が secret-manager 経由 fetch)
LINUX_COMPOSE_SHA256="<取得した hex>"
VPS_COMPOSE_SHA256="<取得した hex>"

# 1. signed config payload (ADV R1 F-009/F-011 adopt: config_version + expires_at + compose_file_sha256)
python3 - <<EOF
import os, json
from scripts.taskhub_signed_approval import canonical_for_signature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import base64

taskhub_home = os.environ.get("TASKHUB_HOME", os.path.expanduser("~/.taskhub"))
key_path = os.path.join(taskhub_home, "keys", "approval-signing-key")

# payload schema = loader schema 完全一致 (ADV R2 F-003 adopt)
payload = {
    "config_version": 1,
    "signed_at": "2026-05-20T10:00:00Z",
    "expires_at": "2026-11-20T10:00:00Z",   # 6 ヶ月期限
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

# ADV R2 F-002 adopt: shared canonicalizer (domain="remote_hosts.v1")
canonical_bytes = canonical_for_signature("remote_hosts.v1", payload)

with open(key_path, "rb") as f:
    priv = Ed25519PrivateKey.from_private_bytes(f.read())
sig = base64.b64encode(priv.sign(canonical_bytes)).decode("ascii")

output = {**payload, "signature": sig}
output_path = os.path.join(taskhub_home, "remote_hosts.signed.json")
# atomic O_CREAT|O_EXCL|O_NOFOLLOW direct create (ADV R1 F-005 同 pattern)
fd = os.open(output_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
try:
    os.write(fd, json.dumps(output, indent=2, sort_keys=True).encode("utf-8"))
    os.fsync(fd)
finally:
    os.close(fd)
EOF
```

**期限切れ再 issue 手順 (ADV R2 F-003 adopt)**:
1. 新 expires_at で payload 再生成
2. `~/.taskhub/remote_hosts.signed.json` を `~/.taskhub/remote_hosts.signed.json.expired-<date>` に rename (archive、削除しない)
3. 新 signed config を上記 Python helper で生成
4. 全 target host へ secret manager 経由 push (secret manager 経由のみ、git/cloud/email/Slack 禁止)
5. 各 host で `taskhub status --remote <host>` で smoke test、`config_expired` reason_code が出なくなることを確認

## §6 SecretBroker boundary 限界 (R1 F-019 adopt)

private key を扱う code path で zeroize 保証:
- raw 32-byte seed は `bytearray` で読み込み、`Ed25519PrivateKey.from_private_bytes()` 後 即時 `for i in range(len): buf[i] = 0` で overwrite
- cryptography library 内部 (Ed25519PrivateKey object) の memory 上書きは **library lifecycle 依存**、Python では確実な zeroize 保証なし
- best-effort: object scope を最小化 (関数内 local 変数のみ、import 跨ぎ不可)、log / stdout / stderr / artifact に key 由来 bytes を一切出さない
- audit event は fingerprint hash (sha256) のみ含める

## §7 Tailscale SSH 接続 bootstrap (R1 F-016 adopt: known_hosts)

`taskhub status --remote <host>` は `StrictHostKeyChecking=yes` で起動する。known_hosts に host entry がない場合は `remote_status_ssh_host_key_untrusted` で fail-closed。初回 bootstrap:

```bash
# 1. Tailscale で target host が到達可能か確認
tailscale ping t-ohga-vps

# 2. 1 回 manual ssh で host key を fetch (この時だけ accept new)
ssh -o StrictHostKeyChecking=accept-new t-ohga-vps echo OK

# 3. ~/.ssh/known_hosts に entry 追加されたことを verify
grep "t-ohga-vps" ~/.ssh/known_hosts

# 4. 以後は StrictHostKeyChecking=yes で動作
taskhub status --remote t-ohga-vps  # OK
```

host key fingerprint mismatch (`@@@@@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!`) の場合は別途 incident response (operator が `ssh-keygen -R <host>` で除去 → 再 bootstrap)。
```

#### 3.D.2 `docs/sprints/SP-022_framework_intake_hardening.md` 更新

§Phase 4 completion section 追加 (PR #78 後の carry-over 7 件のうち 4 件を本 PR で closure、§1.1 trace 反映)、`SP022-T02 Phase 5` 起票 (backup pg_dump compose exec 切替) を明記。

---

## §4 invariant chain (must_ship 完全列)

### 4.1 ADR-00021 invariants 遵守

- §11.2 split-brain default deny: `--remote` が split_brain_safe=True を返さない限り migrate / restore は人間判断で先に進む (auto skip しない、operator が `--remote` 結果を見て manual decide)
- §14.1 PGA-F-013 drill timer alert-only: `taskhub restore --rollback` も signed approval 必須 (本 PR で gate + `RestoreRollbackApprovalClaim` binding)
- §14.1 PGA-F-002 detached signature: 本 PR は detached signature の **operator-side workflow を提供** (approval issue CLI)、source_host_id allowlist は SP-012 carry-over

### 4.2 SecretBroker boundary 遵守 (R1 F-019 明確化)

- Ed25519 private key は disk 上 0o600 + raw 32-byte seed format
- 読込は `bytearray` buffer + load 後 即時 overwrite (best-effort zeroize)
- cryptography object 内部 memory は library lifecycle 依存、plan 上の limit を runbook §6 で明記
- audit / log / artifact / stderr に raw private key を含めない (test #30 + #31)
- `secret_ref` 形式 URI は本 batch では使用しない (P0 では offline ledger 直接管理、SecretBroker DB integration は P1 carry-over)

### 4.3 server-owned boundary 遵守

- approval issue CLI で operator が claim 値を CLI 引数指定するが、CLI 内部で BackupApprovalClaim / RestoreApprovalClaim / RestoreRollbackApprovalClaim dataclass strict 型 + JCS canonical 経路を強制
- canonical payload は既存 `_rfc8785_canonical_payload_bytes()` を再利用、CLI 独自 payload 生成は禁止
- verify side (require_approval_for_destructive) は同 canonical payload を独立に再計算

### 4.4 cross-source enum integrity 遵守 (R1 F-014 adopt: exact count)

ReasonCode 拡張 + 既存定数 整合性:

| source | location | count |
|---|---|---|
| approval_issue_* (Literal) | `scripts/taskhub_approval_cli.py` | 22 (success 1 + 失敗 21) |
| remote_status_* (Literal) | `scripts/taskhub_remote_status.py` | 12 (R1 F-016 で +1 = ssh_host_key_untrusted、R1 F-006 で +1 = remote_identity_unverified) |
| signed_approval ReasonCode 既存 + 本 PR 新規 3 (restore_rollback_claim_required / mismatch / allow_unsigned_skeleton_rejected) | `scripts/taskhub_signed_approval.py` | 既存 + 3 |
| restore_orchestrator new ReasonCode (snapshot manifest 系 5 種) | `scripts/taskhub_restore_orchestrator.py` | 既存 + 5 |
| pytest fixture EXPECTED_* constants | tests/scripts/ 各 file | 上記各 count exact match (set equality test) |
| docs reason code table | `docs/deploy/operator-runbook.md` + Sprint Pack | 上記と sync |

frontend TypeScript enum: 本 PR scope で N/A (CLI 専用 reason code、UI 露出なし)。

### 4.5 testing.md §3 弱 assertion 禁止 遵守

全 80 test fixture (Batch A 25 + B 22 + C 33) で:
- exit code は exact match (not truthy)
- stdout/stderr は exact 文字列 + reason_code presence の両方
- file mode / permission は `stat.S_IMODE(...) == 0o600` の exact
- 弱 assertion (`toBeDefined` / `toBeTruthy` 同等) を全件回避

---

## §5 ファイル変更一覧

### 新規 (5 file + 1 docs)

| path | 行数目安 | 内容 |
|---|---|---|
| `scripts/taskhub_remote_status.py` | ~450 | Tailscale SSH 経由 remote compose ps query + signed config loader + reason code 12 種 |
| `scripts/taskhub_approval_cli.py` | ~700 | Ed25519-signed approval issue CLI + reason code 22 種 + restore_rollback_claim 対応 + zeroize |
| `tests/scripts/test_taskhub_remote_status.py` | ~600 | 22 fixture |
| `tests/scripts/test_taskhub_approval_cli.py` | ~900 | 33 fixture |
| `docs/deploy/operator-runbook.md` | ~300 | bootstrap / issue / re-sign migration / remote_hosts config / SecretBroker limit / known_hosts SOP |

### 修正 (6 file)

| path | 影響範囲 | 行数 |
|---|---|---|
| `scripts/taskhub_signed_approval.py` | RestoreRollbackApprovalClaim 新規 + _rfc8785_canonical_payload_bytes 拡張 + verify_signed_approval rrc verify + require_approval_for_destructive rrc deny + ReasonCode 3 種 | +120 |
| `scripts/taskhub_admin.py` | _cmd_restore (--rollback real I/O) + _cmd_status (--remote real I/O) + 新規 _cmd_approval_issue + subparser approval + manifest verify | +280 / -50 |
| `scripts/taskhub_restore_orchestrator.py` | RestoreOptions.for_rollback_mode classmethod + create_pre_restore_snapshot manifest.json 出力 + verify_snapshot_manifest_binding / component_hashes helper + new ReasonCode 5 種 | +200 |
| `tests/scripts/test_taskhub_signed_approval.py` | RestoreRollbackApprovalClaim 関連 fixture 2 (test #24 + #25) + canonical payload tamper 5 fixture | +250 |
| `tests/scripts/test_taskhub_admin.py` | rollback real I/O 関連 13 fixture (Batch A 内 #1-#16 から admin 関連) | +400 |
| `tests/scripts/test_taskhub_restore_orchestrator.py` | rollback_mode + manifest 関連 6 fixture | +250 |
| `docs/sprints/SP-022_framework_intake_hardening.md` | §Phase 4 completion + carry-over 7 件 trace + SP022-T02 Phase 5 起票 | +80 |

合計: +4,530 / -50 (12 file)

---

## §6 verification 順序

### 6.1 local pre-commit verification

```bash
# Python lint + type
uv run ruff check scripts/taskhub_remote_status.py scripts/taskhub_approval_cli.py scripts/taskhub_admin.py scripts/taskhub_restore_orchestrator.py scripts/taskhub_signed_approval.py
uv run mypy scripts/taskhub_remote_status.py scripts/taskhub_approval_cli.py scripts/taskhub_admin.py scripts/taskhub_restore_orchestrator.py scripts/taskhub_signed_approval.py

# 新規 test
uv run pytest tests/scripts/test_taskhub_remote_status.py tests/scripts/test_taskhub_approval_cli.py tests/scripts/test_taskhub_admin.py tests/scripts/test_taskhub_restore_orchestrator.py tests/scripts/test_taskhub_signed_approval.py -x

# regression
uv run pytest tests/scripts/ -x
```

### 6.2 受け入れ条件

- [ ] `uv run pytest tests/scripts/` 250+ test PASS (本 PR 後 ~280 想定)
- [ ] `uv run mypy scripts/` clean
- [ ] `uv run ruff check scripts/ tests/scripts/` clean
- [ ] Phase 3 restore real I/O test 全件 PASS 維持 (regression なし)
- [ ] approval issue CLI で発行した record を verify_signed_approval が allow にする (end-to-end #20-#23)
- [ ] approval issue 後 claim 改ざんで signature_invalid (R1 F-015 #24-#28)
- [ ] `--rollback` で snapshot dir / manifest 不在で exit 2
- [ ] `--rollback` で snapshot manifest sha256 / target binding / component hash mismatch で exit 2 (R1 F-001 + F-004)
- [ ] `--rollback` allow_unsigned_manual_skeleton で物理 deny (R1 F-002)
- [ ] `--remote` で signed config 不在 / signature invalid で exit 1
- [ ] approval signing key が world-readable / symlink / format 不正で reject (R1 F-008)
- [ ] TTL 48h 境界 PASS / 49h reject (R1 F-009)

### 6.3 codex-plan-review R1-R{N} polish

CLAUDE.md §14 mandatory Codex pre-commit gate に従い:
- `codex-all-loops mode=plan max-rounds=12 clean-criteria=critical_zero` で本 plan を polish
- Phase 1: `codex-review-loop` (構造磨き) → Phase 2: `codex-adversarial-loop` (敵対視点)
- CRITICAL=0 + HIGH ≤ 2 (Readiness Gate READY) 達成まで infinite loop
- 全 findings 100% adopt 反映、rejected.md / defer は AskUserQuestion 経由のみ

---

## §7 Codex multi-round R1-R{N} adoption log

### R1 (Phase A 構造): 19 findings → 全件 adopt 反映済 / R2 (Phase B 実装可能性): 6 findings → 全件 adopt 反映済 / R3 (CRITICAL only): 2 findings → 全件 adopt 反映済

#### R3 (CRITICAL only): 2 findings 全件 adopt 反映

| # | id | severity | adoption |
|---|---|---|---|
| 1 | F-001 | CRITICAL | T09 unblock condition に split-brain second line of defense (SP-012 active registry + active.signed marker chain + thaw 2-party-control + 同 migration_epoch reject test) を追加、§11 反映 |
| 2 | F-002 | CRITICAL | host-level destructive operation lock (`scripts/taskhub_destructive_lock.py` 新規 + `acquire_destructive_lock` context manager + fcntl.flock LOCK_EX|LOCK_NB + payload write)、§3.A.-1 + §3.A.2 rollback branch 統合 + test #26-#30 |

#### R4 (regression / 残留 CRITICAL): 1 finding 全件 adopt 反映

| # | id | severity | adoption |
|---|---|---|---|
| 1 | F-001 | CRITICAL | destructive lock の partial adoption (rollback のみ) を全 destructive subcommand に拡張、本 PR scope では `_cmd_restore --input` (Phase 3 既存) にも統合、他 (backup/migrate/freeze/thaw) は Phase 5 carry-over、§3.A.2 + test #31/#32 |

#### R5 (regression / 残留 CRITICAL): 1 finding 全件 adopt 反映

| # | id | severity | adoption |
|---|---|---|---|
| 1 | F-001 | CRITICAL | TOCTOU 排除: lock 取得を approval gate 直後に移動 + lock 内で manifest sha256 / target binding / component hash を **再計算 + verify**、新 reason_code `restore_rollback_snapshot_manifest_toctou_mismatch`、§3.A.2 + test #33/#34 |

#### R6 (regression / 残留 CRITICAL): 2 findings 全件 adopt 反映

| # | id | severity | adoption |
|---|---|---|---|
| 1 | F-001 | CRITICAL | `_cmd_restore --input` の concrete lock 統合 code (§3.A.2.5)、Phase 3 既存 code を destructive lock で wrap、test #35 |
| 2 | F-002 | CRITICAL | `rollback_from_pre_restore_snapshot` boundary 明確化 (§3.A.2.6): 内部は manifest verify 行わず既存 partial snapshot semantics 維持、CLI standalone path のみ manifest verify、Phase 3 auto-rollback 経路を保護、test #36 |

### Adversarial Phase 2 R2: 4 HIGH findings 全件 adopt 反映

| # | id | severity | adoption |
|---|---|---|---|
| 1 | F-001 | HIGH | approval write は final path に直接 O_CREAT|O_EXCL|O_NOFOLLOW (tmp+rename 廃止)、--force 廃止、§3.C.4 + test #34c |
| 2 | F-002 | HIGH | canonical_for_signature byte layout 仕様明示 (jcs_canonical({"domain": ..., "payload": payload}))、§3.A.0 / §3.B.2 + golden vector test |
| 3 | F-003 | HIGH | runbook §5 remote_hosts 生成 example を loader schema 完全一致 + repo helper 経由に変更、6 ヶ月期限切れ再 issue 手順追加 |
| 4 | F-004 | HIGH | approval key + verify key keyring rotation SOP を T09 unblock 条件に追加 (§11)、本 PR scope では single-key 前提を明示 |

### Adversarial Phase 2 R1: 18 findings 全件 adopt 反映

| # | id | severity | adoption |
|---|---|---|---|
| 1 | F-001 | CRITICAL | restore-rollback approval は upfront 不可、post-snapshot で per-subcommand issue、runbook §2.3 反映 + multi-subcommand example 削除 |
| 2 | F-002 | CRITICAL | destructive lock `TASKHUB_LOCK_DIR` env override + multi-user 制約 doc、§3.A.-1 反映 |
| 3 | F-003 | CRITICAL | docker compose state semantics: safe_down={exited,dead} のみ、restarting/paused/created/removing/unknown は state_unknown で fail-closed、§3.B.4 反映 + test #17d-#17g |
| 4 | F-004 | HIGH | approval record chmod 0o600 (旧 0o644 撤回)、test #34a |
| 5 | F-005 | HIGH | tmp file O_CREAT|O_EXCL|O_NOFOLLOW + try/except/finally、§3.C.4 + test #34b/#34c |
| 6 | F-006 | HIGH | runbook §1: tmp PEM file 経由 撤回、Python cryptography 直接 final path 出力 |
| 7 | F-007 | HIGH | `--backup-archive-sha256` CLI 削除 (既存 BackupApprovalClaim 整合)、runbook §2.1 反映 + test #34d |
| 8 | F-008 | HIGH | per-subcommand approval issue (1 approval = 1 subcommand)、runbook §2.1/2.2/2.3 反映 |
| 9 | F-009 | HIGH | signed config に `compose_file_sha256` 追加、SSH 経由 remote sha256 verify、§3.B.2/§3.B.4 + test #17m |
| 10 | F-010 | HIGH | _parse_restore_rollback_claim_dict per-field strict validate (regex / type / non-empty)、§3.A.0 |
| 11 | F-011 | MEDIUM | signed config に `config_version` + `expires_at` 追加、test #17k/#17l |
| 12 | F-012 | MEDIUM | shared canonicalizer `canonical_for_signature(domain, payload)`、§3.B.2 + test #34e |
| 13 | F-013 | MEDIUM | compose_file Unicode NFC + Cc/Cf reject、§3.B.3 + test #17n/#17o |
| 14 | F-014 | MEDIUM | remote_status reason_code を config_missing/permission/signature/malformed/expired/version で分離、§3.B.1 + test #17h-#17l |
| 15 | F-015 | MEDIUM | approval write try/except/finally + parent dir fsync、§3.C.4 |
| 16 | F-016 | MEDIUM | expected_postgres_major_version regex `^[1-9][0-9]*$` strict、§3.A.1 |
| 17 | F-017 | LOW | manifest_version != 1 reject + v1 fixture 固定、§3.A.1 |
| 18 | F-018 | LOW | runbook `$HOME` / `$TASKHUB_HOME` placeholder、hard-coded `/Users/tohga/` 撤回 |



#### R2 (Phase B): 6 HIGH findings 全件 adopt 反映

| # | id | severity | adoption |
|---|---|---|---|
| 1 | F-001 | HIGH | Batch B subprocess API を既存 `run_safe_subprocess(argv, config=SafeSubprocessConfig(timeout_sec=...))` に統一、stdout 64 KiB 上限は post-read `len(result.stdout)` check、stderr 検査は `result.stderr_sanitized` (str) 使用、§3.B.4 反映 |
| 2 | F-002 | HIGH | `_parse_restore_rollback_claim_dict` + `_restore_rollback_claims_match` + `_load_approval_record` allowed_keys 追加 + `ApprovalRecord` constructor 拡張、§3.A.0 反映 |
| 3 | F-003 | HIGH | remote identity check を `actual_services == expected_set` exact set 一致に変更 (partial overlap で safe 判定不可)、§3.B.4 反映 + test #17a/17b/17c |
| 4 | F-004 | HIGH | manifest schema を per-component `{present: bool, sha256: string|null, skipped_reason: string|null}` に変更、partial snapshot semantics 維持、§3.A.1 反映 |
| 5 | F-005 | HIGH | `run_restore()` に rollback_mode を導入しない、CLI rollback 分岐は `rollback_from_pre_restore_snapshot` 直接呼出、test #17 を `for_rollback_mode` construct test に変更、§3.A.3 反映 |
| 6 | F-006 | HIGH | `read_alembic_head_via_compose_exec` 新規 helper (既存 verify_alembic_head_in_db パターン)、`create_pre_restore_snapshot` で manifest に保存、§3.A.1 反映 |

#### R1 (Phase A 構造): 19 findings → 全件 adopt 反映済

| # | id | severity | category | adoption |
|---|---|---|---|---|
| 1 | F-001 | CRITICAL | security | `RestoreRollbackApprovalClaim` 新規 + verify/issue/CLI 統合、§3.A.0 / §3.A.2 / §3.C.2 反映 |
| 2 | F-002 | HIGH | security | `restore-rollback` `--allow-unsigned-manual-skeleton` 物理 deny、§3.A.2 line 「R1 F-002 adopt」+ test #8 |
| 3 | F-003 | HIGH | security | `args.rollback` regex `^\d{8}T\d{6}(?:-\d+)?$` + `resolve(strict=True)` + symlink reject、§3.A.2 / §2.5 反映 + test #1-#4 |
| 4 | F-004 | HIGH | missing | `snapshot_manifest.json` 契約 + verify_snapshot_manifest_binding / component_hashes helper、§3.A.1 反映 + test #12-#16 + #18 |
| 5 | F-005 | HIGH | risk | CLI rollback branch broad exception catch、§3.A.2 反映 + test #20-#21 |
| 6 | F-006 | HIGH | inconsistency | `remote_hosts.signed.json` per-host config + `frontend` service 含む expected_services、§3.B.2 / §3.B.4 反映 + test #16-#17 |
| 7 | F-007 | HIGH | security | compose project regex + file absolute path validation + shlex.quote、§3.B.3 反映 + test #5-#7 + #20 |
| 8 | F-008 | HIGH | inconsistency | raw 32-byte seed format + operator-runbook helper Python、§2.5 / §3.D.1 §1 反映 + test #6 |
| 9 | F-009 | HIGH | inconsistency | `sa.DEFAULT_MAX_TTL=48h` import + default 24h、§3.C.3 反映 + test #17-#19 |
| 10 | F-010 | HIGH | missing | restore_claim 12 field 完全 1:1 mapping 表、§3.C.2 反映 + test #13 |
| 11 | F-011 | HIGH | inconsistency | `choices=sorted(DRILL_KIND_ALLOWED_SUBCOMMANDS.keys())` で既存 dict 派生、§3.C.3 反映 + test #10 |
| 12 | F-012 | HIGH | planning | T09 unblock condition の hard gate を §11 に明記、Phase 5 carry-over として SP022-T02 Phase 5 起票 |
| 13 | F-013 | MEDIUM | inconsistency | Sprint Pack carry-over 7 件 1:1 trace、§1.1 反映 |
| 14 | F-014 | MEDIUM | inconsistency | reason_code exact count (approval_issue 22 / remote_status 12)、§4.4 反映 |
| 15 | F-015 | MEDIUM | missing | canonical payload tamper negative test 5 fixture、§3.C.5 test #24-#28 |
| 16 | F-016 | MEDIUM | ambiguity | `remote_status_ssh_host_key_untrusted` reason_code + runbook §7 bootstrap、§3.B.1 / §3.D.1 反映 + test #10 |
| 17 | F-017 | MEDIUM | inconsistency | reason_summary regex + runbook example 修正、§2.5 / §3.D.1 §2 反映 + test #9 |
| 18 | F-018 | LOW | ambiguity | `issue_revoke_record` stub 完全削除 (public surface に出さない)、§3.D.1 §3 反映 |
| 19 | F-019 | LOW | ambiguity | zeroize timing 明確化 (`bytearray` + immediate overwrite + library limit)、§2.3 / §3.C.4 / §3.D.1 §6 反映 + test #30-#31 |

---

## §8 ADR proposed → accepted 化 trigger

本 PR で touch する ADR:
- ADR-00021 (host_portable_deployment): 既に `accepted` 状態。本 PR は §11.2 / §14.1 PGA-F-003 / PGA-F-013 の実装に過ぎず、ADR 自体の修正なし。
- 新規 ADR proposed の必要性: なし (rules/sprint-pack-adr-gate.md §4 ADR Gate Criteria 11 種に該当しない、既存 ADR の実装範囲内)

---

## §9 PR title + commit message format

```
feat(sp022-t02p4): SP022-T02 Phase 4 + T08 batch 4 — --rollback real I/O + status --remote split-brain detection + approval issue CLI

- Batch A: `taskhub restore --rollback <pre-restore-ts>` real I/O + 新 RestoreRollbackApprovalClaim + snapshot manifest verify
- Batch B: `taskhub status --remote <host>` Tailscale SSH + host-specific signed config (split-brain default deny first line)
- Batch C: `taskhub approval issue` Ed25519-signed record CLI (restore_claim 12 field + drill_kind dict 派生 + zeroize)
- Batch D: docs/deploy/operator-runbook.md (raw seed key bootstrap / issue / re-sign migration / known_hosts / SecretBroker limit)

codex-all-loops R1-R{N} polish: {N1+N2} findings 全件 adopt + Readiness Gate READY
SP022-T02 Phase 4 完遂、SP022-T09 unblock は backup pg_dump compose exec 切替 (Phase 5) 完了待ち

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

---

## §10 PR 後の carry-over

§1.1 Sprint Pack carry-over 7 件 trace 参照:
- ✅ this PR closure: #1 `--rollback` / #2 `status --remote` / #3 `approval issue` / #7 re-sign SOP
- ❌ explicit out-of-scope: #4 age secret broker integration (P0 manual)
- ❌ blocked_by SP022-T09: #5 actual tool execution validation (実機 drill phase)
- ❌ next PR carry-over: #6 backup_orchestrator pg_dump compose exec 切替 (**SP022-T02 Phase 5**、T09 unblock の hard gate)

---

## §11 T09 unblock condition (R1 F-012 + R3 F-001 adopt: hard gate 明示)

SP022-T09 host migration drill (Mac → VPS RTO ≤ 4h verify) を unblock する条件 (**R3 F-001 + ADV R2 F-004 adopt: split-brain second line + keyring rotation 要件追加**):

- ✅ SP022-T02 Phase 1 (signed approval) — PR #75 merged
- ✅ SP022-T02 Phase 2 (backup real I/O) — PR #77 merged
- ✅ SP022-T02 Phase 3 (restore real I/O) — PR #78 merged
- ✅ SP022-T02 Phase 4 (rollback + remote split-brain first line + approval issue + destructive lock) — **本 PR**
- ❌ SP022-T02 Phase 5 (backup pg_dump compose exec 切替) — 別 PR 必須
- ❌ **SP-012 active registry + active.signed marker chain + thaw 2-party-control** — SP-012 must_ship (ADR-00021 §11.2 + §14.1 PGA-F-003)、本 PR / Phase 5 では実装しない
- ❌ **`tests/deploy/test_split_brain_prevention.py` 同 migration_epoch 二重 active reject 必須 fixture** — SP-012 acceptance に追加
- ❌ **approval signing key + verify key keyring rotation SOP (ADV R2 F-004 adopt)** — SP-012 / SP-022 後続 batch 必須。本 PR は single-key 前提、verifier は `_load_verify_key_and_fingerprint` の 1 file 読込 design。rotation 時は (1) new pubkey 生成 + 全 target host へ secret manager push、(2) overlap 期間 old+new 両方 trust (`approval-verify-keys.d/<fingerprint>.pub` 形式 keyring 移行)、(3) remote_hosts を new key で再 sign + 配布、(4) 全 host smoke test 完了後 (5) old key revoke。本 PR scope では keyring 化未実装、operator が手動で single-key の置換 (旧 fingerprint 削除 + 新 fingerprint 追加) で対応、ただし大規模 drill 中に rotation する場合は別 PR で keyring 化を完了させる必要

**本 PR が merge されても、SP022-T09 は Phase 5 + SP-012 split-brain second line 未完了の限り unblock しない**。`taskhub status --remote` (本 PR Batch B) は **split-brain first line of defense のみ**、second line (freeze.signed + active.signed marker chain + thaw 2-party-control) は SP-012 で実装。

Sprint Pack §SP022-T09 status を「⛔ deferred (blocked_by: SP022-T02 Phase 5 + SP-012 split-brain second line)」のまま維持。両方完了後に T09 を unblock。

理由:
- **R1 F-012**: Phase 5 未完了の限り backup direction は host TCP port-collision attack surface が残存
- **R3 F-001 (split-brain second line)**: `taskhub status --remote` は **network partition / partial reachability** で false-safe を返す経路があり、ADR-00021 §11.2 invariant 「同 migration_epoch で 2 host active 絶対禁止」を **first line のみ**では保証できない (`status --remote` 失敗時の deny 経路は本 PR にあるが、source host で「target restore 成功 → source 自動 thaw deny」は active.signed marker chain で実装必須、本 PR scope 外)
- 本 PR scope を膨らませず SP-012 で対応する方が code review / Codex review の visibility が確保される

---

## §12 risk summary

| risk | mitigation |
|---|---|
| approval issue CLI が operator-supplied claim を bypass | CLI 内部で `BackupApprovalClaim` / `RestoreApprovalClaim` / `RestoreRollbackApprovalClaim` dataclass strict validation + canonical payload root binding test (#20-#28) |
| signing key の raw leak | mode 0o600 + symlink reject + dir 0o700 + format raw 32-byte seed + bytearray zeroize + stderr/stdout filter (test #2-#6, #30-#31) |
| `--remote` ssh で auto-trust 旧 host / wrong project compose ps | host-specific signed config + StrictHostKeyChecking=yes + remote identity verify (test #16-#17) + known_hosts bootstrap SOP |
| rollback で wrong snapshot 復旧 | regex + resolve(strict=True) + symlink reject + manifest sha256 binding + target manifest verify + component hash verify (test #1-#4, #12-#16) |
| 既存 record signature_invalid 化 | docs §4 で operator 手順明記 + archive 隔離 SOP |
| concurrent approval issue (UUID 衝突) | atomic rename + 既存 file 検知 + --force 必須 (test #7) |
| T09 drill が backup direction 脆弱性で危険 | §11 hard gate で T09 unblock を Phase 5 完了待ちに |
