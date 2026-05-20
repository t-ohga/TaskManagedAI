"""SP022-T02 Phase 4 / T08 batch 4: status --remote split-brain detection.

ADR-00021 §11.2 + §285 split-brain prevention first line of defense.

Security invariants:
R1 F-006/F-007/F-016 + ADV R1 F-003/F-006/F-007/F-009/F-011/F-012/F-013/F-014 + ADV R2 F-003 adopt:

- ssh は Tailscale SSH (Tailscale ACL で device 認証済の前提)
- StrictHostKeyChecking=yes + BatchMode=yes + ConnectTimeout 10s
- subprocess は taskhub_subprocess_runner 経由
- stdout cap 64 KiB (post-read len check、runner には cap 機能なし)
- host-specific config は ~/.taskhub/remote_hosts.signed.json (Ed25519 sign 済) から読み込み
- compose_file の sha256 一致 verify (SSH 経由)
- expected_services は exact set 一致を要求 (partial overlap で safe 判定不可)
- safe-down は exited / dead のみ、それ以外 (restarting/paused/created/removing/unknown) は state_unknown で fail-closed
- compose_file は Unicode NFC + Cc/Cf reject (RTL override / control chars)
"""

from __future__ import annotations

import base64
import json
import re
import shlex
import sys
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

# import shared helpers
try:
    from scripts.taskhub_signed_approval import (
        _load_verify_key_and_fingerprint,
        canonical_for_signature,
    )
    from scripts.taskhub_subprocess_runner import (
        SafeSubprocessConfig,
        SubprocessNotFoundError,
        SubprocessTimeoutError,
        run_safe_subprocess,
    )
except ModuleNotFoundError:  # pragma: no cover
    _REPO_ROOT = Path(__file__).resolve().parent.parent
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from scripts.taskhub_signed_approval import (  # noqa: E402
        _load_verify_key_and_fingerprint,
        canonical_for_signature,
    )
    from scripts.taskhub_subprocess_runner import (  # noqa: E402
        SafeSubprocessConfig,
        SubprocessNotFoundError,
        SubprocessTimeoutError,
        run_safe_subprocess,
    )


ReasonCode = Literal[
    "remote_status_ok_down",
    "remote_status_partial_up",
    "remote_status_all_up",
    "remote_status_state_unknown",
    "remote_status_ssh_failed",
    "remote_status_ssh_timeout",
    "remote_status_ssh_auth_failed",
    "remote_status_ssh_host_key_untrusted",
    "remote_status_compose_unavailable",
    "remote_status_invalid_host",
    "remote_status_remote_identity_unverified",
    "remote_status_stdout_oversize",
    "remote_status_compose_output_malformed",
    "remote_status_config_missing",
    "remote_status_config_permission_unsafe",
    "remote_status_config_signature_invalid",
    "remote_status_config_malformed",
    "remote_status_config_expired",
    "remote_status_config_unsupported_version",
]


@dataclass(frozen=True)
class RemoteHostConfig:
    compose_project: str
    compose_file: str
    compose_file_sha256: str  # ADV R1 F-009 adopt
    expected_services: tuple[str, ...]


@dataclass(frozen=True)
class RemoteStatusOptions:
    remote_host: str
    ssh_timeout_sec: int = 10


@dataclass(frozen=True)
class RemoteStatusResult:
    reason_code: ReasonCode
    host: str
    services_up: tuple[str, ...]
    services_down: tuple[str, ...]
    raw_stdout_size_bytes: int
    split_brain_safe: bool


@dataclass(frozen=True)
class RemoteHostsConfigLoadResult:
    reason_code: Literal[
        "config_ok",
        "remote_status_config_missing",
        "remote_status_config_permission_unsafe",
        "remote_status_config_signature_invalid",
        "remote_status_config_malformed",
        "remote_status_config_expired",
        "remote_status_config_unsupported_version",
    ]
    hosts: dict[str, RemoteHostConfig]


# --- signed config loader (ADV R1 F-006/F-009/F-011/F-012/F-014 adopt) ---


def _signed_config_path() -> Path:
    return Path.home() / ".taskhub" / "remote_hosts.signed.json"


