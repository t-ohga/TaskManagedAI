"""SP-PHASE0 gate C (Codex adversarial HIGH 2): orchestrator withhold test.

CREDENTIAL_EXFILTRATION 検出時、orchestrator が **raw artifact を再読込・再 redact
せず** ``[withheld: credential_exfiltration]`` placeholder のみ emit することを確認
する。narrower ``_RAW_SECRET_PATTERNS`` で raw credential (JWT 等) が survive して
outcome / redaction に出る AC-HARD-02 違反経路が閉じていることを fail-fast で固定。

fake / canary credential のみ使用 (実 token を fixture/outcome に残さない)。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

from backend.app.services.cli_artifact.cancel_propagation import (
    CancelKey,
    CancelRegistry,
)
from backend.app.services.cli_artifact.launcher import LauncherDenyReason
from backend.app.services.cli_artifact.orchestrator import (
    CliInvocationOrchestrator,
    CliInvocationRequest,
)
from backend.app.services.cli_artifact.registry import (
    AgentRegistryEntry,
    CliAgentRegistry,
)

# fake JWT credential (実 token ではない、合成値のみ)。
_FAKE_JWT = (
    "eyJhbGciOiJIUzI1NiJ9."
    "eyJzdWIiOiJjYW5hcnktZmFrZS1ub3QtcmVhbCJ9."
    "ZmFrZXNpZ25hdHVyZS1jYW5hcnktMDAwMA"
)


@pytest.fixture(autouse=True)
def _require_posix() -> None:
    if os.name != "posix":
        pytest.skip(f"launcher tests require POSIX shell, not {sys.platform}")


def _registry_writing_credential_to_output(cwd_base: str) -> CliAgentRegistry:
    """{output_file} へ fake credential を書く sh agent (malicious CLI を模す)。"""

    entry = AgentRegistryEntry(
        name="leaker",
        binary_path="/bin/sh",
        argv_template=(
            "-c",
            f'printf "%s" "id_token: {_FAKE_JWT}" > "$1"',
            "sh",
            "{output_file}",
        ),
        stdin_source="",
        env_passthrough=frozenset({"PATH"}),
        timeout_seconds=10,
        max_stdout_bytes=4096,
        max_stderr_bytes=4096,
        max_payload_data_class="internal",
        cwd_allowlist=(cwd_base,),
    )
    return CliAgentRegistry(
        schema_version="1.2.0",
        agents=MappingProxyType({"leaker": entry}),
    )


@pytest.mark.asyncio
async def test_orchestrator_withholds_raw_on_credential_exfiltration(
    tmp_path: Path,
) -> None:
    base = tmp_path / "artifacts"
    base.mkdir(mode=0o700)
    registry = _registry_writing_credential_to_output(str(base))
    orchestrator = CliInvocationOrchestrator(
        registry=registry,
        cancel_registry=CancelRegistry(),
    )
    request = CliInvocationRequest(
        agent_name="leaker",
        tenant_id="t1",
        run_id="0123abcd-0000-4000-8000-000000000001",
        actor_id="0123abcd-0000-4000-8000-0000000000aa",
        prompt_bytes=b"review this diff",
        artifact_workdir_base=str(base),
    )

    outcome = await orchestrator.invoke(request)

    # CREDENTIAL_EXFILTRATION deny で launcher_result は None。
    assert outcome.launcher_result is None
    assert outcome.launcher_error_reason == LauncherDenyReason.CREDENTIAL_EXFILTRATION.value
    # hit-kind metadata は記録される (raw 値非含)。
    assert "jwt_credential_token" in outcome.credential_canary_hit_kinds

    # 核心 (AC-HARD-02): raw credential が outcome / redaction に **一切出ない**。
    assert outcome.stdout_redaction is not None
    assert outcome.stderr_redaction is not None
    for red in (outcome.stdout_redaction, outcome.stderr_redaction):
        assert red.redacted_text == "[withheld: credential_exfiltration]"
        assert _FAKE_JWT not in red.redacted_text
        # content_hash も withheld placeholder の hash であり raw を参照しない。
        assert "eyJ" not in red.redacted_text
        # 再読込・再 redact していないので raw_bytes_length は 0。
        assert red.raw_bytes_length == 0
        assert red.hits == ()

    # raw credential は output_file (disk) には書かれているが、それは caller の
    # quarantine 責任。outcome 経路に raw が乗らないことを本 test が保証する。
    fd = os.open(outcome.workdir.output_file, os.O_RDONLY)
    try:
        written = os.read(fd, 65536)
    finally:
        os.close(fd)
    assert _FAKE_JWT.encode() in written  # disk には残る (caller が隔離)


def _registry_credential_then_sleep(cwd_base: str) -> CliAgentRegistry:
    """{output_file} へ fake credential を書いてから sleep する sh agent。

    cancel race を deterministic にするため、credential write は sleep より前に
    完了する (cancel 時点で output_file に credential が既に存在)。
    """

    entry = AgentRegistryEntry(
        name="slow_leaker",
        binary_path="/bin/sh",
        argv_template=(
            "-c",
            f'printf "%s" "id_token: {_FAKE_JWT}" > "$1"; sleep 30',
            "sh",
            "{output_file}",
        ),
        stdin_source="",
        env_passthrough=frozenset({"PATH"}),
        timeout_seconds=300,
        max_stdout_bytes=4096,
        max_stderr_bytes=4096,
        max_payload_data_class="internal",
        cwd_allowlist=(cwd_base,),
    )
    return CliAgentRegistry(
        schema_version="1.2.0",
        agents=MappingProxyType({"slow_leaker": entry}),
    )


@pytest.mark.asyncio
async def test_orchestrator_withholds_raw_on_cancel_during_launch(
    tmp_path: Path,
) -> None:
    """SP-PHASE0 gate C (Codex adversarial HIGH sibling-path): cancel-during-launch
    path も canary scan を通り、cancel race 中に credential を echo した malicious
    CLI の raw token が outcome / redaction に出ないことを確認する。

    cancel path は launcher の canary scan より前に CancelledError を raise する
    ため、orchestrator の ``_drain_artifact_streams`` に組み込んだ self-scan が
    唯一の防御層。narrow ``redact_stream`` で raw が survive する経路が閉じている
    ことを fail-fast で固定。
    """

    base = tmp_path / "artifacts"
    base.mkdir(mode=0o700)
    registry = _registry_credential_then_sleep(str(base))
    cancel_registry = CancelRegistry()
    orchestrator = CliInvocationOrchestrator(
        registry=registry,
        cancel_registry=cancel_registry,
    )
    tenant_id = "t1"
    run_id = "0123abcd-0000-4000-8000-000000000002"
    request = CliInvocationRequest(
        agent_name="slow_leaker",
        tenant_id=tenant_id,
        run_id=run_id,
        actor_id="0123abcd-0000-4000-8000-0000000000bb",
        prompt_bytes=b"review this diff",
        artifact_workdir_base=str(base),
    )
    cancel_key = CancelKey(tenant_id=tenant_id, run_id=run_id)

    invoke_task = asyncio.create_task(orchestrator.invoke(request))
    # mid-flight cancel: credential が output_file に書かれた後、sleep 中に signal。
    await asyncio.sleep(0.5)
    cancel_registry.signal(cancel_key)
    outcome = await asyncio.wait_for(invoke_task, timeout=15)

    # cancel-during-launch path に入ったことを確認。
    assert outcome.launcher_error_reason == "cancelled_during_launch"
    assert outcome.cancelled_via_registry is True
    # canary scan が hit を検出 (drain helper の self-scan)。
    assert "jwt_credential_token" in outcome.credential_canary_hit_kinds

    # 核心 (AC-HARD-02): cancel path でも raw credential が outcome に出ない。
    assert outcome.stdout_redaction is not None
    assert outcome.stderr_redaction is not None
    assert outcome.stdout_redaction.redacted_text == "[withheld: credential_exfiltration]"
    assert _FAKE_JWT not in outcome.stdout_redaction.redacted_text
    assert "eyJ" not in outcome.stdout_redaction.redacted_text
    assert outcome.stdout_redaction.raw_bytes_length == 0

    # disk には credential が残る (caller の quarantine 責任、outcome 経路は clean)。
    fd = os.open(outcome.workdir.output_file, os.O_RDONLY)
    try:
        written = os.read(fd, 65536)
    finally:
        os.close(fd)
    assert _FAKE_JWT.encode() in written


@pytest.mark.asyncio
async def test_orchestrator_cancel_clean_output_no_false_withhold(
    tmp_path: Path,
) -> None:
    """cancel path で credential を含まない出力は withhold されない (誤検出なし)。"""

    base = tmp_path / "artifacts"
    base.mkdir(mode=0o700)
    entry = AgentRegistryEntry(
        name="slow_clean",
        binary_path="/bin/sh",
        argv_template=(
            "-c",
            'printf "%s" "review summary: looks correct" > "$1"; sleep 30',
            "sh",
            "{output_file}",
        ),
        stdin_source="",
        env_passthrough=frozenset({"PATH"}),
        timeout_seconds=300,
        max_stdout_bytes=4096,
        max_stderr_bytes=4096,
        max_payload_data_class="internal",
        cwd_allowlist=(str(base),),
    )
    registry = CliAgentRegistry(
        schema_version="1.2.0",
        agents=MappingProxyType({"slow_clean": entry}),
    )
    cancel_registry = CancelRegistry()
    orchestrator = CliInvocationOrchestrator(
        registry=registry,
        cancel_registry=cancel_registry,
    )
    tenant_id = "t1"
    run_id = "0123abcd-0000-4000-8000-000000000003"
    request = CliInvocationRequest(
        agent_name="slow_clean",
        tenant_id=tenant_id,
        run_id=run_id,
        actor_id="0123abcd-0000-4000-8000-0000000000cc",
        prompt_bytes=b"x",
        artifact_workdir_base=str(base),
    )
    cancel_key = CancelKey(tenant_id=tenant_id, run_id=run_id)

    invoke_task = asyncio.create_task(orchestrator.invoke(request))
    await asyncio.sleep(0.5)
    cancel_registry.signal(cancel_key)
    outcome = await asyncio.wait_for(invoke_task, timeout=15)

    assert outcome.launcher_error_reason == "cancelled_during_launch"
    assert outcome.credential_canary_hit_kinds == ()
    # clean output は通常の redaction を通る (withhold ではない)。
    assert outcome.stdout_redaction is not None
    assert (
        outcome.stdout_redaction.redacted_text != "[withheld: credential_exfiltration]"
    )
    assert "review summary" in outcome.stdout_redaction.redacted_text
