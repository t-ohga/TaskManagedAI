# SP022-T02 Phase 1: Signed approval Ed25519 verify + automation detection deny

最終更新: 2026-05-20 (r4、R1 18 + R2 5 + R3 1 = 24 findings 全件 adopt: R3 = CRITICAL × 1 security bypass fix、env override 全削除 + fingerprint allowlist hard fail)

`plan_status`: 🟥 heavy (T02 phase 分割の Phase 1、CLI scaffold は Sprint 12 batch 7 で完了済、本 Phase は security boundary 確立に絞る)

## 1. 目的 (Goal)

SP022-T03 SOP §7 (`docs/deploy/half-yearly-drill-sop.md` line 116-126) で planned contract として明文化された **`taskhub` admin CLI の security boundary** を実装。

- **signed approval Ed25519 verification** module 新規 (`scripts/taskhub_signed_approval.py`):
  - **RFC 8785 strict JCS canonical JSON encoder** (F-001 adopt: datetime は parse 後 isoformat 再構成せず原文字列を canonical bytes に保持、reference vector 同梱)
  - approval record schema (strict、`approval_id` allowlist + path traversal deny + `record.approval_id` vs CLI 引数 一致 verify、`signed_at` clock skew tolerance + `expires_at - signed_at <= max_ttl`、signature strict base64 + 64-byte fixed length)
  - subcommand claim requirement 表 (subcommand 属性分類)
  - automation context detection (env matrix 拡張 + TTY absence + container hints)
  - **default deny invariant** for destructive subcommands (F-002 adopt: manual exec も default deny、`--allow-unsigned-manual-skeleton` skeleton-only escape flag、Phase 2-4 では escape 削除予定)
- **`taskhub_admin.py` integration**: destructive subcommand 全件に signed approval pre-execution gate、`--approval-id` / `--from-automation` / `--allow-unsigned-manual-skeleton` 引数追加
- **redacted audit-line scaffold** (F-004 adopt: SecretBroker integration は Phase 2 carry-over、Phase 1 は stderr scaffold のみで scope 矛盾を解消): allowlist 方式 payload (raw `reason` 出さない、`decider` actor_id のみ、`approval_id` 固定形式、env var name のみ)

本 Phase 1 では **既存 skeleton 出力を維持しつつ pre-execution gate のみ追加**。実 backup / restore / migrate I/O は Phase 2-4 で実装。

## 2. 背景 (Background)

- Sprint 12 batch 7 で `scripts/taskhub_admin.py` が 10 subcommand 全 skeleton 完成 (init / backup / restore / migrate / status / age-rotate / verify / freeze / thaw / active-registry)、argparse 完成
- T02 = `taskhub migrate` 自動化 (rollback / split-brain 防止 / age key 運搬連携)、ADR-00021 §3-§7 spec 完備
- **T03 SOP §7 (planned contract for T02、SP022-T02 で確定)**: `taskhub migrate` の手動 approval flow と整合する invariant 想定 (signed approval ID + Ed25519 verify + automation detection)
- Phase 分割 (SP-022 line 95、本 plan §1 通り、`.claude/reference/task-planning-matrix.md` §2 で公式化):
  - **Phase 1 (本 plan)**: CLI security boundary (signed approval + automation deny + redacted audit-line scaffold、本 PR で完結)
  - Phase 2: backup-restore 実 I/O + SecretBroker integration (`taskhub backup` / `taskhub restore` の real pg_dump / pg_restore / age encryption + SecretBroker-mediated audit sink + approval consumption ledger、別 PR)
  - Phase 3: migrate orchestration (`taskhub migrate` の backup → Tailscale transfer → target restore → smoke + age key rotation、別 PR)
  - Phase 4: freeze-thaw split-brain prevention (`taskhub freeze` / `taskhub thaw` の signed marker + 2-party-control、別 PR)
- R1 18 findings 全件 adopt (HIGH 5 + MED 8 + LOW 5)、CRITICAL 0 残存、Readiness Gate READY (R2-R3 で更に polish)

## 3. Scope (実装範囲)

### 3.1 must_ship (本 PR 内)

| # | 対象 | 種別 |
|---|---|---|
| 1 | `scripts/taskhub_signed_approval.py` (NEW) | signed approval module: RFC 8785 strict JCS encoder + Ed25519 signature verify + record schema (allowlist) + automation detection (拡張 env matrix + TTY absence + container hints) + subcommand claim 表 + audit-line scaffold |
| 2 | `scripts/taskhub_admin.py` (MODIFY) | destructive subcommand (backup / restore / migrate / freeze / thaw / age-rotate) に signed approval pre-execution gate integrate、`--approval-id` + `--from-automation` + `--allow-unsigned-manual-skeleton` 引数追加、default deny invariant |
| 3 | `tests/scripts/test_taskhub_signed_approval.py` (NEW) | pytest fixture: positive (RFC 8785 reference vector + valid Ed25519 sig + verify key fingerprint match) + negative (path traversal / approval_id mismatch / signature 不整合 / expired / max_ttl 超過 / signed_at future / subcommand not allowed / target_host mismatch / drill_kind ↔ allowed_subcommands 不整合 / verify key missing / verify key fingerprint mismatch / automation without flag / from_automation without approval_id / manual destructive without approval / allow-unsigned-manual-skeleton + non-destructive subcommand) |
| 4 | `tests/scripts/test_taskhub_admin_security.py` (NEW) | pytest fixture: destructive subcommand に signed approval gate integration verify (default deny + skeleton escape + cron env detect + approval gate 通過 PASS path) |
| 5 | `pyproject.toml` (MODIFY) | `cryptography>=42,<43` dependency 追加 (Ed25519 signature verify、現代 standard) |
| 6 | `uv.lock` (MODIFY) | `uv lock` 更新 + `uv sync --locked` で再現性確認 (F-013 adopt) |
| 7 | `docs/deploy/half-yearly-drill-sop.md` (MODIFY) | §7 を **節単位で分割**: approval record schema + Phase 1 pre-execution gate は normative、実 I/O / SecretBroker integration / rotation / split-brain marker は planned carry-over (F-006 adopt) |
| 8 | `tests/scripts/test_taskhub_admin.py` (MODIFY、R2-F-002 adopt) | 既存 destructive skeleton 回帰テスト (backup / restore / migrate / freeze / thaw / age-rotate) に `--allow-unsigned-manual-skeleton` 付与で exit 1 維持、approval なしの destructive 実行は別 fixture で exit 2 期待。non-destructive 既存 fixture (init / status / verify / active-registry) は無変更で維持 |
| 9 | `.claude/plans/sp022-t02-phase1-signed-approval.md` (本計画、commit 含む) | - |

### 3.2 対象外 (本 Phase 1 では実装しない、Phase 2-4 で実装)

- **実 backup I/O** (pg_dump / Redis BGSAVE / artifacts tar / age encryption): Phase 2
- **実 restore I/O** (age decrypt / pg_restore / volume move / alembic check / healthcheck): Phase 2
- **実 migrate orchestration** (Tailscale transfer / target host SSH): Phase 3
- **実 freeze-thaw split-brain prevention** (signed marker file write / 2-party-control approval): Phase 4
- **age key 生成 / rotation 自動化**: Phase 2-3 (T02 全体で扱うが Phase 1 では Ed25519 signing key の verify key allowlist のみ scope)
- **Tailscale ACL / Serve 設定 自動化**: Phase 3
- **rollback edge case (network 切断 + age key compromise 同時)**: Phase 3 + 手動 SOP (SP-022 line 157)
- **SecretBroker-mediated audit sink integration** (F-004 adopt): Phase 2 carry-over、Phase 1 は stderr-only redacted audit-line scaffold
- **approval consumption ledger (replay 防止 one-time approval marker)** (F-007 adopt): Phase 2 carry-over、Phase 1 では `expires_at - signed_at <= max_ttl` + `signed_at <= now + skew` で時間軸の replay risk 縮小、ledger は Phase 2 で audit DB write integration と同時実装
- **process tree-based automation detection** (`pid` / `ppid` / parent process inspection、F-003 carry-over): Phase 2 で ADR Gate 判断、Phase 1 では env matrix + TTY + container hints のみ
- **`--allow-unsigned-manual-skeleton` escape flag の削除** (F-002 adopt invariant): Phase 2 実 I/O 配置時に削除、Phase 1 では skeleton mode 互換のため残す
- **`taskhub` admin CLI 全体 of authoritative invariant 化** (F-006 adopt): SOP §7 normative 昇格は **approval record schema + Phase 1 pre-execution gate** に限定、実 I/O / SecretBroker integration / rotation は planned carry-over として SOP §7 内に明示
- **`restore` subcommand の target_host claim** (R2-F-003 adopt): 既存 `restore` parser には `--target` が不在、本 Phase 1 では restore の target claim を **未実装として明示的に外す** (subcommand 属性表 §4.4 で `restore` target_host は (required for future) と記載、Phase 2 で `--target-host` argument 追加判断)。Phase 1 で claim 検査するのは `migrate` のみ

## 4. Security boundary 設計

### 4.1 Approval record schema (strict、F-005 + F-007 + F-014 + F-015 + F-016 adopt)

`~/.taskhub/approvals/<approval_id>.signed` (JSON):

```json
{
  "approval_id": "drill-2026-07-01-<sha8>",
  "decider": "<human-actor-id>",
  "reason_summary": "half-yearly-drill",
  "signed_at": "2026-06-30T15:00:00Z",
  "expires_at": "2026-07-02T15:00:00Z",
  "drill_kind": "host_migration_mac_vps",
  "allowed_subcommands": ["backup", "migrate", "restore"],
  "target_host": "t-ohga-vps",
  "signature": "<base64 Ed25519 signature, 64 bytes after decode>"
}
```

