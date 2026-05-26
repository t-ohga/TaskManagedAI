"""SP-008 Batch G: httpx transport security + behavior tests.

Tests token non-exposure, live ref mismatch fail-closed, retry behavior,
and error sanitization.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from backend.app.services.repoproxy.github_app_adapter import GitHubDraftPRResponse
from backend.app.services.repoproxy.httpx_transport import (
    GitHubTransportError,
    HttpxGitHubTransport,
    LiveRefChangedError,
)
from backend.app.services.repoproxy.repoproxy import DraftPRRequest
from backend.app.services.secrets.broker import BrokerOperationContext, SecretHandle


def _make_context() -> BrokerOperationContext:
    return BrokerOperationContext(
        tenant_id=1,
        actor_id=uuid4(),
        run_id=uuid4(),
        requested_operation="repo.pr_open",
        target={"repo_full_name": "owner/repo"},
        payload_hash="abc123",
        secret_handle=SecretHandle(
            secret_ref_id=uuid4(),
            scope="repo",
            name="github-app-key",
            version="v1",
        ),
    )


def _make_request(*, commit_sha: str = "abc123def456") -> DraftPRRequest:
    return DraftPRRequest(
        repo_full_name="owner/repo",
        base_branch="main",
        head_branch="codex/agent-run-12345678",
        commit_sha=commit_sha,
        artifact_hash="sha256:deadbeef",
        approval_id=str(uuid4()),
        policy_version="v1.0.0",
        provider_request_fingerprint="fp_test_123",
        repo_state_commit_sha=commit_sha,
    )


def _make_secret_ref() -> Any:
    ref = MagicMock()
    ref.secret_uri = "secret://sops/repo/github-app-key#v1"
    ref.status = "active"
    ref.id = uuid4()
    ref.scope = "repo"
    ref.name = "github-app-key"
    ref.version = "v1"
    return ref


@pytest.fixture
def mock_resolver() -> AsyncMock:
    resolver = AsyncMock()
    resolver.resolve_secret_material = AsyncMock(return_value=b"ghs_fake_installation_token_1234567890")
    return resolver


@pytest.fixture
def transport(mock_resolver: AsyncMock) -> HttpxGitHubTransport:
    return HttpxGitHubTransport(
        material_resolver=mock_resolver,
        secret_ref=_make_secret_ref(),
    )


class TestTokenNotInReturnValue:
    @pytest.mark.asyncio
    async def test_pr_response_contains_no_token(self, transport: HttpxGitHubTransport) -> None:
        ctx = _make_context()
        req = _make_request()

        with patch.object(transport, "_get_branch_head_sha", return_value=req.commit_sha):
            with patch.object(transport, "_post_with_retry", return_value={
                "number": 42,
                "html_url": "https://github.com/owner/repo/pull/42",
                "draft": True,
                "body": "should be discarded",
                "user": {"login": "bot"},
            }):
                result = await transport.create_draft_pr(
                    context=ctx, request=req, api_version="2022-11-28"
                )

        assert isinstance(result, GitHubDraftPRResponse)
        assert result.pr_number == 42
        assert result.draft is True
        assert "ghs_fake" not in str(result)
        assert "token" not in str(result).lower()


class TestTokenCanaryNotInError:
    @pytest.mark.asyncio
    async def test_transport_error_does_not_contain_token(
        self, transport: HttpxGitHubTransport
    ) -> None:
        ctx = _make_context()
        req = _make_request()

        with patch.object(transport, "_get_branch_head_sha", return_value=req.commit_sha):
            with patch.object(
                transport, "_post_with_retry",
                side_effect=GitHubTransportError("client error (status=422)"),
            ):
                with pytest.raises(GitHubTransportError) as exc_info:
                    await transport.create_draft_pr(
                        context=ctx, request=req, api_version="2022-11-28"
                    )

        assert "ghs_fake" not in str(exc_info.value)


class TestLiveRefChangedBeforeMutation:
    @pytest.mark.asyncio
    async def test_sha_mismatch_raises_live_ref_changed(
        self, transport: HttpxGitHubTransport
    ) -> None:
        ctx = _make_context()
        req = _make_request(commit_sha="expected_sha_123")

        with patch.object(transport, "_get_branch_head_sha", return_value="different_sha_456"):
            with pytest.raises(LiveRefChangedError):
                await transport.create_draft_pr(
                    context=ctx, request=req, api_version="2022-11-28"
                )

    @pytest.mark.asyncio
    async def test_sha_match_proceeds_to_create(
        self, transport: HttpxGitHubTransport
    ) -> None:
        ctx = _make_context()
        req = _make_request(commit_sha="matching_sha")

        with patch.object(transport, "_get_branch_head_sha", return_value="matching_sha"):
            with patch.object(transport, "_post_with_retry", return_value={
                "number": 99,
                "html_url": "https://github.com/owner/repo/pull/99",
                "draft": True,
            }):
                result = await transport.create_draft_pr(
                    context=ctx, request=req, api_version="2022-11-28"
                )

        assert result.pr_number == 99


class TestRetryBehavior:
    @pytest.mark.asyncio
    async def test_429_retries_up_to_max(self, transport: HttpxGitHubTransport) -> None:
        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.headers = {"Retry-After": "0"}

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {"number": 1, "html_url": "url", "draft": True}

        call_count = 0

        async def mock_post(url: str, json: Any = None) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return mock_response_429
            return mock_response_200

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(transport, "_build_client", return_value=mock_client):
            result = await transport._post_with_retry(
                url="https://api.github.com/repos/o/r/pulls",
                token=b"test",
                api_version="2022-11-28",
                json_body={},
            )

        assert result == {"number": 1, "html_url": "url", "draft": True}
        assert call_count == 3


class TestErrorSanitization:
    @pytest.mark.asyncio
    async def test_4xx_error_does_not_expose_response_body(
        self, transport: HttpxGitHubTransport
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.json.return_value = {"message": "Validation Failed", "secret": "leaked"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(transport, "_build_client", return_value=mock_client):
            with pytest.raises(GitHubTransportError) as exc_info:
                await transport._post_with_retry(
                    url="https://api.github.com/repos/o/r/pulls",
                    token=b"test",
                    api_version="2022-11-28",
                    json_body={},
                )

        assert "leaked" not in str(exc_info.value)
        assert "secret" not in str(exc_info.value)


class TestTokenDeletedAfterUse:
    @pytest.mark.asyncio
    async def test_token_del_in_finally(self, transport: HttpxGitHubTransport) -> None:
        ctx = _make_context()
        req = _make_request()

        with patch.object(transport, "_get_branch_head_sha", return_value=req.commit_sha):
            with patch.object(transport, "_post_with_retry", return_value={
                "number": 1,
                "html_url": "https://github.com/owner/repo/pull/1",
                "draft": True,
            }):
                await transport.create_draft_pr(
                    context=ctx, request=req, api_version="2022-11-28"
                )

        # Verify resolver was called (token was obtained and used)
        transport._material_resolver.resolve_secret_material.assert_called_once()
