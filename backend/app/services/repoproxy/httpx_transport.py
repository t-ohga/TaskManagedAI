"""Real httpx transport for broker-mediated GitHub API calls.

Raw installation token is resolved ONLY inside the broker callback scope
via an injected SecretMaterialResolver. Token never leaves the callback,
is never logged, and is never returned to the caller.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Final, cast

import httpx

from backend.app.db.models.secret_ref import SecretRef
from backend.app.services.repoproxy.github_app_adapter import (
    GitHubBrokeredTransport,
    GitHubDraftPRResponse,
)
from backend.app.services.repoproxy.repoproxy import DraftPRRequest
from backend.app.services.repoproxy.webhook_adapters import SecretMaterialResolver
from backend.app.services.secrets.broker import BrokerOperationContext

GITHUB_API_BASE: Final = "https://api.github.com"
MAX_RETRY_ATTEMPTS: Final = 3
RETRY_BASE_SECONDS: Final = 1.0
RETRY_MIN_WAIT: Final = 60.0
CONNECT_TIMEOUT: Final = 30.0
READ_TIMEOUT: Final = 60.0
WRITE_TIMEOUT: Final = 60.0
POOL_TIMEOUT: Final = 10.0

_TOKEN_CHAR_RE: Final = re.compile(r"\A[A-Za-z0-9_\-./+=]+\Z")


class GitHubTransportError(Exception):
    pass


class LiveRefChangedError(GitHubTransportError):
    pass


class SecretRefMismatchError(GitHubTransportError):
    pass


class InvalidTokenError(GitHubTransportError):
    pass


@dataclass(frozen=True, slots=True)
class BranchPushRequest:
    repo_full_name: str
    branch: str
    commit_sha: str
    artifact_hash: str


@dataclass(frozen=True, slots=True)
class BranchPushResult:
    success: bool
    head_sha: str | None
    deny_reason: str | None


class HttpxGitHubTransport(GitHubBrokeredTransport):
    """Concrete httpx transport satisfying GitHubBrokeredTransport Protocol.

    Resolves installation token inside broker callback via material_resolver.
    Token never appears in return values, logs, or exceptions.
    """

    def __init__(
        self,
        *,
        material_resolver: SecretMaterialResolver,
        secret_ref: SecretRef,
    ) -> None:
        self._material_resolver = material_resolver
        self._secret_ref = secret_ref

    async def create_draft_pr(
        self,
        *,
        context: BrokerOperationContext,
        request: DraftPRRequest,
        api_version: str,
    ) -> GitHubDraftPRResponse:
        self._verify_context_secret_ref(context)
        token = await self._resolve_token()
        try:
            live_sha = await self._get_branch_head_sha(
                token=token,
                repo=request.repo_full_name,
                branch=request.head_branch,
                api_version=api_version,
            )
            if live_sha != request.commit_sha:
                raise LiveRefChangedError(
                    "live branch HEAD differs from request.commit_sha"
                )

            response = await self._post_with_retry(
                url=f"{GITHUB_API_BASE}/repos/{request.repo_full_name}/pulls",
                token=token,
                api_version=api_version,
                json_body={
                    "title": "[Agent] Draft PR from run",
                    "head": request.head_branch,
                    "base": request.base_branch,
                    "draft": True,
                },
            )
            return GitHubDraftPRResponse(
                pr_number=cast(int, response["number"]),
                pr_url=cast(str, response["html_url"]),
                draft=cast(bool, response.get("draft", True)),
            )
        finally:
            del token

    def _verify_context_secret_ref(self, context: BrokerOperationContext) -> None:
        if context.secret_handle.secret_ref_id != self._secret_ref.id:
            raise SecretRefMismatchError(
                "broker-authorized secret_ref_id does not match transport secret_ref"
            )

    async def _get_branch_head_sha(
        self,
        *,
        token: bytes,
        repo: str,
        branch: str,
        api_version: str,
    ) -> str:
        async with self._build_client(token, api_version) as client:
            resp = await client.get(f"{GITHUB_API_BASE}/repos/{repo}/git/ref/heads/{branch}")
            if resp.status_code != 200:
                raise GitHubTransportError(
                    f"ref lookup failed (status={resp.status_code})"
                )
            data = resp.json()
            return str(data["object"]["sha"])

    async def _resolve_token(self) -> bytes:
        material = await self._material_resolver.resolve_secret_material(self._secret_ref)
        if isinstance(material, str):
            raw = material.strip().encode()
        else:
            raw = material.strip()
        token_str = raw.decode(errors="replace")
        if not _TOKEN_CHAR_RE.match(token_str):
            raise InvalidTokenError("resolved token contains invalid characters")
        return raw

    async def _post_with_retry(
        self,
        *,
        url: str,
        token: bytes,
        api_version: str,
        json_body: dict[str, object],
    ) -> dict[str, Any]:
        import asyncio

        last_error: Exception | None = None
        for attempt in range(MAX_RETRY_ATTEMPTS):
            async with self._build_client(token, api_version) as client:
                resp = await client.post(url, json=json_body)

                if _is_rate_limited(resp):
                    wait = _compute_rate_limit_wait(resp, attempt)
                    await asyncio.sleep(wait)
                    last_error = GitHubTransportError(f"rate limited (attempt {attempt + 1})")
                    continue

                if resp.status_code >= 500:
                    await asyncio.sleep(RETRY_BASE_SECONDS * (2**attempt))
                    last_error = GitHubTransportError(f"server error {resp.status_code}")
                    continue

                if resp.status_code >= 400:
                    raise GitHubTransportError(
                        f"client error (status={resp.status_code})"
                    )

                return resp.json()  # type: ignore[no-any-return]

        raise last_error or GitHubTransportError("retry exhausted")

    def _build_client(self, token: bytes, api_version: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {token.decode()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": api_version,
            },
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT,
                read=READ_TIMEOUT,
                write=WRITE_TIMEOUT,
                pool=POOL_TIMEOUT,
            ),
            trust_env=False,
        )


def _is_rate_limited(resp: httpx.Response) -> bool:
    if resp.status_code == 429:
        return True
    if resp.status_code == 403:
        remaining = resp.headers.get("x-ratelimit-remaining")
        if remaining == "0":
            return True
        body_text = resp.text[:500] if resp.text else ""
        if "rate limit" in body_text.lower() or "secondary" in body_text.lower():
            return True
    return False


def _compute_rate_limit_wait(resp: httpx.Response, attempt: int) -> float:
    retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
    if retry_after is not None:
        return min(retry_after, 300.0)

    reset_at = _parse_ratelimit_reset(resp.headers.get("x-ratelimit-reset"))
    if reset_at is not None:
        wait = max(reset_at - time.time(), 0.0)
        return min(wait, 300.0)

    return float(max(RETRY_MIN_WAIT, RETRY_BASE_SECONDS * (2**attempt)))


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_ratelimit_reset(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # epoch seconds
    except (ValueError, OverflowError):
        return None


__all__ = [
    "BranchPushRequest",
    "BranchPushResult",
    "GitHubTransportError",
    "HttpxGitHubTransport",
    "InvalidTokenError",
    "LiveRefChangedError",
    "SecretRefMismatchError",
]
