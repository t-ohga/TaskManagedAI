"""SP-008 Batch H: Transport factory + DI wiring tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.app.services.repoproxy.transport_factory import (
    configure_github_transport_on_app,
    create_sops_resolver,
    get_material_resolver_from_app,
)
from backend.app.services.secrets.sops_resolver import SopsSubprocessResolver


class TestCreateSopsResolver:
    def test_creates_resolver_with_explicit_dir(self, tmp_path: Path) -> None:
        sops_dir = tmp_path / "sops"
        sops_dir.mkdir()
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        binary = bin_dir / "sops"
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)
        key_file = tmp_path / "key.txt"
        key_file.write_text("# key\n")

        resolver = create_sops_resolver(
            sops_dir=sops_dir,
            sops_binary=binary,
            age_key_file=key_file,
        )
        assert isinstance(resolver, SopsSubprocessResolver)

    def test_raises_when_sops_dir_missing(self, tmp_path: Path) -> None:
        with pytest.raises((FileNotFoundError, OSError)):
            create_sops_resolver(sops_dir=tmp_path / "nonexistent")


class TestConfigureOnApp:
    def test_sets_resolver_on_app_state(self, tmp_path: Path) -> None:
        sops_dir = tmp_path / "sops"
        sops_dir.mkdir()
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        binary = bin_dir / "sops"
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)
        key_file = tmp_path / "key.txt"
        key_file.write_text("# key\n")

        app_state = MagicMock()
        configure_github_transport_on_app(
            app_state,
            sops_dir=sops_dir,
            sops_binary=binary,
            age_key_file=key_file,
        )
        assert app_state.github_secret_material_resolver is not None

    def test_sets_none_when_sops_unavailable(self, tmp_path: Path) -> None:
        app_state = MagicMock()
        configure_github_transport_on_app(
            app_state,
            sops_dir=tmp_path / "nonexistent",
        )
        assert app_state.github_secret_material_resolver is None


class TestGetResolverFromApp:
    def test_raises_when_not_configured(self) -> None:
        request = MagicMock()
        request.app.state = MagicMock(spec=[])
        del request.app.state.github_secret_material_resolver

        with pytest.raises(RuntimeError, match="not configured"):
            get_material_resolver_from_app(request)

    def test_returns_resolver_when_configured(self) -> None:
        request = MagicMock()
        mock_resolver = MagicMock()
        request.app.state.github_secret_material_resolver = mock_resolver

        result = get_material_resolver_from_app(request)
        assert result is mock_resolver
