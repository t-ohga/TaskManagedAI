# SP022-T02 Phase 3 + T08 batch 3: restore real I/O orchestration

## 1. 目的

`taskhub restore --input <path>.tar.age --approval-id <id>` の **skeleton から real I/O** への昇格。SP022-T02 Phase 2 (PR #77、backup real I/O、df4ee63) の対称形を実装する。

R1 17 findings 100% adopt の結果、scope を当初 plan より拡大 (F-001 / F-002 CRITICAL adopt):

1. **age decrypt** (age 秘密鍵で `.tar.age` を復号、temp `.tar` へ)
2. **archive sha256 verify** (F-006 adopt): meta.json 内に backup 側で書き込んだ archive sha256 と一致 verify、claim の `archive_sha256` と整合
3. **tar extraction with allowlist enforcement + size/member limits** (F-011 adopt)
4. **meta.json + checksums.txt verify** (sha256 全 file 再計算 + deterministic compare、version-aware forward compat F-012 adopt)
5. **service stop orchestration** (F-001 + F-008 adopt): Docker compose `stop postgres redis api worker` を pg_restore 直前に実行 (split-brain 防止)
6. **pre-restore snapshot 作成** (F-002 adopt): `data/_pre-restore-<ts>/` に target dir move + DB は `pg_dump --format=custom` で同 dir に snapshot
7. **pg_restore subprocess** (`--single-transaction` + `--clean --if-exists`、F-013 adopt): PGPASSFILE 必須
8. **Redis RDB ファイル placement** (F-008 adopt): `dump.rdb` を Redis data dir に置く + Redis 再 start で load 反映
9. **artifacts placement** (allowlist 再 verify した上で artifacts dir 配置)
10. **alembic head verify** (F-014 adopt): restore 後 DB の `alembic_version` table を読み、`meta.json.alembic_head` と一致 verify (local code head は別 verify、SOP に明記)
11. **service start orchestration** (F-008 adopt): `docker compose up -d postgres redis api worker` + healthcheck PASS verify
12. **失敗時 rollback** (F-002 adopt): DB は pre-restore `pg_dump` を re-restore、Redis dump.rdb は pre-restore snapshot から復旧、artifacts dir は move-back
13. **cleanup with try-finally** (F-010 adopt): 復号済 tar / 抽出 temp dir / pre-restore snapshot は明示 retention policy で管理
14. **`RestoreApprovalClaim` 拡張 signed approval** (F-004 + F-006 adopt): `input_path` / `archive_sha256` / `target_pg_db` / `target_pg_host_port` / `target_redis_host_port` / `target_artifacts_dir` / `expected_postgres_major_version` / `expected_alembic_head` / `age_public_key_fingerprint` を全 verify

## 2. 対象外 (scope out / carry-over)

R1 adopt 後 carry-over:

- **split-brain remote detection** (T08 batch 3 sub-batch carry-over): 旧 host service down verify (`taskhub status --remote`) は次 batch、本 batch は local service stop のみ
- **--rollback <pre-restore-ts> mode 単独 invocation** の実 I/O: 本 batch では skeleton 維持 (Phase 4 carry-over)、`--input` の失敗時自動 rollback のみ本 batch 対象
- **age 秘密鍵の SecretBroker integration**: P0 manual 運搬で OK、`secret_ref` 経由 resolve は T08 batch 5 (BL-0149) carry-over
- **actual pg_restore / age / redis-cli tool 実行 integration test**: PR #77 同様、mock-based testing で 100% cover、real tool execution は SP022-T09 drill phase carry-over
- **Pure signed_approval_core.py 抽出** (T08 batch 1 R2-F-001 carry-over): 本 batch では touch しない
- **`pg_dump` pre-restore snapshot tool execution** (F-002 部分 carry-over): mock で flow verify、actual `pg_dump` 実行は SP022-T09 carry-over

## 3. 設計判断

### 3.1 RestoreApprovalClaim 構造 (F-004 + F-006 adopt 反映)

`BackupApprovalClaim` の対称形だが、**cross-target attack 防止のため target deployment identity を厳格化**:

| field | 型 | 内容 |
|---|---|---|
| `input_path` | str (absolute normpath) | restore 対象 `.tar.age` の絶対パス |
| `archive_sha256` | str (hex 64) | `.tar.age` 全体の sha256 (caller が approval 取得時計算、CLI が起動時再計算で一致 verify、tar 内 checksums.txt 改竄 + meta.json 改竄 同時攻撃を防御) |
| `age_public_key_fingerprint` | str (sha256 hex) | restore archive を作った backup 側の age public key fingerprint (decrypt は private key で行うが、backup 時 fingerprint と一致 verify) |
| `target_pg_dsn_components` | dict | `{host, port, db, user}` の 4 tuple (target identity strict、cross-DB attack 防御) |
| `target_redis_endpoint` | str | `host:port` (target identity strict) |
| `target_artifacts_dir` | str (absolute normpath) | artifacts 配置先 host path (target identity strict) |
| `target_artifacts_container_path` | str | artifacts container destination path (例: `/app/data/artifacts`、R23-F-001 fix: api/worker bind mount destination 固定) |
| `target_compose_project_name` | str | docker compose project name (R8-F-001 fix: ambient cwd / `COMPOSE_PROJECT_NAME` env 依存防止、別 deployment 操作経路の遮断) |
| `target_compose_file_path` | str (absolute normpath) | docker-compose.yml 絶対 path (R8-F-001 fix: cwd-relative resolve を回避、approval signed 値) |
| `expected_postgres_major_version` | str | meta.json.postgres_version の major (e.g., `"17"`)、minor/patch 差は warning (F-005 adopt) |
| `expected_alembic_head` | str | restore 後 DB の alembic head 期待値 (F-014 adopt) |
| `skip_service_stop` | bool | **R3-F-001 CRITICAL fix**: `--input` (real I/O) 経路では `skip_service_stop=true` を **物理 deny** (no-op で不完全 restore が成功扱いされる事故防止)。warning only path は削除、skeleton 経路は別経由 |

approval flow:
1. CLI が `--approval-id` 経由で record file から `restore_claim` 抽出
2. CLI 起動時に `.tar.age` の sha256 を再計算し、`archive_sha256` と一致 verify
3. `verify_signed_approval(..., restore_claim=cli_restore_claim)` で **全 field 完全一致** verify
4. record (Phase 1) に `restore_claim` 不在 → `restore_claim_required` deny
5. CLI が `--allow-unsigned-manual-skeleton` を指定 → restore subcommand では物理 deny (F-PR77-001 backup と同じ pattern)

### 3.2 ReasonCode 追加 (3 件 + restore orchestration 専用 17 件、F-008 adopt)

`scripts/taskhub_signed_approval.py:133-162`:

```python
"taskhub_signed_approval_restore_claim_required",
"taskhub_signed_approval_restore_claim_mismatch",
"taskhub_signed_approval_restore_allow_unsigned_skeleton_rejected",
```

新規 `scripts/taskhub_restore_orchestrator.py` の reason_code (F-008 adopt で `redis_load_skipped` を `redis_service_restart_failed` に置換):

| reason_code | severity | 内容 |
|---|---|---|
| `restore_input_path_invalid` | usage | `.tar.age` 拡張子チェーン違反 / file 存在 verify 失敗 / symlink reject |
| `restore_input_archive_sha256_mismatch` | usage | CLI 起動時 sha256 と claim.archive_sha256 不一致 (F-006 adopt) |
| `restore_pgpassfile_required` | usage | PGPASSFILE 必須 (F-PR77-003 invariant 継承) |
| `restore_age_identity_path_invalid` | usage | age private key path file 存在 / 0o400 or 0o600 verify 失敗 / symlink reject (F-003 adopt) |
| `restore_age_decrypt_failed` | runtime | age 復号失敗 (private key 不一致 / file 改竄) |
| `restore_archive_size_exceeded` | runtime | tar member size / total size / count 上限超過 (F-011 adopt) |
| `restore_archive_allowlist_violation` | runtime | tar 内に id_rsa / age-secret-key / non-allowlist 含む |
| `restore_meta_json_invalid` | runtime | meta.json schema 不正 / 必須 key 不在 / version 範囲外 (F-012 adopt) |
| `restore_checksums_mismatch` | runtime | checksums.txt と実 file の sha256 不一致 |
| `restore_postgres_major_version_mismatch` | runtime | claim.expected_postgres_major_version と target host pg version major 不一致 (F-005 adopt) |
| `restore_alembic_head_mismatch` | runtime | restore 後 DB alembic_version table と claim.expected_alembic_head 不一致 (F-014 adopt) |
| `restore_service_stop_failed` | runtime | docker compose stop 失敗 (F-001 adopt) |
| `restore_pre_restore_pg_dump_failed` | runtime | pre-restore DB snapshot 取得失敗 (F-002 adopt) |
| `restore_pg_restore_failed` | runtime | pg_restore subprocess non-zero exit (--single-transaction 内なので DB は automatic rollback、F-013 adopt) |
| `restore_redis_data_placement_failed` | runtime | dump.rdb file copy 失敗 (permission / disk full) |
| `restore_service_start_failed` | runtime | docker compose up 失敗 (F-008 adopt) |
| `restore_healthcheck_failed` | runtime | service start 後の healthcheck timeout (F-008 adopt) |
| `restore_rollback_attempted` | warning | restore 失敗 → rollback で `_pre-restore-<ts>/` から復旧した (operational warning) |
| `restore_rollback_failed` | runtime | rollback 自体も失敗 (manual intervention 必要) |
| `restore_completed` | success | 全 step PASS |
| `restore_target_data_dir_in_use_without_overwrite` | usage | target artifacts dir が空でなく `--overwrite` 未指定 (F-009 adopt) |

### 3.3 tar extraction security (CVE-2007-4559 + DoS 防止、F-007 + F-011 adopt)

#### Python 3.12 requirement gate (F-007 + R2-F-008 adopt)

- 本 batch 着手前に `pyproject.toml` の `requires-python = ">=3.12,<3.13"` (現行値) を verify
- CI matrix は **3.12 のみ** (R2-F-008 adopt: pyproject.toml `<3.13` 上限と整合、3.13 言及削除)
- runtime check: `scripts/taskhub_restore_orchestrator.py:_assert_python_version()` で `sys.version_info >= (3, 12)` を check、未満は **import time fail** (graceful skip 禁止)
- 将来 3.13 サポートは別 PR で `pyproject.toml` 上限を `<3.14` に変更 + CI matrix 拡張 (本 batch scope 外)

#### extraction policy (R20-F-002 fix: symlink/hardlink を **member iteration 段階で明示 reject**)

`tarfile.extractall(path, filter='data')` (Python 3.12+ supported) の `data` filter は extraction root 内を指す relative symlink/hardlink を **許可** する仕様。`artifacts/` subtree を別 dir に配置すると、root 内だった symlink が配置後に artifacts 外を指す経路ができる。

**R20-F-002 fix**: `extractall` 呼出前に tar member を iterate して symlink (`TarInfo.issym()`) / hardlink (`TarInfo.islnk()`) / device file (`TarInfo.ischr()` / `TarInfo.isblk()`) / FIFO (`TarInfo.isfifo()`) を **明示 reject**:

```python
def _verify_tar_members_safe(tar: tarfile.TarFile) -> None:
    for member in tar.getmembers():
        if member.issym() or member.islnk():
            raise RestoreRuntimeError(
                "restore_archive_allowlist_violation",
                detail=f"tar member is symlink/hardlink (rejected): {member.name}",
            )
        if member.ischr() or member.isblk() or member.isfifo():
            raise RestoreRuntimeError(
                "restore_archive_allowlist_violation",
                detail=f"tar member is device/fifo (rejected): {member.name}",
            )
        if not (member.isfile() or member.isdir()):
            raise RestoreRuntimeError(
                "restore_archive_allowlist_violation",
                detail=f"tar member unsupported type (rejected): {member.name} type={member.type!r}",
            )
```

加えて `tarfile.extractall(path, filter='data')` で:
- absolute path / `..` を拒否
- symlink / hardlink を拒否 (`_verify_tar_members_safe` 経由で前段 reject、二重防御として filter='data' も維持)
- device file を拒否
- 所有者 / 権限を tar 値ではなく現在 process の uid/gid に upcast

#### DoS 防止 limits (F-011 adopt)

`scripts/taskhub_restore_orchestrator.py` 定数 (`backup_orchestrator.py` mirror):

```python
TAR_MAX_TOTAL_SIZE_BYTES = 50 * 1024**3   # 50 GiB
TAR_MAX_MEMBER_SIZE_BYTES = 10 * 1024**3  # 10 GiB / 単一 member
TAR_MAX_MEMBER_COUNT = 100_000             # 10万 file 上限
SNIFF_MAX_READ_BYTES = 4096                # 抽出前 sniff の最大 read (private key prefix 検出に十分)
```

extraction 前に tar member を iterate して上記制約を verify、超過は `restore_archive_size_exceeded` deny。

#### allowlist sniff (extraction 前、F-011 adopt)

private key sniff (`-----BEGIN OPENSSH PRIVATE KEY-----` / `AGE-SECRET-KEY-1` / `-----BEGIN PGP PRIVATE KEY BLOCK-----`) を `SNIFF_MAX_READ_BYTES` (4096) bytes だけ読み、tar member content を **extraction 前に reject**。

### 3.4 archive sha256 + checksums.txt + meta.json の tamper protection (F-006 + R16-F-002 adopt)

3 層防御:

1. **CLI 起動時 archive sha256 verify** (R16-F-002 TOCTOU fix): `RestoreApprovalClaim.archive_sha256` と `.tar.age` 全体の sha256 を **same fd で** 計算 + decrypt。具体的には:
   - `open(input_path, 'rb')` で fd を 1 回だけ取得
   - fd を seek 0 → sha256 streaming read で hash 計算 → claim と一致 verify
   - fd を seek 0 に戻す → age decrypt の stdin に直接 pipe (path 経由しない)
   - これにより hash verify と decrypt の間の path swap / rename / replace を 物理的に防止
2. **age decrypt 成功**: signature 整合 (age は authenticated encryption、復号成功で integrity 保証)
3. **checksums.txt + meta.json deterministic compare**: tar 内全 file の sha256 を再計算し、`checksums.txt` と byte-lex sort で一致 verify

backup 側 (PR #77 で書き込んだ meta.json) には **archive sha256 を含めない**。理由: archive sha256 = tar.age 全体の hash であり、tar 内 meta.json に書くと再帰的になる。代わりに `RestoreApprovalClaim.archive_sha256` で外部から固定 (approval 取得時 caller が計算)。

```python
def verify_archive_sha256_and_decrypt_via_immutable_stage(
    input_path: Path,
    expected_sha256: str,
    age_identity_file: Path,
    out_tar_path: Path,
    stage_dir: Path,
) -> None:
    """R16-F-002 + R17-F-002 + R18-F-003 fix: input を read-only stage に hardlink/copy 経由で
    immutable snapshot 化、sha256 verify + age decrypt を **stage snapshot で実行**。

    flock は advisory のため非協調 writer / 同 user in-place write を防げない。
    解決: input を別 path に **content-addressed immutable copy** で複製、
    元 path への mutation と無関係に stage 上で verify + decrypt 完結。
    """
    # Symlink reject (sanity check)
    if input_path.is_symlink():
        raise RestoreUsageError(
            "restore_input_path_invalid",
            detail=f"input_path must not be symlink: {input_path}",
        )

    # (1) input を stage_dir に **full copy で別 inode に複製** (R19-F-001 fix)
    # hardlink は元 input_path と同 inode を共有 → 元への in-place overwrite/truncate が
    # stage 側にも反映される (hardlink semantics)。stage は **完全別 inode** で隔離必要。
    # 同 fs で CoW (btrfs / APFS / xfs reflink) 可能なら efficient、不可なら full byte copy。
    stage_path = stage_dir / "input_archive_immutable.tar.age"
    try:
        # macOS APFS / Linux btrfs+CoW なら reflink で efficient copy (data 共有なし)
        subprocess.run(
            ["cp", "--reflink=auto", str(input_path), str(stage_path)],
            check=True, capture_output=True, timeout=300,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        # cp --reflink 未対応 OS / fs (busybox 等) → shutil.copy2 で純粋 byte copy (disk 2x)
        shutil.copy2(input_path, stage_path)
    # stage_path を read-only に + immutable attribute も検討 (Linux chattr +i は root 必要なので scope out)
    os.chmod(stage_path, 0o400)

    # (2) stage_path を O_NOFOLLOW で open、stat で inode 固定 (mutation 監視不要、stage は孤立)
    fd_num = os.open(stage_path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(fd_num, "rb", closefd=False) as fd:
            # (3) sha256 streaming read on stage fd
            h = hashlib.sha256()
            while True:
                chunk = fd.read(64 * 1024)
                if not chunk:
                    break
                h.update(chunk)
            actual = h.hexdigest()
            if actual != expected_sha256:
                raise RestoreUsageError(
                    "restore_input_archive_sha256_mismatch",
                    detail=f"expected={expected_sha256[:16]}..., actual={actual[:16]}...",
                )
            # (4) seek 0 → age decrypt stdin に stage fd 経由で pipe
            # 元 input_path への concurrent mutation は stage_path に影響しない
            fd.seek(0)
            argv = ["age", "-d", "-i", str(age_identity_file), "-o", str(out_tar_path)]
            result = run_safe_subprocess(
                argv,
                config=SafeSubprocessConfig(timeout_sec=AGE_DECRYPT_TIMEOUT_SEC, stdin_file=fd),
            )
            if result.returncode != 0:
                raise RestoreRuntimeError(
                    "restore_age_decrypt_failed",
                    detail=f"exit={result.returncode}",
                )
    finally:
        os.close(fd_num)
        # stage_path は tmp_dir cleanup (try/finally) で削除される
```

R18-F-003 strategy:
- **hardlink** (or fallback copy) で input を別 path に複製、別 inode reference 保持
- 元 input_path への in-place mutation / rename / unlink でも stage_path は影響なし (Linux hardlink semantics)
- stage_path を `chmod 0o400` で read-only 化、root 以外の non-cooperative writer を block
- `O_NOFOLLOW` で stage_path 経由の symlink TOCTOU 排除
- 同 inode 上の in-place mutation を防ぐ flock 不要 (stage は孤立、元 path から物理的に切離されている)
- disk cost: 同 fs hardlink = 0、別 fs copy = 1x archive size (10 GiB max → 10 GiB temp)、SOP に明記

`age` CLI は **stdin から ciphertext を読み**、`-o <path>` で plaintext を出力可能 (age 公式 spec)。

R17-F-002 追加防御:
- `O_NOFOLLOW`: open 時点で symlink を follow しない (race-free symlink rejection)
- `flock LOCK_EX | LOCK_NB`: 同 inode への concurrent writer を block (non-blocking EX で immediate fail-closed)
- `st_ino + st_size + st_ctime_ns` triple compare: lock 取得後の verification として inode 不変性を再確認 (in-place overwrite が flock を bypass する code path は理論上存在しないが念のため double-check)
- 既存 PR #77 の `verify_archive_sha256` も同 pattern に書換 (PR #77 retro-fix 追加)

#### R2-F-007 HIGH fix: archive_sha256 caller 計算 flow

R2 で「approval issue subcommand が CLI に存在しない → operator が restore approval を作る入口がない」を指摘。

本 batch では **`taskhub approval issue` real I/O subcommand 実装は別 batch carry-over** とし、本 batch では以下で対応:

1. **CLI help string で明示**: `taskhub restore --help` に「approval record を `~/.taskhub/approvals/<id>.signed` に手書きする際の `restore_claim.archive_sha256` は CLI が起動時に `.tar.age` 全体の sha256 を再計算した値と一致必須」と書く
2. **test helper script** (`scripts/test_helpers/generate_restore_approval_record.py`): test fixture 用に approval record を Ed25519 署名込みで生成する helper を本 batch に追加。operator が SOP で参照可能
3. **operator SOP** (`docs/deploy/half-yearly-drill-sop.md` §11) に approval issue 手順を 1 行追加: 「real I/O restore の approval は `python -m scripts.test_helpers.generate_restore_approval_record --archive <path> --target-host ... --signer-key ~/.taskhub/keys/signer.priv` で生成 (本格 CLI subcommand は SP022-T08 batch 4 carry-over)」
4. carry-over marker: SP-022 Sprint Pack で `taskhub approval issue` subcommand 実装を batch 4 で明示

これにより本 batch では test fixture + manual operator flow で end-to-end 動作可能。production deployment 前に batch 4 で `taskhub approval issue` を完成。

### 3.4.1 R2-F-001 CRITICAL adopt: Signature canonical payload に claim を含める (PR #77 retro-fix 同梱)

**問題発見**: R2 plan-review で、PR #77 で追加された `backup_claim` も `restore_claim` も `_rfc8785_canonical_payload_bytes` の署名対象に **入っていない**。`allowed_keys` で record schema を許可しただけで、攻撃者が `~/.taskhub/approvals/<id>.signed` の `backup_claim`/`restore_claim` を後から書き換えても signature_invalid にならず、approval の対象 archive / restore 先を差し替えられる **重大 security vulnerability**。

本 batch で **PR #77 backup_claim も遡及 fix 同梱**:

`scripts/taskhub_signed_approval.py:_rfc8785_canonical_payload_bytes`:

```python
def _rfc8785_canonical_payload_bytes(record: ApprovalRecord) -> bytes:
    payload: dict[str, object] = {
        "allowed_subcommands": list(record.allowed_subcommands),
        "approval_id": record.approval_id,
        "decider": record.decider,
        "drill_kind": record.drill_kind,
        "expires_at": record.expires_at_str,
        "reason_summary": record.reason_summary,
        "signed_at": record.signed_at_str,
        "target_host": record.target_host,
    }
    # R2-F-001 adopt: backup_claim / restore_claim を canonical payload に含める
    if record.backup_claim is not None:
        payload["backup_claim"] = {
            "age_public_key_fingerprint": record.backup_claim.age_public_key_fingerprint,
            "include_sops_env": record.backup_claim.include_sops_env,
            "output_path": record.backup_claim.output_path,
            "overwrite": record.backup_claim.overwrite,
            "skip_service_stop": record.backup_claim.skip_service_stop,
        }
    if record.restore_claim is not None:
        payload["restore_claim"] = {
            "age_public_key_fingerprint": record.restore_claim.age_public_key_fingerprint,
            "archive_sha256": record.restore_claim.archive_sha256,
            "expected_alembic_head": record.restore_claim.expected_alembic_head,
            "expected_postgres_major_version": record.restore_claim.expected_postgres_major_version,
            "input_path": record.restore_claim.input_path,
            "skip_service_stop": record.restore_claim.skip_service_stop,
            "target_artifacts_container_path": record.restore_claim.target_artifacts_container_path,  # R23-F-001 fix
            "target_artifacts_dir": record.restore_claim.target_artifacts_dir,
            "target_compose_file_path": record.restore_claim.target_compose_file_path,    # R9-F-002 fix
            "target_compose_project_name": record.restore_claim.target_compose_project_name,  # R9-F-002 fix
            "target_pg_dsn_components": dict(sorted(record.restore_claim.target_pg_dsn_components.items())),
            "target_redis_endpoint": record.restore_claim.target_redis_endpoint,
        }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
```

`ApprovalRecord` dataclass に `backup_claim: BackupApprovalClaim | None` と `restore_claim: RestoreApprovalClaim | None` を field 追加 + loader で load。

**Migration impact (PR #77 retro-fix)**:
- 既存 PR #77 で作成された approval record は backup_claim を signature に含まずに署名済 → 本 fix で signature_invalid になる
- 解決: 既存 test fixture を **re-sign** する script を本 batch に含める (`scripts/test_helpers/re_sign_approval_records.py`)、test fixture の generation flow を update
- production deployment では PR #77 の approval は本 batch deploy 前に **全て revoke** + 新規 issue 必須 (operator SOP に明記)

regression test:
- `test_backup_claim_in_canonical_payload_changes_signature` (claim 書き換えで signature_invalid)
- `test_restore_claim_in_canonical_payload_changes_signature`

### 3.5 service stop / start orchestration (F-001 + F-008 + R2-F-002/F-004/F-006 adopt、scope 格上げ)

#### R2-F-002 CRITICAL fix: service stop と pre-restore snapshot の order 解決

R2 で「stop_services 後に pg_dump できない (postgres down)」「artifacts move 先行で pg_dump 失敗時に中間状態」を指摘。正しい順序:

1. **app-level service stop only** (api / worker): postgres / redis は **alive** で維持 (snapshot 取得のため)
2. **pre-restore snapshot 取得** (postgres / redis 動作中):
   - pg_dump で DB snapshot
   - redis-cli BGSAVE wait + dump.rdb copy
   - artifacts dir move
3. **data-level service stop** (postgres / redis): pg_restore / Redis dump.rdb 置換のため
4. **pg_restore + Redis dump.rdb placement**
5. **postgres / redis を service up** (alembic verify のため必要)
6. **alembic verify** (R2-F-004 fix: api/worker start **前** に実行)
7. **api / worker service up + healthcheck**

```python
# R8-F-001 fix: 全ての docker compose 系 subprocess は `-p <project_name>` + `-f <abs_path>` を明示
# RestoreOptions.target_compose_project_name / target_compose_file_path は claim signed 値、CLI 起動時に
# project name 一致 + compose file 絶対 path 一致 verify 済 (ambient cwd / COMPOSE_PROJECT_NAME env 無効化)
def _compose_argv_prefix(options: RestoreOptions) -> list[str]:
    return [
        "docker", "compose",
        "-p", options.target_compose_project_name,
        "-f", str(options.target_compose_file_path),
    ]

def stop_app_services(options: RestoreOptions) -> None:
    """api / worker のみ stop (postgres / redis は snapshot 取得のため alive 維持)."""
    result = run_safe_subprocess(
        _compose_argv_prefix(options) + ["stop", "--timeout=30", "api", "worker"],
        config=SafeSubprocessConfig(timeout_sec=120),
    )
    if result.returncode != 0:
        raise RestoreRuntimeError("restore_service_stop_failed",
                                  detail=f"app_stop_exit={result.returncode}")


def stop_data_services(options: RestoreOptions) -> None:
    """postgres / redis stop (pg_restore / dump.rdb 置換のため).
    R9-F-001 fix: _compose_argv_prefix(options) 経由で project name + compose file path 明示。
    """
    result = run_safe_subprocess(
        _compose_argv_prefix(options) + ["stop", "--timeout=30", "postgres", "redis"],
        config=SafeSubprocessConfig(timeout_sec=120),
    )
    if result.returncode != 0:
        raise RestoreRuntimeError("restore_service_stop_failed",
                                  detail=f"data_stop_exit={result.returncode}")


def start_data_services_wait_healthy(options: RestoreOptions) -> None:
    """postgres / redis のみ先に up + healthcheck (alembic verify のため必要).
    R9-F-001 fix: _compose_argv_prefix 経由で ambient 依存禁止。
    """
    result = run_safe_subprocess(
        _compose_argv_prefix(options) + ["up", "-d", "postgres", "redis"],
        config=SafeSubprocessConfig(timeout_sec=300),
    )
    if result.returncode != 0:
        raise RestoreRuntimeError("restore_service_start_failed",
                                  detail=f"data_start_exit={result.returncode}")
    _wait_services_healthy(options, ["postgres", "redis"], timeout_sec=DATA_HEALTHCHECK_TIMEOUT_SEC)


def start_app_services_wait_healthy(options: RestoreOptions) -> None:
    """api / worker up + healthcheck (alembic verify PASS 後に実行).
    R9-F-001 fix: _compose_argv_prefix 経由で ambient 依存禁止。
    """
    result = run_safe_subprocess(
        _compose_argv_prefix(options) + ["up", "-d", "api", "worker"],
        config=SafeSubprocessConfig(timeout_sec=300),
    )
    if result.returncode != 0:
        raise RestoreRuntimeError("restore_service_start_failed",
                                  detail=f"app_start_exit={result.returncode}")
    _wait_services_healthy(options, ["api", "worker"], timeout_sec=APP_HEALTHCHECK_TIMEOUT_SEC)


# R5-F-001 + R9-F-001 fix: rollback path 専用の単独 service helper、全て _compose_argv_prefix 経由
def start_postgres_wait_healthy(options: RestoreOptions) -> None:
    result = run_safe_subprocess(
        _compose_argv_prefix(options) + ["up", "-d", "postgres"],
        config=SafeSubprocessConfig(timeout_sec=300),
    )
    if result.returncode != 0:
        raise RestoreRuntimeError("restore_service_start_failed",
                                  detail=f"postgres_only_start_exit={result.returncode}")
    _wait_services_healthy(options, ["postgres"], timeout_sec=DATA_HEALTHCHECK_TIMEOUT_SEC)


def stop_redis_service_only(options: RestoreOptions) -> None:
    result = run_safe_subprocess(
        _compose_argv_prefix(options) + ["stop", "--timeout=30", "redis"],
        config=SafeSubprocessConfig(timeout_sec=120),
    )
    if result.returncode != 0:
        raise RestoreRuntimeError("restore_service_stop_failed",
                                  detail=f"redis_only_stop_exit={result.returncode}")


def start_redis_service_wait_healthy(options: RestoreOptions) -> None:
    result = run_safe_subprocess(
        _compose_argv_prefix(options) + ["up", "-d", "redis"],
        config=SafeSubprocessConfig(timeout_sec=300),
    )
    if result.returncode != 0:
        raise RestoreRuntimeError("restore_service_start_failed",
                                  detail=f"redis_only_start_exit={result.returncode}")
    _wait_services_healthy(options, ["redis"], timeout_sec=DATA_HEALTHCHECK_TIMEOUT_SEC)


def _wait_services_healthy(options: RestoreOptions, services: list[str], *, timeout_sec: int) -> None:
    """R8/R9-F-001 fix: docker compose ps も _compose_argv_prefix 経由で project + file 明示。"""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        ps = run_safe_subprocess(
            _compose_argv_prefix(options) + ["ps", "--format", "json"] + services,
            config=SafeSubprocessConfig(timeout_sec=30),
        )
        if all_services_healthy(ps.stdout, services):
            return
        time.sleep(HEALTHCHECK_POLL_INTERVAL_SEC)
    raise RestoreRuntimeError("restore_healthcheck_failed",
                              detail=f"timeout={timeout_sec}s for {services}")
```

#### R2-F-006 fix: healthcheck timeout を現行 compose に整合化

`docker-compose.yml` の healthcheck 設定 (`interval=30s` + `retries=3` + `start_period=5-10s`) を踏まえた現実的 timeout:

```python
DATA_HEALTHCHECK_TIMEOUT_SEC = 120  # postgres / redis (依存なし、起動 30-60s)
APP_HEALTHCHECK_TIMEOUT_SEC = 180   # api / worker (DB 接続 + alembic check 含む、interval 30s × retries 3 + 余裕)
HEALTHCHECK_POLL_INTERVAL_SEC = 5
```

#### R2-F-003 HIGH fix: Redis restore は docker named volume + AOF disable 経由

R2 で「CONFIG GET dir は container 内 path、AOF 優先で dump.rdb 置いても load されない」を指摘。

修正 strategy (named volume host path 経由 + AOF temp disable):

```python
def acquire_redis_data_host_path(options: RestoreOptions) -> Path:
    """docker inspect <redis_container> の Mounts から実 mount source を取得.
    R17-F-004 fix: volume 名推測 (`<project>_redis_data`) ではなく、実 running container の
    Mounts inspection で実 mount source を取得 (named volume / external / bind mount 全対応)。
    R18-F-001 fix: `--all` で stopped container も含めて取得 (rollback / dump placement は stop 後 invocation 想定)。
    """
    # (1) compose ps --all で redis container ID を取得 (stopped 含む、R18-F-001 fix)
    ps_result = run_safe_subprocess(
        _compose_argv_prefix(options) + ["ps", "--all", "-q", "redis"],
        config=SafeSubprocessConfig(timeout_sec=30),
    )
    if ps_result.returncode != 0 or not ps_result.stdout.strip():
        raise RestoreRuntimeError(
            "restore_redis_data_placement_failed",
            detail=f"compose_ps_redis_failed: exit={ps_result.returncode}",
        )
    container_id = ps_result.stdout.decode("utf-8").strip().split("\n")[0]

    # (2) docker inspect で Mounts 配列を取得、Destination=/data の Source を特定
    inspect_result = run_safe_subprocess(
        ["docker", "inspect", "--format", "{{json .Mounts}}", container_id],
        config=SafeSubprocessConfig(timeout_sec=30),
    )
    if inspect_result.returncode != 0:
        raise RestoreRuntimeError(
            "restore_redis_data_placement_failed",
            detail=f"docker_inspect_failed: exit={inspect_result.returncode}",
        )
    try:
        mounts = json.loads(inspect_result.stdout.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise RestoreRuntimeError(
            "restore_redis_data_placement_failed",
            detail=f"docker_inspect_json_invalid: {e}",
        ) from None
    if not isinstance(mounts, list):
        raise RestoreRuntimeError(
            "restore_redis_data_placement_failed",
            detail="docker_inspect_mounts_not_array",
        )
    # /data destination の Source path を特定
    data_mount = next(
        (m for m in mounts if m.get("Destination") == "/data"),
        None,
    )
    if data_mount is None:
        raise RestoreRuntimeError(
            "restore_redis_data_placement_failed",
            detail="redis_container_no_data_mount: /data destination not found in Mounts",
        )
    source_path = data_mount.get("Source")
    if not isinstance(source_path, str) or not source_path:
        raise RestoreRuntimeError(
            "restore_redis_data_placement_failed",
            detail=f"data_mount_source_invalid: {source_path}",
        )
    return Path(source_path)


def _acquire_redis_data_host_path_legacy_unused(options: RestoreOptions) -> Path:
    """旧 implementation: volume name 推測 (R17-F-004 fix で削除)、参考用のみ."""
    volume_name = f"{options.target_compose_project_name}_redis_data"
    result = run_safe_subprocess(
        ["docker", "volume", "inspect", "-f", "{{.Mountpoint}}", volume_name],
        config=SafeSubprocessConfig(timeout_sec=30),
    )
    if result.returncode != 0:
        raise RestoreRuntimeError("restore_redis_data_placement_failed",
                                  detail="volume_inspect_failed")
    mountpoint = result.stdout.decode("utf-8").strip()
    return Path(mountpoint)


def place_redis_dump_rdb_via_named_volume(
    options: RestoreOptions,
    new_dump_rdb_path: Path,
    pre_restore_dir: Path,
) -> None:
    """redis を停止後、named volume の host mount path に dump.rdb を直接配置。
    AOF (appendonlydir) を temp 退避して RDB load を強制。
    R9-F-001 fix: skip_service_stop 削除済 (CLI で物理 deny)、acquire_redis_data_host_path に options 渡し。
    """
    # 前提: postgres / redis は既に stop_data_services(options) で stop 済み
    redis_host_path = acquire_redis_data_host_path(options)
    # Existing AOF を _pre-restore-<ts>/redis_aof_backup/ へ退避 (rollback で戻すため)
    aof_dir = redis_host_path / "appendonlydir"
    if aof_dir.exists():
        shutil.move(str(aof_dir), str(pre_restore_dir / "redis_aof_backup"))
    # 既存 dump.rdb は pre-restore snapshot で既に copy 済 (create_pre_restore_snapshot で)
    shutil.copy2(new_dump_rdb_path, redis_host_path / "dump.rdb")
    # 注: Redis 7 は AOF disable 時は dump.rdb を起動時に load する
```

**Docker permission caveat**: named volume の host mount path は通常 root 所有 (`/var/lib/docker/volumes/`)。本 batch では実行 user が docker group 経由で operate する前提を SOP に明記 (sudoless 動作)。test 環境では subprocess mock + tmp dir で代替。

**alternative**: docker compose exec を使う方式は本 batch carry-over (実装が複雑、docker cp + redis service の同期挙動が不安定)。

#### R2-F-004 HIGH fix: alembic verify は app service start **前** に実行

R2 で「start_services 後に alembic verify は不整合 schema/data を app に露出」を指摘。

`run_restore` 内の order を修正 (§3.10 で update):

1. stop_app_services
2. create_pre_restore_snapshot (postgres / redis alive)
3. stop_data_services
4. place_artifacts
5. invoke_pg_restore (postgres restart 不要、subprocess は direct connect)
   - **note**: pg_restore は postgres alive 必要、stop_data_services は **pg_restore 後** が正しい
6. place_redis_dump_rdb_via_named_volume (redis stop 必要)
7. start_data_services_wait_healthy (postgres / redis)
8. **verify_alembic_head_in_db** (R2-F-004 fix: ここに移動)
9. start_app_services_wait_healthy (api / worker)

修正 order を §3.10 の擬似コードで明示する。

#### service tool 不在時の挙動

`docker compose` / `docker volume` tool 不在 → `BackupToolNotFoundError` 同 pattern で `restore_service_stop_failed` または `restore_redis_data_placement_failed` deny (graceful skip 禁止)。test 環境では subprocess mock で代替。

### 3.6 pre-restore snapshot + atomic rollback strategy (F-002 adopt)

R1 F-002 で指摘された通り、target_data_dir move-back **だけでは DB / Redis の rollback ができない**。3 component snapshot を取り、 失敗時に全 component を rollback:

```python
def create_pre_restore_snapshot(options: RestoreOptions, ts: str, register_dir: Callable[[Path], None]) -> Path:
    """3 component (artifacts / DB / Redis) の pre-restore snapshot を保管.
    R15-F-001 fix: pg_dump / redis dump path 取得を全て compose exec + named volume 経由に統一。
    R18-F-002 fix: 各 component snapshot 完了直後に register_dir() callback で outer pre_restore_dir
    を update、artifacts move 後の pg_dump 失敗でも outer catch が rollback 起動可能。
    """
    pre_restore_dir = options.target_artifacts_dir.parent / f"_pre-restore-{ts}"
    pre_restore_dir.mkdir(mode=0o700)

    # 1. artifacts: dir move (atomic rename)
    shutil.move(str(options.target_artifacts_dir), str(pre_restore_dir / "artifacts"))

    # R18-F-002 fix: artifacts move 完了直後に outer に登録、後続失敗でも rollback 起動可能
    register_dir(pre_restore_dir)

    # 2. DB: pg_dump via compose exec で current DB の snapshot 取得 (host TCP path 廃止)
    # R20-F-001 fix: `.tmp` suffix で write → atomic rename で最終 path 化、
    # exists(pre_restore_pg_dump.dump) = 真の "完成済" を保証 (partial file 残留防止)
    db_snapshot_path = pre_restore_dir / "pre_restore_pg_dump.dump"
    db_snapshot_tmp = pre_restore_dir / "pre_restore_pg_dump.dump.tmp"
    result = invoke_pg_dump_via_compose_exec(
        options,
        output_path=db_snapshot_tmp,
        timeout_sec=options.pg_dump_timeout_sec,
    )
    if result.returncode != 0:
        # tmp file が残っていれば削除 (best-effort)
        if db_snapshot_tmp.exists():
            db_snapshot_tmp.unlink()
        raise RestoreRuntimeError("restore_pre_restore_pg_dump_failed", detail=f"exit={result.returncode}")
    # atomic rename: rollback の exists() check で真の完成済を保証
    os.rename(db_snapshot_tmp, db_snapshot_path)

    # 3. Redis: synchronous SAVE (blocking) で BGSAVE race-free dump 強制
    # R17-F-001 fix: BGSAVE は LASTSAVE 比較で前の進行中 BGSAVE 完了を誤認するため、
    # blocking SAVE command (REDIS は SAVE 中 client request block、確実に同期 dump 完了)
    # SAVE 完了後 dump.rdb は guaranteed up-to-date、race-free。
    # 注: SAVE は production load 中は使用注意 (blocking)、本 batch では restore 直前 manual approval 後の
    # operational window 内なので blocking 動作許容、SOP に明記。
    invoke_redis_save_sync_via_compose_exec(options, timeout_sec=options.redis_save_timeout_sec)
    # SAVE return success = dump.rdb 完全書込済 (Redis spec)、LASTSAVE race 不要
    # R20-F-001 fix: copy も `.tmp` suffix → atomic rename pattern (partial file 残留防止)
    redis_host_path = acquire_redis_data_host_path(options)  # 実 mount source (R17-F-004 fix で update)
    redis_snapshot_path = pre_restore_dir / "pre_restore_dump.rdb"
    redis_snapshot_tmp = pre_restore_dir / "pre_restore_dump.rdb.tmp"
    try:
        shutil.copy2(redis_host_path / "dump.rdb", redis_snapshot_tmp)
    except OSError:
        if redis_snapshot_tmp.exists():
            redis_snapshot_tmp.unlink()
        raise
    os.rename(redis_snapshot_tmp, redis_snapshot_path)

    return pre_restore_dir
```

rollback 時 (R2-F-002/F-003 + R3-F-002 + R4-F-001 adopt 反映 order):

```python
def rollback_from_pre_restore_snapshot(pre_restore_dir: Path, options: RestoreOptions) -> None:
    """Snapshot から 3 component を原子的に戻す (R2-F-002/F-003 + R3-F-002 + R4-F-001 反映 order).

    R4-F-001 CRITICAL fix: rollback 最初の処理として **app services を確実に stop** してから
    data services restart。`start_app_services_wait_healthy()` の途中失敗ケースで
    api/worker が部分起動状態 + DB/Redis 復活時間帯に restored/new data へ書込 → pre-restore
    state 汚染の race を防止。

    R3-F-002 CRITICAL fix: 失敗地点が data service stop 後だと postgres が停止 / unhealthy
    の可能性があるため、app stop 後に **必ず data services を start + healthcheck**
    してから pg_restore を実行する。
    """
    # R4-F-001 fix: 0a. app services を **最優先** で stop (api/worker partial-up race 防止)
    # 既に stop 済 or 未起動でも idempotent (docker compose stop は no-op で OK)
    stop_app_services(options)

    # R5-F-001 CRITICAL fix: 0b. **postgres のみ** 確実に up + healthy に
    # 旧 `start_data_services_wait_healthy()` (postgres + redis) は Redis 起因の failure で
    # DB rollback にも到達できない事故を防ぐため、ここでは postgres のみ。
    # Redis は Step 4 (dump.rdb 復旧) + Step 5 で改めて up + healthcheck 実行する。
    start_postgres_wait_healthy(options)

    # 2. artifacts: move back (新 artifacts 削除してから pre-restore snapshot を戻す)
    if options.target_artifacts_dir.exists():
        shutil.rmtree(options.target_artifacts_dir, ignore_errors=False)
    shutil.move(str(pre_restore_dir / "artifacts"), str(options.target_artifacts_dir))

    # 3. DB: pg_restore via compose exec で pre-restore dump を再 restore (postgres alive 保証済)
    # R15-F-001 fix: rollback path も compose exec 経由に統一 (host TCP 廃止)
    # R19-F-002 CRITICAL fix: pre_restore_pg_dump.dump 不在なら DB rollback skip (snapshot 未完成)
    pre_db_dump = pre_restore_dir / "pre_restore_pg_dump.dump"
    if not pre_db_dump.exists():
        warnings.append("restore_rollback_db_skipped_no_pre_snapshot")
        # artifacts のみ rollback、DB / Redis は restore で touch されていない前提
        start_app_services_wait_healthy(options)
        return
    result = invoke_pg_restore_via_compose_exec(
        options,
        dump_file=pre_db_dump,
        timeout_sec=options.pg_restore_timeout_sec,
    )
    if result.returncode != 0:
        raise RestoreRuntimeError("restore_rollback_failed",
                                  detail=f"pg_restore_rollback_exit={result.returncode}")

    # 4. Redis: stop → pre-restore Redis snapshot 存在 verify → 既存新 AOF/RDB wipe → 復旧 → start
    # R19-F-002 CRITICAL fix: rollback 開始時に pre_restore_dump.rdb が存在しない場合は
    # **Redis 部分の rollback skip** (snapshot 未完成 = Redis はまだ touch されていない、wipe 不要)
    # 不在のまま wipe すると pre-restore Redis data 破壊。
    pre_redis_dump = pre_restore_dir / "pre_restore_dump.rdb"
    pre_aof_backup = pre_restore_dir / "redis_aof_backup"
    redis_snapshot_exists = pre_redis_dump.exists()

    if redis_snapshot_exists:
        # Redis snapshot 完成済 → 通常 rollback (R17-F-003 clean-slate fix 適用)
        stop_redis_service_only(options)
        redis_host_path = acquire_redis_data_host_path(options)
        # 新 dump.rdb と新 appendonlydir を **明示削除** (clean slate)
        new_dump_rdb = redis_host_path / "dump.rdb"
        if new_dump_rdb.exists():
            new_dump_rdb.unlink()
        new_aof_dir = redis_host_path / "appendonlydir"
        if new_aof_dir.exists():
            shutil.rmtree(new_aof_dir, ignore_errors=False)
        # pre-restore snapshot を配置
        shutil.copy2(pre_redis_dump, redis_host_path / "dump.rdb")
        if pre_aof_backup.exists():
            shutil.move(str(pre_aof_backup), str(redis_host_path / "appendonlydir"))
    else:
        # Redis snapshot 未完成 → restore は Redis を touch しなかった、wipe しない
        warnings.append("restore_rollback_redis_skipped_no_pre_snapshot")

    # 5. redis up + healthcheck (postgres は既に alive)
    # R5-F-001 fix: failure 時は restore_rollback_failed + SOP manual recovery hint
    try:
        start_redis_service_wait_healthy(options)
    except RestoreRuntimeError as e:
        raise RestoreRuntimeError(
            "restore_rollback_failed",
            detail=(
                f"redis_rollback_start_failed: {e.detail}. "
                "DB + artifacts は rollback 成功、Redis は手動復旧必要: "
                "(a) docker volume inspect で host path 確認、(b) pre-restore snapshot "
                f"({pre_restore_dir}/pre_restore_dump.rdb) を確認、(c) docker compose up redis 後 "
                "redis-cli LASTSAVE で load 確認"
            ),
        ) from e

    # 6. app service up + healthcheck
    start_app_services_wait_healthy(options)
```

新規 helper (R5-F-001 fix で追加):
- `start_postgres_wait_healthy()`: postgres のみ up + healthcheck、Redis 触らない
- `stop_redis_service_only()`: redis のみ stop、postgres alive 維持
- `start_redis_service_wait_healthy()`: redis のみ up + healthcheck
- 既存 `start_data_services_wait_healthy()` / `stop_data_services()` は restore 正常系 (Step 6 / 8) でのみ使用、rollback では分割版を使う

### 3.7 pg_restore via docker compose exec (F-013 + F-PR77-003 + R14-F-001 adopt)

**R14-F-001 CRITICAL fix**: pg_restore / pg_dump / redis-cli は **`docker compose exec` 経由で container 内実行**に変更 (旧 host TCP 経由 `127.0.0.1:5432` は port-collision 攻撃 / 別 Compose project が同 port を握る経路が残るため root cause fix)。

`invoke_pg_restore()` argv:
```
docker compose -p <project> -f <abs_path> exec -T -e PGPASSWORD_FROM_VOLUME postgres pg_restore
  --username=$PG_USER
  --dbname=$PG_DB
  --clean --if-exists
  --single-transaction
  --no-owner --no-privileges
  --exit-on-error
  --no-password           # PGPASSFILE は container 内 path or PGPASSWORD env (container 内 only) で渡す
  -                       # stdin から dump 受取
```

stdin redirection: `dump_file` の bytes を docker exec の stdin に流す (host fs に dump file が必要だが、subprocess は file → docker stdin pipe 経由、container 内 fs touch しない)。

**PGPASSFILE strategy 更新 (R14-F-001 fix)**:
- 旧 host-side PGPASSFILE (env `TASKHUB_BACKUP_PGPASSFILE`) は **削除**。container 内には postgres trust auth (Docker network 内 trust) または container 内に baked-in `.pgpass` を使う。
- container 内認証: `docker-compose.yml` の postgres service が trust auth (Docker network 内のみ) で動作する前提を SOP に明記。production deployment で trust auth が許容できない場合は `POSTGRES_PASSWORD` env + container 内 PGPASSWORD env (compose exec `-e` 経由) を使う。本 batch は trust auth 前提 + 必要時 SOP carry-over。
- **caveat**: container 内 unix socket (`-h /var/run/postgresql`) を使えば PGPASSFILE 不要、これを recommended pattern とする。

```python
def invoke_pg_restore_via_compose_exec(
    options: RestoreOptions,
    dump_file: Path,
    *,
    timeout_sec: int,
) -> SubprocessResult:
    """R14-F-001 fix: pg_restore を docker compose exec 経由で container 内実行。
    container 内 unix socket 経由なので TCP port-collision 攻撃 100% 防止。
    """
    argv = (
        _compose_argv_prefix(options)
        + ["exec", "-T", "postgres", "pg_restore"]
        + [f"--username={options.target_pg_dsn_components['user']}"]
        + [f"--dbname={options.target_pg_dsn_components['db']}"]
        + ["--clean", "--if-exists", "--single-transaction",
           "--no-owner", "--no-privileges", "--exit-on-error",
           "--no-password",
           "-h", "/var/run/postgresql",   # container 内 unix socket
           "-"]                            # stdin 経由
    )
    # R15-F-002 fix: f.read() で全 dump メモリ load せず、file object を stdin に直接 pipe
    # 10 GiB dump でも OOM 回避 (kernel が subprocess に streaming pipe)
    with open(dump_file, "rb") as f:
        return run_safe_subprocess(
            argv,
            config=SafeSubprocessConfig(timeout_sec=timeout_sec, stdin_file=f),
        )
```

`run_safe_subprocess()` に `stdin_file: BinaryIO | None` parameter 追加 (PR #77 では `stdin=DEVNULL` 固定)。subprocess.Popen の `stdin=f` に直接渡し、kernel が streaming pipe する (Python メモリ load 回避)。本 batch で `SafeSubprocessConfig` を拡張 (subprocess_runner.py も touch、後方互換維持で default `None` = DEVNULL)。

`stdin_data: bytes` parameter は **採用しない** (R15-F-002 fix: 全 dump メモリ load 経路を提供しない、stream 経由のみ)。

### 3.7.1 pg_dump (pre-restore snapshot) も同様に container exec 経由

```python
def invoke_pg_dump_via_compose_exec(
    options: RestoreOptions,
    output_path: Path,
    *,
    timeout_sec: int,
) -> SubprocessResult:
    """pre-restore snapshot 用 pg_dump、container exec 経由."""
    argv = (
        _compose_argv_prefix(options)
        + ["exec", "-T", "postgres", "pg_dump"]
        + [f"--username={options.target_pg_dsn_components['user']}"]
        + [f"--dbname={options.target_pg_dsn_components['db']}"]
        + ["--format=custom", "--no-owner", "--no-privileges",
           "--no-password",
           "-h", "/var/run/postgresql"]
    )
    # stdout は container 内 pg_dump 出力、host file へ pipe
    with open(output_path, "wb") as f:
        return run_safe_subprocess(
            argv,
            config=SafeSubprocessConfig(timeout_sec=timeout_sec, stdout_file=f),
        )
```

`run_safe_subprocess()` に `stdout_file: BinaryIO | None` parameter 追加が必要。

### 3.7.2 Redis 操作も container exec 経由 (R14-F-001 + R17-F-001 + R18-F-004 fix)

**R18-F-004 fix**: 旧 BGSAVE 経由 helper `invoke_redis_save_via_compose_exec` は **削除**、`invoke_redis_save_sync_via_compose_exec` (blocking SAVE) のみ提供。R17-F-001 で確立した race-free 同期 SAVE を helper level でも単一 entry point に統一 (drift 防止)。

```python
def invoke_redis_save_sync_via_compose_exec(
    options: RestoreOptions, *, timeout_sec: int
) -> SubprocessResult:
    """redis-cli SAVE (blocking sync save) を container exec 経由で実行.
    R17-F-001 fix: BGSAVE + LASTSAVE wait の race (前 BGSAVE 進行中 LASTSAVE 増加で誤認) を回避、
    blocking SAVE return = dump.rdb 完全書込済 (Redis spec) で race-free。
    R18-F-004 fix: BGSAVE 経由 helper は削除、SAVE のみ単一 entry point。
    """
    argv = _compose_argv_prefix(options) + ["exec", "-T", "redis", "redis-cli", "SAVE"]
    return run_safe_subprocess(argv, config=SafeSubprocessConfig(timeout_sec=timeout_sec))


# 旧 invoke_redis_save_via_compose_exec (BGSAVE) + invoke_redis_lastsave_via_compose_exec は
# R18-F-004 で **削除**。drift 防止のため code, test, doc で BGSAVE 言及完全廃止。
```

pre-restore snapshot 取得 (`invoke_redis_save_sync_via_compose_exec` + `acquire_redis_data_host_path` 経由 dump.rdb copy) で完了。host TCP / port-collision 問題なし (compose exec + named volume host source inspection)。

### 3.7.3 R14-F-001 fix scope impact

本変更により以下も連動更新:

1. **`scripts/taskhub_subprocess_runner.py`**: `SafeSubprocessConfig` に `stdin_data: bytes | None` + `stdout_file: BinaryIO | None` 追加 (後方互換 default None)
2. **`scripts/taskhub_backup_orchestrator.py`** (PR #77 retro-fix): pg_dump / age encrypt / redis-cli を **同様に compose exec 経由**へ書き換える (本 batch で同 root cause fix を backup 側にも遡及適用、F-PR77-003 PGPASSFILE 必須 → container exec で不要に変わる)
3. **`docker-compose.yml`**: postgres service に unix socket volume mount を確認 (`/var/run/postgresql` が存在するか、または `PGHOST` を localhost で trust)、必要なら本 batch で update
4. **PGPASSFILE invariant 廃止**: F-PR77-003 / F-R3-F-001 で必須化した PGPASSFILE は host TCP 経由前提だったため、container exec + unix socket 経由なら不要。`BackupOptions.pgpassfile_path` / `RestoreOptions.pgpassfile_path` field 自体は **削除** (postgres trust auth in container 前提)
5. **adversarial test fixture**: 「Compose stack 停止 + 別 process が 127.0.0.1:5432 を holding」シナリオで restore 試行 → compose exec が container down で失敗 (compose service not running) → fail-closed verified

### 3.7.4 PGPASSFILE 廃止 vs 維持の trade-off (R14-F-001 fix)

- 廃止 (R14-F-001 adopt): port-collision 攻撃 100% 防止 / SecretBroker invariant 整合 / 実装 simplify (PGPASSFILE permission verify 不要)
- 維持: production で trust auth 不可能な場合の compatibility
- **本 batch 採用**: 廃止 (root cause fix 優先、production trust auth は SOP で明記、必要に応じて batch 4 で `--db-password-env` flag 追加検討)

### 3.8 alembic head verify (F-014 + R14-F-001 + R15-F-001 adopt: container exec 経由)

restore **後** DB の `alembic_version` table を read、container 内 psql 経由で取得 (R14-F-001 + R15-F-001 fix: host TCP path 完全廃止):

```python
def verify_alembic_head_in_db(options: RestoreOptions) -> str:
    """restore 後 DB の alembic_version table から head を取得し、期待値と一致 verify.
    R15-F-001 fix: docker compose exec 経由で container 内 psql 実行 (host TCP path 排除)。
    """
    argv = (
        _compose_argv_prefix(options)
        + ["exec", "-T", "postgres", "psql"]
        + [f"--username={options.target_pg_dsn_components['user']}"]
        + [f"--dbname={options.target_pg_dsn_components['db']}"]
        + ["-h", "/var/run/postgresql",  # container 内 unix socket
           "--no-password",
           "-c", "select version_num from alembic_version", "-t", "-A"]
    )
    result = run_safe_subprocess(
        argv,
        config=SafeSubprocessConfig(timeout_sec=30),
    )
    if result.returncode != 0:
        raise RestoreRuntimeError("restore_alembic_head_mismatch",
                                  detail=f"psql_via_compose_exec_failed: exit={result.returncode}")
    head = result.stdout.decode("utf-8").strip()
    if head != options.expected_alembic_head:
        raise RestoreRuntimeError("restore_alembic_head_mismatch",
                                  detail=f"db={head}, expected={options.expected_alembic_head}")
    return head
```

local code head との比較は本 batch scope 外 (operator が `alembic check` を SOP で別途実行)、F-014 fix の core は DB 側 verify。

### 3.9 age private key env name (F-003 adopt、SecretBroker invariant 整合)

**問題**: 当初 plan で `TASKHUB_BACKUP_AGE_PRIVATE_KEY` を proposed → `taskhub_subprocess_runner.py:SECRET_ENV_REJECT_PATTERNS` の `*_KEY` pattern と衝突。

**Fix (F-003 adopt)**:
- env 名を `TASKHUB_BACKUP_AGE_IDENTITY_FILE` に変更 (key 値ではなく path を指すことを名前で明示)
- 同 env はあくまで **file path** を持つ、key 値そのものは決して env 経由で渡さない (SecretBroker raw secret 非保存 invariant)
- subprocess runner `extra_env_allowlist=("TASKHUB_BACKUP_AGE_IDENTITY_FILE",)` も検討するが、age subprocess は **argv `-i <path>` で path を渡す方式**を採用、env injection 不要
- CLI flag は `--age-identity-file <path>` (env override 同名)
- path の検証: file 存在 + permission 0o400 or 0o600 + non-symlink + regular file (PGPASSFILE と同 pattern)

### 3.10 cleanup policy + run_restore order (F-010 + R2-F-002/F-003/F-004 adopt)

`try-finally` で確実 cleanup + 正しい service stop / start order:

```python
def run_restore(options: RestoreOptions) -> RestoreResult:
    tmp_dir = resolve_restore_temp_layout()  # mkdtemp + os.chmod(0o700)
    pre_restore_dir = None
    try:
        # === Step 1: archive verification (service 動作中 OK) ===
        # R16-F-002 + R17-F-002 + R18-F-003 fix: input を immutable stage hardlink/copy 経由、
        # sha256 verify + age decrypt を stage 上で実行、in-place mutation 物理排除
        decrypted_tar = tmp_dir / "decrypted.tar"
        stage_dir = tmp_dir / "immutable_stage"
        stage_dir.mkdir(mode=0o700)
        verify_archive_sha256_and_decrypt_via_immutable_stage(
            options.input_path,
            options.archive_sha256,
            options.age_identity_file,
            decrypted_tar,
            stage_dir,
        )
        extract_with_limits(decrypted_tar, tmp_dir / "extracted")  # tar size/count check
        verify_checksums(tmp_dir / "extracted")
        meta = read_and_verify_meta_json(tmp_dir / "extracted" / "meta.json")
        verify_postgres_major_version(meta, options.expected_postgres_major_version)

        # === Step 1.5: target binding consistency preflight (R11-F-001 fix) ===
        # Compose project/file の deployment と claim 内 DB/Redis target が同一 deployment か verify
        verify_target_binding_consistency(options)

        # === Step 2: app service stop (postgres/redis は alive 維持、snapshot のため) ===
        # R3-F-001 fix: skip_service_stop は CLI で物理 deny 済、orchestrator は常に stop/start 実行
        stop_app_services(options)

        # === Step 3: pre-restore snapshot (postgres/redis alive で取得) ===
        # R18-F-002 fix: register_dir callback で各 step 完了直後に outer pre_restore_dir 登録、
        # artifacts move 後の pg_dump / Redis SAVE 失敗でも outer catch が rollback 起動可能
        def _register_pre_restore_dir(dir_path: Path) -> None:
            nonlocal pre_restore_dir
            pre_restore_dir = dir_path
        pre_restore_dir = create_pre_restore_snapshot(options, ts, _register_pre_restore_dir)

        # === Step 4: artifacts placement (新 data) ===
        place_artifacts(tmp_dir / "extracted" / "artifacts", options.target_artifacts_dir)

        # === Step 5: pg_restore (postgres alive、--single-transaction で atomic) ===
        invoke_pg_restore(
            pg_host=options.target_pg_host,
            pg_port=options.target_pg_port,
            pg_user=options.target_pg_user,
            pg_db=options.target_pg_db,
            input_path=tmp_dir / "extracted" / "postgres" / "pg_dump.dump",
            pgpassfile=options.pgpassfile_path,
            single_transaction=True,
            timeout_sec=options.pg_restore_timeout_sec,
        )

        # === Step 6: redis のみ stop (R10-F-001 fix: postgres は alive 維持で alembic verify に直接使用) ===
        stop_redis_service_only(options)

        # === Step 7: Redis dump.rdb 置換 + AOF temp 退避 ===
        place_redis_dump_rdb_via_named_volume(
            options,
            tmp_dir / "extracted" / "redis" / "dump.rdb",
            pre_restore_dir,
        )

        # === Step 8: redis のみ up + healthcheck (R10-F-001 fix: postgres は touch しない) ===
        start_redis_service_wait_healthy(options)

        # === Step 9: alembic verify (R2-F-004 fix: postgres alive で直接 verify) ===
        verify_alembic_head_in_db(options)

        # === Step 10: app service up + healthcheck ===
        start_app_services_wait_healthy(options)

        return RestoreResult(reason_code="restore_completed", warnings=tuple(warnings), ...)

    except (
        RestoreRuntimeError,
        RestoreUsageError,
        BackupRuntimeError,         # invoke_pg_dump 内で raise される可能性
        BackupToolNotFoundError,    # subprocess not found path
        OSError,                    # shutil.move / shutil.copy2 / shutil.rmtree / Path 操作の raw error
        shutil.Error,               # shutil 関数固有の compound error
        subprocess.SubprocessError, # subprocess stdlib raw error (TimeoutExpired 等)
        SubprocessTimeoutError,     # R7-F-001 fix: run_safe_subprocess の独自 timeout 例外 (plain Exception subclass)
        SubprocessNotFoundError,    # R7-F-001 fix: run_safe_subprocess の独自 not-found 例外 (plain Exception subclass)
    ) as exc:
        # R6-F-001 CRITICAL fix: rollback chain は raw OSError / shutil.Error も catch、
        # rollback 迂回による部分的 mutation 状態残留を防止。
        original_error_type = type(exc).__name__
        original_error_detail = str(exc)[:200]  # exception detail を rollback log に含める
        if pre_restore_dir is not None:
            try:
                rollback_from_pre_restore_snapshot(pre_restore_dir, options)
                warnings.append(
                    f"restore_rollback_attempted: original={original_error_type}({original_error_detail})"
                )
            except (RestoreRuntimeError, OSError, shutil.Error,
                    subprocess.SubprocessError,
                    SubprocessTimeoutError, SubprocessNotFoundError) as rollback_exc:
                raise RestoreRuntimeError(
                    "restore_rollback_failed",
                    detail=(
                        f"original={original_error_type}({original_error_detail}), "
                        f"rollback_also_failed={type(rollback_exc).__name__}({str(rollback_exc)[:200]})"
                    ),
                ) from rollback_exc
        # original exception を RestoreRuntimeError として再 raise (caller が exit_code に正規化)
        if isinstance(exc, (RestoreRuntimeError, RestoreUsageError)):
            raise
        # OSError / shutil.Error / BackupRuntimeError / SubprocessError は
        # RestoreRuntimeError に wrap (caller の exit_code mapping を統一)
        raise RestoreRuntimeError(
            "restore_rollback_attempted",
            detail=f"non_restore_error_caught_and_rolled_back: {original_error_type}({original_error_detail})",
        ) from exc
    finally:
        # tmp_dir は常に削除 (復号済 tar は機密性高)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        # pre_restore_dir は **保管** (6 month retention、ADR-00021 §321 SOP)
        # 削除は別 operator command (本 batch scope 外)
```

### 3.11 meta.json schema 統一 + forward compatibility (F-012 + R2-F-005 adopt)

**R2-F-005 fix**: PR #77 `build_meta_json` の既存 keys と本 batch の REQUIRED keys 整合化。backup 側を統一名に rename + restore 側 schema 整合:

**Backup 側 patch (PR #77 retro-fix 同梱)** `scripts/taskhub_backup_orchestrator.py:build_meta_json`:

```python
def build_meta_json(
    host_name: str,
    timestamp_utc: datetime,
    postgres_version: str,
    redis_version: str,
    alembic_head: str,
) -> dict:
    """Backup metadata schema v1.0 (R2-F-005 adopt: restore 側との field 名整合)."""
    return {
        "format_version": "1.0",         # R2-F-005 adopt (旧 backup_format_version 削除)
        "host_name": host_name,           # R2-F-005 adopt (旧 host 削除)
        "timestamp_utc": timestamp_utc.isoformat().replace("+00:00", "Z"),  # 旧 timestamp 削除
        "postgres_version": postgres_version,
        "redis_version": redis_version,
        "alembic_head": alembic_head,
    }
```

**既存 test fixture update**: `test_taskhub_backup_orchestrator.py:test_build_meta_json_includes_required_fields` を新 keys で更新。

**Restore 側 schema (新規)**:

```python
REQUIRED_META_KEYS = frozenset({
    "format_version", "host_name", "timestamp_utc",
    "postgres_version", "redis_version", "alembic_head",
})

KNOWN_OPTIONAL_KEYS = frozenset({
    "tenant_id_set", "multi_agent_tables", "schema_extras",
})

SUPPORTED_FORMAT_VERSIONS = frozenset({"1.0"})

def verify_meta_json(meta: dict) -> None:
    if not REQUIRED_META_KEYS.issubset(meta.keys()):
        raise RestoreRuntimeError("restore_meta_json_invalid",
                                  detail=f"missing_required={sorted(REQUIRED_META_KEYS - meta.keys())}")
    fmt_ver = meta.get("format_version")
    if fmt_ver not in SUPPORTED_FORMAT_VERSIONS:
        raise RestoreRuntimeError("restore_meta_json_invalid",
                                  detail=f"unsupported_format_version={fmt_ver}")
    # extra keys は KNOWN_OPTIONAL_KEYS なら accept、unknown は warning emit (deny しない、forward compat)
    unknown_keys = set(meta.keys()) - REQUIRED_META_KEYS - KNOWN_OPTIONAL_KEYS
    if unknown_keys:
        warnings.append(f"restore_meta_json_unknown_keys: {sorted(unknown_keys)}")
```

**Migration impact (PR #77 retro-fix)**: 既存 PR #77 で生成された test fixture archive (existing `meta.json` with `backup_format_version` / `host` / `timestamp`) は本 batch で **format_version 1.0 へ migration patch** で update。production deployment では PR #77 archive は手動再生成 (operator SOP 明記)。

### 3.12 redis subprocess test coverage (F-015 + R15-F-001 adopt: compose exec 経由)

`tests/scripts/test_taskhub_restore_orchestrator.py` で redis 側の subprocess contract も同 fixture density (host TCP test を全て compose exec test に置換):

- `test_invoke_redis_save_sync_via_compose_exec_argv_uses_save_blocking` (R18-F-004 fix: SAVE 採用 + BGSAVE refs 廃止 verify)
- `test_invoke_redis_save_sync_via_compose_exec_tool_not_found_raises`
- `test_invoke_redis_save_sync_via_compose_exec_timeout_raises`
- `test_acquire_redis_data_host_path_returns_named_volume_mount` (docker volume inspect 経由、CONFIG GET 廃止)
- `test_acquire_redis_data_host_path_volume_inspect_failed_raises`

(pg_restore / age と同密度の 5 fixture、全 fixture が compose exec / named volume 経由を verify)

### 3.11.1 R11-F-001 CRITICAL adopt: target binding consistency preflight

Compose project / file が指す deployment と pg_dsn_components / redis_endpoint が **同一を指す**ことを mutation 前に検証する preflight。`run_restore()` Step 1 (archive verification) 完了後、Step 2 (app service stop) 前に実行:

```python
def verify_target_binding_consistency(options: RestoreOptions) -> None:
    """Compose project/file 経由の deployment と署名済 DB/Redis target が同一を指すか verify.

    R11-F-001 CRITICAL fix: 正しく署名されたが自己矛盾した approval record や helper 生成 bug で
    Stack A を止めながら DB B を restore する経路を遮断。
    """
    # 1. docker compose config で services の連絡先を取得 (resolved values)
    result = run_safe_subprocess(
        _compose_argv_prefix(options) + ["config", "--format", "json"],
        config=SafeSubprocessConfig(timeout_sec=30),
    )
    if result.returncode != 0:
        raise RestoreRuntimeError(
            "restore_target_binding_unresolvable",
            detail=f"compose_config_exit={result.returncode}",
        )
    try:
        compose_config = json.loads(result.stdout.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise RestoreRuntimeError(
            "restore_target_binding_unresolvable",
            detail=f"compose_config_json_invalid: {e}",
        ) from None

    services = compose_config.get("services", {})

    # 2. postgres service の published port + container name が DSN と一致 verify
    pg_svc = services.get("postgres")
    if pg_svc is None:
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail="compose_postgres_service_absent",
        )
    pg_ports = pg_svc.get("ports", [])
    pg_published = _extract_published_port(pg_ports, container_port=5432)
    expected_pg_port = options.target_pg_dsn_components["port"]
    if pg_published is None or str(pg_published) != str(expected_pg_port):
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=f"postgres_port_mismatch: compose={pg_published}, claim={expected_pg_port}",
        )

    # 3. redis service の published port が target_redis_endpoint と一致 verify
    redis_svc = services.get("redis")
    if redis_svc is None:
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail="compose_redis_service_absent",
        )
    redis_ports = redis_svc.get("ports", [])
    redis_published = _extract_published_port(redis_ports, container_port=6379)
    expected_redis_host, expected_redis_port_str = options.target_redis_endpoint.split(":")
    if redis_published is None or str(redis_published) != expected_redis_port_str:
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=f"redis_port_mismatch: compose={redis_published}, claim={expected_redis_port_str}",
        )

    # 4. R21-F-001 CRITICAL fix: target_artifacts_dir も Compose deployment と binding verify
    # (a) target_artifacts_dir を absolute + normpath で正規化
    # (b) allowed root prefix list (env `TASKHUB_RESTORE_ALLOWED_ARTIFACTS_ROOTS` or hardcoded default)
    #     のいずれかで始まることを verify。任意の host directory を destructive operation 対象に
    #     できる経路を遮断 (cross-deployment artifacts attack 防御)
    # (c) Compose の任意 service が `target_artifacts_dir` を bind mount している場合は
    #     volume source と一致 verify (任意 service 反映、artifacts は bind mount 想定)
    expected_artifacts_dir = Path(options.target_artifacts_dir).resolve()
    if str(expected_artifacts_dir) != options.target_artifacts_dir:
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=f"artifacts_dir_not_normalized: claim={options.target_artifacts_dir}, resolved={expected_artifacts_dir}",
        )
    # allowed roots: env override or default ('/var/lib/taskhub/artifacts', '~/.taskhub/artifacts')
    allowed_roots_raw = os.environ.get(
        "TASKHUB_RESTORE_ALLOWED_ARTIFACTS_ROOTS",
        f"/var/lib/taskhub/artifacts:{Path.home() / '.taskhub' / 'artifacts'}",
    )
    allowed_roots = [Path(p).resolve() for p in allowed_roots_raw.split(":") if p]
    if not any(
        expected_artifacts_dir == root or expected_artifacts_dir.is_relative_to(root)
        for root in allowed_roots
    ):
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=(
                f"artifacts_dir_not_in_allowed_roots: {expected_artifacts_dir} "
                f"not under any of {allowed_roots}"
            ),
        )

    # (c) R22-F-001 + R23-F-001 CRITICAL fix: artifacts bind mount を **api と worker 両方** で verify
    # + **container destination path** も claim と一致 verify (decoy service / 未使用 container path 防止)
    # decoy attack: ある service A は artifacts bind mount するが api/worker は別 path を使う構成だと
    # restored artifacts が app から見えない → 不整合状態。
    # RestoreApprovalClaim に `target_artifacts_container_path` field 追加 (ADR-00021 で `/app/data/artifacts` 固定)
    REQUIRED_BIND_SERVICES = frozenset({"api", "worker"})
    expected_container_path = options.target_artifacts_container_path  # claim signed 値
    found_in_services: set[str] = set()
    for svc_name in REQUIRED_BIND_SERVICES:
        svc_def = services.get(svc_name)
        if svc_def is None:
            raise RestoreRuntimeError(
                "restore_target_binding_mismatch",
                detail=f"required_service_missing_in_compose: {svc_name}",
            )
        for vol in svc_def.get("volumes", []):
            host_part: Path | None = None
            container_part: str = ""
            if isinstance(vol, str):
                parts = vol.split(":")
                if len(parts) >= 2:
                    host_part = Path(parts[0]).resolve()
                    container_part = parts[1]
            elif isinstance(vol, dict) and vol.get("type") == "bind":
                host_part = Path(vol.get("source", "")).resolve()
                container_part = vol.get("target", "")
            if host_part is None:
                continue
            host_match = (host_part == expected_artifacts_dir) or \
                         expected_artifacts_dir.is_relative_to(host_part)
            container_match = (container_part == expected_container_path)
            if host_match and container_match:
                found_in_services.add(svc_name)
                break

    missing = REQUIRED_BIND_SERVICES - found_in_services
    if missing:
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=(
                f"artifacts_bind_mount_missing_in_services: {sorted(missing)}, "
                f"required_host={expected_artifacts_dir}, required_container={expected_container_path}, "
                f"found={sorted(found_in_services)} (ADR-00021 §126 requires both api+worker)"
            ),
        )

    # 5. R12+R13-F-001 fix: postgres host は **IP loopback 限定**、DNS-resolvable name は禁止
    # claim.host が ('127.0.0.1', '::1') 以外なら deny (R13 fix: 'localhost' / 'postgres' を除外)
    # 'localhost' / container service name は /etc/hosts や Docker DNS resolution で別 host へ向かう経路があり fail-closed 違反
    # cross-host restore は P0 scope 外 (Tailscale 閉域 + local DB 前提)
    expected_pg_host = options.target_pg_dsn_components["host"]
    if expected_pg_host not in ("127.0.0.1", "::1"):
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=f"postgres_host_not_ip_loopback: {expected_pg_host} (claim must use literal 127.0.0.1 or ::1)",
        )

    # 6. R12-F-001 fix: Compose postgres service の environment と claim DB/user 一致 verify
    # docker-compose.yml の postgres env (POSTGRES_DB / POSTGRES_USER) を取得して比較
    pg_env = pg_svc.get("environment", {})
    # Compose v2 では env は dict or list of "K=V" strings 両方ありうる
    pg_env_dict = _normalize_compose_env(pg_env)
    compose_pg_db = pg_env_dict.get("POSTGRES_DB", "")
    compose_pg_user = pg_env_dict.get("POSTGRES_USER", "")
    expected_pg_db = options.target_pg_dsn_components["db"]
    expected_pg_user = options.target_pg_dsn_components["user"]
    if compose_pg_db != expected_pg_db:
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=f"postgres_db_mismatch: compose={compose_pg_db}, claim={expected_pg_db}",
        )
    if compose_pg_user != expected_pg_user:
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=f"postgres_user_mismatch: compose={compose_pg_user}, claim={expected_pg_user}",
        )

    # 7. R12+R13-F-001 fix: redis host も IP loopback 限定 ('localhost'/'redis' 除外)
    if expected_redis_host not in ("127.0.0.1", "::1"):
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=f"redis_host_not_ip_loopback: {expected_redis_host} (claim must use literal 127.0.0.1 or ::1)",
        )

    # 8. R12+R13-F-001 fix: postgres published port は **明示 127.0.0.1 bind 必須** (fail-closed)
    # _extract_host_ip(None) も deny (Compose default 0.0.0.0 相当)、docker-compose.yml 側で
    # 明示 "127.0.0.1:5432:5432" 表記必須を SOP に明記
    pg_host_ip = _extract_host_ip(pg_ports, container_port=5432)
    if pg_host_ip not in ("127.0.0.1", "::1"):
        # R13 fix: None (host_ip 省略) も deny。「明示 127.0.0.1 bind」だけ accept。
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=(
                f"postgres_published_host_ip_not_explicit_loopback: {pg_host_ip} "
                "(docker-compose.yml must use '127.0.0.1:5432:5432' explicit binding)"
            ),
        )
    redis_host_ip = _extract_host_ip(redis_ports, container_port=6379)
    if redis_host_ip not in ("127.0.0.1", "::1"):
        raise RestoreRuntimeError(
            "restore_target_binding_mismatch",
            detail=(
                f"redis_published_host_ip_not_explicit_loopback: {redis_host_ip} "
                "(docker-compose.yml must use '127.0.0.1:6379:6379' explicit binding)"
            ),
        )
```

### 3.11.1.1 R13-F-001 fix: docker-compose.yml SOP prerequisite

本 preflight が PASS するためには、docker-compose.yml の postgres / redis service の `ports:` が **明示的に `127.0.0.1` host_ip を持つ**必要がある:

```yaml
# 必須形式 (R13-F-001 fix prerequisite):
services:
  postgres:
    ports:
      - "127.0.0.1:5432:5432"   # 明示 loopback bind
  redis:
    ports:
      - "127.0.0.1:6379:6379"   # 明示 loopback bind
```

現行 `docker-compose.yml` の bind 設定 verify は本 batch 着手時に実施 (Read で確認)。明示 127.0.0.1 bind でない場合、本 batch 内で **docker-compose.yml も update**して fix する (host-portable deployment + Tailscale 閉域維持 invariant にも整合、ADR-00021 §5 network boundary)。

operator SOP (`docs/deploy/half-yearly-drill-sop.md` §11 prerequisite):
- restore real I/O 実行前に `docker compose config -p <project> -f <abs_path>` で postgres/redis ports に明示 `127.0.0.1:` prefix を確認
- 不在なら restore 実行前に docker-compose.yml 修正

新規 helper:
- `_normalize_compose_env(env)`: dict or list-of-"K=V" 両形式を dict に normalize
- `_extract_host_ip(ports_spec, container_port)`: ports 配列から host_ip を抽出 (long syntax dict / short syntax string 両対応)

新規 reason_code (R12-F-001 fix): `restore_target_binding_mismatch` 内で `postgres_host_not_loopback` / `postgres_db_mismatch` / `postgres_user_mismatch` / `redis_host_not_loopback` / `postgres_published_host_ip_not_loopback` / `redis_published_host_ip_not_loopback` の detail strings 追加。reason_code enum は単一の `restore_target_binding_mismatch` を維持、detail で具体的 mismatch 種別を伝達 (semantic granularity は detail 経由)。

cross-host restore (Tailscale 経由で別 host の DB に restore) は P0 scope 外、ADR-00021 §316 split-brain prevention の延長として **P0.1+ で別 batch / ADR** で扱う。本 batch では同一 host 内 deployment を前提とし、cross-host attempt を fail-closed で deny。

新規 reason_codes 追加:
- `restore_target_binding_unresolvable`: docker compose config 失敗 / JSON 不正
- `restore_target_binding_mismatch`: compose deployment と claim の port / service identity 不一致

`_extract_published_port(ports_spec, container_port)` helper は docker compose の `ports:` 配列 (short syntax "5432:5432" or long syntax dict) から published host port を抽出する pure function、test fixture で cover (long/short/named port 全て)。

run_restore() の order:
1. archive verification (age decrypt / sha256 / tar / checksums / meta)
2. **verify_target_binding_consistency(options)** ← R11-F-001 fix で追加
3. app service stop
4. ... (以降は §3.10 と同じ)

### 3.12.1 R3-F-001 CRITICAL adopt: skip_service_stop 物理 deny for --input real I/O

`taskhub_admin.py:_cmd_restore` で `skip_service_stop=true` + `--input` の組み合わせを CLI argparse 段階で deny:

```python
if args.input and getattr(args, "skip_service_stop", False):
    print("ERROR: --skip-service-stop is rejected for --input (real I/O) path. "
          "Skipping service stop with real I/O causes incomplete restore: "
          "pg_restore + artifacts placement complete but Redis dump.rdb not loaded "
          "and concurrent service writes corrupt the restored state.", file=sys.stderr)
    return 2
```

`RestoreOptions.skip_service_stop` field 自体は **削除** (CLI 経路で deny されるため不要、real I/O orchestrator は常に service stop/start 経由)。これにより:
- `stop_app_services()` / `stop_data_services()` / `start_data_services_wait_healthy()` / `start_app_services_wait_healthy()` から `skip_service_stop` 引数を削除 (no-op path 物理削除)
- `place_redis_dump_rdb_via_named_volume()` も常に実行 (skip path なし)
- skeleton mode は別経路 (現行 `_cmd_restore` の `_skeleton_message` 経路) でのみ提供、real orchestrator 自体に skeleton mode なし

backup 側 (PR #77) も同パターンで `skip_service_stop` を再 review、本 batch では backup の挙動は変更しない (backup は data write でなく read のため fail-closed reasoning が異なる、別 batch で再評価)。

### 3.13 ADR-00021 §184 contract 整合 (R1 adopt 後の scope)

本 batch scope (R1 adopt 反映):
- ✅ age 秘密鍵で復号
- ✅ 全 service stop (Docker compose stop、F-001 adopt 後 in scope)
- ✅ 既存 volume を `_pre-restore-<ts>/` move (3 component snapshot、F-002 adopt)
- ✅ pg_restore + Redis RDB import + artifacts 配置
- ✅ alembic check PASS verify (DB 側 alembic_version、F-014 adopt)
- ✅ service up + healthcheck PASS verify (F-008 adopt 後 in scope)
- ✅ 失敗時 rollback (3 component restore from pre-restore snapshot、F-002 adopt)

### 3.14 DoD gate 文言修正 (F-016 adopt)

Readiness Gate は CRITICAL=0 + HIGH≤2 残存後の判定。"100% adopt" と分離して 2 step に明示:

1. **Step 1**: codex-plan-review R1-R3 で findings を adopt / reject / defer 判定 (100% 採否判定済)
2. **Step 2**: 採否判定後の **adopted CRITICAL/HIGH** が CRITICAL=0 + HIGH≤2 を満たす → Readiness Gate PASS

「100% adopt」と「CRITICAL=0 / HIGH≤2」は別 layer なので、DoD §10 で 2 行に分けて記述。

## 4. 実装範囲 (files NEW / MODIFY)

### 4.1 NEW files

- `scripts/taskhub_restore_orchestrator.py` (~1000 行、scope 拡大による service orchestration / rollback / healthcheck で backup_orchestrator より長い、R2 adopt 反映で更に拡張)
- `tests/scripts/test_taskhub_restore_orchestrator.py` (~800 行、3-layer test = pure / mock / orchestration + rollback + service)
- `tests/deploy/test_taskhub_restore_integration.py` (integration stub、actual tool execution は SP022-T09 carry-over)
- `scripts/test_helpers/generate_restore_approval_record.py` (R2-F-007 adopt: approval issue subcommand 完成前の operator/test helper、Ed25519 署名込みで approval record 生成)

### 4.2 MODIFY files

- `scripts/taskhub_signed_approval.py`:
  - `RestoreApprovalClaim` dataclass 追加 (8 field、F-004 + F-006 adopt 反映)
  - 3 ReasonCode 追加
  - `_extract_restore_claim_from_record()` + `_restore_claims_match()` helper
  - `verify_signed_approval()` + `require_approval_for_destructive()` signature 拡張 (`restore_claim` 引数)
  - `_load_approval_record` の `allowed_keys` に `restore_claim` 追加 (F-PR77-001 backup_claim と同じ pattern)
  - **R2-F-001 CRITICAL retro-fix**: `_rfc8785_canonical_payload_bytes` に `backup_claim` + `restore_claim` を sub-record として含める (signature 改竄防御)
  - **R2-F-001 retro-fix**: `ApprovalRecord` dataclass に `backup_claim` / `restore_claim` field 追加 + loader で load + signature verify path 更新
- `scripts/taskhub_admin.py`:
  - `_cmd_restore()` を skeleton から real orchestration へ昇格
  - `--allow-unsigned-manual-skeleton` を restore で物理 deny
  - `--overwrite` arg 追加 (artifacts dir overwrite policy、F-009 adopt)
  - `--age-identity-file` arg 追加 (F-003 adopt、`TASKHUB_BACKUP_AGE_IDENTITY_FILE` env override)
  - CLI 起動時 `.tar.age` archive sha256 計算 + claim verify (F-006 adopt)
- `scripts/taskhub_backup_orchestrator.py` (PR #77 retro-fix 同梱、R2-F-005 adopt):
  - `build_meta_json` field 名統一: `backup_format_version` → `format_version` / `host` → `host_name` / `timestamp` → `timestamp_utc`
  - `format_version: "1.0"` 書込
- `tests/scripts/test_taskhub_admin.py`: 既存 restore skeleton test を real orchestration expectations へ更新
- `tests/scripts/test_taskhub_admin_security.py`: restore `--allow-unsigned-manual-skeleton` 物理 deny test 追加
- `tests/scripts/test_taskhub_signed_approval.py`:
  - restore_claim 不要 generic test を "verify" subcommand に rename
  - restore_claim verify test 追加
  - **R2-F-001 retro-fix regression test**: `test_backup_claim_in_canonical_payload_signature_protected` (claim 書換で signature_invalid)
  - **R2-F-001 retro-fix regression test**: `test_restore_claim_in_canonical_payload_signature_protected`
  - 既存 PR #75/#77 test fixture を re-sign する migration script を提供 (`scripts/test_helpers/re_sign_approval_records.py`)
- `tests/scripts/test_taskhub_backup_orchestrator.py`:
  - meta.json field name 変更 regression (R2-F-005 adopt: `format_version` / `host_name` / `timestamp_utc`)
- `docs/sprints/SP-022_framework_intake_hardening.md`: Phase 3 / batch 3 完了 record 追記 (Review 章)
- `docs/deploy/half-yearly-drill-sop.md`:
  - §11 SP022-T09 mandatory drill checklist に restore real I/O 検証項目追加 (5 items: age decrypt / archive sha256 / pg_restore / service start / alembic verify)
  - R2-F-007 adopt: approval issue manual flow 1 行追加 (`generate_restore_approval_record.py` helper への参照)
- `pyproject.toml`: `requires-python = ">=3.12,<3.13"` 既設 verify (現行と整合、R2-F-008 adopt)
- `.github/workflows/*.yml`: CI matrix が 3.12 のみであることを verify (R2-F-008 adopt)
- `.claude/reference/task-planning-matrix.md`: SP022-T02 Phase 3 / T08 batch 3 完了 marker 更新
- `docker-compose.yml`: **本 batch で update** (R13-F-001 + R22-F-001 fix):
  - postgres / redis ports に明示 `127.0.0.1:` prefix (`127.0.0.1:5432:5432` / `127.0.0.1:6379:6379`、R13-F-001 fix)
  - api / worker service に artifacts bind mount 追加 (`./data/artifacts:/app/data/artifacts:rw` or ADR-00021 §126 同等、R22-F-001 fix prerequisite)
  - postgres service に unix socket volume mount 確認 (`/var/run/postgresql` exposed、R14-F-001 fix container exec 経由必須)

## 5. 共通インフラ流用 + 拡張 (PR #77 で確立済)

- `scripts/taskhub_subprocess_runner.py` (PR #77 NEW): `run_safe_subprocess()` を pg_restore / age / redis / docker / psql 全て経由
  - `SECRET_ENV_REJECT_PATTERNS` で PGPASSWORD / *_TOKEN / *_KEY / *_PASSWORD reject
  - `STDERR_REDACT_PATTERNS` で private key block / `AGE-SECRET-KEY-` / `password=` redact
- `_ARCHIVE_ALLOWLIST_PATTERNS` / `_ARCHIVE_DENY_FILENAME_PATTERNS` / `_ARCHIVE_DENY_CONTENT_PREFIXES`: backup_orchestrator から import (重複定義避ける)
- `WarningCode` / `ReasonCode` enum: backup と別 module で定義 (restore は orchestration scope が別)
- 新規 size limit constants (`TAR_MAX_TOTAL_SIZE_BYTES` 等) は restore_orchestrator 内に定義

## 6. 検証手順

### 6.1 Unit tests (Layer 1: pure helpers)

`tests/scripts/test_taskhub_restore_orchestrator.py`:

- `test_check_archive_allowed_*` (backup と同 fixture を import で再利用)
- `test_verify_checksums_*` (deterministic sha256 + byte-lex sort)
- `test_extract_meta_json_validates_required_keys`
- `test_extract_meta_json_accepts_known_optional_keys` (F-012 adopt)
- `test_extract_meta_json_warns_unknown_keys` (F-012 adopt)
- `test_extract_meta_json_rejects_unsupported_format_version` (F-012 adopt)
- `test_resolve_pre_restore_path_uses_timestamp`
- `test_verify_python_version_3_12_minimum` (F-007 adopt)
- `test_tar_size_limits_rejected_member_too_large` (F-011 adopt)
- `test_tar_member_count_limit_rejected` (F-011 adopt)
- `test_tar_total_size_limit_rejected` (F-011 adopt)
- `test_sniff_max_read_bytes_constant` (F-011 adopt)
- `test_all_services_healthy_parser` (F-008 adopt healthcheck)

### 6.2 Subprocess mocks (Layer 2)

- `test_invoke_pg_restore_argv_uses_pgpassfile_env_only`
- `test_invoke_pg_restore_argv_includes_single_transaction_clean_if_exists` (F-013 adopt)
- `test_invoke_pg_restore_tool_not_found_raises`
- `test_invoke_pg_restore_timeout_raises`
- `test_invoke_age_decrypt_uses_identity_file_path_via_argv` (F-003 adopt、env injection なし)
- `test_invoke_age_decrypt_redacts_private_key_in_stderr`
- `test_invoke_age_decrypt_identity_file_permission_required_0600_or_0400` (F-003 adopt)
- `test_invoke_age_decrypt_identity_file_symlink_rejected` (F-003 adopt)
- `test_acquire_redis_dump_path_parses_config_get_output` (F-015 adopt)
- `test_acquire_redis_dump_path_tool_not_found_raises` (F-015 adopt)
- `test_invoke_redis_bgsave_argv_uses_password_via_env_allowlist_only` (F-015 adopt)
- `test_invoke_redis_bgsave_redacts_password_in_stderr` (F-015 adopt)
- `test_invoke_redis_save_timeout_raises` (F-015 adopt)
- `test_verify_alembic_head_in_db_via_psql` (F-014 adopt)
- `test_verify_alembic_head_psql_failure_deny` (F-014 adopt)

### 6.3 Orchestration (Layer 3: full mocks)

- `test_run_restore_full_sequence_success`
- `test_run_restore_target_artifacts_dir_in_use_without_overwrite_rejected` (F-009 adopt)
- `test_run_restore_invalid_extension_rejected`
- `test_run_restore_archive_sha256_mismatch_rejected` (F-006 adopt)
- `test_run_restore_archive_allowlist_violation_in_tar`
- `test_run_restore_pg_restore_failure_triggers_3component_rollback` (F-002 adopt)
- `test_run_restore_alembic_mismatch_triggers_rollback` (F-014 + F-002 adopt)
- `test_run_restore_checksums_mismatch_rejected`
- `test_run_restore_meta_json_unknown_keys_warning_only` (F-012 adopt)
- `test_run_restore_meta_json_unsupported_format_version_rejected` (F-012 adopt)
- `test_run_restore_rejects_symlink_input_path`
- `test_run_restore_rejects_when_pgpassfile_not_provided` (F-PR77-003 invariant 継承)
- `test_run_restore_rejects_pgpassfile_with_world_readable_permissions`
- `test_run_restore_postgres_major_version_mismatch_rejected` (F-005 adopt)
- `test_run_restore_service_stop_failure_rejected` (F-001 adopt)
- `test_run_restore_service_start_failure_triggers_rollback` (F-008 adopt)
- `test_run_restore_healthcheck_timeout_triggers_rollback` (F-008 adopt)
- `test_run_restore_skip_service_stop_emits_warning_only`

### 6.4 RestoreApprovalClaim verify tests

- `test_restore_claim_required_when_record_phase1_missing`
- `test_restore_claim_match_full_field_exact`
- `test_restore_claim_mismatch_archive_sha256` (F-006 adopt)
- `test_restore_claim_mismatch_target_pg_dsn_components` (F-004 adopt)
- `test_restore_claim_mismatch_target_redis_endpoint` (F-004 adopt)
- `test_restore_claim_mismatch_target_artifacts_dir` (F-004 adopt)
- `test_restore_claim_mismatch_age_public_key_fingerprint`
- `test_restore_claim_mismatch_expected_postgres_major_version` (F-005 adopt)
- `test_restore_claim_mismatch_expected_alembic_head`
- `test_restore_allow_unsigned_manual_skeleton_rejected_for_restore_subcommand`
- `test_backup_claim_unaffected_by_restore_claim_signature_extension` (regression)

### 6.5 Rollback chain tests (F-002 adopt 専用)

- `test_rollback_restores_artifacts_from_pre_restore_snapshot`
- `test_rollback_restores_db_from_pre_restore_pg_dump`
- `test_rollback_restores_redis_from_pre_restore_dump_rdb`
- `test_rollback_failure_raises_restore_rollback_failed_with_original_context`

### 6.6 Real backend regression

```bash
uv run pytest tests/scripts/test_taskhub_*.py -x  # 既存 129 + 新規 ~60 = 189 fixture 想定
uv run mypy scripts/  # clean
uv run ruff check scripts tests/scripts  # pre-existing UP017 のみ許容
```

## 7. リスク (R1 adopt 後の最新版)

| risk | severity | mitigation |
|---|---|---|
| **age private key reading** | CRITICAL | argv `-i <path>` 経由のみ、env injection なし。`AGE-SECRET-KEY-*` string が log / audit / stderr に漏れないことを `STDERR_REDACT_PATTERNS` で verify (F-003 adopt) |
| **tar extraction path traversal (CVE-2007-4559)** | CRITICAL | Python 3.12+ `extractall(filter='data')` + 抽出前 allowlist sniff (F-007 + F-011 adopt) |
| **tar DoS (decompression bomb / large member)** | CRITICAL | `TAR_MAX_TOTAL_SIZE_BYTES` / `TAR_MAX_MEMBER_SIZE_BYTES` / `TAR_MAX_MEMBER_COUNT` で extraction 前 verify (F-011 adopt) |
| **rollback 失敗で data loss** | CRITICAL | 3 component (artifacts + DB + Redis) snapshot を pre-restore で保持、rollback 失敗時は `restore_rollback_failed` + stderr に manual recovery 手順 hint (F-002 adopt) |
| **split-brain / 稼働中 restore** | CRITICAL | service stop を pg_restore 直前に実行、`restore_service_stop_failed` で fail-closed (F-001 adopt) |
| **archive tamper (checksums.txt + meta.json 同時改竄)** | HIGH | `RestoreApprovalClaim.archive_sha256` を外部 (approval) で固定、CLI 起動時に `.tar.age` 全体 sha256 を再計算して claim と一致 verify (F-006 adopt) |
| **cross-target attack (別 deployment で restore)** | HIGH | `RestoreApprovalClaim` に target_pg_dsn_components / target_redis_endpoint / target_artifacts_dir を含め完全一致 verify (F-004 adopt) |
| **PostgreSQL version drift** | HIGH | `RestoreApprovalClaim.expected_postgres_major_version` + restore 前に `pg_restore --version` / `psql --version` で current host pg major 取得、不一致 deny (F-005 adopt) |
| **subprocess mock と actual tool 挙動の乖離** | MEDIUM | T09 drill で fail。T09 で real execution validation を必須化、本 batch carry-over として明示 |
| **Redis RDB compatibility** | MEDIUM | meta.json.redis_version の major version 一致 verify、不一致は warning + restore 続行 (RDB は backwards compat 通常 OK) |
| **alembic head が backup 後に新規 migration 追加された** | HIGH | meta.json.alembic_head と restore 後 DB alembic_version 厳密一致 verify、新規 migration なら deny + rollback (operator が migrate-up を別途実行する flow を SOP に明記、F-014 adopt) |
| **pre-restore snapshot 蓄積で disk full** | MEDIUM | `_pre-restore-<ts>/` cleanup は manual SOP (ADR-00021 §321、6 month retention)、本 batch では cleanup 自動化しない |
| **cleanup 失敗で機密 (復号済 tar) が残る** | MEDIUM | `try-finally` で tmp_dir 削除、機密性 high content は 0o700 mode + mkdtemp 経由 (F-010 adopt) |
| **service stop 中の Redis 永続化失敗** | MEDIUM | Redis BGSAVE は service stop 前 (pre-restore snapshot 取得時) に実行、stop 後の RDB 一致は subprocess test で fixture cover |

## 8. CRITICAL invariant 直結確認

本 batch は以下の CRITICAL invariant に直結する (`rules/codex-usage-policy.md §14.1`):

1. **SecretBroker raw secret 非保存** (F-003 adopt 強化): age private key を ContextSnapshot / log / audit / env injection 全てに書き込まない、**argv `-i <path>` 経由のみ**
2. **`payload_data_class` / `allowed_data_class` 境界**: restore は provider call を行わないため non-applicable、ただし audit event payload は raw secret なし
3. **Approval 4 整合 + cross-target防御**: `RestoreApprovalClaim` 8 field 拡張で target deployment identity を厳格化 (F-004 adopt)
4. **runner_mutation_gateway**: 本 batch では Docker compose stop/up を扱うため、subprocess 経由のみ + dangerous command fixture (`docker compose up --build`, `docker compose down -v` 等) で argv allowlist check
5. **5+ source enum integrity**: ReasonCode 3 件 (signed_approval) + 17 件 (restore_orchestrator) 追加は test fixture + Literal で 2 source 整合、TaskManagedAI 5+ source 整合は restore-side でのみ確認 (FE 露出なし、本 batch では DB CHECK 拡張なし)

## 9. R{N} adoption log

### R1 (2026-05-20、17 findings 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| F-001 | CRITICAL | risk | service stop scope out で破壊的操作 → split-brain | adopt (scope 格上げ) | §3.5 / §3.13 / §6.3 |
| F-002 | CRITICAL | risk | rollback が artifacts move-back のみ、DB / Redis rollback 欠落 | adopt (3 component snapshot) | §3.6 / §6.5 |
| F-003 | CRITICAL | risk | `*_KEY` env pattern 衝突、SecretBroker invariant 矛盾 | adopt (env 名変更 + argv 渡し) | §3.9 / §7 / §8 |
| F-004 | HIGH | missing | cross-target attack 可能 (RestoreApprovalClaim 不完全) | adopt (8 field 拡張) | §3.1 |
| F-005 | HIGH | inconsistency | pg_dump --version を restore 側で取得は不適切 | adopt (`pg_restore --version` / `psql --version`) | §3.1 / §7 |
| F-006 | HIGH | missing | tar 内 checksums.txt + meta.json 同時改竄 防御不在 | adopt (archive_sha256 claim 固定) | §3.4 / §3.1 |
| F-007 | HIGH | missing | Python 3.12+ gate / fallback 不明 | adopt (pyproject.toml verify + runtime check) | §3.3 / §6.1 |
| F-008 | HIGH | missing | Redis RDB load 実行しない → success 判定不可 | adopt (service restart in scope) | §3.5 / §3.13 |
| F-009 | HIGH | ambiguity | `--overwrite` 常時必須か空 dir 許容か不明 | adopt (target が空でなければ常時必須) | §3.1 / §6.3 |
| F-010 | MEDIUM | missing | cleanup policy 不明 | adopt (try-finally + retention) | §3.10 |
| F-011 | MEDIUM | missing | tar member size limit 不在 (DoS) | adopt (3 上限 constant) | §3.3 / §6.1 |
| F-012 | MEDIUM | inconsistency | meta.json extra keys 即 fail → forward compat 破壊 | adopt (version-aware policy) | §3.11 / §6.1 |
| F-013 | MEDIUM | missing | pg_restore transaction strategy 未定義 | adopt (--single-transaction --clean --if-exists) | §3.7 / §6.2 |
| F-014 | MEDIUM | ambiguity | alembic head verify 対象不明 (local code / DB) | adopt (restore 後 DB alembic_version) | §3.8 / §6.2 |
| F-015 | MEDIUM | missing | redis subprocess contract test 不足 | adopt (5 fixture 追加) | §3.12 / §6.2 |
| F-016 | MEDIUM | inconsistency | DoD gate 意味矛盾 (100% adopt vs HIGH≤2) | adopt (2 step 分離記述) | §3.14 / §10 |
| F-017 | LOW | ambiguity | PGPASSFILE env 名前が backup 固有 | adopt (CLI help + docs で共通明示) | §3.7 |

### R2 (2026-05-20、8 findings 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R2-F-001 | CRITICAL | risk | backup_claim / restore_claim が signature canonical payload に入っていない (PR #77 retro-fix 必要) | adopt (canonical payload に sub-record で含める、`ApprovalRecord` dataclass 拡張、re-sign migration script 追加) | §3.4.1 / §4.2 |
| R2-F-002 | CRITICAL | inconsistency | pre-restore snapshot と service stop の order conflict (postgres down で pg_dump 不能 + artifacts 先 move で中間状態) | adopt (app stop → snapshot → data stop → restore → start の 6 step order、§3.5/§3.10 で明示) | §3.5 / §3.10 |
| R2-F-003 | HIGH | inconsistency | Redis dump.rdb host shutil.copy2 が container path に書込 + AOF 優先で load されない | adopt (named volume host path inspect + AOF temp 退避 + redis restart で RDB load) | §3.5 (place_redis_dump_rdb_via_named_volume) |
| R2-F-004 | HIGH | risk | alembic verify が start_services 後 → 不整合 schema を app に露出 | adopt (data services start 後 / app services start **前** に alembic verify、§3.10 order 修正) | §3.5 / §3.10 |
| R2-F-005 | HIGH | inconsistency | meta.json schema が PR #77 既存と不一致 (`backup_format_version`/`host`/`timestamp` vs `format_version`/`host_name`/`timestamp_utc`) | adopt (backup 側を新 field 名に統一 + 既存 test fixture migration) | §3.11 / §4.2 |
| R2-F-006 | HIGH | risk | healthcheck timeout 60s が現行 compose 設定 (interval 30s × retries 3) より短い → false rollback | adopt (data 120s / app 180s に延長、poll 5s) | §3.5 |
| R2-F-007 | HIGH | missing | archive_sha256 caller 計算 flow が CLI に入口なし (`taskhub approval issue` 未実装) | adopt (test helper script `generate_restore_approval_record.py` + operator SOP 1 行追加 + batch 4 carry-over marker) | §3.4 / §4.1 |
| R2-F-008 | HIGH | inconsistency | CI matrix 3.12/3.13 と pyproject.toml `<3.13` 上限が矛盾 | adopt (CI matrix 3.12 のみと plan 明記、3.13 言及削除、将来拡張は別 PR) | §3.3 / §4.2 |

### R3 (2026-05-20、2 findings 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R3-F-001 | CRITICAL | risk | `skip_service_stop=true` 経由で不完全 restore (Redis dump load なし + 稼働中 write) が成功扱い | adopt (CLI argparse で物理 deny + `RestoreOptions.skip_service_stop` field 削除 + helper の skip path 削除) | §3.1 / §3.12.1 |
| R3-F-002 | CRITICAL | inconsistency | rollback が postgres alive 前提だが、data services stop 後の失敗で postgres stopped/unhealthy → rollback の pg_restore 自体が失敗 | adopt (rollback 開始時に `start_data_services_wait_healthy()` を first step で実行、postgres alive 保証) | §3.6 (rollback_from_pre_restore_snapshot Step 0) |

### R4 (2026-05-20、1 finding 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R4-F-001 | CRITICAL | risk | rollback Step 0 が `start_data_services_wait_healthy()` 先行で、app start 途中失敗時に api/worker partial-up + DB/Redis 復活時間帯で restored data 書込 → pre-restore state 汚染 race | adopt (Step 0a で `stop_app_services()` を **最優先実行**、app 完全停止後に data services restart) | §3.6 (rollback Step 0a / 0b 分割) |

### R5 (2026-05-20、1 finding 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R5-F-001 | CRITICAL | risk | rollback Step 0b で `start_data_services_wait_healthy()` (postgres + redis) を呼ぶため、Redis 起因の RDB/AOF/権限 failure で DB rollback にも到達不能 → 完全復旧不能 | adopt (Step 0b を `start_postgres_wait_healthy()` に絞る、Redis は Step 4-5 で分離扱い、Redis 失敗時は `restore_rollback_failed` + SOP manual recovery hint) | §3.6 (rollback Step 0b + Step 4-5 分離) |

### R6 (2026-05-20、1 finding 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R6-F-001 | CRITICAL | risk | `except RestoreRuntimeError:` のみで rollback 起動、shutil.move / shutil.copy2 / shutil.rmtree / Docker subprocess の raw `OSError` / `PermissionError` / `shutil.Error` / `SubprocessError` が rollback を迂回 → 部分的 mutation 残留 | adopt (`except (RestoreRuntimeError, RestoreUsageError, BackupRuntimeError, BackupToolNotFoundError, OSError, shutil.Error, subprocess.SubprocessError)` で広く catch + non-RestoreRuntimeError は wrap + nested rollback exception も同様広 catch) | §3.10 run_restore except 範囲拡張 |

### R7 (2026-05-20、1 finding 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R7-F-001 | CRITICAL | risk | `run_safe_subprocess()` 独自 `SubprocessTimeoutError` / `SubprocessNotFoundError` は `subprocess.SubprocessError` ではなく plain `Exception` subclass、rollback catch 範囲外 → service orchestration subprocess の timeout / not-found で rollback 迂回 | adopt (except clause に `SubprocessTimeoutError` / `SubprocessNotFoundError` 追加、nested rollback exception も同様) | §3.10 except 範囲拡張 |

### R8 (2026-05-20、1 finding 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R8-F-001 | CRITICAL | risk | docker compose stop/up / volume inspect が ambient cwd / `COMPOSE_PROJECT_NAME` env 依存、承認 target と実 Compose deployment ずれで別 app 稼働中 DB restore / 別 Redis volume 置換経路残存 | adopt (RestoreApprovalClaim に `target_compose_project_name` + `target_compose_file_path` 追加、全 docker compose 系 subprocess に `-p <project> -f <abs_path>` 明示、`acquire_redis_data_host_path` も project name signed 値経由) | §3.1 / §3.5 _compose_argv_prefix helper |

### R9 (2026-05-20、2 findings 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R9-F-001 | CRITICAL | inconsistency | R8-F-001 修正が `_compose_argv_prefix(options)` 定義のみ、`stop_data_services()` / `start_data_services_wait_healthy()` / `start_app_services_wait_healthy()` / 新規 rollback helper は ambient `docker compose ...` 直書きのまま残存 | adopt (全 service helper の signature を `(options: RestoreOptions)` に統一、`_compose_argv_prefix(options)` 経由で project + file 明示、`_wait_services_healthy` も同様、run_restore 内の caller も全て options 渡しに更新) | §3.5 全 helper rewrite + §3.10 caller update |
| R9-F-002 | CRITICAL | inconsistency | §3.4.1 canonical payload に `target_compose_project_name` / `target_compose_file_path` 含まれず、claim 改竄で R8-F-001 防御無効化 | adopt (canonical payload restore_claim sub-record に両 field 追加、sorted key 内で alphabetical order を維持) | §3.4.1 _rfc8785_canonical_payload_bytes update |

### R10 (2026-05-20、1 finding 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R10-F-001 | CRITICAL | risk | 正常系 Step 6 `stop_data_services(options)` が postgres + redis 両方停止、Redis dump 置換に postgres restart は不要、postgres restart 失敗時は復元済 DB から rollback 不能 | adopt (Step 6 を `stop_redis_service_only(options)` に、Step 8 を `start_redis_service_wait_healthy(options)` に、postgres は restore 中ずっと alive 維持) | §3.10 Step 6 / 8 修正 |

### R11 (2026-05-20、1 finding 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R11-F-001 | CRITICAL | risk | Compose project/file 経由 deployment と claim 内 pg_dsn / redis_endpoint の整合 preflight 不在、自己矛盾した approval record で Stack A 停止 + DB B restore 経路残存 | adopt (`verify_target_binding_consistency(options)` 新規追加、docker compose config --format json から services の published ports を取得し pg/redis port 一致 verify、Step 1.5 で実行、`restore_target_binding_unresolvable` / `_mismatch` 2 reason_code 追加) | §3.11.1 / §3.10 Step 1.5 |

### R12 (2026-05-20、1 finding 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R12-F-001 | CRITICAL | risk/security | preflight が静的 config + port-only で identity proof 不足、claim host が別ホストでも port 一致で通過 / 同一 host:port の別 DB/user も Compose 側 app/worker 設定と照合されない | adopt (preflight 5 追加 check: postgres host loopback 限定 / Compose POSTGRES_DB/USER vs claim db/user 一致 / redis host loopback 限定 / postgres published host_ip loopback bind 限定 / redis published host_ip loopback bind 限定、cross-host restore は P0 scope 外として明示) | §3.11.1 verify_target_binding_consistency 拡張 |

### R13 (2026-05-20、1 finding 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R13-F-001 | CRITICAL | security | published host_ip bind check が fail-closed 違反 (None / DNS-resolvable name 通過、Compose short syntax `5432:5432` で 0.0.0.0 bind 相当が通る、claim host allowlist の 'postgres'/'redis'/'localhost' は DNS 解決で別 host を指せる) | adopt (host allowlist を ('127.0.0.1','::1') IP literal のみに限定 / _extract_host_ip(None) も deny / docker-compose.yml に明示 '127.0.0.1:' prefix 必須を SOP prerequisite で明記、本 batch で docker-compose.yml の bind 設定 verify + 必要なら update) | §3.11.1 fail-closed 強化 / §3.11.1.1 SOP prerequisite |

### R14 (2026-05-20、1 finding 100% adopt — root cause fix scope expansion)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R14-F-001 | CRITICAL | security/data-integrity | 静的 config check では runtime listener ownership 証明できず、Compose stack 停止中 / 別プロセス・別 Compose project が同 loopback port を握ると foreign DB/Redis 経路残存 | adopt (root cause fix: pg_restore / pg_dump / redis-cli を **全て `docker compose exec` 経由 + container 内 unix socket** に切替、host TCP 経由廃止 / PGPASSFILE 廃止 / SafeSubprocessConfig に stdin_data / stdout_file 追加 / backup_orchestrator (PR #77 retro-fix) にも遡及適用 / docker-compose.yml unix socket verify) | §3.7-3.7.4 全面書換 |

### R15 (2026-05-20、2 findings 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R15-F-001 | CRITICAL | security/data-integrity | R14 fix が pg_restore のみ、verify_alembic_head_in_db (psql) / rollback の pg_restore + pg_dump / acquire_redis_dump_path (CONFIG GET) は host TCP 経由のまま残存 → 別 listener 経由の誤復旧経路 | adopt (verify_alembic_head_in_db を compose exec 経由 / create_pre_restore_snapshot の pg_dump + redis BGSAVE を compose exec 経由 / rollback の invoke_pg_restore も compose exec 経由 / redis subprocess test も compose exec 版に置換) | §3.6 / §3.8 / §3.12 全 host TCP path 排除 |
| R15-F-002 | CRITICAL | reliability/data-integrity | `stdin_data=f.read()` で 10 GiB dump をメモリ全 load → OOM kill、Python rollback catch に入らず DB 部分 restore 後の中間状態残留 | adopt (`stdin_file: BinaryIO` parameter に変更、subprocess.Popen の stdin に file object 直接渡し、kernel streaming pipe で memory 使用最小化、`stdin_data: bytes` は採用しない方針) | §3.7 invoke_pg_restore_via_compose_exec stream pattern |

### R16 (2026-05-20、2 findings 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R16-F-001 | CRITICAL | data-integrity/rollback | BGSAVE 発行直後の dump.rdb copy で BGSAVE 完了前の古い RDB を rollback snapshot として保存 → stale dump へ戻すと直前 Redis 書込が失われても rollback 成功扱い | adopt (LASTSAVE timestamp polling: 初期値取得 → BGSAVE 発行 → LASTSAVE 増加 wait 5min timeout → 増加後に dump.rdb copy、`restore_pre_restore_redis_bgsave_failed` reason_code 追加) | §3.6 create_pre_restore_snapshot BGSAVE wait |
| R16-F-002 | CRITICAL | security/data-integrity | sha256 verify と age_decrypt の間で input_path swap される TOCTOU (symlink reject だけでは通常 file の rename/replace 防げない) | adopt (`verify_archive_sha256_and_decrypt_streaming`: 同一 fd で sha256 streaming + seek 0 + age stdin pipe、path 経由 2 回 open を物理排除) | §3.4 TOCTOU 排除 / §3.10 Step 1 update |

### R17 (2026-05-20、4 findings 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R17-F-001 | CRITICAL | data-integrity/rollback | 既存進行中 BGSAVE 完了による LASTSAVE 増加を新 BGSAVE 完了と誤認、古い RDB を rollback snapshot として保存 | adopt (BGSAVE+LASTSAVE wait を廃止、blocking `SAVE` command 採用、Redis spec で SAVE return = dump.rdb 完全書込済 race-free、operational SOP に blocking 注意明記) | §3.6 invoke_redis_save_sync_via_compose_exec |
| R17-F-002 | CRITICAL | security/data-integrity | same fd でも inode in-place overwrite/truncate は防げない、hash 計算後 decrypt 前の file 内容書換 race | adopt (`O_NOFOLLOW` open + `flock LOCK_EX|LOCK_NB` 排他 lock + `st_ino+st_size+st_ctime_ns` triple compare before/after で in-place mutation 物理排除) | §3.4 verify_archive_sha256_and_decrypt_streaming 強化 |
| R17-F-003 | CRITICAL | data-integrity/rollback | rollback Step 4 で `redis_aof_backup` を move する前に既存新 appendonlydir / dump.rdb を削除しないため、新 AOF 優先で stale data 再 load | adopt (rollback Step 4 で `new_dump_rdb.unlink()` + `shutil.rmtree(new_aof_dir)` を明示実行、clean slate 確保してから snapshot 配置) | §3.6 rollback Step 4 clean-slate 化 |
| R17-F-004 | CRITICAL | data-integrity/target-binding | Redis volume 名 `<project>_redis_data` を推測、`external` / `name:` / bind mount で別 volume 触る経路 / 別 deployment volume 破壊 | adopt (volume 名推測廃止、`docker compose ps -q redis` で container ID → `docker inspect --format '{{json .Mounts}}'` で `/data` destination の Source path を実取得、external/named/bind mount 全対応) | §3.5 acquire_redis_data_host_path runtime inspect 化 |

### R18 (2026-05-20、4 findings 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R18-F-001 | CRITICAL | reliability/data-integrity | `compose ps -q redis` が Redis stopped 後に container ID 空 → dump placement / rollback で acquire_redis_data_host_path 失敗 | adopt (`compose ps --all -q redis` で stopped container も取得) | §3.5 |
| R18-F-002 | CRITICAL | data-integrity/rollback | create_pre_restore_snapshot 内 artifacts move 後の pg_dump 失敗で outer pre_restore_dir が None 残り、rollback 起動不能 | adopt (`register_dir: Callable[[Path], None]` callback parameter 追加、artifacts move 完了直後に outer に登録、後続失敗でも rollback 起動可能) | §3.6 / §3.10 Step 3 |
| R18-F-003 | CRITICAL | security/data-integrity | `flock` は advisory lock、非協調 writer / 同 user in-place write を block しない、stat 比較窓内 mutation も race | adopt (hardlink (or fallback copy) で input を immutable stage に snapshot 化、stage 上で sha256 verify + age decrypt、元 path mutation と無関係に完結) | §3.4 verify_archive_sha256_and_decrypt_via_immutable_stage |
| R18-F-004 | CRITICAL | inconsistency/data-integrity | §3.7.2 にまだ `invoke_redis_save_via_compose_exec` (BGSAVE) helper 残存、blocking SAVE fix が実装側に drift | adopt (BGSAVE helper + LASTSAVE helper を完全削除、`invoke_redis_save_sync_via_compose_exec` (SAVE) のみ単一 entry point、test name も SAVE 化) | §3.7.2 / §3.12 |

### R19 (2026-05-20、2 findings 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R19-F-001 | CRITICAL | security/data-integrity | hardlink は同 inode 共有、元 input への in-place overwrite/truncate が stage 側にも反映、chmod 0o400 も同 inode mode 変更のみで既存 writable fd を止められない | adopt (hardlink 廃止、`cp --reflink=auto` で別 inode reflink/CoW copy、未対応 fs なら `shutil.copy2` で pure byte copy (disk 2x))、stage は完全別 inode で隔離 | §3.4 hardlink → full copy |
| R19-F-002 | CRITICAL | data-integrity/rollback | rollback Step 4 (Redis) / Step 3 (DB) が snapshot file 存在前提、artifacts move のみ完了 + DB/Redis snapshot 未完成での rollback で current dump.rdb/AOF を wipe → pre-restore data 破壊 | adopt (rollback で pre_restore_dump.rdb / pre_restore_pg_dump.dump 存在 verify、不在なら component rollback skip + warning + `_skipped_no_pre_snapshot` reason_code) | §3.6 rollback per-component existence verify |

### R20 (2026-05-20、2 findings 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R20-F-001 | CRITICAL | data-integrity/rollback | snapshot を最終 path に直接 write、部分 file 残留で rollback の exists() が突破、Redis copy 途中失敗で partial RDB を rollback 配置 → pre-restore data 破壊 | adopt (`.tmp` suffix で write → 完成後 `os.rename` で atomic 最終 path 化、`exists()` が真の "完成済" を保証、失敗時 tmp file 削除) | §3.6 atomic rename pattern |
| R20-F-002 | CRITICAL | security/data-integrity | tarfile `data` filter は root 内 symlink/hardlink を許可、artifacts 別 dir 配置で root 外参照経路 → arbitrary file 参照 / rollback rmtree 逸脱 | adopt (`_verify_tar_members_safe` で extractall 前に symlink/hardlink/device/fifo を明示 reject、filter='data' と二重防御) | §3.3 extraction policy 強化 |

### R21 (2026-05-20、1 finding 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R21-F-001 | CRITICAL | security/data-integrity | target_artifacts_dir が signed claim にあるが Compose / allowed-root binding 検証なし、正しい stack 停止 + 任意 host directory への destructive operation (shutil.move/rmtree/place_artifacts) 経路 | adopt (verify_target_binding_consistency に追加: artifacts_dir normalize + allowed root prefix verify (env `TASKHUB_RESTORE_ALLOWED_ARTIFACTS_ROOTS` or default `/var/lib/taskhub/artifacts:~/.taskhub/artifacts`) + Compose service bind mount source 一致 verify) | §3.11.1 artifacts binding |

### R22 (2026-05-20、1 finding 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R22-F-001 | CRITICAL | security/data-integrity | artifacts bind mount verify が break するだけで found flag set されず、ループ後 deny なし → 一致 mount 不在でも pass、現行 docker-compose.yml も artifacts bind mount 不在で ADR-00021 §126 drift | adopt (`artifacts_bind_found` flag 導入 + 不在で fail-closed deny + docker-compose.yml に api/worker artifacts bind mount 追加) | §3.11.1 artifacts found flag + docker-compose.yml update |

### R23 (2026-05-20、1 finding 100% adopt)

| ID | severity | category | symptom | adopt status | plan section |
|---|---|---|---|---|---|
| R23-F-001 | CRITICAL | security/data-integrity | artifacts bind verify が「どれか 1 service」で PASS → decoy service / 未使用 container path bind mount でも通る、api/worker が実 read する path と無関係に restore 成功扱い | adopt (`REQUIRED_BIND_SERVICES = {api, worker}` 両方一致必須 + RestoreApprovalClaim に `target_artifacts_container_path` field 追加 + host_match + container_match の 2 条件で verify) | §3.1 claim 拡張 / §3.4.1 canonical payload / §3.11.1 verify_target_binding_consistency 強化 |

## 10. DoD (Definition of Done)

R1 F-016 adopt 反映、2 step 分離:

### Step 1: codex-plan-review findings 採否判定

- [x] R1 17 findings 全件 adopt 判定済 (R1 adoption log §9 参照)
- [x] R2 8 findings 全件 adopt 判定済 (R2 adoption log §9 参照、PR #77 retro-fix 同梱)
- [x] R3 2 findings 全件 adopt 判定済 (R3 adoption log §9 参照、skip_service_stop 物理 deny + rollback start_data_services first step)
- [x] R4 1 finding 全件 adopt 判定済 (R4 adoption log §9 参照、rollback Step 0a で app stop 最優先実行 + partial-up race 防止)
- [x] R5 1 finding 全件 adopt 判定済 (R5 adoption log §9 参照、rollback Step 0b を postgres only に絞る + Redis 分離 + SOP manual recovery hint)
- [x] R6 1 finding 全件 adopt 判定済 (R6 adoption log §9 参照、run_restore except 範囲を OSError/shutil.Error/SubprocessError まで拡張 + nested rollback exception も同様拡張)
- [x] R7 1 finding 全件 adopt 判定済 (R7 adoption log §9 参照、SubprocessTimeoutError/SubprocessNotFoundError を except clause に追加)
- [x] R8 1 finding 全件 adopt 判定済 (R8 adoption log §9 参照、claim に compose_project_name + compose_file_path 追加、全 docker subprocess に -p / -f flag 明示、ambient 依存禁止)
- [x] R9 2 findings 全件 adopt 判定済 (R9 adoption log §9 参照、全 service helper を _compose_argv_prefix(options) 経由に統一 + canonical payload に compose project/file 追加)
- [x] R10 1 finding 全件 adopt 判定済 (R10 adoption log §9 参照、正常系 Step 6/8 を redis-only stop/start に変更、postgres は restore 中常時 alive)
- [x] R11 1 finding 全件 adopt 判定済 (R11 adoption log §9 参照、target binding consistency preflight 追加、docker compose config 経由で port 一致 verify、2 reason_code 追加)
- [x] R12 1 finding 全件 adopt 判定済 (R12 adoption log §9 参照、preflight 5 check 拡張: host loopback 限定 + POSTGRES_DB/USER 一致 + published host_ip bind verify)
- [x] R13 1 finding 全件 adopt 判定済 (R13 adoption log §9 参照、host allowlist を IP literal ('127.0.0.1','::1') のみに限定 / _extract_host_ip(None) も fail-closed deny / docker-compose.yml 明示 127.0.0.1 bind を SOP prerequisite で必須化)
- [x] R14 1 finding 全件 adopt 判定済 (R14 adoption log §9 参照、root cause fix: pg_restore/pg_dump/redis-cli を全て docker compose exec 経由 + container 内 unix socket、host TCP + PGPASSFILE 廃止、SafeSubprocessConfig 拡張、backup_orchestrator にも遡及適用)
- [x] R15 2 findings 全件 adopt 判定済 (R15 adoption log §9 参照、host TCP path 完全排除 (verify_alembic / pre-restore snapshot / rollback) + OOM 防止 stdin streaming pipe)
- [x] R16 2 findings 全件 adopt 判定済 (R16 adoption log §9 参照、Redis BGSAVE LASTSAVE wait + TOCTOU 排除 (sha256 + age decrypt を same fd で streaming))
- [x] R17 4 findings 全件 adopt 判定済 (R17 adoption log §9 参照、Redis blocking SAVE 採用 + flock LOCK_EX + inode triple compare + rollback clean-slate + docker inspect 実 mount source)
- [x] R18 4 findings 全件 adopt 判定済 (R18 adoption log §9 参照、compose ps --all + register_dir callback + immutable stage hardlink + BGSAVE helper 完全削除)
- [x] R19 2 findings 全件 adopt 判定済 (R19 adoption log §9 参照、hardlink → 別 inode reflink copy + rollback per-component snapshot existence verify)
- [x] R20 2 findings 全件 adopt 判定済 (R20 adoption log §9 参照、snapshot atomic rename (`.tmp` → final) + tar member symlink/hardlink 明示 reject)
- [x] R21 1 finding 全件 adopt 判定済 (R21 adoption log §9 参照、artifacts_dir binding verify: normalize + allowed root + Compose bind mount source 一致)
- [x] R22 1 finding 全件 adopt 判定済 (R22 adoption log §9 参照、artifacts_bind_found flag fail-closed deny + docker-compose.yml api/worker artifacts bind mount 追加)
- [x] R23 1 finding 全件 adopt 判定済 (R23 adoption log §9 参照、REQUIRED_BIND_SERVICES = {api, worker} 両方必須 + target_artifacts_container_path claim 追加 + host + container 2 条件 verify)

### Step 2: Readiness Gate

- [ ] R{N} 終了時、**adopted findings の CRITICAL=0 + HIGH ≤ 2** を達成 → READY
- [ ] BLOCKED 残存時は AskUserQuestion で受容理由を `accepted-high.md` に記録

### Step 3: 実装 DoD

- [ ] `scripts/taskhub_restore_orchestrator.py` 新規実装、CRITICAL invariant 全件 verify
- [ ] `scripts/taskhub_signed_approval.py` `RestoreApprovalClaim` (8 field) + 3 ReasonCode + helper 追加
- [ ] `scripts/taskhub_admin.py` `_cmd_restore` real orchestration 化 + archive sha256 verify
- [ ] `scripts/taskhub_backup_orchestrator.py` meta.json `format_version: "1.0"` 書込 (F-012 adopt)
- [ ] `tests/scripts/test_taskhub_*.py` 全 PASS (既存 129 + 新規 ~60 fixture)
- [ ] `uv run mypy scripts/` clean
- [ ] `uv run ruff check scripts tests/scripts` pre-existing 以外 clean
- [ ] PR 起票後 codex_pr_full_review 全件 adopt → admin merge bypass
- [ ] SP-022 Sprint Pack `## Review` 章に Phase 3 / batch 3 完了 record
- [ ] SP022-T09 drill SOP に restore real I/O 検証 5 items 追加
- [ ] T08 carry-over marker: batch 4 (remote split-brain detection + `--rollback` standalone real I/O) を SP-022 Pack で明示
- [ ] `.claude/reference/task-planning-matrix.md` SP022-T02 Phase 3 / T08 batch 3 完了 marker 更新
- [ ] `pyproject.toml` `requires-python = ">=3.12"` 既設 verify (不在なら追加)
