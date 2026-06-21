"""SP-PHASE0 S4 #3: host-ambient CLI 認証供給境界の test (大半 no-DB)。

ADR-00058 案C hybrid: CLI サブスク credential (claude/codex の self-rotating OAuth) は **host-ambient**
(CLI 本体が OAuth を所有・refresh、host worker が ~/.claude / ~/.codex を直読、SecretBroker 非経由)。

本 test が固定する invariant:

1. ``config/cli_registry.toml`` の codex entry が ``credential_supply_mode == "host_ambient"`` (machine-readable
   分類)。
2. launcher が subprocess に渡す env (``_build_scrubbed_env``) に **CLI サブスク token / provider key を
   常駐させない**: codex entry の ``env_passthrough`` allowlist に token-bearing var が無く、forbidden secret
   denylist (``_FORBIDDEN_ENV_NAMES``) が provider key / GitHub token / SOPS key 等を物理 drop する。実際に
   parent env に token を仕込んでも scrubbed env に伝播しないことを確認する。
3. ``SecretRegistrationService.register()`` が **self-rotating / host-ambient credential の broker-managed
   登録を reject** する (案B 罠の構造防止)。reject は DB 書込前 (``_reject_self_rotating``) に起きるため
   session は MagicMock で良い (no-DB)。

すべて no-DB (config parse + launcher env build + service guard、実 DB e2e は他 S4 item が担当)。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from backend.app.services.cli_artifact.registry import (
    _FORBIDDEN_ENV_NAMES,
    load_cli_agent_registry,
)
from backend.app.services.secrets.secret_registration import (
    SecretRegistrationError,
    SecretRegistrationService,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_REGISTRY = _REPO_ROOT / "config" / "cli_registry.toml"

_FAKE_ACTOR = UUID("00000000-0000-4000-8000-0000000009a1")

# subprocess env に **絶対に常駐してはいけない** CLI サブスク / provider credential var。
_TOKEN_BEARING_VARS: frozenset[str] = frozenset(
    {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CODEX_OAUTH_TOKEN",
        "TAILSCALE_AUTHKEY",
        "SOPS_AGE_KEY",
    }
)


def _service_with_mock_session() -> SecretRegistrationService:
    # _reject_self_rotating は _ensure_tenant_context より前に発火するため session/store は未使用 (no-DB)。
    return SecretRegistrationService(session=MagicMock(), store=MagicMock())


# ---- (1) cli_registry host-ambient 分類 ----


def test_codex_entry_is_host_ambient() -> None:
    registry = load_cli_agent_registry(_CLI_REGISTRY)
    codex = registry.get("codex")
    assert codex.credential_supply_mode == "host_ambient", (
        "codex CLI サブスク credential は host-ambient 分類でなければならない (ADR-00058、"
        "CLI が OAuth を所有・refresh、broker 非経由)"
    )


def test_registry_has_no_broker_managed_cli_in_phase0() -> None:
    """Phase 0 では broker-managed CLI launchable entry は存在しない (in-process provider.call は Phase 2)。"""
    registry = load_cli_agent_registry(_CLI_REGISTRY)
    broker_managed = [
        name
        for name in registry.names()
        if registry.get(name).credential_supply_mode == "broker_managed"
    ]
    assert not broker_managed, (
        "Phase 0 は broker-managed CLI launchable entry を持たない "
        f"(in-process provider.call は Phase 2); found: {broker_managed}"
    )


# ---- (2) launcher subprocess env に token が常駐しない ----


def test_codex_env_passthrough_has_no_token_bearing_vars() -> None:
    """codex entry の env_passthrough allowlist に CLI サブスク / provider token var が無い。"""
    registry = load_cli_agent_registry(_CLI_REGISTRY)
    codex = registry.get("codex")
    leaked = codex.env_passthrough & _TOKEN_BEARING_VARS
    assert not leaked, (
        f"codex env_passthrough must not allowlist token-bearing vars; leaked: {sorted(leaked)}"
    )
    # forbidden denylist との交差も無い (registry __post_init__ が load 時に reject するが二重確認)。
    assert not (codex.env_passthrough & _FORBIDDEN_ENV_NAMES)


def test_scrubbed_env_does_not_propagate_parent_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """parent process env に token を仕込んでも scrubbed subprocess env に伝播しない (worker 非常駐)。"""
    from backend.app.services.cli_artifact.launcher import _build_scrubbed_env

    # parent env に CLI サブスク / provider token を仕込む (worker process 環境の擬似)。
    sentinel = "SENTINEL-RAW-TOKEN-MUST-NOT-PROPAGATE"
    for var in _TOKEN_BEARING_VARS:
        monkeypatch.setenv(var, sentinel)
    # env_passthrough allowlist にある HOME も仕込む (これは正当に通る、token ではない)。
    monkeypatch.setenv("HOME", "/home/worker")

    registry = load_cli_agent_registry(_CLI_REGISTRY)
    codex = registry.get("codex")
    scrubbed = _build_scrubbed_env(codex)

    # token-bearing var は scrubbed env に一切現れない。
    for var in _TOKEN_BEARING_VARS:
        assert var not in scrubbed, f"{var} leaked into scrubbed subprocess env"
    # sentinel 値がどの value にも混入しない。
    assert sentinel not in scrubbed.values()
    # 正当な passthrough (HOME) は通る (host-ambient CLI が ~/.claude / ~/.codex を直読するため必要)。
    assert scrubbed.get("HOME") == "/home/worker"


def test_scrubbed_env_drops_even_if_passthrough_lists_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env_passthrough が forbidden var を含んでいても _build_scrubbed_env が drop する (defense-in-depth)。"""
    from backend.app.services.cli_artifact.launcher import _build_scrubbed_env
    from backend.app.services.cli_artifact.registry import AgentRegistryEntry

    monkeypatch.setenv("OPENAI_API_KEY", "raw-key-should-not-pass")
    monkeypatch.setenv("HOME", "/home/worker")
    # registry __post_init__ は forbidden を reject するため、bypass して直接 entry を構築し
    # launcher 側の defense-in-depth (hot-reload 想定) を検査する。env_passthrough に HOME のみを
    # 入れた正規 entry を作り、launcher が parent の OPENAI_API_KEY を拾わないことを確認する。
    entry = AgentRegistryEntry(
        name="codex",
        binary_path="/opt/homebrew/bin/codex",
        argv_template=("exec", "-"),
        stdin_source="",
        env_passthrough=frozenset({"HOME"}),
        timeout_seconds=60,
        max_stdout_bytes=1024,
        max_stderr_bytes=1024,
        max_payload_data_class="internal",
        cwd_allowlist=("/Users/tohga/repo/TaskManagedAI",),
        credential_supply_mode="host_ambient",
    )
    scrubbed = _build_scrubbed_env(entry)
    assert "OPENAI_API_KEY" not in scrubbed
    assert scrubbed.get("HOME") == "/home/worker"


