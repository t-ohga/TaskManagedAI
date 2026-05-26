"""SP-008 Batch F: SOPS subprocess resolver security tests.

Verifies URI scheme validation, path traversal denial, subprocess hardening,
status defense-in-depth, and raw material canary redaction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from backend.app.services.secrets.sops_resolver import (
    SOPS_ENV_ALLOWLIST,
    SopsPathTraversalError,
    SopsResolverError,
    SopsStatusDeniedError,
    SopsSubprocessResolver,
    SopsUriSchemeError,
)


def _make_secret_ref(
    *,
    uri: str = "secret://sops/p0/github_webhook_hmac#v1",
    status: str = "active",
) -> Any:
    ref = MagicMock()
    ref.secret_uri = uri
    ref.status = status
    ref.id = uuid4()
    ref.scope = "p0"
    ref.name = "github_webhook_hmac"
    ref.version = "v1"
    return ref


@pytest.fixture
def sops_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sops"
    d.mkdir()
    return d


@pytest.fixture
def fake_sops_binary(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    binary = bin_dir / "sops"
    binary.write_text("#!/bin/sh\necho fake\n")
    binary.chmod(0o755)
    return binary


@pytest.fixture
def resolver(sops_dir: Path, tmp_path: Path, fake_sops_binary: Path) -> SopsSubprocessResolver:
    key_file = tmp_path / "age-key.txt"
    key_file.write_text("# fake key file\n")
    return SopsSubprocessResolver(sops_dir, sops_binary=fake_sops_binary, age_key_file=key_file)


class TestUriSchemeReject:
    @pytest.mark.parametrize(
        "bad_uri",
        [
            "secret://vault/p0/hmac#v1",
            "https://example.com/secret",
            "sops://p0/hmac#v1",
            "secret://sops/INVALID SCOPE/name#v1",
            "secret://sops/p0/name",
            "",
            "secret://sops/../etc/passwd#v1",
        ],
    )
    @pytest.mark.asyncio
    async def test_rejects_non_sops_uri(
        self, resolver: SopsSubprocessResolver, bad_uri: str
    ) -> None:
        ref = _make_secret_ref(uri=bad_uri)
        with pytest.raises(SopsUriSchemeError):
            await resolver.resolve_secret_material(ref)


class TestPathTraversalDeny:
    @pytest.mark.asyncio
    async def test_path_traversal_via_symlink(
        self, sops_dir: Path, resolver: SopsSubprocessResolver
    ) -> None:
        scope_dir = sops_dir / "p0"
        scope_dir.mkdir()
        target = Path("/etc/passwd")
        link = scope_dir / "evil.v1.enc.yaml"
        try:
            link.symlink_to(target)
        except OSError:
            pytest.skip("Cannot create symlink in test env")

        ref = _make_secret_ref(uri="secret://sops/p0/evil#v1")
        with pytest.raises((SopsPathTraversalError, SopsResolverError)):
            await resolver.resolve_secret_material(ref)

    @pytest.mark.asyncio
    async def test_scope_with_dotdot_rejected(
        self, resolver: SopsSubprocessResolver
    ) -> None:
        ref = _make_secret_ref(uri="secret://sops/../etc/passwd#v1")
        with pytest.raises(SopsUriSchemeError):
            await resolver.resolve_secret_material(ref)


class TestSubprocessStdinDevnull:
    @pytest.mark.asyncio
    async def test_stdin_is_devnull(
        self, sops_dir: Path, resolver: SopsSubprocessResolver
    ) -> None:
        scope_dir = sops_dir / "p0"
        scope_dir.mkdir()
        enc_file = scope_dir / "github_webhook_hmac.v1.enc.yaml"
        enc_file.write_text("encrypted: data\n")

        ref = _make_secret_ref()
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"secret", b""))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            await resolver.resolve_secret_material(ref)

            call_kwargs = mock_exec.call_args
            import subprocess

            assert call_kwargs.kwargs["stdin"] == subprocess.DEVNULL


class TestSubprocessEnvAllowlist:
    @pytest.mark.asyncio
    async def test_env_contains_only_allowlisted_keys(
        self, sops_dir: Path, resolver: SopsSubprocessResolver
    ) -> None:
        scope_dir = sops_dir / "p0"
        scope_dir.mkdir()
        enc_file = scope_dir / "github_webhook_hmac.v1.enc.yaml"
        enc_file.write_text("encrypted: data\n")

        ref = _make_secret_ref()
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"secret", b""))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            await resolver.resolve_secret_material(ref)

            call_kwargs = mock_exec.call_args
            env = call_kwargs.kwargs["env"]
            for key in env:
                assert key in SOPS_ENV_ALLOWLIST


class TestSubprocessTimeout:
    @pytest.mark.asyncio
    async def test_timeout_raises_resolver_error(
        self, sops_dir: Path, resolver: SopsSubprocessResolver
    ) -> None:
        scope_dir = sops_dir / "p0"
        scope_dir.mkdir()
        enc_file = scope_dir / "github_webhook_hmac.v1.enc.yaml"
        enc_file.write_text("encrypted: data\n")

        ref = _make_secret_ref()
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(side_effect=TimeoutError())
            mock_exec.return_value = mock_proc

            with pytest.raises(SopsResolverError, match="timed out"):
                await resolver.resolve_secret_material(ref)


class TestStderrRawMaterialRedact:
    @pytest.mark.asyncio
    async def test_age_key_redacted_in_error(
        self, sops_dir: Path, resolver: SopsSubprocessResolver
    ) -> None:
        scope_dir = sops_dir / "p0"
        scope_dir.mkdir()
        enc_file = scope_dir / "github_webhook_hmac.v1.enc.yaml"
        enc_file.write_text("encrypted: data\n")

        raw_key = "AGE-SECRET-KEY-1ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
        stderr_with_key = f"error: failed to decrypt with key {raw_key}\n"

        ref = _make_secret_ref()
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(
                return_value=(b"", stderr_with_key.encode())
            )
            mock_proc.returncode = 1
            mock_exec.return_value = mock_proc

            with pytest.raises(SopsResolverError) as exc_info:
                await resolver.resolve_secret_material(ref)

            assert raw_key not in str(exc_info.value)
            assert "[REDACTED]" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_github_token_redacted_in_error(
        self, sops_dir: Path, resolver: SopsSubprocessResolver
    ) -> None:
        scope_dir = sops_dir / "p0"
        scope_dir.mkdir()
        enc_file = scope_dir / "github_webhook_hmac.v1.enc.yaml"
        enc_file.write_text("encrypted: data\n")

        token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
        stderr_with_token = f"error: token={token}\n"

        ref = _make_secret_ref()
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(
                return_value=(b"", stderr_with_token.encode())
            )
            mock_proc.returncode = 1
            mock_exec.return_value = mock_proc

            with pytest.raises(SopsResolverError) as exc_info:
                await resolver.resolve_secret_material(ref)

            assert token not in str(exc_info.value)
            assert "[REDACTED]" in str(exc_info.value)


class TestRevokedStatusDeny:
    @pytest.mark.parametrize("status", ["revoked", "pending"])
    @pytest.mark.asyncio
    async def test_denied_status(
        self, resolver: SopsSubprocessResolver, status: str
    ) -> None:
        ref = _make_secret_ref(status=status)
        with pytest.raises(SopsStatusDeniedError):
            await resolver.resolve_secret_material(ref)

    @pytest.mark.parametrize("status", ["active", "deprecated"])
    @pytest.mark.asyncio
    async def test_allowed_status(
        self, sops_dir: Path, resolver: SopsSubprocessResolver, status: str
    ) -> None:
        scope_dir = sops_dir / "p0"
        scope_dir.mkdir()
        enc_file = scope_dir / "github_webhook_hmac.v1.enc.yaml"
        enc_file.write_text("encrypted: data\n")

        ref = _make_secret_ref(status=status)
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"decrypted", b""))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            result = await resolver.resolve_secret_material(ref)
            assert result == b"decrypted"


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_successful_decrypt(
        self, sops_dir: Path, resolver: SopsSubprocessResolver
    ) -> None:
        scope_dir = sops_dir / "p0"
        scope_dir.mkdir()
        enc_file = scope_dir / "github_webhook_hmac.v1.enc.yaml"
        enc_file.write_text("encrypted: data\n")

        ref = _make_secret_ref()
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"my-hmac-secret", b""))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            result = await resolver.resolve_secret_material(ref)

            assert result == b"my-hmac-secret"
            mock_exec.assert_called_once()
            args = mock_exec.call_args.args
            assert str(args[0]).endswith("sops")
            assert "--decrypt" in args


class TestSopsBinaryMissing:
    @pytest.mark.asyncio
    async def test_file_not_found_error(
        self, sops_dir: Path, resolver: SopsSubprocessResolver
    ) -> None:
        scope_dir = sops_dir / "p0"
        scope_dir.mkdir()
        enc_file = scope_dir / "github_webhook_hmac.v1.enc.yaml"
        enc_file.write_text("encrypted: data\n")

        ref = _make_secret_ref()
        with patch(
            "asyncio.create_subprocess_exec", side_effect=FileNotFoundError("sops")
        ):
            with pytest.raises(SopsResolverError, match="sops binary not found"):
                await resolver.resolve_secret_material(ref)
