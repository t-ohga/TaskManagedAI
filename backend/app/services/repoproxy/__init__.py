"""Sprint 8: GitHub App + RepoProxy + Draft PR boundary.

ADR-00011 (GitHub App Permission Matrix) は design decision として
`accepted`。SP-008 は `partial_skeleton` で、Matrix loader / Mock RepoProxy /
Webhook HMAC helper / server-owned Draft PR binding を先行整備している。
実 GitHub App integration は後続 batch で実装する。

server-owned-boundary §1:
- installation_token は SecretBroker 内でのみ resolve
- RepoProxy は broker-mediated operation 経由のみ httpx request 実行
- raw token は caller / AI / runner / artifact / log / audit に渡さない
"""

from __future__ import annotations

from backend.app.services.repoproxy.draft_pr_resolver import DbDraftPRRequestResolver
from backend.app.services.repoproxy.github_app_adapter import (
    GITHUB_API_VERSION,
    GitHubAppAdapter,
    GitHubDraftPRResponse,
)
from backend.app.services.repoproxy.repo_pr_event import (
    RepoPROpenedEventDenyReason,
    RepoPROpenedEventPayload,
    RepoPROpenedEventWriter,
    append_repo_pr_opened_event,
    build_repo_pr_opened_payload,
)
from backend.app.services.repoproxy.webhook_service import (
    GITHUB_WEBHOOK_DENIED_AUDIT_EVENT_TYPE,
    GITHUB_WEBHOOK_REPLAY_WINDOW_SECONDS,
    GITHUB_WEBHOOK_VERIFIED_AUDIT_EVENT_TYPE,
    WEBHOOK_HMAC_FAILED_AUDIT_EVENT_TYPE,
    GitHubWebhookReasonCode,
    GitHubWebhookRequest,
    GitHubWebhookVerificationResult,
    GitHubWebhookVerifier,
    WebhookSecretCandidate,
    WebhookSecretCandidates,
)

__all__ = [
    "DbDraftPRRequestResolver",
    "GITHUB_API_VERSION",
    "GITHUB_WEBHOOK_DENIED_AUDIT_EVENT_TYPE",
    "GITHUB_WEBHOOK_REPLAY_WINDOW_SECONDS",
    "GITHUB_WEBHOOK_VERIFIED_AUDIT_EVENT_TYPE",
    "WEBHOOK_HMAC_FAILED_AUDIT_EVENT_TYPE",
    "GitHubAppAdapter",
    "GitHubDraftPRResponse",
    "GitHubWebhookReasonCode",
    "GitHubWebhookRequest",
    "GitHubWebhookVerificationResult",
    "GitHubWebhookVerifier",
    "RepoPROpenedEventDenyReason",
    "RepoPROpenedEventPayload",
    "RepoPROpenedEventWriter",
    "WebhookSecretCandidate",
    "WebhookSecretCandidates",
    "append_repo_pr_opened_event",
    "build_repo_pr_opened_payload",
]