#### 4.1.1 approval_id allowlist (F-005 adopt: path traversal deny)

- regex: `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`
- path resolve 後に `APPROVAL_DIR` (`~/.taskhub/approvals/`) 配下である verify (`Path.resolve()` で symlink 解決後の parent 確認)
- 違反 → `taskhub_signed_approval_approval_id_malformed`

#### 4.1.2 record.approval_id vs CLI 引数一致 verify (F-015 adopt: replay 防止)

- record file 内の `approval_id` field と CLI `--approval-id` 引数の値が完全一致しない → deny
- 違反 → `taskhub_signed_approval_record_id_mismatch`

#### 4.1.3 datetime 文字列 strict (F-001 adopt: RFC 8785 canonical 整合)

- `signed_at` / `expires_at` は **strict `YYYY-MM-DDTHH:MM:SSZ` UTC format**、`+00:00` や別タイムゾーン rejected
- parse 後 isoformat 再構成は禁止、**原文字列を canonical bytes に保持**
- 違反 → `taskhub_signed_approval_datetime_format_invalid`

#### 4.1.4 clock skew + max_ttl (F-007 adopt: replay 防止)

- `signed_at <= now + clock_skew` (default `clock_skew = 5 minutes`)
- `now < expires_at`
- `expires_at - signed_at <= max_ttl` (default `max_ttl = 48 hours`、drill scheduling SOP §4 半年 drill の最大期間想定)
- 違反 → `taskhub_signed_approval_signed_at_future` / `taskhub_signed_approval_expired` / `taskhub_signed_approval_ttl_exceeded`

#### 4.1.5 reason_summary は **allowlist 方式** (F-010 adopt)

- 原 `reason` は人間入力で長文 / 改行 / 制御文字 / 秘密パターンが入り得る → audit に出さない
- 代わりに `reason_summary` (短い enum-style label、最大 64 chars、`^[A-Za-z0-9_-]+$`) を schema に持つ
- 違反 → `taskhub_signed_approval_reason_summary_malformed`

#### 4.1.6 signature strict base64 + 64-byte (F-016 adopt)

- base64 strict decode (padding 必須、whitespace 不許可、`validate=True`)
- decode 後 64 bytes 固定長
- 違反 → `taskhub_signed_approval_signature_malformed` (signature_invalid とは別 reason_code、record 体裁の問題か署名値の問題かを区別)

#### 4.1.7 drill_kind ↔ allowed_subcommands 整合 (F-014 adopt)

| drill_kind | allowed_subcommands 上限 |
|---|---|
| `host_migration_mac_vps` / `host_migration_linux_vps` / `host_migration_vps_vps` | `backup`, `migrate`, `restore` |
| `backup_only` | `backup` のみ |
| `restore_only` | `restore` のみ |
| `age_rotate` | `age-rotate` のみ |
| `freeze_only` | `freeze` のみ |
| `thaw_only` | `thaw` のみ |

`allowed_subcommands` が上記上限を超える要素を含む → deny。違反 → `taskhub_signed_approval_drill_kind_subcommands_mismatch`。

#### 4.1.8 signature 対象 payload (canonical bytes)

RFC 8785 strict JCS canonical JSON。実装は本 plan §5.1 に reference vector を同梱。署名対象 fields:

`approval_id` / `decider` / `reason_summary` / `signed_at` (原文字列) / `expires_at` (原文字列) / `drill_kind` / `allowed_subcommands` (string array) / `target_host` (null 許容)

### 4.2 Ed25519 signing key 管理 + verify key fingerprint allowlist (F-009 adopt)

- Signing key (private): SOPS age 暗号化で `~/.taskhub/keys/approval-signing-key.txt.encrypted` に保管 (Phase 1 scope 外、user 物理運搬 SOP)
- Verify key (public): plain で `~/.taskhub/keys/approval-verify-key.pub` (chmod 644 推奨、Phase 1 で chmod check 実施)
- **Verify key fingerprint allowlist** (F-009 + R2-F-004 adopt): repo 内 `.taskhub/approval-verify-key-fingerprints.allowlist` (新規) に SHA-256 fingerprint hex string を line-separated で list。**Phase 1 では file 不在 / comment-only / 空 list を soft warning** として扱う (production deployment 前に Phase 2 で hard fail 化判断、本 plan §3.2 carry-over)。**File 存在 + 1+ fingerprint entry の場合は hard fail** (verify key の fingerprint がいずれの entry とも不一致なら deny)。pytest positive fixture では生成した verify key の SHA-256 fingerprint を `tmp_path` 内 allowlist file に書き込む (R2-F-004 adopt)
- **Verify key owner/mode test** (F-009 adopt): `_load_verify_key()` 内で `os.stat()` 実施、owner = current user / mode 0o644 以下 / writable group 不在 を verify、違反 → `taskhub_signed_approval_verify_key_permission_unsafe`
- Algorithm: **Ed25519** 固定 (cryptography lib 採用、PyNaCl は別 dependency tree 回避)、RSA / ECDSA は本 Phase で deny

### 4.3 Automation detection logic (F-003 + F-011 adopt: env matrix 拡張 + 一貫性)

destructive subcommand pre-execution gate で以下を検出:

#### 4.3.1 env matrix (源別)

| env var | source | 採用理由 |
|---|---|---|
| `SYSTEMD_INVOCATION_ID` | systemd | systemd-spawned process 標準 |
| `INVOCATION_ID` | systemd (older versions) | 古い systemd 互換 |
| `JOURNAL_STREAM` | systemd journal redirect | journal 経由実行検出 |
| `CRON_INVOCATION` | vixie-cron / cronie | cron-spawned process |
| `GITHUB_ACTIONS` | GitHub Actions | CI run 標準 |
| `CI` | generic CI | 多 CI provider 共通 |
| `BUILD_ID` / `BUILD_NUMBER` / `RUN_ID` | Jenkins / TeamCity / GitHub | build automation |
| `KUBERNETES_SERVICE_HOST` | Kubernetes | container/pod 経由 |
| `container` | systemd-nspawn / podman / docker (一部) | container env |
| `BASH_EXECUTION_STRING` | shell -c | shell-spawn 経由 |

**不採用** (false positive 抑止、F-011 adopt):
- `DBUS_SESSION_BUS_ADDRESS`: graphical session で常在、deny 条件に使わない

#### 4.3.2 TTY absence (F-003 adopt)

- `stdin` / `stdout` の `isatty()` 両方 False かつ env matrix hit なし → automation 疑い (weak signal、residual risk として記録のみ、deny 条件には使わない、Phase 1)
- Phase 2 で ADR Gate で deny 条件昇格を判断

#### 4.3.3 detection function

```python
AUTOMATION_ENV_VARS = (
    "SYSTEMD_INVOCATION_ID",
    "INVOCATION_ID",
    "JOURNAL_STREAM",
    "CRON_INVOCATION",
    "GITHUB_ACTIONS",
    "CI",
    "BUILD_ID",
    "BUILD_NUMBER",
    "RUN_ID",
    "KUBERNETES_SERVICE_HOST",
    "container",
    "BASH_EXECUTION_STRING",
)

def detect_automation_context() -> dict[str, list[str]]:
    """Return detected env var names (no values, F-010 adopt: audit payload allowlist 方式).

    Strong signal: env matrix hit
    Weak signal: TTY absence + no env hit (residual risk only, Phase 1 では deny に使わない)
    """
    env_hits = [v for v in AUTOMATION_ENV_VARS if os.environ.get(v)]
    tty_absent = not sys.stdin.isatty() and not sys.stdout.isatty()
    return {
        "env_hits": env_hits,  # var names only, raw values not included
        "tty_absent": tty_absent,
    }
```

### 4.4 Subcommand claim requirement 表 (F-008 + F-012 adopt: 属性分類 + claim 明示)

| subcommand | writes_state | reads_secret | remote_access | service_disruption | approval gate | required claim |
|---|---|---|---|---|---|---|
| `init` | yes (initial setup) | no (yet) | no | no | **non-destructive** (initial bootstrap、Phase 1 では skip、Phase 2 で再評価) | - |
| `backup` | no (read-only export) | yes (env decryption + age encrypt 出力) | no | yes (service stop) | **destructive** | `source_host` (option) |
| `restore` | yes (DB / volume overwrite) | yes (age decrypt) | no | yes (service stop + volume move) | **destructive** | `target_host` (**Phase 1 では未実装 / Phase 2 で `--target-host` argument 追加判断**、R2-F-003 adopt: 既存 `restore` parser には `--target` 不在のため Phase 1 では claim 検査外す) |
| `migrate` | yes (target host write) | yes (age + ssh / tailscale) | yes (target host) | yes (source + target service stop) | **destructive** | `target_host` (required、CLI `--target` と record `target_host` 両方 non-empty + exact match、R2-F-003 adopt) |
| `status` | no | yes (`--age-safety` で age key inspect) | optional (`--remote`) | no | **non-destructive** (Phase 1 では skip、ただし `--remote` 経由 Phase 2 で再評価) | - |
| `age-rotate` | yes (key file rotate) | yes (signing/decryption key) | no | no (service down 不要、key 入替のみ) | **destructive** | `key_scope` (carry-over to Phase 2-3) |
| `verify` | no | optional (`--integrity` で SOPS read) | optional (Phase 2+ で remote check) | no | **non-destructive** (Phase 1 では skip、Phase 2 で secret / remote 引数追加時に再評価) | - |
| `freeze` | yes (signed marker file 生成) | no | no | yes (service down + signed marker write) | **destructive** | `environment` (host scope) |
| `thaw` | yes (signed marker 解除) | no | optional (`--decommission-target` で remote registry write) | yes (service up) | **destructive** | `environment` (host scope) |
| `active-registry` | no (print only) | no (signed read のみ) | no | no | **non-destructive** | - |

