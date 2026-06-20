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


def _write_keyring_marker(tmp_path: Path) -> None:
    """marker=keyring を 0o600 で事前 pin する (R12-F1: marker 不在は fail-closed のため初期化済を模擬)。"""
    marker = tmp_path / "backend.marker"
    fd = os.open(str(marker), os.O_CREAT | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(b"keyring")


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
    store.store(1, uuid4(), _RAW)  # marker 初期化 (R12-F1: marker 不在は fail-closed)
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
    _write_keyring_marker(tmp_path)
    store = lss.LocalSecretStore(base_dir=tmp_path, use_keyring=True)
    with pytest.raises(lss.LocalSecretStoreError):
        store.delete(1, uuid4())


def test_keyring_delete_missing_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """material 不在は idempotent no-op (delete_password を呼ばない)。"""
    import backend.app.services.secrets.local_secret_store as lss

    monkeypatch.setattr(lss, "_keyring", _FakeKeyringEmpty())
    _write_keyring_marker(tmp_path)  # marker 初期化 (R12-F1: marker 不在は fail-closed)
    store = lss.LocalSecretStore(base_dir=tmp_path, use_keyring=True)
    store.delete(1, uuid4())  # marker present + 不在 material は idempotent no-op


def test_keyring_password_delete_error_still_present_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex R2-F1 (CRITICAL): PasswordDeleteError でも再 get で material が残存すれば伝播する。

    PasswordDeleteError は backend により「不在」と「delete failure」を区別できないため、再 get で
    不在を確認できた時のみ idempotent success とし、残存していれば成功扱いしない。
    """
    import backend.app.services.secrets.local_secret_store as lss

    monkeypatch.setattr(lss, "_keyring", _FakeKeyringDeleteErrorStillPresent())
    _write_keyring_marker(tmp_path)
    store = lss.LocalSecretStore(base_dir=tmp_path, use_keyring=True)
    with pytest.raises(lss.LocalSecretStoreError):
        store.delete(1, uuid4())


def test_keyring_password_delete_error_then_gone_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PasswordDeleteError でも再 get で不在を確認できれば idempotent success (TOCTOU)。"""
    import backend.app.services.secrets.local_secret_store as lss

    monkeypatch.setattr(lss, "_keyring", _FakeKeyringDeleteErrorThenGone())
    _write_keyring_marker(tmp_path)
    store = lss.LocalSecretStore(base_dir=tmp_path, use_keyring=True)
    store.delete(1, uuid4())  # 例外なし (再 get で不在確認)


class _FakeKeyringStore:
    """dict-backed keyring (store/get/delete 可能)。backend drift test 用。"""

    def __init__(self) -> None:
        self._d: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, account: str, value: str) -> None:
        self._d[(service, account)] = value

    def get_password(self, service: str, account: str) -> str | None:
        return self._d.get((service, account))

    def delete_password(self, service: str, account: str) -> None:
        self._d.pop((service, account), None)


def test_backend_marker_recorded_on_first_store(tmp_path: Path) -> None:
    """Codex R11-F1: 初回 store で deployment backend が marker に pin される。"""
    store = _store(tmp_path)
    store.store(1, uuid4(), _RAW)
    marker = tmp_path / "backend.marker"
    assert marker.is_file()
    assert marker.read_text(encoding="ascii").strip() == "file"
    assert oct(marker.stat().st_mode & 0o777) == "0o600"


def test_backend_drift_keyring_to_file_delete_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex R11-F1 (CRITICAL): keyring 登録 material を file mode で delete すると fail-closed。

    silent fallback (keyring locked/disabled) で file mode に落ちると、_file_delete が対象不在で
    no-op 成功し caller が material_purged_at を偽証する (false-purged)。drift を検出し例外化する。
    """
    import backend.app.services.secrets.local_secret_store as lss

    tid, sid = 1, uuid4()
    monkeypatch.setattr(lss, "_keyring", _FakeKeyringStore())
    kstore = lss.LocalSecretStore(base_dir=tmp_path, use_keyring=True)
    kstore.store(tid, sid, _RAW)  # marker=keyring、material は keyring に存在

    fstore = lss.LocalSecretStore(base_dir=tmp_path, use_keyring=False)
    with pytest.raises(lss.LocalSecretStoreError):
        fstore.delete(tid, sid)
    # material は keyring に残存 = false-purged になっていない。
    assert kstore.resolve(tid, sid) == _RAW


def test_backend_drift_file_to_keyring_delete_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex R11-F1: file 登録 material を keyring mode で delete すると fail-closed。"""
    import backend.app.services.secrets.local_secret_store as lss

    tid, sid = 1, uuid4()
    fstore = lss.LocalSecretStore(base_dir=tmp_path, use_keyring=False)
    fstore.store(tid, sid, _RAW)  # marker=file、material は file に存在

    monkeypatch.setattr(lss, "_keyring", _FakeKeyringStore())
    kstore = lss.LocalSecretStore(base_dir=tmp_path, use_keyring=True)
    with pytest.raises(lss.LocalSecretStoreError):
        kstore.delete(tid, sid)
    # material は file に残存。
    assert fstore.resolve(tid, sid) == _RAW


