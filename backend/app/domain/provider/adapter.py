from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.app.domain.provider.request import ProviderRequest
from backend.app.domain.provider.result import ProviderResult


@runtime_checkable
class ProviderAdapter(Protocol):
    def execute(self, request: ProviderRequest) -> ProviderResult:
        """Execute one structured provider request through a broker-mediated boundary."""

    def provider_name(self) -> str:
        """Return the provider key used by Provider Compliance Matrix rows."""

    def api_or_feature(self) -> str:
        """Return the provider API or feature key used by Provider Compliance Matrix rows."""


__all__ = ["ProviderAdapter"]

