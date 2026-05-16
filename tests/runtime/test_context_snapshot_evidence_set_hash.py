"""Unit tests for ContextSnapshotRepository.create_snapshot_from_evidence
(Sprint 10 BL-0117 / Codex PR #23 R4 F-R4-004 P1 adopt).

Sprint Pack SP-010 受け入れ条件 §line 211:
``evidence_set_hash の caller-supplied hash 経路がない`` (server-owned-boundary §1).

These tests verify the **wiring**: the new server-owned helper computes
``evidence_set_hash`` from inputs (claims / sources / provenance /
evidence_items) and forwards the computed value to ``create_snapshot``.

The DB-touching integration is in ``tests/runtime/test_context_snapshot_
invariants.py`` (real PostgreSQL); this file uses a method-mocked
repository so the contract test runs without a database.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from backend.app.repositories.context_snapshot import ContextSnapshotRepository
from backend.app.services.research.evidence_set_hash import (
    ClaimNormalized,
    EvidenceItemNormalized,
    EvidenceSetHashError,
    SourceNormalized,
    compute_evidence_set_hash,
)


def _make_claim(text: str = "claim text", claim_id: UUID | None = None) -> ClaimNormalized:
    return ClaimNormalized.from_raw(claim_id=claim_id or uuid4(), claim_text=text)


def _make_source(
    url: str = "https://example.com/x",
    content_hash: str | None = None,
    source_id: UUID | None = None,
) -> SourceNormalized:
    return SourceNormalized.from_raw(
        source_id=source_id or uuid4(),
        canonical_url=url,
        content_hash=content_hash or ("a" * 64),
    )


def _valid_repo_state() -> dict[str, Any]:
    return {
        "commit_sha": "0" * 40,
        "branch": "main",
        "dirty": False,
        "diff_hash": "1" * 64,
    }


def _valid_tool_manifest() -> dict[str, Any]:
    return {
        "registry_version": "1",
        "allowlist_hash": "2" * 64,
    }


def _valid_provider_request_fingerprint() -> dict[str, Any]:
    return {"model_resolved": "gpt-test"}


@pytest.fixture
def repo() -> ContextSnapshotRepository:
    """ContextSnapshotRepository with a mocked AsyncSession; we patch
    ``create_snapshot`` directly so the contract test does not touch DB."""
    session = MagicMock()
    return ContextSnapshotRepository(session, tenant_id=1)


@pytest.mark.asyncio
async def test_create_snapshot_from_evidence_computes_hash_server_side(
    repo: ContextSnapshotRepository,
) -> None:
    """F-R4-004 wiring contract: the helper must call compute_evidence_set_hash
    on the supplied inputs and forward the computed value to create_snapshot.
    Callers do NOT pass evidence_set_hash through."""
    cid = uuid4()
    sid = uuid4()
    eid = uuid4()
    claims = [_make_claim(claim_id=cid)]
    sources = [_make_source(source_id=sid)]
    prov: dict[UUID, Any] = {
        cid: {"wasGeneratedBy": [{"generated": "e1", "activity": "a1"}]}
    }
    items = [
        EvidenceItemNormalized.from_raw(
            id=eid,
            claim_id=cid,
            source_id=sid,
            locator="p.1",
            relation="supports",
            relevance_score=0.9,
        )
    ]

    expected_hash = compute_evidence_set_hash(
        claims, sources, prov, evidence_items=items, require_provenance=True
    )

    repo.create_snapshot = AsyncMock()  # type: ignore[method-assign]

    await repo.create_snapshot_from_evidence(
        tenant_id=1,
        run_id=uuid4(),
        claims=claims,
        sources=sources,
        provenance_per_claim=prov,
        evidence_items=items,
        prompt_pack_version="pp-1",
        prompt_pack_lock="3" * 64,
        policy_version="pv-1",
        policy_pack_lock="4" * 64,
        repo_state=_valid_repo_state(),
        tool_manifest=_valid_tool_manifest(),
        provider_continuation_ref=None,
        provider_request_fingerprint=_valid_provider_request_fingerprint(),
        snapshot_kind="input",
    )

    repo.create_snapshot.assert_awaited_once()
    _, kwargs = repo.create_snapshot.call_args
    assert kwargs["evidence_set_hash"] == expected_hash, (
        "create_snapshot_from_evidence must compute the hash from inputs, "
        "not let the caller smuggle a pre-computed value through"
    )


@pytest.mark.asyncio
async def test_create_snapshot_from_evidence_has_no_caller_supplied_hash_param(
    repo: ContextSnapshotRepository,
) -> None:
    """server-owned-boundary §1: signature-level physical removal. The new
    server-owned helper MUST NOT accept ``evidence_set_hash`` as a parameter."""
    import inspect

    sig = inspect.signature(repo.create_snapshot_from_evidence)
    assert "evidence_set_hash" not in sig.parameters, (
        "create_snapshot_from_evidence must not expose a caller-supplied "
        "evidence_set_hash parameter (server-owned-boundary §1)"
    )


@pytest.mark.asyncio
async def test_create_snapshot_from_evidence_requires_provenance(
    repo: ContextSnapshotRepository,
) -> None:
    """The production wiring forces ``require_provenance=True`` so a caller
    that omits a claim's provenance fails closed at the boundary (R4 fix
    flows from R2 fail-closed semantics)."""
    cid = uuid4()
    sid = uuid4()
    claims = [_make_claim(claim_id=cid)]
    sources = [_make_source(source_id=sid)]
    # Empty provenance — this would silently hash {} pre-R2.

    repo.create_snapshot = AsyncMock()  # type: ignore[method-assign]

    with pytest.raises(EvidenceSetHashError) as exc:
        await repo.create_snapshot_from_evidence(
            tenant_id=1,
            run_id=uuid4(),
            claims=claims,
            sources=sources,
            provenance_per_claim={},  # missing — must fail closed
            prompt_pack_version="pp-1",
            prompt_pack_lock="3" * 64,
            policy_version="pv-1",
            policy_pack_lock="4" * 64,
            repo_state=_valid_repo_state(),
            tool_manifest=_valid_tool_manifest(),
            provider_continuation_ref=None,
            provider_request_fingerprint=_valid_provider_request_fingerprint(),
            snapshot_kind="input",
        )
    assert exc.value.reason_code == "provenance_missing_for_claim"
    repo.create_snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_snapshot_from_evidence_dangling_evidence_item_rejected(
    repo: ContextSnapshotRepository,
) -> None:
    """F-R4-003 + F-R4-004 integration: a dangling evidence_item membership
    bubbles through create_snapshot_from_evidence to a structured error,
    not into create_snapshot."""
    cid = uuid4()
    sid_in_set = uuid4()
    sid_dangling = uuid4()
    claims = [_make_claim(claim_id=cid)]
    sources = [_make_source(source_id=sid_in_set)]
    prov: dict[UUID, Any] = {
        cid: {"wasGeneratedBy": [{"generated": "e1", "activity": "a1"}]}
    }
    items = [
        EvidenceItemNormalized.from_raw(
            id=uuid4(),
            claim_id=cid,
            source_id=sid_dangling,
            locator="p.1",
            relation="supports",
        )
    ]

    repo.create_snapshot = AsyncMock()  # type: ignore[method-assign]

    with pytest.raises(EvidenceSetHashError) as exc:
        await repo.create_snapshot_from_evidence(
            tenant_id=1,
            run_id=uuid4(),
            claims=claims,
            sources=sources,
            provenance_per_claim=prov,
            evidence_items=items,
            prompt_pack_version="pp-1",
            prompt_pack_lock="3" * 64,
            policy_version="pv-1",
            policy_pack_lock="4" * 64,
            repo_state=_valid_repo_state(),
            tool_manifest=_valid_tool_manifest(),
            provider_continuation_ref=None,
            provider_request_fingerprint=_valid_provider_request_fingerprint(),
            snapshot_kind="input",
        )
    assert exc.value.reason_code == "evidence_item_source_dangling"
    repo.create_snapshot.assert_not_awaited()


def test_module_level_create_snapshot_from_evidence_exported() -> None:
    """The module-level convenience wrapper must be exported alongside
    create_snapshot so other services can adopt it without reaching into
    the repository class."""
    from backend.app.repositories import context_snapshot as cs_mod

    assert hasattr(cs_mod, "create_snapshot_from_evidence")
    assert "create_snapshot_from_evidence" in cs_mod.__all__
