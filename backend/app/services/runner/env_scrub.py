"""Sprint 7 BL-0076: env scrub (forbidden var set + pattern + audit helper).

DD-06 SecretBroker boundary: raw secret は AI / runner / artifact / log /
audit に出さない invariant を runner env 入口で再強制する。

P0 design:

- ``_FORBIDDEN_ENV_NAMES``: hardcode 50+ var (Sprint 6 launcher と同等 +
  Sprint 7 で code-loading / credential-adjacent / shell-startup を追加)
- ``_FORBIDDEN_PATTERNS``: regex で ``*_TOKEN`` / ``*_KEY`` / ``*_SECRET`` /
  ``*_PASSWORD`` / ``*_CREDENTIALS`` / ``*_PRIVATE_KEY`` を fail-closed
- ``scrub_env(allowlist, base_env)``: allowlist 通過した env から forbidden
  を差し引いて返す。``scrubbed_keys`` (audit payload 用) も返す。
- raw secret 値は scrub_result に含めない (key 名のみ audit)

server-owned-boundary §1:

- caller-supplied env は ``env_allowlist: frozenset[str]`` のみ受け取り、
  実 value は server-side ``os.environ`` から resolve。caller が任意
  key=value を直接渡せない。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Final

# Codex R1 F-004 adopt: drift 防止 (Sprint 6 + Sprint 7 batch 2 で 70+ 種に拡張)
_FORBIDDEN_ENV_NAMES: Final[frozenset[str]] = frozenset(
    {
        # Provider keys
        "OPENAI_API_KEY",
        "OPENAI_ORG_ID",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "HUGGINGFACE_TOKEN",
        "HF_TOKEN",
        # GitHub
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GITHUB_APP_PRIVATE_KEY",
        "GITHUB_INSTALLATION_TOKEN",
        # Tailscale / SOPS / age
        "TAILSCALE_AUTHKEY",
        "SOPS_AGE_KEY",
        "SOPS_AGE_KEY_FILE",
        "AGE_PRIVATE_KEY",
        "AGE_SECRET_KEY",
        # AWS / GCP / Azure (subprocess via cloud SDK)
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_ACCESS_KEY_ID",
        "AZURE_CLIENT_SECRET",
        "AZURE_TENANT_ID",
        # DB
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
        "REDIS_URL",
        "TASKMANAGEDAI_DATABASE_URL",
        # Stripe / Slack / 3rd party
        "STRIPE_KEY",
        "STRIPE_SECRET_KEY",
        "SLACK_TOKEN",
        "SLACK_WEBHOOK_URL",
        # JWT / Supabase
        "JWT_SECRET",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_ANON_KEY",
        # Code-loading hijack (Python / shell / dyld / git)
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONHOME",
        "BASH_ENV",
        "ENV",
        "ZDOTDIR",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "DYLD_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_FALLBACK_LIBRARY_PATH",
        # SSH / Git config injection
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_EXEC_PATH",
        "GIT_SSH",
        "GIT_SSH_COMMAND",
        # Codex R1 F-004 adopt: container / orchestration credential paths
        "KUBECONFIG",
        "DOCKER_CONFIG",
        "DOCKER_HOST",
        "DOCKER_CERT_PATH",
        "DOCKER_TLS_VERIFY",
        "DOCKER_AUTH_CONFIG",
        # Codex R1 F-004 adopt: package manager credential / index hijacking
        "NPM_CONFIG_USERCONFIG",
        "NPM_CONFIG_REGISTRY",
        "NPM_TOKEN",
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_CONFIG_FILE",
        "CARGO_HOME",
        "CARGO_NET_GIT_FETCH_WITH_CLI",
        "CARGO_REGISTRIES_CRATES_IO_TOKEN",
        "RUBYGEMS_HOST",
        "BUNDLE_RUBYGEMS__ORG",
        "MAVEN_OPTS",
        # Codex R1 F-004 adopt: Helm / Terraform / etc.
        "HELM_DRIVER_SQL_CONNECTION_STRING",
        "TF_VAR_AWS_ACCESS_KEY_ID",
        "TF_VAR_AWS_SECRET_ACCESS_KEY",
        "VAULT_TOKEN",
        "VAULT_ADDR",
        # Codex R1 F-004 adopt: agent / GPG / DBus
        "GPG_AGENT_INFO",
        "GPG_TTY",
        "DBUS_SESSION_BUS_ADDRESS",
        "DBUS_STARTER_ADDRESS",
        # Codex R1 F-004 adopt: BuildKit / docker buildx
        "BUILDX_BAKE_KEY",
        "BUILDKIT_HOST",
        # Codex R1 F-004 adopt: cloud CLI configurations
        "AWS_PROFILE",
        "AWS_SHARED_CREDENTIALS_FILE",
        "GOOGLE_CLOUD_PROJECT",
        "GCLOUD_PROJECT",
    }
)

# Pattern-based fail-closed (caller が unknown var 渡しでも secret-like なら deny)
# Codex R1 F-004 adopt: pattern を *_KEY / *_PWD / *_OAUTH / *_DEPLOY_KEY /
# *_SIGNING_KEY / *_PRIVATE_KEY / camelCase token/key/secret/password まで拡張
_FORBIDDEN_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r".*_TOKEN$", re.IGNORECASE),
    re.compile(r".*_API_KEY$", re.IGNORECASE),
    re.compile(r".*_KEY$", re.IGNORECASE),  # Codex F-004: GITHUB_DEPLOY_KEY 等
    re.compile(r".*_SECRET$", re.IGNORECASE),
    re.compile(r".*_SECRET_KEY$", re.IGNORECASE),
    re.compile(r".*_PASSWORD$", re.IGNORECASE),
    re.compile(r".*_PASSWD$", re.IGNORECASE),
    re.compile(r".*_PWD$", re.IGNORECASE),  # Codex F-004: DB_PWD 等
    re.compile(r".*_CREDENTIALS$", re.IGNORECASE),
    re.compile(r".*_PRIVATE_KEY$", re.IGNORECASE),
    re.compile(r".*_AUTH(?:KEY|_KEY)?$", re.IGNORECASE),
    re.compile(r".*_BEARER(?:_TOKEN)?$", re.IGNORECASE),
    re.compile(r".*_OAUTH(?:_TOKEN)?$", re.IGNORECASE),  # Codex F-004: OIDC_OAUTH 等
    re.compile(r".*_DEPLOY_KEY$", re.IGNORECASE),
    re.compile(r".*_SIGNING_KEY$", re.IGNORECASE),
    # camelCase (serviceToken, apiKey, etc.) - secret-like substring without underscore
    # Codex F-004: serviceToken, apiKey 等の camelCase は UPPER convention 違反だが
    # 現実の env に混入するため検出する
    re.compile(r".*[a-z](?:Token|Key|Secret|Password|Credential|Bearer)s?$"),
)


@dataclass(frozen=True, slots=True)
class EnvScrubResult:
    """env scrub の戻り値。

    - ``env``: subprocess に渡す scrubbed dict
    - ``scrubbed_keys``: caller が allowlist に入れたが scrub された key 名
      (audit payload 用、value は含めない)
    - ``allowlist_missed_keys``: caller が allowlist に入れたが os.environ に
      存在しなかった key 名 (drift 検知用)
    """

    env: dict[str, str]
    scrubbed_keys: tuple[str, ...]
    allowlist_missed_keys: tuple[str, ...]


def is_forbidden_env_name(name: str) -> bool:
    """Check whether env var name is forbidden by hardcode set or pattern."""
    if name in _FORBIDDEN_ENV_NAMES:
        return True
    return any(p.match(name) for p in _FORBIDDEN_PATTERNS)


def scrub_env(
    env_allowlist: frozenset[str],
    base_env: dict[str, str] | None = None,
    *,
    inject_path: bool = True,
) -> EnvScrubResult:
    """Return scrubbed env from ``base_env`` filtered by ``env_allowlist``.

    Args:
        env_allowlist: caller-specified env var names to keep
        base_env: source env dict (None = ``os.environ``)
        inject_path: prepend safe PATH if not in allowlist (default True)
    """
    if base_env is None:
        base_env = dict(os.environ)

    env: dict[str, str] = {}
    scrubbed: list[str] = []
    missed: list[str] = []

    for name in env_allowlist:
        if is_forbidden_env_name(name):
            scrubbed.append(name)
            continue
        if name not in base_env:
            missed.append(name)
            continue
        env[name] = base_env[name]

    if inject_path and "PATH" not in env:
        env["PATH"] = "/usr/bin:/bin"

    return EnvScrubResult(
        env=env,
        scrubbed_keys=tuple(sorted(scrubbed)),
        allowlist_missed_keys=tuple(sorted(missed)),
    )


__all__ = [
    "EnvScrubResult",
    "is_forbidden_env_name",
    "scrub_env",
]