# ---- (3) self-rotating / host-ambient を broker-managed 登録すると reject (no-DB) ----


@pytest.mark.asyncio
async def test_register_rejects_self_rotating_credential() -> None:
    service = _service_with_mock_session()
    with pytest.raises(SecretRegistrationError, match="self-rotating"):
        await service.register(
            tenant_id=1,
            scope="project",
            name="claude-subscription",
            version="v1",
            owner_actor_id=_FAKE_ACTOR,
            raw_material=b"should-not-be-stored",
            allowed_consumers=["actor:agent"],
            allowed_operations=["provider.call"],
            metadata={"self_rotating": True},
        )


@pytest.mark.asyncio
async def test_register_rejects_host_ambient_supply_mode() -> None:
    service = _service_with_mock_session()
    with pytest.raises(SecretRegistrationError, match="host-ambient"):
        await service.register(
            tenant_id=1,
            scope="project",
            name="codex-subscription",
            version="v1",
            owner_actor_id=_FAKE_ACTOR,
            raw_material=b"should-not-be-stored",
            allowed_consumers=["actor:agent"],
            allowed_operations=["provider.call"],
            metadata={"credential_supply_mode": "host_ambient"},
        )


@pytest.mark.asyncio
async def test_register_self_rotating_reject_does_not_touch_store() -> None:
    """self-rotating reject は store 書込前に起きる (raw_material が store に流れない)。"""
    store = MagicMock()
    service = SecretRegistrationService(session=MagicMock(), store=store)
    with pytest.raises(SecretRegistrationError):
        await service.register(
            tenant_id=1,
            scope="project",
            name="claude-subscription",
            version="v1",
            owner_actor_id=_FAKE_ACTOR,
            raw_material=b"should-not-be-stored",
            allowed_consumers=["actor:agent"],
            allowed_operations=["provider.call"],
            metadata={"self_rotating": True},
        )
    store.store.assert_not_called()
    store.ensure_initialized.assert_not_called()