**Phase 1 destructive list (gate 適用対象、6 件)**: `backup`, `restore`, `migrate`, `age-rotate`, `freeze`, `thaw`

**Phase 1 non-destructive list (gate skip、4 件)**: `init`, `status`, `verify`, `active-registry`

`init` / `status` / `verify` / `active-registry` の **Phase 2+ re-classification trigger**:
- `init` が初回 Docker volume 作成 + age key 生成を実装する Phase 2 では destructive 化判断 (ADR Gate)
- `status --remote` / `status --age-safety` が remote host inspect / age key 内容 read を実装する Phase 2 では re-classify 判断
- `verify --integrity` が SOPS 復号 + remote check を実装する Phase 2 では re-classify 判断

claim required は本 Phase 1 では `target_host` のみ実装 (**`migrate` で必須、`restore` は Phase 2 carry-over**、R2-F-003 adopt)、他 claim (`source_host` / `key_scope` / `environment`) は Phase 2-3 carry-over として approval record schema に optional field として追加。

#### 4.4.1 `migrate` target_host claim 厳密化 (R2-F-003 adopt)

`migrate` の target_host claim は以下を **全て満たすときのみ allow**:

- CLI `--target` 引数が non-empty string (空文字 / None / whitespace-only は deny)
- record の `target_host` field が non-empty string (空文字 / null / whitespace-only は deny)
- `--target` と `record.target_host` の string 完全一致 (`.strip()` 後 case-sensitive compare、`strip` で whitespace 差を吸収)

違反 → `taskhub_signed_approval_target_host_mismatch`

### 4.5 Pre-execution gate logic (F-002 + F-017 adopt: default deny + reason_code 区別)

```python
def require_approval_for_destructive(
    subcommand: str,
    approval_id: str | None,
    from_automation: bool,
    allow_unsigned_manual_skeleton: bool,
    target_host: str | None = None,
) -> tuple[bool, ReasonCode, dict[str, object]]:
    """Pre-execution gate. Default deny for destructive subcommands.

    Returns (allowed, reason_code, audit_payload_extras).
    F-002 adopt: destructive 手動実行 (automation なし、approval_id なし) は default deny、
    `--allow-unsigned-manual-skeleton` escape flag (Phase 2 で削除予定) のみ allow.
    F-017 adopt: non-destructive subcommand skip と verified PASS は別 reason_code.
    """
    extras: dict[str, object] = {
        "subcommand": subcommand,
        "from_automation": from_automation,
        "allow_unsigned_manual_skeleton": allow_unsigned_manual_skeleton,
    }
    if subcommand not in DESTRUCTIVE_SUBCOMMANDS:
        # F-017 adopt: skip と verified は別 reason_code
        return True, "taskhub_signed_approval_skipped_non_destructive", extras

    automation = detect_automation_context()
    extras["automation_env_hits"] = automation["env_hits"]
    extras["tty_absent"] = automation["tty_absent"]

    has_automation_env = bool(automation["env_hits"])

    # F-002 adopt: default deny
    if has_automation_env:
        if not from_automation:
            return False, "taskhub_signed_approval_automation_detected_without_flag", extras
        if not approval_id:
            return False, "taskhub_signed_approval_from_automation_requires_approval_id", extras
    elif not approval_id:
        # 手動実行 (automation env なし) かつ approval_id なし
        if allow_unsigned_manual_skeleton:
            # F-002 adopt: skeleton-only escape (Phase 2 で削除予定)
            extras["unsigned_manual_skeleton_used"] = True
            return True, "taskhub_signed_approval_unsigned_manual_skeleton_allowed", extras
        # default deny
        return False, "taskhub_signed_approval_destructive_requires_approval", extras

    # approval_id 提供時は verify
    allowed, reason, verify_extras = verify_signed_approval(
        approval_id, subcommand, target_host=target_host
    )
    extras.update(verify_extras)
    return allowed, reason, extras
```

### 4.6 Audit-line scaffold (F-004 + F-010 adopt: stderr-only redacted scaffold)

Phase 1 では stderr 経由の **redacted audit-line scaffold** のみ。SecretBroker boundary 経由 audit sink integration は Phase 2 carry-over。Phase 1 では payload を allowlist 方式で構築:

```python
AUDIT_PAYLOAD_ALLOWLIST_KEYS = frozenset({
    "reason_code",
    "subcommand",
    "approval_id",            # 固定形式 (regex 検証済)
    "decider",                # actor_id のみ (raw secret なし)
    "drill_kind",             # enum-style label
    "allowed_subcommands",    # list of subcommand names (signature 対象、機密ではない)
    "target_host",            # hostname (機密ではない)
    "expected_target_host",   # mismatch 時のみ
    "actual_target_host",     # mismatch 時のみ
    "from_automation",
    "allow_unsigned_manual_skeleton",
    "unsigned_manual_skeleton_used",
    "automation_env_hits",    # var names のみ (raw values なし)
    "tty_absent",
    "timestamp",
    "audit_marker",
    "verify_key_fingerprint", # SHA-256 hex (起動時取得、allowlist 照合用)
})

# 出力禁止 (raw `reason` は出さない、F-010 adopt):
# - raw signature bytes
# - signing key 任意形態
# - raw `reason` (人間入力、機密 / 制御文字 risk)
# - approval record file 内 raw bytes

def emit_audit_event(reason_code: ReasonCode, extras: dict[str, object]) -> None:
    """Emit redacted audit-line scaffold to stderr (Phase 1)."""
    payload = {
        "reason_code": reason_code,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "audit_marker": "taskhub_signed_approval_gate",
    }
    for k, v in extras.items():
        if k in AUDIT_PAYLOAD_ALLOWLIST_KEYS:
            payload[k] = v
    print(  # noqa: T201
        f"AUDIT taskhub_signed_approval_gate: {json.dumps(payload, sort_keys=True)}",
        file=sys.stderr,
    )
```

### 4.7 Reason codes (一覧)

| reason_code | trigger | exit code |
|---|---|---|
| `taskhub_signed_approval_verified` | Ed25519 verify PASS + claim match | 0 (subcommand 実行へ) |
| `taskhub_signed_approval_skipped_non_destructive` | non-destructive subcommand (F-017) | 0 (gate skip) |
| `taskhub_signed_approval_unsigned_manual_skeleton_allowed` | manual destructive + `--allow-unsigned-manual-skeleton` (Phase 1 only、Phase 2 で削除) | 0 (skeleton mode) |
| `taskhub_signed_approval_destructive_requires_approval` | manual destructive + approval_id なし + `--allow-unsigned-manual-skeleton` なし (default deny、F-002) | 2 |
| `taskhub_signed_approval_automation_detected_without_flag` | env matrix hit + `--from-automation` 未指定 | 2 |
| `taskhub_signed_approval_from_automation_requires_approval_id` | `--from-automation` 指定 + `--approval-id` 未指定 | 2 |
| `taskhub_signed_approval_approval_id_malformed` | `approval_id` allowlist 違反 / path traversal (F-005) | 2 |
| `taskhub_signed_approval_record_not_found` | `~/.taskhub/approvals/<id>.signed` 不在 | 2 |
| `taskhub_signed_approval_record_malformed` | JSON parse error / required field 不在 | 2 |
| `taskhub_signed_approval_record_id_mismatch` | record.approval_id ≠ CLI 引数 (F-015) | 2 |
| `taskhub_signed_approval_datetime_format_invalid` | strict UTC `Z` format 違反 (F-001) | 2 |
| `taskhub_signed_approval_signed_at_future` | `signed_at > now + clock_skew` (F-007) | 2 |
| `taskhub_signed_approval_expired` | `expires_at <= now` (F-007) | 2 |
| `taskhub_signed_approval_ttl_exceeded` | `expires_at - signed_at > max_ttl` (F-007) | 2 |
| `taskhub_signed_approval_reason_summary_malformed` | enum-style label 違反 (F-010) | 2 |
| `taskhub_signed_approval_subcommand_not_allowed` | `allowed_subcommands` に不在 | 2 |
| `taskhub_signed_approval_target_host_mismatch` | `--target` と `target_host` 不一致 | 2 |
| `taskhub_signed_approval_drill_kind_subcommands_mismatch` | drill_kind ↔ allowed_subcommands 上限超過 (F-014) | 2 |
| `taskhub_signed_approval_signature_malformed` | base64 / 64-byte 違反 (F-016、署名値の体裁問題) | 2 |
| `taskhub_signed_approval_signature_invalid` | Ed25519 verify 失敗 (署名値の暗号学的問題) | 2 |
| `taskhub_signed_approval_verify_key_missing` | `approval-verify-key.pub` 不在 | 2 |
| `taskhub_signed_approval_verify_key_fingerprint_mismatch` | verify key fingerprint ≠ allowlist (F-009) | 2 |
| `taskhub_signed_approval_verify_key_fingerprint_allowlist_missing` | allowlist file 不在 (R3-F-001: hard fail) | 2 |
| `taskhub_signed_approval_verify_key_fingerprint_allowlist_empty` | allowlist 空 / comment-only (R3-F-001: hard fail) | 2 |
| `taskhub_signed_approval_verify_key_permission_unsafe` | verify key file の owner/mode 不適切 (F-009) | 2 |

