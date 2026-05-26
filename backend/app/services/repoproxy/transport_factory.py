"""Factory for creating broker-mediated GitHub transport instances.

Provides FastAPI dependency injection and arq worker context wiring
for HttpxGitHubTransport + SopsSubprocessResolver.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from fastapi import Request

from backend.app.db.models.secret_ref import SecretRef
from backend.app.services.repoproxy.httpx_transport import HttpxGitHubTransport
from backend.app.services.repoproxy.webhook_adapters import SecretMaterialResolver
from backend.app.services.secrets.sops_resolver import SopsSubprocessResolver

_DEFAULT_SOPS_DIR_ENV: Final = "TASKMANAGEDAI_SOPS_DIR"
_DEFAULT_SOPS_DIR: Final = "config/secrets"


def create_sops_resolver(
    *,
    sops_dir: Path | None = None,
    sops_binary: Path | None = None,
    age_key_file: Path | None = None,
) -> SopsSubprocessResolver:
    resolved_dir = sops_dir or Path(os.environ.get(_DEFAULT_SOPS_DIR_ENV, _DEFAULT_SOPS_DIR))
    return SopsSubprocessResolver(
        resolved_dir,
        sops_binary=sops_binary,
        age_key_file=age_key_file,
    )


def create_github_transport(
    *,
    material_resolver: SecretMaterialResolver,
    secret_ref: SecretRef,
) -> HttpxGitHubTransport:
    return HttpxGitHubTransport(
        material_resolver=material_resolver,
        secret_ref=secret_ref,
    )


def get_material_resolver_from_app(request: Request) -> SecretMaterialResolver:
    resolver: SecretMaterialResolver | None = getattr(request.app.state, "github_secret_material_resolver", None)
    if resolver is None:
        raise RuntimeError(
            "github_secret_material_resolver not configured on app.state. "
            "Set it during app startup via configure_github_transport()."
        )
    return resolver


def configure_github_transport_on_app(
    app_state: object,
    *,
    sops_dir: Path | None = None,
    sops_binary: Path | None = None,
    age_key_file: Path | None = None,
) -> None:
    try:
        resolver = create_sops_resolver(
            sops_dir=sops_dir,
            sops_binary=sops_binary,
            age_key_file=age_key_file,
        )
        app_state.github_secret_material_resolver = resolver  # type: ignore[attr-defined]
    except Exception:
        app_state.github_secret_material_resolver = None  # type: ignore[attr-defined]


__all__ = [
    "configure_github_transport_on_app",
    "create_github_transport",
    "create_sops_resolver",
    "get_material_resolver_from_app",
]
