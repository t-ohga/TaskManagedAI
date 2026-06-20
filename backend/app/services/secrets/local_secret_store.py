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
import os
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

    def store(self, tenant_id: int, secret_ref_id: UUID, raw: bytes) -> None:
        """material を idempotent に書き込む (既存は上書き)。raw は bytes。"""
        if self._use_keyring:
            self._keyring_set(tenant_id, secret_ref_id, raw)
            return
        self._file_store(tenant_id, secret_ref_id, raw)

    def resolve(self, tenant_id: int, secret_ref_id: UUID) -> bytes:
        """material を返す。不在は LocalSecretMaterialNotFound。broker 内部専用。"""
        if self._use_keyring:
            return self._keyring_get(tenant_id, secret_ref_id)
        return self._file_resolve(tenant_id, secret_ref_id)

    def delete(self, tenant_id: int, secret_ref_id: UUID) -> None:
        """material を idempotent に削除する (不在でも例外を出さない)。"""
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
        return base64.b64decode(encoded)

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
        except _PasswordDeleteError:
            # get 後に別経路で消えた (TOCTOU) → 既に不在 = idempotent。
            return
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
        key = Fernet.generate_key()
        self._write_secure_file(key_path, key)
        return key

    # ---- secure file helpers ----

    def _write_secure_file(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=_SECURE_DIR_MODE)
        # 0o600 で atomic に書く (O_CREAT|O_TRUNC|O_WRONLY、temp + replace)。
        tmp = path.with_name(f".{path.name}.tmp")
        fd = os.open(str(tmp), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, _SECURE_FILE_MODE)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        os.chmod(tmp, _SECURE_FILE_MODE)
        os.replace(tmp, path)
        os.chmod(path, _SECURE_FILE_MODE)
        # parent dir を fsync し rename を durable 化 (Codex F4: power-loss で DB が present に進んだのに
        # file rename が失われる乖離を防ぐ)。
        self._fsync_dir(path.parent)

    @staticmethod
    def _fsync_dir(directory: Path) -> None:
        """directory entry を durable 化する (rename/unlink の crash-safety)。"""
        try:
            fd = os.open(str(directory), os.O_RDONLY)
        except OSError:  # pragma: no cover - platform (一部 FS は dir fsync 不可)
            return
        try:
            os.fsync(fd)
        except OSError:  # pragma: no cover - platform
            pass
        finally:
            os.close(fd)

    @staticmethod
    def _assert_secure_file_mode(path: Path) -> None:
        mode = path.stat().st_mode & 0o777
        if mode != _SECURE_FILE_MODE:
            raise LocalSecretStorePermissionError(
                f"insecure permissions {oct(mode)} on {path.name} (expected 0o600)"
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