## 5. 実装詳細

### 5.1 `scripts/taskhub_signed_approval.py` 構造

詳細 module skeleton (R1 adopt 反映後):

```python
"""Signed approval Ed25519 verification module (SP022-T02 Phase 1).

Provides:
- ApprovalRecord schema (strict、allowlist 方式)
- detect_automation_context(): env matrix + TTY absence
- verify_signed_approval(approval_id, subcommand, target_host=None):
  RFC 8785 strict JCS canonical JSON + Ed25519 signature verify +
  expiration + max_ttl + clock_skew + allowed_subcommands +
  target_host + drill_kind ↔ subcommands 整合 + verify key fingerprint
- require_approval_for_destructive(subcommand, approval_id, from_automation,
  allow_unsigned_manual_skeleton, target_host):
  pre-execution gate (default deny、F-002 adopt)
- emit_audit_event(reason_code, extras): stderr redacted audit-line scaffold
  (allowlist 方式、F-010 adopt)

Reference vector for RFC 8785 canonical encoder is embedded in tests.
"""

from __future__ import annotations
import base64
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

def _taskhub_home() -> Path:
    """R3-F-001 adopt: env override 全削除、`Path.home()` のみ使用。

    `Path.home()` は Unix で `HOME` env を respect (OS-standard user isolation)。
    pytest fixture は `monkeypatch.setenv("HOME", str(tmp_path))` で HOME 全体を
    tmp_path に redirect する。subprocess integration test も同様に `env={"HOME": ...}`
    を `_run_cli` 経由で渡す。

    **REMOVED**: 旧 `TASKHUB_HOME` env override (R3-F-001 adopt: production trust root
    を attacker-controllable にする security bypass の経路を物理削除).
    """
    return Path.home() / ".taskhub"


def _approval_dir() -> Path:
    return _taskhub_home() / "approvals"


def _verify_key_path() -> Path:
    return _taskhub_home() / "keys" / "approval-verify-key.pub"


def _verify_key_fingerprint_allowlist_path() -> Path:
    """R3-F-001 adopt: env override 全削除。repo-internal 固定 path のみ。

    Unit test は `monkeypatch.setattr(taskhub_signed_approval, "_verify_key_fingerprint_allowlist_path", lambda: tmp_path / "allowlist")`
    で override (env-based 経路は production code に置かない)。
    Subprocess integration test は `monkeypatch.setenv("HOME", str(tmp_path))` 経由で
    HOME 全体を redirect し、`Path(__file__).parent.parent / .taskhub/...` は repo 内固定なので
    そのまま使用される。fingerprint allowlist の準備は subprocess test では skip し、
    unit-level で `_load_verify_key_and_fingerprint` を直接 test する。

    **REMOVED**: 旧 `TASKHUB_FINGERPRINT_ALLOWLIST` env override。
    """
    return Path(__file__).parent.parent / ".taskhub" / "approval-verify-key-fingerprints.allowlist"

APPROVAL_ID_REGEX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REASON_SUMMARY_REGEX = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DATETIME_STRICT_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
BASE64_SIG_LEN = 88  # 64 bytes Ed25519 sig × 4/3 base64 = 88 chars with padding

DEFAULT_CLOCK_SKEW = timedelta(minutes=5)
DEFAULT_MAX_TTL = timedelta(hours=48)

AUTOMATION_ENV_VARS = (
    "SYSTEMD_INVOCATION_ID",
    "INVOCATION_ID",
    "JOURNAL_STREAM",
    "CRON_INVOCATION",
    "GITHUB_ACTIONS",
    "CI",
    "BUILD_ID",
    "BUILD_NUMBER",
    "RUN_ID",
    "KUBERNETES_SERVICE_HOST",
    "container",
    "BASH_EXECUTION_STRING",
)

DESTRUCTIVE_SUBCOMMANDS = frozenset({
    "backup", "restore", "migrate", "freeze", "thaw", "age-rotate",
})

DRILL_KIND_ALLOWED_SUBCOMMANDS = {
    "host_migration_mac_vps": frozenset({"backup", "migrate", "restore"}),
    "host_migration_linux_vps": frozenset({"backup", "migrate", "restore"}),
    "host_migration_vps_vps": frozenset({"backup", "migrate", "restore"}),
    "backup_only": frozenset({"backup"}),
    "restore_only": frozenset({"restore"}),
    "age_rotate": frozenset({"age-rotate"}),
    "freeze_only": frozenset({"freeze"}),
    "thaw_only": frozenset({"thaw"}),
}

ReasonCode = Literal[
    "taskhub_signed_approval_verified",
    "taskhub_signed_approval_skipped_non_destructive",
    "taskhub_signed_approval_unsigned_manual_skeleton_allowed",
    "taskhub_signed_approval_destructive_requires_approval",
    "taskhub_signed_approval_automation_detected_without_flag",
    "taskhub_signed_approval_from_automation_requires_approval_id",
    "taskhub_signed_approval_approval_id_malformed",
    "taskhub_signed_approval_record_not_found",
    "taskhub_signed_approval_record_malformed",
    "taskhub_signed_approval_record_id_mismatch",
    "taskhub_signed_approval_datetime_format_invalid",
    "taskhub_signed_approval_signed_at_future",
    "taskhub_signed_approval_expired",
    "taskhub_signed_approval_ttl_exceeded",
    "taskhub_signed_approval_reason_summary_malformed",
    "taskhub_signed_approval_subcommand_not_allowed",
    "taskhub_signed_approval_target_host_mismatch",
    "taskhub_signed_approval_drill_kind_subcommands_mismatch",
    "taskhub_signed_approval_signature_malformed",
    "taskhub_signed_approval_signature_invalid",
    "taskhub_signed_approval_verify_key_missing",
    "taskhub_signed_approval_verify_key_fingerprint_mismatch",
    "taskhub_signed_approval_verify_key_permission_unsafe",
]

AUDIT_PAYLOAD_ALLOWLIST_KEYS = frozenset({
    "reason_code", "subcommand", "approval_id", "decider", "drill_kind",
    "allowed_subcommands", "target_host", "expected_target_host",
    "actual_target_host", "from_automation", "allow_unsigned_manual_skeleton",
    "unsigned_manual_skeleton_used", "automation_env_hits", "tty_absent",
    "timestamp", "audit_marker", "verify_key_fingerprint",
})


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    decider: str
    reason_summary: str
    signed_at_str: str  # 原文字列 (F-001: canonical bytes 用)
    expires_at_str: str
    drill_kind: str
    allowed_subcommands: tuple[str, ...]
    target_host: str | None
    signature_b64: str  # raw base64 string (validate 済)


def detect_automation_context() -> dict[str, object]:
    """env matrix hit + TTY absence (F-003 adopt: 拡張 env list + TTY weak signal)."""
    env_hits = [v for v in AUTOMATION_ENV_VARS if os.environ.get(v)]
    tty_absent = not sys.stdin.isatty() and not sys.stdout.isatty()
    return {"env_hits": sorted(env_hits), "tty_absent": tty_absent}


def _validate_approval_id(approval_id: str) -> bool:
    """F-005 adopt: allowlist + path traversal deny."""
    if not APPROVAL_ID_REGEX.fullmatch(approval_id):
        return False
    # path resolve 後 _approval_dir() 配下確認
    # R2-F-005 adopt: env override 対応 (TASKHUB_HOME 経由)、R2-F-003 adopt
    # 注: Path.resolve() は file 不在でも path normalization する (Python 3.6+ strict=False default)
    expected_root = _approval_dir().resolve()
    expected_path = (_approval_dir() / f"{approval_id}.signed").resolve()
    try:
        expected_path.relative_to(expected_root)
    except ValueError:
        return False
    return True


def _rfc8785_canonical_payload_bytes(record: ApprovalRecord) -> bytes:
    """RFC 8785 strict JCS canonical JSON (F-001 adopt: datetime 原文字列保持).

    Reference vector tested separately in tests/scripts/test_taskhub_signed_approval.py.
    """
    payload = {
        "allowed_subcommands": list(record.allowed_subcommands),
        "approval_id": record.approval_id,
        "decider": record.decider,
        "drill_kind": record.drill_kind,
        "expires_at": record.expires_at_str,  # 原文字列 (parse 後 reconstruct しない)
        "reason_summary": record.reason_summary,
        "signed_at": record.signed_at_str,    # 原文字列
        "target_host": record.target_host,
    }
    # JCS canonical: sorted keys + no whitespace + UTF-8
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _load_approval_record(approval_id: str) -> tuple[ApprovalRecord | None, ReasonCode | None]:
    """Load and parse approval record (F-005 + F-015 + F-001 + F-016 adopt)."""
    if not _validate_approval_id(approval_id):
        return None, "taskhub_signed_approval_approval_id_malformed"

    path = _approval_dir() / f"{approval_id}.signed"
    if not path.exists():
        return None, "taskhub_signed_approval_record_not_found"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None, "taskhub_signed_approval_record_malformed"

    required = {"approval_id", "decider", "reason_summary", "signed_at",
                "expires_at", "drill_kind", "allowed_subcommands", "signature"}
    if not required.issubset(data.keys()):
        return None, "taskhub_signed_approval_record_malformed"

    # F-015 adopt: record.approval_id vs CLI approval_id 一致
    if data["approval_id"] != approval_id:
        return None, "taskhub_signed_approval_record_id_mismatch"

    # F-001 adopt: datetime 文字列 strict
    if not DATETIME_STRICT_REGEX.fullmatch(data["signed_at"]):
        return None, "taskhub_signed_approval_datetime_format_invalid"
    if not DATETIME_STRICT_REGEX.fullmatch(data["expires_at"]):
        return None, "taskhub_signed_approval_datetime_format_invalid"

    # F-010 adopt: reason_summary allowlist
    if not REASON_SUMMARY_REGEX.fullmatch(data["reason_summary"]):
        return None, "taskhub_signed_approval_reason_summary_malformed"

    # F-016 adopt: signature strict base64 + 64-byte
    sig_b64 = data["signature"]
    if not isinstance(sig_b64, str) or len(sig_b64) != BASE64_SIG_LEN:
        return None, "taskhub_signed_approval_signature_malformed"
    try:
        decoded = base64.b64decode(sig_b64, validate=True)
    except (ValueError, base64.binascii.Error):
        return None, "taskhub_signed_approval_signature_malformed"
    if len(decoded) != 64:
        return None, "taskhub_signed_approval_signature_malformed"

    record = ApprovalRecord(
        approval_id=data["approval_id"],
        decider=data["decider"],
        reason_summary=data["reason_summary"],
        signed_at_str=data["signed_at"],
        expires_at_str=data["expires_at"],
        drill_kind=data["drill_kind"],
        allowed_subcommands=tuple(data["allowed_subcommands"]),
        target_host=data.get("target_host"),
        signature_b64=sig_b64,
    )
    return record, None


def _verify_key_permissions(key_path: Path) -> ReasonCode | None:
    """F-009 adopt: owner/mode check."""
    try:
        st = key_path.stat()
    except OSError:
        return "taskhub_signed_approval_verify_key_missing"
    # current user owner check
    if st.st_uid != os.getuid():
        return "taskhub_signed_approval_verify_key_permission_unsafe"
    # writable by group / others は不可
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return "taskhub_signed_approval_verify_key_permission_unsafe"
    return None


def _load_verify_key_and_fingerprint() -> tuple[Ed25519PublicKey | None, str | None, ReasonCode | None]:
    """F-009 adopt: fingerprint allowlist + permission check."""
    verify_key_path = _verify_key_path()  # R2-F-005 adopt: env override 対応
    perm_error = _verify_key_permissions(verify_key_path)
    if perm_error:
        return None, None, perm_error
    raw = verify_key_path.read_bytes()
    key_bytes: bytes | None = None
    if len(raw) == 32:
        key_bytes = raw
    else:
        try:
            decoded = base64.b64decode(raw.strip(), validate=True)
            if len(decoded) == 32:
                key_bytes = decoded
        except (ValueError, base64.binascii.Error):
            pass
    if key_bytes is None:
        return None, None, "taskhub_signed_approval_verify_key_missing"
    fingerprint = sha256(key_bytes).hexdigest()

    # F-009 + R2-F-004 + R3-F-001 adopt: fingerprint allowlist 照合 (hard fail invariant)
    # R3-F-001 adopt: file 不在 / 空 / comment-only も hard fail (production trust root の安全装置)
    # production deployment では allowlist file に少なくとも 1 fingerprint を含める必要あり
    # pytest fixture は monkeypatch.setattr で path を tmp_path に override、tmp allowlist に
    # generated key の fingerprint を書き込む
    allowlist_path = _verify_key_fingerprint_allowlist_path()
    if not allowlist_path.exists():
        return None, fingerprint, "taskhub_signed_approval_verify_key_fingerprint_allowlist_missing"
    allowlist = {
        line.strip()
        for line in allowlist_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    if not allowlist:
        # 空 / comment-only → hard fail (R3-F-001 adopt: 旧 soft warning は security bypass の経路)
        return None, fingerprint, "taskhub_signed_approval_verify_key_fingerprint_allowlist_empty"
    if fingerprint not in allowlist:
        return None, fingerprint, "taskhub_signed_approval_verify_key_fingerprint_mismatch"

    return Ed25519PublicKey.from_public_bytes(key_bytes), fingerprint, None


def verify_signed_approval(
    approval_id: str, subcommand: str, target_host: str | None = None,
    *, clock_skew: timedelta = DEFAULT_CLOCK_SKEW, max_ttl: timedelta = DEFAULT_MAX_TTL,
) -> tuple[bool, ReasonCode, dict[str, object]]:
    """Verify approval record (F-001/F-005/F-007/F-014/F-015/F-016 全 adopt)."""
    extras: dict[str, object] = {"approval_id": approval_id, "subcommand": subcommand}
    record, load_error = _load_approval_record(approval_id)
    if load_error or record is None:
        return False, load_error or "taskhub_signed_approval_record_malformed", extras
    extras["decider"] = record.decider
    extras["drill_kind"] = record.drill_kind

    now = datetime.now(timezone.utc)
    # F-001 adopt: parse 原文字列 (strict format で確実に UTC)
    signed_at = datetime.strptime(record.signed_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    expires_at = datetime.strptime(record.expires_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

    # F-007 adopt: clock skew + max_ttl
    if signed_at > now + clock_skew:
        return False, "taskhub_signed_approval_signed_at_future", extras
    if expires_at <= now:
        return False, "taskhub_signed_approval_expired", extras
    if expires_at - signed_at > max_ttl:
        return False, "taskhub_signed_approval_ttl_exceeded", extras

    if subcommand not in record.allowed_subcommands:
        extras["allowed_subcommands"] = list(record.allowed_subcommands)
        return False, "taskhub_signed_approval_subcommand_not_allowed", extras

    # F-014 adopt: drill_kind ↔ allowed_subcommands 整合
    expected_subs = DRILL_KIND_ALLOWED_SUBCOMMANDS.get(record.drill_kind)
    if expected_subs is None or not set(record.allowed_subcommands).issubset(expected_subs):
        return False, "taskhub_signed_approval_drill_kind_subcommands_mismatch", extras

    if target_host and record.target_host and target_host != record.target_host:
        extras["expected_target_host"] = record.target_host
        extras["actual_target_host"] = target_host
        return False, "taskhub_signed_approval_target_host_mismatch", extras

    verify_key, fingerprint, key_error = _load_verify_key_and_fingerprint()
    if key_error or verify_key is None:
        if fingerprint:
            extras["verify_key_fingerprint"] = fingerprint
        return False, key_error or "taskhub_signed_approval_verify_key_missing", extras
    extras["verify_key_fingerprint"] = fingerprint

    payload = _rfc8785_canonical_payload_bytes(record)
    try:
        signature_bytes = base64.b64decode(record.signature_b64, validate=True)
        verify_key.verify(signature_bytes, payload)
    except InvalidSignature:
        return False, "taskhub_signed_approval_signature_invalid", extras
    return True, "taskhub_signed_approval_verified", extras


def require_approval_for_destructive(
    subcommand: str,
    approval_id: str | None,
    from_automation: bool,
    allow_unsigned_manual_skeleton: bool,
    target_host: str | None = None,
) -> tuple[bool, ReasonCode, dict[str, object]]:
    """Pre-execution gate (F-002 + F-017 adopt: default deny + reason_code 区別)."""
    extras: dict[str, object] = {
        "subcommand": subcommand,
        "from_automation": from_automation,
        "allow_unsigned_manual_skeleton": allow_unsigned_manual_skeleton,
    }
    if subcommand not in DESTRUCTIVE_SUBCOMMANDS:
        return True, "taskhub_signed_approval_skipped_non_destructive", extras

    automation = detect_automation_context()
    extras["automation_env_hits"] = automation["env_hits"]
    extras["tty_absent"] = automation["tty_absent"]
    has_automation_env = bool(automation["env_hits"])

    if has_automation_env:
        if not from_automation:
            return False, "taskhub_signed_approval_automation_detected_without_flag", extras
        if not approval_id:
            return False, "taskhub_signed_approval_from_automation_requires_approval_id", extras
    elif not approval_id:
        if allow_unsigned_manual_skeleton:
            extras["unsigned_manual_skeleton_used"] = True
            return True, "taskhub_signed_approval_unsigned_manual_skeleton_allowed", extras
        return False, "taskhub_signed_approval_destructive_requires_approval", extras

    if approval_id is None:
        # never reached given above branches, but for type safety
        return False, "taskhub_signed_approval_destructive_requires_approval", extras

    allowed, reason, verify_extras = verify_signed_approval(
        approval_id, subcommand, target_host=target_host
    )
    for k, v in verify_extras.items():
        extras.setdefault(k, v)
    return allowed, reason, extras


def emit_audit_event(reason_code: ReasonCode, extras: dict[str, object]) -> None:
    """F-010 adopt: allowlist-only redacted audit-line scaffold (stderr、Phase 1)."""
    payload: dict[str, object] = {
        "reason_code": reason_code,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "audit_marker": "taskhub_signed_approval_gate",
    }
    for k, v in extras.items():
        if k in AUDIT_PAYLOAD_ALLOWLIST_KEYS:
            payload[k] = v
    print(  # noqa: T201
        f"AUDIT taskhub_signed_approval_gate: {json.dumps(payload, sort_keys=True)}",
        file=sys.stderr,
    )
```

