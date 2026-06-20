"""SECRET_URI_PATTERN (uri_pattern.py) の grammar + 5+source drift guard (no-DB)。

ADR-00058: backend を secret://(sops|local)/... へ additive 拡張。単一定数を runtime source とし、
migration は revision 固定 literal を hardcode する。本 test は両者の exact 一致を CI 強制する。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from backend.app.services.secrets.uri_pattern import (
    SECRET_BACKENDS,
    SECRET_SCOPES,
    SECRET_URI_PATTERN,
    SecretUriError,
    build_secret_uri,
    is_valid_secret_uri,
    parse_secret_uri,
    secret_uri_backend,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_0049 = _REPO_ROOT / "migrations" / "versions" / "0049_secret_uri_local_backend.py"


def test_backends_and_scopes_exact_set() -> None:
    assert set(SECRET_BACKENDS) == {"sops", "local"}
    assert set(SECRET_SCOPES) == {
        "p0",
        "workspace",
        "project",
        "repo",
        "agent_run",
        "provider",
    }


@pytest.mark.parametrize("backend", ["sops", "local"])
@pytest.mark.parametrize("scope", list(SECRET_SCOPES))
def test_build_and_parse_round_trip(backend: str, scope: str) -> None:
    uri = build_secret_uri(backend, scope, "my-key_1", "v3")
    assert uri == f"secret://{backend}/{scope}/my-key_1#v3"
    assert is_valid_secret_uri(uri)
    assert parse_secret_uri(uri) == (backend, scope, "my-key_1", "v3")
    assert secret_uri_backend(uri) == backend


def test_local_backend_accepted() -> None:
    assert is_valid_secret_uri("secret://local/project/openai#v1")


def test_sops_backend_backward_compatible() -> None:
    assert is_valid_secret_uri("secret://sops/repo/github-app#v9")


@pytest.mark.parametrize(
    "bad",
    [
        "secret://vault/p0/foo#v1",  # 未知 backend
        "secret://local/unknownscope/foo#v1",  # 未知 scope
        "secret://local/p0/Foo#v1",  # 大文字 name
        "secret://local/p0/foo#1",  # v prefix 欠落
        "secret://local/p0/foo",  # version 欠落
        "secret://local/p0//foo#v1",  # 空 name
        "local://p0/foo#v1",  # scheme 違反
        "secret://local/p0/foo#v1 ",  # 末尾空白
        "",
    ],
)
def test_invalid_uris_fail_closed(bad: str) -> None:
    assert not is_valid_secret_uri(bad)
    with pytest.raises(SecretUriError):
        parse_secret_uri(bad)


@pytest.mark.parametrize(
    "backend,scope,name,version",
    [
        ("vault", "p0", "foo", "v1"),  # 未知 backend
        ("local", "bogus", "foo", "v1"),  # 未知 scope
        ("local", "p0", "Foo", "v1"),  # 大文字 name
        ("local", "p0", "foo", "1"),  # v prefix 欠落
    ],
)
def test_build_rejects_invalid_components(
    backend: str, scope: str, name: str, version: str
) -> None:
    with pytest.raises(SecretUriError):
        build_secret_uri(backend, scope, name, version)


def test_unknown_backend_dispatch_fail_closed() -> None:
    with pytest.raises(SecretUriError):
        secret_uri_backend("secret://vault/p0/foo#v1")


def _load_migration_literal() -> str:
    spec = importlib.util.spec_from_file_location("_mig0049", _MIGRATION_0049)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(module.SECRET_URI_FORMAT_LITERAL)


def test_migration_literal_matches_runtime_pattern_no_drift() -> None:
    """5+source drift guard: migration 0049 の固定 literal == current SECRET_URI_PATTERN。

    SECRET_URI_PATTERN を変えたら本 test が落ちる。固定 literal を書き換えるのではなく、新 migration を
    追加する規律 (migration 不変性、ADR-00058 境界批評 R4)。
    """
    assert _load_migration_literal() == SECRET_URI_PATTERN
