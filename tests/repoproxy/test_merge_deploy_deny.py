"""Sprint 8 BL-0101 + Codex SP8 R1 F-SP8-003 adopt: 3 層 defense-in-depth で
merge / deploy P0 deny を regression 固定。

ADR-00011 §採用案 §merge / deploy P0 deny (3 層):
1. **SecretBroker.allowed_operations**: `RequestedOperation` Literal に
   merge/deploy を **登録しない** → issue 時点で 型レベル + runtime deny
2. **Policy Engine**: action_class merge/deploy は P0 default deny
   (Sprint 3 既存、本 audit 範囲外、`tests/policy/test_initial_policy_matrix.py`
   で別 verify)
3. **FastAPI 経路**: merge/deploy endpoint が**存在しない** (file/route 不在)

本 test は 1 + 3 を統合 regression 化 (2 は既存)。Sprint 11 で
`GitHubAppRepoProxy` 実装時にも 3 層を維持する gate。
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

from backend.app.domain.agent_runtime.operation_context import RequestedOperation


def test_layer1_requested_operation_excludes_merge_deploy() -> None:
    """**Layer 1**: RequestedOperation Literal に merge/deploy が存在しない。
    capability token issue API は型レベルで merge/deploy を受け付けない。
    """
    valid_operations = get_args(RequestedOperation)
    assert "merge" not in valid_operations, (
        f"merge が RequestedOperation に含まれる → SecretBroker から "
        f"merge capability token issue 可能になる risk。valid={valid_operations}"
    )
    assert "deploy" not in valid_operations, (
        f"deploy が RequestedOperation に含まれる → SecretBroker から "
        f"deploy capability token issue 可能になる risk。valid={valid_operations}"
    )


def test_layer1_only_p0_safe_operations_registered() -> None:
    """**Layer 1**: RequestedOperation は P0 で許可された operation のみ。
    将来追加 (merge/deploy 含む) は ADR-00011 update 必須。
    """
    valid_operations = get_args(RequestedOperation)
    expected_p0 = frozenset(
        {
            "provider.call",
            "repo.push",
            "repo.pr_open",
            "secret.verify",
            "rotation.read_old",
            "rotation.read_new",
        }
    )
    assert set(valid_operations) == expected_p0, (
        f"RequestedOperation drift detected. P0 = {expected_p0}, "
        f"actual = {set(valid_operations)}"
    )


def test_layer3_no_merge_deploy_fastapi_route_files() -> None:
    """**Layer 3**: FastAPI に merge/deploy endpoint 用 route file が存在しない。

    backend/app/api/ に `merge.py` / `deploy.py` / `merge_*.py` / `deploy_*.py`
    が存在しないこと、router prefix に `/merge` / `/deploy` が含まれないことを
    検証する (Sprint 11 で `GitHubAppRepoProxy` 実装後も維持される gate)。
    """
    api_dir = Path(__file__).resolve().parents[2] / "backend" / "app" / "api"
    assert api_dir.is_dir(), f"backend/app/api/ not found at {api_dir}"

    forbidden_filenames = ("merge.py", "deploy.py")
    forbidden_prefixes = ("merge_", "deploy_")
    for f in api_dir.glob("*.py"):
        assert f.name not in forbidden_filenames, (
            f"forbidden API file exists: {f}; P0 では merge/deploy endpoint を "
            f"作らない (ADR-00011 §採用案 §3 層 defense)"
        )
        assert not any(f.name.startswith(p) for p in forbidden_prefixes), (
            f"API file with forbidden prefix: {f}"
        )


def test_layer3_no_merge_deploy_in_existing_routers() -> None:
    """**Layer 3**: 既存 router の prefix / route に `/merge` / `/deploy` が
    含まれないこと (grep ベース静的 verify)。
    """
    api_dir = Path(__file__).resolve().parents[2] / "backend" / "app" / "api"
    for f in api_dir.glob("*.py"):
        content = f.read_text(encoding="utf-8")
        # router prefix に /merge / /deploy が含まれていないか
        forbidden_patterns = (
            "/merge",
            "/deploy",
            'prefix="/merge"',
            'prefix="/deploy"',
        )
        for pattern in forbidden_patterns:
            assert pattern not in content, (
                f"forbidden pattern {pattern!r} found in {f}; "
                f"P0 では merge/deploy endpoint を作らない"
            )


def test_repoproxy_mock_always_denies_merge_deploy() -> None:
    """**Layer 1 cross-check**: MockRepoProxy.deny_merge / deny_deploy は
    常に DENIED を返す (Sprint 8 Mock 層の test、Sprint 11 で
    GitHubAppRepoProxy で同じ assertion が成立する)。
    """
    import asyncio

    from backend.app.services.repoproxy.repoproxy import (
        MockRepoProxy,
        RepoProxyDenyReason,
    )

    async def _check() -> None:
        proxy = MockRepoProxy()
        merge_result = await proxy.deny_merge("owner/repo", pr_number=1)
        assert merge_result.deny_reason == RepoProxyDenyReason.MERGE_DENIED_P0

        deploy_result = await proxy.deny_deploy("owner/repo", environment="prod")
        assert deploy_result.deny_reason == RepoProxyDenyReason.DEPLOY_DENIED_P0

    asyncio.run(_check())