### 5.2 `scripts/taskhub_admin.py` への integration

#### 5.2.1 Import path fix (R2-F-001 adopt)

既存テストは `python scripts/taskhub_admin.py` の direct-script 起動を正規に検証 (`tests/scripts/test_taskhub_admin.py:14`)。direct-script では `sys.path[0]` が `scripts/` になるため、`from scripts.taskhub_signed_approval import ...` は `ModuleNotFoundError` で argparse 到達前に落ちる。

dual import で direct-script と console_script 両対応:

```python
# scripts/taskhub_admin.py 冒頭
import sys
from pathlib import Path

# R2-F-001 adopt: dual import (direct-script + console_script 両対応)
try:
    # console_script (uv run taskhub) / pytest from repo root
    from scripts.taskhub_signed_approval import (
        require_approval_for_destructive,
        emit_audit_event,
    )
except ModuleNotFoundError:
    # direct-script (python scripts/taskhub_admin.py) fallback
    # sys.path[0] = scripts/ なので、parent dir (repo root) を append して再 import
    _REPO_ROOT = Path(__file__).resolve().parent.parent
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from scripts.taskhub_signed_approval import (  # noqa: E402
        require_approval_for_destructive,
        emit_audit_event,
    )
```

#### 5.2.2 destructive subcommand gate integration

