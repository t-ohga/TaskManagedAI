"""SOPS subprocess material resolver for broker/webhook internal use only.

Resolves encrypted secret material via `sops --decrypt` subprocess.
NOT a general-purpose secret getter. Restricted to:
- secret://sops/<scope>/<name>#<version> URI scheme only
- sops_dir containment (path traversal denied, symlink denied)
- Subprocess with absolute binary path, allowlisted env, stdin=DEVNULL, timeout+kill
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Final

from backend.app.db.models.secret_ref import SecretRef
from backend.app.services.secrets.uri_pattern import (
    SecretUriError,
    parse_secret_uri,
)

_RAW_MATERIAL_CANARY_PATTERNS: Final = (
    re.compile(r"AGE-SECRET-KEY-[A-Z0-9]+"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"gh[ps]_[A-Za-z0-9_.]{36,}"),
    re.compile(r"ghu_[A-Za-z0-9_]{36,}"),
    re.compile(r"gho_[A-Za-z0-9_]{36,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"tskey-[a-z0-9]+-[A-Za-z0-9]+"),
)

SUBPROCESS_TIMEOUT_SECONDS: Final = 30
SUBPROCESS_KILL_GRACE_SECONDS: Final = 5
STDERR_MAX_BYTES: Final = 4096
SOPS_ENV_ALLOWLIST: Final = frozenset({"HOME", "SOPS_AGE_KEY_FILE"})


class SopsResolverError(Exception):
    pass


class SopsUriSchemeError(SopsResolverError):
    pass


class SopsPathTraversalError(SopsResolverError):
    pass


class SopsStatusDeniedError(SopsResolverError):
    pass


class SopsSubprocessResolver:
    """Broker/webhook internal-only SOPS material resolver.

    Satisfies the SecretMaterialResolver Protocol defined in
    backend.app.services.repoproxy.webhook_adapters.
    """

    def __init__(
        self,
        sops_dir: Path,
        *,
        sops_binary: Path | None = None,
        age_key_file: Path | None = None,
    ) -> None:
        self._sops_dir = sops_dir.resolve(strict=True)
        self._sops_binary = self._resolve_sops_binary(sops_binary)
        self._age_key_file = self._validate_age_key_file(
            age_key_file or self._resolve_age_key_file_from_env()
        )

    async def resolve_secret_material(
        self, secret_ref: SecretRef, *, allow_pending_verify: bool = False
    ) -> bytes:
        self._validate_uri_scheme(secret_ref.secret_uri)
        self._validate_status(secret_ref, allow_pending_verify=allow_pending_verify)
        file_path = self._resolve_file_path(secret_ref)
        self._validate_containment(file_path)
        self._validate_no_symlink_components(file_path)
        return await self._decrypt(file_path, secret_ref)

    def _validate_uri_scheme(self, uri: str) -> None:
        # canonical grammar (uri_pattern.SECRET_URI_PATTERN) を単一 source として検証する
        # (Codex R7-F3): 独立 regex を持つと scope enum が drift し、DB CHECK が弾く非 canonical scope
        # (例: secret://sops/cluster/...) を resolver boundary だけが受理してしまう (cross-source-enum
        # -integrity §1 違反)。backend は sops のみ許可する。
        try:
            backend, _, _, _ = parse_secret_uri(uri)
        except SecretUriError as exc:
            raise SopsUriSchemeError(
                "URI scheme rejected: expected secret://sops/<scope>/<name>#<version>"
            ) from exc
        if backend != "sops":
            raise SopsUriSchemeError(
                f"URI scheme rejected: sops resolver does not handle backend {backend!r}"
            )

    def _validate_status(
        self, secret_ref: SecretRef, *, allow_pending_verify: bool = False
    ) -> None:
        # revoked は常時 deny。pending は broker 経由の rotation verify (allow_pending_verify=True) のみ
        # 許可し、direct/webhook 利用は default False で従来どおり拒否する (Codex R18-F1)。
        denied_statuses: tuple[str, ...] = ("revoked", "pending")
        if allow_pending_verify:
            denied_statuses = ("revoked",)
        if secret_ref.status in denied_statuses:
            raise SopsStatusDeniedError(
                f"secret_ref status={secret_ref.status} denied for direct resolve"
            )

    def _resolve_file_path(self, secret_ref: SecretRef) -> Path:
        # canonical parse から component を取得 (Codex R7-F3、独立 regex を持たない)。scope は
        # SECRET_SCOPES enum、name は [a-z0-9_-]+、version は v[0-9]+ に限定され path traversal 不可。
        try:
            backend, scope, name, version = parse_secret_uri(secret_ref.secret_uri)
        except SecretUriError as exc:
            raise SopsUriSchemeError("URI parse failed") from exc
        if backend != "sops":
            raise SopsUriSchemeError(
                f"sops resolver does not handle backend {backend!r}"
            )
        lexical_path = self._sops_dir / scope / f"{name}.{version}.enc.yaml"
        self._validate_no_symlink_components(lexical_path)
        if lexical_path.is_symlink():
            raise SopsPathTraversalError("Symlink denied at lexical path before resolve")
        return lexical_path.resolve()

    def _validate_containment(self, file_path: Path) -> None:
        try:
            file_path.relative_to(self._sops_dir)
        except ValueError:
            raise SopsPathTraversalError(
                "Path traversal denied: resolved path escapes sops_dir"
            ) from None

    def _validate_no_symlink_components(self, file_path: Path) -> None:
        current = file_path
        while current != self._sops_dir:
            if current.is_symlink():
                raise SopsPathTraversalError(
                    "Path traversal denied: symlink component detected"
                )
            current = current.parent

    async def _decrypt(self, file_path: Path, secret_ref: SecretRef) -> bytes:
        if not Path.is_file(file_path):  # noqa: ASYNC240
            raise SopsResolverError(f"Encrypted file not found for secret_ref id={secret_ref.id}")
        self._validate_no_symlink_components(file_path)
        if Path.is_symlink(file_path):  # noqa: ASYNC240
            raise SopsPathTraversalError("Symlink target file denied at exec time")

        env = self._build_subprocess_env()
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                str(self._sops_binary),
                "--decrypt",
                "--output-type",
                "raw",
                str(file_path),
                stdin=subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            await self._kill_process(proc)
            raise SopsResolverError("sops decrypt timed out") from None
        except FileNotFoundError:
            raise SopsResolverError(
                f"sops binary not found at {self._sops_binary}"
            ) from None
        except OSError as exc:
            # subprocess spawn の PermissionError (binary 非実行) 等 backend 例外を SopsResolverError へ
            # 正規化する (Codex R19-F1)。broker custody-error catch が拾えるよう raw OSError を漏らさない。
            await self._kill_process(proc)
            raise SopsResolverError(f"sops decrypt subprocess failed (errno={exc.errno})") from exc

        if proc.returncode != 0:
            sanitized_stderr = self._sanitize_stderr(
                stderr[:STDERR_MAX_BYTES].decode(errors="replace")
            )
            raise SopsResolverError(
                f"sops decrypt failed (exit={proc.returncode}): {sanitized_stderr}"
            )

        return stdout

    @staticmethod
    async def _kill_process(proc: asyncio.subprocess.Process | None) -> None:
        if proc is None:
            return
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=SUBPROCESS_KILL_GRACE_SECONDS)
        except (TimeoutError, ProcessLookupError):
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass

    def _build_subprocess_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in SOPS_ENV_ALLOWLIST:
            value = os.environ.get(key)
            if value is not None:
                env[key] = value
        if self._age_key_file is not None:
            env["SOPS_AGE_KEY_FILE"] = str(self._age_key_file)
        return env

    def _sanitize_stderr(self, stderr: str) -> str:
        sanitized = stderr
        for pattern in _RAW_MATERIAL_CANARY_PATTERNS:
            sanitized = pattern.sub("[REDACTED]", sanitized)
        return sanitized[:500]

    def _resolve_sops_binary(self, explicit: Path | None) -> Path:
        if explicit is not None:
            resolved = explicit.resolve()
            if not resolved.is_file():
                raise SopsResolverError(f"sops binary not found: {resolved}")
            return resolved
        found = shutil.which("sops")
        if found is None:
            raise SopsResolverError("sops binary not found in PATH")
        return Path(found).resolve()

    @staticmethod
    def _validate_age_key_file(path: Path | None) -> Path | None:
        if path is None:
            return None
        if path.is_symlink():
            raise SopsResolverError("age_key_file must not be a symlink")
        resolved = path.resolve()
        if not resolved.is_file():
            raise SopsResolverError(f"age_key_file not found: {resolved}")
        return resolved

    @staticmethod
    def _resolve_age_key_file_from_env() -> Path | None:
        env_value = os.environ.get("SOPS_AGE_KEY_FILE")
        if env_value:
            return Path(env_value)
        return None


__all__ = [
    "SOPS_ENV_ALLOWLIST",
    "STDERR_MAX_BYTES",
    "SUBPROCESS_KILL_GRACE_SECONDS",
    "SUBPROCESS_TIMEOUT_SECONDS",
    "SopsPathTraversalError",
    "SopsResolverError",
    "SopsStatusDeniedError",
    "SopsSubprocessResolver",
    "SopsUriSchemeError",
]
