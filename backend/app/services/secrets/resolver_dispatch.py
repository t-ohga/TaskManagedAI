"""CompositeSecretResolver: secret_uri の backend segment で material resolver を dispatch する。

``SecretMaterialResolver`` Protocol (webhook_adapters) を満たし、broker / RepoProxy 境界の内部から
``resolve_secret_material(secret_ref)`` で呼ばれる。backend ごとに:

- ``local`` → ``LocalSecretStore.resolve(tenant_id, secret_ref_id)``
- ``sops``  → 既存 ``SopsSubprocessResolver`` (任意注入)

未知 backend は fail-closed deny (``CompositeResolverError``)。backend 判定は単一 source of truth
``uri_pattern.secret_uri_backend`` (未知形式は parse 段階で ``SecretUriError``)。

raw material は broker 内部専用 (caller / AI / runner env / artifact / audit に出さない、§10)。
"""

from __future__ import annotations

import asyncio

from backend.app.db.models.secret_ref import SecretRef
from backend.app.services.repoproxy.webhook_adapters import SecretMaterialResolver
from backend.app.services.secrets.local_secret_store import LocalSecretStore
from backend.app.services.secrets.uri_pattern import SecretUriError, secret_uri_backend


class CompositeResolverError(Exception):
    """backend dispatch 失敗 (未知 backend / 未設定 backend)。"""


class CompositeSecretResolver:
    """backend dispatch する SecretMaterialResolver 実装 (fail-closed)。"""

    def __init__(
        self,
        *,
        local_store: LocalSecretStore,
        sops_resolver: SecretMaterialResolver | None = None,
    ) -> None:
        self._local_store = local_store
        self._sops_resolver = sops_resolver

    async def resolve_secret_material(self, secret_ref: SecretRef) -> bytes:
        try:
            backend = secret_uri_backend(secret_ref.secret_uri)
        except SecretUriError as exc:
            raise CompositeResolverError("secret_uri rejected (unknown format)") from exc

        if backend == "local":
            # LocalSecretStore は sync IO。event loop を塞がないよう to_thread で実行。
            return await asyncio.to_thread(
                self._local_store.resolve,
                secret_ref.tenant_id,
                secret_ref.id,
            )
        if backend == "sops":
            if self._sops_resolver is None:
                raise CompositeResolverError("sops backend resolver is not configured")
            material = await self._sops_resolver.resolve_secret_material(secret_ref)
            return material if isinstance(material, bytes) else material.encode()
        # parse が fail-closed のため到達しないが defense-in-depth。
        raise CompositeResolverError(f"unknown secret backend: {backend!r}")


__all__ = ["CompositeResolverError", "CompositeSecretResolver"]