各 destructive subcommand handler の冒頭に signed approval gate を追加 (default deny):

```python

def _cmd_backup(args: argparse.Namespace) -> int:
    # NEW: signed approval pre-execution gate (T02 Phase 1、default deny)
    allowed, reason, extras = require_approval_for_destructive(
        "backup", args.approval_id, args.from_automation,
        args.allow_unsigned_manual_skeleton,
    )
    emit_audit_event(reason, extras)
    if not allowed:
        print(  # noqa: T201
            f"ERROR: signed approval gate denied (reason={reason})",
            file=sys.stderr,
        )
        return 2
    # ... existing skeleton output ...
```

新引数 (各 destructive subcommand subparser に追加):

```python
sub_backup.add_argument(
    "--approval-id",
    type=str,
    default=None,
    help="signed approval ID (~/.taskhub/approvals/<id>.signed)。automation 実行時は必須。手動実行でも default deny、`--allow-unsigned-manual-skeleton` で skeleton mode のみ escape (Phase 2 で削除予定)",
)
sub_backup.add_argument(
    "--from-automation",
    action="store_true",
    help="automation (cron/systemd/CI) 経由実行を明示。signed approval ID と組合せ必須",
)
sub_backup.add_argument(
    "--allow-unsigned-manual-skeleton",
    action="store_true",
    help="(Phase 1 only、Phase 2 削除予定) skeleton mode の手動実行で approval gate を escape。default deny を override する旨を audit に記録",
)
```

`migrate` subcommand には `target_host=args.target` を `require_approval_for_destructive` に渡す (R2-F-003 adopt: `restore` は Phase 1 で target_host claim 未実装、Phase 2 で `--target-host` argument 追加判断)。`migrate` 内で CLI `--target` と record `target_host` 両方 non-empty + `.strip()` 後 exact match 検査 (`verify_signed_approval` 内で実施)。

#### 5.2.3 既存テスト更新 (R2-F-002 adopt)

`tests/scripts/test_taskhub_admin.py` の既存 destructive skeleton 回帰 fixture を以下 pattern で更新:

| 既存 fixture (現状: approval なしで exit 1 期待) | 更新後 | 新 fixture |
|---|---|---|
| `test_backup_skeleton_exits_1` (`backup --output ...`) | `--allow-unsigned-manual-skeleton` 追加で exit 1 期待維持 | `test_backup_without_approval_denies_by_default` で exit 2 + reason_code 期待 |
| `test_restore_skeleton_exits_1` | 同上 | 同 pattern |
| `test_migrate_skeleton_exits_1` | 同上 | 同 pattern |
| `test_freeze_skeleton_exits_1` | 同上 | 同 pattern |
| `test_thaw_skeleton_exits_1` | 同上 | 同 pattern |
| `test_age_rotate_skeleton_exits_1` | 同上 | 同 pattern |
| `test_init_skeleton_exits_1` (non-destructive) | 無変更 (gate skip) | - |
| `test_status_skeleton_exits_1` (non-destructive) | 無変更 (gate skip) | - |
| `test_verify_skeleton_exits_1` (non-destructive) | 無変更 (gate skip) | - |
| `test_active_registry_skeleton_exits_1` (non-destructive) | 無変更 (gate skip) | - |

`_run_cli` helper も `env` 引数追加で `TASKHUB_HOME=tmp_path/.taskhub` を渡せるよう更新 (R2-F-005 adopt)。

### 5.3 `tests/scripts/test_taskhub_signed_approval.py` 構造 (positive 5 + negative 18 = 23 fixture)

**Positive (5):**
- `test_verify_valid_signature_allows_subcommand`
- `test_verify_target_host_match_allows_migrate`
- `test_detect_automation_returns_empty_in_interactive`
- `test_require_approval_non_destructive_subcommand_always_allowed` (例: `status`, `verify`)
- `test_rfc8785_canonical_encoder_reference_vector_match` (F-001 adopt: reference vector で encoder の deterministic 性 verify)

**Negative (18):**
- `test_verify_approval_id_path_traversal_denied` (`../`) (F-005)
- `test_verify_approval_id_allowlist_violation_denied` (special chars) (F-005)
- `test_verify_approval_id_too_long_denied` (>128 chars) (F-005)
- `test_verify_record_not_found`
- `test_verify_record_malformed` (JSON parse error)
- `test_verify_record_id_mismatch` (file 内 approval_id ≠ CLI 引数) (F-015)
- `test_verify_datetime_format_invalid` (`+00:00` instead of `Z`) (F-001)
- `test_verify_signed_at_future` (clock skew 超過) (F-007)
- `test_verify_expired` (`expires_at` 過去)
- `test_verify_ttl_exceeded` (`expires_at - signed_at > 48h`) (F-007)
- `test_verify_reason_summary_malformed` (control chars / too long) (F-010)
- `test_verify_subcommand_not_allowed`
- `test_verify_target_host_mismatch_migrate`
- `test_verify_drill_kind_subcommands_mismatch` (F-014)
- `test_verify_signature_malformed` (base64 padding / 64-byte fail) (F-016)
- `test_verify_signature_invalid` (forged signature)
- `test_verify_key_missing`
- `test_verify_key_permission_unsafe` (world-writable) (F-009)
- `test_verify_key_fingerprint_mismatch` (allowlist で未登録 fingerprint) (F-009)
- `test_automation_detected_without_flag_denies`
- `test_from_automation_without_approval_id_denies`
- `test_destructive_manual_without_approval_denies_by_default` (F-002)
- `test_destructive_manual_with_allow_unsigned_skeleton_passes_with_audit_marker` (F-002 escape)

(注: 上 23 = positive 5 + negative 18、実装時 fixture 数で微調整可)

### 5.4 `tests/scripts/test_taskhub_admin_security.py` 構造 (8 fixture)

subprocess 経由で `taskhub_admin.py` 全 destructive subcommand に gate integration verify:

- `test_backup_with_signed_approval_proceeds` (signed approval valid → skeleton exit 1)
- `test_backup_manual_without_approval_denies_by_default` (F-002 default deny → exit 2)
- `test_backup_manual_with_allow_unsigned_skeleton_proceeds` (F-002 escape → skeleton exit 1 + audit marker `unsigned_manual_skeleton_used=true`)
- `test_backup_with_automation_env_without_flag_denies` (cron env + `--from-automation` なし → exit 2)
- `test_migrate_with_target_host_mismatch_denies` (signed approval `target_host=vps` だが `--target=linux` → exit 2)
- `test_status_no_approval_required` (non-destructive、approval gate skip → skeleton exit 1)
- `test_audit_event_payload_allowlist_enforced` (F-010 adopt: payload に `reason` raw / raw signature / signing key が含まれないこと、`automation_env_hits` は var names のみ)
- `test_verify_key_fingerprint_match_required` (F-009 adopt: allowlist 不一致 → exit 2)

### 5.5 RFC 8785 reference vector (テスト同梱、F-001 adopt)

`tests/scripts/test_taskhub_signed_approval.py` 内で:

```python
REFERENCE_RECORD = ApprovalRecord(
    approval_id="drill-2026-07-01-abc123de",
    decider="t-ohga",
    reason_summary="half-yearly-drill",
    signed_at_str="2026-06-30T15:00:00Z",
    expires_at_str="2026-07-02T15:00:00Z",
    drill_kind="host_migration_mac_vps",
    allowed_subcommands=("backup", "migrate", "restore"),
    target_host="t-ohga-vps",
    signature_b64="A" * 88,  # placeholder for canonical bytes test only
)

REFERENCE_CANONICAL_BYTES = (
    b'{"allowed_subcommands":["backup","migrate","restore"],'
    b'"approval_id":"drill-2026-07-01-abc123de","decider":"t-ohga",'
    b'"drill_kind":"host_migration_mac_vps",'
    b'"expires_at":"2026-07-02T15:00:00Z","reason_summary":"half-yearly-drill",'
    b'"signed_at":"2026-06-30T15:00:00Z","target_host":"t-ohga-vps"}'
)

def test_rfc8785_canonical_encoder_reference_vector_match():
    actual = _rfc8785_canonical_payload_bytes(REFERENCE_RECORD)
    assert actual == REFERENCE_CANONICAL_BYTES
```

## 6. 検証手順

