"""LocalSecretStore file-mode (Fernet) の custody contract (no-DB)。

ADR-00058: material key = tenant_id + secret_ref_id 束縛 / encrypted-at-rest / 0o600 / master key 非同居
/ 紛失=material loss。keyring mode は OS Keychain 依存のため CI では file mode のみ検証する。
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.services.secrets.local_secret_store import (
    LocalSecretMaterialNotFound,
    LocalSecretStore,
    LocalSecretStorePermissionError,
)

_RAW = b"super-secret-material-\x00\x01-binary"


def _store(tmp_path: Path) -> LocalSecretStore:
    return LocalSecretStore(base_dir=tmp_path, use_keyring=False)


def test_file_mode_round_trip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.uses_keyring is False
    tid, sid = 1, uuid4()
    store.store(tid, sid, _RAW)
    assert store.resolve(tid, sid) == _RAW
    assert store.exists(tid, sid) is True


def test_material_encrypted_at_rest(tmp_path: Path) -> None:
    store = _store(tmp_path)
    tid, sid = 1, uuid4()
    store.store(tid, sid, _RAW)
    ciphertext = (tmp_path / "secrets.d" / str(tid) / f"{sid}.enc").read_bytes()
    assert b"super-secret-material" not in ciphertext  # raw が平文で残らない


def test_ciphertext_and_master_key_permissions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    tid, sid = 1, uuid4()
    store.store(tid, sid, _RAW)
    enc = tmp_path / "secrets.d" / str(tid) / f"{sid}.enc"
    master = tmp_path / "keyring.d" / "master.key"
    assert oct(enc.stat().st_mode & 0o777) == "0o600"
    assert oct(master.stat().st_mode & 0o777) == "0o600"


def test_master_key_not_colocated_with_ciphertext(tmp_path: Path) -> None:
    store = _store(tmp_path)
    tid, sid = 1, uuid4()
    store.store(tid, sid, _RAW)
    enc = tmp_path / "secrets.d" / str(tid) / f"{sid}.enc"
    master = tmp_path / "keyring.d" / "master.key"
    assert master.is_file()
    assert master.parent != enc.parent  # key 非同居 (ADR-00058 finding R16-2)


def test_master_key_persists_across_instances(tmp_path: Path) -> None:
    tid, sid = 1, uuid4()
    _store(tmp_path).store(tid, sid, _RAW)
    # 別インスタンスでも同 master key で復号できる。
    assert _store(tmp_path).resolve(tid, sid) == _RAW


def test_cross_tenant_same_secret_ref_isolated(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sid = uuid4()
    store.store(1, sid, b"tenant-1-material")
    store.store(2, sid, b"tenant-2-material")
    assert store.resolve(1, sid) == b"tenant-1-material"
    assert store.resolve(2, sid) == b"tenant-2-material"  # 衝突・誤解決しない


def test_resolve_missing_raises_not_found(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(LocalSecretMaterialNotFound):
        store.resolve(1, uuid4())
    assert store.exists(1, uuid4()) is False


def test_delete_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    tid, sid = 1, uuid4()
    store.store(tid, sid, _RAW)
    store.delete(tid, sid)
    store.delete(tid, sid)  # 2 回目は no-op
    assert store.exists(tid, sid) is False


def test_master_key_loss_is_material_loss(tmp_path: Path) -> None:
    store = _store(tmp_path)
    tid, sid = 1, uuid4()
    store.store(tid, sid, _RAW)
    # master key 紛失をシミュレート (再生成 → 旧 ciphertext は復号不能 = material loss)。
    (tmp_path / "keyring.d" / "master.key").unlink()
    fresh = _store(tmp_path)  # 新 master key を生成
    from backend.app.services.secrets.local_secret_store import LocalSecretStoreError

    with pytest.raises(LocalSecretStoreError):
        fresh.resolve(tid, sid)


def test_insecure_master_key_permission_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    tid, sid = 1, uuid4()
    store.store(tid, sid, _RAW)
    master = tmp_path / "keyring.d" / "master.key"
    os.chmod(master, 0o644)  # 安全側でない permission
    with pytest.raises(LocalSecretStorePermissionError):
        _store(tmp_path).resolve(tid, sid)


class _FakeKeyringLocked:
    """delete 時に not-found 以外の KeyringError を返す backend (keyring locked 相当)。"""

    def get_password(self, service: str, account: str) -> str:
        return "ZmFrZQ=="  # 存在する (base64)

    def delete_password(self, service: str, account: str) -> None:
        import backend.app.services.secrets.local_secret_store as lss

        raise lss._KeyringError("keyring locked")  # noqa: SLF001


class _FakeKeyringEmpty:
    """material 不在 backend (get→None)。delete は呼ばれてはならない。"""

    def get_password(self, service: str, account: str) -> str | None:
        return None

    def delete_password(self, service: str, account: str) -> None:  # pragma: no cover
        raise AssertionError("delete_password must not be called when material is absent")


class _FakeKeyringDeleteErrorStillPresent:
    """delete が PasswordDeleteError を投げるが material は残存し続ける backend (delete failure)。"""

    def get_password(self, service: str, account: str) -> str:
        return "ZmFrZQ=="  # 常に残存 (delete failure)

    def delete_password(self, service: str, account: str) -> None:
        import backend.app.services.secrets.local_secret_store as lss

        raise lss._PasswordDeleteError("delete failed")  # noqa: SLF001


class _FakeKeyringDeleteErrorThenGone:
    """delete が PasswordDeleteError を投げ、再 get で不在になる backend (TOCTOU で既に消えた)。"""

    def __init__(self) -> None:
        self._calls = 0

    def get_password(self, service: str, account: str) -> str | None:
        # 1 回目 (delete 前) は存在、2 回目 (delete エラー後の再 get) は不在。
        self._calls += 1
        return "ZmFrZQ==" if self._calls == 1 else None

    def delete_password(self, service: str, account: str) -> None:
        import backend.app.services.secrets.local_secret_store as lss

        raise lss._PasswordDeleteError("already gone")  # noqa: SLF001


def test_keyring_delete_failure_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex F1 (CRITICAL): keyring delete 失敗 (locked 等) は成功扱いせず伝播する。

    握り潰すと material 残留のまま purged 化され raw secret が残るため、caller (revoke/gc) が
    purge_attempts++ + material_purged_at NULL で再試行できるよう例外を上げる。
    """
    import backend.app.services.secrets.local_secret_store as lss

    monkeypatch.setattr(lss, "_keyring", _FakeKeyringLocked())
    store = lss.LocalSecretStore(base_dir=tmp_path, use_keyring=True)
    with pytest.raises(lss.LocalSecretStoreError):
        store.delete(1, uuid4())