def test_backend_drift_resolve_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex R11-F1: drift 時の resolve は NotFound でなく drift error (fail-closed)。"""
    import backend.app.services.secrets.local_secret_store as lss

    tid, sid = 1, uuid4()
    monkeypatch.setattr(lss, "_keyring", _FakeKeyringStore())
    lss.LocalSecretStore(base_dir=tmp_path, use_keyring=True).store(tid, sid, _RAW)

    fstore = lss.LocalSecretStore(base_dir=tmp_path, use_keyring=False)
    with pytest.raises(lss.LocalSecretStoreError):
        fstore.resolve(tid, sid)


def test_delete_with_missing_marker_fails_closed(tmp_path: Path) -> None:
    """Codex R12-F1 (CRITICAL): marker 不在 (削除 / base_dir 復元) の delete は fail-closed。

    marker を「空 deployment=安全」と誤認すると、keyring material 存在下に file-mode delete が no-op
    成功 → false-purged。authoritative backend を確定できない以上、delete は例外を上げ purged 化させない。
    """
    import backend.app.services.secrets.local_secret_store as lss

    tid, sid = 1, uuid4()
    store = _store(tmp_path)
    store.store(tid, sid, _RAW)
    # marker を削除 (restore-without-marker / base_dir drift を模擬)。
    (tmp_path / "backend.marker").unlink()
    with pytest.raises(lss.LocalSecretStoreError):
        store.delete(tid, sid)
    # material は残存 (false-purged になっていない)。
    (tmp_path / "backend.marker").write_text("file", encoding="ascii")
    assert store.resolve(tid, sid) == _RAW


def test_resolve_with_missing_marker_fails_closed(tmp_path: Path) -> None:
    """Codex R12-F1: marker 不在の resolve も fail-closed (誤った not-found を返さない)。"""
    import backend.app.services.secrets.local_secret_store as lss

    tid, sid = 1, uuid4()
    store = _store(tmp_path)
    store.store(tid, sid, _RAW)
    (tmp_path / "backend.marker").unlink()
    with pytest.raises(lss.LocalSecretStoreError):
        store.resolve(tid, sid)


def test_non_regular_marker_rejected(tmp_path: Path) -> None:
    """Codex R12-F1: marker が dir 等の非正規ファイルなら fail-closed (改ざん経路 reject)。"""
    store = _store(tmp_path)
    (tmp_path / "backend.marker").mkdir(parents=True)
    with pytest.raises(LocalSecretStorePermissionError):
        store.delete(1, uuid4())


def test_world_writable_marker_rejected(tmp_path: Path) -> None:
    """Codex R12-F1: group/other writable marker は改ざん可能なため fail-closed。"""
    store = _store(tmp_path)
    marker = tmp_path / "backend.marker"
    marker.write_text("file", encoding="ascii")
    os.chmod(marker, 0o666)  # noqa: S103 - insecure marker を意図的に作り reject を検証
    with pytest.raises(LocalSecretStorePermissionError):
        store.resolve(1, uuid4())


def test_store_drift_blocks_writing_other_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex R12-F1: pin 済 marker と別 backend での store は material 書込前に fail-closed。

    concurrent first-store race の loser や backend 切替で、material が pin と別 store に入るのを防ぐ。
    """
    import backend.app.services.secrets.local_secret_store as lss

    # file mode で先に pin (marker=file)。
    lss.LocalSecretStore(base_dir=tmp_path, use_keyring=False).store(1, uuid4(), _RAW)
    # 後から keyring mode で store しようとすると drift で reject (material は keyring に入らない)。
    fake = _FakeKeyringStore()
    monkeypatch.setattr(lss, "_keyring", fake)
    kstore = lss.LocalSecretStore(base_dir=tmp_path, use_keyring=True)
    with pytest.raises(lss.LocalSecretStoreError):
        kstore.store(1, uuid4(), _RAW)
    assert fake._d == {}  # noqa: SLF001 - keyring に material が書かれていないことを検証


def test_atomic_publish_loser_returns_existing_content(tmp_path: Path) -> None:
    """Codex R13-F1/F2: _atomic_publish は既存 final を上書きせず winner の値を返す (race loser semantics)。"""
    store = _store(tmp_path)
    target = tmp_path / "race.bin"
    first = store._atomic_publish(target, b"winner")  # noqa: SLF001
    assert first == b"winner"
    second = store._atomic_publish(target, b"loser")  # noqa: SLF001 - 既存 → winner の値を返す
    assert second == b"winner"
    assert target.read_bytes() == b"winner"  # 上書きされていない


def test_master_key_creation_uses_existing_key_no_overwrite(tmp_path: Path) -> None:
    """Codex R13-F1 (CRITICAL): master.key 既存時は上書きせず既存 key を使う (first-store race loser)。

    concurrent first-store で 2 process が別 key を生成し一方が他方を上書きすると、上書き前 key で
    暗号化された material が復号不能 (false-present / material loss) になる。既存 key を必ず使うことで
    winner key 暗号化 material が resolve 可能なまま保たれることを担保する。
    """
    from cryptography.fernet import Fernet

    keyring_dir = tmp_path / "keyring.d"
    keyring_dir.mkdir(parents=True)
    key = Fernet.generate_key()  # winner の key
    mk = keyring_dir / "master.key"
    fd = os.open(str(mk), os.O_CREAT | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    os.chmod(mk, 0o600)

    store = _store(tmp_path)
    tid, sid = 1, uuid4()
    store.store(tid, sid, _RAW)
    assert mk.read_bytes() == key  # 既存 key を上書きしていない
    assert store.resolve(tid, sid) == _RAW  # winner key で復号可能 (material loss なし)


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
