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

    async def resolve_secret_material(
        self, secret_ref: SecretRef, *, allow_pending_verify: bool = False
    ) -> bytes:
        try:
            backend = secret_uri_backend(secret_ref.secret_uri)
        except SecretUriError as exc:
            raise CompositeResolverError("secret_uri rejected (unknown format)") from exc

        if backend == "local":
            # fail-closed material gate (Codex R6-F2): 本 resolver は SecretMaterialResolver として
            # broker を経由しない直接利用 (RepoProxy / webhook) からも呼ばれる。broker の issue/redeem
            # gate を常に通るとは限らないため、resolver boundary でも status active/deprecated かつ
            # material_state='present' を必須化する (writing/purging/purged の未検証・部分書込 material を
            # resolve させない、broker gate の resolver 版)。
            # ただし broker 経由の rotation verify (allow_pending_verify=True) のみ pending+present を
            # 許可する (Codex R18-F1、R17-F1 の broker gate と整合)。direct/webhook は default False で
            # 従来どおり pending を拒否し fail-closed を維持する。
            status = getattr(secret_ref, "status", None)
            material_state = getattr(secret_ref, "material_state", None)
            allowed_statuses: tuple[str, ...] = ("active", "deprecated")
            if allow_pending_verify:
                allowed_statuses = ("active", "deprecated", "pending")
            if status not in allowed_statuses:
                raise CompositeResolverError(
                    f"local secret_ref not resolvable for status {status!r}"
                )
            if material_state != "present":
                raise CompositeResolverError(
                    f"local material_state not present (got {material_state!r})"
                )
            # LocalSecretStore は sync IO。event loop を塞がないよう to_thread で実行。
            return await asyncio.to_thread(
                self._local_store.resolve,
                secret_ref.tenant_id,
                secret_ref.id,
            )
        if backend == "sops":
            if self._sops_resolver is None:
                raise CompositeResolverError("sops backend resolver is not configured")
            material = await self._sops_resolver.resolve_secret_material(
                secret_ref, allow_pending_verify=allow_pending_verify
            )
            return material if isinstance(material, bytes) else material.encode()
        # parse が fail-closed のため到達しないが defense-in-depth。
        raise CompositeResolverError(f"unknown secret backend: {backend!r}")


__all__ = ["CompositeResolverError", "CompositeSecretResolver"]