def test_keyring_delete_missing_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """material 不在は idempotent no-op (delete_password を呼ばない)。"""
    import backend.app.services.secrets.local_secret_store as lss

    monkeypatch.setattr(lss, "_keyring", _FakeKeyringEmpty())
    store = lss.LocalSecretStore(base_dir=tmp_path, use_keyring=True)
    store.delete(1, uuid4())  # 例外なし


def test_keyring_password_delete_error_still_present_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex R2-F1 (CRITICAL): PasswordDeleteError でも再 get で material が残存すれば伝播する。

    PasswordDeleteError は backend により「不在」と「delete failure」を区別できないため、再 get で
    不在を確認できた時のみ idempotent success とし、残存していれば成功扱いしない。
    """
    import backend.app.services.secrets.local_secret_store as lss

    monkeypatch.setattr(lss, "_keyring", _FakeKeyringDeleteErrorStillPresent())
    store = lss.LocalSecretStore(base_dir=tmp_path, use_keyring=True)
    with pytest.raises(lss.LocalSecretStoreError):
        store.delete(1, uuid4())


def test_keyring_password_delete_error_then_gone_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PasswordDeleteError でも再 get で不在を確認できれば idempotent success (TOCTOU)。"""
    import backend.app.services.secrets.local_secret_store as lss

    monkeypatch.setattr(lss, "_keyring", _FakeKeyringDeleteErrorThenGone())
    store = lss.LocalSecretStore(base_dir=tmp_path, use_keyring=True)
    store.delete(1, uuid4())  # 例外なし (再 get で不在確認)


def test_symlink_material_file_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    tid, sid = 1, uuid4()
    store.store(tid, sid, _RAW)
    enc = tmp_path / "secrets.d" / str(tid) / f"{sid}.enc"
    target = tmp_path / "elsewhere.enc"
    target.write_bytes(enc.read_bytes())
    enc.unlink()
    enc.symlink_to(target)
    with pytest.raises(LocalSecretStorePermissionError):
        store.resolve(tid, sid)