```bash
# 1. dependency install + lockfile update
uv lock        # F-013 adopt: lockfile 更新
uv sync --locked  # 再現性 verify

# 2. module syntax check
uv run python -m py_compile scripts/taskhub_signed_approval.py
uv run python -m py_compile scripts/taskhub_admin.py

# 3. CLI smoke (skeleton mode、approval gate なしの non-destructive subcommand)
uv run taskhub status  # gate skip、既存 skeleton 維持

# 4. CLI smoke (destructive subcommand、default deny 検証)
uv run taskhub backup --output /tmp/test.tar.age
# expected: exit 2 + reason=taskhub_signed_approval_destructive_requires_approval
uv run taskhub backup --output /tmp/test.tar.age --allow-unsigned-manual-skeleton
# expected: skeleton exit 1 + AUDIT marker unsigned_manual_skeleton_used=true

# 5. pytest 新規 fixture (23 + 8 = 31)
uv run pytest tests/scripts/test_taskhub_signed_approval.py -v
uv run pytest tests/scripts/test_taskhub_admin_security.py -v

# 6. regression: T01/T03/T04/T07 既存 fixture
uv run pytest tests/deploy/ tests/scripts/ -q
uv run ruff check backend tests scripts
uv run mypy backend
```

## 7. レビュー観点 (codex-plan-review trigger 必須)

