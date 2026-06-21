"""LocalSecretStore: 簡易 local secret material store (ADR-00058)。

SOPS+age は後フェーズ (D-4)。Phase 0 は local Mac 実運用 target として macOS Keychain (``keyring``)
を先行採用し、CI Linux / headless 等の Keychain 不在環境のみ ``cryptography`` Fernet 暗号化ファイルに
fallback する。**raw material は DB に保存しない** (DB は secret_ref metadata のみ)。

material key は **``tenant_id + secret_ref_id`` (DB 上一意な所有者) に束縛** する。name の sha256 だけ
だと cross-tenant 同名 secret が衝突・誤解決するため不可 (ADR-00058 finding-2)。

2 mode:

- **keyring mode** (local Mac、Keychain 利用可): material を Keychain に直接格納 (OS-level 保護、
  Fernet 不要)。
- **file mode** (keyring 不在 / 無効): Fernet で暗号化し ``secrets.d/<tenant>/<id>.enc`` (0o600) に格納。
  master key は **ciphertext と別 dir** ``keyring.d/master.key`` (0o600) に保存 (key 非同居、
  ADR-00058 finding R16-2)。紛失時は復号不能 = material loss → 該当 secret_ref を revoked + 再登録で
  recovery (rollback=再登録、ADR-00059)。

本 store は **broker 内部専用**。resolve() が返す raw material は broker / RepoProxy 境界の内部でのみ
扱い、caller / AI / runner env / artifact / audit に出さない (SecretBroker §10)。
"""

from __future__ import annotations

import base64
import errno
import os
import tempfile
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

try:  # keyring は optional (ADR-00020 Framework Intake)。不在環境は Fernet file fallback。
    import keyring as _keyring
    from keyring.errors import KeyringError as _KeyringError
    from keyring.errors import PasswordDeleteError as _PasswordDeleteError
except ImportError:  # pragma: no cover - depends on environment
    _keyring = None  # type: ignore[assignment]

    class _KeyringError(Exception):  # type: ignore[no-redef]
        pass

    class _PasswordDeleteError(_KeyringError):  # type: ignore[no-redef]
        pass


def _require_keyring() -> Any:  # noqa: ANN401 - keyring は untyped な third-party module
    """keyring module を返す (不在は LocalSecretStoreError)。keyring mode でのみ呼ばれる。"""
    if _keyring is None:  # pragma: no cover - keyring mode に入る時点で None ではない
        raise LocalSecretStoreError("keyring backend not available")
    return _keyring


_DEFAULT_BASE_DIR_ENV: Final = "TASKHUB_SECRETS_HOME"
_DISABLE_KEYRING_ENV: Final = "TASKHUB_DISABLE_KEYRING"
_DEFAULT_BASE_DIR: Final = "~/.taskhub"

_MATERIAL_KEYRING_PREFIX: Final = "taskhub-material"
_MATERIAL_KEYRING_ACCOUNT: Final = "material"
_PROBE_SERVICE: Final = "taskhub-keyring-probe"
_PROBE_ACCOUNT: Final = "probe"

_SECURE_FILE_MODE: Final = 0o600
_SECURE_DIR_MODE: Final = 0o700

# deployment の物理 backend (keyring|file) を pin する non-secret marker (Codex R11-F1)。
# runtime 検出 backend が marker と drift したら fail-closed (別 backend の no-op 削除で false-purged
# になるのを防ぐ)。base_dir 直下に置き、両 mode で共有する。
_BACKEND_MARKER_NAME: Final = "backend.marker"
_BACKEND_KEYRING: Final = "keyring"
_BACKEND_FILE: Final = "file"


class LocalSecretStoreError(Exception):
    """LocalSecretStore の一般エラー (raw material を message に含めない)。"""


class LocalSecretMaterialNotFound(LocalSecretStoreError):
    """指定 (tenant_id, secret_ref_id) の material が store に存在しない。"""


class LocalSecretStorePermissionError(LocalSecretStoreError):
    """master key / ciphertext file の permission が安全側でない (0o600 必須)。"""