def load_remote_hosts_signed_config() -> RemoteHostsConfigLoadResult:
    """Read + signature verify + expiry check の `RemoteHostConfig` dict を返す."""
    path = _signed_config_path()
    if not path.is_file():
        return RemoteHostsConfigLoadResult("remote_status_config_missing", {})
    try:
        st = path.stat()
    except OSError:
        return RemoteHostsConfigLoadResult("remote_status_config_missing", {})
    mode = st.st_mode & 0o777
    if mode != 0o600:
        return RemoteHostsConfigLoadResult("remote_status_config_permission_unsafe", {})

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return RemoteHostsConfigLoadResult("remote_status_config_malformed", {})
    if not isinstance(data, dict):
        return RemoteHostsConfigLoadResult("remote_status_config_malformed", {})

    # ADV R1 F-011 adopt: config_version + expires_at 必須
    if data.get("config_version") != 1:
        return RemoteHostsConfigLoadResult("remote_status_config_unsupported_version", {})

    expires_at_str = data.get("expires_at")
    signed_at_str = data.get("signed_at")
    if not isinstance(expires_at_str, str) or not isinstance(signed_at_str, str):
        return RemoteHostsConfigLoadResult("remote_status_config_malformed", {})
    try:
        expires_at = datetime.strptime(expires_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return RemoteHostsConfigLoadResult("remote_status_config_malformed", {})
    if expires_at <= datetime.now(UTC):
        return RemoteHostsConfigLoadResult("remote_status_config_expired", {})

    # ADV R1 F-012 adopt: shared canonicalizer + signature verify
    signature_b64 = data.get("signature")
    if not isinstance(signature_b64, str):
        return RemoteHostsConfigLoadResult("remote_status_config_malformed", {})
    hosts_raw = data.get("hosts")
    if not isinstance(hosts_raw, dict):
        return RemoteHostsConfigLoadResult("remote_status_config_malformed", {})

    payload_for_sign = {
        "config_version": data["config_version"],
        "signed_at": signed_at_str,
        "expires_at": expires_at_str,
        "hosts": hosts_raw,
    }
    canonical_bytes = canonical_for_signature("remote_hosts.v1", payload_for_sign)

    verify_key, _fingerprint, key_error = _load_verify_key_and_fingerprint()
    if key_error or verify_key is None:
        return RemoteHostsConfigLoadResult("remote_status_config_signature_invalid", {})
    try:
        sig_bytes = base64.b64decode(signature_b64, validate=True)
    except (ValueError, Exception):  # noqa: BLE001
        return RemoteHostsConfigLoadResult("remote_status_config_signature_invalid", {})
    try:
        verify_key.verify(sig_bytes, canonical_bytes)
    except Exception:  # cryptography InvalidSignature
        return RemoteHostsConfigLoadResult("remote_status_config_signature_invalid", {})

    # hosts parse
    hosts: dict[str, RemoteHostConfig] = {}
    for host_name, host_entry in hosts_raw.items():
        if not isinstance(host_entry, dict):
            return RemoteHostsConfigLoadResult("remote_status_config_malformed", {})
        compose_project_v = host_entry.get("compose_project")
        compose_file_v = host_entry.get("compose_file")
        compose_file_sha256_v = host_entry.get("compose_file_sha256")
        expected_services_v = host_entry.get("expected_services")
        if not isinstance(compose_project_v, str) or not compose_project_v:
            return RemoteHostsConfigLoadResult("remote_status_config_malformed", {})
        if not isinstance(compose_file_v, str) or not compose_file_v:
            return RemoteHostsConfigLoadResult("remote_status_config_malformed", {})
        if not isinstance(compose_file_sha256_v, str) or not compose_file_sha256_v:
            return RemoteHostsConfigLoadResult("remote_status_config_malformed", {})
        if not isinstance(expected_services_v, list) or not all(
            isinstance(s, str) and s for s in expected_services_v
        ):
            return RemoteHostsConfigLoadResult("remote_status_config_malformed", {})
        # ADV PR R2 F-004 adopt: 空 list reject (空集合 == 空集合で safe-down 判定無効化を防止)
        if len(expected_services_v) == 0:
            return RemoteHostsConfigLoadResult("remote_status_config_malformed", {})
        hosts[host_name] = RemoteHostConfig(
            compose_project=compose_project_v,
            compose_file=compose_file_v,
            compose_file_sha256=compose_file_sha256_v,
            expected_services=tuple(expected_services_v),
        )
    return RemoteHostsConfigLoadResult("config_ok", hosts)


# --- SSH command construction (R1 F-007 + ADV R1 F-013 adopt) ---


def _validate_compose_file_path(compose_file: str) -> None:
    """ADV R1 F-013 adopt: Unicode NFC + Cc/Cf reject."""
    if not compose_file.startswith("/"):
        msg = f"compose_file must be absolute path: {compose_file!r}"
        raise ValueError(msg)
    if "\x00" in compose_file or "\n" in compose_file:
        msg = "compose_file must not contain NUL or newline"
        raise ValueError(msg)
    nfc = unicodedata.normalize("NFC", compose_file)
    if nfc != compose_file:
        msg = f"compose_file must be in NFC form: {compose_file!r}"
        raise ValueError(msg)
    for ch in compose_file:
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf"):
            msg = f"compose_file contains control/format character: U+{ord(ch):04X}"
            raise ValueError(msg)


def _build_ssh_argv(
    host: str, compose_project: str, compose_file: str, timeout_sec: int,
) -> list[str]:
    """SSH command を vector で構築、shell injection 完全排除 (R1 F-007 adopt)."""
    PROJECT_REGEX = re.compile(r"^[a-z][a-z0-9_-]*$")
    if not PROJECT_REGEX.fullmatch(compose_project):
        msg = f"compose_project invalid: {compose_project!r}"
        raise ValueError(msg)
    _validate_compose_file_path(compose_file)
    # hostname: DNS RFC 1123 compatible + FQDN (Tailscale MagicDNS 等の dotted name)
    # ADV PR F-3 adopt: 1-label only 制限を緩和、複数 label の FQDN 許容
    if not re.fullmatch(
        r"[a-z0-9][a-z0-9-]{0,62}(\.[a-z0-9][a-z0-9-]{0,62})*",
        host,
    ):
        msg = f"host invalid: {host!r}"
        raise ValueError(msg)
    known_hosts_path = Path.home() / ".ssh" / "known_hosts"
    return [
        "ssh",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={known_hosts_path}",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={timeout_sec}",
        "-o", "ServerAliveInterval=5",
        "-o", "ServerAliveCountMax=2",
        "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "GSSAPIAuthentication=no",
        "-o", "PreferredAuthentications=publickey",
        "--",
        host,
        (
            f"docker compose -p {shlex.quote(compose_project)} "
            f"-f {shlex.quote(compose_file)} ps --format json "
            f"&& sha256sum {shlex.quote(compose_file)}"
        ),
    ]


# --- compose ps output parser ---


def _parse_compose_ps_json(stdout: bytes) -> list[dict[str, object]]:
    """docker compose ps --format json output parse.

    ADV PR F-1 adopt: stdout は `docker compose ps --format json && sha256sum <file>` の連結。
    sha256sum 行 (`<64-hex>  <path>`) を **先に separate** してから docker output を解析する。
    Docker は公式仕様で JSON 配列 (or NDJSON、Docker version で異なる) を返す.
    """
    text = stdout.decode("utf-8", errors="strict")
    # Step 1: sha256sum line を末尾から分離
    docker_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        # sha256sum line (hex + 2 space + path) は skip
        if re.match(r"^[0-9a-f]{64}\s\s", stripped):
            continue
        docker_lines.append(line)
    docker_text = "\n".join(docker_lines).strip()

    services: list[dict[str, object]] = []
    if not docker_text:
        return services
    # Step 2: try JSON array first (Docker 公式仕様)
    if docker_text.startswith("["):
        try:
            arr = json.loads(docker_text)
            if isinstance(arr, list):
                return [s for s in arr if isinstance(s, dict)]
        except json.JSONDecodeError:
            pass
    # Step 3: NDJSON fallback (older Docker compose)
    for line in docker_text.splitlines():
        line_stripped = line.strip()
        if not line_stripped:
            continue
        try:
            obj = json.loads(line_stripped)
            if isinstance(obj, dict):
                services.append(obj)
        except json.JSONDecodeError:
            continue
    return services


def _extract_remote_compose_file_sha256(stdout: bytes) -> str | None:
    """末尾 sha256sum line から hex を抽出."""
    text = stdout.decode("utf-8", errors="strict")
    for line in text.splitlines():
        m = re.match(r"^([0-9a-f]{64})\s\s+(.+)$", line.strip())
        if m:
            return m.group(1)
    return None


# --- main query function ---


_STDOUT_MAX_BYTES = 64 * 1024
_SAFE_DOWN_STATES = frozenset({"exited", "dead"})
_RUNNING_STATE = "running"
_TRANSITIONAL_STATES = frozenset({"paused", "restarting", "created", "removing"})


def query_remote_compose_status(opts: RemoteStatusOptions) -> RemoteStatusResult:
    """SSH 経由で旧 host の docker compose service status を取得.

    invariants:
    - opts.remote_host は signed config の hosts dict にある
    - compose_project / compose_file は signed config から取得 (env から取得しない)
    - SSH StrictHostKeyChecking=yes / BatchMode=yes 強制
    - stdout > 64 KiB は stdout_oversize で reject
    - state machine: running / safe_down{exited,dead} / transitional / unknown
    """
    # 1. signed config load
    cfg_result = load_remote_hosts_signed_config()
    if cfg_result.reason_code != "config_ok":
        return RemoteStatusResult(
            reason_code=cfg_result.reason_code,
            host=opts.remote_host,
            services_up=(),
            services_down=(),
            raw_stdout_size_bytes=0,
            split_brain_safe=False,
        )
    if opts.remote_host not in cfg_result.hosts:
        return RemoteStatusResult(
            reason_code="remote_status_invalid_host",
            host=opts.remote_host,
            services_up=(),
            services_down=(),
            raw_stdout_size_bytes=0,
            split_brain_safe=False,
        )
    host_config = cfg_result.hosts[opts.remote_host]

    # 2. SSH argv 構築 + exec
    try:
        argv = _build_ssh_argv(
            opts.remote_host, host_config.compose_project, host_config.compose_file,
            opts.ssh_timeout_sec,
        )
    except ValueError:
        return RemoteStatusResult(
            reason_code="remote_status_invalid_host",
            host=opts.remote_host,
            services_up=(), services_down=(),
            raw_stdout_size_bytes=0, split_brain_safe=False,
        )
    # ADV PR R2 F-001 adopt: stdout を tempfile に stream (subprocess が直接 file に書込、
    # Python memory に full bytes を load しない)、その後 size enforce
    import tempfile
    stdout_size: int = 0
    stdout_bytes: bytes = b""
    try:
        with tempfile.TemporaryFile(mode="w+b") as stdout_tmp:
            result = run_safe_subprocess(
                argv,
                config=SafeSubprocessConfig(
                    timeout_sec=opts.ssh_timeout_sec + 5,
                    capture_stdout=False,
                    stdout_file=stdout_tmp,
                ),
            )
            stdout_tmp.seek(0, 2)
            stdout_size = stdout_tmp.tell()
            if stdout_size > _STDOUT_MAX_BYTES:
                return RemoteStatusResult(
                    reason_code="remote_status_stdout_oversize",
                    host=opts.remote_host,
                    services_up=(), services_down=(),
                    raw_stdout_size_bytes=stdout_size,
                    split_brain_safe=False,
                )
            stdout_tmp.seek(0)
            stdout_bytes = stdout_tmp.read(_STDOUT_MAX_BYTES + 1)
    except SubprocessTimeoutError:
        return RemoteStatusResult(
            reason_code="remote_status_ssh_timeout",
            host=opts.remote_host,
            services_up=(), services_down=(),
            raw_stdout_size_bytes=0, split_brain_safe=False,
        )
    except SubprocessNotFoundError:
        return RemoteStatusResult(
            reason_code="remote_status_ssh_failed",
            host=opts.remote_host,
            services_up=(), services_down=(),
            raw_stdout_size_bytes=0, split_brain_safe=False,
        )

    # ADV PR R2 F-001 adopt: stdout は既に streaming で tempfile に書込済、size enforce 済

    stderr_text = result.stderr_sanitized

    # 3. exit code 解釈
    if result.returncode == 255:
        if "Host key verification failed" in stderr_text or "REMOTE HOST IDENTIFICATION HAS CHANGED" in stderr_text:
            return RemoteStatusResult(
                reason_code="remote_status_ssh_host_key_untrusted",
                host=opts.remote_host,
                services_up=(), services_down=(),
                raw_stdout_size_bytes=len(stdout_bytes),
                split_brain_safe=False,
            )
        if "Permission denied" in stderr_text or "publickey" in stderr_text:
            return RemoteStatusResult(
                reason_code="remote_status_ssh_auth_failed",
                host=opts.remote_host,
                services_up=(), services_down=(),
                raw_stdout_size_bytes=len(stdout_bytes),
                split_brain_safe=False,
            )
        return RemoteStatusResult(
            reason_code="remote_status_ssh_failed",
            host=opts.remote_host,
            services_up=(), services_down=(),
            raw_stdout_size_bytes=len(stdout_bytes),
            split_brain_safe=False,
        )
    if result.returncode == 127:
        return RemoteStatusResult(
            reason_code="remote_status_compose_unavailable",
            host=opts.remote_host,
            services_up=(), services_down=(),
            raw_stdout_size_bytes=len(stdout_bytes),
            split_brain_safe=False,
        )
    if result.returncode != 0:
        return RemoteStatusResult(
            reason_code="remote_status_ssh_failed",
            host=opts.remote_host,
            services_up=(), services_down=(),
            raw_stdout_size_bytes=len(stdout_bytes),
            split_brain_safe=False,
        )

    # 4. compose_file sha256 verify (ADV R1 F-009 adopt)
    remote_sha256 = _extract_remote_compose_file_sha256(stdout_bytes)
    if remote_sha256 != host_config.compose_file_sha256:
        return RemoteStatusResult(
            reason_code="remote_status_remote_identity_unverified",
            host=opts.remote_host,
            services_up=(),
            services_down=tuple(sorted(host_config.expected_services)),
            raw_stdout_size_bytes=len(stdout_bytes),
            split_brain_safe=False,
        )

    # 5. compose ps json parse
    try:
        services_data = _parse_compose_ps_json(stdout_bytes)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return RemoteStatusResult(
            reason_code="remote_status_compose_output_malformed",
            host=opts.remote_host,
            services_up=(), services_down=(),
            raw_stdout_size_bytes=len(stdout_bytes),
            split_brain_safe=False,
        )

    # 6. exact set match (R1 F-006 + R2 F-003 adopt)
    actual_services: set[str] = set()
    for s in services_data:
        name = s.get("Service") or s.get("Name")
        if isinstance(name, str) and name:
            actual_services.add(name)
    expected_set = set(host_config.expected_services)

    if actual_services != expected_set:
        return RemoteStatusResult(
            reason_code="remote_status_remote_identity_unverified",
            host=opts.remote_host,
            services_up=(),
            services_down=tuple(sorted(expected_set)),
            raw_stdout_size_bytes=len(stdout_bytes),
            split_brain_safe=False,
        )

    # 7. state machine (ADV R1 F-003 adopt)
    running_set: set[str] = set()
    safe_down_set: set[str] = set()
    transitional_set: set[str] = set()
    unknown_set: set[str] = set()
    for s in services_data:
        name_obj = s.get("Service") or s.get("Name")
        if not isinstance(name_obj, str) or not name_obj:
            continue
        state_obj = s.get("State")
        state = state_obj.lower() if isinstance(state_obj, str) else ""
        if state == _RUNNING_STATE:
            running_set.add(name_obj)
        elif state in _SAFE_DOWN_STATES:
            safe_down_set.add(name_obj)
        elif state in _TRANSITIONAL_STATES:
            transitional_set.add(name_obj)
        else:
            unknown_set.add(name_obj)

    if transitional_set or unknown_set:
        return RemoteStatusResult(
            reason_code="remote_status_state_unknown",
            host=opts.remote_host,
            services_up=tuple(sorted(running_set)),
            services_down=tuple(sorted(safe_down_set)),
            raw_stdout_size_bytes=len(stdout_bytes),
            split_brain_safe=False,
        )

    running_services = tuple(sorted(running_set))
    safe_down_services = tuple(sorted(safe_down_set))

    if not running_services and len(safe_down_services) == len(expected_set):
        return RemoteStatusResult(
            reason_code="remote_status_ok_down",
            host=opts.remote_host,
            services_up=running_services,
            services_down=safe_down_services,
            raw_stdout_size_bytes=len(stdout_bytes),
            split_brain_safe=True,
        )
    if len(running_services) == len(expected_set):
        return RemoteStatusResult(
            reason_code="remote_status_all_up",
            host=opts.remote_host,
            services_up=running_services,
            services_down=(),
            raw_stdout_size_bytes=len(stdout_bytes),
            split_brain_safe=False,
        )
    return RemoteStatusResult(
        reason_code="remote_status_partial_up",
        host=opts.remote_host,
        services_up=running_services,
        services_down=safe_down_services,
        raw_stdout_size_bytes=len(stdout_bytes),
        split_brain_safe=False,
    )


__all__ = [
    "ReasonCode",
    "RemoteHostConfig",
    "RemoteHostsConfigLoadResult",
    "RemoteStatusOptions",
    "RemoteStatusResult",
    "_build_ssh_argv",
    "_parse_compose_ps_json",
    "_validate_compose_file_path",
    "load_remote_hosts_signed_config",
    "query_remote_compose_status",
]