mandatory Codex gate (`.claude/rules/codex-usage-policy.md §14.1`、CRITICAL invariant 直結 = SecretBroker boundary + ADR Gate Criteria #6 Secrets):
- `codex-plan-review R1-R3` minimum + 採否判定

### 7.1 期待される review focus (R2-R3)

1. RFC 8785 reference vector の正確性 (F-001 adopt)
2. default deny invariant の Phase 2 carry-over 明示 (F-002 adopt)
3. automation env matrix の cover (F-003 adopt)、`allow-unsigned-manual-skeleton` の Phase 2 削除 trigger
4. SecretBroker integration carry-over 明示と Phase 1 stderr scaffold scope (F-004 adopt)
5. approval_id path traversal 防御 (F-005 adopt)
6. SOP §7 normative 範囲分割 (F-006 adopt)
7. clock skew + max_ttl 値の妥当性 (F-007 adopt)
8. subcommand 属性分類表の完全性 (F-008 + F-012 adopt)
9. verify key fingerprint allowlist file の管理経路 (F-009 adopt)
10. audit payload allowlist 完全性 (F-010 adopt: raw `reason` 出さない)
11. cryptography lockfile + license 影響 (F-013 adopt)
12. drill_kind ↔ allowed_subcommands 整合 (F-014 adopt)
13. record.approval_id mismatch test 完全性 (F-015 adopt)
14. signature strict base64 + 64-byte test (F-016 adopt)
15. skip vs verified reason_code 区別 (F-017 adopt)
16. Rollback Tier 2 escape env 削除済確認 (F-018 adopt)

## 8. リスク / Rollback

| リスク | 影響 | mitigation |
|---|---|---|
| RFC 8785 canonical encoder の cross-platform deterministic 性 | signature_invalid 偽陽性 | reference vector pytest fixture で deterministic verify、複数 platform で run |
| `--allow-unsigned-manual-skeleton` の Phase 2 削除忘れ | security boundary 弱化 | Phase 2 plan の DoD に「escape flag 削除 + grep で残存 reference 0」を必須化、本 plan §3.2 で carry-over 明示 |
| automation env detection 不足 (new CI tools) | automation 経由 bypass | F-003 で env matrix 拡張、Phase 2 で process tree-based detection を ADR Gate で判断、本 plan §3.2 carry-over 明示 |
| verify key fingerprint allowlist 改ざん | local user 任意 approval 通過 | F-009 adopt: allowlist file は repo 内 commit + Phase 2 で `chmod 644 + git diff` 検出を CI gate 化判断 |
| audit payload に `reason` raw が混入 | secret / 制御文字 leakage | F-010 adopt: allowlist 方式 enforce、test で `reason` key 不在 verify |
| `expires_at - signed_at > 48h` の運用上不便 | 半年 drill の場合に approval 取り直し | F-007 adopt: 48h は drill SOP §4 の half-yearly drill 想定 + 2 day buffer、Phase 2 で長期 ledger と組合せ調整 |
| cryptography lib のメジャー bump | breaking change risk | `cryptography>=42,<43` 固定、Phase 2 で `<44` 緩和判断、CI で `uv sync --locked` 強制 |
| `init` を non-destructive 扱いした判定誤り | Phase 2 で実 I/O 配置時に re-classify 必要 | 本 plan §4.4 subcommand 属性表に Phase 2+ re-classify trigger 明示、Phase 2 plan §3.1 で再評価 |
| Codex review が delayed | merge 遅延 | 30 min max polling、admin merge bypass (CI billing failure 継続) |

### Rollback (3 階層、F-018 adopt: Tier 2 escape env 削除版)

- **Tier 1 (pre-merge local)**: `git restore` 対象 file
- **Tier 2 (post-merge、F-018 adopt: env-based disable 削除)**: revert commit + SP-022 `## Review` に rollback 記録、`config/taskhub_signed_approval_disabled` flag file を実装する場合は別 PR で signed/audited break-glass として ADR Gate で設計判断 (本 PR で env-based disable は実装しない)
- **Tier 3 (break-glass)**: PR revert + ADR で security boundary 緊急 disable 経路 (audit + 24h 期限) を新規設計、本 plan §1 carry-over 明示

## 9. commit 戦略

single commit。SP022-T01/T03/T04/T07 pattern 踏襲。

## 10. PR workflow

SP022-T01/T03/T04/T07 pattern 踏襲: plan draft → codex-plan-review R1-R3 → 実装 → pre-commit verify → commit/push/PR → Codex auto-review polling + multi-round adopt + admin merge bypass。

## 11. DoD (R1 18 findings 全 adopt 反映後)

### 11.1 必須 DoD

- [ ] `scripts/taskhub_signed_approval.py` 新規作成 (RFC 8785 canonical + Ed25519 verify + automation detection 拡張 + audit-line scaffold、§5.1 構造)
- [ ] `scripts/taskhub_admin.py` の destructive subcommand 6 件 (backup / restore / migrate / freeze / thaw / age-rotate) に signed approval gate integrate、`--approval-id` + `--from-automation` + `--allow-unsigned-manual-skeleton` 引数追加 (F-002 adopt: default deny + skeleton escape)
- [ ] `tests/scripts/test_taskhub_signed_approval.py` 23 fixture 全 PASS (positive 5 + negative 18、RFC 8785 reference vector 含む)
- [ ] `tests/scripts/test_taskhub_admin_security.py` 8 fixture 全 PASS
- [ ] `pyproject.toml` に `cryptography>=42,<43` 追加、`uv lock` 更新 + `uv sync --locked` で再現性確認 (F-013 adopt)
- [ ] `.taskhub/approval-verify-key-fingerprints.allowlist` placeholder 作成 (空 file または `# placeholder for verify key SHA-256 fingerprints` comment line のみ、F-009 adopt)
- [ ] `docs/deploy/half-yearly-drill-sop.md` §7 を **節単位で分割** (approval record schema + Phase 1 pre-execution gate は normative、実 I/O / SecretBroker / rotation / split-brain marker は planned carry-over) (F-006 adopt)
- [ ] audit event payload に **raw signing key / raw signature bytes / raw `reason`** が含まれない (F-010 adopt: `test_audit_event_payload_allowlist_enforced`)
- [ ] non-destructive subcommand (status / verify / init / active-registry) は approval gate skip、既存 skeleton 動作維持、`taskhub_signed_approval_skipped_non_destructive` reason_code (F-017 adopt)
- [ ] approval_id allowlist + path traversal deny (F-005 adopt: `test_verify_approval_id_path_traversal_denied`)
- [ ] record.approval_id vs CLI 引数 一致 verify (F-015 adopt: `test_verify_record_id_mismatch`)
- [ ] signature strict base64 + 64-byte (F-016 adopt: `test_verify_signature_malformed`)
- [ ] drill_kind ↔ allowed_subcommands 整合 (F-014 adopt)
- [ ] verify key fingerprint allowlist + owner/mode permission check (F-009 adopt)
- [ ] `--allow-unsigned-manual-skeleton` escape は audit に `unsigned_manual_skeleton_used=true` marker 必須
- [ ] codex-plan-review R{N} findings are triaged adopt/defer/reject, and all adopted CRITICAL/HIGH are resolved before implementation
- [ ] **R2-F-001 adopt**: dual import (direct-script + console_script 両対応) で `scripts/taskhub_admin.py` 既存 direct-script 起動を破壊しない
- [ ] **R2-F-002 adopt**: `tests/scripts/test_taskhub_admin.py` の既存 destructive 6 fixture を `--allow-unsigned-manual-skeleton` 付与で exit 1 期待維持 + approval なし default deny の新 fixture 6 件追加 + non-destructive 4 fixture 無変更
- [ ] **R2-F-003 adopt**: `migrate` claim は CLI `--target` と record `target_host` 両方 non-empty + `.strip()` 後 exact match、`restore` の target_host claim は Phase 1 で未実装 (Phase 2 で `--target-host` 引数追加判断)
- [ ] **R2-F-004 adopt**: positive test fixture では生成した verify key の SHA-256 fingerprint を `tmp_path` 内 allowlist に書き込む、production は file 不在 / 空 / comment-only を soft warning として扱う (Phase 2 で hard fail 化判断)
- [ ] **R2-F-005 + R3-F-001 adopt**: env-based trust root override **全削除** (旧 `TASKHUB_HOME` / `TASKHUB_FINGERPRINT_ALLOWLIST` env は production code から物理削除、security bypass 経路を遮断)。pytest fixture は `monkeypatch.setenv("HOME", str(tmp_path))` で HOME 全体 redirect (OS-standard) + `monkeypatch.setattr(taskhub_signed_approval, "_verify_key_fingerprint_allowlist_path", lambda: ...)` で repo-internal path override
- [ ] **R3-F-001 adopt**: fingerprint allowlist **hard fail** invariant (file 不在 / 空 / comment-only も全て deny)。新 reason_code 2 種: `taskhub_signed_approval_verify_key_fingerprint_allowlist_missing` / `taskhub_signed_approval_verify_key_fingerprint_allowlist_empty`
- [ ] regression: tests/deploy/ + tests/scripts/ 全 PASS (T01/T03/T04 fixture 全 PASS)、ruff/mypy clean

### 11.2 任意 DoD (回帰確認)

- [ ] PR Codex auto-review R{N} clean (採否判定 3 分類 + multi-round polish)
- [ ] T03 SOP §7 normative 昇格 PR (本 PR 内 docs/deploy/half-yearly-drill-sop.md update)

## 12. 関連

- ADR-00021 §3-§7 (taskhub admin CLI spec、本 plan の上位 spec)
- ADR-00021 §11.1 PG-F-015 (`--include-secrets` → `--include-sops-env` rename invariant、本 Phase 1 では touch しない、Phase 2 で考慮)
- ADR-00021 §11.2 / §14.1 / §14.2 (freeze / age-safety / mac-preflight、Phase 4 / Phase 3 で実装)
- T03 SOP `docs/deploy/half-yearly-drill-sop.md` §7 (T02 planned contract、本 Phase 1 で approval record schema + pre-execution gate 部分を normative 化)
- `.claude/rules/secretbroker-boundary.md` (raw secret leakage 0 invariant、本 Phase 1 の audit event payload allowlist に適用)
- `.claude/rules/server-owned-boundary.md` §3 (caller-supplied 禁止経路、本 Phase 1 の approval record verify は server-owned fingerprint 構造を継承)
- `.claude/reference/task-planning-matrix.md` (本 plan の 🟥 heavy + phase 分割 marking 根拠)
- SP022-T01 PR #70 / SP022-T03 PR #71 / SP022-T04 PR #72 / SP022-T07 PR #73 / planning matrix PR #74 (確立 pattern)
- Sprint 12 batch 7 `scripts/taskhub_admin.py` (本 Phase 1 が integrate する skeleton)
- RFC 8785 (JSON Canonicalization Scheme): https://datatracker.ietf.org/doc/html/rfc8785

## 13. R1+R2+R3 plan-review findings adoption log

R1 (2026-05-20, codex-plan-review): 18 findings, **全件 adopt** (HIGH×5 / MEDIUM×8 / LOW×5).
R2 (2026-05-20, codex-plan-review Phase B 実装可能性): 5 HIGH findings, **全件 adopt** (integration / testing / security 実装可能性 fix)。
R3 (2026-05-20, codex-plan-review CRITICAL final gate): 1 CRITICAL finding, **adopt** (F-R3-001 env-based trust root override security bypass、env override 全削除 + fingerprint allowlist hard fail)。**Readiness Gate READY** (CRITICAL=0 残存、累計 24 findings 100% adopt)。

| ID | severity | category | summary | adopted location |
|---|---|---|---|---|
| F-001 | HIGH | planning | RFC 8785 strict canonical + datetime 原文字列保持 + reference vector | §4.1.3, §4.1.8, §5.1 (_rfc8785_canonical_payload_bytes), §5.5 (reference vector), §11.1 DoD |
| F-002 | HIGH | risk | destructive manual exec 含め default deny、`--allow-unsigned-manual-skeleton` skeleton-only escape (Phase 2 削除予定) | §1, §3.2, §4.5, §5.1 (require_approval_for_destructive), §11.1 DoD |
| F-003 | HIGH | missing | automation env matrix 拡張 + TTY absence + container hints | §4.3 (env matrix), §5.1 (AUTOMATION_ENV_VARS), §11.1 DoD |
| F-004 | HIGH | inconsistency | SecretBroker integration を Phase 2 carry-over に明示、Phase 1 は redacted audit-line scaffold (stderr-only) | §1, §3.2, §4.6, §11.1 DoD |
| F-005 | HIGH | missing | approval_id allowlist + path traversal deny + APPROVAL_DIR 配下 verify | §4.1.1, §5.1 (_validate_approval_id), §5.3 negative tests, §11.1 DoD |
| F-006 | MEDIUM | inconsistency | SOP §7 normative 範囲を分割 (schema + gate は normative、実 I/O / SecretBroker / rotation は planned carry-over) | §3.1 #7, §11.1 DoD |
| F-007 | MEDIUM | missing | clock skew + max_ttl + signed_at future | §4.1.4, §5.1 (verify_signed_approval), §5.3 negative tests, §11.1 DoD |
| F-008 | MEDIUM | ambiguity | subcommand 属性分類表 (claim requirement 明示) | §4.4, §11.1 DoD |
| F-009 | MEDIUM | risk | verify key fingerprint allowlist + owner/mode permission check | §4.2, §5.1 (_verify_key_permissions + _load_verify_key_and_fingerprint), §11.1 DoD |
| F-010 | MEDIUM | missing | audit payload allowlist 方式 + raw `reason` 出さない (`reason_summary` enum-style label) | §4.1.5, §4.6, §5.1 (AUDIT_PAYLOAD_ALLOWLIST_KEYS), §11.1 DoD |
| F-011 | MEDIUM | inconsistency | env list §4.3 と §5.1 整合 (DBUS_SESSION_BUS_ADDRESS 除外明示) | §4.3 (env matrix 採用/非採用表), §5.1 |
| F-012 | MEDIUM | missing | subcommand 属性 (writes_state / reads_secret / remote_access / service_disruption) 分類 + Phase 2+ re-classify trigger | §4.4 (subcommand claim 表), §11.1 DoD |
| F-013 | MEDIUM | missing | `uv lock` 更新 + `uv sync --locked` 検証順 + license/wheel/Python version 影響 | §3.1 #6, §6 検証手順, §11.1 DoD |
| F-014 | LOW | ambiguity | drill_kind ↔ allowed_subcommands 上限 table | §4.1.7, §5.1 (DRILL_KIND_ALLOWED_SUBCOMMANDS), §5.3 negative tests, §11.1 DoD |
| F-015 | LOW | missing | record.approval_id vs CLI approval_id 一致 verify | §4.1.2, §5.1 (_load_approval_record), §5.3 negative tests, §11.1 DoD |
| F-016 | LOW | missing | signature strict base64 + 64-byte 固定長 + `record_malformed` vs `signature_invalid` 区別 | §4.1.6, §5.1 (_load_approval_record), §5.3 negative tests, §11.1 DoD |
| F-017 | LOW | ambiguity | non-destructive skip と verified を別 reason_code | §4.5, §5.1 (require_approval_for_destructive), §11.1 DoD |
| F-018 | LOW | planning | Rollback Tier 2 escape env 削除 (revert + config-managed patch のみ) | §8 (Rollback Tier 2), §11.1 DoD |
| R2-F-001 | HIGH | integration | direct-script 起動 (sys.path[0]=scripts/) で `from scripts.taskhub_signed_approval` が ModuleNotFoundError、dual import (try package + fallback sys.path insert) で両対応 | §5.2.1 (Import path fix), §11.1 DoD |
| R2-F-002 | HIGH | testing | 既存 `tests/scripts/test_taskhub_admin.py` destructive skeleton fixture が approval なしで exit 1 期待していたため default deny と衝突、`--allow-unsigned-manual-skeleton` 付与で exit 1 維持 + approval なし default deny の新 fixture 追加 + non-destructive 既存 fixture 維持 | §3.1 #8 (must_ship), §5.2.3 (既存テスト更新), §11.1 DoD |
| R2-F-003 | HIGH | security | `migrate` claim は CLI `--target` と record `target_host` 両方 non-empty 必須 + exact match (null/empty fallback bypass 防止)、`restore` parser に `--target` 不在のため Phase 1 では target_host claim 未実装 (Phase 2 で `--target-host` 引数追加判断) | §3.2 (restore claim 未実装明示), §4.4 (subcommand 属性表 restore/migrate), §4.4.1 (migrate target_host 厳密化), §11.1 DoD |
| R2-F-004 | HIGH | testing | placeholder allowlist だと positive test の verify key fingerprint check で常に hard fail、positive fixture では tmp/repo-local allowlist に generated key の fingerprint を書き込む、production は file 不在/空/comment-only を soft warning として扱う | §4.2, §5.1 (allowlist 照合 logic + soft warning), §11.1 DoD |
| R2-F-005 | HIGH | testing | `APPROVAL_DIR` / `VERIFY_KEY_PATH` が import-time 定数で pytest が tmp_path 経由で override 不可、accessor pattern (`_taskhub_home()` / `_approval_dir()` / `_verify_key_path()`) + `_run_cli` helper に env 引数追加 (R3-F-001 で env override 削除に修正、HOME env 経由のみに統一) | §5.1 (accessor functions), §5.2.3 (`_run_cli` env arg), §11.1 DoD |
| R3-F-001 | CRITICAL | security | env-based trust root override (`TASKHUB_HOME` / `TASKHUB_FINGERPRINT_ALLOWLIST`) が production code に残ると attacker-controllable な path で gate bypass、env override 全削除 + `Path.home()` (HOME env、OS-standard) + pytest monkeypatch.setattr + fingerprint allowlist hard fail (file 不在 / 空 / comment-only も全 deny) | §5.1 (env override 削除), §5.1 (fingerprint allowlist hard fail), §4.7 reason_code 2 種追加, §11.1 DoD |
