from __future__ import annotations

import argparse
import hashlib
import sys
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from backend.app.domain.agent_runtime.operation_context import canonical_json_dumps
from backend.app.services.tool_registry.schemas import (
    ToolRegistryDocument,
    ToolRegistryEntry,
)

_DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[4] / "config/tool_registry.toml"


@dataclass(frozen=True, slots=True)
class ToolManifestLock:
    registry_version: str
    allowlist_hash: str

    def as_json(self) -> dict[str, str]:
        return {
            "registry_version": self.registry_version,
            "allowlist_hash": self.allowlist_hash,
        }


class LoadedToolRegistry(dict[str, ToolRegistryEntry]):
    def __init__(self, document: ToolRegistryDocument) -> None:
        entries: dict[str, ToolRegistryEntry] = {}
        for entry in document.tools:
            if entry.tool_key in entries:
                raise ValueError(f"duplicate tool_registry tool_key: {entry.tool_key!r}")
            entries[entry.tool_key] = entry
        super().__init__(entries)
        self.document = document
        self.registry_version = document.registry_version
        self.allowlist_hash = compute_allowlist_hash(document.tools)

    @property
    def tool_manifest(self) -> ToolManifestLock:
        return ToolManifestLock(
            registry_version=self.registry_version,
            allowlist_hash=self.allowlist_hash,
        )


def load_tool_registry(toml_path: str | Path = _DEFAULT_REGISTRY_PATH) -> LoadedToolRegistry:
    path = Path(toml_path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("tool registry TOML must be an object.")

    try:
        document = ToolRegistryDocument.model_validate(data)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc

    return LoadedToolRegistry(document)


def compute_allowlist_hash(entries: Iterable[ToolRegistryEntry]) -> str:
    projection: list[dict[str, Any]] = []
    for entry in sorted(entries, key=lambda item: item.tool_key):
        projection.append(
            {
                "tool_key": entry.tool_key,
                "allowed_actions": sorted(entry.allowed_actions),
                "trust_tier": entry.trust_tier,
                "max_outgoing_data_class": entry.max_outgoing_data_class,
                "network_access": entry.network_access,
            }
        )
    encoded = canonical_json_dumps(projection).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def current_tool_manifest(
    toml_path: str | Path = _DEFAULT_REGISTRY_PATH,
) -> dict[str, str]:
    return load_tool_registry(toml_path).tool_manifest.as_json()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the Tool Registry TOML.")
    parser.add_argument(
        "path",
        nargs="?",
        default=str(_DEFAULT_REGISTRY_PATH),
        help="Path to config/tool_registry.toml.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate and print the resolved manifest lock.",
    )
    args = parser.parse_args(argv)

    registry = load_tool_registry(args.path)
    if args.validate:
        manifest = registry.tool_manifest.as_json()
        sys.stdout.write(
            "tool_registry valid "
            f"version={manifest['registry_version']} "
            f"allowlist_hash={manifest['allowlist_hash']}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LoadedToolRegistry",
    "ToolManifestLock",
    "compute_allowlist_hash",
    "current_tool_manifest",
    "load_tool_registry",
]
