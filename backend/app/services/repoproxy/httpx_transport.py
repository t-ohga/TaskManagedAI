"""Real httpx transport for broker-mediated GitHub API calls.

Raw installation token is resolved ONLY inside the broker callback scope
via an injected SecretMaterialResolver. Token never leaves the callback,
is never logged, and is never returned to the caller.
"""

from __future__ import annotations

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
CONNECT_TIMEOUT: Final = 30.0
READ_TIMEOUT: Final = 60.0


class GitHubTransportError(Exception):
    pass


class LiveRefChangedError(GitHubTransportError):
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
            return material.encode()
        return material

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

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", RETRY_BASE_SECONDS * (2**attempt)))
                    await asyncio.sleep(min(retry_after, 60))
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
            timeout=httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT),
        )


__all__ = [
    "BranchPushRequest",
    "BranchPushResult",
    "GitHubTransportError",
    "HttpxGitHubTransport",
    "LiveRefChangedError",
]
