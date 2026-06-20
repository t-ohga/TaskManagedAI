"""CompositeSecretResolver の backend dispatch + fail-closed (no-DB)。

ADR-00058: local → LocalSecretStore / sops → SopsSubprocessResolver / 未知 backend → fail-closed deny。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.services.secrets.local_secret_store import LocalSecretStore
from backend.app.services.secrets.resolver_dispatch import (
    CompositeResolverError,
    CompositeSecretResolver,
)


def _secret_ref(uri: str, tenant_id: int = 1, secret_ref_id=None):  # noqa: ANN001, ANN202
    return SimpleNamespace(secret_uri=uri, tenant_id=tenant_id, id=secret_ref_id or uuid4())


class _FakeSopsResolver:
    def __init__(self, material: bytes) -> None:
        self._material = material
        self.called_with: object | None = None

    async def resolve_secret_material(self, secret_ref: object) -> bytes:
        self.called_with = secret_ref
        return self._material


async def test_local_dispatch_returns_store_material(tmp_path: Path) -> None:
    store = LocalSecretStore(base_dir=tmp_path, use_keyring=False)
    sid = uuid4()
    store.store(1, sid, b"local-material")
    resolver = CompositeSecretResolver(local_store=store)
    ref = _secret_ref("secret://local/project/openai#v1", tenant_id=1, secret_ref_id=sid)
    assert await resolver.resolve_secret_material(ref) == b"local-material"


async def test_sops_dispatch_delegates_to_sops_resolver(tmp_path: Path) -> None:
    store = LocalSecretStore(base_dir=tmp_path, use_keyring=False)
    fake = _FakeSopsResolver(b"sops-material")
    resolver = CompositeSecretResolver(local_store=store, sops_resolver=fake)
    ref = _secret_ref("secret://sops/repo/github-app#v2")
    assert await resolver.resolve_secret_material(ref) == b"sops-material"
    assert fake.called_with is ref


async def test_sops_dispatch_without_resolver_fail_closed(tmp_path: Path) -> None:
    store = LocalSecretStore(base_dir=tmp_path, use_keyring=False)
    resolver = CompositeSecretResolver(local_store=store)  # sops_resolver 未設定
    ref = _secret_ref("secret://sops/repo/github-app#v2")
    with pytest.raises(CompositeResolverError):
        await resolver.resolve_secret_material(ref)


async def test_unknown_backend_fail_closed(tmp_path: Path) -> None:
    store = LocalSecretStore(base_dir=tmp_path, use_keyring=False)
    resolver = CompositeSecretResolver(local_store=store)
    ref = _secret_ref("secret://vault/project/foo#v1")
    with pytest.raises(CompositeResolverError):
        await resolver.resolve_secret_material(ref)