class LocalSecretStore:
    """broker-owned local material の key-value store (keyring 主 + Fernet file fallback)。"""

    def __init__(
        self,
        *,
        base_dir: Path | None = None,
        use_keyring: bool | None = None,
    ) -> None:
        if base_dir is not None:
            self._base_dir = base_dir.expanduser()
        else:
            env_dir = os.environ.get(_DEFAULT_BASE_DIR_ENV)
            self._base_dir = Path(env_dir).expanduser() if env_dir else Path(_DEFAULT_BASE_DIR).expanduser()
        self._secrets_dir = self._base_dir / "secrets.d"
        self._keyring_dir = self._base_dir / "keyring.d"
        self._use_keyring = self._detect_keyring(use_keyring)

    # ---- public API (sync; resolver が to_thread で wrap) ----

    @property
    def uses_keyring(self) -> bool:
        return self._use_keyring

    def is_initialized(self) -> bool:
        """backend marker が pin 済か (= 既に first-store 済の deployment か、Codex R23-F1)。

        service が fresh first-init と marker-loss-recovery を区別するために使う。破損 / insecure marker は
        ``_read_marker_backend`` が fail-closed (LocalSecretStorePermissionError) するため、ここでも伝播する。
        """
        return self._read_marker_backend() is not None

    def ensure_initialized(self) -> None:
        """material 書込より前に backend marker を durable に pin する (Codex R14-F1)。

        register()/rotate() は pending+writing の DB owner row を store 書込より前に commit するため、
        marker pin を store() に任せると「DB row commit 後 / store() 前」の crash window で marker 不在の
        まま row が残る。後続 gc の delete() は marker 必須で fail-closed のため、その row は永久に purge
        収束できない。caller はこの method を **DB row commit 前**に呼び、marker を先に pin する。
        """
        self._ensure_marker_pinned()

    def store(self, tenant_id: int, secret_ref_id: UUID, raw: bytes) -> None:
        """material を idempotent に書き込む (既存は上書き)。raw は bytes。

        material 書込前に backend marker を **atomic に pin** する (Codex R12-F1): O_CREAT|O_EXCL で
        初回作成し、既存なら re-read して現在 backend と一致を verify する。concurrent first-store race で
        loser が別 backend を書くと marker と乖離するため、material 書込前に marker と現在 backend の一致を
        必ず確認する (mismatch は drift で fail-closed)。
        """
        self._ensure_marker_pinned()
        if self._use_keyring:
            self._keyring_set(tenant_id, secret_ref_id, raw)
            return
        self._file_store(tenant_id, secret_ref_id, raw)

    def resolve(self, tenant_id: int, secret_ref_id: UUID) -> bytes:
        """material を返す。不在は LocalSecretMaterialNotFound。broker 内部専用。

        marker 不在 / drift は fail-closed (Codex R11/R12-F1): authoritative backend を確定できない状態で
        現在 backend を読むと、別 backend の material を見落として誤った not-found を返す危険があるため。

        custody 例外正規化 (Codex R19-F1): file read の PermissionError、破損 master.key による
        ``Fernet()`` 構築 ``ValueError``、keyring 値の base64 decode 失敗など、backend/corruption/permission
        例外を **すべて ``LocalSecretStoreError`` 系へ正規化**する。これにより broker redeem の custody-error
        catch (``_RESOLVER_CUSTODY_ERRORS``) が確実に拾い、token revoke + denied audit + material_not_present
        へ落ちる (raw exception が broker へ漏れて denied 経路を bypass し 500/rollback 依存になるのを防ぐ)。
        ``LocalSecretMaterialNotFound`` (= not-found) はそのまま伝播 (custody error として正しく扱われる)。
        raw secret は message に含めない。
        """
        self._assert_backend_consistent(require_marker=True)
        try:
            if self._use_keyring:
                return self._keyring_get(tenant_id, secret_ref_id)
            return self._file_resolve(tenant_id, secret_ref_id)
        except LocalSecretStoreError:
            raise
        except Exception as exc:  # noqa: BLE001 - 任意 backend/corruption/permission 例外を custody error 化
            raise LocalSecretStoreError(
                "local material resolve failed (backend/corruption/permission error)"
            ) from exc

    def delete(self, tenant_id: int, secret_ref_id: UUID) -> None:
        """material を idempotent に削除する (不在でも例外を出さない)。

        backend drift / marker 不在時は fail-closed (Codex R11/R12-F1): 登録時と別 backend で実行すると
        対象が別 store に残ったまま no-op 成功し caller が material_purged_at を偽証する。marker が無い
        (未初期化 / 削除 / base_dir 復元) 場合も authoritative backend を確定できないため、現在 backend の
        no-op 成功で purged 化させない。例外を上げ caller (revoke/gc) が purged 化せず再試行する。
        """
        self._assert_backend_consistent(require_marker=True)
        if self._use_keyring:
            self._keyring_delete(tenant_id, secret_ref_id)
            return
        self._file_delete(tenant_id, secret_ref_id)

    def exists(self, tenant_id: int, secret_ref_id: UUID) -> bool:
        try:
            self.resolve(tenant_id, secret_ref_id)
        except LocalSecretMaterialNotFound:
            return False
        return True

    # ---- keyring mode ----

    def _material_service(self, tenant_id: int, secret_ref_id: UUID) -> str:
        # tenant_id + secret_ref_id 束縛 (cross-tenant 同名衝突防止)。
        return f"{_MATERIAL_KEYRING_PREFIX}:{tenant_id}:{secret_ref_id}"

    def _keyring_set(self, tenant_id: int, secret_ref_id: UUID, raw: bytes) -> None:
        kr = _require_keyring()
        encoded = base64.b64encode(raw).decode("ascii")
        try:
            kr.set_password(
                self._material_service(tenant_id, secret_ref_id),
                _MATERIAL_KEYRING_ACCOUNT,
                encoded,
            )
        except _KeyringError as exc:  # pragma: no cover - backend specific
            raise LocalSecretStoreError("keyring store failed") from exc

    def _keyring_get(self, tenant_id: int, secret_ref_id: UUID) -> bytes:
        kr = _require_keyring()
        try:
            encoded = kr.get_password(
                self._material_service(tenant_id, secret_ref_id),
                _MATERIAL_KEYRING_ACCOUNT,
            )
        except _KeyringError as exc:  # pragma: no cover - backend specific
            raise LocalSecretStoreError("keyring read failed") from exc
        if encoded is None:
            raise LocalSecretMaterialNotFound(
                f"material not found for tenant={tenant_id} secret_ref={secret_ref_id}"
            )
        # 破損 keyring 値は base64 strict 検証で検出 (Codex R19-F1)。binascii.Error は resolve() の
        # custody 正規化 wrap が LocalSecretStoreError へ落とす (raw 値非露出)。
        return base64.b64decode(encoded, validate=True)

    def _keyring_delete(self, tenant_id: int, secret_ref_id: UUID) -> None:
        kr = _require_keyring()
        service = self._material_service(tenant_id, secret_ref_id)
        # 不在は idempotent no-op。**削除失敗 (keyring locked / permission denied 等) は伝播**させ、
        # caller (revoke/gc) が material_purged_at を set せず purge_attempts++ で再試行する
        # (Codex F1 CRITICAL: 全 KeyringError を成功扱いすると material 残留のまま purged 化する)。
        try:
            existing = kr.get_password(service, _MATERIAL_KEYRING_ACCOUNT)
        except _KeyringError as exc:  # pragma: no cover - backend specific
            raise LocalSecretStoreError("keyring read failed during delete") from exc
        if existing is None:
            return  # 不在 = idempotent success (delete を呼ばない)
        try:
            kr.delete_password(service, _MATERIAL_KEYRING_ACCOUNT)
        except _PasswordDeleteError as exc:
            # PasswordDeleteError は backend により「不在」と「delete failure」を区別できない
            # (Codex R2-F1)。再 get で不在を確認できた時のみ idempotent success とし、値が残る /
            # 再 get 失敗は LocalSecretStoreError として伝播する (material 残留を purged 化しない)。
            try:
                still = kr.get_password(service, _MATERIAL_KEYRING_ACCOUNT)
            except _KeyringError as recheck_exc:  # pragma: no cover - backend specific
                raise LocalSecretStoreError(
                    "keyring re-check failed after delete error"
                ) from recheck_exc
            if still is None:
                return  # 不在確認 = idempotent success
            raise LocalSecretStoreError(
                "keyring delete failed (material still present)"
            ) from exc
        except _KeyringError as exc:  # pragma: no cover - backend specific
            raise LocalSecretStoreError("keyring delete failed") from exc

    # ---- file mode (Fernet) ----

    def _material_path(self, tenant_id: int, secret_ref_id: UUID) -> Path:
        # secret_ref_id は UUID (path traversal 不能)。tenant 別 subdir で分離。
        return self._secrets_dir / str(int(tenant_id)) / f"{secret_ref_id}.enc"

    def _fernet(self) -> Fernet:
        return Fernet(self._load_or_create_master_key())

    def _file_store(self, tenant_id: int, secret_ref_id: UUID, raw: bytes) -> None:
        token = self._fernet().encrypt(raw)
        path = self._material_path(tenant_id, secret_ref_id)
        self._write_secure_file(path, token)

    def _file_resolve(self, tenant_id: int, secret_ref_id: UUID) -> bytes:
        path = self._material_path(tenant_id, secret_ref_id)
        if path.is_symlink():
            raise LocalSecretStorePermissionError("material file must not be a symlink")
        if not path.is_file():
            raise LocalSecretMaterialNotFound(
                f"material not found for tenant={tenant_id} secret_ref={secret_ref_id}"
            )
        token = path.read_bytes()
        try:
            return self._fernet().decrypt(token)
        except InvalidToken as exc:
            # master key 紛失 / ciphertext 破損 = 復号不能 (material loss、再登録 recovery)。
            raise LocalSecretStoreError(
                "material decrypt failed (master key lost or ciphertext corrupted); "
                "recover by revoking and re-registering the secret"
            ) from exc

    def _file_delete(self, tenant_id: int, secret_ref_id: UUID) -> None:
        path = self._material_path(tenant_id, secret_ref_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return  # idempotent
        # parent dir を fsync し削除を durable 化 (Codex F4: power-loss で purged 済 file が復活すると
        # material_purged_at non-NULL のため gc が再試行せず raw material が残る)。
        self._fsync_dir(path.parent)

    # ---- master key custody (file mode) ----

    def _load_or_create_master_key(self) -> bytes:
        key_path = self._keyring_dir / "master.key"
        if key_path.is_symlink():
            raise LocalSecretStorePermissionError("master key must not be a symlink")
        if key_path.is_file():
            self._assert_secure_file_mode(key_path)
            return key_path.read_bytes()
        # 不在 → race-safe に publish (Codex R13-F1): concurrent first-store で 2 process が別 key を
        # 生成し一方が他方を上書きすると、material が上書き前 key で暗号化されたまま復号不能になる
        # (false-present / material loss)。temp→os.link の atomic create-if-absent で、winner / loser とも
        # **同一の最終 key** を返す (loser は winner の完成 file を読む)。
        final = self._atomic_publish(key_path, Fernet.generate_key())
        self._assert_secure_file_mode(key_path)
        if not final:
            raise LocalSecretStoreError("master key empty after atomic publish")
        return final

    # ---- secure file helpers ----

    def _write_secure_file(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=_SECURE_DIR_MODE)
        # 0o600 で atomic overwrite (unique temp + replace、Codex R13-F1: 共有 temp 名 .{name}.tmp を
        # 2 process が同時に O_TRUNC すると temp が破損するため、mkstemp で per-call unique temp を使う)。
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, _SECURE_FILE_MODE)
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        os.chmod(path, _SECURE_FILE_MODE)
        # parent dir を fsync し rename を durable 化 (Codex F4: power-loss で DB が present に進んだのに
        # file rename が失われる乖離を防ぐ)。
        self._fsync_dir(path.parent)

    def _atomic_publish(self, path: Path, content: bytes) -> bytes:
        """``path`` に ``content`` を race-safe に publish し、最終 authoritative bytes を返す。

        Codex R13-F1/F2: 完全に書いた unique temp を ``os.link`` で final へ **atomic create-if-absent**
        する (final は完成形でのみ出現)。winner は自分の content が final になり、race loser
        (``FileExistsError``) は winner の完成 final を読んで返す (partial read なし)。これにより first-store
        race でも全 caller が同一 authoritative 値 (master key / marker) を観測する。symlink は fail-closed。
        """
        if path.is_symlink():
            raise LocalSecretStorePermissionError(f"{path.name} must not be a symlink")
        path.parent.mkdir(parents=True, exist_ok=True, mode=_SECURE_DIR_MODE)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, _SECURE_FILE_MODE)
            try:
                os.link(str(tmp), str(path))  # atomic create-if-absent (final は完成形でのみ出現)
            except FileExistsError:
                pass  # race loser: final は既に完成形で存在する
            self._fsync_dir(path.parent)
        finally:
            tmp.unlink(missing_ok=True)
        if path.is_symlink():  # link 後に symlink へ差し替えられていないか再確認
            raise LocalSecretStorePermissionError(f"{path.name} must not be a symlink")
        return path.read_bytes()

    @staticmethod
    def _fsync_dir(directory: Path) -> None:
        """directory entry を durable 化する (rename/unlink の crash-safety、Codex R2-F4)。

        EINVAL / ENOTSUP (dir fsync 非対応 FS) のみ degraded mode として許容し、それ以外の
        durability failure (EIO / ENOSPC / EACCES 等) は LocalSecretStoreError として伝播する
        (握り潰すと DB が present/purged に進んだのに store が durable でない乖離が残る)。
        """
        _unsupported = {errno.EINVAL, errno.ENOTSUP}
        try:
            fd = os.open(str(directory), os.O_RDONLY)
        except OSError as exc:
            if exc.errno in _unsupported:  # pragma: no cover - platform
                return
            raise LocalSecretStorePermissionError(
                f"directory open for fsync failed: {exc.errno}"
            ) from exc
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno in _unsupported:  # pragma: no cover - platform
                return
            raise LocalSecretStorePermissionError(
                f"directory fsync failed: {exc.errno}"
            ) from exc
        finally:
            os.close(fd)

    @staticmethod
    def _assert_secure_file_mode(path: Path) -> None:
        mode = path.stat().st_mode & 0o777
        if mode != _SECURE_FILE_MODE:
            raise LocalSecretStorePermissionError(
                f"insecure permissions {oct(mode)} on {path.name} (expected 0o600)"
            )

    # ---- backend custody (drift / marker-absence fail-closed、Codex R11/R12-F1) ----

    def _current_backend(self) -> str:
        return _BACKEND_KEYRING if self._use_keyring else _BACKEND_FILE

    def _backend_marker_path(self) -> Path:
        return self._base_dir / _BACKEND_MARKER_NAME

    def _read_marker_backend(self) -> str | None:
        """marker から pin 済 backend を返す (不在は None)。非正規 / insecure / 破損 marker は fail-closed。

        symlink / 非通常ファイル (dir 等) / group・other writable な marker は改ざん経路のため reject
        (Codex R12-F1 "reject non-regular or insecure marker files")。

        marker の stat / read / ascii decode で生じる ``OSError`` (PermissionError 等) / ``UnicodeDecodeError``
        / ``ValueError`` (破損・非ASCII・読取不能 marker) を **`LocalSecretStorePermissionError` へ正規化**する
        (Codex R20-F1)。本 method は `_assert_backend_consistent` (resolve/delete の custody 前段) と
        `_ensure_marker_pinned` (store) から呼ばれるため、raw 例外が broker の custody-error catch
        (`_RESOLVER_CUSTODY_ERRORS`、R14-F2/R15-F1) を bypass して 500/rollback 依存になるのを防ぐ。
        """
        marker = self._backend_marker_path()
        try:
            if marker.is_symlink():
                raise LocalSecretStorePermissionError("backend marker must not be a symlink")
            if not marker.exists():
                return None
            if not marker.is_file():
                raise LocalSecretStorePermissionError(
                    "backend marker must be a regular file (non-regular marker rejected)"
                )
            mode = marker.stat().st_mode & 0o777
            if mode & 0o022:  # group/other writable = 改ざん可能
                raise LocalSecretStorePermissionError(
                    f"insecure backend marker permissions {oct(mode)} (group/other writable)"
                )
            return marker.read_text(encoding="ascii").strip()
        except LocalSecretStorePermissionError:
            raise
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            # 破損 / 非ASCII / 読取不能 marker を custody error へ正規化 (raw 例外を漏らさない)。
            raise LocalSecretStorePermissionError(
                "backend marker unreadable or corrupted"
            ) from exc

    def _assert_backend_consistent(self, *, require_marker: bool) -> None:
        """runtime 検出 backend が pin 済 marker と一致するか確認する (不一致 / 不在は fail-closed)。

        material は keyring か file の一方にしか無いが、backend は runtime 検出で silent fallback する
        (TASKHUB_DISABLE_KEYRING / keyring import 不在 / probe 例外)。pin 済 backend と別 backend で
        delete/resolve すると対象が別 store に残ったまま no-op になり、delete 成功扱い → material_purged_at
        偽証 (false-purged、R11-F1)。さらに **marker 不在** (未初期化 / 削除 / base_dir 復元 / 初期化 race)
        は authoritative backend を確定できないため、``require_marker=True`` (resolve/delete) では
        fail-closed にする (R12-F1: marker 不在を「空 deployment=安全」と誤認すると、material 存在下に
        現在 backend の no-op 成功で false-purged が再発する)。
        """
        recorded = self._read_marker_backend()
        if recorded is None:
            if require_marker:
                raise LocalSecretStoreError(
                    "backend marker missing; cannot determine the authoritative local secret "
                    "backend (uninitialized, deleted, or restored without marker). refusing to "
                    "operate to avoid false-purged material; run store-side init / operator reconcile"
                )
            return
        current = self._current_backend()
        if recorded != current:
            raise LocalSecretStoreError(
                f"secret material backend drift detected "
                f"(recorded={recorded!r}, current={current!r}); refusing to operate to avoid "
                "false-purged material. restore the original backend or migrate material first"
            )

    def _ensure_marker_pinned(self) -> None:
        """material 書込前に backend marker を atomic に pin する (Codex R12-F1 / R13-F2)。

        既存 marker があれば現在 backend と一致を verify (mismatch は drift fail-closed)。不在なら
        ``_atomic_publish`` (temp→os.link) で race-safe に作成する。concurrent first-store の loser は
        winner の完成 marker を読み、**winner の backend が自分と一致しない (別 backend / 削除で read 不能)
        場合は必ず fail-closed** にする (R13-F2: 旧実装は ``raced is None`` を success で通し、marker 無しで
        material を書く穴があった)。publish 後も marker を再読し content / mode を verify してから返す。
        """
        recorded = self._read_marker_backend()
        current = self._current_backend()
        if recorded is not None:
            if recorded != current:
                raise LocalSecretStoreError(
                    f"secret material backend drift detected "
                    f"(recorded={recorded!r}, current={current!r}); refusing to store material "
                    "in a different backend than the pinned one"
                )
            return
        # marker 不在 → race-safe に publish (winner/loser とも winner の完成 marker を観測)。
        final = self._atomic_publish(self._backend_marker_path(), current.encode("ascii"))
        if final.decode("ascii", errors="replace").strip() != current:
            # loser が別 backend の winner marker を読んだ (drift)。fail-closed (別 backend へ書かない)。
            raise LocalSecretStoreError(
                f"secret material backend drift detected during first-store race "
                f"(published={final!r}, current={current!r})"
            )
        # publish 後の最終 verify (R13-F2 final-verify): symlink/非正規/insecure/別 backend を再検証。
        verified = self._read_marker_backend()
        if verified != current:
            raise LocalSecretStoreError(
                f"backend marker re-read mismatch after publish "
                f"(verified={verified!r}, current={current!r})"
            )

    # ---- keyring detection ----

    @staticmethod
    def _detect_keyring(override: bool | None) -> bool:
        if override is not None:
            return override
        if os.environ.get(_DISABLE_KEYRING_ENV):
            return False
        if _keyring is None:
            return False
        try:
            # read-only probe: 使える backend なら不在 key で None を返す、無ければ例外。
            _keyring.get_password(_PROBE_SERVICE, _PROBE_ACCOUNT)
        except Exception:  # noqa: BLE001 - 任意の backend エラーは fallback トリガ
            return False
        return True


__all__ = [
    "LocalSecretMaterialNotFound",
    "LocalSecretStore",
    "LocalSecretStoreError",
    "LocalSecretStorePermissionError",
]
